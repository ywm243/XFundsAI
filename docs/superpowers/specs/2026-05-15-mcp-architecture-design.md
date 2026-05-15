# Smart BI MCP 架构改造设计说明书

> 版本：v1.0 | 日期：2026-05-15 | 状态：待实现 | Phase 1/4

---

## 1. 动机

Smart BI 是代客交易系统 AI 项目的第一个 Agent，后续还会有 7-8 个独立 Agent（询报价、风控、合规、客户画像、报表、知识问答等），需要支持串行、并行、智能路由。当前架构 FastAPI 直连数据库、LLM 只做文本解析，不具备多 Agent 编排能力。

MCP（Model Context Protocol）是 Anthropic 发布的 AI 工具调用开放协议，可以让 LLM Agent 以标准化方式发现和调用后端工具。引入 MCP + LangGraph 三层架构，将项目从"单点 BI 查询"升级为"多 Agent 操作系统"。

---

## 2. 总体架构

```
┌─────────────────────────────────────────┐
│                 前端 (Vue)                │
├─────────────────────────────────────────┤
│           FastAPI 网关层（瘦）             │
│    认证 · 会话 · SSE 推送 · 静态文件       │
├─────────────────────────────────────────┤
│       Agent 编排层 (LangGraph)           │
│  智能路由 · 串行/并行 DAG · State · 上下文  │
├──────────┬──────────┬──────────────────┤
│ BI Agent │ 询报价    │ 风控 Agent  ...   │
│          │ Agent    │                  │
├──────────┴──────────┴──────────────────┤
│            MCP 工具层 (FastMCP)          │
│  Oracle查询 · MySQL规则 · LLM调用 · 会话  │
└─────────────────────────────────────────┘
```

### 各层职责

| 层 | 框架 | 做什么 | 不做什么 |
|----|------|--------|---------|
| 网关层 | FastAPI | 认证、会话管理、SSE 流式推送、静态文件服务 | 不解析业务、不知道有哪些 Agent、不路由 |
| 编排层 | LangGraph 1.1 | Agent 注册、文本→Agent 智能路由、串行/并行 DAG 执行、跨 Agent 上下文共享 | 不直接连数据库、不管理前端状态 |
| 工具层 | FastMCP | 暴露 Oracle/MySQL/LLM 为标准工具，LLM 可自主发现和调用 | 不做业务编排、不管理 Agent 生命周期 |

---

## 3. 数据流示例

用户连续两轮对话，以"本月工行交易量"→"同比增加多少"为例：

### 第一轮："本月工行交易量"

```
前端 POST /api/chat { message: "本月工行交易量", session_id: "s1" }
  │
  ▼
[网关层] 
  1. 校验 session_id，加载历史上下文
  2. 建立 SSE 通道
  3. 转发 { text, context, session_id } 到编排层
  │
  ▼
[编排层 - Router Node]
  分析文本 → "交易量、工行" → BI=0.9, 询报价=0.0, 风控=0.1
  路由决策 → BI Agent
  │
  ▼
[BI Agent 子图]
  Step 1: MCP.tool.load_rules("all")          → 规则库
  Step 2: 规则解析 "本月工行交易量"             → { bank_name: "工商银行", aggregate: true, date_start: "2026-05-01", date_end: "2026-05-15" }
  Step 3: MCP.tool.build_sql(params)          → Oracle SQL
  Step 4: MCP.tool.oracle_query(sql)          → rows
  Step 5: MCP.tool.build_summary(rows, params) → 自然语言摘要
  │
  ▼
  结果写入 LangGraph State，返回网关层
  │
  ▼
[网关层] SSE 推送结果到前端
```

### 第二轮："同比增加多少"

```
编排层从 State 中读取上一轮的 { date_start: "2026-05-01", date_end: "2026-05-15" }
自动注入到 BI Agent → 不需要用户重复"这个月"
无需日期时 → 网关返回 confirm_date，前端弹确认卡
```

### 并行示例（未来，Phase 3+）

```
用户："对比工行、农行、中行的交易量"
编排层 DAG:
  ┌─ query("工行") ─┐
  ├─ query("农行") ─┤ → merge → build_summary → 返回
  └─ query("中行") ─┘
3 个子任务并行执行，汇总后一次返回
```

---

## 4. Agent 规划

| Agent | 职责 | 状态 |
|-------|------|------|
| Router | 文本语义分析，决定分发给哪个 Agent | 新设计 |
| BI Agent | 外汇交易数据查询、聚合、排名、套保率、同比环比 | 迁移 |
| 询报价 Agent | 实时汇率询价、报价生成 | 待建 |
| 风控 Agent | 交易风险监控、异常检测 | 待建 |
| 合规 Agent | 交易合规检查 | 待建 |
| 客户画像 Agent | 客户交易行为分析 | 待建 |
| 报表 Agent | 定时/条件触发的批量报表 | 待建 |
| 知识问答 Agent | 业务规则、文档问答 | 待建 |
| Fallback Agent | 无法识别时的兜底回复 | 待建 |

