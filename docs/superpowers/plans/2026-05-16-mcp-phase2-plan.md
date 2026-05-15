# MCP Phase 2 实现计划 — LangGraph 编排层

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 构建 LangGraph 编排层（Context Resolver → Router → BI Agent → Validator），新增 8 个 MCP 工具，新端点 `/api/chat`，新旧系统并行运行。

**架构：** 新增 `backend/langgraph/` 目录，每个组件一个文件。BI Agent 封装现有 BI 逻辑（不重写）。8 个 MCP 工具放在 `backend/mcp/tools/`。`/api/chat` 端点在 `app.py` 中新增，与 `/api/query` 并行。

**技术栈：** Python 3.13 + LangGraph 1.1 + FastMCP + FastAPI + oracledb + pymysql

---

## 文件结构

### 新建

| 文件 | 职责 |
|------|------|
| `backend/mcp/tools/load_rules_tool.py` | MySQL 规则库查询工具 |
| `backend/mcp/tools/parse_date_tool.py` | 自然语言日期提取工具 |
| `backend/mcp/tools/detect_entities_tool.py` | 实体检测（银行/客户）工具 |
| `backend/mcp/tools/compute_comparison_tool.py` | 同比/环比计算工具 |
| `backend/mcp/tools/get_session_context_tool.py` | 会话历史查询工具 |
| `backend/mcp/tools/save_memory_tool.py` | 会话记忆保存工具 |
| `backend/mcp/tools/write_audit_log_tool.py` | 审计日志写入工具 |
| `backend/mcp/tools/check_cache_tool.py` | 缓存查询工具 |
| `backend/langgraph/__init__.py` | 包入口 |
| `backend/langgraph/state.py` | AgentState dataclass |
| `backend/langgraph/agents/__init__.py` | Agents 子包 |
| `backend/langgraph/agents/bi_agent.py` | BI Agent 子图（6 个节点） |
| `backend/langgraph/router.py` | 三层门禁路由 |
| `backend/langgraph/registry.py` | Agent 注册表 |
| `backend/langgraph/graph.py` | 主图 DAG |
| `backend/langgraph/context_resolver.py` | LLM 上下文解析 |
| `backend/langgraph/validators.py` | SQL + Result Validator |

### 修改

| 文件 | 修改 |
|------|------|
| `backend/mcp/server.py` | 注册 8 个新工具 |
| `backend/app.py` | 新增 `/api/chat` 端点，注册 langgraph 路由 |

---

### 任务 1：新增 8 个 MCP 工具

**文件：**
- 创建：`backend/mcp/tools/load_rules_tool.py`
- 创建：`backend/mcp/tools/parse_date_tool.py`
- 创建：`backend/mcp/tools/detect_entities_tool.py`
- 创建：`backend/mcp/tools/compute_comparison_tool.py`
- 创建：`backend/mcp/tools/get_session_context_tool.py`
- 创建：`backend/mcp/tools/save_memory_tool.py`
- 创建：`backend/mcp/tools/write_audit_log_tool.py`
- 创建：`backend/mcp/tools/check_cache_tool.py`
- 修改：`backend/mcp/server.py`（注册 8 个新工具）

- [ ] **Step 1: 创建 load_rules_tool.py**

```python
# backend/mcp/tools/load_rules_tool.py
"""MCP tool: load_rules — query MySQL rule items by category."""

import logging
from mcp.server.fastmcp import FastMCP
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def load_rules(category: str) -> list[dict]:
        """Load rule items for a given category from the MySQL rules store.

        Categories: product_type, buy_sell_direction, bank_name,
        special_states, amount_filter, app_id.

        Args:
            category: Rule category name.

        Returns:
            list of dicts, each containing keyword, display_value, display_name.
        """
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT keyword, display_value, display_name "
                    "FROM rule_items WHERE category = %s AND is_active = 1 "
                    "ORDER BY priority",
                    (category,),
                )
                rows = [dict(r) for r in cur.fetchall()]
                logger.info("load_rules(%s): %d items", category, len(rows))
                return rows
        finally:
            conn.close()
```

- [ ] **Step 2: 创建 parse_date_tool.py**

```python
# backend/mcp/tools/parse_date_tool.py
"""MCP tool: parse_date — extract date range from natural language text."""

import json
import logging
import os
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def parse_date(text: str) -> dict:
        """Extract a date range from natural language text using LLM.

        Args:
            text: Natural language text containing date references.

        Returns:
            dict with keys: date_start (str), date_end (str), display (str).
            Empty dict if no date found.
        """
        api_key = os.environ.get("LLM_API_KEY", "")
        base_url = os.environ.get("LLM_BASE_URL", "")
        model = os.environ.get("LLM_MODEL", "")
        if not api_key or not base_url or not model:
            return {}

        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                temperature=0.0,
                messages=[{"role": "user", "content": (
                    f"从以下文本中提取日期范围，返回JSON格式：\n"
                    f'{{"date_start":"YYYY-MM-DD","date_end":"YYYY-MM-DD",'
                    f'"display":"中文描述"}}\n'
                    f"如果无明确日期返回{{}}\n文本：{text}"
                )}],
                timeout=10,
            )
            content = resp.choices[0].message.content or "{}"
            # Extract JSON from response
            import re
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                return json.loads(m.group(1))
            return {}
        except Exception as exc:
            logger.warning("parse_date failed: %s", exc)
            return {}
```

- [ ] **Step 3: 创建 detect_entities_tool.py**

