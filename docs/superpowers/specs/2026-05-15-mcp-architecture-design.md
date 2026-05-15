# Smart BI MCP 架构改造设计说明书

> 版本：v4.0 | 日期：2026-05-15 | 状态：待实现 | Phase 1/4

---

## 设计原则

本项目定位为**银行生产级**代客交易 AI 平台，所有设计决策遵循以下原则：

| # | 原则 | 强制级别 |
|---|------|---------|
| 1 | 数据 100% 准确性 — 宁可不做，不能做错 | 硬约束 |
| 2 | 性能与反馈时间 — 渐进式反馈，缓存优先 | 硬约束 |
| 3 | 输出专业友好 — 术语统一，错误脱敏 | 硬约束 |
| 4 | 扩展容易 — 配置驱动，新 Agent 不改核心代码 | 目标 |
| 5 | 代码可读性 — 强类型接口，决策点注释 WHY | 目标 |
| 6 | 审计完整 — 全链路记录，满足银行合规 | 硬约束 |

---

## 1. 核心原则

```
宁可不做，不能做错。

┌─────────────────────────────────────────┐
│  Router 决策流程图                        │
│                                         │
│  用户输入 → 混合路由打分                   │
│           │                              │
│           ├─ 高置信度(≥阈值) → SQL校验→执行 │
│           ├─ 中等置信度 → 追问确认          │
│           └─ 低置信度/超出能力 → 拒答        │
└─────────────────────────────────────────┘
```

---

## 2. 总体架构

```
                        ┌──────────────────────┐
                        │     前端 (Vue 3)       │
                        │  SSE 接收 / 确认卡交互  │
                        └──────────┬───────────┘
                                   │ HTTPS + SSE
                        ┌──────────┴───────────┐
                        │   FastAPI 网关层       │
                        │  认证·鉴权·限流·静态    │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┴──────────────────────┐
              │         Agent 编排层 (LangGraph)            │
              │                                            │
              │  Gateway Adapter                           │
              │       │                                    │
              │  Context Resolver  ← LLM 分析全部对话        │
              │       │                                    │
              │  Router  ← 混合路由 + 三层门禁               │
              │       │                                    │
              │  SQL Validator  ← 规则引擎重建 SQL(防幻觉)   │
              │       │                                    │
              │  Execution Engine  ← DAG 串行/并行          │
              │       │                                    │
              │  Result Validator  ← 空集/异常/量级校验      │
              │       │                                    │
              │  Response Formatter ← 脱敏/格式化/术语统一   │
              │                                            │
              └──┬──────────┬──────────┬──────────────────┘
                 │          │          │
            ┌────┴───┐ ┌───┴───┐ ┌───┴────────┐
            │  BI    │ │询报价  │ │ 风控/合规.. │
            │ Agent  │ │Agent  │ │             │
            └───┬────┘ └───────┘ └─────────────┘
                │
   ┌────────────┴────────────────────┐
   │         MCP 工具层 (FastMCP)      │
   │  Oracle查询 · MySQL · LLM · 缓存   │
   └─────────────────────────────────┘
                │
   ┌────────────┴────────────────────┐
   │         数据与基础设施             │
   │  Oracle · MySQL · Redis · 审计    │
   └─────────────────────────────────┘
```

### 各层职责

| 层 | 框架 | 做什么 | 不做什么 |
|----|------|--------|---------|
| 网关层 | FastAPI | 认证、鉴权、限流、SSE 推送、静态文件 | 不解析业务、不知道有哪些 Agent |
| 编排层 | LangGraph 1.1 | Context Resolver、Router、SQL Validator、DAG 执行、Result Validator、Response Formatter | 不直接连数据库 |
| 工具层 | FastMCP | 暴露 Oracle/MySQL/LLM/Cache 为标准工具 | 不做业务编排 |
| 数据层 | Oracle+MySQL+Redis | 持久化、缓存、审计日志 | 不做业务逻辑 |

---

