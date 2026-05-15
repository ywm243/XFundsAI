# Smart BI MCP 架构改造设计说明书

> 版本：v2.0 | 日期：2026-05-15 | 状态：待实现 | Phase 1/4

---

## 1. 核心原则

```
宁可不做，不能做错。

┌─────────────────────────────────────────┐
│  Router 决策流程图                        │
│                                         │
│  用户输入 → 混合路由打分                   │
│           │                              │
│           ├─ 高置信度(≥阈值) → 路由到Agent │
│           ├─ 中等置信度 → 追问确认          │
│           └─ 低置信度(无匹配) → 拒答        │
│              "抱歉，我不支持这个查询"        │
└─────────────────────────────────────────┘
```

这是银行级项目，输出错误数据的代价远高于"不支持"。整个路由框架的设计以此为最高优先级。

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
| 编排层 | LangGraph 1.1 | Context Resolver（LLM 上下文解析）、Agent 注册、智能路由、串行/并行 DAG 执行、跨 Agent 上下文共享 | 不直接连数据库、不管理前端状态 |
| 工具层 | FastMCP | 暴露 Oracle/MySQL/LLM 为标准工具，LLM 可自主发现和调用 | 不做业务编排、不管理 Agent 生命周期 |

---

## 3. Context Resolver — 上下文解析器

### 3.1 为什么不能简单取上一条

上下文继承必须是 LLM 分析**全部对话**后智能推断，不能机械取最近的 assistant 消息。

```
场景 A：同一主题多轮（应该继承）
  T1: "本月工行交易量"        → { date: 2026-05, bank: "工行" }
  T2: "农行呢"                → 继承 date，只换 bank
  T3: "同比增加多少"           → 继承 T1/T2 的 date+bank，加 comparison
  → LLM 应输出：date=本月, bank=农行, comparison=yoy

场景 B：主题切换（不应继承）
  T1: "本月工行交易量"        → { date: 2026-05, bank: "工行" }
  T2: "美元即期汇率多少"      → 主题切换为汇率，不应继承 bank
  T3: "同比增加多少"           → 这里需要 LLM 判断"同比谁"
  → LLM 应输出：date=本月, comparison=yoy, 但不确定实体 → 返回 confirm

场景 C：跨度继承
  T1: "今年一季度交易量"      → { date: 2026-01~03 }
  T2: "排名前5的银行"         → 继承 date
  T3: "它们的套保率呢"        → 继承 date + 排名银行
  T4: "跟去年同比"             → 继承全部 + comparison
  → LLM 应输出：date=一季度, banks=前5, comparison=yoy

场景 D：指代消解
  T1: "工行和农行本月交易量"  → { banks: ["工行","农行"], date: 本月 }
  T2: "中行呢"                → "呢" 表示"加到对比"，不是替换
  → LLM 应输出：banks=["工行","农行","中行"], date=本月
```

### 3.2 Context Resolver 节点

在编排层中，Router 之前插入一个 Context Resolver 节点：

```
编排层 DAG:
  Gateway Adapter → Context Resolver → Router → Agent(s) → Result Merge
                       │
                       ├─ 输入: session_id, text, full_history (最近 20 轮)
                       ├─ 输出: resolved_params (合并了继承参数的完整参数)
                       └─ 实现: LLM 分析全部历史 → 结构化输出
```

Context Resolver 给 LLM 的系统提示：

```
你是对话上下文分析器。根据完整对话历史，推断当前查询的完整参数。

## 上下文继承规则
1. 如果当前查询的实体/日期/维度为空，向前查找最近的相关轮次
2. 如果中途切换了主题（如从交易量→汇率），不要继承无关参数
3. "呢""它们的""也"等词表示承接上文
4. 不确定的参数留空，不要猜

## 完整对话历史
{history}

## 当前查询
{text}

## 输出 JSON
{ "resolved": { "date_start": "...", "date_end": "...", "bank_name": "...",
                "product_type": "...", "comparison": "...", ... },
  "inherited_fields": ["date_start", "date_end"],  // 哪些字段来自上下文
  "confidence": 0.95,
  "needs_confirm": []  // 需要追问确认的字段
}
```

