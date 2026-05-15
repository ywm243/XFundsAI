# Smart BI 产品需求规格说明书（PRD）

**版本**: 1.0  
**日期**: 2026-05-15  
**状态**: 已实现  
**作者**: Smart BI 开发团队  

---

## 1. 产品概述

### 1.1 项目背景

外汇交易业务涉及即期、远期、掉期三类产品，交易数据存储在 Oracle 数据仓库中（含机构信息表 `XF_BASE_BANK` 与多张交易视图 `XF_FX_SPOTTRADE_VIEW` / `XF_FX_FWDTRADE_VIEW` / `XF_FX_SWAPTRADE_VIEW`）。业务人员日常需要频繁查询交易总量、排名、套保率、同比/环比对比等指标，但传统方式依赖编写 SQL 或使用固定的报表工具，存在以下痛点：

- **学习门槛高**：业务人员不熟悉 SQL 语法和数据库表结构
- **响应速度慢**：每次新需求都需要技术人员介入编写查询
- **上下文断裂**：每次查询都是独立会话，无法连续追问
- **规则分散**：业务规则硬编码在代码中，修改需要上线部署

Smart BI 通过自然语言查询 + LLM 解析 + 规则引擎守门的架构，让业务人员直接用中文输入查询意图，系统自动解析、生成 SQL、执行并返回四段式可视化结果（摘要→图表→洞察→表格）。

### 1.2 产品目标

| 维度 | 目标 | 衡量指标 |
|------|------|----------|
| 效率提升 | 将常见查询的响应时间从 30 分钟（找技术+写SQL）降至 5 秒内 | 查询全链路耗时 < 5s（不含 LLM 调用） |
| 降低门槛 | 业务人员无需 SQL 知识即可自主查询 | 支持 13 种中文时间表达式、5 种统计维度 |
| 高可用 | 规则引擎覆盖 80% 常见查询，LLM 作为补充 | 规则置信度 >= 0.8 时跳过 LLM，节省 API 成本 |
| 规则可管理 | 非技术人员可安全修改业务规则 | 管理后台纯表单操作，零 JSON 编写；版本回滚一键完成 |
| 对话连续性 | 支持多轮追问，自动继承上下文 | 通过 SQLite 持久化会话上下文 |

### 1.3 用户画像

| 角色 | 描述 | 典型场景 |
|------|------|----------|
| 交易业务员 | 日常追踪交易数据，无 SQL 技能 | "本月即期结汇交易量"、"各银行排名"、"套保率" |
| 风控分析师 | 监控交易异常，需要同比/环比对比 | "本月交易量同比"、"逾期交易金额大于 100 万" |
| 业务主管 | 查看全局数据、排名分布 | "一季度各机构交易量排名 TOP 10" |
| 系统管理员 | 维护业务规则（关键词→映射值） | 通过管理后台新增/修改/禁用规则，热部署生效 |

### 1.4 技术架构概览

```
用户输入(中文) → 规则引擎解析(parser.py) → 置信度评估
                    ↓ 置信度 < 0.8
                LLM 解析(llm_client.py) + Gatekeep 守门(rules_engine.py)
                    ↓
               SQL 构建(query_builder.py, 5种路由)
                    ↓
              Oracle 执行 → 结果增强(摘要/图表/洞察/对比)
                    ↓
              Vue 3 前端四段式卡片展示
```

**技术栈**：Python 3 + FastAPI（后端），Vue 3 + Naive UI（前端），Oracle 19c（数据源），SQLite（规则+记忆存储），OpenAI-compatible LLM API（阿里云 DashScope / DeepSeek 等）。

---

## 2. 功能需求

### 2.1 NL 查询解析（双引擎 + 置信度路由）

**用户故事**：作为业务人员，我想要用中文输入查询需求（如"本月即期结汇交易量"），以便系统自动理解并返回数据结果，无需我编写 SQL。

**验收标准**：
1. 系统必须先执行规则引擎解析（`rule_based_parse`），耗时 < 1ms
2. 规则引擎计算置信度评分（0.0 ~ 1.0），评分维度包括：日期识别（权重 1.5）、实体识别（权重 1.0）、查询意图（权重 1.5）
3. 置信度 >= 0.8 时跳过 LLM，仅用规则结果，返回 `pipeline="rule(confidence=XX%)"`
4. 置信度 < 0.8 时调用 LLM 解析，LLM 结果经 Gatekeep 守门验证后输出，返回 `pipeline="llm+gatekeep(rule_confidence=XX%)"`
5. LLM 调用失败时自动回退到规则结果，返回 `pipeline="rule_fallback(confidence=XX%)"`
6. 输出结构化参数：包含 `product_type`（all/spot/fwd/swap）、`date_start`/`date_end`、`buy_sell`、`bank_name`、`cust_name`、`aggregate`、`top_n`、`amount_filter`、`dimension`、`hedge_ratio`、`comparison` 等字段
7. 支持多轮对话上下文注入（可选 `context` 参数）

