# Smart BI MCP Phase 2 设计说明书

> 版本：v1.0 | 日期：2026-05-16 | 状态：待实现

---

## 设计原则

1. **并行运行，渐进切换** — 新编排层与现有系统并行，旧 `/api/query` 保留做降级
2. **每步独立可测** — 每个模块可单独验证后再继续
3. **复用现有逻辑** — 不重写 `rule_based_parse`、`gatekeep`、`TradeQueryBuilder`，只封装为 LangGraph Node
4. **先简单后完善** — Router 初始只路由到 BI Agent，后续再扩展

---

## 目录结构

```
backend/langgraph/
├── __init__.py
├── state.py              # LangGraph State 定义
├── graph.py              # 主图 DAG 定义
├── context_resolver.py   # LLM 全历史分析
├── router.py             # 三层门禁路由
├── registry.py           # Agent 注册表
├── agents/
│   ├── __init__.py
│   └── bi_agent.py       # BI Agent 子图
└── validators.py         # SQL Validator + Result Validator
```

新增 MCP 工具放在 `backend/mcp/tools/` 下，每个工具一个文件。
新端点 `POST /api/chat` 挂在 `app.py`。

---

## Step 1：新增 MCP 工具

每个工具遵循与 `oracle_tool.py` 相同的 `register(mcp)` 模式。

### 1.1 load_rules

从 MySQL 规则库加载指定类别的规则。类别: product_type, buy_sell_direction, bank_name, special_states, amount_filter, app_id。

### 1.2 parse_date

从自然语言文本中提取日期范围。返回 {date_start, date_end, display}。底层调用 llm_chat。

### 1.3 detect_entities

从文本中检测银行名、客户名等实体。返回 {banks: [], customers: [], app_ids: []}。底层调用 llm_chat + 规则匹配。

### 1.4 compute_comparison

计算同比/环比数据。从 MySQL 规则引擎复用 compute_comparison_dates。

### 1.5 get_session_context

获取指定 session 最近的 n 轮对话。

### 1.6 save_memory

保存会话记忆到 MySQL memory_summaries。

### 1.7 write_audit_log

写入审计日志（append-only）。审计表结构参照设计文档第 10 节。

### 1.8 check_cache

检查查询结果缓存。当前返回 None（缓存层后续 Phase 4 实现）。

---

## Step 2：LangGraph + BI Agent

### 2.1 State 定义 (state.py)

```python
@dataclass
class AgentState:
    request_id: str
    session_id: str
    user_text: str
    context: list[dict] | None = None
    resolved_params: dict = field(default_factory=dict)
    inherited_fields: list[str] = field(default_factory=list)
    context_confidence: float = 0.0
    needs_confirm: list[str] = field(default_factory=list)
    router_decision: dict = field(default_factory=dict)
    parsed_params: dict = field(default_factory=dict)
    pipeline: str = ""
    sql: str = ""
    sql_validated: bool = False
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    comparison: dict | None = None
    validation_warnings: list[str] = field(default_factory=list)
    summary: str = ""
    chart_option: dict | None = None
    insights: list[dict] = field(default_factory=list)
    error: str = ""
```

### 2.2 BI Agent 子图节点

| 节点 | 复用代码 |
|------|---------|
| parse | rule_based_parse() |
| gatekeep | rules_engine.gatekeep() |
| build_sql | TradeQueryBuilder.* |
| execute | get_db() + cursor |
| build_comparison | app._compute_comparison() |
| format | app._build_summary/chart/insights() |

### 2.3 主图流程

```
用户输入 → Context Resolver → Router → BI Agent 子图 → Result Validator → Response
```

---

## Step 3：Router

### 3.1 Agent 注册表 (registry.py)

初始只有 BI Agent：
- keywords: [交易量, 排名, 套保率, 金额, 笔数, 银行, 客户]
- NOT_capabilities: [预测, 预估, 趋势, 风险, 汇率, 合规]

### 3.2 三层门禁

1. 关键词打分 — 最高分 - 次高分 ≥ 2
2. 实体校验 + NOT_capabilities 硬拒绝
3. 参数完整性 → 标记 confirm

输出: {status: ok|rejected|confirm, agent, confidence, message}

---

## Step 4：Context Resolver

替换 app.py 中现有的 _inherit_dates_from_context()。

LLM 分析最近 20 轮对话，推断继承参数。降级策略：LLM 失败则规则模式（简单取上一轮日期）。

---

## Step 5：Validator

### SQL Validator
- 表名白名单 + 字段名白名单 + 危险关键字检测
- 不替代 TradeQueryBuilder，而是作为第二道防线

### Result Validator
- 空集检查、异常值检测（10σ）、量级校验（>500%）、对比基数校验

---

## Step 6：新端点 /api/chat

```
POST /api/chat { "text": "...", "session_id": "...", "context": [...] }
→ 返回与 /api/query 相同格式（兼容前端 ResultCard）
```

| 端点 | 引擎 | 状态 |
|------|------|------|
| /api/query | 直接调用 parse → execute | 保留（降级）|
| /api/chat | LangGraph 编排 | 新增（主流程）|
| /api/parse | 纯解析（不执行）| 保留 |

---

## 实施顺序

| 步骤 | 内容 | 交付物 |
|------|------|--------|
| 1 | 新增 8 个 MCP 工具 | 每个工具一个文件 |
| 2 | LangGraph 目录 + State + BI Agent 子图 | state.py, bi_agent.py |
| 3 | 主图 + /api/chat 端点 | graph.py, app.py |
| 4 | Router + Agent Registry | router.py, registry.py |
| 5 | Context Resolver | context_resolver.py |
| 6 | SQL Validator + Result Validator | validators.py |
| 7 | 端到端验证 | curl + ResultCard 验证 |

---

## 降级策略

| 组件失败 | 降级行为 |
|---------|---------|
| Context Resolver | 规则模式（简单取上一轮日期）|
| Router | 默认路由到 BI Agent |
| BI Agent | 回退到旧的 /api/query |
| LLM 不可用 | 规则解析 + gatekeep 兜底 |

---

## 风险

| 风险 | 缓解 |
|------|------|
| LangGraph 增加延迟 | 超时控制 + 渐进式 SSE |
| Context Resolver 幻觉 | 降级策略 + needs_confirm |
| Router 误拒绝 | 低置信度走 confirm |
| 迁移期间新旧不一致 | 并线运行，/api/query 为基准 |
