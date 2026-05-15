# Smart BI 系统架构设计说明书

> 版本：v1.0 | 日期：2026-05-15 | 状态：已实现

---

## 1. 系统概述

Smart BI 是一个面向外汇交易数据的智能 BI 分析平台，支持用户通过自然语言（中文）查询外汇交易数据。系统将用户的自然语言输入解析为结构化查询参数，经由规则引擎守门后生成 Oracle SQL，执行聚合查询并返回可视化结果。

**核心能力：**
- 自然语言解析：关键词规则引擎 + LLM（OpenAI 兼容接口）双通道解析
- SQL 路由：5 种查询类型（明细 / 聚合 / 排名 / 套保率 / 条件过滤）自动路由
- 数据富化：同比/环比对比计算、自然语言摘要生成、图表配置构造、数据洞察推荐
- 分析类问题：LLM 多步推理，自动规划子查询并合成分析报告
- 规则管理：Admin API 支持规则的 CRUD、预览、热重载和版本回滚
- 多轮对话：AgentMemory 实现会话上下文继承和记忆摘要

**技术栈：**

| 层级 | 技术 |
|------|------|
| 后端框架 | Python 3 + FastAPI 0.115 + uvicorn 0.30 |
| LLM 客户端 | OpenAI Python SDK（兼容阿里云 DashScope / DeepSeek / OpenRouter） |
| 数据源 | Oracle 19c（oracledb 4.0），通过视图层查询 |
| 本地存储 | SQLite（规则持久化 + 会话记忆） |
| 前端框架 | Vue 3 Composition API（`<script setup>`）+ Naive UI 2.40 |
| 图表 | ECharts 5 |
| 构建 | Vite 5 |
| Agent 框架 | LangChain 1.2 + LangGraph 1.1（已依赖，多 Agent 预留） |

---

## 2. 总体架构

### 2.1 系统分层