**实现文件**：`backend/llm_parser/parser.py`、`backend/llm_parser/llm_client.py`、`backend/llm_parser/rules_engine.py`

---

### 2.2 多轮对话上下文

**用户故事**：作为业务人员，我想要连续提问（如先问"本月交易量"，再问"上月呢"），以便系统记住上一轮的查询条件，不必重复输入。

**验收标准**：
1. 前端自动收集最近 4 条用户消息和系统响应，构建为对话上下文
2. 上下文作为 `context` 参数传入 `/api/parse`，LLM 在 system prompt 中包含"历史对话"区块
3. 上下文包含 role（user/assistant）和 content（用户原文/解析结果 JSON）
4. 上下文直接拼接在基础 system prompt 末尾（不缓存带上下文的 prompt）
5. 会话数据持久化到 SQLite（`sessions` 表 + `turns` 表），支持跨请求恢复
6. 每 5 轮自动触发生成摘要（`memory_summaries` 表）

**实现文件**：`backend/llm_parser/prompt_builder.py`、`backend/memory/store.py`、`frontend/src/App.vue`（`buildContext` 函数）

---

### 2.3 5 种 SQL 路由

**用户故事**：作为系统，我需要根据解析出的参数自动选择正确的 SQL 查询模式，以便返回符合用户意图的结果（明细/聚合/排名/套保率/金额过滤）。

**验收标准**：

| 路由类型 | 触发条件 | SQL 特征 | 典型问句 |
|----------|----------|----------|----------|
| 明细查询 | 无聚合/排名/套保/过滤标识 | SELECT 明细字段 LEFT JOIN 机构表 | "工商银行本月交易" |
| 聚合查询 | `aggregate=true` 或关键词含"交易量/金额/总额/总计/汇总" | SUM + COUNT，可选 GROUP BY 维度 | "本月交易量" |
| 排名查询 | `top_n` 有值 或 关键词含"TOP N/前N/排名/排行" | GROUP BY + ORDER BY + ROWNUM | "各银行排名前 5" |
| 套保率查询 | `hedge_ratio=true` 或 关键词含"套保率" | 嵌套 SELECT 含 HEDGE_RATIO 公式 | "各机构套保率" |
| 金额过滤 | `amount_filter` 非空 | GROUP BY + HAVING 金额条件 | "交易量大于 100 万美元" |

2. 所有 SQL 通过参数化构建（`TradeQueryBuilder` 类），禁止字符串拼接用户输入
3. 机构名称使用 CTE + LIKE 模糊匹配（`XF_BASE_BANK.DIPNAME`），特殊字符转义
4. 日期参数转换为 `YYYYMMDD` 整数格式用于 Oracle 比较
5. 买卖方向、产品类型、特殊状态均通过 SQL WHERE 条件精确控制

**实现文件**：`backend/db/query_builder.py`

---

### 2.4 同比环比对比计算

**用户故事**：作为风控分析师，我想要查询"本月交易量同比"，以便看到与去年同期相比的变化趋势。

**验收标准**：
1. 识别关键词："同比"/"同步"→ `comparison="yoy"`，"环比" → `comparison="mom"`
2. 同比计算：日期范围前移一年（处理闰年 2 月 29 日边界）
3. 环比计算：日期区间整体前移一个区间长度
4. 对比 SQL 复用当前查询的 SQL 构建逻辑（`_build_comparison_sql`），仅替换日期参数
5. 对比结果包含：`current_period`、`compare_period`、`current_amount`、`compare_amount`、`change_amount`、`change_rate`
6. 多行结果（如排名）自动按维度标签匹配合并对比变化率列（`_merge_comparison_into_rows`）
7. 对比数据在图表中以双系列柱状图展示（当期蓝色 / 对比期绿色）

**实现文件**：`backend/app.py`（`_build_comparison_sql`、`_compute_comparison`、`_merge_comparison_into_rows`）、`backend/llm_parser/parser.py`（`compute_comparison_dates`）

---

### 2.5 四段式结果卡片

**用户故事**：作为业务人员，我想要查询结果以直观的方式呈现（文字摘要 + 图表 + 数据洞察 + 数据表格），以便快速理解数据含义。

**验收标准**：

**第一段：摘要**（`_build_summary`）
1. 自动生成一句话中文摘要，包含：日期范围、实体名称、交易总量（万美元）、笔数
2. 多行结果时自动识别排名第一的实体及占比
3. 有对比数据时自动加入同比/环比变化方向

**第二段：图表**（`_build_chart_option`）
1. 生成 ECharts 配置 JSON，前端用 `ChartView.vue` 渲染
2. 柱状图，X 轴为维度标签，Y 轴为金额（万美元）
3. 有对比数据时叠加对比期系列
4. 图表标题自动从查询参数生成