### 3.3 Context Resolver 输出处理

```
Context Resolver 输出
  │
  ├─ needs_confirm 非空 → 返回前端确认卡
  │   例: ["bank_name"] → "你想看哪家银行的同比？"
  │
  ├─ confidence < 0.8  → LLM 二次确认
  │   例: "同比增加多少" + 历史有银行和汇率两个主题 → 不确定
  │
  └─ confidence >= 0.8 → resolved_params 传给 Router
      Router 做能力校验，通过后传给 Agent
```

---

## 4. 数据流示例

### 4.1 单轮查询

```
用户: "本月工行交易量"

[网关层] → 建立 SSE，转发请求到编排层

[编排层]
  Context Resolver → 无历史，直接解析
  Router → 门禁 1(关键词 BI=3) ✓ → 门禁 2(工行存在) ✓ → 门禁 3(参数齐全) ✓
  BI Agent → 执行查询 → 返回结果

[网关层] → SSE 推送结果
```

### 4.2 多轮上下文继承

```
T1: "本月工行交易量"       → BI 返回数据
T2: "农行呢"               → Context Resolver: 继承 date，bank→农行 → BI 返回
T3: "同比增加多少"          → Context Resolver: 继承 T1/T2 的 date+bank，加 comparison
                              → BI 执行同比对比 → 返回
```

### 4.3 并行查询

```
用户: "对比工行、农行、中行的交易量"

Context Resolver → 拆解为 3 个独立子查询
Router → 每个子查询通过门禁 → 验证零依赖
编排层 DAG:
  ┌─ query("工行") ─┐
  ├─ query("农行") ─┤ → merge → build_summary → 返回
  └─ query("中行") ─┘
```

### 4.4 串行查询

```
用户: "农行本月交易量下降多少，什么原因"

Context Resolver → 拆解为串行步骤
Router → Step 1: BI Agent → { change: -20% }
         Step 2: 风控 Agent(change=-20%) → 原因分析
Fan-in → 合并返回
```

---

## 5. Router 安全决策框架

### 5.1 三层门禁（智能路由）

每个查询必须通过三道门禁才能路由到 Agent 执行：

```
"本月工行交易量"
    │
    ├─ 门禁 1: 关键词匹配
    │   BI 命中 "交易量""工行" → 得分 3
    │   其他 Agent 均为 0
    │   通过：唯一命中 Agent，差距 ≥2
    │
    ├─ 门禁 2: 领域边界校验
    │   系统已知银行列表中有"工商银行" ✓
    │   日期范围在合理区间内 ✓
    │   通过：实体可验证
    │
    ├─ 门禁 3: 参数完整性检查
    │   必要参数齐全（有日期或默认值、有实体或全市场）
    │   通过：可执行
    │
    ▼
  路由到 BI Agent → 执行查询 → 返回真实数据
```

```
"工行最近的异常交易有哪些"
    │
    ├─ 门禁 1: 关键词匹配
    │   BI=1（"交易""工行"），风控=1（"异常"）
    │   ⚠ 差距 0 < 2，不确定
    │
    ├─ 门禁 2: LLM 二次判断
    │   LLM: "这是风控相关查询，需要分析异常模式"
    │   风控得分更高
    │
    ├─ 门禁 3: Agent 能力校验
    │   风控 Agent 已实现？→ 是
    │   需要的数据源可访问？→ 是
    │
    ▼
  路由到风控 Agent
```