## 3. Context Resolver — 上下文解析器

### 3.1 为什么不能简单取上一条

上下文继承必须是 LLM 分析**全部对话**后智能推断。以下四个场景说明复杂度：

```
场景 A：同一主题多轮（应该继承）
  T1: "本月工行交易量"        → { date: 2026-05, bank: "工行" }
  T2: "农行呢"                → 继承 date，只换 bank
  T3: "同比增加多少"           → 继承 T1/T2 的 date+bank，加 comparison
  → LLM 输出：date=本月, bank=农行, comparison=yoy

场景 B：主题切换（不应继承）
  T1: "本月工行交易量"        → { date: 2026-05, bank: "工行" }
  T2: "美元即期汇率多少"      → 主题切换为汇率，不应继承 bank
  T3: "同比增加多少"           → 需要 LLM 判断"同比谁"
  → LLM 输出：date=本月, comparison=yoy, 实体不确定 → needs_confirm

场景 C：跨度继承
  T1: "今年一季度交易量"      → { date: 2026-01~03 }
  T2: "排名前5的银行"         → 继承 date
  T3: "它们的套保率呢"        → 继承 date + 排名银行
  T4: "跟去年同比"             → 继承全部 + comparison
  → LLM 输出：date=一季度, banks=前5, comparison=yoy

场景 D：指代消解
  T1: "工行和农行本月交易量"  → { banks: ["工行","农行"], date: 本月 }
  T2: "中行呢"                → "呢" = 加入对比，非替换
  → LLM 输出：banks=["工行","农行","中行"], date=本月
```

### 3.2 Context Resolver 实现

编排层 DAG 中，Router 之前执行：

```
Gateway Adapter → Context Resolver → Router → SQL Validator → ...
                       │
                       ├─ 输入: session_id, text, full_history (最近 20 轮)
                       ├─ 输出: resolved_params (含继承的完整参数)
                       └─ 实现: LLM 分析 + 结构化输出
```

**给 LLM 的系统提示：**

```
你是对话上下文分析器。根据完整对话历史，推断当前查询的完整参数。

## 上下文继承规则
1. 如果当前查询的实体/日期/维度为空，向前查找最近的相关轮次
2. 如果中途切换了主题（如从交易量→汇率），不要继承无关参数
3. "呢""它们的""也""还是"等词表示承接上文
4. 不确定的参数留空，不要猜
5. 如果历史上讨论了多个主题，优先匹配最近的主题

## 完整对话历史
{history}

## 当前查询
{text}

## 输出 JSON
{
  "resolved": { ... },
  "inherited_fields": ["date_start", "date_end"],
  "confidence": 0.95,
  "needs_confirm": []
}
```

### 3.3 输出处理

```
Context Resolver 输出
  │
  ├─ needs_confirm 非空 → 返回确认卡
  │   例: ["entity"] → "您想查哪家银行或客户的同比数据？"
  │
  ├─ confidence < 0.8  → LLM 二次确认
  │
  └─ confidence >= 0.8 → 传给 Router
```

---

## 4. Router 安全决策框架

### 4.1 三层门禁

每个查询必须通过三道门禁才能执行：

```
门禁 1: 关键词匹配 → 门禁 2: 领域边界校验 → 门禁 3: 参数完整性
```

**通过示例：**
```
"本月工行交易量"
  门禁 1: BI 命中 "交易量""工行" → 得分 3，其他 0，差距 ≥2 ✓
  门禁 2: 银行列表含"工商银行" ✓，日期范围合理 ✓
  门禁 3: 参数齐全 ✓
  → 路由 BI Agent → 执行
```

**拒答示例：**
```
"帮我预测下个月美元走势"
  门禁 1: 所有 Agent 得分 0-1 ⚠
  门禁 2: "预测"命中所有 Agent 的 NOT_capabilities ✗
  → 拒答："抱歉，我目前不支持趋势预测。可以查询历史交易数据或汇率报价。"
```

