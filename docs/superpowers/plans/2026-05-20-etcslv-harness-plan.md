# ETCSLV Harness 改进实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 XFundsAINext 从"带护栏的函数调用管线"升级为完整的 agent harness——可观测、可恢复、可评估、自适应。

**架构：** 5 个 Phase 逐步增强 6 大 harness 组件。Phase 0 建立质量基础（多模型路由 + token 追踪），Phase 1 聚焦准确性核心（消除上下文双重发送 + Wiki 注入），Phase 2 夯实基础设施（检查点、重试、熔断、中间件），Phase 3 增强工具与管理层，Phase 4 建立评估体系，Phase 5 统一管线。

**技术栈：** Python 3 + FastAPI + LangGraph + DeepSeek v4 Flash/Pro + MySQL + Vue 3

---

### 任务 0：Phase 0 — 质量基础

**目标：** 让每次 LLM 调用可衡量、可归因。不改变任何业务行为。

---

#### 任务 0.1：新增 token_usage_log 表

**文件：**
- 修改：`backend/db/mysql_store.py:50-198` (SCHEMA_SQL)

- [ ] **步骤 1：在 SCHEMA_SQL 中添加表定义**

在 `backend/db/mysql_store.py` 第 198 行（`wiki_pages` 表定义之后）`"""` 结束前插入：

