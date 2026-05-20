# ETCSLV Harness 改进设计规格

> 日期: 2026-05-20
> 状态: Draft
> 目标模型: DeepSeek v4 Flash (默认) + DeepSeek v4 Pro (按需)
> 核心原则: **准确性优先，Token 是质量问题不是成本问题**

---

## 1. 背景与目标

### 1.1 当前问题

系统在**单请求确定性防护**上做得好（rule-first、gatekeep、post-validation、risk guard），但作为一个持续运行的 agent harness 缺少核心基础设施：

| 组件 | 完备度 | 核心缺口 |
|------|--------|----------|
| **E** 执行循环 | 3/10 | 无 OODA 循环、无重试、无检查点、无熔断 |
| **T** 工具注册表 | 4/10 | 无认证、无 schema 校验、无自动发现、无监控 |
| **C** 上下文管理 | 3/10 | 无 token 预算、importance 存而不用、两套 Memory 不统一、RAG 空壳 |
| **S** 状态存储 | 4/10 | LangGraph 无 checkpoint、状态机非事务性、result_hash 空 |
| **L** 生命周期钩子 | 2/10 | 无中间件、事件总线 0 订阅、无认证、审计不完整 |
| **V** 评估接口 | 3/10 | 无跨请求追踪、无 A/B、无性能指标、无反馈环 |

### 1.2 Token 消费现状

9 个 LLM 调用点，**零 token 追踪**：

| # | 调用点 | Prompt 估算 | Completion 估算 | max_tokens | 跟踪 |
|---|--------|-------------|-----------------|------------|------|
| 1 | `llm_parse` (BI 解析) | 1,300-2,500+ | 100-200 | 未设 | 无 |
| 2 | `llm_chat` (分析) | 1,500-4,000 | 150-300 | 未设 | 无 |
| 3 | `llm_tool_call` (Orchestrator 主分析) | 1,500-3,500 | 500-1,000 | 2048 | 无 |
| 4 | `llm_tool_call` (Orchestrator 修正重试) | 3,000-5,500 | 500-1,000 | 2048 | 无 |
| 5 | Context Resolver | 2,500-3,500 | 80-150 | 未设 | 无 |
| 6 | MCP `llm_chat` | **无限** | **无限** | 未设 | 无 |
| 7 | MCP `detect_entities` | 80-150 | 30-80 | 未设 | 无 |
| 8 | MCP `parse_date` | 80-150 | 30-60 | 未设 | 无 |
| 9 | `llm_parse` (定价意图) | 450-600 | 80-150 | 未设 | 无 |

**准确性损害来源：**

1. **上下文双重发送** — LangGraph 管线中，context_resolver 和 BI agent parse 分别向 LLM 发送相同对话历史，同一信息的两种表示（原始文本 vs resolved_params）可能微妙不一致，导致 LLM 解析偏移
2. **无关历史占位** — 低 importance 的旧轮次挤掉当前查询需要的 wiki 规则注入空间
3. **模型能力不匹配** — 所有调用用同一模型，简单提取和复杂分析无法区分
4. **无质量反馈** — 不知道哪次调用结果不准，无法针对性优化

### 1.3 设计目标

1. **准确性提升** — 消除上下文混淆源，Wiki 规则注入补充 gatekeep 盲区
2. **可观测性** — 每次 LLM 调用可追踪、可归因、可对比
3. **可恢复性** — 管线崩溃后可从检查点恢复，不从头重跑
4. **可评估性** — 跨请求质量追踪，支持 A/B 验证规则变更效果
5. **自适应性** — 系统根据会话状态自动选择最优模型和上下文策略

### 1.4 核心原则

| 原则 | 含义 |
|------|------|
| 花得准比花得少重要 | Token 不是成本问题，是质量问题。每个 token 应服务于准确性 |
| 升级比降级重要 | 复杂场景升级到 Pro，而非简单场景降级到规则 |
| 去噪声比砍内容重要 | 压缩是提炼信息而非截断，保留关键信息去除冗余表述 |
| Wiki 是准确性杠杆 | Flash 低成本使 Wiki 规则注入可行，补充 gatekeep 硬编码盲区 |

---

## 2. E — 执行循环 (Execution Loop)

### 2.1 现状

三条管线全部单次通过，无真正 OODA 循环：

```
管线1: LangGraph DAG    context_resolver → router → [bi_agent | pricing_agent] → validate → END
管线2: Orchestrator      工具执行 → LLM生成 → PostValidator → (1次重试) → END
管线3: Pricing Service   请求-响应，FSM 控制生命周期
```

- 无全局迭代上限/熔断器
- LangGraph 无 checkpoint，崩溃后从头重跑
- 除 Orchestrator 1 次后验证重试外无任何重试机制
- Wiki context resolver 已实现但 LangGraph 管线未接入

### 2.2 设计

#### E1: LangGraph 接入 Wiki Context Resolver

当前 `langgraph/context_resolver.py` 用 LLM+规则解析上下文，`wiki/context_resolver.py` 已有 wiki-first + 对话 fallback 策略但未使用。

**改动文件:** `backend/langgraph/context_resolver.py` `_node_resolve_context()`

**改动内容:**
1. 先调 `wiki.resolve_bi_context()` / `resolve_pricing_context()`
2. wiki 返回有效 resolved_params 且 confidence >= 0.7 → 直接使用，跳过 LLM 调用
3. wiki 无结果或低置信度 → 走现有 LLM+规则路径

**准确性收益:** Wiki 实体页的 frontmatter 是确定性数据（客户偏好、常用产品），比 LLM 推断更准确。

#### E2: LangGraph MySQL Checkpointer

**新增文件:** `backend/langgraph/checkpointer.py`

**实现:**
```python
class MySqlCheckpointer(BaseCheckpointSaver):
    """LangGraph 节点执行后自动持久化 AgentState 到 MySQL"""

    # 表: langgraph_checkpoints
    #   thread_id VARCHAR(128)
    #   checkpoint_ns VARCHAR(128)
    #   checkpoint_id VARCHAR(64) — UUID
    #   parent_id VARCHAR(64) — 前一个 checkpoint
    #   data JSON — 序列化的 AgentState
    #   created_at DATETIME

    def put(self, config, checkpoint, metadata, new_versions):
        # 序列化 AgentState → JSON 写入 MySQL

    def get(self, config):
        # 读取最新 checkpoint，反序列化为 AgentState

    def list(self, config, limit=10, before=None):
        # 列出历史 checkpoints
```

