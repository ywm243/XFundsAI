# Smart BI 外汇交易智能查询系统 — 需求规格说明书

> **文档类型：** 需求规格说明书（基于 main 分支已实现功能的反向梳理）
> **版本：** v2.0
> **日期：** 2026-05-14
> **分支：** main（生产分支），feature/langchain-agent（开发分支，单独标注）

---

## 1. 引言

### 1.1 项目背景

外汇交易部门日常需要查询大量交易数据——交易量统计、排名分析、套保率计算等。传统方式需要业务人员手动编写 SQL 或依赖 IT 部门出报表，响应周期长、灵活性差。Smart BI 通过自然语言查询 + AI 解析的方式，让业务人员直接输入中文描述需求，系统自动转化为 SQL 并返回结构化结果。

### 1.2 项目目标（Main 分支已实现）

1. **自然语言查询**：用户输入中文查询语句（如"本月各银行交易量"），系统自动解析意图
2. **智能解析**：LLM（DeepSeek V4 Flash）+ 规则引擎双重保障，确保解析准确性
3. **安全 SQL 生成**：TradeQueryBuilder 参数化构建 Oracle SQL，严禁 LLM 直接生成 SQL
4. **多维分析**：支持明细查询、聚合统计、排名、套保率、金额筛选
5. **同比环比**：自动计算并展示同比（YoY）/ 环比（MoM）对比数据
6. **参数确认**：前端 ConfirmCard 展示解析结果，用户可修改后执行

### 1.3 技术栈（Main 分支实际使用）

| 层级 | 技术 | 版本 | 备注 |
|------|------|------|------|
| 后端框架 | Python 3 + FastAPI | 0.115 | |
| LLM 客户端 | OpenAI SDK（调用 DeepSeek） | ≥2.36 | `llm_client.py` |
| 数据库驱动 | python-oracledb | 4.0 | Oracle 19c |
| 前端框架 | Vue 3 (Composition API) | 3.5 | `<script setup>` |
| UI 组件库 | Naive UI | 2.40 | 含 zhCN 中文 locale |
| 构建工具 | Vite | 5.4 | 开发代理 /api → localhost:8000 |

> **注意：** `requirements.txt` 中声明了 langchain/langgraph 依赖，但 main 分支代码未实际使用。Agent、ECharts 图表、报告导出等模块仅在 `feature/langchain-agent` 分支实现。

### 1.4 术语定义

| 术语 | 说明 |
|------|------|
| 结汇 | 客户将外汇卖给银行（银行买入），对应 buy_sell=B |
| 购汇/售汇 | 客户从银行购买外汇（银行卖出），对应 buy_sell=S |
| 结售汇 | 同时包含结汇和售汇，强制 appid=2，不筛选方向 |
| 即期 (spot) | 现货外汇交易 |
| 远期 (fwd) | 远期外汇交易 |
| 掉期 (swap) | 外汇掉期交易 |
| 套保率 | 衍生品（远期+掉期）交易金额 / 总交易金额 × 100% |
| 同比 (YoY) | 与去年同期对比（日期整体前移一年） |
| 环比 (MoM) | 与上一等长周期对比 |

---

## 2. 功能需求

### 2.1 系统架构与数据流

```
┌─────────────────────────────────────────────────────────┐
│  前端 (Vue 3 + Naive UI)                                │
│  InputArea → /api/parse → ConfirmCard → /api/query → ResultPanel  │
└─────────────────────────────────────────────────────────┘
          │  POST /api/parse          │  POST /api/query
          ▼                           ▼
┌─────────────────────────────────────────────────────────┐
│  FastAPI (app.py)                                       │
│                                                        │
│  /api/parse:                                           │
│    llm_parse() ──成功──▶ gatekeep() ──▶ {params, pipeline:"llm+gatekeep"} │
│         │                                            │
│         └──失败──▶ rule_based_parse() ──▶ {params, pipeline:"fallback"}  │
│                                                        │
│  /api/query:                                           │
│    有 pre_parsed? → 跳过解析                            │
│    否则 → 同 /api/parse 流程                            │
│    → TradeQueryBuilder 构建 SQL（5 种路由）              │
│    → Oracle 执行                                        │
│    → compute_comparison 同比/环比（可选）                 │
│    → {sql, columns, rows, row_count, comparison}        │
└─────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  Oracle 19c                                             │
│  XF_FX_SPOTTRADE_VIEW / XF_FX_FWDTRADE_VIEW            │
│  XF_FX_SWAPTRADE_VIEW / XF_BASE_BANK                   │
└─────────────────────────────────────────────────────────┘
```