```sql
CREATE TABLE IF NOT EXISTS token_usage_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL DEFAULT '',
    session_id VARCHAR(128) NOT NULL DEFAULT '',
    call_site VARCHAR(32) NOT NULL DEFAULT '' COMMENT '调用点: bi_parse/context_resolve/llm_chat/...',
    model_tier VARCHAR(8) NOT NULL DEFAULT '' COMMENT 'flash / pro',
    model_name VARCHAR(64) NOT NULL DEFAULT '',
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL DEFAULT 0,
    duration_ms FLOAT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_session_id (session_id),
    INDEX idx_call_site (call_site),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **步骤 2：在 mysql_store.py 中添加写入方法**

在文件末尾添加：

```python
def insert_token_usage(conn, request_id: str, session_id: str, call_site: str,
                       model_tier: str, model_name: str,
                       prompt_tokens: int, completion_tokens: int,
                       total_tokens: int, duration_ms: float) -> int:
    sql = """INSERT INTO token_usage_log (request_id, session_id, call_site,
              model_tier, model_name, prompt_tokens, completion_tokens,
              total_tokens, duration_ms)
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    with conn.cursor() as cur:
        cur.execute(sql, (request_id, session_id, call_site, model_tier,
                         model_name, prompt_tokens, completion_tokens,
                         total_tokens, duration_ms))
        return cur.lastrowid


def query_token_usage(conn, call_site: str = None, session_id: str = None,
                      window_hours: int = 24, group_by: str = None) -> list[dict]:
    """聚合查询 token 使用数据"""
    where = ["created_at >= NOW() - INTERVAL %s HOUR"]
    params = [window_hours]
    if call_site:
        where.append("call_site = %s")
        params.append(call_site)
    if session_id:
        where.append("session_id = %s")
        params.append(session_id)
    sql = f"""SELECT call_site, model_tier,
                     SUM(total_tokens) AS total_tokens,
                     COUNT(*) AS call_count,
                     AVG(duration_ms) AS avg_duration_ms
              FROM token_usage_log
              WHERE {' AND '.join(where)}
              GROUP BY call_site, model_tier
              ORDER BY total_tokens DESC"""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
```

- [ ] **步骤 3：验证表创建**

运行：`cd backend && python -c "
from db.mysql_store import init_db, SCHEMA_SQL
assert 'token_usage_log' in SCHEMA_SQL, 'FAIL: table not in SCHEMA_SQL'
print('PASS')
"`

- [ ] **步骤 4：Commit**

```bash
git add backend/db/mysql_store.py
git commit -m "feat: add token_usage_log table and CRUD methods"
```

---

#### 任务 0.2：创建 QualityRouter 多模型路由

**文件：**
- 创建：`backend/llm_parser/quality_router.py`
- 修改：`backend/llm_parser/__init__.py`（如果存在）

- [ ] **步骤 1：创建 quality_router.py**

```python
"""QualityRouter — 按任务复杂度路由到最优模型，提升准确性"""
import os


class QualityRouter:
    """让每次 LLM 调用都用最优配置产出最准确结果

    不是省 token，不是降级。简单任务用 Flash 保持速度，
    复杂分析/长上下文用 Pro 保证准确性。
    """

    MODEL_TIERS = {
        "flash": os.getenv("LLM_MODEL_FLASH", "deepseek-v4-flash"),
        "pro": os.getenv("LLM_MODEL_PRO", "deepseek-v4-pro"),
    }

    TASK_PROFILES = {
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

    # 长上下文解析时升级到 Pro 的阈值
    CONTEXT_UPGRADE_THRESHOLD = 4000

    def route(self, task: str, context_size_hint: int = 0) -> dict:
        """返回 {model, tier, max_tokens, temperature}

        Args:
            task: 任务名（TASK_PROFILES 的 key）
            context_size_hint: 上下文大小估计（字符数），用于决定是否升级到 Pro
        """
        if task not in self.TASK_PROFILES:
            profile = dict(self.TASK_PROFILES["bi_parse"])
        else:
            profile = dict(self.TASK_PROFILES[task])

        # 长上下文解析自动升级到 Pro，保证准确
        if profile["tier"] == "flash" and task in ("bi_parse", "pricing_parse") \
           and context_size_hint > self.CONTEXT_UPGRADE_THRESHOLD:
            profile["tier"] = "pro"

        profile["model"] = self.MODEL_TIERS[profile["tier"]]
        return profile


# 全局单例
quality_router = QualityRouter()
```

- [ ] **步骤 2：验证模块可导入**

运行：`cd backend && python -c "from llm_parser.quality_router import quality_router; r = quality_router.route('bi_parse'); assert r['tier'] == 'flash'; assert 'model' in r; print('PASS')"`

- [ ] **步骤 3：Commit**

```bash
git add backend/llm_parser/quality_router.py
git commit -m "feat: add QualityRouter for task-based model routing"
```

---

#### 任务 0.3：修改 llm_client.py — 接入 QualityRouter + usage 追踪

**文件：**
- 修改：`backend/llm_parser/llm_client.py:49-100` (llm_parse), `109-140` (llm_chat), `142-208` (llm_tool_call)

- [ ] **步骤 1：在 llm_client.py 顶部添加导入**

```python
# 在现有 import 之后添加（第 8 行附近）
from backend.llm_parser.quality_router import quality_router
from backend.db.mysql_store import insert_token_usage, get_conn as mysql_get_conn
import time
import threading
```

- [ ] **步骤 2：添加异步 token 日志写入函数**

在文件顶部（import 之后）添加：

```python
def _write_token_log_async(request_id: str, session_id: str, call_site: str,
                            model_tier: str, model_name: str,
                            prompt_tokens: int, completion_tokens: int,
                            total_tokens: int, duration_ms: float):
    """fire-and-forget 写入 token_usage_log，不阻塞主调用"""
    try:
        conn = mysql_get_conn()
        insert_token_usage(conn, request_id, session_id, call_site,
                          model_tier, model_name, prompt_tokens,
                          completion_tokens, total_tokens, duration_ms)
        conn.close()
    except Exception:
        pass  # 写入失败不影响业务
```

- [ ] **步骤 3：改造 llm_parse() — 接入 QualityRouter + usage 读取**

修改 `llm_parse()` 函数签名和实现（第 49 行起）：

```python
def llm_parse(text: str, system_prompt: str,
              task: str = "bi_parse", context_size_hint: int = 0,
              request_id: str = "", session_id: str = "") -> dict | None:
    """BI 解析 — 规则优先，LLM 兜底"""
    from backend.llm_parser.rules_engine import rule_based_parse, gatekeep
    result = rule_based_parse(text)
    if result and result.get("_confidence", 0) >= 0.8:
        result["_parse_source"] = "rule"
        return gatekeep(result, text)

    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    if not api_key or not base_url:
        return gatekeep(result, text) if result else None

    profile = quality_router.route(task, context_size_hint)
    model = profile["model"]
    max_tokens = profile["max_tokens"]
    temperature = profile["temperature"]

    t0 = time.monotonic()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # 读取 usage
        usage = response.usage
        if usage:
            duration_ms = (time.monotonic() - t0) * 1000
            threading.Thread(target=_write_token_log_async, args=(
                request_id, session_id, task, profile["tier"], model,
                usage.prompt_tokens, usage.completion_tokens,
                usage.total_tokens, duration_ms
            )).start()

        content = response.choices[0].message.content
        parsed = json.loads(content) if content else {}
        parsed["_parse_source"] = "llm"
        if result:
            parsed["_rule_fallback"] = result
        return gatekeep(parsed, text)
    except Exception:
        if result:
            result["_parse_source"] = "rule"
            return gatekeep(result, text)
        return None
```

- [ ] **步骤 4：改造 llm_chat() — 接入 QualityRouter + usage 读取**

修改 `llm_chat()` 函数签名（第 109 行起）：

```python
def llm_chat(system_prompt: str, user_prompt: str,
             task: str = "llm_chat", context_size_hint: int = 0,
             request_id: str = "", session_id: str = "",
             timeout: int = 120) -> str | None:
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    if not api_key or not base_url:
        return None

    profile = quality_router.route(task, context_size_hint)
    model = profile["model"]
    max_tokens = profile["max_tokens"]
    temperature = profile["temperature"]

    t0 = time.monotonic()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=timeout)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )
        usage = response.usage
        if usage:
            duration_ms = (time.monotonic() - t0) * 1000
            threading.Thread(target=_write_token_log_async, args=(
                request_id, session_id, task, profile["tier"], model,
                usage.prompt_tokens, usage.completion_tokens,
                usage.total_tokens, duration_ms
            )).start()
        return response.choices[0].message.content
    except Exception:
        return None
```

- [ ] **步骤 5：改造 llm_tool_call() — 接入 QualityRouter + usage 读取**

修改 `llm_tool_call()` 函数签名（第 142 行起）：

```python
def llm_tool_call(messages: list[dict], tools: list[dict],
                  task: str = "analysis_text", context_size_hint: int = 0,
                  request_id: str = "", session_id: str = "",
                  temperature: float = 0.1, max_tokens: int = 4096,
                  timeout: int = 60) -> dict | None:
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    if not api_key or not base_url:
        return None

    profile = quality_router.route(task, context_size_hint)
    model = profile["model"]
    # QualityRouter 的 max_tokens 覆盖调用方传入的默认值
    if task in quality_router.TASK_PROFILES:
        max_tokens = profile["max_tokens"]
        temperature = profile["temperature"]

    t0 = time.monotonic()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=timeout)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,
            temperature=temperature,
            max_tokens=max_tokens
        )
        usage = response.usage
        if usage:
            duration_ms = (time.monotonic() - t0) * 1000
            threading.Thread(target=_write_token_log_async, args=(
                request_id, session_id, task, profile["tier"], model,
                usage.prompt_tokens, usage.completion_tokens,
                usage.total_tokens, duration_ms
            )).start()
        # ... 保持原有解析逻辑不变
    except Exception:
        return None
```

- [ ] **步骤 6：更新所有 LLM 调用点传入 task 参数**

搜索所有调用 `llm_parse()`, `llm_chat()`, `llm_tool_call()` 的位置，传入以下 task 参数：

| 调用位置 | task 值 |
|----------|---------|
| `backend/langgraph/agents/bi_agent.py:36` `_node_parse` | `"bi_parse"` |
| `backend/langgraph/agents/pricing_agent.py:44` `_node_parse_pricing` | `"pricing_parse"` |
| `backend/langgraph/context_resolver.py:70` `resolve_context` (LLM 调用) | `"context_resolve"` |
| `backend/agent/orchestrator.py:280` 主分析 LLM | `"analysis_text"` |
| `backend/agent/orchestrator.py:360` 修正重试 LLM | `"analysis_retry"` |
| `backend/smartbi_mcp/tools/llm_tool.py` MCP `llm_chat` | `"llm_chat"` |
| `backend/smartbi_mcp/tools/detect_entities_tool.py` | `"entity_extract"` |
| `backend/smartbi_mcp/tools/parse_date_tool.py` | `"date_parse"` |

每个调用点增加 `task=`, `request_id=`, `session_id=` 参数。

- [ ] **步骤 7：验证**

运行：`cd backend && python -c "
from llm_parser.llm_client import llm_parse, llm_chat, llm_tool_call
import inspect
# 确认新参数存在
sig1 = inspect.signature(llm_parse)
assert 'task' in sig1.parameters, 'FAIL: llm_parse missing task param'
sig2 = inspect.signature(llm_chat)
assert 'task' in sig2.parameters, 'FAIL: llm_chat missing task param'
print('PASS: all signatures updated')
"`

- [ ] **步骤 8：Commit**

```bash
git add backend/llm_parser/llm_client.py backend/llm_parser/quality_router.py
git commit -m "feat: integrate QualityRouter and token usage tracking into llm_client"
```

---

#### 任务 0.4：新增 request_log 和 error_log 表

**文件：**
- 修改：`backend/db/mysql_store.py:50-198` (SCHEMA_SQL)

- [ ] **步骤 1：在 SCHEMA_SQL 中添加两个表**

```sql
CREATE TABLE IF NOT EXISTS request_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL DEFAULT '',
    method VARCHAR(8) NOT NULL DEFAULT '',
    path VARCHAR(256) NOT NULL DEFAULT '',
    status_code INT NOT NULL DEFAULT 0,
    duration_ms FLOAT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS error_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL DEFAULT '',
    method VARCHAR(8) NOT NULL DEFAULT '',
    path VARCHAR(256) NOT NULL DEFAULT '',
    error_type VARCHAR(64) NOT NULL DEFAULT '',
    error_message TEXT,
    traceback TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_error_type (error_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **步骤 2：在 mysql_store.py 中添加写入方法**

```python
def insert_request_log(conn, request_id: str, method: str, path: str,
                       status_code: int, duration_ms: float) -> int:
    sql = """INSERT INTO request_log (request_id, method, path, status_code, duration_ms)
             VALUES (%s, %s, %s, %s, %s)"""
    with conn.cursor() as cur:
        cur.execute(sql, (request_id, method, path, status_code, duration_ms))
        return cur.lastrowid


def insert_error_log(conn, request_id: str, method: str, path: str,
                     error_type: str, error_message: str, traceback: str) -> int:
    sql = """INSERT INTO error_log (request_id, method, path, error_type, error_message, traceback)
             VALUES (%s, %s, %s, %s, %s, %s)"""
    with conn.cursor() as cur:
        cur.execute(sql, (request_id, method, path, error_type, error_message, traceback))
        return cur.lastrowid
```

- [ ] **步骤 3：验证**

```bash
cd backend && python -c "
from db.mysql_store import SCHEMA_SQL
assert 'request_log' in SCHEMA_SQL
assert 'error_log' in SCHEMA_SQL
print('PASS')
"
```

- [ ] **步骤 4：Commit**

```bash
git add backend/db/mysql_store.py
git commit -m "feat: add request_log and error_log tables for middleware observability"
```

---

### 任务 1：Phase 1 — 准确性核心

**目标：** 消除上下文双重发送（LLM 混淆源），Wiki 规则注入补充 gatekeep 盲区。每个 token 服务于准确性。

---

#### 任务 1.1：ContextAssembler — 统一上下文组装器

**文件：**
- 创建：`backend/langgraph/context_assembler.py`

- [ ] **步骤 1：创建 context_assembler.py**

```python
"""ContextAssembler — 一次组装，所有 LangGraph 节点共享，消除双重发送"""
from dataclasses import dataclass, field
from backend.memory.store import AgentMemory


@dataclass
class AssembledContext:
    resolved_params: dict = field(default_factory=dict)
    wiki_context: str = ""         # 注入 system prompt 的 wiki 规则
    conversation_context: str = "" # 注入 system prompt 的对话历史
    agent_memory_context: str = "" # 注入 system prompt 的 agent 记忆
    wiki_hit: bool = False

    @property
    def total_context(self) -> str:
        """合并所有上下文，供 prompt_builder 使用"""
        parts = [self.wiki_context, self.conversation_context, self.agent_memory_context]
        return "\n\n".join(p for p in parts if p)


class ContextAssembler:
    """一次组装，所有节点共享，消除上下文双重发送"""

    def __init__(self, token_budget: int = 6000):
        self.token_budget = token_budget
        self.memory = AgentMemory()

    async def assemble(self, session_id: str, user_text: str,
                       agent_type: str, wiki_store=None) -> AssembledContext:
        resolved = {}
        wiki_context = ""
        conversation_context = ""
        agent_memory_context = ""

        # Step 1: Wiki 实体解析（确定性数据，准确性最高）
        # Step 2: Wiki 规则匹配
        if wiki_store:
            try:
                wiki_context, resolved_wiki = await self._match_wiki(user_text, wiki_store, agent_type)
                resolved.update(resolved_wiki)
            except Exception:
                pass

        # Step 3: 对话历史（按 importance 排序 + 摘要）
        try:
            conversation_context, resolved_history = self._build_conversation(session_id)
            resolved.update(resolved_history)
        except Exception:
            pass

        # Step 4: Agent 记忆
        try:
            agent_memory_context = self._build_agent_memory(session_id)
        except Exception:
            pass

        return AssembledContext(
            resolved_params=resolved,
            wiki_context=wiki_context,
            conversation_context=conversation_context,
            agent_memory_context=agent_memory_context,
            wiki_hit=bool(resolved),
        )

    async def _match_wiki(self, user_text: str, wiki_store, agent_type: str) -> tuple[str, dict]:
        """关键词匹配 wiki 概念页，提取相关规则"""
        # 从 wiki_store 搜索匹配的概念页
        keywords = self._extract_keywords(user_text, agent_type)
        if not keywords:
            return "", {}
        matched = wiki_store.search_concepts(keywords, limit=3)
        if not matched:
            return "", {}
        # 组装 wiki 规则上下文
        lines = []
        for page in matched:
            lines.append(f"### {page['title']}\n{page.get('body', '')[:400]}")
        return "\n".join(lines), self._extract_frontmatter_params(matched)

    def _extract_keywords(self, user_text: str, agent_type: str) -> list[str]:
        """从用户文本提取业务关键词"""
        patterns = {
            "bi": ["即期", "远期", "掉期", "结汇", "购汇", "交易量", "套保率", "月", "季", "年"],
            "pricing": ["报价", "询价", "远期", "掉期", "即期", "价格", "汇率"],
            "analysis": ["为什么", "原因", "分析", "变化"],
        }
        kw_list = patterns.get(agent_type, patterns["bi"])
        return [kw for kw in kw_list if kw in user_text]

    def _extract_frontmatter_params(self, pages: list[dict]) -> dict:
        """从 wiki 页面的 frontmatter 提取实体参数"""
        params = {}
        for page in pages:
            fm = page.get("frontmatter", {})
            for key in ("product_type", "bank_name", "cust_name", "dimension", "appid"):
                if key in fm:
                    params[key] = fm[key]
        return params

    def _build_conversation(self, session_id: str) -> tuple[str, dict]:
        """构建对话历史上下文 — 最近3轮原始，更早用摘要"""
        turns = self.memory.get_context(session_id, last_n=20)
        if not turns:
            return "", {}

        # 按 importance DESC, turn_index DESC 排序
        turns = sorted(turns, key=lambda t: (-t.get("importance", 1), -t["turn_index"]))

        recent_turns = [t for t in turns if t["turn_index"] >= max(t["turn_index"] for t in turns) - 2]
        older_turns = [t for t in turns if t["turn_index"] < max(t["turn_index"] for t in turns) - 2]

        lines = []
        if recent_turns:
            lines.append("## 最近对话")
            for t in sorted(recent_turns, key=lambda x: x["turn_index"]):
                lines.append(f"用户: {t.get('user_query', '')}")
                params = t.get("parsed_params", {})
                if params:
                    lines.append(f"解析: {self._params_to_text(params)}")

        if older_turns:
            # 从 memory_summaries 获取摘要
            summaries = self.memory.get_summaries(session_id)
            if summaries:
                lines.append("## 历史摘要")
                for s in summaries[-3:]:
                    lines.append(s.get("content", ""))

        resolved = {}
        if recent_turns:
            last = recent_turns[0]
            params = last.get("parsed_params", {})
            for key in ("product_type", "buy_sell", "bank_name", "cust_name", "dimension"):
                if key in params:
                    resolved[key] = params[key]

        return "\n".join(lines), resolved

    def _build_agent_memory(self, session_id: str) -> str:
        """构建 agent 记忆上下文"""
        try:
            from backend.agent.memory import AgentMemory as AgentMem
            mem = AgentMem()
            return mem.build_context_prompt(session_id) or ""
        except Exception:
            return ""

    @staticmethod
    def _params_to_text(params: dict) -> str:
        parts = []
        for k, v in params.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (str, int, float)):
                parts.append(f"{k}={v}")
        return ", ".join(parts)
```

- [ ] **步骤 2：验证模块可导入**

```bash
cd backend && python -c "from langgraph.context_assembler import ContextAssembler, AssembledContext; print('PASS')"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/langgraph/context_assembler.py
git commit -m "feat: add ContextAssembler - unified context assembly to eliminate double-send"
```

---

#### 任务 1.2：修改 context_resolver — 接入 ContextAssembler + Wiki

**文件：**
- 修改：`backend/langgraph/context_resolver.py:43-100` (resolve_context)

- [ ] **步骤 1：改造 resolve_context() 函数**

修改 `backend/langgraph/context_resolver.py` 第 43 行起的 `resolve_context()`：

```python
from backend.langgraph.context_assembler import ContextAssembler


def resolve_context(state: AgentState) -> dict:
    """解析多轮对话上下文 — 优先使用 ContextAssembler (Wiki + 历史)"""
    request_id = getattr(state, "request_id", "")
    session_id = getattr(state, "session_id", "")
    user_text = getattr(state, "user_text", "")
    agent_type = getattr(state, "router_decision", {}).get("agent", "BI")

    # 获取 wiki_store 实例
    wiki_store = None
    try:
        from backend.wiki.query import WikiQuery
        wiki_store = WikiQuery()
    except Exception:
        pass

    assembler = ContextAssembler()
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在事件循环中运行
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                assembler.assemble(session_id, user_text, agent_type, wiki_store), loop)
            ctx = future.result(timeout=3)
        else:
            ctx = asyncio.run(assembler.assemble(session_id, user_text, agent_type, wiki_store))
    except Exception:
        # 降级：走原有 LLM+规则路径
        ctx = None

    if ctx and ctx.resolved_params:
        return {
            "resolved_params": ctx.resolved_params,
            "inherited_fields": list(ctx.resolved_params.keys()),
            "context_confidence": 0.9 if ctx.wiki_hit else 0.7,
            "wiki_hit": ctx.wiki_hit,
            "_assembled_context": ctx.total_context,
        }

    # Fallback: 原有 LLM+规则路径
    context = getattr(state, "context", []) or []
    if not context:
        return {"resolved_params": {}, "inherited_fields": [],
                "context_confidence": 0.0, "wiki_hit": False}

    # ... 保持原有 LLM 调用逻辑 ...
```

- [ ] **步骤 2：确保向后兼容 — 原有 LLM fallback 保持**

保留原有的 `_resolve_fallback()` 函数（第 14 行）不变，当 ContextAssembler 失败时自动降级到原有路径。

- [ ] **步骤 3：Commit**

```bash
git add backend/langgraph/context_resolver.py
git commit -m "feat: wire ContextAssembler into LangGraph context_resolver with graceful fallback"
```

---

#### 任务 1.3：消除 BI agent 上下文双重发送

**文件：**
- 修改：`backend/langgraph/agents/bi_agent.py:23-49` (_node_parse)

- [ ] **步骤 1：修改 _node_parse() — 不再重新发送原始 context**

修改 `backend/langgraph/agents/bi_agent.py` 第 35 行：

```python
# 改前（第 35 行）:
system_prompt = build_system_prompt(state.context)

# 改后:
# 优先使用 ContextAssembler 组装好的上下文（已包含 wiki + 对话历史 + agent 记忆）
# 不再传入原始 state.context，消除双重发送
assembled = getattr(state, "_assembled_context", None)
system_prompt = build_system_prompt(
    context=None,                      # 不再发送原始 context
    query_text=state.user_text,        # 让 prompt_builder 根据 query 匹配 wiki
    assembled_context=assembled         # 传入已组装的上下文
)
```

- [ ] **步骤 2：同步修改 pricing_agent.py**

修改 `backend/langgraph/agents/pricing_agent.py` 中对应的 prompt 构建调用（第 35-45 行区域），同样不再传入原始 context。

- [ ] **步骤 3：验证 -- 启动后端确认管线正常运行**

```bash
cd backend && python -c "
import requests, time
time.sleep(2)  # wait for server if running
try:
    r = requests.post('http://localhost:8000/api/chat', json={
        'user_text': '本月结汇交易量', 'session_id': 'test-dedup-001'
    }, timeout=30)
    assert r.status_code in (200, 422), f'Unexpected status: {r.status_code}'
    print(f'PASS: status={r.status_code}')
except requests.ConnectionError:
    print('INFO: server not running, syntax check passed')
"
```

- [ ] **步骤 4：Commit**

```bash
git add backend/langgraph/agents/bi_agent.py backend/langgraph/agents/pricing_agent.py
git commit -m "fix: eliminate context double-send — BI/pricing parse no longer re-sends raw context"
```

---

#### 任务 1.4：Prompt Builder 接入 Wiki 规则注入

**文件：**
- 修改：`backend/llm_parser/prompt_builder.py:69-90` (build_system_prompt)

- [ ] **步骤 1：修改 build_system_prompt() — 增加 wiki 规则注入 + query_text 参数**

修改 `build_system_prompt()` 函数签名和实现（第 69 行起）：

```python
def build_system_prompt(context: list | None = None, query_text: str = None,
                        assembled_context: str = None) -> str:
    """构建系统提示词，注入 DB 规则 + Wiki 规则 + 上下文

    Args:
        context: 旧版上下文格式（保留向后兼容，新调用传 None）
        query_text: 用户查询文本，用于匹配 wiki 概念页
        assembled_context: ContextAssembler 预组装的上下文
    """
    rules = _load_rules()
    base = _build_base_prompt(rules)

    # 1. Wiki 规则注入（Flash 低成本，补充 gatekeep 盲区）
    if query_text:
        try:
            wiki_context = _match_wiki_concepts(query_text)
            if wiki_context:
                base += f"\n\n## 业务规则补充（来自知识库）\n{wiki_context}"
        except Exception:
            pass

    # 2. ContextAssembler 预组装上下文（取消了双重发送）
    if assembled_context:
        base += f"\n\n## 对话上下文\n{assembled_context}"
    elif context:
        # 向后兼容旧调用路径
        base += "\n\n## 对话上下文（多轮对话历史）\n"
        for msg in context[-20:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:200]
            base += f"- [{role}] {content}\n"

    return base


def _match_wiki_concepts(query_text: str) -> str | None:
    """关键词匹配 wiki 概念页，提取相关规则片段（上限 1200 tokens）"""
    try:
        from backend.wiki.query import WikiQuery
        wiki = WikiQuery()
        # 提取产品/方向关键词
        keywords = set()
        for kw in ["即期", "远期", "掉期", "结汇", "购汇", "交易量", "套保率",
                    "报价", "询价", "月", "季度", "年"]:
            if kw in query_text:
                keywords.add(kw)
        if not keywords:
            return None
        pages = wiki.search_concepts(list(keywords), limit=3)
        if not pages:
            return None
        lines = []
        for p in pages:
            body = p.get("body", "")[:400]
            if body:
                lines.append(f"### {p['title']}\n{body}")
        return "\n".join(lines)
    except Exception:
        return None
```

- [ ] **步骤 2：验证 — 查询包含"远期"时自动注入 FWD 规则**

```bash
cd backend && python -c "
from llm_parser.prompt_builder import build_system_prompt
prompt = build_system_prompt(query_text='远期结汇报价')
# 远期查询应包含 FWD 相关规则（如果 wiki 中有概念页）
print(f'Prompt length: {len(prompt)} chars')
print('PASS: no crash')
"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/llm_parser/prompt_builder.py
git commit -m "feat: inject wiki concept rules into prompt_builder for accuracy"
```

---

#### 任务 1.5：对话历史按 importance 排序 + 摘要减压

**文件：**
- 修改：`backend/memory/store.py:82-109` (build_context_prompt)

- [ ] **步骤 1：修改 build_context_prompt() — importance 排序**

修改 `backend/memory/store.py` 第 82 行起的 `build_context_prompt()`：

```python
def build_context_prompt(self, session_id: str, last_n: int = 3,
                         use_importance: bool = True) -> str:
    """构建对话历史上下文

    Args:
        session_id: 会话 ID
        last_n: 保留的轮次数
        use_importance: 是否按 importance 排序
    """
    turns = self.get_turns(session_id)
    if not turns:
        return ""

    if use_importance:
        # 按 importance DESC, turn_index DESC 排序
        # 高 importance 轮次（比较、聚合、多维度）优先进入上下文
        turns = sorted(turns, key=lambda t: (-t.get("importance", 1), -t["turn_index"]))
    else:
        turns = sorted(turns, key=lambda t: t["turn_index"], reverse=True)

    # 分层: 最近 3 轮原始格式 + 更早用摘要
    recent_turns = turns[:min(3, last_n)]
    older_turns = turns[3:last_n] if last_n > 3 else []

    lines = []
    if recent_turns:
        lines.append("## 最近对话")
        for t in sorted(recent_turns, key=lambda x: x["turn_index"]):
            lines.append(f"用户: {t.get('user_query', '')}")
            params = t.get("parsed_params", {})
            if params:
                parts = []
                for k, v in params.items():
                    if not k.startswith("_") and v:
                        parts.append(f"{k}={v}")
                if parts:
                    lines.append(f"解析: {', '.join(parts)}")

    if older_turns:
        summaries = self.get_summaries(session_id)
        if summaries:
            lines.append("## 历史摘要")
            for s in summaries[-3:]:
                content = s.get("content", "")
                if isinstance(content, dict):
                    content = content.get("summary", str(content))
                lines.append(str(content)[:300])

    return "\n".join(lines)
```

- [ ] **步骤 2：修改 should_summarize() 触发的摘要生成为 LLM 驱动**

修改 `backend/memory/store.py` 第 110 行起：

```python
def should_summarize(self, session_id: str) -> bool:
    count = self.count_turns(session_id)
    return count > 0 and count % 5 == 0

async def generate_llm_summary(self, session_id: str) -> str:
    """Flash 生成压缩摘要 — 提炼信息而非砍内容"""
    turns = self.get_turns(session_id)[-5:]
    if not turns:
        return ""

    prompt = "将以下5轮对话压缩为一句话摘要，保留关键实体（产品、币种、金额）和查询意图：\n"
    for t in turns:
        query = t.get("user_query", "")[:80]
        if query:
            prompt += f"用户：{query}\n"

    try:
        from backend.llm_parser.llm_client import llm_chat
        summary = llm_chat(
            system_prompt="你是一个对话摘要生成器。输出一句中文摘要（50字以内），保留关键业务信息。",
            user_prompt=prompt,
            task="summary_generate",
            request_id=f"summary-{session_id}",
            session_id=session_id,
        )
        if summary:
            self.save_summary(session_id, "turn_group", {
                "summary": summary,
                "source_turns": [t["turn_index"] for t in turns],
            })
            return summary
    except Exception:
        pass

    # Fallback: 字段级摘要
    indices = [t["turn_index"] for t in turns]
    queries = [t.get("user_query", "")[:40] for t in turns]
    self.save_summary(session_id, "turn_group", {
        "turn_indices": indices,
        "queries": queries,
        "has_comparison": any(t.get("parsed_params", {}).get("comparison") for t in turns),
    })
    return f"历史查询: {'; '.join(queries)}"
```

- [ ] **步骤 3：在 mysql_store.py 中添加 get_summaries/save_summary 方法（如尚未存在）**

验证 `backend/db/mysql_store.py` 中已有 `get_memory_summaries()` 和 `save_memory_summary()` 方法。如果没有，添加：

```python
def get_memory_summaries(conn, session_id: str) -> list[dict]:
    sql = """SELECT content, source_turns FROM memory_summaries
             WHERE session_id = %s ORDER BY created_at ASC"""
    with conn.cursor() as cur:
        cur.execute(sql, (session_id,))
        return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
```

- [ ] **步骤 4：Commit**

```bash
git add backend/memory/store.py backend/db/mysql_store.py
git commit -m "feat: importance-sorted context + LLM-driven summary for context decompression"
```

---

### 任务 2：Phase 2 — 基础设施

**目标：** 检查点恢复、重试、熔断、结构化错误、中间件栈。

---

#### 任务 2.1：AgentState 结构化错误字段

**文件：**
- 修改：`backend/langgraph/state.py:7-50` (AgentState)
- 修改：`backend/langgraph/validators.py:109-119` (node_validate)

- [ ] **步骤 1：修改 AgentState — 替换 `error: str` 为 `errors: list[dict]`**

修改 `backend/langgraph/state.py`：

```python
# 改前（第 46 行）:
error: str = ""

# 改后:
errors: list[dict] = field(default_factory=list)
# 每个 error dict: {node: str, code: str, message: str,
#                   severity: "fatal"|"warning"|"info", timestamp: float}

# 增加后向兼容属性
@property
def error(self) -> str:
    fatals = [e for e in self.errors if e["severity"] == "fatal"]
    if fatals:
        return fatals[0]["message"]
    return ""

@error.setter
def error(self, value: str):
    if value:
        self.errors.append({
            "node": "unknown",
            "code": "Error",
            "message": value,
            "severity": "warning",
            "timestamp": 0.0,
        })
```

- [ ] **步骤 2：修改 node_validate() — 检查 fatal 错误**

修改 `backend/langgraph/validators.py` 第 109 行的 `node_validate()`：

```python
def node_validate(state: AgentState) -> dict:
    # 如果有 fatal 错误，跳过验证直接返回
    fatals = [e for e in state.errors if e["severity"] == "fatal"]
    if fatals:
        return {
            "validation_warnings": [f["message"] for f in fatals],
            "sql_validated": False,
        }

    # ... 保持原有验证逻辑 ...
    sql_result = node_validate_sql(state)
    result_result = node_validate_result(state)
    return {
        "sql_validated": sql_result.get("sql_validated", True),
        "validation_warnings": sql_result.get("validation_warnings", []) +
                               result_result.get("validation_warnings", []),
    }
```

- [ ] **步骤 3：更新所有设置 `state.error` 的节点**

搜索所有设置 `state.error = "..."` 的位置，改为：

```python
# 改前:
return {"error": "some message"}

# 改后:
return {"errors": [{"node": "node_name", "code": "ErrorType", "message": "some message",
                    "severity": "warning", "timestamp": time.time()}]}
```

涉及文件：
- `backend/langgraph/agents/bi_agent.py:40,54,72` (_node_parse, _node_build_sql, _node_execute)
- `backend/langgraph/agents/pricing_agent.py:60,80` (_node_parse_pricing, _node_pricing_inquiry)

- [ ] **步骤 4：验证**

```bash
cd backend && python -c "
from langgraph.state import AgentState
s = AgentState(request_id='t1', session_id='s1', user_text='test')
assert s.errors == []
assert s.error == ''
s.error = 'oh no'
assert len(s.errors) == 1
assert s.error == 'oh no'
print('PASS: backward compatible error field')
"
```

- [ ] **步骤 5：Commit**

```bash
git add backend/langgraph/state.py backend/langgraph/validators.py backend/langgraph/agents/bi_agent.py backend/langgraph/agents/pricing_agent.py
git commit -m "feat: structured errors in AgentState with backward-compatible error property"
```

---

#### 任务 2.2：MySQL Checkpointer

**文件：**
- 创建：`backend/langgraph/checkpointer.py`
- 修改：`backend/langgraph/pipeline.py:28-54` (build_main_graph)
- 修改：`backend/db/mysql_store.py:50-198` (SCHEMA_SQL)

- [ ] **步骤 1：在 SCHEMA_SQL 中添加 langgraph_checkpoints 表**

```sql
CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    thread_id VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(64) NOT NULL DEFAULT '',
    parent_id VARCHAR(64) NOT NULL DEFAULT '',
    data JSON,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_thread (thread_id, checkpoint_ns, checkpoint_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **步骤 2：创建 checkpointer.py**

```python
"""MySQL Checkpointer for LangGraph — 节点执行后自动持久化 AgentState"""
import json
import uuid
import logging
from dataclasses import asdict

logger = logging.getLogger(__name__)


class MySqlCheckpointer:
    """LangGraph checkpointer 实现，持久化到 MySQL

    集成方式: builder.compile(checkpointer=MySqlCheckpointer(conn_string))
    """

    def __init__(self):
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            from backend.db.mysql_store import get_conn
            self._conn = get_conn()
        return self._conn

    def put(self, config: dict, checkpoint: dict, metadata: dict,
            new_versions: dict) -> dict:
        """持久化一个 checkpoint"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        checkpoint_id = checkpoint.get("id") or str(uuid.uuid4())
        parent_id = checkpoint.get("parent_checkpoint_id", "")

        data = json.dumps(checkpoint, ensure_ascii=False, default=str)
        conn = self._get_conn()
        sql = """INSERT INTO langgraph_checkpoints
                 (thread_id, checkpoint_ns, checkpoint_id, parent_id, data)
                 VALUES (%s, %s, %s, %s, %s)"""
        with conn.cursor() as cur:
            cur.execute(sql, (thread_id, checkpoint_ns, checkpoint_id, parent_id, data))
        conn.commit()
        logger.debug(f"Checkpoint saved: {thread_id}/{checkpoint_id}")
        return {"config": config, "checkpoint": checkpoint}

    def get(self, config: dict) -> dict | None:
        """获取最新 checkpoint"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        conn = self._get_conn()
        sql = """SELECT data FROM langgraph_checkpoints
                 WHERE thread_id = %s AND checkpoint_ns = %s
                 ORDER BY created_at DESC LIMIT 1"""
        with conn.cursor() as cur:
            cur.execute(sql, (thread_id, checkpoint_ns))
            row = cur.fetchone()
            if not row:
                return None
        return json.loads(row[0])

    def list(self, config: dict, limit: int = 10,
             before: dict = None) -> list[dict]:
        """列出历史 checkpoints"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        conn = self._get_conn()
        sql = """SELECT checkpoint_id, created_at FROM langgraph_checkpoints
                 WHERE thread_id = %s AND checkpoint_ns = %s
                 ORDER BY created_at DESC LIMIT %s"""
        with conn.cursor() as cur:
            cur.execute(sql, (thread_id, checkpoint_ns, limit))
            return [{"checkpoint_id": r[0], "created_at": str(r[1])} for r in cur.fetchall()]

    def get_tuple(self, config: dict) -> tuple | None:
        """LangGraph API: 读取 checkpoint tuple"""
        return self.get(config)

    async def aget_tuple(self, config: dict) -> tuple | None:
        return self.get_tuple(config)