**改动文件:** `backend/langgraph/pipeline.py` `build_main_graph()`

```python
# 改前
return builder.compile()
# 改后
return builder.compile(checkpointer=MySqlCheckpointer(mysql_conn_string))
```

**可恢复性收益:** 任何节点崩溃后，从最近 checkpoint 恢复 AgentState，不丢失已执行的 SQL 结果或解析参数。

#### E3: 统一重试层

**新增文件:** `backend/langgraph/retry.py`

```python
class RetryableNode:
    """包装节点函数，对瞬态错误自动重试"""

    def __init__(self, fn, max_retries=2, retry_on=(ConnectionError, TimeoutError),
                 backoff_base=1.0):
        self.fn = fn
        self.max_retries = max_retries
        self.retry_on = retry_on
        self.backoff_base = backoff_base

    async def __call__(self, state: AgentState) -> dict:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self.fn(state)
            except self.retry_on as e:
                last_error = e
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff_base * (2 ** attempt))
                # 非瞬态错误（ValidationError、BusinessError）不重试，直接抛出
        raise last_error
```

**应用场景:**
- `bi_agent._node_execute` — Oracle 连接超时
- `pricing_agent._node_pricing_inquiry` — 定价引擎超时
- `context_resolver` LLM 调用 — API 限流

#### E4: Orchestrator 并入 LangGraph

当前 Orchestrator 是独立管线，`/api/query mode=analyze` 调用。目标：成为 LangGraph 的第三个子图。

**新增文件:** `backend/langgraph/agents/analysis_agent.py`

**子图拓扑:**
```
parse → execute_tools → generate_text → post_validate → (retry?) → format
```

- `parse`: 复用 BI agent 的解析逻辑 + 确定 analysis 维度
- `execute_tools`: 确定性调用 query_metrics + decompose_change
- `generate_text`: LLM 生成分析文本（使用 Pro 模型）
- `post_validate`: PostValidator 数字交叉校验
- `retry?`: 不匹配时一次修正重试
- `format`: 输出 analysis_data

**改动文件:** `backend/langgraph/pipeline.py` `build_main_graph()`

```python
# router 增加第三个分支
def _route_agent(state: AgentState) -> str:
    if state.router_decision.status in ("rejected", "confirm"):
        return "__end__"
    if state.router_decision.agent == "PRICING":
        return "pricing_agent"
    if state.router_decision.agent == "ANALYSIS":
        return "analysis_agent"  # 新增
    return "bi_agent"
```

**改动文件:** `backend/langgraph/registry.py`

```python
AGENT_REGISTRY = {
    "BI": AgentCapability(keywords=[...], capabilities=[...], NOT_capabilities=[...]),
    "ANALYSIS": AgentCapability(
        keywords=["为什么", "原因", "分析", "怎么回事", "解释", "变化", "趋势说明"],
        capabilities=["change_attribution", "dimension_decomposition", "text_analysis"],
        NOT_capabilities=["prediction", "forecast"],
    ),
}
```

**前端改动:** `App.vue` 不再区分 `isAnalytical`，所有查询统一走 `/api/chat`。

#### E5: 熔断器

**新增文件:** `backend/langgraph/circuit_breaker.py`

```python
class CircuitBreaker:
    """包装外部依赖，连续失败后短路返回降级结果"""

    STATES = ("CLOSED", "OPEN", "HALF_OPEN")

    def __init__(self, name, failure_threshold=5, reset_timeout=60,
                 fallback_fn=None):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.fallback_fn = fallback_fn  # 降级回调

    async def call(self, fn, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "HALF_OPEN"  # 试探
            else:
                return await self.fallback_fn(*args, **kwargs) if self.fallback_fn else None
        try:
            result = await fn(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"  # 恢复
            self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
            if self.fallback_fn:
                return await self.fallback_fn(*args, **kwargs)
            raise
```

**应用场景:**
- LLM API — 降级为模板生成
- Oracle — 降级为缓存查询结果
- Pricing Engine — 降级为拒绝并建议线下渠道

#### E6: QualityRouter — 多模型路由

**新增文件:** `backend/llm_parser/quality_router.py`

**设计原则:** 按任务复杂度选最优模型，不是按 token 预算砍功能。

```python
class QualityRouter:
    """让每次 LLM 调用都用最优配置产出最准确结果"""

    MODEL_TIERS = {
        "flash": os.getenv("LLM_MODEL_FLASH", "deepseek-v4-flash"),
        "pro": os.getenv("LLM_MODEL_PRO", "deepseek-v4-pro"),
    }

    TASK_PROFILES = {
        # 任务名: {tier, max_tokens, temperature}
        "entity_extract":  {"tier": "flash", "max_tokens": 200,  "temperature": 0.0},
        "date_parse":      {"tier": "flash", "max_tokens": 100,  "temperature": 0.0},
        "context_resolve": {"tier": "flash", "max_tokens": 300,  "temperature": 0.0},
        "bi_parse":        {"tier": "flash", "max_tokens": 500,  "temperature": 0.1},
        "pricing_parse":   {"tier": "flash", "max_tokens": 300,  "temperature": 0.0},
        "wiki_rule_read":  {"tier": "flash", "max_tokens": 500,  "temperature": 0.0},
        "summary_generate":{"tier": "flash", "max_tokens": 800,  "temperature": 0.3},
        "analysis_text":   {"tier": "pro",   "max_tokens": 2048, "temperature": 0.1},
        "analysis_retry":  {"tier": "pro",   "max_tokens": 2048, "temperature": 0.1},
        "insight_generate":{"tier": "pro",   "max_tokens": 1024, "temperature": 0.3},
    }

    def route(self, task: str, context_size_hint: int = 0) -> dict:
        profile = dict(self.TASK_PROFILES[task])
        # 长上下文解析升级到 Pro，保证准确
        if profile["tier"] == "flash" and task in ("bi_parse", "pricing_parse") \
           and context_size_hint > 4000:
            profile["tier"] = "pro"
        profile["model"] = self.MODEL_TIERS[profile["tier"]]
        return profile
```

**改动文件:** `backend/llm_parser/llm_client.py`