每个 Agent 是 LangGraph 的一个子图（subgraph），对外暴露 `invoke(state) → state`。

---

## 5. MCP 工具清单

### Phase 1（本次实现）

| 工具 | 参数 | 返回 | 实现 |
|------|------|------|------|
| `oracle_query` | `sql: str` | `{columns, rows, row_count}` | 复用 `db/connection.py` |
| `mysql_query` | `sql: str` | `list[dict]` | 复用 `db/mysql_store.py` |
| `llm_chat` | `prompt: str` | `str` | 复用 `llm_parser/llm_client.py` |

### Phase 2+（后续扩展）

| 工具 | 参数 | 返回 | 使用者 |
|------|------|------|--------|
| `load_rules` | `category: str` | `rule_list` | 所有 Agent |
| `parse_date` | `text: str` | `{start, end}` | BI、报表 |
| `detect_entities` | `text: str` | `{banks, customers}` | BI、风控、客户画像 |
| `compute_comparison` | `rows, type` | `comparison_data` | BI、报表 |
| `get_session_context` | `session_id, n` | `turns` | 所有 Agent |
| `save_memory` | `session_id, key, value` | - | 所有 Agent |

---

## 6. FastMCP 技术选型

**选型：** `mcp` Python SDK + `FastMCP`

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("SmartBI")

@mcp.tool()
def oracle_query(sql: str) -> dict:
    """查询 Oracle 外汇交易数据库。传入标准 Oracle SQL。"""
    ...

@mcp.tool()
def mysql_query(sql: str) -> list:
    """查询 MySQL 规则库和会话记忆。传入标准 MySQL SQL。"""
    ...

@mcp.tool()
def llm_chat(prompt: str) -> str:
    """调用 DeepSeek LLM 进行文本理解和生成。"""
    ...
```

**挂载到 FastAPI：**

```python
# app.py
app.mount("/mcp", mcp.http_app())
```

**FastMCP 对比直接写 API：**

| 直接写 API | FastMCP |
|-----------|---------|
| 每个工具要写路由、验证、文档 | `@mcp.tool()` 自动生成 schema |
| 前后端耦合 | 标准 MCP 协议，任何 MCP 客户端可调 |
| LLM 无法自动发现工具 | LLM 通过 MCP 协议自动发现和调用 |

**两种传输模式：**

| 模式 | 适用场景 |
|------|---------|
| Streamable HTTP（`/mcp` 端点） | 挂到 FastAPI，前端/外部系统可调 |
| stdio | Claude Code / Cursor 直连调试 |

当前选用 Streamable HTTP。

---

## 7. Phase 1 实现范围

**原则：** 不碰现有代码，新增独立目录，两条线并行运行。

```
backend/
├── app.py              ← 不变，加一行 app.mount("/mcp", ...)
├── db/                 ← 不变
├── llm_parser/         ← 不变
├── memory/             ← 不变
└── mcp/                ← 新增
    ├── __init__.py
    ├── server.py        ← FastMCP 入口
    └── tools/
        ├── __init__.py
        ├── oracle_tool.py    ← @mcp.tool() oracle_query
        ├── mysql_tool.py     ← @mcp.tool() mysql_query
        └── llm_tool.py       ← @mcp.tool() llm_chat
```

**完工标准：**

- `GET /mcp` 返回 MCP Server 信息
- `POST /mcp` 接受 MCP 协议请求
- Claude Code 可通过 MCP 客户端调用 `oracle_query`、`mysql_query`、`llm_chat`
- 现有 `/api/*` 全部正常运行

---

## 8. 落地节奏

| Phase | 内容 | 产出 |
|-------|------|------|
| Phase 1 | MCP 工具层 — 3 个工具封好 + 挂 FastAPI | MCP Server 可独立运行 |
| Phase 2 | LangGraph 编排层 + BI Agent 迁移到 MCP | BI Agent 通过 MCP 工具执行 |
| Phase 3 | 接入第二个 Agent（询报价），验证串行/并行/路由 | 多 Agent 协同 |
| Phase 4 | 批量接入剩余 5-6 个 Agent | 完整多 Agent 系统 |

---

## 9. 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| `mcp` SDK 尚在演进 | API 可能变动 | 锁定版本，Phase 1 仅用 `@mcp.tool()` |
| MCP 协议与现有 `/api/*` 并存 | 维护两套接口 | Phase 1 完全独立，互不影响 |
| FastMCP HTTP 模式无 SSE 流式 | 长查询无进度反馈 | Phase 2 通过 LangGraph streaming 解决 |
| LLM 直接执行 SQL | 安全风险 | 工具内部做 SQL 注入校验；后续加查询审批 |