**追问示例：**
```
"工行最近的异常交易有哪些"
  门禁 1: BI=1, 风控=1，差距 <2 ⚠
  门禁 2: LLM 判断偏向风控
  门禁 3: 风控 Agent 已实现 ✓
  → 追问确认："你是想查交易量还是看异常情况？"
```

### 4.2 并行硬条件

三个必要条件缺一不可：

| 条件 | 说明 |
|------|------|
| ✅ 每个子问题独立通过门禁 | 拆开的每一部分都能独立执行 |
| ✅ 子问题之间零依赖 | 共享只读数据不算依赖 |
| ✅ 每个子 Agent 不超出能力边界 | 对照 NOT_capabilities |

**通过：** "对比工行、农行、中行交易量" → 3 个独立 BI 查询 → 并行
**拒答：** "对比工行本月和下月预估交易量" → "预估"超出能力 → 只执行第一部分

### 4.3 串行硬条件

| 条件 | 说明 |
|------|------|
| ✅ 第一步独立通过门禁 | 不依赖后续 |
| ✅ 第二步依赖第一步的具体字段 | 字段名明确，非模糊依赖 |
| ✅ 第一步输出 schema 第二步可消费 | 无需 LLM 自由格式转换 |

**通过：** "农行本月下降了多少，什么原因" → BI 查数据 → 风控分析原因
**追问：** "工行为什么下降了" → 先追问"同比还是环比"

### 4.4 Agent 能力声明

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
        ],
        "NOT_capabilities": [
            "预测、预估、趋势分析",
            "风险评估、异常检测",
            "汇率实时报价",
            "客户信用评估",
        ],
    },
    # ... 其余 Agent 同理
}
```

### 4.5 Router 三种输出

```python
# 成功路由
{ "status": "ok", "plan": "single", "agent": "BI", "confidence": 0.95 }

# 拒答
{ "status": "rejected", "reason": "out_of_scope",
  "message": "抱歉，我目前不支持预测类查询",
  "suggestions": ["本月工行交易量", "美元即期汇率"] }

# 追问
{ "status": "confirm", "reason": "ambiguous",
  "message": "你是想查交易量还是看异常情况？",
  "options": [{"agent": "BI", "query": "工行本月交易量"},
              {"agent": "风控", "query": "工行异常交易"}] }
```

---

## 5. SQL Validator — 数据准确性保障

### 5.1 为什么需要

LLM 可以规划查询，但**绝对不能直接输出 SQL**。LLM 幻觉可能产生：
- 拼错的表名、字段名
- 错误的 WHERE 条件
- 不存在的视图

### 5.2 校验流程

```
Agent 输出查询意图 (不是 SQL)
  │
  ▼
SQL Validator:
  1. 意图 → 通过 TradeQueryBuilder 重建 SQL（不信任 LLM 原文）
  2. SQL 白名单校验：表名必须在 VIEW_MAP 中
  3. WHERE 条件字段必须在 COMMON_FIELDS 中
  4. 危险关键字检测：DROP/ALTER/TRUNCATE/INSERT/UPDATE/DELETE
  5. 参数化验证：所有值都通过 %s 占位符绑定
  │
  ├─ 通过 → 执行
  └─ 不通过 → 拒答 + 记录审计日志
```

### 5.3 结果校验

```
Oracle 返回后：
  1. 空集检查 → "未查询到符合条件的数据"
  2. 异常值检测 → 单值偏离均值 10σ 以上 → 标记可疑
  3. 数量级校验 → 同比变化 >500% → 二次确认查询
  4. 对比数据一致性 → 同期对比基数为 0 → 标为"不可比"
```

---

## 6. 性能与缓存

### 6.1 缓存分层

```
L1: 内存缓存 (进程级)
  规则库 → 加载后缓存，Admin API 修改时主动失效
  Agent 注册表 → 启动加载，yaml 变更时热重载