### 2.2 功能模块

#### F1: 自然语言查询解析

**入口：** `POST /api/parse` 或 `POST /api/query`（带 text）

**输入：** 中文自然语言文本（前端限制 ≤2000 字符）

**输出：** 结构化参数字典，包含以下字段（基于 `_fields_defaults()` + `rule_based_parse()` 实际返回）：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| product_type | str | `"all"` | spot / fwd / swap / all |
| date_start | str | `""` | `"YYYY-MM-DD"` |
| date_end | str | `""` | `"YYYY-MM-DD"` |
| special_states | str | `""` | 逗号分隔的状态码，如 `"0,1"` |
| trade_class | str | `""` | 逗号分隔的交易类别码，如 `"1,2,6"` |
| buy_sell | str | `""` | `"B"` / `"S"` / `""` |
| bank_name | str | `""` | 银行名称 |
| cust_name | str | `""` | 客户名称 |
| aggregate | bool | `false` | 是否聚合统计 |
| top_n | int or None | `null` | 前 N 名（1-100） |
| amount_filter | dict or None | `null` | `{"amount_op":"gt", "amount_value":100000000}` |
| dimension | str | `"bank"` | bank / customer / customer_id / manager / manager_name |
| hedge_ratio | bool | `false` | 是否查询套保率 |
| appid | int or None | `null` | 1=外汇 / 2=结售汇 |
| comparison | str | `""` | `"yoy"` / `"mom"` / `""` |

**解析流程（双引擎）：**

```
1. llm_parse(text, system_prompt)
   ├─ 调用 DeepSeek V4 Flash API（api.deepseek.com）
   ├─ 30s 超时，temperature=0.1
   ├─ 提取 JSON（支持 ```json 代码块 / 纯 JSON）
   └─ 失败返回 None

2. 如果 LLM 成功 → gatekeep(parsed, text)
   ├─ 阶段 1a: 铁律 buy_sell 覆盖（结汇=B, 购汇/售汇=S）
   ├─ 阶段 1b: "结售汇"特例（appid=2, buy_sell=""）
   ├─ 阶段 1c: 客户前缀反转（客户买入→S, 客户卖出→B）
   ├─ 阶段 1d: special_states 精确匹配
   ├─ 阶段 1d2: trade_class 匹配
   ├─ 阶段 1d3: 签约交易检测（ISSIGNTRADE=0）
   ├─ 阶段 1e: product_type 精确匹配
   ├─ 阶段 1f: app_id 匹配（仅未设置时）
   ├─ 阶段 2: 日期回退（LLM未解析出时从规则补充）
   ├─ 阶段 3: 客户名称回退
   ├─ 阶段 4: 银行名称回退
   ├─ 阶段 5: 互斥校验（cust_name + bank_name → 清空bank_name）
   ├─ 聚合/套保率/TopN/金额过滤/维度回退
   └─ pipeline 标记: "llm+gatekeep"

3. 如果 LLM 失败 → rule_based_parse(text)
   └─ pipeline 标记: "fallback"
```

**规则解析器覆盖的能力（`parser.py`）：**

| 子模块 | 覆盖范围 |
|--------|---------|
| `_parse_product_type` | 即期→spot, 远期→fwd, 掉期→swap, 多选→all |
| `_parse_buy_sell` | 结汇→B（铁律），购汇/售汇→S（铁律），买入→B，卖出→S，结售汇→空 |
| `_parse_date_range` | 13 级优先级：显式日期范围 → 完整日期 → 月份 → 今年N月 → 今年 → 本月 → 本周 → 旬 → 昨天/今天 → 上月 → 近N月/年/天 → 本季度 |
| `_parse_bank_name` | XX银行 / XX分行/支行/分公司/营业部 / XX银行XX分行 |
| `_parse_cust_name` | XX客户 / XX的套保率 |
| `_parse_special_states` | 在途/未到期→0, 逾期/已过期→1, 展期/延期→3, 提前交割/提前交收→4, 平仓/已平仓→5（无挂账） |
| `_parse_trade_class` | 两遍匹配：先精确匹配 14 组长关键词，无结果时泛化匹配（平仓→1,2,6,7,10,11,15,17 / 展期→3,5,12,13 / 提前交割→4,16） |
| `_cn_to_int` | 中文数字→整数（十→10, 十五→15, 一百零五→105） |
| `_parse_top_n` | TOP N / 前N / 排名/排行（默认10） |
| `_parse_aggregate` | 交易量/金额/总额/总计/汇总 → true |
| `_parse_hedge_ratio` | 套保率 → true |
| `_parse_amount_filter` | 大于等于(gte)/大于(gt)/小于等于(lte)/小于(lt) + 万/亿单位换算 |
| `_parse_comparison_modifier` | 同比→yoy, 环比→mom |
| `_parse_dimension` | 客户号→customer_id, 客户经理ID→manager, 客户经理名称/姓名→manager_name, 客户→customer, 默认→bank |
| `compute_comparison_dates` | YoY 前移一年（含2月29日处理），MoM 等长区间前移 |

#### F2: 查询参数确认与修改

**前端组件：** `ConfirmCard.vue`

**数据流：**
```
App.vue handleSend(text)
  → POST /api/parse {text}
  → 收到 {params, pipeline}
  → BotMessage 切换 mode="confirm"
  → ConfirmCard 展示可编辑表单
  → 用户修改 → 点击"确认查询"
  → App.vue handleConfirm(params, msgIdx)
  → POST /api/query {params}