```python
# 改前
def llm_parse(text, system_prompt):
    model = os.getenv("LLM_MODEL")

# 改后
def llm_parse(text, system_prompt, task="bi_parse", context_size_hint=0):
    profile = quality_router.route(task, context_size_hint)
    model = profile["model"]
    max_tokens = profile["max_tokens"]
    temperature = profile["temperature"]
```

同样修改 `llm_chat()` 和 `llm_tool_call()` 的签名。

**准确性收益:** 复杂分析任务用 Pro 模型提升推理深度；简单提取任务用 Flash 保持速度和成本效益。

---

## 3. T — 工具注册表 (Tool Registry)

### 3.1 现状

两套并行系统：MCP 工具（12 个，手动注册）+ LLM 工具（2 个，静态定义）。

- MCP 手动注册，新增需改 server.py 两处
- LLM tool_call 参数无 schema 校验
- 无认证，所有端点开放
- 无 Wiki MCP 工具

### 3.2 设计

#### T1: 统一工具注册表

**新增文件:** `backend/tools/registry.py`

```python
@dataclass
class ToolDef:
    name: str
    fn: Callable
    input_schema: dict          # JSON Schema
    output_schema: dict | None
    category: str               # "bi" | "pricing" | "wiki" | "system" | "external"
    writes: bool = False        # 是否写数据
    requires_auth: bool = False
    model_tier: str = "flash"   # 调用此工具需要的模型层级

class ToolRegistry:
    _tools: dict[str, ToolDef] = {}

    @classmethod
    def register(cls, name, category, input_schema, output_schema=None,
                 writes=False, requires_auth=False, model_tier="flash"):
        """装饰器：注册工具"""
        def decorator(fn):
            cls._tools[name] = ToolDef(name=name, fn=fn, ...)
            return fn
        return decorator

    @classmethod
    def get(cls, name: str) -> ToolDef: ...

    @classmethod
    def list(cls, category: str = None) -> list[ToolDef]: ...
```

**改动文件:** `backend/smartbi_mcp/server.py`

```python
# 改前: 手动注册
from backend.smartbi_mcp.tools import oracle_tool, mysql_tool, ...
oracle_tool.register(mcp)
mysql_tool.register(mcp)

# 改后: 自动注册
for tool_def in ToolRegistry.list(category="external"):
    mcp.tool()(tool_def.fn)
```

#### T2: Wiki MCP 工具

**新增文件:** `backend/smartbi_mcp/tools/wiki_search_tool.py`

```python
@ToolRegistry.register("wiki_search", category="wiki",
    input_schema={"type": "object", "properties": {
        "query": {"type": "string"},
        "page_type": {"type": "string", "enum": ["concept","entity","reference"]},
        "limit": {"type": "integer", "default": 5}
    }})
def wiki_search(query: str, page_type: str = None, limit: int = 5) -> list[dict]:
    """搜索 wiki 概念/实体页面"""
```

**新增文件:** `backend/smartbi_mcp/tools/wiki_get_tool.py`

```python
@ToolRegistry.register("wiki_get", category="wiki",
    input_schema={"type": "object", "properties": {
        "slug": {"type": "string"}
    }})
def wiki_get(slug: str) -> dict | None:
    """获取指定 slug 的 wiki 页面"""
```

#### T3: LLM tool_call 参数 Schema 校验

**改动文件:** `backend/llm_parser/llm_client.py` `llm_tool_call()`

```python
# 解析 LLM 返回的 function_call.arguments 后:
for call in calls:
    tool_def = ToolRegistry.get(call["function"]["name"])
    if tool_def and tool_def.input_schema:
        try:
            jsonschema.validate(call["function"]["arguments"], tool_def.input_schema)
        except jsonschema.ValidationError as e:
            logger.warning(f"LLM tool_call 参数校验失败: {e.message}")
            # 尝试修复常见错误（类型转换、缺失字段填充默认值）
            call["function"]["arguments"] = _attempt_repair(
                call["function"]["arguments"], tool_def.input_schema, e)
```

#### T4: 工具执行监控

**新增文件:** `backend/tools/monitor.py`

```python
class ToolMonitor:
    """包装工具调用，记录执行指标"""

    @staticmethod
    async def wrap(tool_name: str, fn, *args, **kwargs):
        start = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            duration_ms = (time.monotonic() - start) * 1000
            await _log_tool_call(tool_name, duration_ms, success=True)
            return result
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            await _log_tool_call(tool_name, duration_ms, success=False,
                                 error_type=type(e).__name__)
            raise

    @staticmethod
    def get_stats(tool_name: str, window_minutes: int = 60) -> dict:
        """返回 {avg_ms, p95_ms, error_rate, call_count}"""
```

**新增 MySQL 表:** `tool_calls_log`

| 列 | 类型 | 用途 |
|----|------|------|
| tool_name | VARCHAR(64) | 工具名称 |
| duration_ms | FLOAT | 执行耗时 |
| success | BOOLEAN | 是否成功 |
| error_type | VARCHAR(64) | 错误类型 |
| session_id | VARCHAR(128) | 会话关联 |
| request_id | VARCHAR(64) | 请求关联 |
| created_at | DATETIME | 时间戳 |

#### T5: Wiki 规则读取工具

基于 Flash 低成本，允许 LLM 动态读取 wiki 规则替代 gatekeep 硬编码。

**新增文件:** `backend/smartbi_mcp/tools/wiki_rules_tool.py`

```python
@ToolRegistry.register("wiki_query_rules", category="wiki",
    input_schema={"type": "object", "properties": {
        "query_text": {"type": "string"},
        "rule_categories": {"type": "array", "items": {"type": "string"}}
    }})
def wiki_query_rules(query_text: str, rule_categories: list[str] = None) -> dict:
    """从 wiki 读取与当前查询匹配的规则

    流程:
    1. 关键词匹配 wiki 概念页（product-params, compliance-redlines 等）
    2. 将匹配页面的 body 注入 Flash 模型
    3. Flash 提取与当前查询相关的规则片段
    4. 返回结构化规则 dict

    成本: Flash 约 ¥0.00005/次
    准确性收益: 补充 gatekeep 硬编码的 7 个纯硬编码阶段
    """
```

---

## 4. C — 上下文管理器 (Context Manager)

### 4.1 现状

三层上下文来源，两套 AgentMemory 竞争，importance 存而不用。

