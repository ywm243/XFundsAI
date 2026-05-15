# Smart BI 架构扩展性评估方案 v3

> 评估日期：2026-05-14
> 背景：当前仅智能 BI Agent，后续将扩展智能询报价 Agent、风险监控 Agent 等
> 本版整合了向量数据库选型、记忆存储、前端配置、置信度打分等全部讨论结论

---

## 一、规则存储与匹配：SQLite + 向量 DB 双层架构

### 1.1 两个存储解决的是完全不同的问题

```
SQLite                       向量 DB (Chroma)
─────────────────────────    ─────────────────────────
查询类型: 精确匹配             查询类型: 语义相似
SQL:      WHERE k='结汇'      查询:    embedding → cosine
结果:     有就是有，没有就没有   结果:   最接近的 Top-K 条
延迟:     < 1ms               延迟:    50-200ms
可审计:   能，SELECT 看原始数据  可审计:   不能，向量是数字数组
确定性:   100%                 确定性:   概率性
```

**实际例子：**

```
用户输入: "同步增加多少"

SQLite:
  SELECT * FROM rule_items WHERE keywords LIKE '%同步增加%'
  → 0 rows ← 查不到，因为规则库里没有"同步增加"这个词

Chroma:
  embed("同步增加") → [0.12, -0.34, 0.78, ...]
  cosine_similarity vs "同比增长统计" → 0.92
  → 返回 comparison="yoy" ← 语义层面知道它们意思接近
```

### 1.2 为什么不能只用其中一个

| 场景 | 用 SQLite | 用向量 DB |
|------|----------|----------|
| "结汇" → buy_sell=？ | ✓ 铁律规则，必须 100% 返回 B | ✗ 可能返回 S（语义混淆） |
| "同步增加" → 是否同比？ | ✗ 关键词匹配不到 | ✓ 语义相似度匹配 |
| 规则版本回滚到 v42 | ✓ 精确 id 查找 | ✗ 没有版本号概念 |
| 历史查询 Top-K 推荐 | ✗ LIKE 不是语义匹配 | ✓ 向量相似度排序 |
| 状态码校验（0-5 范围） | ✓ 精确枚举 | ✗ 无法校验值域 |
| 新 Agent 零样本启动 | ✓ 直接复用 common/ 共享规则 | ✗ 需要积累 embedding 数据 |

### 1.3 双层架构：向量 DB 给建议，SQLite 做决定

```
用户输入: "北京分公司今年一季度交易量，同步增加多少"
                │
                ▼
        ┌──────────────┐
        │  向量 DB (Chroma)│  ← 语义层：相似查询推荐
        │  Top-3 召回:     │
        │  1. "同比增长统计" (0.92)
        │  2. "环比变化分析" (0.78)
        │  3. "YOY趋势查询" (0.71)
        └──────┬───────┘
               │ comparison 候选: ["yoy", "mom", "yoy"]
               ▼
        ┌──────────────┐
        │  SQLite       │  ← 确定性层：精确规则验证
        │  rule_items   │
        │               │     铁律覆盖 + 参数互斥校验
        │               │     候选 → 最终决定
        └──────┬───────┘
               │ comparison="yoy" (确定)
               ▼
           进入 SQL 构建
```

**核心原则：向量 DB 的输出必须经过 SQLite 规则引擎验证。它给的是建议，规则引擎做最终决定。**

### 1.4 规则分层：共享层 + Agent 专用层

重新审视当前 `semantic_rules.json` 的 395 行规则，大约 70% 是所有 Agent 共用的：

```
common/ (agent_type='common')        ← 一次配置，全部 Agent 复用
├── buy_sell_direction       8 条规则（铁律 4 + 可反转 4）
├── product_type             4 条规则
├── time_expressions         31 条规则（含新增的季度模式）
├── special_states           5 条规则
├── trade_class              17 条规则
├── app_id                   2 条规则
└── sql_rules                视图映射/字段/schema

bi/ (agent_type='bi')               ← BI Agent 专用
├── aggregate_keywords       ["交易量","金额","总额","总计","汇总"]
├── ranking_keywords         排名/排行/TOP N
├── hedge_ratio_keywords     套保率
├── comparison_modifiers     同比/环比/同步
└── dimension_mapping        5 种维度

quoting/ (agent_type='quoting')     ← 询报价 Agent 专用（新增）
├── bid_ask_terms            买入价/卖出价/bid/ask
├── point_terms              spot points/fwd points
├── pricing_logic            报价方向逻辑
└── validity_terms           有效期/交割日

risk/ (agent_type='risk')          ← 风控 Agent 专用（新增）
├── exposure_thresholds       敞口阈值
├── alert_conditions          预警条件
└── limit_rules               限额规则
```