```

**ConfirmCard 实际可编辑字段（`form` reactive 对象）：**

| 表单字段 | UI 组件 | 数据来源 | 是否可编辑 |
|---------|---------|---------|-----------|
| product_type | NSelect（全部/即期/远期/掉期） | params.product_type | 是 |
| date_start | NDatePicker | params.date_start 转 timestamp | 是 |
| date_end | NDatePicker | params.date_end 转 timestamp | 是 |
| buy_sell | NRadioGroup（不限/B/S） | params.buy_sell | 是 |
| appid | NRadioGroup（不限/外汇/结售汇） | params.appid | 是 |
| special_states | NCheckboxGroup（6 种状态含挂账） | params.special_states 拆分为数组 | 是 |
| bank_name | NInput | params.bank_name | 是 |
| cust_name | NInput | params.cust_name | 是 |
| aggregate | NSwitch + 汇总标签 | params.aggregate | 是 |
| top_n | NInputNumber（min=1） | params.top_n | 是 |
| dimension | NSelect（5 种维度） | params.dimension | 是 |

**提交时收集的字段（`handleConfirm`）：**
```javascript
{
  product_type, date_start, date_end, buy_sell, appid,
  special_states,  // 数组 join(',')
  bank_name, cust_name, aggregate,
  top_n,           // 0 表示不限
  dimension,
  comparison       // 来自原始 params，不可编辑，仅透传
}
```

> **注意：** hedge_ratio 和 trade_class 不在 ConfirmCard 表单中（不可编辑），但通过 `props.params` 保留在 comparison 等字段中传递。如果用户选择了"重置"，会重新调用 `/api/parse` 用原始文本解析。

**展示标签：**
- pipeline 标签：`"llm+gatekeep"` → 绿色 "LLM解析" / 其他 → 橙色 "规则匹配"
- comparison 标签：`"yoy"` → 蓝色 "同比" / `"mom"` → 蓝色 "环比"

**交互操作：**
- "确认查询"：emit('confirm', collectedParams) → App.vue 调用 executeQuery()
- "重置"：emit('reset') → App.vue 重新调用 parseQuery(originalText)

#### F3: SQL 安全构建与路由

**原则：** SQL 由 `TradeQueryBuilder` 静态方法确定性地构建，LLM 绝不参与 SQL 生成。

**Main 分支实际路由（5 条分支，`app.py:215-278`）：**

```
parsed 参数
  ├─ amount_filter 不为空？ → build_filtered_query()
  │    按维度分组 + HAVING SUM(USDAMOUNT) >=/<= N
  │    支持 hedge_ratio 模式（HAVING 套保率公式）
  │
  ├─ top_n > 0？ → build_ranking_query()
  │    按维度分组 + ORDER BY SUM DESC + ROWNUM <= N
  │    hedge_ratio=true 时 ORDER BY HEDGE_RATIO DESC
  │
  ├─ hedge_ratio=true？ → build_hedge_ratio_query()
  │    按维度分组 + 套保率公式 + 衍生品金额/笔数
  │    自动追加 SPECIALSTATE=0（仅统计在途交易）
  │
  ├─ aggregate=true？ → build_aggregate_query()
  │    SUM(USDAMOUNT) + COUNT(*) + 可选 GROUP BY 维度
  │    无维度时返回单行总计
  │
  └─ 默认 → build_query()
       返回所有字段明细（无 ROWNUM 限制）
       含 LEFT JOIN XF_BASE_BANK 获取 DIPNAME