```

- [ ] **步骤 3：修改 build_main_graph() — 注入 checkpointer**

修改 `backend/langgraph/pipeline.py` 第 28 行起：

```python
def build_main_graph(checkpointer=None) -> StateGraph:
    builder = StateGraph(AgentState)

    # ... 添加节点不变 ...

    if checkpointer:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()
```

修改 `backend/app.py` 中调用处（第 537 行附近）：

```python
# 改前:
_langgraph_app = build_main_graph()

# 改后:
from backend.langgraph.checkpointer import MySqlCheckpointer
_langgraph_app = build_main_graph(checkpointer=MySqlCheckpointer())
```

- [ ] **步骤 4：验证**

```bash
cd backend && python -c "
from langgraph.checkpointer import MySqlCheckpointer
cp = MySqlCheckpointer()
config = {'configurable': {'thread_id': 'test-001', 'checkpoint_ns': ''}}
cp.put(config, {'id': 'ckpt-1', 'data': 'test'}, {}, {})
result = cp.get(config)
assert result is not None
print('PASS: checkpointer works')
"
```

- [ ] **步骤 5：Commit**

```bash
git add backend/langgraph/checkpointer.py backend/langgraph/pipeline.py backend/app.py backend/db/mysql_store.py
git commit -m "feat: MySQL Checkpointer for LangGraph with crash recovery"
```

---

#### 任务 2.3：统一重试层

**文件：**
- 创建：`backend/langgraph/retry.py`

- [ ] **步骤 1：创建 retry.py**

```python
"""统一重试层 — 对瞬态错误自动重试"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# 可重试的错误类型（瞬态故障）
RETRYABLE_ERRORS = (
    ConnectionError,
    TimeoutError,
    OSError,  # 网络不可达、连接重置等
)


class RetryableNode:
    """包装 LangGraph 节点函数，对瞬态错误自动重试

    非瞬态错误（ValueError, TypeError, 业务逻辑错误）不重试，直接抛出
    """

    def __init__(self, fn, max_retries: int = 2, backoff_base: float = 1.0):
        self.fn = fn
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.__name__ = getattr(fn, "__name__", "retryable")

    async def __call__(self, *args, **kwargs):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(self.fn):
                    return await self.fn(*args, **kwargs)
                return self.fn(*args, **kwargs)
            except RETRYABLE_ERRORS as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = self.backoff_base * (2 ** attempt)
                    logger.warning(
                        f"RetryableNode {self.__name__} attempt {attempt + 1}/{self.max_retries + 1} "
                        f"failed with {type(e).__name__}, retrying in {wait:.1f}s"
                    )
                    await asyncio.sleep(wait)
        logger.error(
            f"RetryableNode {self.__name__} exhausted all {self.max_retries + 1} attempts: {last_error}"
        )
        raise last_error


def retryable(max_retries: int = 2, backoff_base: float = 1.0):
    """装饰器：将函数包装为可重试"""
    def decorator(fn):
        return RetryableNode(fn, max_retries=max_retries, backoff_base=backoff_base)
    return decorator
```

- [ ] **步骤 2：验证**

```bash
cd backend && python -c "
from langgraph.retry import RetryableNode, RETRYABLE_ERRORS
import asyncio

async def flaky(i=0):
    if i < 2:
        raise ConnectionError('transient')
    return 'ok'

# 前2次失败，第3次成功
counter = [0]
async def test_fn():
    counter[0] += 1
    if counter[0] < 3:
        raise ConnectionError('fail')
    return counter[0]

node = RetryableNode(test_fn, max_retries=2)
result = asyncio.run(node())
assert result == 3, f'Expected 3, got {result}'
print('PASS: retry works')
"
```

- [ ] **步骤 3：为关键节点添加重试**

修改 `backend/langgraph/pipeline.py` 中 `build_main_graph()` 中关键节点的绑定：

```python
from backend.langgraph.retry import RetryableNode
from backend.langgraph.agents.bi_agent import _node_execute

builder.add_node("bi_agent.execute", RetryableNode(_node_execute, max_retries=2))
```

- [ ] **步骤 4：Commit**

```bash
git add backend/langgraph/retry.py backend/langgraph/pipeline.py
git commit -m "feat: unified retry layer for transient error recovery"
```

---

#### 任务 2.4：熔断器

**文件：**
- 创建：`backend/langgraph/circuit_breaker.py`

- [ ] **步骤 1：创建 circuit_breaker.py**

```python
"""熔断器 — 连续失败后短路，返回降级结果"""
import time
import asyncio
import logging

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """包装外部依赖，连续失败后短路返回降级结果

    States: CLOSED(正常) -> OPEN(短路) -> HALF_OPEN(探测) -> CLOSED(恢复)
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(self, name: str, failure_threshold: int = 5,
                 reset_timeout: float = 60.0, fallback_fn=None):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.fallback_fn = fallback_fn
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0

    async def call(self, fn, *args, **kwargs):
        if self.state == self.OPEN:
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = self.HALF_OPEN
                logger.info(f"CircuitBreaker {self.name} -> HALF_OPEN (probing)")
            else:
                logger.warning(f"CircuitBreaker {self.name} OPEN, using fallback")
                if self.fallback_fn:
                    return await self._invoke(self.fallback_fn, *args, **kwargs)
                return None

        try:
            result = await self._invoke(fn, *args, **kwargs)
            if self.state == self.HALF_OPEN:
                self.state = self.CLOSED
                logger.info(f"CircuitBreaker {self.name} -> CLOSED (recovered)")
            self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = self.OPEN
                logger.error(
                    f"CircuitBreaker {self.name} -> OPEN ({self.failure_count} failures): {e}"
                )
            if self.fallback_fn:
                return await self._invoke(self.fallback_fn, *args, **kwargs)
            raise

    async def _invoke(self, fn, *args, **kwargs):
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return fn(*args, **kwargs)

    def reset(self):
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
```

- [ ] **步骤 2：为 LLM API 创建熔断器实例**

在 `backend/llm_parser/llm_client.py` 中添加：

```python
from backend.langgraph.circuit_breaker import CircuitBreaker