### 1.5 SQLite 表设计（规则 + 记忆同一个 DB）

```sql
-- 规则分类表
CREATE TABLE rule_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_type TEXT NOT NULL CHECK(agent_type IN ('common','bi','quoting','risk')),
    category TEXT NOT NULL,           -- 'buy_sell' | 'product_type' | 'time_expr' | ...
    display_name TEXT NOT NULL,       -- 前端显示名
    priority INTEGER DEFAULT 0,
    UNIQUE(agent_type, category)
);

-- 规则明细表
CREATE TABLE rule_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES rule_categories(id),
    keywords TEXT NOT NULL,           -- JSON array: ["结汇","结汇交易"]
    rule_data JSON NOT NULL,          -- {"direction":"B","set_app_id":2,...}
    is_ironclad BOOLEAN DEFAULT FALSE,
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 规则版本表（每次热部署自动备份）
CREATE TABLE rule_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL,
    version_num INTEGER NOT NULL,
    snapshot JSON NOT NULL,
    created_by TEXT DEFAULT 'system',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 二、解析流程改造：加置信度打分 + 分流

### 2.1 当前问题

```python
# app.py /api/parse — 当前逻辑（无打分，无分流）
@app.post("/api/parse")
async def api_parse(request: Request):
    text = body.get("text", "")
    system_prompt = build_system_prompt()
    llm_result = llm_parse(text, system_prompt)      # ← 每次都调 LLM
    if llm_result is not None:
        parsed = gatekeep(llm_result, text)
        pipeline = "llm+gatekeep"
    else:
        parsed = rule_based_parse(text)               # ← LLM 挂了才用规则
        pipeline = "fallback"
```

问题：
- "本月交易量"这种规则 100% 能搞定的查询，白白浪费一次 LLM API 调用（~2s 延迟 + 费用）
- LLM 优先，规则只是兜底——但实际上规则解析是免费的（<1ms, 零费用）
- 没有置信度概念，不知道规则结果有多可靠

### 2.2 改造后：规则先行 + 置信度分流

```python
# 改造后 /api/parse
@app.post("/api/parse")
async def api_parse(request: Request):
    text = body.get("text", "")

    # Step 1: 规则先跑（免费，<1ms）
    rule_parsed = rule_based_parse(text)
    confidence = _rule_confidence(text, rule_parsed)

    # Step 2: 分流
    if confidence >= 0.8:
        # 高置信度 → 跳过 LLM，省一次 API 调用
        parsed = gatekeep(rule_parsed, text)
        pipeline = f"rule(confidence={confidence:.0%})"
    else:
        # 低置信度 → 需要 LLM
        system_prompt = build_system_prompt()
        llm_result = llm_parse(text, system_prompt)
        if llm_result is not None:
            parsed = gatekeep(llm_result, text)
            pipeline = f"llm+gatekeep(rule_confidence={confidence:.0%})"
        else:
            parsed = gatekeep(rule_parsed, text)
            pipeline = f"rule_fallback(confidence={confidence:.0%})"

    return {"params": parsed, "pipeline": pipeline}
```

### 2.3 置信度打分函数

```python
# 新增 parser.py
def _rule_confidence(text: str, parsed: dict) -> float:
    """
    计算规则解析的置信度 0.0~1.0。

    不是算"有多少字段被填了"，而是算"核心字段是否从文本中成功提取"。
    避免默认值（如 product_type='all'）拉高置信度。
    """
    core_score = 0.0
    core_total = 4.0

    # 日期 (权重 1.5)：最关键字段
    if parsed.get("date_start") and parsed.get("date_end"):
        if _has_quarter_mismatch(text, parsed):
            # "一季度" 但返回了 YTD → 误判信号
            core_score += 0.3
        else:
            core_score += 1.5

    # 实体 (权重 1.0)：银行/客户至少命中一个
    if parsed.get("bank_name") or parsed.get("cust_name"):
        core_score += 1.0
    elif not _text_has_entity_keyword(text):
        # 文本本身没有实体词，不算扣分
        core_score += 1.0

    # 意图 (权重 1.5)：aggregate/hedge_ratio/top_n/amount_filter 至少命中一个
    if any([
        parsed.get("aggregate"),
        parsed.get("hedge_ratio"),
        parsed.get("top_n"),
        parsed.get("amount_filter"),
    ]):
        core_score += 1.5

    return min(core_score / core_total, 1.0)