```
"帮我预测下个月美元走势"
    │
    ├─ 门禁 1: 关键词匹配
    │   所有 Agent 均为 0-1 分
    │   ⚠ 无明确命中
    │
    ├─ 门禁 2: LLM 判断
    │   LLM: "预测类查询，系统不支持"
    │
    ▼
  Fallback: "抱歉，我目前不支持趋势预测功能。
             可以查询历史交易数据或汇率报价。"
```

### 5.2 并行硬条件

触发并行的三个必要条件，缺一不可：

| 条件 | 说明 |
|------|------|
| ✅ 每个子问题独立通过三层门禁 | 拆开的每个部分都能独立执行 |
| ✅ 子问题之间零依赖 | 共享只读数据不算依赖 |
| ✅ 每个子 Agent 查询范围不超出能力边界 | 对照 `NOT capabilities` 校验 |

**通过示例：**

```
"对比工行、农行、中行本月交易量"
  拆分为 3 个独立子问题：
    ├─ BI("工行本月交易量") → 独立通过门禁 ✓
    ├─ BI("农行本月交易量") → 独立通过门禁 ✓
    └─ BI("中行本月交易量") → 独立通过门禁 ✓
  依赖关系：无 → 可并行
```

**拒答示例：**

```
"对比工行本月和下月预估交易量"
  ├─ BI("工行本月交易量")      → 通过 ✓
  └─ BI("下月预估交易量")      → 拒答，"预估"超出能力
  结论：只执行第一个，提示第二个不支持

"工行交易量和市场情绪分析"
  ├─ BI("工行交易量")          → 通过 ✓
  └─ 情绪分析                   → 拒答，无对应 Agent
  结论：只执行 BI，拒答第二部分
```

### 5.3 串行硬条件

触发串行的三个必要条件：

| 条件 | 说明 |
|------|------|
| ✅ 第一步独立通过门禁 | 不依赖后续步骤 |
| ✅ 第二步依赖第一步的具体字段 | 非模糊依赖，字段名明确 |
| ✅ 第一步输出格式是第二步可消费的 | schema 匹配，无需 LLM 自由格式转换 |

**通过示例：**

```
"农行本月交易量下降了多少，什么原因"
  拆分为 2 个串行步骤：
  Step 1: BI Agent → 查询农行本月交易量 + 同比变化
    输出: { bank: "农行", current: 1200, compare: 1500, change: -20% }
  Step 2: 风控 Agent → 基于 -20% 数据做原因分析
    输入: Step 1 的 { bank, change, rows }
    输出: 原因分析
  ✓ 依赖关系明确，字段匹配
```

**追问确认示例：**

```
"工行为什么交易量下降了"
  Step 1: BI("工行交易量") → 可独立执行 ✓
  Step 2: 风控("分析原因")
    问题：风控需要知道"下降"是对比什么（同比？环比？上月？）
    → 先追问确认，不直接分析
```

### 5.4 Agent 能力声明

每个 Agent 注册时必须声明 `capabilities` 和 `NOT capabilities`：

```python
AGENT_REGISTRY = {
    "BI": {
        "keywords": ["交易量", "排名", "套保率", "金额", "笔数", "银行", "客户"],
        "capabilities": [
            "聚合查询（按月/按银行/按客户/按维度）",
            "排名查询（TopN）",
            "套保率计算",
            "同比环比对比",
            "条件过滤（金额阈值）",
            "交易明细查询",
        ],
        "NOT_capabilities": [
            "预测、预估、趋势分析",
            "风险评估、异常检测",
            "汇率实时报价",
            "客户信用评估",
        ],
        "data_sources": ["Oracle:XF_FX_SPOTTRADE_VIEW", "Oracle:XF_FX_FWDTRADE_VIEW",
                         "Oracle:XF_FX_SWAPTRADE_VIEW", "MySQL:rules"],
        "output_schema": {
            "columns": "list[str]",
            "rows": "list[list]",
            "row_count": "int",
            "comparison": "dict | None",
        },
    },
    "询报价": {
        "keywords": ["汇率", "报价", "点差", "即期", "远期", "掉期"],
        "capabilities": [
            "实时汇率查询",
            "即期/远期/掉期报价",
            "点差查询",
        ],
        "NOT_capabilities": [
            "汇率走势预测",
            "交易建议",
            "套保策略推荐",
        ],
        "data_sources": [],  # 待定
        "output_schema": {},
    },
    "风控": {
        "keywords": ["风险", "异常", "预警", "限额", "超限", "波动"],
        "capabilities": [
            "交易异常检测",
            "限额监控",
            "风险指标计算",
        ],
        "NOT_capabilities": [
            "风险预测模型",
            "信用评级",
            "合规判定",
        ],
        "data_sources": ["Oracle:XF_FX_*_VIEW", "MySQL:rules"],
        "output_schema": {},
    },
    # ... 其余 Agent 同理
}
```