L2: 查询结果缓存
  按 params hash → Redis (TTL 60s)
  命中条件：相同 params hash + 时间差 < TTL
  不缓存：实时汇率类查询

L3: 会话上下文
  LangGraph State → 同一 session 内共享
  跨 session 隔离
```

### 6.2 超时与熔断

| 资源 | 超时 | 熔断 |
|------|------|------|
| Oracle 查询 | 10s | 连续 3 次超时 → 熔断 60s |
| MySQL 查询 | 3s | 连续 3 次失败 → 告警 |
| LLM 调用 | 30s | 连续 3 次超时 → 降级规则模式 |
| MCP 工具 | 15s | 超时返回部分结果 |

### 6.3 渐进式反馈（SSE 推送）

```
阶段 1 (100ms):  "正在理解您的问题..."
   → Context Resolver 完成

阶段 2 (500ms):  "正在查询 {银行} {时间} 数据..."
   → Router 完成，显示命中的 Agent 和参数

阶段 3 (2s):     "正在分析对比..."
   → Oracle 查询执行中

阶段 4 (100ms):  "整理结果..."
   → 格式化、脱敏、生成摘要

异常时:          "查询时间较长，预计还需 {n} 秒..."
   → 超时前 3s 预警
```

---

## 7. 输出规范

### 7.1 错误脱敏

```
内部错误              → 对外输出
ORA-00942: table...   → 暂时无法查询该数据，请稍后再试
ORA-12170: timeout    → 数据查询超时，正在重试...
DPI-1047: client...   → 系统维护中，请稍后再试
LLM API timeout       → 智能解析暂时不可用，已用规则模式处理
MySQL connection...   → 配置数据加载异常，已通知管理员
```

### 7.2 数字格式

| 类型 | 格式 | 示例 |
|------|------|------|
| 金额 | 千分位 + 万美元 + 两位小数 | 1,234.56万美元 |
| 笔数 | 整数 + 千分位 | 2,491笔 |
| 百分比 | 正负号 + 两位小数 | +12.35% / -3.21% |
| 排名 | "第 N 名" | 第3名 |
| 日期 | 中文格式 + ~ 间隔 | 2026年5月1日 ~ 2026年5月15日 |

### 7.3 术语统一

| 标准术语 | 禁用表述 |
|---------|---------|
| 交易量 | 成交量、交易额 |
| 交易笔数 | 成交笔数、笔次 |
| 套保率 | 对冲比率 |
| 同比 | YoY（内部用英文，对客用中文） |
| 环比 | MoM |

### 7.4 拒答模板

```
"该查询超出我目前的分析范围。可以帮您查询：
  1. {建议查询1}
  2. {建议查询2}
  3. {建议查询3}"
```

---

## 8. 可扩展性

### 8.1 配置驱动

Agent 注册从硬编码改为 `agents.yaml`：

```yaml
agents:
  BI:
    enabled: true
    version: "1.2.0"
    keywords: [交易量, 排名, 套保率, 金额, 笔数, 银行, 客户]
    capabilities: [聚合查询, 排名查询, 套保率计算, ...]
    NOT_capabilities: [预测, 预估, 趋势分析, 风险评估, ...]
    routes_to: bi_subgraph
  quoting:
    enabled: false
    version: "0.1.0"
    keywords: [汇率, 报价, 即期, 远期, 掉期, 点差]
    capabilities: [实时汇率查询, 报价生成]
    NOT_capabilities: [走势预测, 交易建议]
    routes_to: quoting_subgraph
```

**新增 Agent 只需：**
1. 写一个 LangGraph 子图
2. 在 `agents.yaml` 注册
3. MCP 工具复用
4. 不改 Router 代码，不改前端

### 8.2 热加载

`agents.yaml` 变更后通过 `POST /api/admin/reload-agents` 热加载，无需重启。

### 8.3 MCP 工具版本

工具签名变更时保留旧版本 30 天（`oracle_query` / `oracle_query_v2`），给下游迁移窗口。

---

## 9. 代码规范

### 9.1 命名

```
银行领域术语统一，不用缩写：

  ✓ query_fx_trade_aggregate()     ✗ get_data()
  ✓ validate_hedge_ratio_threshold() ✗ check_hr()
  ✓ resolve_context_from_history() ✗ process_ctx()
  ✓ build_execution_plan()         ✗ do_plan()