**准确性核心问题:**
1. **上下文双重发送** — context_resolver 发一次，BI agent parse 再发一次，同一信息两种表示可能混淆 LLM
2. **自动摘要不减压** — 5 轮触发摘要但 build_context_prompt 仍读原始轮次
3. **importance 存而不用** — 上下文选择纯按时间序
4. **find_similar 实现了但从未调用** — RAG 检索是空壳
5. **Wiki 上下文解析已实现但 LangGraph 未接入**

### 4.2 设计

#### C1: 统一上下文组装器

**新增文件:** `backend/langgraph/context_assembler.py`

**核心改动:** 消除上下文双重发送。当前 context_resolver 和 BI agent parse 分别向 LLM 发送相同对话历史，同一信息两种表示（原始文本 vs resolved_params）可能不一致，导致 LLM 解析偏移。

```python
class ContextAssembler:
    """一次组装，所有节点共享，不重复发送"""

    def __init__(self, token_budget=6000):
        self.token_budget = token_budget

    async def assemble(self, session_id: str, user_text: str,
                       agent_type: str) -> AssembledContext:
        """返回: AssembledContext(resolved_params, wiki_context, conversation_context,
                                    agent_memory_context, rule_context)"""

        # Step 1: Wiki 实体解析（确定性，最高优先级）
        wiki_entity = await self._resolve_wiki_entity(session_id, agent_type)
        # → 从 wiki.query.get_customer_profile() 读取 frontmatter
        # → 返回: {dimension, bank_name, product_type, appid, ...}

        # Step 2: Wiki 规则匹配（Flash 低成本，补充 gatekeep 盲区）
        wiki_rules = await self._match_wiki_rules(user_text)
        # → 关键词匹配 wiki 概念页
        # → Flash 提取相关规则片段
        # → 返回: {required_fields: [...], constraints: [...]}

        # Step 3: 对话历史（按 importance 排序，不再纯按时间）
        conversation = await self._build_conversation_context(session_id)
        # → 最近 3 轮原始格式
        # → 更早轮次使用 LLM 摘要（Flash 生成，~80 tokens/5轮）

        # Step 4: Agent 记忆（工具调用摘要 + 关键实体）
        agent_memory = await self._build_agent_memory(session_id)

        # Step 5: Token 预算分配
        allocated = self._allocate_budget(
            wiki_entity, wiki_rules, conversation, agent_memory)

        return AssembledContext(
            resolved_params=self._merge_params(wiki_entity, conversation),
            wiki_context=allocated.wiki_rules_text,     # 注入 system prompt
            conversation_context=allocated.conversation, # 注入 system prompt
            agent_memory_context=allocated.agent_memory, # 注入 system prompt
            wiki_hit=wiki_entity is not None,
        )
```

**Token 预算分配策略（6000 tokens 总预算）:**

| 来源 | 分配 | 说明 |
|------|------|------|
| Wiki 规则 | 15% (900) | Flash 读取，低成本提升准确性 |
| Wiki 实体 | 10% (600) | frontmatter 字段，确定性数据 |
| 对话历史 | 40% (2400) | 按 importance 排序，提炼信息 |
| Agent 记忆 | 15% (900) | 工具调用摘要 |
| 规则指令 | 20% (1200) | prompt_builder 输出 |

**改动文件:** `backend/langgraph/context_resolver.py` `_node_resolve_context()`

```python
# 改前: 直接调用 LLM 解析对话历史
# 改后: 调用 ContextAssembler，一次组装所有上下文
assembler = ContextAssembler()
context = await assembler.assemble(state.session_id, state.user_text, "bi")
# resolved_params 直接写入 state，不再发送原始上下文给后续节点
return {
    "resolved_params": context.resolved_params,
    "inherited_fields": list(context.resolved_params.keys()),
    "context_confidence": 0.9 if context.wiki_hit else 0.7,
    # 不再返回原始 context 文本给下游
}
```

**改动文件:** `backend/langgraph/agents/bi_agent.py` `_node_parse()`

```python
# 改前: build_system_prompt(state.context) — 再次发送原始上下文
# 改后: 不传 state.context，只使用 state.resolved_params
# 消除双重发送 = 消除 LLM 混淆源 = 提升准确率
```

**准确性收益:**
- 消除同一信息的两种表示，避免 LLM 混淆
- 省下的 token 空间留给 wiki 规则注入
- 预计每次请求减少 ~2,000-3,000 tokens 的无效重复

#### C2: 对话历史按 Importance 排序

**改动文件:** `backend/memory/store.py` `build_context_prompt()`

```python
# 改前: 按 turn_index 排序取 last N
turns = sorted(turns, key=lambda t: t["turn_index"], reverse=True)[:last_n]

# 改后: 按 importance DESC, turn_index DESC 排序
turns = sorted(turns, key=lambda t: (-t.get("importance", 1), -t["turn_index"]))[:last_n]
# 高 importance 轮次（包含比较、聚合、多维度）优先进入上下文
# 低 importance 轮次在预算不足时被截断
```

#### C3: 自动摘要实际减压

**改动文件:** `backend/memory/store.py` `build_context_prompt()`

当前问题：`should_summarize()` 每 5 轮触发，但摘要不用于 prompt 构建，原始轮次仍完整发送。

**改动内容:**
1. 最近 3 轮：原始格式（用户+系统解析）
2. 更早轮次：使用 `memory_summaries` 中的摘要（Flash 生成）

**摘要生成改为 LLM 驱动:**

```python
# 改前: 摘要是字段级 JSON（turn_indices, queries, products, has_comparison）
# 改后: 摘要是 LLM 生成的自然语言压缩

async def _generate_llm_summary(self, turns: list[dict]) -> str:
    """Flash 生成压缩摘要，~80 tokens/5轮"""
    prompt = "将以下5轮对话压缩为一句话摘要，保留关键实体和查询意图：\n"
    for t in turns:
        prompt += f"用户：{t['user_query']}\n"
    # Flash 调用，max_tokens=150, temperature=0.0
    return await llm_chat(prompt, system_prompt="摘要生成", task="summary_generate")
```

**准确性收益:**
- 10 轮对话的上下文从 ~3000 tokens 降到 ~1200 tokens
- 压缩是提炼信息（同一 product_type 只写1次），不是砍内容
- 省下的空间可注入更多 wiki 规则

#### C4: find_similar() 实际接入

**改动文件:** `backend/langgraph/context_assembler.py`

在 `assemble()` 方法中增加语义检索步骤：