```

**各方法构建的 SQL 形态：**

| 方法 | SELECT 内容 | 分组 | 排序 | 限制 |
|------|------------|------|------|------|
| `build_query` | 全部 COMMON_FIELDS + DIPNAME | 无 | 无 | 无 |
| `build_aggregate_query` | SUM + COUNT（可选维度列） | 可选 GROUP BY | TOTAL_AMOUNT DESC（有维度时） | 无 |
| `build_hedge_ratio_query` | 维度列 + HEDGE_RATIO + DERIVATIVE_AMOUNT/COUNT + TOTAL_AMOUNT/COUNT | GROUP BY 维度 | HEDGE_RATIO DESC | 无 |
| `build_ranking_query` | 维度列 + TOTAL_AMOUNT + TRADE_COUNT（或套保率字段） | GROUP BY 维度 | SUM DESC / HEDGE_RATIO DESC | ROWNUM ≤ N |
| `build_filtered_query` | 同 ranking_query | GROUP BY 维度 | TOTAL_AMOUNT DESC / HEDGE_RATIO DESC | HAVING 条件 |

**共享 SQL 构建逻辑：**

- `_build_where_conditions()`: 所有查询共用的 WHERE 子句（TRADESTATUS=0, APPID, 日期范围, buy_sell, cust_name, special_states, bank_condition）
- `_build_from()`: UNION ALL 构建（all=3个视图合并，单一类型=单个视图），with_pt 参数用于套保率查询
- `_build_cte()`: 银行名称模糊搜索的 CTE（`WITH matched_banks AS (SELECT BANKID FROM XF_BASE_BANK WHERE DIPNAME LIKE '%name%')`）
- `_join_clause()`: 银行维度或指定 bank_name 时 LEFT JOIN XF_BASE_BANK
- `_group_cols()`: 5 种维度 → SELECT/GROUP BY 列的映射
- `_escape_bank_name()`: 转义 `\`, `'`, `%`, `_`

**安全措施：**
- 所有 SQL 通过静态方法参数化构建
- 用户输入的银行名称经过 `_escape_bank_name()` 转义
- 用户输入的客户名称经过 `cust_name.replace("'", "''")` 转义
- HEDGE_RATIO_SQL 为类常量，不可动态拼接

**数据源：**

| 视图常量 | 数据库视图 | 说明 |
|---------|-----------|------|
| spot | XF_FX_SPOTTRADE_VIEW | 即期外汇交易 |
| fwd | XF_FX_FWDTRADE_VIEW | 远期外汇交易 |
| swap | XF_FX_SWAPTRADE_VIEW | 掉期外汇交易 |
| - | XF_BASE_BANK | 银行基础信息（LEFT JOIN 用） |

> **注意：** Main 分支`query_builder.py`没有收益表（XF_FX_PROFIT）相关的查询方法，也没有产品分布、趋势等查询类型。

#### F4: 查询结果展示

**前端组件：** `ResultPanel.vue`

**3 个标签页（按条件显示）：**

1. **数据标签页**（hasData=true 时显示）
   - Naive UI DataTable：列名通过 `COLUMN_LABELS` 映射为中文（如 USDAMOUNT→"折美元金额（万美元）"）
   - 金额列（USDAMOUNT/TOTAL_AMOUNT/DERIVATIVE_AMOUNT）自动 ÷10000 格式化，保留 2 位小数
   - 套保率列（HEDGE_RATIO）显示为 `xx.xx%`
   - DIPNAME 为 null 时显示 "(未识别)"
   - 最大高度 400px + striped 斑马纹
   - 底部显示 "共 N 行"

2. **SQL 标签页**（hasSql=true 时显示）
   - Naive UI NCode 组件，语言标识 `sql`，自动换行
   - 用于审计追溯生成的 SQL 语句

3. **参数标签页**（hasParams=true 时显示）
   - Naive UI NCode 组件，语言标识 `json`
   - JSON.stringify(params, null, 2) 格式化

**对比卡片**（hasComparison=true 时显示，在标签页上方）：
- 卡片头部：对比类型标签（同比/环比）+ 变化率 Tag（绿色+/红色-）
- 三列数据：当期金额 / 对比期金额 / 变化金额（均以万美元显示）
- 计算逻辑位于 `app.py:_compute_comparison()`，取 `TOTAL_AMOUNT`（列索引 1）计算变化量和变化率