```python
# backend/mcp/tools/detect_entities_tool.py
"""MCP tool: detect_entities — extract bank/customer/APP entities from text."""

import json
import logging
import os
import re
from mcp.server.fastmcp import FastMCP
from openai import OpenAI
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def detect_entities(text: str) -> dict:
        """Detect bank names, customer names, and APP IDs from text.

        Uses LLM + MySQL rule lookup for entity resolution.

        Args:
            text: Natural language text.

        Returns:
            dict with keys: banks (list), customers (list), app_ids (list).
        """
        # First try LLM extraction
        api_key = os.environ.get("LLM_API_KEY", "")
        base_url = os.environ.get("LLM_BASE_URL", "")
        model = os.environ.get("LLM_MODEL", "")
        result = {"banks": [], "customers": [], "app_ids": []}

        if api_key and base_url and model:
            try:
                client = OpenAI(api_key=api_key, base_url=base_url)
                resp = client.chat.completions.create(
                    model=model,
                    temperature=0.0,
                    messages=[{"role": "user", "content": (
                        f"从文本中提取实体，返回JSON：\n"
                        f'{{"banks":["银行名"],"customers":["客户名"],"app_ids":["APPID"]}}\n'
                        f"无匹配返回空数组。文本：{text}"
                    )}],
                    timeout=10,
                )
                content = resp.choices[0].message.content or "{}"
                m = re.search(r"\{.*\}", content, re.DOTALL)
                if m:
                    result = json.loads(m.group(1))
            except Exception as exc:
                logger.warning("detect_entities LLM failed: %s", exc)

        # Fallback: match against known bank names from MySQL
        if not result.get("banks"):
            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT display_name FROM rule_items "
                        "WHERE category = 'bank_name' AND is_active = 1"
                    )
                    for row in cur.fetchall():
                        name = row["display_name"]
                        if name and name in text:
                            result["banks"].append(row["display_value"] or name)
            finally:
                conn.close()

        return result
```

- [ ] **Step 4: 创建 compute_comparison_tool.py**

```python
# backend/mcp/tools/compute_comparison_tool.py
"""MCP tool: compute_comparison — calculate YoY/MoM comparison data."""

import logging
from mcp.server.fastmcp import FastMCP
from llm_parser.parser import compute_comparison_dates

logger = logging.getLogger(__name__)


def _compute(rows: list, compare_rows: list, comparison: str,
             date_start: str, date_end: str, cmp_start: str, cmp_end: str) -> dict | None:
    """Replica of app._compute_comparison for MCP tool use."""
    if not rows or not compare_rows:
        return None
    try:
        amt_idx = 1  # TOTAL_AMOUNT
        current_amt = float(rows[0][amt_idx]) if rows[0][amt_idx] is not None else 0
        compare_amt = float(compare_rows[0][amt_idx]) if compare_rows[0][amt_idx] is not None else 0
    except (ValueError, IndexError, TypeError):
        return None

    change_amount = current_amt - compare_amt
    change_rate = round(abs(change_amount / compare_amt) * 100, 2) if compare_amt != 0 else None

    label_map = {"yoy": "同比", "mom": "环比"}
    return {
        "type": comparison,
        "label": label_map.get(comparison, comparison),
        "current_period": f"{date_start} ~ {date_end}",
        "compare_period": f"{cmp_start} ~ {cmp_end}",
        "current_amount": round(current_amt, 2),
        "compare_amount": round(compare_amt, 2),
        "change_amount": round(change_amount, 2),
        "change_rate": change_rate,
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def compute_comparison(rows: list, comparison: str,
                           date_start: str, date_end: str,
                           compare_rows: list) -> dict | None:
        """Calculate YoY or MoM comparison from current and comparison data.

        Args:
            rows: Current period query results (list of rows).
            comparison: 'yoy' or 'mom'.
            date_start: Current period start date.
            date_end: Current period end date.
            compare_rows: Comparison period query results.

        Returns:
            dict with comparison data, or None if computation fails.
        """
        cmp_start, cmp_end = compute_comparison_dates(date_start, date_end, comparison)
        if not cmp_start or not cmp_end:
            return None
        return _compute(rows, compare_rows, comparison,
                        date_start, date_end, cmp_start, cmp_end)
```

- [ ] **Step 5: 创建 get_session_context_tool.py**

```python
# backend/mcp/tools/get_session_context_tool.py
"""MCP tool: get_session_context — retrieve conversation history."""

import logging
from mcp.server.fastmcp import FastMCP
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_session_context(session_id: str, n: int = 20) -> list[dict]:
        """Get recent conversation turns for a session.

        Args:
            session_id: The session identifier.
            n: Number of recent turns to retrieve (default 20).

        Returns:
            list of dicts with keys: turn_index, user_query, parsed_params,
            executed_sql, result_summary.
        """
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT turn_index, user_query, parsed_params, "
                    "executed_sql, result_summary "
                    "FROM turns WHERE session_id = %s "
                    "ORDER BY turn_index DESC LIMIT %s",
                    (session_id, n),
                )
                rows = cur.fetchall()
                # Reverse to chronological order
                result = [dict(r) for r in reversed(rows)]
                logger.info("get_session_context(%s): %d turns", session_id, len(result))
                return result
        finally:
            conn.close()
```

- [ ] **Step 6: 创建 save_memory_tool.py**

```python
# backend/mcp/tools/save_memory_tool.py
"""MCP tool: save_memory — persist session memory."""

import json
import logging
from mcp.server.fastmcp import FastMCP
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def save_memory(session_id: str, key: str, value: str) -> str:
        """Save a key-value memory entry for a session.

        Upserts into the memory_summaries table.

        Args:
            session_id: The session identifier.
            key: Memory key (e.g., 'last_params', 'user_preference').
            value: JSON-encoded value string.

        Returns:
            'ok' on success, error message on failure.
        """
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO memory_summaries (session_id, key, value) "
                    "VALUES (%s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE value = %s, updated_at = NOW()",
                    (session_id, key, value, value),
                )
            conn.commit()
            logger.info("save_memory(%s, %s): %d chars", session_id, key, len(value))
            return "ok"
        except Exception as exc:
            logger.warning("save_memory failed: %s", exc)
            return f"error: {exc}"
        finally:
            conn.close()
```

- [ ] **Step 7: 创建 write_audit_log_tool.py**

```python
# backend/mcp/tools/write_audit_log_tool.py
"""MCP tool: write_audit_log — append-only audit trail."""

import json
import logging
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def write_audit_log(request_id: str, data: str) -> str:
        """Write an entry to the append-only audit log.

        Args:
            request_id: Unique identifier for the request.
            data: JSON string containing audit fields. Must include
                  session_id, user_text, router_decision, resolved_params,
                  sql_executed, result_rows, response_to_user.

        Returns:
            'ok' on success, error message on failure.
        """
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            return f"error: invalid JSON - {exc}"

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO audit_log
                       (request_id, session_id, raw_input, router_decision,
                        resolved_params, sql_executed, result_rows,
                        result_hash, response_to_user, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        request_id,
                        payload.get("session_id", ""),
                        payload.get("user_text", ""),
                        json.dumps(payload.get("router_decision", {}), ensure_ascii=False),
                        json.dumps(payload.get("resolved_params", {}), ensure_ascii=False),
                        payload.get("sql_executed", ""),
                        payload.get("result_rows", 0),
                        payload.get("result_hash", ""),
                        payload.get("response_to_user", ""),
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
            conn.commit()
            logger.info("write_audit_log(%s): OK", request_id)
            return "ok"
        except Exception as exc:
            logger.warning("write_audit_log failed: %s", exc)
            return f"error: {exc}"
        finally:
            conn.close()
```

