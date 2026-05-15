# LangChain Agent 架构设计 — 外汇交易智能查询

## 概述

在现有 Smart BI 架构（llm_parser + gatekeep + TradeQueryBuilder）基础上，引入 LangChain Agent（LangGraph）作为顶层编排层。Agent 负责意图理解、多工具编排、自我检查和结果验证，但 **SQL 生成完全锁死在现有的 TradeQueryBuilder 路由节点中，LLM 不能触碰 SQL**。

## 设计原则

1. **准确性优先** — 所有 SQL 生成基于确定性知识库（query_builder.py），LLM 不参与 SQL 构建
2. **规则引擎兜底** — Agent 思考输出必须经过 gatekeep 校验，规则永远是最终权威
3. **可审计** — LangGraph State 完整记录每一轮思考和工具调用
4. **渐进增强** — 不破坏现有 `/api/query` 和 `/api/parse` 端点

## 角色边界

| 角色 | 职责 | 不可触及 |
|------|------|----------|
| LLM / Agent | 理解自然语言、提取参数、选择路径、判断是否需要图表 | 生成 SQL、访问 DB schema、绕过 gatekeep |
| 规则引擎 gatekeep | 校验和修正 Agent 的输出、强制执行铁律 | — |
| TradeQueryBuilder | 根据 params 生成确定的 Oracle SQL | — |
| 可视化 ECharts Builder | 根据查询结果生成图表配置 | — |

## 架构总览

```
用户查询
    │
    ▼
┌─────────────────────────────────────────────────┐
│              LangGraph Agent                     │
│                                                  │
│  ┌──────────┐  思考循环    ┌──────────────┐     │
│  │ agent    │ ──────────► │ reflect_node │     │
│  │ _parse   │  检查修正    │ (自我检查)    │     │
│  └────┬─────┘             └──────┬───────┘     │
│       │                          │              │
│       ▼                          ▼              │
│  ┌──────────────────────────────────────┐       │
│  │         route_sql (确定性路由)        │       │
│  │  hedge_ratio → build_hedge_ratio    │       │
│  │  top_n → build_ranking              │       │
│  │  amount_filter → build_filtered      │       │
│  │  aggregate → build_aggregate         │       │
│  │  else → build_query                  │       │
│  └──────────────────────────────────────┘       │
│       │                                          │
│       ▼                                          │
│  ┌──────────┐  回测验证   ┌──────────────┐     │
│  │ agent    │ ──────────► │ verify_node  │     │
│  │ _execute │  合理性检查  │ (结果验证)    │     │
│  └────┬─────┘             └──────┬───────┘     │
│       │                          │              │
│       ▼                          ▼              │
│  ┌──────────┐  学习记录   ┌──────────────┐     │
│  │ chart/   │             │ learn_node   │     │
│  │ compare  │             │ (记忆积累)    │     │
│  └──────────┘             └──────────────┘     │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │ AgentMemory (Pattern Store)              │   │
│  │  交互模式记录 → 后续查询参考              │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

## Agent State

```python
class AgentState(TypedDict):
    query_text: str                    # 用户原始查询
    pre_parsed_params: Optional[dict]  # 前端确认卡参数（跳过解析）
    messages: list                     # ReAct 消息历史
    
    # 解析阶段
    validated_params: Optional[dict]   # gatekeep 校验后的最终参数
    pipeline: str                      # "agent" | "direct"
    
    # SQL 阶段（由 route_sql 填充，Agent 不可见）
    sql: Optional[str]
    
    # 执行阶段
    columns: list[str]
    rows: list[list]
    row_count: int
    
    # 比较和可视化
    comparison: Optional[dict]
    visualization: Optional[dict]
    
    # 控制
    retry_count: int                   # 重试次数
    error: Optional[str]
```

## Agent Tools（Agent 可调用的 4 个工具）

### 1. parse_query
- **封装**: `llm_parse()` + `gatekeep()` / `rule_based_parse()`
- **输入**: `text: str`
- **输出**: `validated_params: dict`
- **约束**: 输出必须经过 gatekeep 校验

### 2. execute_sql
- **封装**: `get_db()` + cursor.execute
- **输入**: `sql: str`（必须来自 state.sql，由 route_sql 填充）
- **输出**: `(columns, rows)`

### 3. compute_comparison
- **封装**: `_compute_comparison()` + `_build_comparison_sql()`
- **输入**: `params, sql, rows, comparison_type`
- **输出**: `comparison_data: dict`

### 4. generate_chart
- **封装**: 新模块 `visualization/echarts_builder.py`
- **输入**: `columns, rows, query_text`
- **输出**: `echarts_option: dict`

## Graph 节点

### agent_parse（思考节点）
ReAct 循环，Agent 在此节点理解用户意图，调用 `parse_query` 工具。思考链示例：
```
用户: "工商银行近3个月远期结汇交易量排名"
思考: 1) ranking → top_n=10  2) 远期结汇 → product_type=fwd, buy_sell=B  
      3) 近3个月 → date推算  4) 交易量 → aggregate=true