---

## 3. 非功能需求

### 3.1 性能

| 指标 | 值 | 实现位置 |
|------|-----|---------|
| LLM 解析超时 | 30 秒 | `llm_client.py:64` timeout=30 |
| LLM temperature | 0.1 | 低随机性，保证解析一致性 |
| 前端健康检查超时 | 5 秒 | `api.js:2` AbortSignal.timeout(5000) |

### 3.2 安全

- Oracle 凭据通过 `.env` 文件注入（DB_HOST/DB_PORT/DB_SERVICE/DB_USER/DB_PASSWORD）
- DeepSeek API Key 通过环境变量 `DEEPSEEK_API_KEY` 注入
- SQL 中用户输入经过转义：`_escape_bank_name()` 转义 `\`, `'`, `%`, `_`
- LLM 仅解析意图为结构化参数，绝不直接生成 SQL
- 前端无路由（单页面），无 XSS 风险点

### 3.3 可用性

- 生产模式：后端自动 serve `frontend/dist/` 静态文件（`/` 路由指向 dist/index.html，`/assets` 挂载 dist/assets）
- 开发模式：Vite 开发服务器（5173）代理 `/api` 到后端（8000）
- 前端启动时自动检查 `/api/health`，状态栏显示连接状态
- 错误信息通过 JSONResponse 返回 `{error: "TypeName: message"}`

### 3.4 可维护性

- 业务规则集中在 `knowledge_base/semantic_rules.json`（395 行），支持 `/api/reload-rules` 热加载
- 模块职责清晰：`llm_client`（LLM 调用）→ `rules_engine`（守门）→ `parser`（规则解析）→ `query_builder`（SQL 构建）
- `prompt_builder.py` 有缓存机制，reload-rules 时失效

---

## 4. 数据模型

### 4.1 外汇交易视图公共字段（`COMMON_FIELDS`）

`query_builder.py:8` 定义，三个交易视图共享：

| 字段名 | 中文含义 | 备注 |
|--------|---------|------|
| USDAMOUNT | 美元金额 | NUMBER |
| TRADEDATE | 交易日期 | NUMBER(8) YYYYMMDD |
| TRADESTATUS | 交易状态 | 0=正常 |
| SPECIALSTATE | 特殊状态 | 0=在途, 1=逾期, 3=展期, 4=提前交割, 5=平仓 |
| APPID | 业务系统 | 1=外汇, 2=结售汇 |
| BUYORSELL | 买卖方向 | B=银行买入, S=银行卖出 |
| BANKID | 机构ID | 关联 XF_BASE_BANK |
| CUSTNAME | 客户名称 | |
| CUSTOMERID | 客户号 | |
| CUSTMAINMANAGER | 客户主管ID | |
| CUSTMANAGERNAME | 客户经理姓名 | |

### 4.2 银行基础信息表

| 字段名 | 中文含义 |
|--------|---------|
| DIPNAME | 银行全称（模糊搜索目标字段） |
| BANKID | 银行ID（JOIN 关联字段） |

---

## 5. API 接口规格（Main 分支实际实现）

### 5.1 健康检查

```
GET /api/health
→ 200 { "status": "ok" }
```

### 5.2 查询解析

```
POST /api/parse
Request:  { "text": "本月交易量" }
Response: {
  "params": {
    "product_type": "all",
    "date_start": "2026-05-01",
    "date_end": "2026-05-14",
    "special_states": "",
    "trade_class": "",
    "buy_sell": "",
    "bank_name": "",
    "cust_name": "",
    "aggregate": true,
    "top_n": null,
    "amount_filter": null,
    "dimension": "bank",
    "hedge_ratio": false,
    "appid": null,
    "comparison": ""
  },
  "pipeline": "llm+gatekeep"   // 或 "fallback"
}
Error: 500 { "error": "ExceptionType: message" }
```

### 5.3 查询执行

```
POST /api/query
Request:  {
  "text": "本月交易量",        // 可选（无 params 时使用）
  "params": { ... }           // 可选（前端确认后跳过解析）
}
Response: {
  "sql": "SELECT SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT ...",
  "params": { ... },
  "columns": ["TOTAL_AMOUNT", "TRADE_COUNT"],
  "rows": [[123456789, 42]],
  "row_count": 1,
  "comparison": {              // 仅在请求了同比/环比且有对比数据时存在
    "type": "yoy",
    "label": "同比",
    "current_period": "2026-05-01 ~ 2026-05-14",
    "compare_period": "2025-05-01 ~ 2025-05-14",
    "current_amount": 1234567.89,
    "compare_amount": 1000000.00,
    "change_amount": 234567.89,
    "change_rate": 23.46
  },
  "error": ""
}
Error: 500 { "sql": "...", "params": {...}, "columns": [], "rows": [], "row_count": 0, "error": "..." }
```