```

### 9.2 强类型接口

```python
# 每层的入参/出参是明确的 dataclass，不传裸 dict

@dataclass
class ResolvedContext:
    params: dict
    inherited_fields: list[str]
    confidence: float
    needs_confirm: list[str]

@dataclass
class ExecutionPlan:
    status: str            # "ok" | "rejected" | "confirm"
    plan: str              # "single" | "parallel" | "serial"
    steps: list[PlanStep]
    confidence: float

@dataclass
class AgentResult:
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    comparison: dict | None
    result_hash: str
    duration_ms: int
```

### 9.3 关键决策注释

每个 `if` 分支如果涉及业务决策，必须注释 WHY：

```python
# 门禁 2 拒绝：实体验证失败。
# "美元指数"不在已知银行/客户列表中，
# 为避免错误解读为"美元→银行名模糊匹配"，直接拒答。
if not entity_validated:
    return rejected("out_of_scope")
```

---

## 10. 审计日志

### 10.1 每条查询一条记录

```sql
CREATE TABLE audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL UNIQUE,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    session_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    
    -- 输入
    raw_input TEXT NOT NULL,
    
    -- 上下文
    context_used JSON,         -- [{turn:1, fields:["date_start","date_end"]}]
    
    -- 路由
    router_decision JSON,      -- {status:"ok", agent:"BI", confidence:0.95}
    
    -- 解析
    resolved_params JSON,
    
    -- SQL
    sql_executed TEXT,
    sql_validated BOOLEAN,
    sql_validation_by VARCHAR(32),  -- "TradeQueryBuilder" | "rejected"
    sql_duration_ms INT,
    
    -- 结果
    result_rows INT,
    result_hash VARCHAR(128),       -- SHA-256 of serialized rows
    result_validated BOOLEAN,
    
    -- 输出
    response_to_user TEXT,
    pipeline VARCHAR(64),
    
    -- LLM
    llm_calls JSON,            -- [{model:"deepseek-v4", tokens:1234, duration_ms:850}]
    
    -- 元数据
    client_ip VARCHAR(45),
    user_agent VARCHAR(256),
    version VARCHAR(16)       -- 系统版本号
    
    INDEX idx_session (session_id),
    INDEX idx_created (created_at),
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 10.2 审计要求

- 每条查询生成唯一 `request_id`，全链路透传
- 数据**不可修改、不可删除**（append-only）
- 保留至少 5 年
- 支持按 session/user/时间范围导出
- SQL 执行前后的参数和结果 hash 必须一致（防篡改）

---

## 11. 安全纵深

### 11.1 网络层

```
前端 → HTTPS (TLS 1.3) → Nginx/网关 → HTTP → FastAPI
                                        │
                                   内网 Oracle/MySQL
```

### 11.2 认证鉴权

```
JWT Token 认证:
  - 登录后颁发，有效期 2h
  - Refresh Token 续期

RBAC 角色:
  admin:    全部功能 + 规则管理 + Agent 配置
  trader:   BI 查询 + 汇率查询 + 报表
  risk:     风控查询 + 合规查询
  readonly: 只看 BI 报表，不能导出
```

### 11.3 输入防护

```
输入长度:   文本 ≤ 2000 字符 (已有)
SQL 注入:   所有 SQL 通过 TradeQueryBuilder 参数化 (已有)
XSS:        前端 Naive UI 默认转义 (已有)
敏感数据:   客户全名 → 王**，身份证/账号 → 完全脱敏
```

### 11.4 限流