**第三段：洞察**（`_build_insights`）
1. 至少返回 2 条洞察
2. 类型标签：`growth`（增长）、`risk`（风险/集中度）、`quality`（信息提示）
3. 每条洞察附带"可追问 query"建议（如"交易量排名前 5"），点击可一键追问
4. 结果为空时提示"查询结果为空，请检查查询条件"

**第四段：表格**（`ResultPanel.vue`）
1. Naive UI DataTable 展示原始数据
2. 金额列自动转换为万美元格式（除以 10000）
3. 套保率列自动显示百分号
4. 对比列自动显示 +/- 变化率
5. 支持"数据"/"SQL"/"参数"三个标签页切换

**实现文件**：`backend/app.py`（`_build_summary`、`_build_chart_option`、`_build_insights`）、`frontend/src/components/ResultPanel.vue`、`frontend/src/components/ResultCard.vue`、`frontend/src/components/ChartView.vue`、`frontend/src/components/InsightPanel.vue`、`frontend/src/constants.js`

---

### 2.6 分析类问题（/api/analyze）

**用户故事**：作为业务主管，我想要在看完数据后追问"为什么交易量增长了"（分析类问题），以便系统自动分析原因并给出文字解释。

**验收标准**：
1. 前端检测用户输入是否包含"为什么/原因/分析/怎么回事/解释"关键词
2. 匹配时路由到 `/api/analyze` 接口（而非 `/api/query`）
3. `/api/analyze` 执行三阶段流水线：
   - **规划阶段**：LLM 判断需要哪些额外查询数据，输出 JSON 格式的 `queries` 数组
   - **执行阶段**：后端依次执行规划出的查询（最多 3 条），每条经过解析→构建 SQL→执行
   - **合成阶段**：将所有数据喂给 LLM，生成中文分析总结
4. 分析结果以纯文本模式展示（`mode: 'analysis'`），不含图表/表格
5. LLM 未配置时返回友好提示"LLM 未配置，无法进行分析"

**实现文件**：`backend/app.py`（`api_analyze`）、`frontend/src/App.vue`（`handleSend` 中的 isAnalytical 判断）

---

### 2.7 暗色主题 + 左侧导航栏 + 首页快捷引导

**用户故事**：作为业务人员，我想要一个视觉舒适、导航清晰的界面，以便快速上手使用。

**验收标准**：
1. 全局暗色主题（`darkTheme`），CSS 变量定义：`--bg-primary: #0f172a`、`--bg-card: #1e293b`、`--bg-sidebar: #0b1120` 等
2. 左侧 56px 宽导航栏（`Sidebar.vue`），包含：
   - Logo 图标
   - 三个 Agent 图标（BI / 询报价 / 风控，后两个禁用态）
   - 底部：查询历史按钮（展开面板）、规则管理按钮（跳转管理页）
3. 首次进入（无消息时）展示 `WelcomeGuide.vue`：6 个快捷引导芯片，覆盖交易量/排名/套保率/趋势/同比/客户维度
4. 输入区支持多行输入（最多 4 行，最大 2000 字符），Enter 发送，Shift+Enter 换行
5. 点击芯片或输入查询后，WelcomeGuide 消失，进入对话视图

**实现文件**：`frontend/src/App.vue`、`frontend/src/components/Sidebar.vue`、`frontend/src/components/WelcomeGuide.vue`、`frontend/src/components/InputArea.vue`

---

### 2.8 规则管理后台

**用户故事**：作为系统管理员，我想要在一个可视化界面中管理业务规则（关键词到映射值的对应关系），以便无需修改代码就能维护和调整规则。

**验收标准**：

**5 个规则分类**：
| 分类 ID | 显示名称 | 映射逻辑 |
|---------|----------|----------|
| `app_id` | 产品类型映射 | 关键词 → appid（1=外汇, 2=结售汇） |
| `buy_sell_direction` | 买卖方向映射 | 关键词 → direction(B/S) + 客户视角反转方向 |
| `product_type` | 交易类型映射 | 关键词 → product_type（spot/fwd/swap/all） |
| `special_trade_type` | 特殊交易类型映射 | 关键词 → SPECIALSTATE / SPECTRADECLASS 值 |
| `time_expressions` | 时间表达式映射 | 表达式模式 → 起止日期计算规则 |

**功能清单**：
1. 左侧 Agent 筛选下拉框（全部/公共/BI/询报价/风控）
2. 左侧分类列表，显示每个分类的规则数和启用数
3. 右侧展示选中分类的所有规则卡片
4. 每条规则卡片显示：关键词 Tag、映射值 Badge、优先级、铁律标记、启用/禁用状态
5. 新增/编辑规则弹窗：根据分类动态展示对应表单字段（纯表单，零 JSON）
6. 软删除（set `is_active=0`），支持一键启用/禁用
7. 规则预览测试：输入测试语句，实时查看规则解析结果和置信度
8. 热部署按钮：清除后端规则缓存，使修改立即生效
9. 版本历史：每次修改自动创建快照版本，支持一键回滚到任意历史版本