### 5.4 规则重载

```
POST /api/reload-rules
→ 200 { "status": "ok", "message": "Rules and prompt cache refreshed" }
```
行为：重新读取 `semantic_rules.json`，清空 rules_engine 缓存 + prompt_builder 缓存。

### 5.5 前端静态文件

```
GET /
→ 200  dist/index.html（存在时）或 frontend/index.html

GET /assets/*
→ StaticFiles from frontend/dist/assets（存在时）
```

---

## 6. 前端组件结构与交互

### 6.1 组件树

```
App.vue (root, reactive messages[], connectionStatus ref)
├── StatusHeader.vue          # 标题 "Smart BI" + 连接状态 Tag
├── MessageArea.vue           # 消息列表（overflow-y:auto，新消息自动滚底）
│   └── BotMessage.vue        # Bot 消息路由（4 种 mode）
│       ├── mode="loading"    # NSpin + "思考中..."
│       ├── mode="error"      # NAlert 错误信息
│       ├── mode="confirm"    # ConfirmCard 参数确认表单
│       └── mode="result"     # ResultPanel 结果展示
└── InputArea.vue             # 输入框 + 发送按钮（Enter 发送，Shift+Enter 换行）
```

### 6.2 消息数据结构

```javascript
// 用户消息
{ type: 'user', text: '本月交易量' }

// Bot 消息 - 加载中
{ type: 'bot', mode: 'loading' }

// Bot 消息 - 参数确认
{ type: 'bot', mode: 'confirm', params: {...}, pipeline: 'llm+gatekeep',
  originalText: '本月交易量', querying: false, resetting: false }

// Bot 消息 - 查询结果
{ type: 'bot', mode: 'result', data: { columns, rows, row_count, sql, params, comparison } }

// Bot 消息 - 错误
{ type: 'bot', mode: 'error', error: '错误描述' }
```

### 6.3 状态管理

单页面应用，无 Vue Router / Pinia。`App.vue` 中 `reactive([])` 管理消息列表，通过 props/emits 在父子组件间传递数据。3 个核心事件流：
- `@send` → handleSend(text)
- `@confirm` → handleConfirm(params, msgIdx)
- `@reset` → handleReset(msgIdx)

---

## 7. 业务规则详细说明

### 7.1 买卖方向完整规则（semantic_rules.json buy_sell_direction）

**铁律规则（customer_reversible=false，不能被客户前缀反转）：**

| 关键词 | 方向 | 额外操作 | 适用产品 |
|--------|------|---------|---------|
| 结汇, 结汇交易 | B | set_app_id=2 | spot/fwd/swap |
| 购汇, 售汇, 购汇交易, 售汇交易 | S | set_app_id=2 | spot/fwd/swap |
| 近购远结, 近售远结 | B | set_app_id=2 | swap |
| 近结远购, 近结远售 | S | set_app_id=2 | swap |

**可反转规则（customer_reversible=true，含"客户"前缀时反转）：**

| 关键词 | 默认方向 | 客户视角方向 | 适用产品 |
|--------|---------|------------|---------|
| 买入, 买, 购买, BUY | B | S | spot/fwd |
| 卖出, 卖, 出售, SELL | S | B | spot/fwd |
| 买入, 买, 近卖远买 | B | S | swap |
| 卖出, 卖, 近买远卖 | S | B | swap |

**"结售汇"特殊处理：** 同时含结汇和售汇关键词 → buy_sell=""（不筛选方向），appid=2（强制结售汇系统）

### 7.2 时间表达解析（parser.py 实现的 13 级优先级）