```
/api/chat:     每用户 20次/min
/api/query:    每用户 30次/min
/api/admin/*:  每用户 10次/min
LLM 调用:      每 session 10次/min
```

---

## 12. 高可用

### 12.1 容器与服务

```
MySQL:     Docker restart=always，数据卷持久化
FastAPI:   gunicorn/uvicorn 多 worker (4 进程)
Redis:     Docker 或云服务，缓存层可失
Oracle:    连接池 min=2 max=10，自动重连
```

### 12.2 健康检查

```
GET /api/health/live    → 进程存活检查               (100ms)
GET /api/health/ready   → Oracle + MySQL 连接检查     (2s)
GET /api/health/deep    → SELECT 1 FROM DUAL 真实执行  (5s)

Kubernetes / Docker 健康探针用 /live 和 /ready
```

### 12.3 优雅关闭

```
收到 SIGTERM:
  1. 停止接受新请求
  2. 等待现有请求完成 (graceful_timeout=30s)
  3. 关闭 Oracle/MySQL 连接池
  4. 刷新审计日志缓冲区
  5. 退出
```

---

## 13. 监控告警

### 13.1 关键指标

| 指标 | 目标 | 告警阈值 |
|------|------|---------|
| 查询成功率 | > 99.5% | < 99% 持续 3min |
| p95 响应时间 | < 5s | > 8s 持续 5min |
| p99 响应时间 | < 10s | > 15s 持续 3min |
| Oracle 连接池 | < 80% | > 90% |
| LLM 成功率 | > 95% | < 90% 持续 3min |
| 拒答率 | < 15% | > 30%（说明覆盖面不足） |
| 熔断状态 | 正常 | 任何组件熔断 |
| 审计日志写入延迟 | < 100ms | > 1s |

### 13.2 告警通知

```
P0: Oracle 不可达 / 成功率骤降        → 企业微信 + 短信
P1: LLM 降级 / 响应时间超标 / 熔断     → 企业微信
P2: 缓存命中率低 / 拒答率高            → 日报汇总
```

---

## 14. 灰度降级

### 14.1 Oracle 不可用

```
  /api/parse  → 正常（纯 MySQL 规则引擎）
  /api/query  → "数据查询暂时不可用，请稍后再试"
  /api/admin  → 正常（MySQL 规则库）
  前端:        显示橙色状态条"数据查询降级中"
```

### 14.2 LLM 不可用

```
  Context Resolver → 降级为规则模式（简单匹配上一轮日期）
  Router → 纯关键词路由
  BI Agent → 规则解析 + gatekeep 兜底
  前端:        显示"智能模式降级为基本模式"
```

### 14.3 MySQL 不可用

```
  规则库 → 从内存缓存加载（最后一次快照）
  会话记忆 → 降级为当前 session 内存存储
  告警立即通知
```

### 14.4 全链路降级

```
所有后端不可用：
  前端显示 "系统维护中，预计 {时间} 恢复"
  提供客服联系方式
```

---

## 15. Agent 规划

| Agent | 职责 | 状态 |
|-------|------|------|
| Context Resolver | 全对话历史分析，参数继承推断 | 新设计 |
| Router | 文本→Agent 分发，三层门禁 | 新设计 |
| SQL Validator | TradeQueryBuilder 重建 SQL | 新设计 |
| Result Validator | 结果校验、异常检测 | 新设计 |
| Response Formatter | 脱敏、格式化、术语统一 | 新设计 |
| BI Agent | 外汇交易数据查询、聚合、排名、套保率、同比环比 | 迁移 |
| 询报价 Agent | 实时汇率询价、报价生成 | 待建 |
| 风控 Agent | 交易风险监控、异常检测 | 待建 |
| 合规 Agent | 交易合规检查 | 待建 |
| 客户画像 Agent | 客户交易行为分析 | 待建 |
| 报表 Agent | 定时/条件触发的批量报表 | 待建 |
| 知识问答 Agent | 业务规则、文档问答 | 待建 |
| Fallback Agent | 拒答 + 引导 | 待建 |