```
┌─────────────────────────────────────────────────────────┐
│                     前端层 (Vue 3)                        │
│  App.vue (根组件 + 暗色主题)                              │
│  ├─ Sidebar.vue       (多 Agent 导航 + 规则管理入口)       │
│  ├─ WelcomeGuide.vue  (快捷引导卡片)                       │
│  ├─ MessageArea.vue   (消息列表 + 滚动控制)                │
│  │   └─ BotMessage.vue (消息模式分发)                     │
│  │       ├─ ConfirmCard.vue  (参数确认表单)               │
│  │       ├─ ResultCard.vue   (四段式结果卡片)              │
│  │       ├─ ChartView.vue    (ECharts 图表)               │
│  │       └─ InsightPanel.vue (数据洞察推荐)               │
│  ├─ InputArea.vue     (消息输入)                          │
│  └─ AdminRules.vue    (规则管理视图)                       │
├─────────────────────────────────────────────────────────┤
│                      API 层 (FastAPI)                     │
│  app.py (主应用)                                          │
│  ├─ GET  /api/health           健康检查                   │
│  ├─ POST /api/parse            解析 NL → 结构化参数        │
│  ├─ POST /api/query            解析+SQL构建+执行+富化       │
│  ├─ POST /api/analyze          LLM分析（多步推理）         │
│  ├─ POST /api/reload-rules     热重载规则+缓存             │
│  └─ /api/admin/*               规则管理 CRUD              │
│      admin_routes.py                                      │
├─────────────────────────────────────────────────────────┤
│                    解析层 (llm_parser/)                    │
│  parser.py        → 关键词规则解析器（15+ 子模块）         │
│  llm_client.py    → OpenAI 兼容 LLM 客户端                │
│  rules_engine.py  → gatekeep() 守门验证引擎               │
│  prompt_builder.py → build_system_prompt() 提示构建        │
├─────────────────────────────────────────────────────────┤
│                     数据层 (db/)                           │
│  query_builder.py → TradeQueryBuilder（5 种 SQL 路由）    │
│  connection.py    → Oracle 连接（延迟加载 Instant Client） │
│  sqlite_store.py  → SQLite 存储（规则 + 会话 + 记忆）      │
│  config.py        → 数据库配置（env 变量驱动）             │
├─────────────────────────────────────────────────────────┤
│                    记忆层 (memory/)                        │
│  store.py         → AgentMemory（会话 + 轮次 + 摘要）      │
└─────────────────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

```
app.py
  ├── llm_parser/
  │     ├── parser.py          (被 rules_engine 和 prompt_builder 引用)
  │     ├── llm_client.py      (独立，仅调用 OpenAI SDK)
  │     ├── rules_engine.py    (依赖 parser.py, sqlite_store)
  │     └── prompt_builder.py  (依赖 sqlite_store)
  ├── db/
  │     ├── query_builder.py   (独立静态方法类)
  │     ├── connection.py      (依赖 config.py)
  │     ├── sqlite_store.py    (独立，被 rules_engine, prompt_builder, admin_routes 调用)
  │     └── config.py          (仅依赖 os.environ)
  ├── memory/
  │     └── store.py           (依赖 sqlite_store)
  └── admin_routes.py          (依赖 sqlite_store, llm_parser/*)
```

---

## 3. 核心数据流

### 3.1 数据类查询流程（主流程）

```
用户输入 "本月各银行交易量"
    │
    ▼
[App.vue] handleSend(text)
    │
    ├── 分析类检测：正则 /为什么|原因|分析|怎么回事|解释/
    │
    ▼ (非分析类，走数据查询路径)
[api.js] parseQuery(text, context)
    │
    ▼ POST /api/parse
[app.py] api_parse()
    │
    ├── Step 1: rule_based_parse(text) → 规则解析（<1ms，纯 CPU）
    │   ├── _parse_date_range()     → 日期范围（15 级优先级）
    │   ├── _parse_product_type()   → 产品类型（即期/远期/掉期）
    │   ├── _parse_buy_sell()       → 买卖方向（B/S，铁律先行）
    │   ├── _parse_bank_name()      → 银行名称
    │   ├── _parse_cust_name()      → 客户名称
    │   ├── _parse_top_n()          → TopN（支持中文数字）
    │   ├── _parse_aggregate()      → 聚合意图
    │   ├── _parse_hedge_ratio()    → 套保率意图
    │   ├── _parse_amount_filter()  → 金额过滤
    │   ├── _parse_dimension()      → 统计维度
    │   ├── _parse_comparison_modifier() → 同比/环比
    │   ├── _parse_special_states() → 特殊状态
    │   └── _parse_trade_class()    → 交易类别（精确→泛化两遍）
    │
    ├── Step 2: _rule_confidence(text, parsed) → 置信度打分
    │   ├── 日期字段 (权重 1.5)：季度边界校验
    │   ├── 实体字段 (权重 1.0)：银行/客户名称
    │   └── 意图字段 (权重 1.5)：aggregate/hedge_ratio/top_n/amount_filter
    │
    ├── Route A: confidence >= 0.8
    │   └── gatekeep(rule_parsed, text) → 守门校验后直接返回
    │
    ├── Route B: confidence < 0.8
    │   └── llm_parse(text, system_prompt) → LLM 解析
    │       └── gatekeep(llm_result, text) → 守门校验
    │
    └── Route C: LLM 失败
        └── gatekeep(rule_parsed, text) → 规则兜底
    │
    ▼ 返回 { params, pipeline, confidence }
[api.js] executeQuery(params)
    │
    ▼ POST /api/query
[app.py] query()
    │
    ├── Step a: 参数归一化（处理 special_states 格式转换等）
    ├── Step b: SQL 路由
    │   ├── amount_filter? → build_filtered_query()     [HAVING 子句]
    │   ├── top_n > 0?     → build_ranking_query()      [ROWNUM 分页]
    │   ├── hedge_ratio?   → build_hedge_ratio_query()  [套保率公式]
    │   ├── aggregate?     → build_aggregate_query()     [SUM + COUNT]
    │   └── default        → build_query()               [明细行]
    │
    ├── Step c: Oracle 执行
    │   └── get_db() → _ensure_oracle() 延迟加载 Instant Client
    │
    ├── Step d: 同比/环比计算
    │   ├── compute_comparison_dates() → 计算对比期日期
    │   ├── _build_comparison_sql()   → 构建对比 SQL
    │   └── _compute_comparison()     → 计算变化量和变化率
    │
    └── Step e: 结果富化
        ├── _build_summary()      → 自然语言摘要
        ├── _build_chart_option() → ECharts 配置
        └── _build_insights()     → 数据洞察（至少 2 条）
    │
    ▼ 返回 { sql, params, columns, rows, comparison, summary, chartOption, insights }
[App.vue]
    └── ResultCard 渲染（摘要→图表→洞察→数据表 四段式）
```

### 3.2 分析类问题流程

```
用户输入 "为什么交易量下降了"
    │
    ▼ (匹配分析类正则)
POST /api/analyze
    │
    ├── Step 1: LLM 规划阶段
    │   └── 输出 { queries: [{ text, reason }] } 计划
    │
    ├── Step 2: 子查询执行（最多 3 个）
    │   └── 每个子查询走完整的 parse + build + execute 流程
    │
    └── Step 3: LLM 合成阶段
        └── 汇集原始数据 + 子查询结果 → 生成中文分析报告
```

### 3.3 多轮对话流程

```
[App.vue] buildContext()
    │
    ├── 提取最近 4 条消息（user ↔ assistant 配对）
    └── 注入到 build_system_prompt(context) → LLM 上下文
        │
        └── prompt_builder.py 拼接"对话上下文"段落
```

---

## 4. 模块详细设计

### 4.1 解析模块 (`llm_parser/`)

#### 4.1.1 `parser.py` — 关键词规则解析器

**职责：** 将中文自然语言文本解析为结构化参数字典，无需 LLM 依赖，纯规则匹配。

**核心函数 `rule_based_parse(text) -> dict`：**

返回字典包含 14 个字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `product_type` | `"all"\|"spot"\|"fwd"\|"swap"` | 产品类型，默认 `"all"` |
| `date_start` / `date_end` | `str` | 日期范围，格式 `YYYY-MM-DD`，无则空串 |
| `special_states` | `str` | 逗号分隔状态值 `"1,3"` |
| `trade_class` | `str` | 交易类别码（精确→泛化两遍匹配） |
| `buy_sell` | `"B"\|"S"\|""` | 买卖方向 |
| `bank_name` | `str` | 银行名称 |
| `cust_name` | `str` | 客户名称（含 "XX客户" 和 "XX的套保率" 两种模式） |
| `aggregate` | `bool` | 是否聚合查询 |
| `top_n` | `int\|None` | 排名数量（支持中文数字） |
| `amount_filter` | `dict\|None` | 金额过滤条件 `{amount_op, amount_value}` |
| `dimension` | `str` | 统计维度 `bank\|customer\|customer_id\|manager\|manager_name` |
| `hedge_ratio` | `bool` | 是否套保率查询 |
| `appid` | `int\|None` | 业务系统 `1(外汇)\|2(结售汇)` |
| `comparison` | `"yoy"\|"mom"\|""` | 同比/环比 |

**子函数清单（15 个）：**
`_parse_date_range`, `_parse_product_type`, `_parse_buy_sell`, `_parse_bank_name`, `_parse_cust_name`, `_parse_special_states`, `_parse_trade_class`, `_parse_top_n`, `_parse_aggregate`, `_parse_hedge_ratio`, `_parse_amount_filter`, `_parse_dimension`, `_parse_comparison_modifier`, `compute_comparison_dates`, `_rule_confidence`

**关键设计点：**

- 日期解析有 15 级优先级，从精确日期 `YYYY年MM月` 到相对时间 `上月/今年一季度`
- 买卖方向采用"铁律先行"策略：结汇/购汇/售汇为铁律关键词，不可被客户前缀反转
- 置信度打分 `_rule_confidence()` 基于三个维度加权：日期(1.5) + 实体(1.0) + 意图(1.5)，满分 4.0，>0.8 跳过 LLM

#### 4.1.2 `llm_client.py` — LLM 客户端

**职责：** 将自然语言文本发送给 LLM，获取结构化 JSON 解析结果。

**核心函数 `llm_parse(text, system_prompt) -> dict | None`：**

- 读取环境变量 `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`
- 通过 `openai.OpenAI` 创建客户端（兼容 OpenAI API 标准）
- 发送 `temperature=0.1` 的低温度调用，保证解析稳定性
- 超时 30 秒，失败返回 `None`（触发规则兜底）
- 从 LLM 回复中提取 JSON 代码块（支持 markdown 代码块包裹）

**支持的 LLM 供应商：** 阿里云 DashScope、DeepSeek、OpenRouter 等所有 OpenAI 兼容 API。

#### 4.1.3 `rules_engine.py` — 守门验证引擎

**职责：** 在 LLM/规则解析之后，对参数进行校验、补充、互斥处理，确保最终输出的参数安全有效。

**核心函数 `gatekeep(parsed, original_text) -> dict`：**

6 个阶段按序执行：
1. **铁律 buy_sell** — 从 SQLite 加载规则，对 `customer_reversible=false` 的铁律规则强制覆盖
2. **"结售汇"特例** — 自动设 `appid=2, buy_sell=""`
3. **可反转规则 + 客户前缀** — 客户视角方向反转
4. **special_states / trade_class 精确匹配** — 调用 `parser._parse_trade_class` 补充
5. **签约交易检测** — `"签约" in text` → `sign_trade=0`
6. **时间/实体/维度/对比回退** — 补全 LLM 可能遗漏的字段
7. **互斥校验** — `cust_name` 和 `bank_name` 不能同时存在
8. **聚合/套保率检测** — 文本含关键词则置位

**`reload_rules()`** — 清除内存缓存，触发下次请求从 SQLite 重新加载。

#### 4.1.4 `prompt_builder.py` — 系统提示构建

**职责：** 从 SQLite 规则库动态构造 LLM 系统提示（含上下文注入）。

**核心函数 `build_system_prompt(context=None) -> str`：**

- 从 SQLite 加载 5 类规则：`product_type`, `buy_sell_direction`, `time_expressions`, `special_trade_type`, `app_id`
- 渲染为 LLM 可理解的结构化文本
- 包含当前日期、JSON 输出格式约束
- 支持缓存：无会话上下文时缓存一次性构造（避免每次调用都读取 SQLite）
- 支持上下文注入：传入 `context` 参数时拼接多轮对话历史

**`invalidate_cache()`** — 规则变更后清除缓存。

### 4.2 数据库模块 (`db/`)

#### 4.2.1 `query_builder.py` — SQL 构建器

**类：** `TradeQueryBuilder`（全静态方法，无状态）

**常量：**
- `VIEW_MAP` — 产品类型到 Oracle 视图的映射：`spot→XF_FX_SPOTTRADE_VIEW`, `fwd→XF_FX_FWDTRADE_VIEW`, `swap→XF_FX_SWAPTRADE_VIEW`
- `COMMON_FIELDS` — 10 个公共字段列表
- `HEDGE_RATIO_SQL` — 套保率计算公式：`SUM(衍生品金额) / SUM(全部金额) * 100`
- `OP_MAP` — 金额过滤操作符映射：`gt→>`, `gte→>=`, `lt→<`, `lte→<=`

**5 种查询路由方法：**

| 方法 | 用途 | 关键 SQL 特性 |
|------|------|--------------|
| `build_query()` | 明细查询 | CTE + LEFT JOIN XF_BASE_BANK, 无聚合 |
| `build_aggregate_query()` | 聚合统计 | SUM/CAMPCOUNT, 支持多维度 GROUP BY |
| `build_ranking_query()` | 排名查询 | 子查询 + ROWNUM 分页 |
| `build_hedge_ratio_query()` | 套保率分析 | HEDGE_RATIO_SQL 公式, 衍生品金额/笔数 |
| `build_filtered_query()` | 条件过滤 | HAVING 子句, 可选套保率过滤 |

**共享设施：**
- `_build_cte(bank_name)` — 银行名称模糊搜索 CTE，含 SQL 注入防护（单引号、百分号、下划线转义）
- `_build_where_conditions(...)` — 公共 WHERE 条件构建（TRADESTATUS=0, APPID, 日期范围, BUYORSELL, etc.）
- `_build_from(product_type)` — UNION ALL 多视图
- `_group_cols(dimension)` — 5 种维度的 GROUP BY 映射
- `_join_clause(dimension)` — 仅 bank 维度做 JOIN XF_BASE_BANK
- 参数校验：`_validate_buy_sell`, `_validate_top_n`(1-100), `_validate_product_type`

#### 4.2.2 `connection.py` — Oracle 连接管理

- **延迟加载**：`_ensure_oracle()` 在首次调用 `get_db()` 时才初始化 `oracledb.init_oracle_client()`
- **平台适配**：Windows 使用 `D:\soft\instantclient\instantclient_19_19`，Linux 使用 `/home/ywm/oracle/instantclient_21_12`
- **上下文管理器**：`get_db()` 返回连接，自动关闭

#### 4.2.3 `sqlite_store.py` — SQLite 存储引擎

**存储位置：** `backend/data/smartbi.db`

**6 张表：**

| 表 | 用途 |
|----|------|
| `rule_categories` | 规则分类（agent_type + category + display_name） |
| `rule_items` | 规则条目（keywords JSON + rule_data JSON + is_ironclad） |
| `rule_versions` | 版本快照（每次修改自动备份） |
| `sessions` | 会话记录 |
| `turns` | 对话轮次（user_query + parsed_params + executed_sql） |
| `memory_summaries` | 记忆摘要 |

**关键特性：**
- 线程安全：所有写操作使用 `threading.Lock`
- WAL 模式：支持并发读
- 自动迁移：首次启动时从 `backend/knowledge_base/semantic_rules.json` 迁移规则到 SQLite
- 规则拆分：旧 JSON 的 `special_states` 和 `trade_class` 合并为 `special_trade_type` 分类，通过 `sub_type` 字段区分
- 热重载：`reload_rules()` 清除内存缓存

#### 4.2.4 `config.py` — 数据库配置

- 环境变量驱动：`DB_HOST`, `DB_PORT`, `DB_SERVICE`, `DB_USER`, `DB_PASSWORD`
- `dsn` 属性：组装为 `host:port/service` 格式

### 4.3 记忆模块 (`memory/`)

#### `store.py` — AgentMemory

**类：** `AgentMemory(agent_type="bi")`

| 方法 | 说明 |
|------|------|
| `ensure_session(session_id)` | 创建/更新会话 |
| `add_turn(session_id, turn_index, user_query, ...)` | 记录一轮对话 |
| `get_context(session_id, last_n=3)` | 获取最近 N 轮对话 |
| `build_context_prompt(session_id, last_n=3)` | 构建上下文提示文本 |
| `get_turn_count(session_id)` | 获取会话轮次数 |
| `should_summarize(session_id)` | 每 5 轮触发摘要 |
| `add_summary(session_id, summary_type, content)` | 存储记忆摘要 |
| `find_similar(query_text, limit=3)` | 关键词重叠检索相似历史查询 |

### 4.4 管理模块 (`admin_routes.py`)

**接口前缀：** `/api/admin`

**10 个端点：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rules/categories` | 列出规则分类（支持 agent_type 过滤） |
| GET | `/rules/categories/{id}/items` | 列出分类下规则条目 |
| POST | `/rules/categories/{id}/items` | 创建规则条目（含校验） |
| PUT | `/rules/items/{id}` | 更新规则条目 |
| DELETE | `/rules/items/{id}` | 软删除规则条目 |
| GET | `/rules/categories/{id}/versions` | 查看版本历史 |
| POST | `/rules/categories/{id}/rollback` | 版本回滚 |
| POST | `/rules/preview` | 规则预览（不保存，测试匹配效果） |
| POST | `/rules/reload` | 热重载所有规则缓存 |
| POST | `/api/reload-rules` | 全局重载端点（app.py 注册） |

**校验规则 `_validate_rule_item()`：**
- 关键词唯一性检查（同类目内不重复）
- 特殊状态值范围检查（仅允许 1,3,4,5）
- 交易类别值范围检查（允许 0-7,10-17）
- 产品类型值检查（仅 spot/fwd/swap/all）
- 买卖方向字段非空检查

---

## 5. 数据库设计

### 5.1 SQLite 表结构

#### `rule_categories` — 规则分类

| 字段 | 类型 | 约束 |
|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| agent_type | TEXT | NOT NULL, CHECK(IN ('common','bi','quoting','risk')) |
| category | TEXT | NOT NULL |
| display_name | TEXT | NOT NULL |
| priority | INTEGER | DEFAULT 0 |
| UNIQUE(agent_type, category) | | |

#### `rule_items` — 规则条目

| 字段 | 类型 | 约束 |
|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| category_id | INTEGER | NOT NULL, FK → rule_categories.id |
| keywords | TEXT | NOT NULL, JSON 数组 |
| rule_data | TEXT | NOT NULL, JSON 对象 |
| is_ironclad | INTEGER | DEFAULT 0（0=可反转, 1=铁律） |
| priority | INTEGER | DEFAULT 0 |
| is_active | INTEGER | DEFAULT 1（0=软删除） |
| created_at | TEXT | DEFAULT NOW |
| updated_at | TEXT | DEFAULT NOW |

#### `rule_versions` — 版本快照

| 字段 | 类型 | 约束 |
|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| category_id | INTEGER | NOT NULL, FK |
| version_num | INTEGER | NOT NULL |
| snapshot | TEXT | NOT NULL, JSON 数组 |
| created_by | TEXT | DEFAULT 'system' |
| created_at | TEXT | DEFAULT NOW |

**自动备份机制：** 每次 `add_item()`、`update_item()`、`delete_item()` 操作前，自动查询 `MAX(version_num)+1` 并保存当前全量快照。

#### `sessions` — 会话

| 字段 | 类型 | 约束 |
|------|------|------|
| id | TEXT | PRIMARY KEY |
| agent_type | TEXT | NOT NULL DEFAULT 'bi' |
| user_id | TEXT | DEFAULT 'default' |
| created_at / updated_at | TEXT | DEFAULT NOW |
| is_active | INTEGER | DEFAULT 1 |

#### `turns` — 对话轮次

| 字段 | 类型 | 约束 |
|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| session_id | TEXT | NOT NULL, FK → sessions.id |
| turn_index | INTEGER | NOT NULL |
| user_query | TEXT | NOT NULL |
| parsed_params | TEXT | JSON, 可空 |
| executed_sql | TEXT | 可空 |
| result_summary | TEXT | 可空 |
| user_feedback | TEXT | 可空 |
| created_at | TEXT | DEFAULT NOW |

#### `memory_summaries` — 记忆摘要

| 字段 | 类型 | 约束 |
|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| session_id | TEXT | FK → sessions.id |
| scope | TEXT | DEFAULT 'session' |
| summary_type | TEXT | NOT NULL |
| content | TEXT | NOT NULL, JSON |
| source_turns | TEXT | 摘要来源轮次范围 |
| embedding_id | TEXT | 向量 ID 预留 |

### 5.2 Oracle 视图层

数据源通过 3 个 Oracle 视图访问：

| 视图 | 对应产品类型 |
|------|-------------|
| `XF_FX_SPOTTRADE_VIEW` | 即期 (spot) |
| `XF_FX_FWDTRADE_VIEW` | 远期 (fwd) |
| `XF_FX_SWAPTRADE_VIEW` | 掉期 (swap) |

查询策略：
- `product_type="all"` → 3 视图 UNION ALL
- 指定类型 → 单视图查询
- 银行名称匹配 → LEFT JOIN `XF_BASE_BANK` 表（DIPNAME LIKE 模糊匹配，含转义防护）

**10 个公共字段：** USDAMOUNT, TRADEDATE, TRADESTATUS, SPECIALSTATE, APPID, BUYORSELL, BANKID, CUSTNAME, CUSTOMERID, CUSTMAINMANAGER, CUSTMANAGERNAME

---

## 6. API 设计

### 6.1 `GET /api/health`

**请求：** 无参数

**响应：** `{"status": "ok"}`

**用途：** 前端启动时检测后端可用性（5 秒超时）。

### 6.2 `POST /api/parse`

**请求：**
```json
{
  "text": "本月工商银行交易量",
  "context": [{"role": "user", "content": "..."}, ...]
}
```

**响应：**
```json
{
  "params": {
    "product_type": "all",
    "date_start": "2026-05-01",
    "date_end": "2026-05-15",
    "bank_name": "工商银行",
    "aggregate": true,
    ...
  },
  "pipeline": "rule(confidence=88%)",
  "confidence": 0.875
}
```

**pipeline 取值：**
- `"rule(confidence=XX%)"` — 规则命中，置信度 >= 80%
- `"llm+gatekeep(rule_confidence=XX%)"` — LLM 解析 + 守门
- `"rule_fallback(confidence=XX%)"` — LLM 失败，规则兜底

### 6.3 `POST /api/query`

**请求：**
```json
{
  "text": "本月交易量",       // 可选，无 params 时走解析
  "params": { ... }           // 可选，前端已确认参数
}
```

**响应：**
```json
{
  "sql": "WITH matched_banks AS (...) SELECT ...",
  "params": { ... },
  "columns": ["机构名称", "TOTAL_AMOUNT", "TRADE_COUNT"],
  "rows": [["工商银行", 12345678.90, 150]],
  "row_count": 1,
  "comparison": {
    "type": "yoy",
    "label": "同比",
    "current_period": "2026-05-01 ~ 2026-05-15",
    "compare_period": "2025-05-01 ~ 2025-05-15",
    "current_amount": 123.45,
    "compare_amount": 100.00,
    "change_amount": 23.45,
    "change_rate": 23.45
  },
  "summary": "2026-05-01 ~ 2026-05-15工商银行交易总量123.46万美元，共150笔。",
  "chartOption": { "_title": "...", "tooltip": {...}, "xAxis": {...}, "series": [...] },
  "insights": [
    {"type": "quality", "title": "交易概览", "detail": "...", "query": "..."},
    {"type": "growth", "title": "排名分布", "detail": "...", "query": "..."}
  ],
  "error": ""
}
```

### 6.4 `POST /api/analyze`

**请求：**
```json
{
  "text": "为什么交易量下降了",
  "context": [...],
  "previous_data": { "columns": ..., "rows": ..., "comparison": ... }
}
```

**响应：**
```json
{
  "summary": "经分析，本月交易量下降的主要原因是..."
}
```

**内部流程：** LLM 规划子查询 → 后端执行（最多 3 个） → LLM 合成分析报告。

### 6.5 `POST /api/reload-rules`

**请求：** 无参数

**响应：** `{"status": "ok", "message": "Rules and prompt cache refreshed"}`

### 6.6 Admin API 端点（详见表）

见 4.4 节管理模块的 10 个端点列表。

---

## 7. 前端组件设计

### 7.1 组件树

```
App.vue (根)
├── NConfigProvider (暗色主题 + 中文 locale)
│   └── NMessageProvider
│       ├── Sidebar.vue
│       │   Props: 无（通过 emit 'navigate' 通信）
│       │   State: expanded (boolean), activeAgent
│       │   Agents: BI Agent / 询报价 Agent / 风控 Agent（后两者预留禁用）
│       │   宽度: 56px → 220px（展开时）
│       │
│       ├── StatusHeader.vue
│       │   Props: status ('checking' | 'connected' | 'disconnected')
│       │
│       ├── [chat 模式]
│       │   ├── WelcomeGuide.vue (messages.length === 0 时显示)
│       │   │   Props: 无
│       │   │   Emits: quickQuery(text)
│       │   │   快捷示例: 6 个（交易量/排名/套保率/趋势/同比/客户维度）
│       │   │
│       │   ├── MessageArea.vue (messages.length > 0 时显示)
│       │   │   Props: messages[]
│       │   │   Emits: confirm(params, idx), reset(idx), quickQuery(text)
│       │   │   └── BotMessage.vue (消息模式分发)
│       │   │       Props: message (Object)
│       │   │       ├── mode='loading'    → NSpin "思考中..."
│       │   │       ├── mode='error'      → NAlert
│       │   │       ├── mode='confirm'    → ConfirmCard.vue
│       │   │       │   Props: params, pipeline, originalText, querying, resetting
│       │   │       │   Emits: confirm(params), reset()
│       │   │       │   表单字段: product_type/date/buy_sell/appid/special_states/
│       │   │       │            bank_name/cust_name/aggregate/top_n/dimension
│       │   │       ├── mode='analysis'   → 纯文本渲染
│       │   │       ├── mode='result'     → ResultPanel.vue
│       │   │       └── mode='result_card'→ ResultCard.vue
│       │   │           Props: data { columns, rows, sql, params, comparison, summary, chartOption, insights }
│       │   │           Emits: quickQuery(text)
│       │   │           四段式: 摘要 → ChartView → InsightPanel → NDataTable/NCode
│       │   │           └── ChartView.vue
│       │   │               Props: option (ECharts 配置对象)
│       │   │           └── InsightPanel.vue
│       │   │               Props: insights[]
│       │   │               Emits: click(query)
│       │   │
│       │   └── InputArea.vue
│       │       Props: disabled
│       │       Emits: send(text)
│       │       Expose: focus()
│       │
│       └── [admin 模式]
│           └── AdminRules.vue
│               API: 通过 fetch('/api/admin/...') 直连
│               功能: 分类列表/条目CRUD/预览/热重载/版本回滚
```

### 7.2 消息流状态机

```
用户输入 text
    │
    ├── 分析类正则匹配?
    │   ├── YES → POST /api/analyze → mode='analysis' (纯文本)
    │   └── NO  → POST /api/parse  → POST /api/query → mode='result_card' (四段式)
    │
    每个新用户消息 → messages.push({ type: 'user', text })
                  → messages.push({ type: 'bot', mode: 'loading' })
                  → 响应后覆盖 bot 消息为对应 mode
```

### 7.3 关键状态管理

- **messages**: `reactive([])` — App.vue 级别状态，所有组件通过 props 读取
- **viewMode**: `ref('chat')` — chat/admin 视图切换
- **connectionStatus**: `ref('checking')` — 后端连接状态
- **context**: 动态构建 — `buildContext()` 从最近 4 条消息提取 user/assistant 配对

---

## 8. 关键设计决策

### 8.1 为什么"规则优先，LLM 补充"？

**决策：** 所有查询先通过 `rule_based_parse()` 进行关键词规则解析，仅当置信度 < 80% 时才调用 LLM。

**理由：**
1. **成本优化** — 规则解析 <1ms 且零成本；LLM 调用每次产生 API 费用
2. **响应速度** — 高频查询（如"本月交易量"）可在 1ms 内完成解析
3. **确定性** — 关键词规则对已知模式 100% 确定，不存在 LLM 幻觉风险
4. **可观测性** — `pipeline` 字段清晰标识每条查询走的是规则还是 LLM 通道
5. **健壮性** — LLM 不可用时（API 未配置、网络故障），规则兜底保证基本功能

**数据验证：** `_rule_confidence()` 三维度加权打分，>= 80% 即认为规则解析可靠。

### 8.2 为什么用 SQLite 而非 Oracle 存储规则？

**决策：** 规则引擎的配置数据存储在本地 SQLite，而非业务数据库 Oracle。

**理由：**
1. **解耦** — 规则管理不依赖 Oracle 可用性；Oracle 仅用于业务数据查询
2. **轻量** — SQLite 零配置、零运维，适合 KB 级别的规则数据
3. **热重载** — 规则变更后通过 `POST /api/admin/rules/reload` 即时生效，无需重启
4. **版本管理** — 内置版本快照机制，支持一键回滚
5. **多 Agent 预留** — `agent_type` 字段支持 common/bi/quoting/risk 多套规则共存

### 8.3 为什么设计四段式结果卡片？

**决策：** `ResultCard.vue` 将查询结果分为四段展示：自然语言摘要 → 图表 → 数据洞察 → 数据表。

**理由：**
1. **渐进式信息披露** — 用户先看到一句话结论，再按需深入图表和数据
2. **引导分析** — 洞察面板提供快捷追问入口（点击即可发起新查询）
3. **技术可追溯** — SQL/参数 tab 保留技术细节，方便排查和数据审计
4. **对比可视化** — 摘要栏直接显示同比/环比变化率，一目了然

### 8.4 为什么 Oracle 连接采用延迟加载？

**决策：** `connection.py` 中的 `_ensure_oracle()` 仅在首次 `get_db()` 调用时初始化 Oracle Instant Client。

**理由：** FastAPI 服务启动时无需 Oracle 可用；`/api/health`, `/api/parse`, `/api/admin/*` 等端点均不依赖 Oracle。延迟加载意味着可以启动服务、管理规则、进行解析测试，而无需 Oracle 环境。

---

## 9. 安全设计

| 层面 | 措施 | 实现位置 |
|------|------|---------|
| SQL 注入防护 | `TradeQueryBuilder` 所有参数通过参数化构建，字符串值做转义处理（`_escape_bank_name` 转义单引号、百分号、下划线、反斜杠） | `db/query_builder.py` |
| 输入长度限制 | 前端 `NInput` maxlength=2000 | `InputArea.vue` |
| buy_sell 校验 | 仅允许 `'B'` / `'S'` / `None`，`_validate_buy_sell` 抛异常拦截非法值 | `db/query_builder.py` |
| top_n 范围校验 | 仅允许 1-100 | `db/query_builder.py` |
| product_type 校验 | 仅允许 `all/spot/fwd/swap` | `db/query_builder.py` |
| 规则管理权限 | Admin API 路径独立 `/api/admin`，前端通过侧边栏隐藏入口（非登录态不可见）/ 目前无认证 | `admin_routes.py` |
| 环境变量隔离 | 数据库凭证、LLM API Key 通过 `.env` 文件加载，不入库 | `config.py`, `.env` |
| LLM 输出校验 | `gatekeep()` 对 LLM 输出做铁律覆盖 + 互斥校验 | `rules_engine.py` |

---

## 10. 扩展性设计

### 10.1 多 Agent 架构预留

当前仅实现 BI Agent，但架构已为多 Agent 场景做好预留：

- **SQLite 规则隔离**：`rule_categories.agent_type` 已定义 `common/bi/quoting/risk` 四种类型
- **前端侧边栏**：`Sidebar.vue` 包含 BI Agent、询报价 Agent、风控 Agent 三个入口（后两者标记 `active: false`）
- **记忆层隔离**：`AgentMemory(agent_type)` 支持按 agent_type 进行会话和记忆隔离
- **规则构建器隔离**：`prompt_builder.py` 从 SQLite 加载时可按 agent_type 过滤

### 10.2 LangChain/LangGraph 依赖预留

`requirements.txt` 已包含 `langchain>=1.2.18`, `langgraph>=1.1.10` 等依赖，为后续升级到 LangChain Agent 架构做好准备。当前解析模块 `llm_parser/` 保持独立，不依赖 LangChain，转换时可平滑迁移。

### 10.3 向量检索预留

`memory_summaries` 表包含 `embedding_id` 字段，`AgentMemory.find_similar()` 方法注释标注了"未来可升级为 Chroma 向量检索"的路径。当前使用关键词重叠度计算相似性。

### 10.4 前端多视图分离

前端 `viewMode` 已经支持 chat/admin 两种模式切换。Admin 规则管理作为独立视图，不影响主聊天界面。

---

## 附录：文件清单

### 后端文件（17 个源文件）

| 文件 | 行数 | 说明 |
|------|------|------|
| `backend/app.py` | ~840 | FastAPI 主应用、5 端点 + 结果富化 |
| `backend/llm_parser/parser.py` | ~670 | 关键词规则解析器 |
| `backend/llm_parser/llm_client.py` | ~105 | OpenAI 兼容 LLM 客户端 |
| `backend/llm_parser/rules_engine.py` | ~180 | 守门验证引擎 |
| `backend/llm_parser/prompt_builder.py` | ~178 | 系统提示构建器 |
| `backend/db/query_builder.py` | ~341 | SQL 构建器（5 种路由） |
| `backend/db/connection.py` | ~51 | Oracle 连接（延迟加载） |
| `backend/db/sqlite_store.py` | ~563 | SQLite 存储（规则+会话+记忆） |
| `backend/db/config.py` | ~14 | 数据库环境配置 |
| `backend/admin_routes.py` | ~257 | 规则管理 Admin API |
| `backend/memory/store.py` | ~129 | 会话记忆持久化层 |
| `backend/requirements.txt` | 11 | Python 依赖清单 |

### 前端文件（13 个源文件）

| 文件 | 说明 |
|------|------|
| `frontend/src/App.vue` | 根组件（布局 + 暗色主题 + 核心逻辑） |
| `frontend/src/main.js` | Vue 应用入口 |
| `frontend/src/api.js` | API 客户端（checkHealth/parseQuery/executeQuery） |
| `frontend/src/constants.js` | 常量（列标签、格式化函数、选项配置） |
| `frontend/src/components/Sidebar.vue` | 侧边栏导航 |
| `frontend/src/components/WelcomeGuide.vue` | 首页快捷引导 |
| `frontend/src/components/StatusHeader.vue` | 连接状态头部 |
| `frontend/src/components/InputArea.vue` | 消息输入区域 |
| `frontend/src/components/MessageArea.vue` | 消息列表区域 |
| `frontend/src/components/BotMessage.vue` | 机器人消息模式分发 |
| `frontend/src/components/ConfirmCard.vue` | 参数确认卡片 |
| `frontend/src/components/ResultCard.vue` | 四段式结果卡片 |
| `frontend/src/components/ChartView.vue` | ECharts 图表容器 |
| `frontend/src/components/InsightPanel.vue` | 数据洞察面板 |
| `frontend/src/components/ResultPanel.vue` | 旧版结果面板（保留） |
| `frontend/src/views/AdminRules.vue` | 规则管理视图 |