| 优先级 | 模式 | 示例 | 结果 |
|--------|------|------|------|
| 1 | YYYY-MM-DD 到 YYYY-MM-DD | 2026-01-01 到 2026-05-14 | [2026-01-01, 2026-05-14] |
| 2 | YYYY年MM月DD日 | 2026年3月15日 | [2026-03-15, 2026-03-15] |
| 3 | YYYY年MM月 | 2026年3月 | [2026-03-01, 2026-03-31] |
| 4 | 今年N月 | 今年3月 | [2026-03-01, 2026-03-31] |
| 5 | 今年 | 今年 | [2026-01-01, 今天] |
| 6 | 本月 | 本月 | [本月1日, 今天] |
| 7 | 本周 | 本周 | [本周一, 今天] |
| 8 | 上旬/中旬/下旬 | 上旬 | [本月1日, 本月10日] |
| 9 | 昨天/今天 | 昨天 | [昨天, 昨天] |
| 10 | 上月/上个月 | 上月 | [上月1日, 上月最后一天] |
| 11 | 近N个月/近N年/近N天 | 近6个月 | [6月前1日, 今天] |
| 12 | 本季度 | 本季度 | [本季度初, 今天] |
| - | 兜底 | 无匹配 | ("", "") |

> **注意：** `semantic_rules.json` 定义了 31 条时间规则（含去年、前年、上半年、下半年等），但 parser.py 目前只实现了上述 13 级。LLM prompt 中包含了完整规则，LLM 可以解析 parser 未覆盖的时间表达。

### 7.3 特殊状态码

| 代码 | 含义 | 关键词 |
|------|------|--------|
| 0 | 在途 | 在途, 未到期 |
| 1 | 逾期 | 逾期, 已过期 |
| 3 | 展期 | 展期, 延期 |
| 4 | 提前交割 | 提前交割, 提前交收 |
| 5 | 平仓 | 平仓, 已平仓 |

> 代码 2（挂账）在前端 `SPECIAL_STATES` 常量中存在可选，但在 `semantic_rules.json` 和 parser 中未定义，LLM prompt 中特别注明"没有挂账状态，不要在 special_states 中使用 2"。

### 7.4 交易类别（Trade Class）两遍匹配

`_parse_trade_class()` 先精确匹配 14 组关键词（如"全部平仓"→6, "交割日平仓"→2, "近端原价展期"→12），无精确匹配时才泛化（平仓→1,2,6,7,10,11,15,17 / 展期→3,5,12,13 / 提前交割→4,16）。

### 7.5 聚合维度映射

| 维度值 | 关键词 | SELECT 列 | GROUP BY 列 |
|--------|--------|-----------|-------------|
| bank | 默认 | b.DIPNAME as 机构名称 | b.DIPNAME |
| customer | 客户名称, 客户 | t.CUSTNAME as 客户名称 | t.CUSTNAME |
| customer_id | 客户号, 客户编号, 客户ID | t.CUSTOMERID as 客户号 | t.CUSTOMERID |
| manager | 客户经理ID, 客户经理编号 | t.CUSTMAINMANAGER as 客户经理ID | t.CUSTMAINMANAGER |
| manager_name | 客户经理名称, 客户经理姓名, 客户经理 | t.CUSTMANAGERNAME as 客户经理名称 | t.CUSTMANAGERNAME |

### 7.6 客户名与银行名互斥

- `cust_name` 不为空 → 强制 `dimension="customer"`，清空 `bank_name`
- `cust_name` 和 `bank_name` 同时存在 → 清空 `bank_name`（客户优先）

---

## 8. 当前实现状态

### 8.1 Main 分支（已实现）

| 功能 | 状态 | 关键文件 |
|------|------|---------|
| F1: NL 查询解析（LLM + 规则双引擎） | 已完成 | `llm_client.py`, `parser.py`, `rules_engine.py`, `prompt_builder.py` |
| F2: ConfirmCard 参数确认修改 | 已完成 | `ConfirmCard.vue`, `App.vue` |
| F3: SQL 安全构建（5 种查询类型） | 已完成 | `query_builder.py`, `app.py` |
| F4: 结果展示（数据表格+SQL+参数+同比环比） | 已完成 | `ResultPanel.vue`, `constants.js` |
| 规则热加载 | 已完成 | `app.py:/api/reload-rules` |
| 系统提示缓存 + 热失效 | 已完成 | `prompt_builder.py` |
| 健康检查 + 连接状态展示 | 已完成 | `app.py:/api/health`, `StatusHeader.vue` |
| 生产模式静态文件服务 | 已完成 | `app.py:/` + `/assets` mount |

### 8.2 Feature 分支（feature/langchain-agent，开发中）