**实现文件**：`backend/admin_routes.py`、`backend/db/sqlite_store.py`、`frontend/src/views/AdminRules.vue`

---

### 2.9 规则热部署 + 版本回滚

**用户故事**：作为系统管理员，我修改规则后想要立即生效，并且能在出错时回滚到之前的版本。

**验收标准**：
1. 管理后台修改规则后，点击"热部署"调用 `/api/admin/rules/reload`
2. 热部署操作：`reload_rules()` 清除内存缓存 + `invalidate_cache()` 清除 System Prompt 缓存
3. 每次修改规则时自动创建快照版本（`rule_versions` 表），版本号自增
4. 版本列表展示版本号和创建时间
5. 回滚操作：删除当前分类所有规则，从快照 JSON 重新插入

**实现文件**：`backend/admin_routes.py`（`_backup_category`、`rollback_category`、`_reload_all`）、`backend/db/sqlite_store.py`

---

### 2.10 记忆持久化（SQLite）

**用户故事**：作为系统，我需要持久化会话数据和历史查询记录，以便跨请求恢复上下文和分析使用模式。

**验收标准**：
1. SQLite 数据库文件 `backend/data/smartbi.db`，使用 WAL 模式 + 外键约束
2. 6 张核心表：
   - `rule_categories`：规则分类定义
   - `rule_items`：规则条目（keywords + rule_data + is_ironclad + priority）
   - `rule_versions`：分类版本快照
   - `sessions`：会话记录（session_id + agent_type + user_id）
   - `turns`：对话轮次（user_query + parsed_params + executed_sql + result_summary）
   - `memory_summaries`：记忆摘要（周期性的对话压缩）
3. 首次启动自动迁移：从 `semantic_rules.json` 导入规则到 SQLite
4. `AgentMemory` 类提供高层 API：`ensure_session` / `add_turn` / `get_context` / `build_context_prompt` / `should_summarize`
5. 简单相似查询检索：通过字面关键词重叠度匹配历史查询

**实现文件**：`backend/db/sqlite_store.py`、`backend/memory/store.py`

---

## 3. 非功能需求

### 3.1 性能要求

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 规则解析耗时 | < 1ms | 纯内存关键词匹配，无 IO |
| 规则+LLM 全链路 | < 5s | LLM 调用超时 30s/60s |
| SQLite 操作耗时 | < 10ms | WAL 模式，读写不互斥 |
| Oracle 查询耗时 | < 2s | 依赖数据库索引和查询复杂度 |
| 前端首屏渲染 | < 2s | Vite 构建产物，Gzip 压缩 |
| 并发支持 | 20 QPS | FastAPI + uvicorn 异步 |

### 3.2 安全要求

1. **SQL 注入防护**：所有 SQL 通过 `TradeQueryBuilder` 类参数化构建，使用 f-string 仅用于表名/字段名（来自固定映射，非用户输入）
2. **密码保护**：`.env` 文件不进入 Git 版本控制（已在 `.gitignore` 中），环境变量通过 `python-dotenv` 注入
3. **API 鉴权**（当前未实现，规划中）：Admin API 需要登录态保护
4. **输入校验**：前端限制输入 2000 字符，后端对 `top_n`（1-100）、`buy_sell`（B/S）、`product_type`（spot/fwd/swap/all）等参数有严格校验

### 3.3 可用性要求

1. **优雅降级**：LLM 未配置或调用失败时，自动回退到规则引擎结果
2. **友好错误提示**：数据库连接失败时返回中文错误信息，前端展示错误卡片
3. **连接状态指示**：前端顶部 Header 显示后端连接状态（检查中/已连接/已断开）
4. **拼音/错别字容错**（当前未实现，规划中）：LLM 可部分处理，规则引擎暂不支持

### 3.4 可维护性要求

1. **规则与代码分离**：业务规则存储在 SQLite 中，通过管理后台修改，无需重启服务
2. **自动版本管理**：每次修改自动创建快照，支持一键回滚
3. **可观测性**：Python `logging` 记录关键路径日志，格式含时间戳和模块名
4. **热部署**：管理员修改规则后点击"热部署"即生效，不影响在线服务

---

## 4. 数据模型

### 4.1 Oracle 数据源（只读）

#### 交易视图