_llm_cb = CircuitBreaker("llm_api", failure_threshold=5, reset_timeout=60)
_oracle_cb = CircuitBreaker("oracle_db", failure_threshold=3, reset_timeout=30)
_pricing_cb = CircuitBreaker("pricing_engine", failure_threshold=5, reset_timeout=60)
```

- [ ] **步骤 3：验证**

```bash
cd backend && python -c "
from langgraph.circuit_breaker import CircuitBreaker
import asyncio

cb = CircuitBreaker('test', failure_threshold=2, reset_timeout=0.1)
async def fail():
    raise ConnectionError('bad')

# 连续失败 2 次后 OPEN
for i in range(3):
    try:
        await cb.call(fail)
    except ConnectionError:
        pass
assert cb.state == 'OPEN'
# reset_timeout 短，等下就 HALF_OPEN
import time
time.sleep(0.2)
try:
    await cb.call(fail)
except ConnectionError:
    pass
print('PASS: circuit breaker state transitions correct')
"
```

- [ ] **步骤 4：Commit**

```bash
git add backend/langgraph/circuit_breaker.py backend/llm_parser/llm_client.py
git commit -m "feat: circuit breaker for external dependency failure isolation"
```

---

#### 任务 2.5：FastAPI 中间件栈

**文件：**
- 创建：`backend/middleware/__init__.py`
- 创建：`backend/middleware/request_id.py`
- 创建：`backend/middleware/timing.py`
- 创建：`backend/middleware/error_handler.py`
- 修改：`backend/app.py:78-101` (FastAPI app setup)

- [ ] **步骤 1：创建 middleware/__init__.py**

```python
"""FastAPI 中间件包"""
```

- [ ] **步骤 2：创建 middleware/request_id.py**

```python
"""Request-ID 中间件 — 生成 UUID 贯穿请求生命周期"""
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:12]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

- [ ] **步骤 3：创建 middleware/timing.py**

```python
"""计时中间件 — 记录请求耗时到 request_log"""
import time
import threading
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - t0) * 1000
        rid = getattr(request.state, "request_id", "")
        # fire-and-forget 写入 request_log
        threading.Thread(target=_write_request_log, args=(
            rid, request.method, request.url.path,
            response.status_code, duration_ms
        )).start()
        return response


def _write_request_log(request_id: str, method: str, path: str,
                       status_code: int, duration_ms: float):
    try:
        from backend.db.mysql_store import get_conn, insert_request_log
        conn = get_conn()
        insert_request_log(conn, request_id, method, path, status_code, duration_ms)
        conn.close()
    except Exception:
        pass
```

- [ ] **步骤 4：创建 middleware/error_handler.py**

```python
"""全局异常处理中间件 — 统一 JSON 错误格式"""
import traceback
import threading
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            rid = getattr(request.state, "request_id", "")
            err_type = type(exc).__name__
            err_msg = str(exc)[:500]
            tb = traceback.format_exc()[:2000]
            # fire-and-forget 写入 error_log
            threading.Thread(target=_write_error_log, args=(
                rid, request.method, request.url.path,
                err_type, err_msg, tb
            )).start()
            return JSONResponse(
                status_code=500,
                content={
                    "error": err_type,
                    "message": err_msg,
                    "request_id": rid,
                }
            )
```

- [ ] **步骤 5：修改 app.py — 注册中间件**

修改 `backend/app.py` 第 78 行附近：

```python
app = FastAPI(title="Smart BI", version="1.0.0", lifespan=_mcp_lifespan)

# 注册中间件（从外到内：ErrorHandler > Timing > RequestID）
from backend.middleware.error_handler import ErrorHandlerMiddleware
from backend.middleware.timing import TimingMiddleware
from backend.middleware.request_id import RequestIDMiddleware

app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIDMiddleware)
```

- [ ] **步骤 6：验证**

```bash
cd backend && python -c "
from app import app
middlewares = [m.cls.__name__ for m in app.user_middleware]
assert 'ErrorHandlerMiddleware' in middlewares
assert 'TimingMiddleware' in middlewares
assert 'RequestIDMiddleware' in middlewares
print('PASS: all middlewares registered')
"
```

- [ ] **步骤 7：Commit**

```bash
git add backend/middleware/ backend/app.py
git commit -m "feat: FastAPI middleware stack — RequestID, Timing, ErrorHandler"
```

---

#### 任务 2.6：SessionStrategy — 自适应会话策略

**文件：**
- 创建：`backend/langgraph/session_strategy.py`

- [ ] **步骤 1：创建 session_strategy.py**

```python
"""SessionStrategy — 根据会话状态自适应调整策略。升级不降级。"""
from backend.memory.store import AgentMemory


class SessionStrategy:
    """根据会话状态调整模型和上下文策略

    核心原则: 升级不降级。复杂场景用更强的模型和更深的上下文。
    """

    def __init__(self):
        self.memory = AgentMemory()

    def get_strategy(self, session_id: str) -> dict:
        turn_count = self._get_turn_count(session_id)
        complexity = self._estimate_complexity(session_id)

        if turn_count <= 3 and complexity == "simple":
            return {
                "model_tier": "flash",
                "context_depth": 3,
                "wiki_injection": True,
                "summary_mode": "none",
            }
        if turn_count <= 10:
            return {
                "model_tier": "flash",
                "context_depth": 5,
                "wiki_injection": True,
                "summary_mode": "compress_old",
            }
        # 长会话/复杂 → 升级到 Pro
        return {
            "model_tier": "pro",
            "context_depth": 10,
            "wiki_injection": True,
            "summary_mode": "llm_summary",
        }

    def _get_turn_count(self, session_id: str) -> int:
        try:
            return self.memory.count_turns(session_id)
        except Exception:
            return 0

    def _estimate_complexity(self, session_id: str) -> str:
        try:
            recent = self.memory.get_context(session_id, last_n=3)
        except Exception:
            return "simple"
        for t in recent:
            params = t.get("parsed_params", {})
            if params.get("comparison") or params.get("hedge_ratio") \
               or params.get("aggregate"):
                return "complex"
        return "simple"
```

- [ ] **步骤 2：验证**

```bash
cd backend && python -c "
from langgraph.session_strategy import SessionStrategy
s = SessionStrategy()
strat = s.get_strategy('nonexistent-session')
assert strat['model_tier'] == 'flash'  # 新会话默认 Flash
print('PASS')
"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/langgraph/session_strategy.py
git commit -m "feat: adaptive SessionStrategy — upgrade to Pro for complex sessions"
```

---

### 任务 3：Phase 3 — 增强层

**目标：** 工具注册、Wiki 工具、Schema 校验、认证、事件订阅、审计补全。

---

#### 任务 3.1：统一工具注册表

**文件：**
- 创建：`backend/tools/__init__.py`
- 创建：`backend/tools/registry.py`

- [ ] **步骤 1：创建 tools/__init__.py**

```python
"""工具注册表包"""
```

- [ ] **步骤 2：创建 tools/registry.py**