def _has_quarter_mismatch(text: str, parsed: dict) -> bool:
    """检测季度查询被"今年"兜底误判为 YTD 的情况"""
    import re
    has_quarter = bool(re.search(r"[一二三四1-4]\s*(?:季度|季)", text))
    if not has_quarter:
        return False
    # 检查返回的日期范围是否是 YTD（跨了多个季度）
    end = parsed.get("date_end", "")
    # 一季度结束于3月，二季度6月，三季度9月，四季度12月
    # 如果是 YTD 则 end 接近当前日期，而非季度末
    return "03" not in end[-5:-3] and "06" not in end[-5:-3] \
       and "09" not in end[-5:-3] and "12" not in end[-5:-3]
```

### 2.4 效果示例

```
"本月交易量"
  date: 2026-05-01~2026-05-14 ✓ (1.5)
  entity: 文本无实体词 ✓ (1.0)
  intent: aggregate=true ✓ (1.5)
  confidence: 4.0/4.0 = 100% → 跳过 LLM ✓

"北京分公司今年一季度同步增加多少"（修复前）
  date: 2026-01-01~2026-05-14 (YTD 误判) → 0.3
  entity: bank_name 命中 ✓ (1.0)
  intent: 无 aggregate/hedge_ratio/top_n/amount_filter → 0
  confidence: 1.3/4.0 = 33% → 调 LLM ✓

"北京分公司今年一季度同步增加多少"（修复后）
  date: 2026-01-01~2026-03-31 ✓ (1.5)
  entity: bank_name 命中 ✓ (1.0)
  intent: 无 explicit intent → 0
  confidence: 2.5/4.0 = 63% → 调 LLM（边界情况，合理）

"工商银行结汇交易量排名前10"
  date: 无 → 0
  entity: bank_name 命中 ✓ (1.0)
  intent: top_n=10 ✓ (1.5)
  confidence: 2.5/4.0 = 63% → 调 LLM（需要 LLM 推断日期）
```

---

## 三、记忆存储：SQLite + 三层总结

### 3.1 现状

```python
# Feature 分支 sql_engine/memory.py（main 分支无此模块）
_sessions: dict[str, list[dict]] = defaultdict(list)   # 内存，重启丢失
_pattern_file = Path("memory/agent_patterns.json")      # JSON，只追加不清理
# 上下文: build_context_prompt(session_id) → 最近 3 轮原文
```

| 问题 | 严重度 |
|------|--------|
| 内存丢失：服务重启，所有会话上下文消失 | 高 |
| 无总结压缩：只保留最近 3 轮原文，没有摘要 | 高 |
| JSON 膨胀：`agent_patterns.json` 200+ 条，只追加 | 中 |
| 无跨会话学习：A 会话纠正的参数不影响 B 会话 | 中 |

### 3.2 三层记忆模型

```
Layer 1: 工作记忆（最近 N 轮原文）
├─ N=3~5，完整对话
├─ 用于 LLM 上下文注入
└─ 存入 SQLite turns 表

Layer 2: 短期记忆（会话摘要）
├─ 每 5 轮触发 LLM 总结一次
├─ 提取：实体、时间偏好、纠正历史
├─ 存入 SQLite memory_summaries 表
└─ 跨会话可查

