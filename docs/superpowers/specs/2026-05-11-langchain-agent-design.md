# Smart BI → LangChain Agent 重构设计

## 目标

将当前硬编码管道（解析 → 守门 → 构建SQL → 执行）重构为 LangGraph ReAct Agent，实现：

- **自主分析**：Agent 自主规划多步骤分析（查询 → 对比 → 深入下钻）
- **多轮对话**：支持追问、澄清、上下文延续
- **100% 数据准确性**：SQL 由确定性构建器生成，Agent 只传结构化参数

## 技术选型

| 组件 | 选择 | 原因 |
|------|------|------|
| LLM | DeepSeek (ChatOpenAI 兼容) | 已配置，成本低 |
| Agent框架 | LangGraph | ReAct Agent + 持久化会话 |
| 会话持久化 | SqliteSaver | 零依赖，本地文件存储 |
| 工具定义 | @tool 装饰器 | LangChain 原生 |
| API | FastAPI + SSE 流式响应 | 支持逐步展示推理过程 |

## 架构

```
POST /api/chat (SSE流式)
       ↓
LangGraph ReAct Agent
  ├── LLM (DeepSeek via ChatOpenAI)
  ├── Tools
  │   ├── search_knowledge   (检索业务规则)
  │   ├── get_schema          (获取表结构)
  │   ├── query               (执行查询 ← 确定性SQL构建)
  │   └── compare             (同比/环比对比)
  └── SqliteSaver (会话记忆)
       ↓
  Oracle DB
```

## 工具设计

### search_knowledge
- **作用**：搜索业务知识库（产品类型、买卖方向、时间表达式、维度、特殊状态）
- **输入**：关键词或问题
- **输出**：匹配的规则描述
- **确定性**：从 semantic_rules.json 文本检索

### get_schema
- **作用**：获取视图定义、字段名和含义
- **输入**：视图名或字段名（可选）
- **输出**：DDL + 字段注释
- **确定性**：硬编码的 schema 定义，从 db/schema.py 读取

### query
- **作用**：执行聚合/排名/明细查询
- **输入**：结构化参数 {product_type, date_start, date_end, dimension, filters, aggregate, top_n}
- **输出**：{sql, columns, rows, row_count}
- **确定性**：内部使用规则化 SQL 构建器，Agent 不接触 SQL 字符串

### compare
- **作用**：同比/环比对比计算
- **输入**：同 query 的 params + comparison_type ("yoy"|"mom")
- **输出**：{current_period, compare_period, current_amount, compare_amount, change_amount, change_rate}
- **确定性**：日期计算函数 + 两次 query 调用

## 文件结构（改造后）

```
backend/
├── app.py                 # FastAPI: GET /api/chat (SSE流式), GET /api/health
├── agent/
│   ├── __init__.py
│   ├── agent.py           # create_react_agent 定义
│   ├── tools.py           # @tool 定义 (4个工具)
│   ├── prompts.py         # 系统提示词
│   ├── state.py           # SqliteSaver checkpointer 管理
│   └── query_executor.py  # 确定性SQL构建 + 执行
├── db/
│   ├── __init__.py
│   ├── connection.py      # Oracle 连接
│   └── schema.py          # 表结构信息
├── knowledge/
│   └── semantic_rules.json # 业务知识库
└── llm_parser/            # 废弃删除
```

## 前后端交互

### /api/chat (SSE流式)

请求：
```json
{
  "thread_id": "uuid",
  "text": "浙江分公司今年1月份交易量，同比多少"
}
```

SSE事件类型：
```
event: thinking     →  "正在查询浙江分公司今年1月交易数据..."
event: tool_call    →  {"tool": "query", "args": {...}}
event: data         →  {"type": "table", "columns": [...], "rows": [...]}
event: comparison   →  {"type": "comparison", "data": {...}}
event: message      →  "浙江分公司2026年1月交易量6932万美元，同比增长12.5%"
event: done
```

### 废弃端点
- `POST /api/parse` — 不再需要
- `POST /api/query` — 不再需要

## 前端影响

- 对话界面改为 SSE EventSource 消费流式响应
- 逐步展示：思考状态 → 工具调用 → 数据表格 → 对比卡片 → 自然语言小结
- ConfirmCard 不再需要（Agent 自主判断参数）
- 前端改造在 Agent 后端稳定后单独迭代

## 验证标准

1. Agent 能正确理解自然语言查询并调用 query 工具
2. 生成的 SQL 与旧 query_builder 输出一致
3. 同比/环比对比计算结果正确
4. 多轮追问能保持上下文（同一 thread_id）
5. SSE 流式响应前端能正常消费