| 视图名 | 产品类型 | 关键字段 |
|--------|----------|----------|
| `XF_FX_SPOTTRADE_VIEW` | 即期(spot) | USDAMOUNT, TRADEDATE, TRADESTATUS, SPECIALSTATE, APPID, BUYORSELL, BANKID, CUSTNAME, CUSTOMERID, CUSTMAINMANAGER, CUSTMANAGERNAME |
| `XF_FX_FWDTRADE_VIEW` | 远期(fwd) | 同上 |
| `XF_FX_SWAPTRADE_VIEW` | 掉期(swap) | 同上 |

#### 机构信息表

| 表名 | 关键字段 |
|------|----------|
| `XF_BASE_BANK` | BANKID, DIPNAME（机构名称） |

#### 通用字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `USDAMOUNT` | NUMBER | 交易金额（美元） |
| `TRADEDATE` | NUMBER(8) | 交易日期（YYYYMMDD） |
| `TRADESTATUS` | NUMBER | 交易状态（0=正常） |
| `SPECIALSTATE` | NUMBER | 特殊状态码（1=逾期, 3=展期, 4=提前交割, 5=平仓） |
| `APPID` | NUMBER | 业务系统（1=外汇, 2=结售汇） |
| `BUYORSELL` | CHAR(1) | 买卖方向（B=银行买入/结汇, S=银行卖出/购汇） |
| `BANKID` | NUMBER | 机构 ID |
| `CUSTNAME` | VARCHAR2 | 客户名称 |
| `CUSTOMERID` | NUMBER | 客户号 |
| `CUSTMAINMANAGER` | NUMBER | 客户经理 ID |
| `CUSTMANAGERNAME` | VARCHAR2 | 客户经理名称 |

### 4.2 SQLite 规则存储

#### rule_categories（规则分类）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `agent_type` | TEXT | common / bi / quoting / risk |
| `category` | TEXT | app_id / buy_sell_direction / product_type / special_trade_type / time_expressions / comparison_modifiers |
| `display_name` | TEXT | 中文显示名 |
| `priority` | INTEGER | 排序权重 |

#### rule_items（规则条目）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `category_id` | INTEGER FK | 关联分类 |
| `keywords` | TEXT(JSON) | 关键词数组，如 `["结汇", "结汇交易"]` |
| `rule_data` | TEXT(JSON) | 规则映射数据，含 direction/value/sub_type 等 |
| `is_ironclad` | INTEGER | 是否铁律（不可被客户前缀反转或 AI 覆盖） |
| `priority` | INTEGER | 匹配优先级（数字越小越优先） |
| `is_active` | INTEGER | 启用状态（0=禁用, 1=启用） |

#### rule_versions（版本快照）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `category_id` | INTEGER FK | 关联分类 |
| `version_num` | INTEGER | 版本号（自增） |
| `snapshot` | TEXT(JSON) | 完整快照（该分类所有规则的 JSON 数组） |

### 4.3 SQLite 记忆存储

#### sessions（会话）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 会话 ID（UUID） |
| `agent_type` | TEXT | bi / quoting / risk |
| `user_id` | TEXT | 用户标识 |
| `is_active` | INTEGER | 活跃状态 |

#### turns（对话轮次）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `session_id` | TEXT FK | 关联会话 |
| `turn_index` | INTEGER | 轮次序号 |
| `user_query` | TEXT | 用户原始查询 |
| `parsed_params` | TEXT(JSON) | 解析后的结构化参数 |
| `executed_sql` | TEXT | 实际执行的 SQL |
| `result_summary` | TEXT | 结果摘要 |

#### memory_summaries（记忆摘要）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `session_id` | TEXT FK | 关联会话 |
| `scope` | TEXT | session（会话级）|
| `summary_type` | TEXT | 摘要类型 |
| `content` | TEXT(JSON) | 摘要内容 |
| `source_turns` | TEXT | 来源轮次范围 |

---

## 5. API 接口规格

### 5.1 公共接口

#### GET /api/health

健康检查。

| 请求 | 响应 |
|------|------|
| 无参数 | `{"status": "ok"}` |

---

#### POST /api/parse

解析自然语言为结构化参数（不执行 SQL）。

**请求体**：
```json
{
  "text": "本月结汇交易量",
  "context": [{"role": "user", "content": "..."}]
}
```

**响应**：
```json
{
  "params": {
    "product_type": "all",
    "date_start": "2026-05-01",
    "date_end": "2026-05-15",
    "special_states": "",
    "buy_sell": "B",
    "bank_name": "",
    "cust_name": "",
    "aggregate": true,
    "top_n": null,
    "amount_filter": null,
    "dimension": "bank",
    "hedge_ratio": false,
    "appid": 2,
    "comparison": ""
  },
  "pipeline": "rule(confidence=100%)",
  "confidence": 1.0
}
```

---

#### POST /api/query

执行完整的自然语言查询流程：解析 → 构建 SQL → 执行 → 结果增强。

**请求体**：
```json
{
  "text": "本月结汇交易量",
  "params": { ... }
}
```