Layer 3: 长期记忆（用户画像）
├─ 周期离线程式总结
├─ 常用查询、偏好维度、关注银行
└─ 个性化推荐和默认值填充
```

### 3.3 总结触发规则

```
轮次 % 5 == 0 且 轮次 > 0 → 触发总结
会话结束 → 最终总结写入长期记忆
```

**总结 Prompt：**
```
将以下对话历史压缩为结构化摘要：
- 用户关注的银行/客户/产品
- 查询的时间偏好
- 用户纠正过的参数
- 最终确认的查询意图
```

### 3.4 SQLite 表设计

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL,           -- 'bi' | 'quoting' | 'risk'
    user_id TEXT DEFAULT 'default',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    turn_index INTEGER NOT NULL,
    user_query TEXT NOT NULL,
    parsed_params JSON,
    executed_sql TEXT,
    result_summary TEXT,
    user_feedback TEXT,                 -- 'confirmed' | 'reset' | 'modified'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE memory_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    scope TEXT NOT NULL,                -- 'session' | 'user' | 'agent'
    summary_type TEXT NOT NULL,         -- 'entity_preferences' | 'query_patterns' | 'corrections'
    content JSON NOT NULL,
    source_turns TEXT,                  -- "1-5"
    embedding_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3.5 为什么选 SQLite 而非 Oracle

- 零运维：嵌入式，无需额外服务
- 性能：记忆读写 QPS < 10，SQLite 完全够用
- LangChain 原生支持 `SqliteSaver`
- 规则和记忆同一个 DB，管理方便

---

## 四、前端规则配置页面

### 4.1 现状

```
业务人员提需求 → 开发人员改 JSON → 部署 → curl /api/reload-rules → 生效
```

业务人员无法自助配置，修改周期长，无校验，无预览，无回滚。

### 4.2 目标

```
业务人员打开管理页面 → 修改规则 → 预览测试 → 点击[热部署] → 立即生效
```

### 4.3 API 设计

```
GET    /api/admin/rules                    列出所有规则（按 agent_type 分组）
GET    /api/admin/rules/{category}         获取单类规则详情
POST   /api/admin/rules/{category}/items   添加单条规则
PUT    /api/admin/rules/{category}/items/{id}  更新单条规则
DELETE /api/admin/rules/{category}/items/{id}  删除单条规则
POST   /api/admin/rules/preview            预览规则匹配效果
GET    /api/admin/rules/history            版本历史
POST   /api/admin/rules/rollback           回滚到指定版本
POST   /api/admin/rules/reload             热部署（清缓存）
```

### 4.4 前端页面

```
┌──────────────────────────────────────────────────────┐
│  规则管理                               [热部署] [回滚] │
├────────────┬─────────────────────────────────────────┤
│ 规则分类    │                                         │
│            │  ┌─ 买卖方向规则 ─────────────────────┐  │
│ ▸ common   │  │ 关键词          │ 方向 │ 铁律 │ 操作 │  │
│  ├买卖方向  │  │ 结汇,结汇交易    │  B  │  ✓  │ 编辑  │  │
│  ├产品类型  │  │ 购汇,售汇       │  S  │  ✓  │ 编辑  │  │
│  ├时间表达  │  │ 买入,买,BUY     │  B  │  -  │ 编辑  │  │
│  ├特殊状态  │  │ [+ 添加规则]                      │  │
│  ├交易类别  │  └────────────────────────────────────┘  │
│  └业务系统  │                                         │
│            │  ┌─ 规则预览测试 ────────────────────┐  │
│ ▸ bi       │  │ 输入: "今年一季度结汇交易量"        │  │
│  ├聚合/对比 │  │ [运行预览]                         │  │
│  └维度映射  │  │                                    │  │
│            │  │ 匹配:                               │  │
│ ▸ quoting  │  │  product_type → all                 │  │
│            │  │  buy_sell → B (结汇,铁律)            │  │
│ ▸ risk     │  │  date → 2026-01-01 ~ 2026-03-31   │  │
│            │  └────────────────────────────────────┘  │
└────────────┴─────────────────────────────────────────┘
```

### 4.5 实时生效机制

```
前端点击 [热部署]
  → POST /api/admin/rules/reload
     → rules_engine.reload_rules()        → _rules_cache = None
     → prompt_builder.invalidate_cache()  → _cache = None
  → 返回 { status: "ok", version: 42 }

下一个请求进来:
  _load_rules() 发现缓存空 → 从 SQLite 重新加载 → 新规则生效
  延迟: 下一次请求 + 5ms
```

**不需要重启。** 机制就是清缓存，跟当前 `reload_rules()` 完全一样，只是数据源从 JSON 文件换成了 SQLite。

### 4.6 规则校验

```python
def validate_rules(rules: dict) -> list[str]:
    """规则提交前校验"""
    errors = []
    # 关键词冲突检测
    # 铁律规则 vs 可反转规则关键词不可重叠
    # 状态码范围 0-5
    # 必填字段检查
    return errors