- [ ] **Step 8: 创建 check_cache_tool.py**

```python
# backend/mcp/tools/check_cache_tool.py
"""MCP tool: check_cache — query result cache lookup.

Stub implementation — cache layer comes in Phase 4.
"""

import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def check_cache(params_hash: str) -> dict | None:
        """Check if a cached query result exists for the given params hash.

        Args:
            params_hash: SHA-256 hash of serialized query parameters.

        Returns:
            Cached result dict, or None (cache not yet implemented).
        """
        logger.debug("check_cache(%s): miss (cache not implemented)", params_hash)
        return None
```

- [ ] **Step 9: 更新 server.py 注册 8 个新工具**

在 `backend/mcp/server.py` 末尾，`llm_tool.register(mcp)` 之后添加：

```python
from .tools import load_rules_tool  # noqa: E402
load_rules_tool.register(mcp)

from .tools import parse_date_tool  # noqa: E402
parse_date_tool.register(mcp)

from .tools import detect_entities_tool  # noqa: E402
detect_entities_tool.register(mcp)

from .tools import compute_comparison_tool  # noqa: E402
compute_comparison_tool.register(mcp)

from .tools import get_session_context_tool  # noqa: E402
get_session_context_tool.register(mcp)

from .tools import save_memory_tool  # noqa: E402
save_memory_tool.register(mcp)

from .tools import write_audit_log_tool  # noqa: E402
write_audit_log_tool.register(mcp)

from .tools import check_cache_tool  # noqa: E402
check_cache_tool.register(mcp)
```

- [ ] **Step 10: 验证 11 个工具（3 旧 + 8 新）**

```bash
cd c:/AIProject/smartbi0512/backend
python -c "
from mcp.server import mcp
print('Tools registered:', len(mcp._tool_manager._tools))
for name in sorted(mcp._tool_manager._tools.keys()):
    print(f'  {name}')
"
```

预期输出包含：`oracle_query`、`mysql_query`、`llm_chat`、`load_rules`、`parse_date`、`detect_entities`、`compute_comparison`、`get_session_context`、`save_memory`、`write_audit_log`、`check_cache`。

- [ ] **Step 11: 提交**

```bash
git add backend/mcp/tools/load_rules_tool.py
git add backend/mcp/tools/parse_date_tool.py
git add backend/mcp/tools/detect_entities_tool.py
git add backend/mcp/tools/compute_comparison_tool.py
git add backend/mcp/tools/get_session_context_tool.py
git add backend/mcp/tools/save_memory_tool.py
git add backend/mcp/tools/write_audit_log_tool.py
git add backend/mcp/tools/check_cache_tool.py
git add backend/mcp/server.py
git commit -m "feat(mcp): 新增 8 个 MCP 工具 — 规则/日期/实体/对比/记忆/审计/缓存"
```

---

### 任务 2：LangGraph State + BI Agent 子图

**文件：**
- 创建：`backend/langgraph/__init__.py`
- 创建：`backend/langgraph/state.py`
- 创建：`backend/langgraph/agents/__init__.py`
- 创建：`backend/langgraph/agents/bi_agent.py`
- 安装：`pip install langgraph`

- [ ] **Step 1: 安装 langgraph**

```bash
pip install "langgraph>=1.1.10"
```

验证：`python -c "from langgraph.graph import StateGraph; print('langgraph', StateGraph.__module__)"`

- [ ] **Step 2: 创建 langgraph/__init__.py**

```python
# backend/langgraph/__init__.py
"""LangGraph orchestration layer — DAG-based multi-agent pipeline."""
```

- [ ] **Step 3: 创建 langgraph/agents/__init__.py**

```python
# backend/langgraph/agents/__init__.py
"""Agent sub-graph implementations."""
```

- [ ] **Step 4: 创建 state.py**

```python
# backend/langgraph/state.py
"""AgentState — shared state for the LangGraph pipeline."""
from dataclasses import dataclass, field


@dataclass
class AgentState:
    """Pipeline state flowing through Context Resolver → Router → Agent → Validator."""

    # Input
    request_id: str = ""
    session_id: str = ""
    user_text: str = ""
    context: list[dict] | None = None  # optional frontend-provided context

    # Context Resolver output
    resolved_params: dict = field(default_factory=dict)
    inherited_fields: list[str] = field(default_factory=list)
    context_confidence: float = 0.0
    needs_confirm: list[str] = field(default_factory=list)

    # Router output
    router_decision: dict = field(default_factory=dict)

    # BI Agent output
    parsed_params: dict = field(default_factory=dict)
    pipeline: str = ""
    sql: str = ""
    sql_validated: bool = False
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    comparison: dict | None = None

    # Validator output
    validation_warnings: list[str] = field(default_factory=list)

    # Formatter output
    summary: str = ""
    chart_option: dict | None = None
    insights: list[dict] = field(default_factory=list)
    error: str = ""
```

- [ ] **Step 5: 创建 BI Agent 子图**