**响应**：
```json
{
  "sql": "WITH matched_banks AS (...)...",
  "params": { ... },
  "columns": ["TOTAL_AMOUNT", "TRADE_COUNT"],
  "rows": [[1234567.89, 42]],
  "row_count": 1,
  "comparison": null,
  "summary": "2026-05-01 ~ 2026-05-15全市场，交易总量12.35万美元，共42笔。",
  "chartOption": { ... },
  "insights": [ ... ],
  "error": ""
}
```

`comparison` 对象结构（有对比数据时）：
```json
{
  "type": "yoy",
  "label": "同比",
  "current_period": "2026-05-01 ~ 2026-05-15",
  "compare_period": "2025-05-01 ~ 2025-05-15",
  "current_amount": 1234.57,
  "compare_amount": 987.65,
  "change_amount": 246.92,
  "change_rate": 25.0
}
```

---

#### POST /api/analyze

分析类问题：LLM 自主规划查询 → 执行 → 合成分析。

**请求体**：
```json
{
  "text": "为什么这个月交易量增长了",
  "context": [...],
  "previous_data": { "columns": [...], "rows": [...], ... }
}
```

**响应**：
```json
{
  "summary": "根据数据分析，本月交易量增长25%主要由以下因素驱动：1) A银行交易量增长..."
}
```

---

#### POST /api/reload-rules

强制刷新规则缓存（与 Admin 热部署功能等效）。

**响应**：`{"status": "ok", "message": "Rules and prompt cache refreshed"}`

---

### 5.2 管理后台接口（/api/admin）

Base URL: `/api/admin`

#### GET /rules/categories

列出所有规则分类。

**查询参数**：`agent_type`（可选，过滤 Agent 类型）

**响应**：
```json
{
  "categories": [
    { "id": 1, "agent_type": "common", "category": "app_id", "display_name": "产品类型映射", "priority": 0, "item_count": 5, "active_count": 5 }
  ]
}
```

---

#### GET /rules/categories/{category_id}/items

获取分类下的所有规则条目。

**响应**：`{"category": {...}, "items": [...]}`

---

#### POST /rules/categories/{category_id}/items

新增规则条目。

**请求体**：
```json
{
  "keywords": ["结汇", "结汇交易"],
  "rule_data": {"direction": "B", "description": "铁律：结汇=银行买入"},
  "is_ironclad": true,
  "priority": 0
}
```

**校验规则**：
- 关键词不能在同类中重复
- 特殊状态值仅限 1/3/4/5
- 交易类别值仅限 0,1,2,3,4,5,6,7,10,11,12,13,14,15,16,17
- 产品类型值仅限 spot/fwd/swap/all
- 买卖方向规则必须填写 direction 字段

---

#### PUT /rules/items/{item_id}

更新规则条目。body 参数同 create，所有字段可选。

---

#### DELETE /rules/items/{item_id}

软删除规则条目（设置 is_active=0）。

---

#### GET /rules/categories/{category_id}/versions

获取分类的版本历史（最近 50 个版本）。

---

#### POST /rules/categories/{category_id}/rollback

回滚到指定版本。查询参数：`version_num`。

---

#### POST /rules/preview

预览规则解析结果。

**请求体**：`{"text": "北京分公司今年一季度结汇交易量"}`

**响应**：
```json
{
  "text": "...",
  "rule_parsed": {...},
  "confidence": 1.0,
  "would_skip_llm": true,
  "after_gatekeep": {...}
}
```

---

#### POST /rules/reload

热部署：清除所有规则缓存和 Prompt 缓存。

---

## 6. 业务规则

### 6.1 买卖方向铁律

买卖方向遵循"银行视角"映射，分为铁律规则和可反转规则两类：

**铁律规则**（不可被客户前缀反转，`customer_reversible=false`）：

| 关键词 | 方向 | appid |
|--------|------|-------|
| 结汇 | B（银行买入） | 2（结售汇） |
| 购汇 | S（银行卖出） | 2（结售汇） |
| 售汇 | S（银行卖出） | 2（结售汇） |

**可反转规则**（`customer_reversible=true`）：当查询包含"客户"前缀时，方向反转为 `customer_direction`：

| 关键词 | 默认方向（非客户视角） | 反转方向（客户视角） |
|--------|------------------------|----------------------|
| 买入 / 近卖远买 | B | S |
| 卖出 / 近买远卖 | S | B |

**结售汇特例**："结售汇"同时包含结汇+售汇 → `buy_sell=""`（不筛选方向）、`appid=2`

### 6.2 时间表达式优先级（13 级）