Router 做决策时：
- `keywords` 命中 → 进入门禁 1
- `capabilities` 匹配 → 通过门禁 3
- `NOT_capabilities` 命中 → **直接拒答**，不调 LLM

### 5.5 Router 输出三种状态

```python
# 状态 1: 成功路由
{
    "status": "ok",
    "plan": "single",            # single | parallel | serial
    "agent": "BI",
    "query": "本月工行交易量",
    "confidence": 0.95,
}

# 状态 2: 拒答（超出能力）
{
    "status": "rejected",
    "reason": "out_of_scope",
    "message": "抱歉，我目前不支持预测类查询",
    "suggestions": [
        {"agent": "BI", "query": "本月工行交易量"},
        {"agent": "询报价", "query": "美元即期汇率"},
    ],
}

# 状态 3: 追问确认（中等置信度，需要澄清）
{
    "status": "confirm",
    "reason": "ambiguous",
    "message": "你是想查交易量还是看异常情况？",
    "options": [
        {"agent": "BI", "query": "工行本月交易量"},
        {"agent": "风控", "query": "工行异常交易"},
    ],
}
```

---

## 6. Agent 规划

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

## 7. MCP 工具清单

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

## 8. FastMCP 技术选型

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

## 9. Phase 1 实现范围

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

## 10. 落地节奏

| Phase | 内容 | 产出 |
|-------|------|------|
| Phase 1 | MCP 工具层 — 3 个工具封好 + 挂 FastAPI | MCP Server 可独立运行 |
| Phase 2 | LangGraph 编排层（Context Resolver + Router + BI Agent 迁移） | BI Agent 通过 MCP 工具执行，上下文智能继承 |
| Phase 3 | 接入第二个 Agent（询报价），验证串行/并行/路由 | 多 Agent 协同 |
| Phase 4 | 批量接入剩余 5-6 个 Agent | 完整多 Agent 系统 |

---

## 11. 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| `mcp` SDK 尚在演进 | API 可能变动 | 锁定版本，Phase 1 仅用 `@mcp.tool()` |
| MCP 协议与现有 `/api/*` 并存 | 维护两套接口 | Phase 1 完全独立，互不影响 |
| FastMCP HTTP 模式无 SSE 流式 | 长查询无进度反馈 | Phase 2 通过 LangGraph streaming 解决 |
| LLM 直接执行 SQL | 安全风险 | 工具内部做 SQL 注入校验；后续加查询审批 |
| LLM 幻觉导致错误业务数据 | 银行业务零容忍 | 三层门禁 + NOT capabilities 硬拦截；拒答优于误答 |
| Router 误路由到错误 Agent | 用户得到不相关结果 | 门禁 2 实体校验 + 门禁 3 能力校验双重保障 |
| 并行/串行拆解错误 | 遗漏上下文或错误拼接 | 硬条件校验 + 输出 schema 匹配检查 |
| Agent 能力声明与实际不符 | 静默输出错误 | `NOT capabilities` 为否定清单，命中即拦截 |