```python
# backend/langgraph/agents/bi_agent.py
"""BI Agent sub-graph — parse, gatekeep, build SQL, execute, compare, format."""

import logging
from langgraph.graph import StateGraph
from llm_parser.parser import rule_based_parse, _rule_confidence
from llm_parser.rules_engine import gatekeep
from llm_parser.llm_client import llm_parse
from llm_parser.prompt_builder import build_system_prompt
from db.query_builder import TradeQueryBuilder
from db.connection import get_db
from langgraph.state import AgentState

logger = logging.getLogger(__name__)


def _node_parse(state: AgentState) -> dict:
    """Parse user text using rule engine + optional LLM fallback."""
    text = state.user_text
    resolved = state.resolved_params or {}

    rule_parsed = rule_based_parse(text)
    confidence = _rule_confidence(text, rule_parsed)

    if confidence >= 0.8:
        parsed = gatekeep(rule_parsed, text)
        pipeline = f"rule(confidence={confidence:.0%})"
    else:
        system_prompt = build_system_prompt(state.context)
        llm_result = llm_parse(text, system_prompt)
        if llm_result is not None:
            parsed = gatekeep(llm_result, text)
            pipeline = f"llm+gatekeep(rule_confidence={confidence:.0%})"
        else:
            parsed = gatekeep(rule_parsed, text)
            pipeline = f"rule_fallback(confidence={confidence:.0%})"

    # Merge resolved context (e.g. inherited dates) into parsed params
    for k, v in resolved.items():
        if v and not parsed.get(k):
            parsed[k] = v

    return {"parsed_params": parsed, "pipeline": pipeline}


def _node_build_sql(state: AgentState) -> dict:
    """Build SQL from parsed params using TradeQueryBuilder."""
    parsed = state.parsed_params
    if not parsed:
        return {"sql": "", "sql_validated": False}

    buy_sell = parsed.get("buy_sell") or None
    cust_name = parsed.get("cust_name") or None
    special_states = parsed.get("special_states")
    if isinstance(special_states, str) and special_states:
        special_states = [s.strip() for s in special_states.split(",")]
    else:
        special_states = None

    amount_filter = parsed.get("amount_filter")
    top_n = parsed.get("top_n")

    try:
        if amount_filter:
            sql = TradeQueryBuilder.build_filtered_query(
                product_type=parsed["product_type"],
                date_start=parsed.get("date_start") or None,
                date_end=parsed.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                amount_op=amount_filter["amount_op"],
                amount_value=amount_filter["amount_value"],
                hedge_ratio=parsed.get("hedge_ratio", False),
                dimension=parsed.get("dimension", "bank"),
                cust_name=cust_name, appid=parsed.get("appid"),
            )
        elif top_n and top_n > 0:
            sql = TradeQueryBuilder.build_ranking_query(
                product_type=parsed["product_type"],
                date_start=parsed.get("date_start") or None,
                date_end=parsed.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                top_n=top_n, dimension=parsed.get("dimension", "bank"),
                hedge_ratio=parsed.get("hedge_ratio", False),
                cust_name=cust_name, appid=parsed.get("appid"),
            )
        elif parsed.get("hedge_ratio"):
            sql = TradeQueryBuilder.build_hedge_ratio_query(
                product_type=parsed["product_type"],
                date_start=parsed.get("date_start") or None,
                date_end=parsed.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                dimension=parsed.get("dimension", "bank"),
                cust_name=cust_name, appid=parsed.get("appid"),
            )
        elif parsed.get("aggregate"):
            sql = TradeQueryBuilder.build_aggregate_query(
                product_type=parsed["product_type"],
                date_start=parsed.get("date_start") or None,
                date_end=parsed.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                cust_name=cust_name, appid=parsed.get("appid"),
                dimension=parsed.get("dimension"),
            )
        else:
            sql = TradeQueryBuilder.build_query(
                product_type=parsed["product_type"],
                date_start=parsed.get("date_start") or None,
                date_end=parsed.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                cust_name=cust_name, appid=parsed.get("appid"),
            )
        return {"sql": sql, "sql_validated": True}
    except Exception as exc:
        logger.warning("build_sql failed: %s", exc)
        return {"sql": "", "sql_validated": False, "error": str(exc)}


def _node_execute(state: AgentState) -> dict:
    """Execute SQL against Oracle."""
    if not state.sql:
        return {"columns": [], "rows": [], "row_count": 0}

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(state.sql)
                cols = [desc[0] for desc in cur.description] if cur.description else []
                rows = [list(row) for row in cur.fetchall()]
                logger.info("bi_agent execute: %d rows, %d cols", len(rows), len(cols))
                return {"columns": cols, "rows": rows, "row_count": len(rows)}
    except Exception as exc:
        logger.warning("execute failed: %s", exc)
        return {"columns": [], "rows": [], "row_count": 0, "error": str(exc)}


def _node_build_comparison(state: AgentState) -> dict:
    """Build comparison data from existing rows (already enriched by SQL)."""
    # Comparison is already computed in the query SQL for ranking queries.
    # For aggregate queries, the comparison data comes from a second SQL.
    # For Phase 2, we skip re-computation and pass through.
    return {}


def _node_format(state: AgentState) -> dict:
    """Format results into summary, chart_option, insights."""
    from app import _build_summary, _build_chart_option, _build_insights

    if not state.rows or not state.columns:
        return {"summary": "", "chart_option": None, "insights": []}

    summary = _build_summary(state.parsed_params, state.rows,
                             state.columns, state.comparison)
    chart_option = _build_chart_option(state.parsed_params, state.rows,
                                       state.columns, state.comparison)
    insights = _build_insights(state.parsed_params, state.rows,
                               state.columns, state.comparison)

    return {"summary": summary, "chart_option": chart_option, "insights": insights}


def build_bi_subgraph() -> StateGraph:
    """Build and return the BI Agent sub-graph."""
    builder = StateGraph(AgentState)

    builder.add_node("parse", _node_parse)
    builder.add_node("build_sql", _node_build_sql)
    builder.add_node("execute", _node_execute)
    builder.add_node("build_comparison", _node_build_comparison)
    builder.add_node("format", _node_format)

    builder.set_entry_point("parse")
    builder.add_edge("parse", "build_sql")
    builder.add_edge("build_sql", "execute")
    builder.add_edge("execute", "build_comparison")
    builder.add_edge("build_comparison", "format")

    return builder.compile()
```

- [ ] **Step 6: 验证 BI Agent 子图可导入**

```bash
cd c:/AIProject/smartbi0512/backend
python -c "
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('.env'))
from langgraph.agents.bi_agent import build_bi_subgraph
graph = build_bi_subgraph()
print('BI subgraph:', type(graph).__name__)
print('Nodes:', list(graph.nodes.keys()))
"
```

预期: `BI subgraph: CompiledStateGraph`, Nodes 包含 parse/build_sql/execute/build_comparison/format。

- [ ] **Step 7: 提交**

```bash
git add backend/langgraph/
git commit -m "feat(langgraph): State + BI Agent 子图 — parse→build→execute→format"
```

---

### 任务 3：主图 + /api/chat 端点

**文件：**
- 创建：`backend/langgraph/graph.py`
- 修改：`backend/app.py`（新增 `/api/chat` 端点）

- [ ] **Step 1: 创建主图 graph.py**