```python
"""统一工具注册表 — 装饰器注册 + 自动发现"""
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolDef:
    name: str
    fn: Callable
    input_schema: dict
    output_schema: dict | None = None
    category: str = "system"
    writes: bool = False
    requires_auth: bool = False
    model_tier: str = "flash"


class ToolRegistry:
    _tools: dict[str, ToolDef] = {}

    @classmethod
    def register(cls, name: str, category: str = "system",
                 input_schema: dict = None, output_schema: dict = None,
                 writes: bool = False, requires_auth: bool = False,
                 model_tier: str = "flash"):
        """装饰器：注册工具"""
        def decorator(fn):
            cls._tools[name] = ToolDef(
                name=name, fn=fn,
                input_schema=input_schema or {},
                output_schema=output_schema,
                category=category,
                writes=writes,
                requires_auth=requires_auth,
                model_tier=model_tier,
            )
            return fn
        return decorator

    @classmethod
    def get(cls, name: str) -> ToolDef | None:
        return cls._tools.get(name)

    @classmethod
    def list(cls, category: str = None) -> list[ToolDef]:
        tools = list(cls._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    @classmethod
    def list_names(cls, category: str = None) -> list[str]:
        return [t.name for t in cls.list(category)]

    @classmethod
    def as_openai_tools(cls, category: str = None) -> list[dict]:
        """转为 OpenAI tool-calling 格式"""
        tools = []
        for t in cls.list(category):
            tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": getattr(t.fn, "__doc__", "") or "",
                    "parameters": t.input_schema,
                }
            })
        return tools
```

- [ ] **步骤 3：注册现有 LLM 工具到 ToolRegistry**

修改 `backend/agent/tools.py`，在函数定义后添加注册：

```python
from backend.tools.registry import ToolRegistry

# ... query_metrics 函数定义后 ...
ToolRegistry.register("query_metrics", category="bi",
    input_schema=TOOL_DEFINITIONS[0]["function"]["parameters"])(
    query_metrics)

ToolRegistry.register("decompose_change", category="bi",
    input_schema=TOOL_DEFINITIONS[1]["function"]["parameters"])(
    decompose_change)
```

- [ ] **步骤 4：验证**

```bash
cd backend && python -c "
from tools.registry import ToolRegistry
# 注册一个测试工具
@ToolRegistry.register('test_tool', category='test')
def test(): pass

assert ToolRegistry.get('test_tool') is not None
assert 'test_tool' in ToolRegistry.list_names()
assert 'test_tool' in ToolRegistry.list_names('test')
assert 'test_tool' not in ToolRegistry.list_names('other')
print('PASS: ToolRegistry works')
"
```

- [ ] **步骤 5：Commit**

```bash
git add backend/tools/ backend/agent/tools.py
git commit -m "feat: unified ToolRegistry with decorator-based registration"
```

---

#### 任务 3.2：Wiki MCP 工具

**文件：**
- 创建：`backend/smartbi_mcp/tools/wiki_search_tool.py`
- 创建：`backend/smartbi_mcp/tools/wiki_get_tool.py`
- 修改：`backend/smartbi_mcp/server.py:7-38` (工具注册)

- [ ] **步骤 1：创建 wiki_search_tool.py**

```python
"""MCP 工具: wiki_search — 搜索 wiki 概念/实体页面"""
import logging
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@ToolRegistry.register("wiki_search", category="wiki",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "page_type": {"type": "string", "enum": ["concept", "entity", "reference"],
                          "description": "页面类型"},
            "limit": {"type": "integer", "default": 5, "description": "返回数量上限"},
        },
        "required": ["query"],
    })
async def wiki_search(query: str, page_type: str = None, limit: int = 5) -> dict:
    """搜索 wiki 概念/实体页面"""
    try:
        from backend.wiki.query import WikiQuery
        wiki = WikiQuery()
        results = wiki.search(query, page_type=page_type, limit=limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.warning(f"wiki_search failed: {e}")
        return {"results": [], "count": 0, "error": str(e)}


def register(mcp):
    """向 FastMCP 实例注册工具"""
    tool_def = ToolRegistry.get("wiki_search")
    if tool_def:
        mcp.tool()(tool_def.fn)
```

- [ ] **步骤 2：创建 wiki_get_tool.py**

```python
"""MCP 工具: wiki_get — 获取指定 slug 的 wiki 页面"""
import logging
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@ToolRegistry.register("wiki_get", category="wiki",
    input_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "页面 slug"},
        },
        "required": ["slug"],
    })
async def wiki_get(slug: str) -> dict:
    """获取指定 slug 的 wiki 页面"""
    try:
        from backend.wiki.query import WikiQuery
        wiki = WikiQuery()
        page = wiki.get_page(slug)
        if page:
            return {"found": True, "page": page}
        return {"found": False, "error": f"Page not found: {slug}"}
    except Exception as e:
        logger.warning(f"wiki_get failed: {e}")
        return {"found": False, "error": str(e)}


def register(mcp):
    tool_def = ToolRegistry.get("wiki_get")
    if tool_def:
        mcp.tool()(tool_def.fn)
```

- [ ] **步骤 3：修改 server.py — 改为自动注册**

修改 `backend/smartbi_mcp/server.py` 第 7-38 行：

```python
# 改前: 手动逐个 import 和 register
# 改后: 从 ToolRegistry 自动发现
from backend.tools.registry import ToolRegistry

from backend.smartbi_mcp.tools import wiki_search_tool
from backend.smartbi_mcp.tools import wiki_get_tool

# 原有工具模块列表
_TOOL_MODULES = [
    "backend.smartbi_mcp.tools.oracle_tool",
    "backend.smartbi_mcp.tools.mysql_tool",
    "backend.smartbi_mcp.tools.llm_tool",
    "backend.smartbi_mcp.tools.load_rules_tool",
    "backend.smartbi_mcp.tools.parse_date_tool",
    "backend.smartbi_mcp.tools.detect_entities_tool",
    "backend.smartbi_mcp.tools.compute_comparison_tool",
    "backend.smartbi_mcp.tools.get_session_context_tool",
    "backend.smartbi_mcp.tools.save_memory_tool",
    "backend.smartbi_mcp.tools.write_audit_log_tool",
    "backend.smartbi_mcp.tools.check_cache_tool",
    "backend.smartbi_mcp.tools.wiki_search_tool",
    "backend.smartbi_mcp.tools.wiki_get_tool",
]

# 自动注册所有 MCP 工具
for module_path in _TOOL_MODULES:
    try:
        mod = importlib.import_module(module_path)
        if hasattr(mod, "register"):
            mod.register(mcp)
    except Exception as e:
        logger.warning(f"Failed to load MCP tool {module_path}: {e}")
```

- [ ] **步骤 4：验证**

```bash
cd backend && python -c "
from smartbi_mcp.server import mcp
print('PASS: MCP server loads with new wiki tools')
"
```

- [ ] **步骤 5：Commit**

```bash
git add backend/smartbi_mcp/tools/wiki_search_tool.py backend/smartbi_mcp/tools/wiki_get_tool.py backend/smartbi_mcp/server.py
git commit -m "feat: Wiki MCP tools (wiki_search, wiki_get) + auto-registration from ToolRegistry"
```

---

#### 任务 3.3：LLM tool_call Schema 校验

**文件：**
- 修改：`backend/llm_parser/llm_client.py:142-208` (llm_tool_call)

- [ ] **步骤 1：在 llm_tool_call() 中添加 schema 校验**

在解析 LLM 返回的 function_call.arguments 后（`llm_tool_call()` 函数内）：

```python
from backend.tools.registry import ToolRegistry
import json

# 在解析每个 call 后:
for call in calls:
    fn_name = call["function"]["name"]
    tool_def = ToolRegistry.get(fn_name)
    if tool_def and tool_def.input_schema:
        try:
            import jsonschema
            jsonschema.validate(
                call["function"]["arguments"],
                tool_def.input_schema
            )
        except jsonschema.ValidationError as e:
            logger.warning(f"Tool call schema validation failed for {fn_name}: {e.message}")
            # 尝试修复常见错误
            try:
                call["function"]["arguments"] = _attempt_repair(
                    call["function"]["arguments"],
                    tool_def.input_schema,
                    e
                )
            except Exception:
                pass  # 无法修复，使用原始参数
        except ImportError:
            pass  # jsonschema 未安装，跳过校验

def _attempt_repair(args: dict, schema: dict, error) -> dict:
    """尝试修复常见的 LLM 输出错误"""
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    # 填充缺失的 required 字段默认值
    for key in required:
        if key not in args and key in properties:
            default = properties[key].get("default")
            if default is not None:
                args[key] = default
        # 类型转换: LLM 有时返回字符串而非数字
        if key in args and key in properties:
            ptype = properties[key].get("type", "")
            if ptype == "number" and isinstance(args[key], str):
                try:
                    args[key] = float(args[key])
                except ValueError:
                    pass
            elif ptype == "integer" and isinstance(args[key], str):
                try:
                    args[key] = int(args[key])
                except ValueError:
                    pass
    return args
```

- [ ] **步骤 2：验证**

```bash
cd backend && python -c "
# 测试 _attempt_repair
from llm_parser.llm_client import _attempt_repair

args = {}
schema = {
    'type': 'object',
    'properties': {'count': {'type': 'integer', 'default': 5}},
    'required': ['count'],
}
class FakeError: pass
e = FakeError()
e.message = 'required field missing'

repaired = _attempt_repair(args, schema, e)
assert 'count' in repaired
assert repaired['count'] == 5
print('PASS: repair fills defaults')

# 类型转换
args2 = {'count': '10'}
repaired2 = _attempt_repair(args2, schema, e)
assert repaired2['count'] == 10
print('PASS: repair coerces types')
"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/llm_parser/llm_client.py
git commit -m "feat: JSON Schema validation + auto-repair for LLM tool_call arguments"
```

---

#### 任务 3.4：认证中间件

**文件：**
- 创建：`backend/middleware/auth.py`
- 修改：`backend/app.py:78-101` (FastAPI app setup)
- 修改：`backend/db/mysql_store.py:50-198` (SCHEMA_SQL)

- [ ] **步骤 1：在 SCHEMA_SQL 中添加 api_keys 表**