| 优先级 | 表达式模式 | 示例 | 输出 |
|--------|-----------|------|------|
| 1 | `YYYY-MM-DD 到 YYYY-MM-DD` | "2026-01-01 到 2026-03-31" | 精确区间 |
| 2 | `YYYY年MM月DD日` | "2026年3月15日" | 单日 |
| 3 | `YYYY年MM月` | "2026年3月" | 月初至月末 |
| 4 | `今年N月` | "今年3月" | 当月全月 |
| 4.5 | `今年N季度` / `今年第N季度` | "今年一季度" | 当季全季 |
| 5 | `今年` / `本月` | "本月" | 月初至今 |
| 6 | `本周` | "本周" | 周一至今 |
| 7 | `上旬` / `中旬` / `下旬` | "上旬" | 隐含本月 |
| 8 | `昨天` | "昨天" | 单日 |
| 9 | `今天` | "今天" | 单日 |
| 9.5 | `第N季度` / `N季度` | "一季度" | 隐含今年当季 |
| 10 | `上月` / `上个月` | "上月" | 上月全月 |
| 10 | `近N个月` | "近3个月" | N月前至今 |
| 11 | `近N年` | "近2年" | N年前至今 |
| 12 | `近N天` | "近30天" | N天前至今 |
| 13 | `本季度` | "本季度" | 当季初至今 |

### 6.3 特殊状态码

| 状态码 | 含义 | 触发关键词 |
|--------|------|-----------|
| （空） | 正常交易 | 无关键词时默认排除特殊状态 |
| 1 | 逾期 | "逾期"、"已过期" |
| 3 | 展期 | "展期"、"延期" |
| 4 | 提前交割 | "提前交割"、"提前交收" |
| 5 | 平仓 | "平仓"、"已平仓" |

**重要**：
- 没有"挂账"状态（不存在状态码 2）
- "在途"不是 SPECIALSTATE 字段，在途 = totaldelivery 表剩余金额 > 0
- 套保率查询默认排除特殊状态交易（`SPECIALSTATE=0`）

### 6.4 交易类别码（SPECTRADECLASS）

交易类别采用两遍匹配策略：先精确匹配（长关键词优先），无匹配时使用泛化规则。

**精确匹配**（部分）：
- "全部平仓" → 6
- "提前平仓" → 1,10
- "原价展期" → 5
- "近端提前交割" → 16
- "普通交易" / "正常交易" → 0

**泛化规则**：
- 含"平仓"或"平盘" → 1,2,6,7,10,11,15,17
- 含"展期" → 3,5,12,13
- 含"提前交割" → 4,16

### 6.5 统计维度

维度判断优先级（长关键词优先）：

| 优先级 | 维度 | 关键词 | 分组字段 |
|--------|------|--------|----------|
| 1 | customer_id | 客户号/客户编号/客户ID | t.CUSTOMERID |
| 2 | manager | 客户经理ID/客户经理编号 | t.CUSTMAINMANAGER |
| 3 | manager_name | 客户经理名称/客户经理姓名/客户经理 | t.CUSTMANAGERNAME |
| 4 | customer | 客户名称/客户（不含上述精确匹配） | t.CUSTNAME |
| 5（默认） | bank | 无客户关键词时 | b.DIPNAME |

---

## 7. 前端页面结构

### 7.1 整体布局

```
┌─────────┬─────────────────────────────────────┐
│         │  StatusHeader（连接状态）             │
│         ├─────────────────────────────────────┤
│ Sidebar │                                     │
│         │  MessageArea / WelcomeGuide         │
│ 56px    │  （对话消息区域 / 首次欢迎引导）        │
│         │                                     │
│         ├─────────────────────────────────────┤
│         │  InputArea（查询输入 + 发送按钮）      │
└─────────┴─────────────────────────────────────┘
```

### 7.2 组件树

```
App.vue
├── NConfigProvider (zhCN + darkTheme)
│   └── NMessageProvider
│       ├── Sidebar.vue
│       │   ├── Logo
│       │   ├── Agent 图标 (BI/询报价/风控)
│       │   ├── 查询历史按钮 + 展开面板
│       │   └── 规则管理按钮 (→跳转 AdminRules)
│       ├── StatusHeader.vue (连接状态指示)
│       ├── [viewMode === 'chat']
│       │   ├── WelcomeGuide.vue (无消息时)
│       │   │   └── 6 个快捷引导芯片
│       │   ├── MessageArea.vue (有消息时)
│       │   │   ├── BotMessage.vue
│       │   │   │   ├── ResultCard.vue
│       │   │   │   │   ├── 摘要文本
│       │   │   │   │   ├── 同比/环比对比卡片
│       │   │   │   │   ├── ChartView.vue (ECharts 图表)
│       │   │   │   │   ├── InsightPanel.vue (洞察卡片)
│       │   │   │   │   └── ResultPanel.vue (数据/SQL/参数 Tab)
│       │   │   │   ├── ConfirmCard.vue (参数确认卡片, 已注释)
│       │   │   │   └── 分析文本 (analysis mode)
│       │   │   └── 用户消息
│       │   └── InputArea.vue (NInput textarea + NButton)
│       └── [viewMode === 'admin']
│           └── AdminRules.vue
│               ├── Agent 筛选下拉框
│               ├── 分类导航列表 (左侧 200px)
│               ├── 规则卡片列表 (右侧)
│               ├── 编辑弹窗 (按分类展示不同表单)
│               ├── 版本历史弹窗
│               └── 预览测试面板 (底部折叠)
```