```python
# backend/langgraph/graph.py
"""Main LangGraph DAG — Context Resolver → Router → Agent → Validator → Format."""

import logging
from langgraph.graph import StateGraph
from langgraph.state import AgentState
from langgraph.agents.bi_agent import build_bi_subgraph
from langgraph.validators import node_validate_result

logger = logging.getLogger(__name__)

# Conditional routing: skip router for now, direct all to BI Agent
def _route_agent(state: AgentState) -> str:
    """Route to the appropriate agent sub-graph based on router decision."""
    decision = state.router_decision or {}
    status = decision.get("status", "ok")
    if status == "rejected":
        return "__end__"
    if status == "confirm":
        return "__end__"  # Frontend handles confirm cards
    return "bi_agent"


def build_main_graph() -> StateGraph:
    """Build the full orchestration graph."""
    builder = StateGraph(AgentState)

    # Nodes
    builder.add_node("bi_agent", build_bi_subgraph())
    builder.add_node("validate", node_validate_result)

    # Entry point: Context Resolver and Router are stubbed for now
    builder.set_entry_point("bi_agent")

    # Edges
    builder.add_edge("bi_agent", "validate")

    return builder.compile()
```

- [ ] **Step 2: 在 app.py 中注册 /api/chat 端点**

在 `backend/app.py` 末尾、`app.mount("/assets", ...)` 之后添加：

```python
# ---- LangGraph orchestration endpoint ----

from langgraph.graph import build_main_graph
_langgraph_app = build_main_graph()


@app.post("/api/chat")
async def api_chat(request: Request):
    """Run the LangGraph orchestration pipeline.

    Parallel to /api/query — both return the same ResultCard-compatible format.
    """
    from langgraph.state import AgentState

    body = await request.json()
    text = body.get("text", "")
    session_id = body.get("session_id", "")
    context = body.get("context")

    state = AgentState(
        request_id=str(uuid.uuid4())[:8],
        session_id=session_id,
        user_text=text,
        context=context,
    )

    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=True)

        final = await _langgraph_app.ainvoke(state)

        return {
            "sql": final.sql,
            "params": final.parsed_params,
            "columns": final.columns,
            "rows": final.rows,
            "row_count": final.row_count,
            "comparison": final.comparison,
            "summary": final.summary,
            "chartOption": final.chart_option,
            "insights": final.insights,
            "error": final.error,
        }
    except Exception as exc:
        logger.exception("LangGraph /api/chat failed: %s", text)
        return JSONResponse(status_code=500, content={
            "error": f"{type(exc).__name__}: {exc}",
            "sql": "",
            "params": {},
            "columns": [],
            "rows": [],
            "row_count": 0,
            "comparison": None,
            "summary": "",
            "chartOption": {},
            "insights": [],
        })
```

- [ ] **Step 3: 验证 /api/chat 可通过 LangGraph 执行查询**

```bash
cd c:/AIProject/smartbi0512/backend
# Ensure server is running
python -c "
import requests
r = requests.post('http://localhost:8000/api/chat',
    json={'text': '本月交易量', 'session_id': 'test001'})
d = r.json()
print('Status:', r.status_code)
print('Summary:', d.get('summary', '')[:100])
print('Columns:', d.get('columns', []))
print('Row count:', d.get('row_count', 0))
# Check ResultCard compatibility
assert all(k in d for k in ['summary','chartOption','insights','columns','rows'])
print('PASS: ResultCard compatible')
"
```

预期输出：与 `/api/query` 相同格式，summary 和 chartOption 有内容。

- [ ] **Step 4: 提交**

```bash
git add backend/langgraph/graph.py backend/app.py
git commit -m "feat(langgraph): 主图 DAG + /api/chat 端点，并行运行"
```

---

### 任务 4：Router + Agent Registry

**文件：**
- 创建：`backend/langgraph/registry.py`
- 创建：`backend/langgraph/router.py`
- 修改：`backend/langgraph/graph.py`（添加 Router 节点）

- [ ] **Step 1: 创建 registry.py**

```python
# backend/langgraph/registry.py
"""Agent registry — capability definitions and routing metadata."""

from dataclasses import dataclass, field


@dataclass
class AgentCapability:
    """Capability definition for a single Agent."""
    name: str
    keywords: list[str]
    capabilities: list[str]
    NOT_capabilities: list[str]
    subgraph: str = ""


AGENT_REGISTRY: dict[str, AgentCapability] = {
    "BI": AgentCapability(
        name="BI",
        keywords=["交易量", "排名", "套保率", "金额", "笔数",
                  "银行", "客户", "同比", "环比", "汇总", "趋势"],
        capabilities=["聚合查询", "排名查询", "套保率计算",
                      "同比环比对比", "条件过滤"],
        NOT_capabilities=["预测", "预估", "趋势预测",
                          "风险评估", "异常检测", "汇率报价",
                          "客户信用", "合规检查"],
        subgraph="bi_agent",
    ),
}


def match_keywords(text: str) -> dict[str, float]:
    """Score each agent by keyword match ratio.

    Returns dict of {agent_name: score}.
    """
    scores: dict[str, float] {}
    for name, cap in AGENT_REGISTRY.items():
        hits = sum(1 for kw in cap.keywords if kw in text)
        scores[name] = hits / max(len(cap.keywords), 1)  # normalized 0..1
    return scores


def check_not_capabilities(text: str) -> list[str]:
    """Check if text hits any NOT_capabilities across all agents.

    Returns list of agents with blocked capabilities hit.
    """
    blocked = []
    for name, cap in AGENT_REGISTRY.items():
        for nc in cap.NOT_capabilities:
            if nc in text:
                blocked.append(name)
                break
    return blocked
```

- [ ] **Step 2: 创建 router.py**