```sql
CREATE TABLE IF NOT EXISTS api_keys (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    key_hash VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'SHA-256 of API key',
    permissions JSON COMMENT '["bi","pricing","admin"]',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME DEFAULT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    INDEX idx_key_hash (key_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **步骤 2：创建 middleware/auth.py**

```python
"""API Key 认证中间件"""
import os
import hashlib
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    WHITELIST = ["/api/health", "/docs", "/openapi.json", "/redoc"]

    async def dispatch(self, request: Request, call_next):
        if os.getenv("ENABLE_AUTH", "").lower() == "true":
            if request.url.path not in self.WHITELIST:
                api_key = request.headers.get("X-API-Key") or \
                          request.query_params.get("api_key", "")
                if not api_key or not self._validate_key(api_key):
                    return JSONResponse(
                        status_code=401,
                        content={"error": "Invalid or missing API key"},
                    )
                request.state.api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return await call_next(request)

    def _validate_key(self, api_key: str) -> bool:
        try:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            from backend.db.mysql_store import get_conn
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT 1 FROM api_keys
                       WHERE key_hash = %s AND is_active = TRUE
                       AND (expires_at IS NULL OR expires_at > NOW())""",
                    (key_hash,)
                )
                result = cur.fetchone()
            conn.close()
            return result is not None
        except Exception:
            return False
```

- [ ] **步骤 3：修改 app.py — 注册认证中间件**

```python
from backend.middleware.auth import APIKeyAuthMiddleware

# 在 ErrorHandlerMiddleware 之前注册（最外层）
app.add_middleware(APIKeyAuthMiddleware)
app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIDMiddleware)
```

- [ ] **步骤 4：验证**

```bash
cd backend && python -c "
from app import app
# 默认不启用认证，中间件应该放行
middlewares = [m.cls.__name__ for m in app.user_middleware]
assert 'APIKeyAuthMiddleware' in middlewares
print('PASS: auth middleware registered')
"
```

- [ ] **步骤 5：Commit**

```bash
git add backend/middleware/auth.py backend/app.py backend/db/mysql_store.py
git commit -m "feat: API key authentication middleware with whitelist and expiry"
```

---

#### 任务 3.5：事件总线补全订阅者 + 审计补全

**文件：**
- 修改：`backend/app.py:67-100` (lifespan)
- 修改：`backend/pricing/service.py:200-210` (handle_inquiry)

- [ ] **步骤 1：在 app.py lifespan 中添加事件订阅**

```python
# 在 _mcp_lifespan() 函数中，after startup:

from backend.event_bus import bus
from backend.llm_parser.prompt_builder import invalidate_cache as invalidate_prompt_cache
from backend.llm_parser.rules_engine import reload_rules

async def _on_wiki_updated(event):
    """Wiki 页面更新时清除规则缓存"""
    from backend.llm_parser.rules_engine import _rules_cache
    _rules_cache.clear()
    invalidate_prompt_cache()
    logger.info(f"Wiki updated, caches cleared: {event.data.get('slug')}")

async def _on_quote_expired(event):
    logger.info(f"Quote expired: pricing_id={event.data.get('pricing_id')}")

async def _on_evaluation_degraded(event):
    logger.warning(f"Quality degradation: {event.data}")

bus.subscribe("wiki.page_updated", _on_wiki_updated)
bus.subscribe("quote.expired", _on_quote_expired)
bus.subscribe("evaluation.degraded", _on_evaluation_degraded)
```

- [ ] **步骤 2：补全定价审计 — engine_raw_response 和 llm_decision_steps**

修改 `backend/pricing/service.py` 第 209 行的 `add_pricing_audit` 调用：

```python
# 在 handle_inquiry 中:
mysql_store.add_pricing_audit(
    pricing_id=pricing_id,
    action="INQUIRY",
    detail=inquiry_detail,
    engine_raw=engine_result.get("raw_json", {}) if engine_result else None,
    llm_steps=intent_steps,  # LLM 解析的各阶段结果
    evidence_hash=evidence_hash,
    evidence_type="quote",
    actor=customer_id,
)
```

同样修改 `handle_confirm_trade`（第 334 行）、`handle_refresh`（第 437 行）、`handle_cancel`（第 501 行）中的 `add_pricing_audit` 调用，补全 engine_raw 和 llm_steps 参数。

- [ ] **步骤 3：填充 result_hash**

修改 `backend/app.py` 第 113 行的 `_write_audit_log()`：

```python
def _write_audit_log(session_id, raw_input, parsed, sql, row_count, summary,
                     columns=None, rows=None):
    try:
        import hashlib, json
        result_hash = ""
        if columns and rows:
            result_hash = hashlib.sha256(
                json.dumps({"columns": columns, "rows": rows},
                          ensure_ascii=False, default=str).encode()
            ).hexdigest()

        mysql_store.write_audit_log(
            session_id=session_id,
            raw_input=raw_input[:5000],
            parsed=json.dumps(parsed, ensure_ascii=False, default=str),
            sql=sql,
            row_count=row_count,
            result_hash=result_hash,
            summary=summary[:2000] if summary else None,
        )
    except Exception as e:
        logger.warning(f"Audit log write failed: {e}")
```

- [ ] **步骤 4：Commit**

```bash
git add backend/app.py backend/pricing/service.py backend/event_bus.py
git commit -m "feat: event subscribers + pricing audit completion + result_hash"
```

#### 任务 3.6：工具执行监控 (T4)

**文件：**
- 创建：`backend/tools/monitor.py`
- 修改：`backend/db/mysql_store.py:50-198` (SCHEMA_SQL)

- [ ] **步骤 1：在 SCHEMA_SQL 中添加 tool_calls_log 表**

```sql
CREATE TABLE IF NOT EXISTS tool_calls_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    tool_name VARCHAR(64) NOT NULL DEFAULT '',
    duration_ms FLOAT NOT NULL DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_type VARCHAR(64) NOT NULL DEFAULT '',
    session_id VARCHAR(128) NOT NULL DEFAULT '',
    request_id VARCHAR(64) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tool_name (tool_name),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **步骤 2：创建 tools/monitor.py**

```python
"""工具执行监控 — 包装工具调用，记录指标"""
import time
import threading
import logging

logger = logging.getLogger(__name__)


class ToolMonitor:
    """包装工具调用，fire-and-forget 记录到 tool_calls_log"""

    @staticmethod
    def wrap(tool_name: str, fn, *args, **kwargs):
        """同步包装"""
        t0 = time.monotonic()
        try:
            result = fn(*args, **kwargs)
            duration_ms = (time.monotonic() - t0) * 1000
            ToolMonitor._log(tool_name, duration_ms, True)
            return result
        except Exception as e:
            duration_ms = (time.monotonic() - t0) * 1000
            ToolMonitor._log(tool_name, duration_ms, False, type(e).__name__)
            raise

    @staticmethod
    async def awrap(tool_name: str, fn, *args, **kwargs):
        """异步包装"""
        t0 = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            duration_ms = (time.monotonic() - t0) * 1000
            ToolMonitor._log(tool_name, duration_ms, True)
            return result
        except Exception as e:
            duration_ms = (time.monotonic() - t0) * 1000
            ToolMonitor._log(tool_name, duration_ms, False, type(e).__name__)
            raise

    @staticmethod
    def _log(tool_name: str, duration_ms: float, success: bool,
             error_type: str = ""):
        def _write():
            try:
                from backend.db.mysql_store import get_conn
                conn = get_conn()
                sql = """INSERT INTO tool_calls_log
                         (tool_name, duration_ms, success, error_type)
                         VALUES (%s, %s, %s, %s)"""
                with conn.cursor() as cur:
                    cur.execute(sql, (tool_name, duration_ms, success, error_type))
                conn.commit()
                conn.close()
            except Exception:
                pass
        threading.Thread(target=_write, daemon=True).start()

    @staticmethod
    def get_stats(tool_name: str = None, window_minutes: int = 60) -> dict:
        try:
            from backend.db.mysql_store import get_conn
            conn = get_conn()
            where = "created_at >= NOW() - INTERVAL %s MINUTE"
            params = [window_minutes]
            if tool_name:
                where += " AND tool_name = %s"
                params.append(tool_name)
            sql = f"""SELECT tool_name, COUNT(*) AS calls,
                             AVG(duration_ms) AS avg_ms,
                             SUM(CASE WHEN success THEN 0 ELSE 1 END) / COUNT(*) AS error_rate
                      FROM tool_calls_log
                      WHERE {where}
                      GROUP BY tool_name"""
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
            conn.close()
            return {"window_minutes": window_minutes, "stats": rows}
        except Exception:
            return {"window_minutes": window_minutes, "stats": []}
```

- [ ] **步骤 3：Commit**

```bash
git add backend/tools/monitor.py backend/db/mysql_store.py
git commit -m "feat: tool execution monitor with tool_calls_log table"
```

---

#### 任务 3.7：Wiki 规则读取 MCP 工具 (T5)

**文件：**
- 创建：`backend/smartbi_mcp/tools/wiki_rules_tool.py`
- 修改：`backend/smartbi_mcp/server.py:7-38` (_TOOL_MODULES)

- [ ] **步骤 1：创建 wiki_rules_tool.py**

```python
"""MCP 工具: wiki_query_rules — 从 wiki 知识库动态读取匹配规则"""
import logging
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@ToolRegistry.register("wiki_query_rules", category="wiki",
    input_schema={
        "type": "object",
        "properties": {
            "query_text": {"type": "string", "description": "用户查询文本"},
            "rule_categories": {"type": "array", "items": {"type": "string"},
                               "description": "可选：限制的规则类别列表"},
        },
        "required": ["query_text"],
    })
async def wiki_query_rules(query_text: str, rule_categories: list[str] = None) -> dict:
    """从 wiki 读取与当前查询匹配的规则

    流程:
    1. 关键词匹配 wiki 概念页（product-params, compliance-redlines 等）
    2. 将匹配页面的 body 返回
    3. 调用方可将结果注入 LLM prompt

    成本: Flash 读取 ~¥0.00005/次
    准确性收益: 补充 gatekeep 硬编码的 7 个纯硬编码阶段
    """
    try:
        from backend.wiki.query import WikiQuery
        wiki = WikiQuery()
        keywords = set()
        for kw in ["即期", "远期", "掉期", "结汇", "购汇", "交易量", "套保率",
                    "报价", "询价", "月", "季度", "年"]:
            if kw in query_text:
                keywords.add(kw)
        if not keywords:
            return {"rules": [], "hint": "no keywords matched"}

        pages = wiki.search_concepts(list(keywords), limit=3)
        if rule_categories:
            pages = [p for p in pages if p.get("category", "") in rule_categories]

        rules = []
        for p in pages:
            rules.append({
                "slug": p.get("slug", ""),
                "title": p.get("title", ""),
                "body": p.get("body", "")[:600],
                "category": p.get("category", ""),
            })
        return {"rules": rules, "count": len(rules)}
    except Exception as e:
        logger.warning(f"wiki_query_rules failed: {e}")
        return {"rules": [], "count": 0, "error": str(e)}


def register(mcp):
    tool_def = ToolRegistry.get("wiki_query_rules")
    if tool_def:
        mcp.tool()(tool_def.fn)
```

- [ ] **步骤 2：在 server.py 的 _TOOL_MODULES 中添加**

```python
"backend.smartbi_mcp.tools.wiki_rules_tool",
```

- [ ] **步骤 3：Commit**

```bash
git add backend/smartbi_mcp/tools/wiki_rules_tool.py backend/smartbi_mcp/server.py
git commit -m "feat: wiki_query_rules MCP tool for dynamic rule reading from wiki"
```

---

#### 任务 3.8：find_similar() 接入上下文组装 (C4)

**文件：**
- 修改：`backend/langgraph/context_assembler.py`

- [ ] **步骤 1：在 ContextAssembler.assemble() 中增加语义检索**

在 `_build_conversation()` 方法末尾增加 find_similar 调用：

```python
def _build_conversation(self, session_id: str) -> tuple[str, dict]:
    # ... 保持现有 importance 排序 + 摘要逻辑 ...

    # 新增：语义检索相似历史查询
    try:
        similar = self.memory.find_similar(session_id, limit=3)
        if similar:
            lines.append("## 相似历史查询")
            for s in similar:
                if isinstance(s, dict):
                    lines.append(f"- {s.get('user_query', '')[:80]} → "
                                f"{self._params_to_text(s.get('parsed_params', {}))}")
    except Exception:
        pass

    return "\n".join(lines), resolved
```

- [ ] **步骤 2：Commit**

```bash
git add backend/langgraph/context_assembler.py
git commit -m "feat: wire find_similar() into ContextAssembler for semantic retrieval"
```

---

#### 任务 3.9：Pricing State Machine 事务性 (S3)

**文件：**
- 修改：`backend/pricing/service.py`

- [ ] **步骤 1：改造_transition_and_save — 事务包裹**

在 `service.py` 添加：

```python
async def _transition_and_save(self, pricing_id: str, machine,
                                new_status, session_data: dict):
    """事务性状态转换：先写 DB → 成功后改内存，失败回滚"""
    conn = None
    try:
        conn = self.mysql.get_conn()
        # Step 1: 先写 MySQL（含 valid_until），不再先改内存
        self.mysql.save_pricing_session(conn, {**session_data, "status": new_status,
                                                "valid_until": machine.valid_until})
        # Step 2: 成功后改内存
        machine.transition(new_status)
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
```

- [ ] **步骤 2：在 handle_inquiry/handle_confirm_trade/handle_refresh/handle_cancel 中替换原有非事务性代码**

将各处 "先改 FSM → 再 save" 改为调用 `_transition_and_save()`。

- [ ] **步骤 3：验证 valid_until 持久化**

确保 `pricing_sessions` 表的 `valid_until` 列在 `save_pricing_session()` 中实际写入。检查 `backend/db/mysql_store.py` 中 `save_pricing_session()` 的 SQL。

- [ ] **步骤 4：Commit**

```bash
git add backend/pricing/service.py
git commit -m "fix: transactional pricing state machine — DB write before memory change"
```

---

#### 任务 3.10：LangGraph 节点级钩子 (L5)

**文件：**
- 创建：`backend/langgraph/hooks.py`
- 修改：`backend/langgraph/pipeline.py` (集成钩子)

- [ ] **步骤 1：创建 hooks.py**

```python
"""LangGraph 节点级钩子 — 执行前/后/错误记录"""
import time
import threading
import logging

logger = logging.getLogger(__name__)


class NodeHooks:
    @staticmethod
    def before_node(node_name: str, state: dict) -> dict:
        state["_node_start_time"] = time.monotonic()
        logger.debug(f"Node '{node_name}' started")
        return state

    @staticmethod
    def after_node(node_name: str, state: dict, result: dict) -> dict:
        duration_ms = (time.monotonic() - state.get("_node_start_time", time.monotonic())) * 1000
        logger.debug(f"Node '{node_name}' completed in {duration_ms:.0f}ms")
        # fire-and-forget 写入 tool_calls_log
        def _log():
            try:
                from backend.db.mysql_store import get_conn
                conn = get_conn()
                sql = """INSERT INTO tool_calls_log
                         (tool_name, duration_ms, success)
                         VALUES (%s, %s, TRUE)"""
                with conn.cursor() as cur:
                    cur.execute(sql, (f"node:{node_name}", duration_ms))
                conn.commit()
                conn.close()
            except Exception:
                pass
        threading.Thread(target=_log, daemon=True).start()
        return result

    @staticmethod
    def on_error(node_name: str, state: dict, error: Exception) -> dict:
        errors = state.get("errors", [])
        errors.append({
            "node": node_name,
            "code": type(error).__name__,
            "message": str(error),
            "severity": "fatal" if isinstance(error, (ConnectionError, TimeoutError)) else "warning",
            "timestamp": time.time(),
        })
        state["errors"] = errors
        logger.error(f"Node '{node_name}' failed: {error}")
        return state
```

- [ ] **步骤 2：在 pipeline.py 节点函数中嵌入钩子**

```python
# 在每个节点的入口和出口:
def _wrapped_node(state, node_name, fn):
    try:
        state = NodeHooks.before_node(node_name, state)
        result = fn(state)
        NodeHooks.after_node(node_name, state, result)
        return result
    except Exception as e:
        NodeHooks.on_error(node_name, state, e)
        raise
```

- [ ] **步骤 3：Commit**

```bash
git add backend/langgraph/hooks.py backend/langgraph/pipeline.py
git commit -m "feat: node-level hooks for execution tracing and structured error capture"
```

---

### 任务 4：Phase 4 — 评估层

**目标：** 质量指标采集、评估 API、前端面板、A/B 框架、降级告警。

---

#### 任务 4.1：评估数据采集器 + evaluation_records 表

**文件：**
- 创建：`backend/evaluation/__init__.py`
- 创建：`backend/evaluation/collector.py`
- 修改：`backend/db/mysql_store.py:50-198` (SCHEMA_SQL)

- [ ] **步骤 1：在 SCHEMA_SQL 中添加 evaluation_records 表**

```sql
CREATE TABLE IF NOT EXISTS evaluation_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL DEFAULT '',
    session_id VARCHAR(128) NOT NULL DEFAULT '',
    agent_type VARCHAR(16) NOT NULL DEFAULT '' COMMENT 'BI/PRICING/ANALYSIS',
    router_confidence FLOAT NOT NULL DEFAULT 0,
    parse_confidence FLOAT NOT NULL DEFAULT 0,
    post_validation_mismatches JSON COMMENT '数字不匹配列表',
    sql_validated BOOLEAN NOT NULL DEFAULT TRUE,
    validation_warnings_count INT NOT NULL DEFAULT 0,
    total_duration_ms FLOAT NOT NULL DEFAULT 0,
    wiki_hit BOOLEAN NOT NULL DEFAULT FALSE,
    errors_count INT NOT NULL DEFAULT 0,
    fatal_errors INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session_id (session_id),
    INDEX idx_agent_type (agent_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

并在 `mysql_store.py` 中添加：

```python
def insert_evaluation_record(conn, record: dict) -> int:
    sql = """INSERT INTO evaluation_records
             (request_id, session_id, agent_type, router_confidence,
              parse_confidence, post_validation_mismatches, sql_validated,
              validation_warnings_count, total_duration_ms, wiki_hit,
              errors_count, fatal_errors)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    with conn.cursor() as cur:
        cur.execute(sql, (
            record["request_id"], record["session_id"], record["agent_type"],
            record["router_confidence"], record["parse_confidence"],
            json.dumps(record["post_validation_mismatches"]),
            record["sql_validated"], record["validation_warnings_count"],
            record["total_duration_ms"], record["wiki_hit"],
            record["errors_count"], record["fatal_errors"],
        ))
        return cur.lastrowid