→ 调用 parse_query
```

### reflect_node（检查节点）
内置确定性逻辑检查，无需 LLM：
- `product_type` ∈ {all, spot, fwd, swap}
- `date_start <= date_end`
- `cust_name` 和 `bank_name` 互斥
- `appid` 与 `buy_sell` 匹配（结售汇 appid=2）
- 参数完整性校验

不通过 → state.error 设值，回退到 agent_parse（retry_count++）

### route_sql（确定性路由）
**此节点 LLM 不可见，由代码直接执行**：
```python
def route_sql(params: dict) -> str:
    if params.get("amount_filter"):   return TradeQueryBuilder.build_filtered_query(...)
    if params.get("top_n"):           return TradeQueryBuilder.build_ranking_query(...)
    if params.get("hedge_ratio"):     return TradeQueryBuilder.build_hedge_ratio_query(...)
    if params.get("aggregate"):       return TradeQueryBuilder.build_aggregate_query(...)
    return TradeQueryBuilder.build_query(...)
```

### agent_execute（行动节点）
Agent 调用 `execute_sql` 工具执行 SQL。

### verify_node（回测验证节点）
内置逻辑检查执行结果：
- rows 为空但预期应有数据 → 回退调整参数重试
- 比较期数据量级异常 → 标记警告
- Top N 排名去重检查

### learn_node（学习节点）
记录交互到 AgentMemory（SQLite/JSON 文件）：
```json
{
  "query": "工商银行近3个月远期结汇交易量排名",
  "params": {...},
  "success": true,
  "row_count": 10,
  "timestamp": "2025-05-12T10:00:00"
}
```
后续同类查询时参考历史 pattern，辅助 Agent 更快决策。

## Visualization 模块

```
visualization/
  __init__.py
  echarts_builder.py    # ECharts 配置生成
  chart_detector.py     # 图表类型自动判定
```

### 图表类型判定规则（无 LLM）
| 查询特征 | 图表类型 |
|----------|----------|
| top_n + 单一维度 | bar（柱状图） |
| aggregate + 有维度 | bar / pie |
| comparison（同比/环比） | bar with two series |
| 时间序列趋势 | line |
| 套保率查询 | bar |
| 明细查询 | 无图表（table） |

## API 集成

新增端点在 `app.py`：

```python
@app.post("/api/agent/query")
async def agent_query(request: Request):
    """新端点：走 LangGraph Agent 管道"""
    body = await request.json()
    result = agent_graph.invoke({
        "query_text": body.get("text", ""),
        "pre_parsed_params": body.get("params"),
    })
    # 标准化输出格式（与 /api/query 兼容）
    return {
        "sql": result.get("sql"),
        "params": result.get("validated_params"),
        "columns": result.get("columns", []),
        "rows": result.get("rows", []),
        "row_count": result.get("row_count", 0),
        "comparison": result.get("comparison"),
        "visualization": result.get("visualization"),
        "error": result.get("error", ""),
    }
```

## 错误处理

| 错误场景 | 处理方式 | 重试次数 |
|----------|----------|----------|
| LLM 解析失败 | 回退到 rule_based_parse | 1 |
| gatekeep 校验不通过 | 覆盖参数 | 0（强制） |
| reflect 检查不通过 | 回退 agent_parse | 最多 3 次 |
| SQL 执行异常 | 报错返回 | 0 |
| verify 验证不通过 | 回退 agent_parse | 最多 2 次 |

## 文件结构变更

```
backend/
  sql_engine/
    __init__.py
    agent.py              # Graph 定义和编译
    state.py              # AgentState
    tools.py              # 4 个 Agent 工具定义
    nodes.py              # 各节点函数
    memory.py             # AgentMemory（pattern store）
  visualization/
    __init__.py
    echarts_builder.py    # ECharts 配置生成
    chart_detector.py     # 图表类型判定
  app.py                  # + /api/agent/query 端点
```

## 不涉及的变更

- 不修改 `llm_parser/` 现有逻辑
- 不修改 `db/query_builder.py` 和 `db/connection.py`
- 不修改 `knowledge_base/` 规则文件
- 不修改前端代码（新增端点输出格式与现有 `/api/query` 兼容）