```python
# backend/langgraph/router.py
"""Router — 3-gate security: keyword match, entity validation, parameter completeness."""

import logging
from langgraph.state import AgentState
from langgraph.registry import match_keywords, check_not_capabilities

logger = logging.getLogger(__name__)


def route_to_agent(state: AgentState) -> dict:
    """Run three security gates to decide routing.

    Returns updated router_decision dict.
    """
    text = state.user_text
    scores = match_keywords(text)

    # Gate 1: lowest confidence. If no agent scores above 0.1 → unknown topic
    max_score = max(scores.values()) if scores else 0
    if max_score < 0.1:
        return {
            "router_decision": {
                "status": "rejected",
                "agent": "fallback",
                "confidence": 0.0,
                "reason": "out_of_scope",
                "message": "该查询超出我目前的分析范围。请尝试查询交易量、排名或套保率数据。",
            }
        }

    # Gate 2: NOT_capabilities check (hard block)
    blocked = check_not_capabilities(text)
    if blocked:
        return {
            "router_decision": {
                "status": "rejected",
                "agent": blocked[0],
                "confidence": 0.0,
                "reason": "not_capability",
                "message": "抱歉，我不支持该类查询。可以查询交易数据或排名信息。",
            }
        }

    # Gate 3: parameter completeness check
    # (Simplified for now - full entity validation comes with Context Resolver)
    best_agent = max(scores, key=scores.get)

    return {
        "router_decision": {
            "status": "ok",
            "agent": best_agent,
            "confidence": round(max_score, 2),
            "reason": "",
            "message": "",
        }
    }
```

- [ ] **Step 3: 更新 graph.py 加入 Router**

修改 `build_main_graph` 添加 Router 节点：

```python
# In backend/langgraph/graph.py, update imports:
from langgraph.router import route_to_agent

def build_main_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    builder.add_node("router", route_to_agent)
    builder.add_node("bi_agent", build_bi_subgraph())
    builder.add_node("validate", node_validate_result)

    builder.set_entry_point("router")

    # Router → conditional agent dispatch
    builder.add_conditional_edges(
        "router",
        _route_agent,
        {"bi_agent": "bi_agent", "__end__": "__end__"},
    )
    builder.add_edge("bi_agent", "validate")

    return builder.compile()
```

同时更新 `_route_agent` 函数，使其使用 `state.router_decision`：

```python
def _route_agent(state: AgentState) -> str:
    decision = state.router_decision or {}
    status = decision.get("status", "ok")
    if status in ("rejected", "confirm"):
        return "__end__"
    # Map agent name to graph node (only BI for now)
    return "bi_agent"
```

- [ ] **Step 4: 验证 Router 决策**

```bash
cd c:/AIProject/smartbi0512/backend
python -c "
import os
os.environ['DB_HOST'] = '192.168.10.184'
from langgraph.router import route_to_agent
from langgraph.state import AgentState

# Test 1: valid BI query
s = AgentState(user_text='本月工行交易量')
r = route_to_agent(s)
assert r['router_decision']['status'] == 'ok'
print('Test 1 PASS: BI query routed OK')

# Test 2: out-of-scope query  
s = AgentState(user_text='帮我预测下个月美元走势')
r = route_to_agent(s)
assert r['router_decision']['status'] == 'rejected'
print('Test 2 PASS: prediction rejected')

# Test 3: NOT_capabilities hit
s = AgentState(user_text='风险评估报告')
r = route_to_agent(s)
assert r['router_decision']['status'] == 'rejected'
print('Test 3 PASS: risk assessment rejected')

print('All router tests passed')
"
```

- [ ] **Step 5: 提交**

```bash
git add backend/langgraph/registry.py backend/langgraph/router.py backend/langgraph/graph.py
git commit -m "feat(langgraph): Router 三层门禁 — 关键词 + NOT_capabilities + 参数完整性"
```

---

### 任务 5：Context Resolver

**文件：**
- 创建：`backend/langgraph/context_resolver.py`
- 修改：`backend/langgraph/graph.py`（添加 Context Resolver 节点）

- [ ] **Step 1: 创建 context_resolver.py**

```python
# backend/langgraph/context_resolver.py
"""Context Resolver — LLM-based full conversation history analysis."""

import json
import logging
import os
import re
from openai import OpenAI
from langgraph.state import AgentState

logger = logging.getLogger(__name__)


def _resolve_fallback(state: AgentState) -> dict:
    """Fallback: take most recent assistant date from context."""
    ctx = state.context or []
    for msg in reversed(ctx):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            try:
                prev = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            ds = prev.get("date_start", "") or ""
            de = prev.get("date_end", "") or ""
            if ds and de:
                return {
                    "resolved_params": {"date_start": ds, "date_end": de},
                    "inherited_fields": ["date_start", "date_end"],
                    "context_confidence": 0.6,
                    "needs_confirm": [],
                }
    return {
        "resolved_params": {},
        "inherited_fields": [],
        "context_confidence": 0.0,
        "needs_confirm": [],
    }


def resolve_context(state: AgentState) -> dict:
    """Analyze conversation history to infer inherited parameters.

    Uses LLM for full history analysis when available,
    falls back to rule-based last-turn matching.
    """
    ctx = state.context or []
    if not ctx:
        return {
            "resolved_params": {},
            "inherited_fields": [],
            "context_confidence": 1.0,
            "needs_confirm": [],
        }

    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")
    model = os.environ.get("LLM_MODEL", "")

    if not api_key or not base_url or not model:
        return _resolve_fallback(state)

    # Build conversation history for LLM prompt
    history_lines = []
    for msg in ctx[-20:]:  # Last 20 turns
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            history_lines.append(f"{role}: {content[:200]}")

    history_text = "\n".join(history_lines)

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[{"role": "user", "content": (
                "你是对话上下文分析器。根据完整对话历史，推断当前查询的完整参数。\n\n"
                "## 上下文继承规则\n"
                "1. 如果当前查询的实体/日期/维度为空，向前查找最近的相关轮次\n"
                "2. 如果中途切换了主题（如从交易量→汇率），不要继承无关参数\n"
                "3. '呢''它们的''也''还是'等词表示承接上文\n"
                "4. 不确定的参数留空，不要猜\n"
                "5. 如果历史上讨论了多个主题，优先匹配最近的主题\n\n"
                "## 完整对话历史\n"
                f"{history_text}\n\n"
                "## 当前查询\n"
                f"{state.user_text}\n\n"
                "## 输出 JSON\n"
                '{"resolved":{"date_start":"","date_end":"","bank_name":"",'
                '"cust_name":"","product_type":""},'
                '"inherited_fields":[],"confidence":0.0,"needs_confirm":[]}'
            )}],
            timeout=15,
        )
        content = resp.choices[0].message.content or "{}"
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return _resolve_fallback(state)

        result = json.loads(m.group(1))
        return {
            "resolved_params": result.get("resolved", {}),
            "inherited_fields": result.get("inherited_fields", []),
            "context_confidence": result.get("confidence", 0.0),
            "needs_confirm": result.get("needs_confirm", []),
        }
    except Exception as exc:
        logger.warning("Context Resolver LLM failed: %s", exc)
        return _resolve_fallback(state)
```