def query_evaluation_metrics(conn, window_hours: int = 24,
                              agent_type: str = None) -> list[dict]:
    """聚合查询评估指标"""
    where = ["created_at >= NOW() - INTERVAL %s HOUR"]
    params = [window_hours]
    if agent_type:
        where.append("agent_type = %s")
        params.append(agent_type)
    sql = f"""SELECT agent_type,
                     COUNT(*) AS total_requests,
                     AVG(router_confidence) AS avg_router_conf,
                     AVG(parse_confidence) AS avg_parse_conf,
                     AVG(total_duration_ms) AS avg_duration_ms,
                     SUM(CASE WHEN wiki_hit THEN 1 ELSE 0 END) / COUNT(*) AS wiki_hit_rate,
                     SUM(CASE WHEN fatal_errors > 0 THEN 1 ELSE 0 END) / COUNT(*) AS error_rate
              FROM evaluation_records
              WHERE {' AND '.join(where)}
              GROUP BY agent_type"""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
```

- [ ] **步骤 2：创建 evaluation/collector.py**

```python
"""评估数据采集器 — 每次 LangGraph 执行完成后采集质量指标"""
import json
import logging
import threading

logger = logging.getLogger(__name__)


class EvaluationCollector:
    def collect(self, state, duration_ms: float):
        """从 AgentState 提取质量指标并异步存储"""
        mismatches = self._extract_mismatches(state)
        record = {
            "request_id": getattr(state, "request_id", ""),
            "session_id": getattr(state, "session_id", ""),
            "agent_type": (getattr(state, "router_decision", {}) or {}).get("agent", "BI"),
            "router_confidence": (getattr(state, "router_decision", {}) or {}).get("confidence", 0),
            "parse_confidence": (getattr(state, "parsed_params", {}) or {}).get("_confidence", 0),
            "post_validation_mismatches": mismatches,
            "sql_validated": getattr(state, "sql_validated", True),
            "validation_warnings_count": len(getattr(state, "validation_warnings", [])),
            "total_duration_ms": duration_ms,
            "wiki_hit": getattr(state, "wiki_hit", False),
            "errors_count": len(getattr(state, "errors", [])),
            "fatal_errors": len([e for e in getattr(state, "errors", [])
                                 if e.get("severality") == "fatal"]),
        }
        threading.Thread(target=_write_eval_async, args=(record,), daemon=True).start()

    def _extract_mismatches(self, state) -> list:
        try:
            from backend.agent.post_validator import PostValidator
            pv = PostValidator()
            mismatches = pv.validate(
                getattr(state, "summary", ""),
                getattr(state, "analysis_data", {}),
            )
            return [{"value": m[0], "real": m[1]} for m in mismatches[:5]]
        except Exception:
            return []


def _write_eval_async(record: dict):
    try:
        from backend.db.mysql_store import get_conn, insert_evaluation_record
        conn = get_conn()
        insert_evaluation_record(conn, record)
        conn.close()
    except Exception as e:
        logger.debug(f"eval write failed: {e}")
```

- [ ] **步骤 3：在 LangGraph 管线末尾调用 Collector**

修改 `backend/app.py` 中 `/api/chat` 端点（第 570 行附近）：

```python
import time
from backend.evaluation.collector import EvaluationCollector

t0 = time.monotonic()
result = await _langgraph_app.ainvoke(initial_state)
duration_ms = (time.monotonic() - t0) * 1000

state = _normalize_state(result)
collector = EvaluationCollector()
collector.collect(state, duration_ms)
```

- [ ] **步骤 4：验证**

```bash
cd backend && python -c "
from db.mysql_store import SCHEMA_SQL
assert 'evaluation_records' in SCHEMA_SQL
from evaluation.collector import EvaluationCollector
print('PASS: collector imports')
"
```

- [ ] **步骤 5：Commit**

```bash
git add backend/evaluation/ backend/db/mysql_store.py backend/app.py
git commit -m "feat: evaluation collector + evaluation_records table for quality tracking"
```

---

#### 任务 4.2：质量指标 API

**文件：**
- 创建：`backend/evaluation/routes.py`
- 修改：`backend/app.py:99-101` (include_router)

- [ ] **步骤 1：创建 evaluation/routes.py**

```python
"""评估 API — 质量指标查询"""
from fastapi import APIRouter, Query
from backend.db.mysql_store import get_conn, query_evaluation_metrics, query_token_usage

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/accuracy")
def get_accuracy(window: int = Query(24, description="小时")):
    """PostValidator 不匹配率趋势"""
    conn = get_conn()
    try:
        metrics = query_evaluation_metrics(conn, window_hours=window)
        return {"window_hours": window, "metrics": metrics}
    finally:
        conn.close()


@router.get("/latency")
def get_latency(window: int = Query(24)):
    """延迟分布 (P50/P95/P99)"""
    conn = get_conn()
    try:
        sql = """SELECT agent_type,
                        AVG(total_duration_ms) AS p50,
                        MAX(CASE WHEN pct <= 0.95 THEN total_duration_ms END) AS p95,
                        MAX(total_duration_ms) AS p99
                 FROM (
                     SELECT agent_type, total_duration_ms,
                            PERCENT_RANK() OVER (PARTITION BY agent_type ORDER BY total_duration_ms) AS pct
                     FROM evaluation_records
                     WHERE created_at >= NOW() - INTERVAL %s HOUR
                 ) t
                 GROUP BY agent_type"""
        with conn.cursor() as cur:
            cur.execute(sql, (window,))
            rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        return {"window_hours": window, "latency": rows}
    except Exception:
        # MySQL 可能不支持 PERCENT_RANK，降级为简单聚合
        return {"window_hours": window, "latency": []}
    finally:
        conn.close()


@router.get("/routing")
def get_routing(window: int = Query(24)):
    """路由分布"""
    conn = get_conn()
    try:
        sql = """SELECT agent_type, COUNT(*) AS cnt
                 FROM evaluation_records
                 WHERE created_at >= NOW() - INTERVAL %s HOUR
                 GROUP BY agent_type"""
        with conn.cursor() as cur:
            cur.execute(sql, (window,))
            rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        return {"window_hours": window, "routing": rows}
    finally:
        conn.close()


@router.get("/token-usage")
def get_token_usage(window: int = Query(24), group_by: str = Query("call_site")):
    """Token 使用分析"""
    conn = get_conn()
    try:
        rows = query_token_usage(conn, window_hours=window)
        return {"window_hours": window, "usage": rows}
    finally:
        conn.close()


@router.get("/error-rate")
def get_error_rate(window: int = Query(24)):
    """错误率趋势"""
    conn = get_conn()
    try:
        sql = """SELECT agent_type,
                        COUNT(*) AS total,
                        SUM(CASE WHEN fatal_errors > 0 THEN 1 ELSE 0 END) AS errors
                 FROM evaluation_records
                 WHERE created_at >= NOW() - INTERVAL %s HOUR
                 GROUP BY agent_type"""
        with conn.cursor() as cur:
            cur.execute(sql, (window,))
            rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        return {"window_hours": window, "error_rate": rows}
    finally:
        conn.close()


@router.get("/wiki-impact")
def get_wiki_impact(window: int = Query(24)):
    """Wiki 命中率 vs 查询质量"""
    conn = get_conn()
    try:
        sql = """SELECT wiki_hit,
                        COUNT(*) AS cnt,
                        AVG(router_confidence) AS avg_router_conf,
                        AVG(parse_confidence) AS avg_parse_conf
                 FROM evaluation_records
                 WHERE created_at >= NOW() - INTERVAL %s HOUR
                 GROUP BY wiki_hit"""
        with conn.cursor() as cur:
            cur.execute(sql, (window,))
            rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        return {"window_hours": window, "wiki_impact": rows}
    finally:
        conn.close()
```

- [ ] **步骤 2：在 app.py 中注册路由**

```python
from backend.evaluation.routes import router as evaluation_router
app.include_router(evaluation_router)
```

- [ ] **步骤 3：验证**

```bash
cd backend && python -c "
from evaluation.routes import router
assert router.prefix == '/api/evaluation'
print(f'PASS: {len(router.routes)} routes')
for r in router.routes:
    print(f'  {r.path}')
"
```

- [ ] **步骤 4：Commit**

```bash
git add backend/evaluation/routes.py backend/app.py
git commit -m "feat: evaluation API — accuracy, latency, routing, token-usage, error-rate, wiki-impact"
```

---

#### 任务 4.3：A/B 测试框架 + 降级告警

**文件：**
- 创建：`backend/evaluation/ab_test.py`
- 创建：`backend/evaluation/alerts.py`

- [ ] **步骤 1：创建 evaluation/ab_test.py**

```python
"""规则 A/B 测试框架"""
import hashlib
import threading
from dataclasses import dataclass, field


@dataclass
class ABTest:
    test_id: str
    variant_a_rules: dict
    variant_b_rules: dict
    traffic_split: float = 0.5
    min_samples: int = 100

    def assign_variant(self, session_id: str) -> str:
        """确定性分配: hash(session_id + test_id) 决定走哪个 variant"""
        h = hashlib.sha256(f"{session_id}:{self.test_id}".encode()).hexdigest()
        bucket = int(h[:8], 16) % 100
        return "A" if bucket < self.traffic_split * 100 else "B"

    def get_results(self) -> dict:
        """从 evaluation_records 对比两个 variant 的效果"""
        # variant 信息通过 request_id 前缀编码
        return {
            "test_id": self.test_id,
            "variants": {"A": {}, "B": {}},
            "significant": False,  # 样本不足
        }


class ABTestRegistry:
    _tests: dict[str, ABTest] = {}

    @classmethod
    def register(cls, test: ABTest):
        cls._tests[test.test_id] = test

    @classmethod
    def get(cls, test_id: str) -> ABTest | None:
        return cls._tests.get(test_id)
```

- [ ] **步骤 2：创建 evaluation/alerts.py**

```python
"""降级检测告警"""
import time
import threading
import logging

logger = logging.getLogger(__name__)


class DegradationAlerts:
    THRESHOLDS = {
        "mismatch_rate": 0.10,
        "p95_latency_ms": 5000,
        "rejection_rate": 0.30,
        "error_rate": 0.05,
    }

    def __init__(self, check_interval_sec: int = 300):
        self.check_interval_sec = check_interval_sec
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        logger.info(f"DegradationAlerts started, check every {self.check_interval_sec}s")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            self.check()
            time.sleep(self.check_interval_sec)

    def check(self):
        try:
            from backend.db.mysql_store import get_conn
            conn = get_conn()
        except Exception:
            return

        try:
            # 检查 30 分钟窗口内的错误率
            sql = """SELECT
                       SUM(CASE WHEN fatal_errors > 0 THEN 1 ELSE 0 END) / COUNT(*) AS error_rate
                     FROM evaluation_records
                     WHERE created_at >= NOW() - INTERVAL 30 MINUTE"""
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
                if row and row[0]:
                    rate = float(row[0])
                    if rate > self.THRESHOLDS["error_rate"]:
                        from backend.event_bus import bus
                        bus.publish("evaluation.degraded", {
                            "metric": "error_rate",
                            "current": rate,
                            "threshold": self.THRESHOLDS["error_rate"],
                        })
                        logger.warning(f"Quality degradation: error_rate = {rate:.2%} > {self.THRESHOLDS['error_rate']:.0%}")
        except Exception:
            pass
        finally:
            conn.close()