| 功能 | 状态 |
|------|------|
| LangGraph Agent 8 节点流水线 | 已实现（`sql_engine/agent.py`, `nodes.py`） |
| 4 个 Agent 工具（Parse/Execute/Compare/Chart） | 已实现（`sql_engine/tools.py`） |
| Agent 记忆 + 多轮对话 | 已实现（`sql_engine/memory.py`） |
| 查询结果缓存 | 已实现（`sql_engine/cache.py`） |
| 扩展 SQL：产品分布/趋势/收益排名（7 种新类型） | 已实现（`query_builder.py` feature 版） |
| ECharts 图表生成（4 种类型自动检测） | 已实现（`visualization/`） |
| NL 摘要 + 数据洞察 | 已实现（`nodes.py:think_summary`） |
| Excel/PDF 报告导出 | 已实现（`report_generator/exporter.py`） |
| 前端 ChartView 集成 | 已实现（`ChartView.vue`） |
| `/api/agent/query` + `/api/report/export` 端点 | 已实现（`app.py` feature 版） |
| SSE 流式响应 | 计划中 |
| 前端摘要 + insights 展示 | 计划中 |

---

## 9. 附录

### 9.1 Main 分支实际文件结构

```
smartbi0512/
├── backend/
│   ├── app.py                       # FastAPI，4 个 API 端点 + 静态文件
│   ├── requirements.txt             # Python 依赖
│   ├── start_server.py / run.sh     # 启动脚本
│   ├── db/
│   │   ├── config.py                # Oracle 连接配置（环境变量）
│   │   ├── connection.py            # oracledb 连接管理器
│   │   └── query_builder.py         # TradeQueryBuilder（341 行，5 种查询）
│   ├── llm_parser/
│   │   ├── llm_client.py            # DeepSeek API 客户端（86 行）
│   │   ├── parser.py                # 关键词规则解析器（568 行）
│   │   ├── prompt_builder.py        # LLM 系统提示构建（157 行）
│   │   └── rules_engine.py          # 守门验证引擎（171 行）
│   └── knowledge_base/
│       ├── semantic_rules.json      # 业务语义规则（395 行）
│       └── sql_rules.json           # SQL 结构描述（50 行）
├── frontend/
│   ├── src/
│   │   ├── App.vue                  # 根组件（128 行）
│   │   ├── api.js                   # 3 个 API 函数（34 行）
│   │   ├── constants.js             # 列标签/格式化/选项常量（80 行）
│   │   └── components/
│   │       ├── StatusHeader.vue     # 标题+连接状态（24 行）
│   │       ├── InputArea.vue        # 查询输入（57 行）
│   │       ├── MessageArea.vue      # 消息列表（67 行）
│   │       ├── BotMessage.vue       # 消息路由（55 行）
│   │       ├── ConfirmCard.vue      # 参数确认表单（265 行）
│   │       └── ResultPanel.vue      # 结果面板（117 行）
│   ├── package.json
│   └── vite.config.js
├── .env                             # 环境变量
└── CLAUDE.md                        # 项目文档
```

### 9.2 关键环境变量

| 变量 | 用途 | 默认值 |
|------|------|--------|
| DEEPSEEK_API_KEY | DeepSeek API 密钥 | 无（未设置则跳过 LLM） |
| DB_HOST | Oracle 主机 | localhost |
| DB_PORT | Oracle 端口 | 1521 |
| DB_SERVICE | Oracle 服务名 | orclutf |
| DB_USER | Oracle 用户名 | 无 |
| DB_PASSWORD | Oracle 密码 | 无 |
| LLM_API_KEY | 备用 LLM API 密钥（.env 中有但 llm_client 未使用） | - |
| LLM_BASE_URL | 备用 LLM 地址（.env 中有但 llm_client 未使用） | - |

### 9.3 LLM 客户端实际配置（硬编码）

```python
# llm_client.py
_BASE_URL = "https://api.deepseek.com"
_MODEL = "deepseek-v4-flash"
# 使用 DEEPSEEK_API_KEY 环境变量
```

### 9.4 前端金额格式化规则

```javascript
// constants.js
// 金额列（USDAMOUNT, TOTAL_AMOUNT, DERIVATIVE_AMOUNT）
// 显示值 = 原始值 / 10000，保留 2 位小数，英文 locale 格式（千分位逗号）
// 例：123456789 → "12,345.68"

// 套保率（HEDGE_RATIO）
// 显示值 = xx.xx%
// 例：45.6789 → "45.68%"
```

---

> **文档维护说明：** 本文档严格基于 main 分支 2026-05-14 实际代码状态生成。Feature 分支内容已明确标注。后续功能变更请同步更新对应章节和实现状态。