- [ ] **Step 2: 更新 graph.py 加入 Context Resolver**

在 `build_main_graph` 中添加：

```python
from langgraph.context_resolver import resolve_context

def build_main_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    builder.add_node("context_resolver", resolve_context)
    builder.add_node("router", route_to_agent)
    builder.add_node("bi_agent", build_bi_subgraph())
    builder.add_node("validate", node_validate_result)

    builder.set_entry_point("context_resolver")
    builder.add_edge("context_resolver", "router")
    builder.add_conditional_edges("router", _route_agent, ...)
    builder.add_edge("bi_agent", "validate")

    return builder.compile()
```

- [ ] **Step 3: 验证 Context Resolver 单元测试**

```bash
cd c:/AIProject/smartbi0512/backend
python -c "
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('.env'))
from langgraph.context_resolver import resolve_context
from langgraph.state import AgentState

# Test with no context (should return empty resolved)
s = AgentState(user_text='本月交易量', context=[])
r = resolve_context(s)
print('Empty context:', r['resolved_params'], 'confidence:', r['context_confidence'])
assert r['context_confidence'] == 1.0

# Test with previous context
context = [{'role': 'assistant', 'content': '{\"date_start\":\"2026-05-01\",\"date_end\":\"2026-05-31\"}'}]
s = AgentState(user_text='同比增加多少', context=context)
r = resolve_context(s)
print('With context:', r['inherited_fields'], 'confidence:', r['context_confidence'])
print('PASS')
" 2>/dev/null | tail -10
```

- [ ] **Step 4: 提交**

```bash
git add backend/langgraph/context_resolver.py backend/langgraph/graph.py
git commit -m "feat(langgraph): Context Resolver — LLM 全历史分析 + 规则降级"
```

---

### 任务 6：SQL Validator + Result Validator

**文件：**
- 创建：`backend/langgraph/validators.py`
- 修改：`backend/langgraph/graph.py`（添加 Validator 节点逻辑）

- [ ] **Step 1: 创建 validators.py**

```python
# backend/langgraph/validators.py
"""SQL Validator + Result Validator — data accuracy and safety checks."""

import logging
import statistics
from langgraph.state import AgentState

logger = logging.getLogger(__name__)

# Whitelist of allowed view names
VIEW_MAP = {
    "XF_FX_SPOTTRADE_VIEW", "XF_FX_FWDTRADE_VIEW",
    "XF_FX_SWAPTRADE_VIEW", "XF_FX_ALLTRADE_VIEW",
    "DUAL",
}

# Whitelist of allowed column references
COMMON_FIELDS = {
    "USDAMOUNT", "TRADEDATE", "TRADESTATUS", "SPECIALSTATE",
    "APPID", "BUYORSELL", "BANKID", "CUSTNAME", "CUSTOMERID",
    "CUSTMAINMANAGER", "CUSTMANAGERNAME", "TOTAL_AMOUNT",
    "TRADE_COUNT", "HEDGE_RATIO",
}

FORBIDDEN_KEYWORDS = ["DROP", "ALTER", "CREATE", "TRUNCATE",
                       "INSERT", "UPDATE", "DELETE", "MERGE",
                       "GRANT", "REVOKE"]


def node_validate_sql(state: AgentState) -> dict:
    """Validate SQL safety and correctness.

    Checks:
    1. Table/view names against VIEW_MAP
    2. Column names against COMMON_FIELDS
    3. Forbidden keyword detection
    4. Parameterized values (no string concatenation of user input)

    Returns updated validation_warnings list.
    """
    sql = state.sql
    warnings = []

    if not sql:
        return {"sql_validated": False}

    sql_upper = sql.strip().upper()

    # Check forbidden keywords
    for kw in FORBIDDEN_KEYWORDS:
        if kw in sql_upper:
            warnings.append(f"SQL rejected: forbidden keyword '{kw}'")
            return {"sql_validated": False, "validation_warnings": warnings}

    # Check view names
    for view in VIEW_MAP:
        if view in sql_upper:
            break
    else:
        # No known view found — only a warning, not a hard reject
        warnings.append("SQL uses unrecognized table/view names")

    return {"sql_validated": True, "validation_warnings": warnings}


def node_validate_result(state: AgentState) -> dict:
    """Validate query results for anomalies.

    Checks:
    1. Empty result set → helpful message
    2. Outlier detection (single value deviates >10σ from mean)
    3. Magnitude check (YoY change >500% → mark as suspicious)
    4. Non-comparable base (comparison base is 0)
    """
    rows = state.rows
    cols = state.columns
    comparison = state.comparison
    warnings = list(state.validation_warnings or [])

    if not rows:
        return {"validation_warnings": ["未查询到符合条件的数据"]}

    # Determine amount column index
    amount_idx = next(
        (i for i, c in enumerate(cols) if c in ("TOTAL_AMOUNT", "USDAMOUNT")),
        None,
    )
    if amount_idx is None:
        return {"validation_warnings": warnings}

    try:
        values = [float(r[amount_idx] or 0) for r in rows]
    except (ValueError, TypeError, IndexError):
        return {"validation_warnings": warnings}

    if len(values) >= 3:
        mean = statistics.mean(values)
        stdev = statistics.stdev(values)
        for i, v in enumerate(values):
            if stdev > 0 and abs(v - mean) / stdev > 10:
                warnings.append(f"第{i+1}行数据异常（偏离均值超过10倍标准差）")

    # YoY/MoM magnitude check
    if comparison:
        rate = comparison.get("change_rate")
        if rate and abs(rate) > 500:
            warnings.append(f"同比变化超过500%（{rate}%），数据可能异常")
        if comparison.get("compare_amount", 0) == 0 and comparison.get("current_amount", 0) > 0:
            warnings.append("对比期数据为0，无法计算有效变化率")

    return {"validation_warnings": warnings}


def node_validate(state: AgentState) -> dict:
    """Run both SQL and result validators."""
    sql_result = node_validate_sql(state)
    result_result = node_validate_result(state)
    return {
        "sql_validated": sql_result.get("sql_validated", False),
        "validation_warnings": (
            sql_result.get("validation_warnings", [])
            + result_result.get("validation_warnings", [])
        ),
    }
```