```

---

## 五、实施计划

### Phase 1（当前迭代，2-3 天）

```
├─ JSON → SQLite 规则库迁移 ★★★
│  理由：为前端配置打基础，共享规则 common/ 一次配置全部复用
│  工作：建表 schema + 迁移脚本 + _load_rules() 改读 SQLite
│        兼容层确保 gatekeep/prompt_builder 行为不变
│  文件：db/migrate_rules.py, rules_engine.py 改造 ≈ 150 行
│
├─ 置信度打分 + 分流逻辑 ★★★
│  理由：规则 100% 搞定的查询跳过 LLM，省时省钱
│  工作：_rule_confidence() + app.py /api/parse /api/query 改造
│  文件：parser.py + app.py ≈ 80 行
│
├─ 管理后台 API ★★★
│  理由：业务人员可自助配置规则，不再依赖开发
│  工作：admin_routes.py + 校验 + 版本管理
│  文件：backend/admin_routes.py ≈ 250 行
│
├─ SQLite 记忆持久化 ★★★
│  理由：解决重启丢失，为多 Agent 打基础
│  工作：store.py + schema.sql，替换内存 dict
│  文件：backend/memory/store.py ≈ 250 行
│
└─ 管理后台前端页面 ★★★
   理由：可视化配置规则 + 预览测试 + 一键热部署
   工作：AdminRules.vue
   文件：frontend/src/views/AdminRules.vue ≈ 350 行

Phase 1 总工作量 ≈ 1080 行，预计 2-3 天
```

### Phase 2（下个迭代，3-5 天）

```
├─ 规则按 common/ + Agent 专用拆分 ★★
│  理由：新 Agent 零规则成本接入
│  工作：SQLite 中通过 agent_type 字段隔离
│  文件：migrate 脚本 ≈ 100 行
│
├─ 记忆总结中间件 ★★
│  理由：长对话上下文压缩，降低 LLM token 消耗
│  工作：summarizer.py + LLM 调用
│  文件：backend/memory/summarizer.py ≈ 200 行
│
└─ 规则冲突检测 + 预览测试完善 ★★
   工作：validate_rules() 升级 + preview API
   文件：backend/admin_routes.py 补充 ≈ 150 行
```

### Phase 3（远期，1-2 周）

```
└─ Chroma 向量数据库集成 ★
   理由：语义检索增强，需积累足够标注数据才有价值
   定位：确定性规则引擎的补充，给建议不做决定
   工作：embedding 流水线 + Top-K 召回 + 规则引擎集成
   文件：backend/vector_store/ ≈ 500 行
```

---

## 六、总结对比

| 维度 | 当前 | Phase 1 后 | Phase 2 后 | Phase 3 后 |
|------|------|-----------|-----------|-----------|
| 规则存储 | JSON 文件 | SQLite（common+专用） | agent_type 隔离 | + Chroma 向量 |
| 规则配置 | 改 JSON 文件 | 管理页面操作 | 冲突检测+预览 | 语义推荐 |
| 规则生效 | curl reload | 页面一键热部署 | 自动热部署 | 实时同步 |
| 解析流程 | LLM 优先 | 规则优先+置信度分流 | 阈值可配 | 向量辅助决策 |
| 会话记忆 | 内存 dict（重启丢） | SQLite 持久化 | 自动总结压缩 | 跨会话画像 |
| 记忆查询 | 最近 3 轮原文 | 完整历史 | 摘要 + 原文 | 语义检索历史 |
| 多 Agent | 不支持 | 按 agent_type 隔离 | 统一管理页 | 向量知识共享 |
| LLM 调用量 | 每次请求 | 高置信度跳过 | 更低（规则覆盖更全） | 更低（向量缓存命中） |

---

> **核心结论：**
> 1. SQLite 做确定性存储（规则 + 记忆），Chroma 做语义补充（Phase 3），前者做决定，后者给建议
> 2. 规则按 common/ + Agent 专用分层，新 Agent 零规则成本接入
> 3. 置信度 ≥ 80% 跳过 LLM，省时省钱
> 4. Phase 1 一次性搞定规则 SQLite 化 + 管理后台 + 记忆持久化，三个共用同一个 SQLite