### 7.3 路由

当前为单页应用（SPA），无 vue-router，通过 `viewMode` 控制视图切换：

- `viewMode='chat'`：对话查询界面（默认）
- `viewMode='admin'`：规则管理后台

### 7.4 消息模式

`messages` 数组中每条消息包含 `type` + `mode`：

| type | mode | 说明 |
|------|------|------|
| `'user'` | — | 用户消息 |
| `'bot'` | `'loading'` | 加载中 |
| `'bot'` | `'result_card'` | 四段式结果卡片 |
| `'bot'` | `'analysis'` | 分析类问题回复 |
| `'bot'` | `'error'` | 错误提示 |
| `'bot'` | `'confirm'` | 参数确认卡片（已注释，当前跳过直接查询） |

### 7.5 前端 API 层

```javascript
// api.js
checkHealth()        → GET  /api/health
parseQuery(text, ctx) → POST /api/parse
executeQuery(params) → POST /api/query
// /api/analyze 在 App.vue handleSend 中直接 fetch
```

---

## 附录 A. 环境依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.x | 后端运行环境 |
| FastAPI | 0.115.0 | API 框架 |
| uvicorn | 0.30.0 | ASGI 服务器 |
| python-oracledb | 4.0.0 | Oracle 连接（需要 Instant Client） |
| openai | >=2.36.0 | OpenAI-compatible 客户端（调用 LLM） |
| python-dotenv | >=1.0.0 | 环境变量管理 |
| langchain | >=1.2.18 | Agent 框架（规划中） |
| Vue | 3.x | 前端框架 |
| Naive UI | 2.40+ | UI 组件库 |
| Vite | 5.4 | 构建工具 |

## 附录 B. 环境变量

```env
LLM_API_KEY=sk-xxx                           # LLM API 密钥
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1  # API 端点
LLM_MODEL=glm-5.1                            # 模型名称
DB_HOST=192.168.10.184                       # Oracle 主机
DB_PORT=1521                                 # Oracle 端口
DB_SERVICE=orclutf                           # Oracle 服务名
DB_USER=xfunds40                             # 数据库用户
DB_PASSWORD=xfunds40                         # 数据库密码
```

## 附录 C. 关键文件索引

| 文件路径 | 功能 |
|----------|------|
| `backend/app.py` | FastAPI 主应用 + 所有 API 端点 + 结果增强函数 |
| `backend/admin_routes.py` | 管理后台 API（CRUD + 预览 + 热部署 + 版本回滚） |
| `backend/llm_parser/parser.py` | 规则引擎解析器（关键词匹配 + 置信度计算） |
| `backend/llm_parser/llm_client.py` | LLM API 客户端 |
| `backend/llm_parser/rules_engine.py` | Gatekeep 守门逻辑（铁律校验 + 规则回退） |
| `backend/llm_parser/prompt_builder.py` | System Prompt 构建器（含上下文注入 + 缓存） |
| `backend/db/query_builder.py` | 5 种 SQL 路由构建器 |
| `backend/db/connection.py` | Oracle 连接管理 |
| `backend/db/config.py` | 数据库配置类 |
| `backend/db/sqlite_store.py` | SQLite 持久化（规则 + 记忆 + 自动迁移） |
| `backend/memory/store.py` | Agent 记忆层高层 API |
| `frontend/src/App.vue` | Vue 根组件（路由控制 + 对话逻辑） |
| `frontend/src/api.js` | 前端 API 调用封装 |
| `frontend/src/constants.js` | 前端常量（列名映射、选项列表、格式化函数） |
| `frontend/src/views/AdminRules.vue` | 规则管理后台页面 |
| `frontend/src/components/Sidebar.vue` | 左侧导航栏 |
| `frontend/src/components/WelcomeGuide.vue` | 首页快捷引导 |
| `frontend/src/components/ResultCard.vue` | 四段式结果卡片容器 |
| `frontend/src/components/ResultPanel.vue` | 数据表格 + SQL + 参数 Tab |
| `frontend/src/components/ChartView.vue` | ECharts 图表 |
| `frontend/src/components/InsightPanel.vue` | 数据洞察卡片 |
| `frontend/src/components/ConfirmCard.vue` | 参数确认表单（当前已跳过） |
| `frontend/src/components/InputArea.vue` | 查询输入区域 |