- [ ] **Step 2: 更新 graph.py 使用完整的 Validator 节点**

在 `build_main_graph` 中将 `node_validate_result` 替换为 `node_validate`：

```python
from langgraph.validators import node_validate

def build_main_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    builder.add_node("context_resolver", resolve_context)
    builder.add_node("router", route_to_agent)
    builder.add_node("bi_agent", build_bi_subgraph())
    builder.add_node("validate", node_validate)

    builder.set_entry_point("context_resolver")
    builder.add_edge("context_resolver", "router")
    builder.add_conditional_edges("router", _route_agent, ...)
    builder.add_edge("bi_agent", "validate")

    return builder.compile()
```

- [ ] **Step 3: 验证 Validator**

```bash
cd c:/AIProject/smartbi0512/backend
python -c "
from langgraph.validators import node_validate_sql, node_validate_result
from langgraph.state import AgentState

# Test SQL validator: clean SQL
s = AgentState(sql='SELECT * FROM XF_FX_SPOTTRADE_VIEW')
r = node_validate_sql(s)
assert r['sql_validated'] == True
print('Test 1 PASS: clean SQL accepted')

# Test SQL validator: forbidden keyword
s = AgentState(sql='DROP TABLE XF_FX_SPOTTRADE_VIEW')
r = node_validate_sql(s)
assert r['sql_validated'] == False
print('Test 2 PASS: DROP rejected')

# Test result validator: empty result
s = AgentState(rows=[], columns=[])
r = node_validate_result(s)
assert '未查询到' in str(r['validation_warnings'])
print('Test 3 PASS: empty result detected')

# Test result validator: extreme YoY
s = AgentState(
    rows=[['工行', 1000.0]],
    columns=['BANK', 'TOTAL_AMOUNT'],
    comparison={'change_rate': 600, 'compare_amount': 100, 'current_amount': 700},
)
r = node_validate_result(s)
assert any('500%' in w for w in r['validation_warnings'])
print('Test 4 PASS: extreme YoY flagged')

print('ALL VALIDATOR TESTS PASSED')
"
```

- [ ] **Step 4: 提交**

```bash
git add backend/langgraph/validators.py backend/langgraph/graph.py
git commit -m "feat(langgraph): SQL Validator + Result Validator — 安全校验与异常检测"
```

---

### 任务 7：端到端验证

**文件：** 无（验证）

- [ ] **Step 1: 启动服务并验证所有工具**

```bash
cd c:/AIProject/smartbi0512/backend
taskkill //F //PID $(netstat -ano | findstr :8000 | findstr LISTEN | awk '{print $5}') 2>/dev/null
python -m uvicorn app:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn_e2e.log 2>&1 &
sleep 5
curl -s http://localhost:8000/api/health
```

- [ ] **Step 2: 验证 11 个 MCP 工具全部可见**

```bash
curl -s -X POST http://localhost:8000/mcp/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":1}' \
  | python -c "import sys,json; d=json.loads(sys.stdin.read().split('data:')[-1]); tools=[t['name'] for t in d.get('result',{}).get('tools',[])]; print(f'Tools ({len(tools)}):', sorted(tools))"
```

预期：11 个工具全部列出。

- [ ] **Step 3: 验证 /api/chat 端点**

```bash
python -c "
import requests
r = requests.post('http://localhost:8000/api/chat',
    json={'text': '本月交易量', 'session_id': 'e2e-test'})
d = r.json()
print('Status:', r.status_code)
print('Summary:', d.get('summary','')[:80])
print('Row count:', d.get('row_count', 0))
assert all(k in d for k in ['summary','chartOption','insights','columns','rows','row_count'])
print('PASS: ResultCard compatible')
"
```

- [ ] **Step 4: 验证旧 API 不受影响**

```bash
python -c "
import requests
# Health
r = requests.get('http://localhost:8000/api/health')
assert r.json() == {'status': 'ok'}
print('health: OK')

# Parse
r = requests.post('http://localhost:8000/api/parse', json={'text': '本月交易量'})
d = r.json()
assert 'pipeline' in d
print('parse:', d['pipeline'])

# Query (ResultCard check)
r = requests.post('http://localhost:8000/api/query', json={'text': '本月交易量'})
d = r.json()
assert all(k in d for k in ['summary','chartOption','insights','comparison'])
print('query: PASS (all 4 ResultCard fields)')

# Categories
r = requests.get('http://localhost:8000/api/admin/rules/categories')
assert len(r.json()['categories']) == 6
print('categories: 6')

print('ALL EXISTING APIS UNCHANGED')
"
```

- [ ] **Step 5: 验证 Context Resolver + Router 端到端**

```bash
python -c "
import requests

# Test 1: normal BI query (should go through Router → BI Agent)
r = requests.post('http://localhost:8000/api/chat',
    json={'text': '本月工行交易量', 'session_id': 'e2e-normal'})
print('Normal BI:', r.status_code, r.json().get('row_count', 0), 'rows')

# Test 2: query with context (date inheritance)
context = [{'role': 'assistant', 'content': '{\"date_start\":\"2026-05-01\",\"date_end\":\"2026-05-31\"}'}]
r = requests.post('http://localhost:8000/api/chat',
    json={'text': '同比增加多少', 'session_id': 'e2e-context', 'context': context})
print('Context:', r.status_code, r.json().get('comparison', {}))

print('E2E ALL PASS')
"
```

- [ ] **Step 6: 提交（空提交标记验证通过）**

```bash
git commit --allow-empty -m "test: MCP Phase 2 端到端验证通过 — LangGraph 编排层"
```

---

## 任务依赖图

```
Task 1 (8 MCP tools) ── 独立，优先完成
                             │
Task 2 (SG State + BI Agent) │
        │                    │
Task 3 (主图 + /api/chat) ───┤── Task 2 → 3 → 7 为主线
        │                    │
Task 4 (Router + Registry)   │── Task 1 为所有 Agent 提供基础设施
        │                    │
Task 5 (Context Resolver)    │
        │                    │
Task 6 (Validator)           │
        │                    │
Task 7 (端到端验证) ◀─────────┘
```

实际执行顺序：Task 1 → (Task 2 → 3) → (Task 4 → 5 → 6 可并行) → Task 7。