```python
# 对于当前 user_text，调用 find_similar
similar = self.memory.find_similar(user_text, limit=3)
if similar:
    # 将相似历史查询的 parsed_params 作为补充上下文
    # 注入格式: "历史上类似查询: {query} → 参数: {params}"
    conversation += "\n## 相似历史查询\n"
    for s in similar:
        conversation += f"- {s['user_query']} → {s['parsed_params']}\n"
```

**准确性收益:** 用户问"上个月结汇量"时，系统发现类似查询"4月结汇量"的参数可参考，减少 LLM 推断错误。

#### C5: Prompt Builder 接入 Wiki

**改动文件:** `backend/llm_parser/prompt_builder.py` `build_system_prompt()`

```python
# 改前: 仅从 MySQL rule_items 注入规则
# 改后: 增加 wiki 概念页注入

def build_system_prompt(self, context=None, query_text=None):
    base = self._build_base_prompt(self.rules)

    # 新增: 根据查询关键词匹配 wiki 概念页
    if query_text:
        wiki_context = self._match_wiki_concepts(query_text)
        if wiki_context:
            base += f"\n\n## 业务规则补充（来自知识库）\n{wiki_context}"

    if context:
        base += f"\n\n## 对话上下文（多轮对话历史）\n{context}"

    return base

def _match_wiki_concepts(self, query_text: str) -> str | None:
    """关键词匹配 wiki 概念页，提取相关规则片段"""
    # 1. 提取查询中的产品类型、方向等关键词
    # 2. 搜索 wiki 概念页 (wiki.query.search_concepts)
    # 3. 返回匹配页面的 body 中与查询相关的片段
    # 预算: 上限 1200 tokens
```

**准确性收益:** 查询包含"远期"时自动注入 FWD 必填字段规则，LLM 知道要追问 tenor，返回 follow-up 而非错误结果。

---

## 5. S — 状态存储 (State Store)

### 5.1 现状

定价管线有 MySQL 持久化，BI 管线全内存。`wiki_pages` 表已新增。

### 5.2 设计

#### S1: MySQL Checkpointer（与 E2 合并）

见 E2 节。新增 `langgraph_checkpoints` 表和 `MySqlCheckpointer` 类。

#### S2: AgentState 结构化错误字段

**改动文件:** `backend/langgraph/state.py`

```python
# 改前
error: str = ""

# 改后
errors: list[dict] = field(default_factory=list)
# 每个 dict: {node: str, code: str, message: str,
#             severity: "fatal"|"warning"|"info", timestamp: float}
```

**改动文件:** `backend/langgraph/validators.py` `node_validate()`

```python
# 如果有 severity="fatal" 的错误，跳过验证直接返回错误响应
fatals = [e for e in state.errors if e["severity"] == "fatal"]
if fatals:
    return {"validation_warnings": [f["message"] for f in fatals],
            "sql_validated": False}
```

**准确性收益:** 下游节点可检查错误列表按严重程度决定是否继续，而非只看一个扁平字符串。

#### S3: Pricing State Machine 事务性

**改动文件:** `backend/pricing/service.py`

```python
# 改前: 先改内存 FSM → 再写 MySQL（失败则不一致）
# 改后: MySQL 事务包裹两步操作

async def _transition_and_save(self, machine, new_status, session_data):
    conn = self.mysql.get_conn()
    try:
        # Step 1: 写 MySQL（含 valid_until）
        self.mysql.save_pricing_session(conn, session_data)
        # Step 2: 成功后改内存 FSM
        machine.transition(new_status)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

额外：`valid_until` 写入 `pricing_sessions` 表，重建时恢复。

#### S4: result_hash 实际填充

**改动文件:** `backend/app.py` `_write_audit_log()`

```python
# 改前: result_hash 列始终 NULL
# 改后: SHA-256(columns + rows JSON)
import hashlib, json
result_hash = hashlib.sha256(
    json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False).encode()
).hexdigest()
```

用途：检测结果是否被篡改、对比两次查询结果是否相同。

#### S5: Token 使用追踪表

**新增 MySQL 表:** `token_usage_log`

| 列 | 类型 | 用途 |
|----|------|------|
| request_id | VARCHAR(64) | 请求关联 |
| session_id | VARCHAR(128) | 会话关联 |
| call_site | VARCHAR(32) | 调用点（9 种） |
| model_tier | VARCHAR(8) | flash / pro |
| model_name | VARCHAR(64) | 实际模型名 |
| prompt_tokens | INT | 输入 token 数 |
| completion_tokens | INT | 输出 token 数 |
| total_tokens | INT | 总 token 数 |
| duration_ms | FLOAT | 调用耗时 |
| created_at | DATETIME | 时间戳 |

**用途：**
1. **质量归因** — 哪类任务 token 消耗高？高消耗的准确性是否也高？
2. **异常检测** — 单次调用 > 10K tokens 可能注入了过多上下文，LLM 被干扰
3. **模型选择验证** — Flash vs Pro 在同一任务上的准确性对比
4. **不设硬上限** — session 累计超过 30K tokens 记录标记供分析，不降级

---

## 6. L — 生命周期钩子 (Lifecycle Hooks)

### 6.1 现状

事件总线 9 种事件，1 个活跃订阅者（InsightEngine），无 FastAPI 中间件，无认证。

### 6.2 设计

#### L1: FastAPI 中间件栈

**新增文件:** `backend/middleware/__init__.py`
**新增文件:** `backend/middleware/request_id.py`
**新增文件:** `backend/middleware/timing.py`
**新增文件:** `backend/middleware/cors.py`
**新增文件:** `backend/middleware/error_handler.py`

**注册顺序（app.py）:**

```python
app.add_middleware(ErrorHandlerMiddleware)   # 最外层，捕获所有异常
app.add_middleware(TimingMiddleware)          # 请求耗时记录
app.add_middleware(RequestIDMiddleware)       # X-Request-ID 注入
app.add_middleware(CORSMiddleware)            # CORS 配置
```

**RequestIDMiddleware:** 生成 UUID 注入 `X-Request-ID` header，贯穿整个请求生命周期，写入 audit_log 和 token_usage_log。

**TimingMiddleware:** 记录每个请求的 method、path、status_code、duration_ms，写入 `request_log` 表。

**ErrorHandlerMiddleware:** 捕获未处理异常，返回统一 JSON 错误格式，记录到 `error_log`。

#### L2: 认证中间件（轻量级）

**新增文件:** `backend/middleware/auth.py`

```python
class APIKeyAuthMiddleware:
    """轻量级 API Key 认证"""

    WHITELIST = ["/api/health", "/docs", "/openapi.json"]

    async def __call__(self, request, call_next):
        if not os.getenv("ENABLE_AUTH", "true").lower() == "true":
            return await call_next(request)  # 开发模式跳过
        if request.url.path in self.WHITELIST:
            return await call_next(request)
        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not api_key or not self._validate_key(api_key, request.url.path):
            return JSONResponse(status_code=401, content={"error": "Invalid API key"})
        return await call_next(request)