---

## 16. MCP 工具清单

### Phase 1

| 工具 | 参数 | 返回 |
|------|------|------|
| `oracle_query` | `sql: str` | `{columns, rows, row_count}` |
| `mysql_query` | `sql: str` | `list[dict]` |
| `llm_chat` | `prompt: str` | `str` |

### Phase 2+

| 工具 | 参数 | 返回 | 使用者 |
|------|------|------|--------|
| `load_rules` | `category: str` | `rule_list` | 所有 Agent |
| `parse_date` | `text: str` | `{start, end}` | BI、报表 |
| `detect_entities` | `text: str` | `{banks, customers}` | BI、风控 |
| `compute_comparison` | `rows, type` | `comparison_data` | BI、报表 |
| `get_session_context` | `session_id, n` | `turns` | 所有 Agent |
| `save_memory` | `session_id, key, value` | - | 所有 Agent |
| `write_audit_log` | `request_id, data` | - | 所有 Agent |
| `check_cache` | `params_hash` | `cached_result | None` | 所有 Agent |

---

## 17. FastMCP 技术选型

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
app.mount("/mcp", mcp.http_app())
```

**传输模式：** Streamable HTTP（`/mcp` 端点）

---

## 18. Phase 1 实现范围

**原则：** 新增独立目录，不碰现有代码。

```
backend/
├── app.py              ← +一行 app.mount("/mcp", ...)
├── db/                 ← 不变
├── llm_parser/         ← 不变
├── memory/             ← 不变
└── mcp/                ← 新增
    ├── __init__.py
    ├── server.py        ← FastMCP 入口
    └── tools/
        ├── __init__.py
        ├── oracle_tool.py
        ├── mysql_tool.py
        └── llm_tool.py
```

**完工标准：**
- `GET /mcp` 返回 MCP Server 信息
- Claude Code 可调用 `oracle_query`、`mysql_query`、`llm_chat`
- 现有 `/api/*` 全部正常运行

---

## 19. 落地节奏

| Phase | 内容 | P0 交付物 |
|-------|------|----------|
| Phase 1 | MCP 工具层 — 3 个工具 + 挂 FastAPI | MCP Server 独立运行 |
| Phase 2 | LangGraph 编排层（Context Resolver + Router + SQL Validator + BI Agent 迁移） | BI Agent 通过 MCP 执行 |
| Phase 3 | 审计日志 + 安全纵深（认证/鉴权/限流） + 输出规范 | 银行合规就绪 |
| Phase 4 | 高可用 + 监控告警 + 缓存 | 生产可部署 |
| Phase 5 | 接入询报价 Agent + 验证并行/串行 | 多 Agent 协同 |
| Phase 6 | 批量接入剩余 Agent + 灰度降级完善 | 完整多 Agent 系统 |

---

## 20. 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 幻觉导致错误 SQL | 业务数据错误 | SQL Validator 强制重建，不用 LLM 原文 |
| LLM 幻觉导致错误业务结论 | 银行业务零容忍 | 三层门禁 + NOT capabilities + Result Validator |
| Router 误路由 | 用户得到不相关结果 | 门禁 2 实体校验 + 门禁 3 能力校验 |
| 上下文继承错误 | 查错实体/日期 | Context Resolver LLM 全历史分析 + 不确定则追问 |
| 并行/串行拆解错误 | 遗漏上下文或错误拼接 | 硬条件校验 + 输出 schema 匹配 |
| Oracle/MySQL 不可用 | 服务中断 | 灰度降级 + 健康检查 + 自动重连 |
| 审计日志丢失 | 合规风险 | 写入确认 + 缓冲区刷新 + 监控告警 |
| MCP SDK 演进 | API 变动 | 锁定版本 + Phase 1 仅用 `@mcp.tool()` |
| 8 个 Agent 后编排层复杂 | 性能下降 | LangGraph DAG 编译优化 + 子图缓存 |