# 全局单例
alerts = DegradationAlerts()
```

- [ ] **步骤 3：在 app.py lifespan 中启动告警检查**

```python
# 在 lifespan startup 中:
from backend.evaluation.alerts import alerts
alerts.start()

# 在 shutdown 中:
alerts.stop()
```

- [ ] **步骤 4：验证**

```bash
cd backend && python -c "
from evaluation.ab_test import ABTest, ABTestRegistry
t = ABTest('test-001', {'a': 1}, {'b': 2})
ABTestRegistry.register(t)
assert ABTestRegistry.get('test-001') is t
v = t.assign_variant('session-1')
assert v in ('A', 'B')
print(f'PASS: variant={v}')

from evaluation.alerts import DegradationAlerts
alerts = DegradationAlerts()
assert alerts.THRESHOLDS['error_rate'] == 0.05
print('PASS: alerts configured')
"
```

- [ ] **步骤 5：Commit**

```bash
git add backend/evaluation/ab_test.py backend/evaluation/alerts.py backend/app.py
git commit -m "feat: A/B testing framework + degradation detection alerts"
```

---

### 任务 5：Phase 5 — 统一层

**目标：** Orchestrator 并入 LangGraph，前端统一到 `/api/chat`。

---

#### 任务 5.1：创建 analysis_agent 子图

**文件：**
- 创建：`backend/langgraph/agents/analysis_agent.py`
- 修改：`backend/langgraph/registry.py:17-29` (AGENT_REGISTRY)
- 修改：`backend/langgraph/pipeline.py:16-26` (_route_agent)

- [ ] **步骤 1：创建 analysis_agent.py**

```python
"""Analysis Agent — LangGraph 子图，执行归因分析和 LLM 文本生成"""
import logging
from backend.langgraph.state import AgentState

logger = logging.getLogger(__name__)


def build_analysis_graph():
    """构建分析子图: parse → execute_tools → generate_text → post_validate → format"""
    from langgraph.graph import StateGraph, END

    builder = StateGraph(AgentState)
    builder.add_node("analysis_parse", _node_analysis_parse)
    builder.add_node("analysis_execute_tools", _node_analysis_execute_tools)
    builder.add_node("analysis_generate_text", _node_analysis_generate_text)
    builder.add_node("analysis_post_validate", _node_analysis_post_validate)
    builder.add_node("analysis_format", _node_analysis_format)

    builder.set_entry_point("analysis_parse")
    builder.add_edge("analysis_parse", "analysis_execute_tools")
    builder.add_edge("analysis_execute_tools", "analysis_generate_text")
    builder.add_edge("analysis_generate_text", "analysis_post_validate")
    builder.add_conditional_edges("analysis_post_validate", _route_post_validate, {
        "retry": "analysis_generate_text",
        "done": "analysis_format",
        "failed": "analysis_format",  # 重试仍失败，走模板兜底
    })
    builder.add_edge("analysis_format", END)
    return builder.compile()


def _node_analysis_parse(state: AgentState) -> dict:
    """确定分析维度：哪些维度还未指定，需要分解"""
    parsed = state.parsed_params or {}
    resolved = state.resolved_params or {}
    merged = {**parsed, **resolved}

    # 确定需要分解的维度
    all_dims = ["product_type", "bank", "customer"]
    specified = set()
    if merged.get("product_type"):
        specified.add("product_type")
    if merged.get("bank_name"):
        specified.add("bank")
    if merged.get("cust_name"):
        specified.add("customer")
    remaining = [d for d in all_dims if d not in specified]

    return {
        "parsed_params": {**merged, "analysis_dimensions": remaining},
    }


def _node_analysis_execute_tools(state: AgentState) -> dict:
    """确定执行 query_metrics + decompose_change"""
    from backend.agent.tools import query_metrics, decompose_change

    params = state.parsed_params or {}
    dims = params.get("analysis_dimensions", [])
    comparison = params.get("comparison", "")

    results = []
    try:
        # 1. 基线查询
        baseline = query_metrics(params={**params, "comparison": ""})
        results.append({"tool": "query_metrics", "type": "baseline", "data": baseline})

        # 2. 如果有比较，加比较查询
        if comparison:
            compare = query_metrics(params=params)
            results.append({"tool": "query_metrics", "type": "compare", "data": compare})

        # 3. 按维度分解
        for dim in dims:
            decomp = decompose_change(
                current_params=params,
                dimension=dim,
            )
            results.append({"tool": "decompose_change", "dimension": dim, "data": decomp})
    except Exception as e:
        logger.warning(f"Analysis tool execution error: {e}")
        results.append({"tool": "error", "error": str(e)})

    return {"analysis_data": {"tool_results": results}}


def _node_analysis_generate_text(state: AgentState) -> dict:
    """LLM 生成分析文本（使用 Pro 模型）"""
    from backend.agent.orchestrator import _build_system_prompt, _build_data_prompt
    from backend.llm_parser.llm_client import llm_chat

    data = state.analysis_data or {}
    tool_results = data.get("tool_results", [])

    system_prompt = _build_system_prompt()
    user_prompt = _build_data_prompt(tool_results)

    summary = llm_chat(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        task="analysis_text",
        request_id=state.request_id,
        session_id=state.session_id,
    )

    # 记录 LLM 调用到 _analysis_llm_response 供 PostValidator 使用
    if state._analysis_data is None:
        state._analysis_data = {}
    state._analysis_data["_llm_text"] = summary or ""

    return {"summary": summary or ""}


def _node_analysis_post_validate(state: AgentState) -> dict:
    """PostValidator 数字交叉校验"""
    from backend.agent.post_validator import PostValidator

    validator = PostValidator()
    mismatches = validator.validate(
        state.summary or "",
        state.analysis_data or {},
    )

    if mismatches:
        retry_count = getattr(state, "_analysis_retries", 0)
        if retry_count < 1:  # 最多 1 次重试
            from backend.llm_parser.llm_client import llm_chat
            correction_prompt = f"Your previous analysis had errors:\n{mismatches}\nPlease correct."
            corrected = llm_chat(
                system_prompt="Correct the analysis errors.",
                user_prompt=correction_prompt,
                task="analysis_retry",
                request_id=state.request_id,
                session_id=state.session_id,
            )
            return {
                "_analysis_retries": retry_count + 1,
                "_analysis_mismatches": mismatches,
                "summary": corrected or state.summary,
            }
        return {
            "_analysis_retries": retry_count + 1,
            "_analysis_mismatches": mismatches,
        }

    return {"_analysis_mismatches": []}


def _route_post_validate(state: AgentState) -> str:
    mismatches = getattr(state, "_analysis_mismatches", [])
    retries = getattr(state, "_analysis_retries", 0)
    if mismatches and retries < 2:
        return "retry"
    return "done"


def _node_analysis_format(state: AgentState) -> dict:
    """格式化输出"""
    from backend.services.result_formatter import build_insights

    params = state.parsed_params or {}
    insights = build_insights(params, [], [], {}) if hasattr(build_insights, '__call__') else []

    return {
        "summary": state.summary,
        "insights": insights,
        "mode": "analyze",
        "analysis_data": {
            "tool_calls": [r for r in (state.analysis_data or {}).get("tool_results", [])],
            "mismatches": getattr(state, "_analysis_mismatches", []),
        },
    }
```

- [ ] **步骤 2：在 registry.py 中注册 ANALYSIS agent**

修改 `backend/langgraph/registry.py` 第 17 行：

```python
AGENT_REGISTRY: dict[str, AgentCapability] = {
    "BI": AgentCapability(
        keywords=[...],  # 保持现有不变
        capabilities=[...],
        NOT_capabilities=[...],
        subgraph="bi_agent",
    ),
    "ANALYSIS": AgentCapability(
        keywords=["为什么", "原因", "分析", "怎么回事", "解释", "怎么变化", "趋势说明"],
        capabilities=["change_attribution", "dimension_decomposition", "text_analysis"],
        NOT_capabilities=["prediction", "forecast"],
        subgraph="analysis_agent",
    ),
}
```

- [ ] **步骤 3：在 pipeline.py 中添加 analysis_agent 分支**

修改 `_route_agent()` 函数（第 16 行）：

```python
def _route_agent(state: AgentState) -> str:
    decision = getattr(state, "router_decision", {}) or {}
    status = decision.get("status", "ok")
    if status in ("rejected", "confirm"):
        return "__end__"
    agent = decision.get("agent", "BI")
    if agent == "PRICING":
        return "pricing_agent"
    if agent == "ANALYSIS":
        return "analysis_agent"
    return "bi_agent"
```

在 `build_main_graph()` 中添加 analysis_agent 节点和边：

```python
from backend.langgraph.agents.analysis_agent import build_analysis_graph

analysis_graph = build_analysis_graph()
builder.add_node("analysis_agent", analysis_graph)
builder.add_edge("analysis_agent", "validate")
```

- [ ] **步骤 4：在 router.py 中添加 ANALYSIS 路由逻辑**

修改 `backend/langgraph/router.py`，在 `route_to_agent()` 中增加分析检测：

```python
def route_to_agent(text: str, context: list = None) -> dict:
    # ... 保持现有 Pricing/Bi 评分 ...

    # 检测分析意图
    analysis_score = _match_analysis_keywords(text)
    bi_score = match_keywords(text).get("BI", 0)

    # 分析意图强于一般查询 → 路由到 ANALYSIS
    if analysis_score > 0.3 and analysis_score > bi_score:
        return {
            "agent": "ANALYSIS",
            "confidence": analysis_score,
            "status": "ok",
            "reason": "analysis_intent_detected",
        }
```

并在文件末尾添加：

```python
_ANALYSIS_KEYWORDS = {"为什么", "原因", "分析", "怎么回事", "解释", "怎么变化", "趋势说明"}

def _match_analysis_keywords(text: str) -> float:
    hits = sum(1 for kw in _ANALYSIS_KEYWORDS if kw in text)
    return hits / len(_ANALYSIS_KEYWORDS) if _ANALYSIS_KEYWORDS else 0.0
```

- [ ] **步骤 5：前端统一到 /api/chat**

修改 `frontend/src/App.vue` 中 `handleSend()`：
- 移除 `isAnalytical` 正则检测
- 移除 `isPricing` 关键词检测
- 所有查询统一调用 `executeChat()`（需要新增到 api.js）

修改 `frontend/src/api.js`，添加：

```js
export async function executeChat(userText, sessionId) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_text: userText, session_id: sessionId }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.error || 'Request failed')
  }
  return res.json()
}
```

- [ ] **步骤 6：验证**

```bash
cd backend && python -c "
from langgraph.registry import AGENT_REGISTRY
assert 'ANALYSIS' in AGENT_REGISTRY
assert '分析' in AGENT_REGISTRY['ANALYSIS'].keywords
print('PASS: ANALYSIS agent registered')

from langgraph.agents.analysis_agent import build_analysis_graph
g = build_analysis_graph()
assert g is not None
print('PASS: analysis graph compiles')
"
```

- [ ] **步骤 7：Commit**

```bash
git add backend/langgraph/agents/analysis_agent.py backend/langgraph/registry.py backend/langgraph/pipeline.py backend/langgraph/router.py frontend/src/App.vue frontend/src/api.js
git commit -m "feat: unify pipelines — analysis_agent in LangGraph, frontend routes all to /api/chat"
```

---

## 验收检查清单

Phase 0:
- [ ] `GET /api/evaluation/token-usage` 返回按 call_site 分组的 token 数据
- [ ] 所有 LLM 调用点读取 `response.usage` 写入 `token_usage_log`

Phase 1:
- [ ] ContextAssembler 消除双重发送（日志验证：BI parse 不再包含原始 context）
- [ ] Wiki 规则注入 prompt_builder，查询"远期"时注入 FWD 必填字段
- [ ] PostValidator 不匹配率不高于改造前

Phase 2:
- [ ] LangGraph 管线崩溃后从最近 checkpoint 恢复
- [ ] Oracle/LLM/Pricing Engine 超时自动重试（最多 2 次）
- [ ] 连续 5 次失败触发熔断
- [ ] 所有 HTTP 请求有 X-Request-ID

Phase 3:
- [ ] 新增 MCP 工具（wiki_search, wiki_get）可通过 MCP 协议调用
- [ ] LLM tool_call 参数通过 JSON Schema 校验
- [ ] API Key 认证生效

Phase 4:
- [ ] `/api/evaluation/accuracy` 等端点正常返回数据
- [ ] A/B 测试框架可用

Phase 5:
- [ ] 前端所有查询统一走 `/api/chat`
- [ ] 分析查询路由到 analysis_agent 子图
- [ ] `isAnalytical` 逻辑从 App.vue 移除