```

**新增 MySQL 表:** `api_keys`

| 列 | 类型 | 用途 |
|----|------|------|
| key_hash | VARCHAR(64) | SHA-256 of API key |
| permissions | JSON | 权限列表 ["bi", "pricing", "admin"] |
| created_at | DATETIME | 创建时间 |
| expires_at | DATETIME | 过期时间 |

#### L3: 事件总线补全订阅者

**改动文件:** `backend/app.py` startup 事件

```python
# wiki.page_updated → 触发 prompt 缓存失效
bus.subscribe("wiki.page_updated", _on_wiki_updated)

async def _on_wiki_updated(event):
    """Wiki 页面更新时清除规则缓存，下次查询重新加载"""
    rules_engine._rules_cache.clear()
    prompt_builder._base_prompt_cache = None
    logger.info(f"Wiki 更新，已清除规则缓存: {event.data.get('slug')}")

# quote.expired → 日志记录
bus.subscribe("quote.expired", _on_quote_expired)

async def _on_quote_expired(event):
    logger.info(f"报价过期: pricing_id={event.data.get('pricing_id')}")

# market.rate_changed / customer.risk_alert → 暂不实现（无外部数据源）
```

#### L4: 定价审计补全

**改动文件:** `backend/pricing/service.py`

```python
# 改前: engine_raw_response 和 llm_decision_steps 列为空
# 改后: 每次写入 pricing_audit_log 时填充

# 在 handle_inquiry 中:
mysql_store.add_pricing_audit(
    pricing_id=pricing_id,
    action="INQUIRY",
    detail=detail,
    engine_raw_response=engine_result.raw_json,  # 新增：定价引擎原始响应
    llm_decision_steps=llm_steps,                 # 新增：LLM 解析思考过程（如果用了 LLM 兜底）
    evidence_hash=evidence_hash,
    evidence_type="quote",
)
```

#### L5: LangGraph 节点级钩子

**新增文件:** `backend/langgraph/hooks.py`

```python
class NodeHooks:
    """LangGraph 节点执行前后钩子"""

    @staticmethod
    def before_node(state: AgentState, node_name: str):
        """记录开始时间、注入 request-id"""
        state["_node_start_time"] = time.monotonic()
        logger.debug(f"[{state.request_id}] Node {node_name} started")

    @staticmethod
    def after_node(state: AgentState, node_name: str, result: dict):
        """记录完成、写审计"""
        duration_ms = (time.monotonic() - state.get("_node_start_time", 0)) * 1000
        logger.debug(f"[{state.request_id}] Node {node_name} completed in {duration_ms:.0f}ms")
        # 异步写入 tool_calls_log（与 T4 共享表）

    @staticmethod
    def on_error(state: AgentState, node_name: str, error: Exception):
        """结构化错误记录"""
        state.errors.append({
            "node": node_name,
            "code": type(error).__name__,
            "message": str(error),
            "severity": "fatal" if isinstance(error, (ConnectionError, TimeoutError)) else "warning",
            "timestamp": time.time(),
        })
```

#### L6: LLM 调用前后钩子

**改动文件:** `backend/llm_parser/llm_client.py`

```python
# 在 llm_parse / llm_chat / llm_tool_call 三个函数中:

# 调用前:
event_data = {"call_site": task, "model": model, "estimated_tokens": len(prompt) // 2}
bus.publish("llm.call_started", event_data)

# 调用后:
usage = response.usage  # 读取实际 token 使用量
token_log = {
    "call_site": task,
    "model_tier": profile["tier"],
    "model_name": model,
    "prompt_tokens": usage.prompt_tokens,
    "completion_tokens": usage.completion_tokens,
    "total_tokens": usage.total_tokens,
    "duration_ms": duration_ms,
}
# 异步写入 token_usage_log（fire-and-forget）
asyncio.create_task(_write_token_log(token_log))
bus.publish("llm.call_completed", token_log)

# 异常:
bus.publish("llm.call_failed", {"call_site": task, "model": model, "error": str(e)})
circuit_breaker.record_failure(task)
```

---

## 7. V — 评估接口 (Evaluation Interface)

### 7.1 现状

强单请求评估（PostValidator、RiskGuard），弱跨请求评估（无追踪、无 A/B、无趋势）。

### 7.2 设计

#### V1: 评估数据采集器

**新增文件:** `backend/evaluation/collector.py`

```python
class EvaluationCollector:
    """每次 LangGraph 执行完成后采集质量指标"""

    async def collect(self, state: AgentState, duration_ms: float):
        record = {
            "request_id": state.request_id,
            "session_id": state.session_id,
            "agent_type": state.router_decision.get("agent", "BI"),
            "router_confidence": state.router_decision.get("confidence", 0),
            "parse_confidence": state.parsed_params.get("_confidence", 0),
            "post_validation_mismatches": self._extract_mismatches(state),
            "sql_validated": state.sql_validated,
            "validation_warnings_count": len(state.validation_warnings),
            "total_duration_ms": duration_ms,
            "wiki_hit": getattr(state, "wiki_hit", False),
            "errors_count": len(state.errors),
            "fatal_errors": len([e for e in state.errors if e["severity"] == "fatal"]),
        }
        # 异步写入 evaluation_records 表
        await _write_eval_record(record)
```

**新增 MySQL 表:** `evaluation_records`

| 列 | 类型 | 用途 |
|----|------|------|
| request_id | VARCHAR(64) | 主键 |
| session_id | VARCHAR(128) | 会话关联 |
| agent_type | VARCHAR(16) | BI / PRICING / ANALYSIS |
| router_confidence | FLOAT | 路由置信度 |
| parse_confidence | FLOAT | 解析置信度 |
| post_validation_mismatches | JSON | 数字不匹配列表 |
| sql_validated | BOOLEAN | SQL 是否安全 |
| validation_warnings_count | INT | 验证警告数 |
| total_duration_ms | FLOAT | 总耗时 |
| wiki_hit | BOOLEAN | 是否命中 Wiki |
| errors_count | INT | 错误数 |
| fatal_errors | INT | 致命错误数 |
| created_at | DATETIME | 时间戳 |

#### V2: 质量指标 API

**新增文件:** `backend/evaluation/routes.py` — 挂载在 `/api/evaluation/`

| 端点 | 说明 |
|------|------|
| `GET /api/evaluation/accuracy?window=24h` | PostValidator 不匹配率趋势 |
| `GET /api/evaluation/latency?window=24h` | P50/P95/P99 延迟 |
| `GET /api/evaluation/routing?window=24h` | 路由分布（BI vs Pricing vs Rejected） |
| `GET /api/evaluation/wiki-impact?window=24h` | Wiki 命中率 vs 查询质量 |
| `GET /api/evaluation/token-usage?window=24h&group_by=call_site` | Token 使用分析 |
| `GET /api/evaluation/error-rate?window=24h` | 错误率趋势 |

#### V3: 前端评估面板

**新增文件:** `frontend/src/components/EvaluationPanel.vue`

- 质量指标卡片（准确率、延迟、路由分布）
- 趋势图（ECharts 折线图）
- Token 使用分析标签页（调用分布、Flash vs Pro 比例、成本趋势）
- 最近失败查询列表（可展开查看详情）
- 与 WikiPanel 同级，在侧边栏展开

#### V4: 规则 A/B 测试框架

**新增文件:** `backend/evaluation/ab_test.py`

```python
class ABTest:
    """为规则变更创建实验，对比新旧规则效果"""

    def __init__(self, test_id, variant_a_rules, variant_b_rules,
                 traffic_split=0.5, min_samples=100):
        ...

    def assign_variant(self, session_id: str) -> str:
        """确定性分配: hash(session_id + test_id) % 100 < traffic_split * 100"""
        ...

    def get_results(self, test_id: str) -> dict:
        """对比两个 variant 的准确率、延迟、不匹配率"""
        ...
```

**API:**
- `POST /api/evaluation/ab-tests` — 创建实验
- `GET /api/evaluation/ab-tests/{id}/results` — 查看结果
- `POST /api/evaluation/ab-tests/{id}/complete` — 结束实验

#### V5: 降级检测告警

**新增文件:** `backend/evaluation/alerts.py`

```python
class DegradationAlerts:
    """定义质量阈值，超阈值发布告警事件"""

    THRESHOLDS = {
        "mismatch_rate": 0.10,    # PostValidator 不匹配率 > 10%
        "p95_latency_ms": 5000,   # P95 延迟 > 5s
        "rejection_rate": 0.30,   # 路由拒绝率 > 30%
        "error_rate": 0.05,       # 致命错误率 > 5%
    }

    async def check(self):
        """定时检查（每5分钟），超阈值发布 evaluation.degraded 事件"""
        for metric, threshold in self.THRESHOLDS.items():
            current = await self._compute_metric(metric, window_minutes=30)
            if current > threshold:
                bus.publish("evaluation.degraded", {
                    "metric": metric,
                    "current": current,
                    "threshold": threshold,
                })
                logger.warning(f"质量降级: {metric} = {current} > {threshold}")
```

#### V6: Token 质量分析

**基于 `token_usage_log` 表的聚合查询:**

| 分析维度 | 说明 |
|----------|------|
| 按 call_site 分组 | 哪个调用点消耗最多 token？高消耗的准确率如何？ |
| Flash vs Pro 对比 | 同一任务两种模型的准确率差异 |
| 异常检测 | 单次调用 > 10K tokens → 可能注入了过多上下文 |
| 趋势分析 | 平均 token/请求随时间变化，反映系统使用模式 |

**不是成本控制工具，是质量归因工具。**

---

## 8. SessionStrategy — 自适应会话策略

### 8.1 设计

**新增文件:** `backend/langgraph/session_strategy.py`

```python
class SessionStrategy:
    """根据会话状态调整策略，保证准确性优先

    核心原则: 升级不降级，复杂场景用更强的模型和更深的上下文
    """

    def get_strategy(self, session_id: str) -> dict:
        turn_count = self._get_turn_count(session_id)
        complexity = self._estimate_complexity(session_id)
        has_wiki_hit = self._check_wiki_hit(session_id)

        # 短会话 + 简单查询 → Flash + 标准上下文
        if turn_count <= 3 and complexity == "simple":
            return {
                "model_tier": "flash",
                "context_depth": 3,
                "wiki_injection": True,
                "summary_mode": "none",
            }

        # 中等会话 → Flash + 增加上下文深度 + 压缩旧轮次
        if turn_count <= 10:
            return {
                "model_tier": "flash",
                "context_depth": 5,
                "wiki_injection": True,
                "summary_mode": "compress_old",
            }

        # 长会话/复杂查询 → Pro + 深度上下文 + LLM 摘要
        return {
            "model_tier": "pro",            # 升级，不是降级
            "context_depth": 10,
            "wiki_injection": True,
            "summary_mode": "llm_summary",  # Flash 生成摘要，Pro 处理主查询
        }

    def _estimate_complexity(self, session_id: str) -> str:
        """基于最近轮次的参数复杂度估算"""
        recent = self.memory.get_context(session_id, last_n=3)
        # 有比较查询、多维度、聚合 → "complex"
        # 否则 → "simple"
        for t in recent:
            params = t.get("parsed_params", {})
            if params.get("comparison") or params.get("hedge_ratio") \
               or params.get("aggregate"):
                return "complex"
        return "simple"
```

---

## 9. 实施计划

### 9.1 分阶段实施

```
Phase 0 — 质量基础（1周）
  E6: QualityRouter 多模型路由
  S5: token_usage_log 表 + LLM 调用 usage 读取
  L6: LLM 调用前后钩子
  → 目的: 让每次调用可衡量、可归因

Phase 1 — 准确性核心（2周）
  E1: Wiki Context Resolver 接入 LangGraph
  C2: 消除上下文双重发送
  C6: Wiki 规则注入 Prompt Builder
  C3: 摘要减压（提炼信息）
  C1: 统一上下文组装器
  → 目的: 每个 token 都服务于准确性

Phase 2 — 基础设施（1.5周）
  T1: 统一工具注册表
  S2: AgentState 结构化错误
  L1: FastAPI 中间件栈
  E2+S1: MySQL Checkpointer
  E3: 统一重试层
  E5: 熔断器
  SessionStrategy: 自适应会话策略

Phase 3 — 增强层（2周）
  T5: Wiki 规则读取工具
  T2: Wiki MCP 工具
  T3: Schema 校验
  T4: 工具执行监控
  C4: importance 排序
  C5: find_similar 接入
  S3: Pricing 事务性
  S4: result_hash 填充
  L2: 认证中间件
  L3: 事件订阅补全
  L4: 审计补全
  L5: 节点钩子

Phase 4 — 评估层（1周）
  V1: 评估数据采集器
  V2: 质量指标 API
  V6: Token 质量分析
  V3: 前端评估面板
  V4: A/B 测试框架
  V5: 降级检测告警

Phase 5 — 统一层（1周）
  E4: Orchestrator 并入 LangGraph (analysis_agent)
  前端统一到 /api/chat
  废弃 /api/query 端点
```

### 9.2 依赖关系

```
Phase 0 ─────────────────────────────────────────────────────┐
  E6 → S5 → L6                                               │
                                                              ▼
Phase 1 ─────────────────────────────────────────────────────┐
  E1 → C2 → C6 → C3 → C1                                    │
                                                              ▼
Phase 2 ─────────────────────────────────────────────────────┐
  T1 → S2 → L1 → E2+S1 → E3 → E5 → SessionStrategy         │
                                                              ▼
Phase 3 ─────────────────────────────────────────────────────┐
  T5 → T2 → T3 → T4 → C4 → C5 → S3 → S4 → L2 → L3 → L4 → L5
                                                              ▼
Phase 4 ─────────────────────────────────────────────────────┐
  V1 → V2 → V6 → V3 → V4 → V5                               │
                                                              ▼
Phase 5 ─────────────────────────────────────────────────────
  E4 → 前端统一
```

### 9.3 新增文件清单

| 文件路径 | 用途 |
|----------|------|
| `backend/llm_parser/quality_router.py` | 多模型路由 |
| `backend/langgraph/checkpointer.py` | MySQL Checkpointer |
| `backend/langgraph/retry.py` | 统一重试层 |
| `backend/langgraph/circuit_breaker.py` | 熔断器 |
| `backend/langgraph/context_assembler.py` | 统一上下文组装器 |
| `backend/langgraph/session_strategy.py` | 自适应会话策略 |
| `backend/langgraph/hooks.py` | 节点级钩子 |
| `backend/langgraph/agents/analysis_agent.py` | 分析子图 |
| `backend/tools/registry.py` | 统一工具注册表 |
| `backend/tools/monitor.py` | 工具执行监控 |
| `backend/smartbi_mcp/tools/wiki_search_tool.py` | Wiki 搜索 MCP 工具 |
| `backend/smartbi_mcp/tools/wiki_get_tool.py` | Wiki 获取 MCP 工具 |
| `backend/smartbi_mcp/tools/wiki_rules_tool.py` | Wiki 规则读取 MCP 工具 |
| `backend/middleware/__init__.py` | 中间件包 |
| `backend/middleware/request_id.py` | Request-ID 中间件 |
| `backend/middleware/timing.py` | 计时中间件 |
| `backend/middleware/cors.py` | CORS 中间件 |
| `backend/middleware/error_handler.py` | 全局异常处理中间件 |
| `backend/middleware/auth.py` | API Key 认证中间件 |
| `backend/evaluation/collector.py` | 评估数据采集器 |
| `backend/evaluation/routes.py` | 评估 API 路由 |
| `backend/evaluation/ab_test.py` | A/B 测试框架 |
| `backend/evaluation/alerts.py` | 降级检测告警 |
| `frontend/src/components/EvaluationPanel.vue` | 评估面板组件 |

### 9.4 新增 MySQL 表

| 表名 | 用途 |
|------|------|
| `langgraph_checkpoints` | LangGraph 检查点 |
| `token_usage_log` | Token 使用追踪 |
| `tool_calls_log` | 工具调用监控 |
| `evaluation_records` | 评估指标记录 |
| `api_keys` | API Key 认证 |

---

## 10. 验收标准

### 10.1 Phase 0 验收

- [ ] 所有 9 个 LLM 调用点读取 `response.usage` 并写入 `token_usage_log`
- [ ] QualityRouter 按 task 类型选择 Flash/Pro 模型
- [ ] `GET /api/evaluation/token-usage` 返回按 call_site 分组的 token 使用数据

### 10.2 Phase 1 验收

- [ ] LangGraph 管线不再双重发送对话历史（日志验证：context_resolver LLM 调用后，BI agent parse 不再包含原始 context）
- [ ] Wiki 规则注入 prompt_builder，查询包含"远期"时自动注入 FWD 必填字段
- [ ] 10 轮对话上下文 token 消耗较改造前下降 40%+（通过 token_usage_log 对比）
- [ ] 准确性不降：PostValidator 不匹配率不高于改造前

### 10.3 Phase 2 验收

- [ ] LangGraph 管线崩溃后可从最近 checkpoint 恢复
- [ ] Oracle/LLM/Pricing Engine 超时自动重试（最多 2 次）
- [ ] 连续 5 次调用失败触发熔断，降级到 fallback
- [ ] 所有 HTTP 请求有 X-Request-ID，可追踪全链路

### 10.4 Phase 3 验收

- [ ] 新增 MCP 工具（wiki_search, wiki_get, wiki_rules）可通过 MCP 协议调用
- [ ] LLM tool_call 返回的参数通过 JSON Schema 校验
- [ ] Pricing State Machine 事务性：DB 写入失败不改变内存状态
- [ ] API Key 认证生效，无 key 的请求返回 401

### 10.5 Phase 4 验收

- [ ] 前端评估面板展示准确率趋势、延迟分布、路由分布
- [ ] Token 质量分析可按 call_site/Flash vs Pro 聚合
- [ ] A/B 测试框架可对比两版规则的准确率差异
- [ ] 降级告警触发时发布 `evaluation.degraded` 事件

### 10.6 Phase 5 验收

- [ ] 前端所有查询统一走 `/api/chat`，`/api/query` 标记为 deprecated
- [ ] 分析查询（为什么/原因/分析）路由到 analysis_agent 子图
- [ ] 前端 `isAnalytical` 逻辑移除，由后端 Router 统一判断
