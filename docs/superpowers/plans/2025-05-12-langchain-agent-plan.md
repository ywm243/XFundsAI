# LangChain Agent 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在现有 Smart BI 架构上构建 LangGraph Agent 层，Agent 负责意图理解和编排，SQL 生成锁死在 TradeQueryBuilder 中。

**架构：** LangGraph Agent（agent_parse → reflect → route_sql → execute → verify → learn）+ 4 个安全工具 + visualization 模块。所有 SQL 通过确定性路由节点生成，LLM 不参与 SQL 构建。

**技术栈：** Python 3.13 + LangChain 1.2 + LangGraph 1.1 + FastAPI + ECharts

---

## 文件结构

### 创建的文件
- `backend/sql_engine/state.py` — AgentState TypedDict
- `backend/sql_engine/tools.py` — 4 个 LangChain 工具（parse_query, execute_sql, compute_comparison, generate_chart）
- `backend/sql_engine/nodes.py` — Graph 节点（agent_parse, reflect, route_sql, execute, verify, chart_compare, learn）
- `backend/sql_engine/memory.py` — AgentMemory 交互模式存储
- `backend/sql_engine/agent.py` — Graph 构建和编译入口
- `backend/visualization/__init__.py` — 包初始化
- `backend/visualization/chart_detector.py` — 图表类型自动判定规则
- `backend/visualization/echarts_builder.py` — ECharts Option 构建器
- `backend/tests/__init__.py` — 测试包初始化
- `backend/tests/test_sql_engine.py` — sql_engine 测试
- `backend/tests/test_visualization.py` — visualization 测试

### 修改的文件
- `backend/app.py` — 新增 `/api/agent/query` 端点和 agent 初始化

---

### 任务 1：AgentState 定义

**文件：**
- 创建：`backend/sql_engine/__init__.py`
- 创建：`backend/sql_engine/state.py`

- [ ] **步骤 1：创建 sql_engine 包和 state.py**

创建 `backend/sql_engine/__init__.py`：
```python
```

创建 `backend/sql_engine/state.py`：
```python
"""LangGraph Agent state definition."""

from typing import TypedDict, Optional


class AgentState(TypedDict):
    """State passed through the LangGraph agent pipeline."""
    query_text: str
    pre_parsed_params: Optional[dict]
    messages: list
    validated_params: Optional[dict]
    pipeline: str
    sql: Optional[str]
    columns: list[str]
    rows: list[list]
    row_count: int
    comparison: Optional[dict]
    visualization: Optional[dict]
    retry_count: int
    error: Optional[str]
```

- [ ] **步骤 2：Commit**

```bash
git add backend/sql_engine/__init__.py backend/sql_engine/state.py
git commit -m "feat: add AgentState type definition"
```

---

### 任务 2：AgentMemory — 交互模式存储

**文件：**
- 创建：`backend/sql_engine/memory.py`

- [ ] **步骤 1：创建 AgentMemory**

```python
"""Agent interaction memory — pattern store for query history."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"
_MEMORY_FILE = _MEMORY_DIR / "agent_patterns.json"


class AgentMemory:
    """Record and retrieve query patterns for agent learning.
    
    Stores normalized query → params mappings to help the agent
    make faster, more accurate decisions on repeated query types.
    """

    def __init__(self):
        self._patterns: list[dict] = []
        self._load()

    def _load(self):
        if _MEMORY_FILE.exists():
            try:
                with open(_MEMORY_FILE, "r", encoding="utf-8") as f:
                    self._patterns = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load agent patterns: %s", exc)
                self._patterns = []

    def _save(self):
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        # Keep only last 500 entries
        self._patterns = self._patterns[-500:]
        with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self._patterns, f, ensure_ascii=False, indent=2)

    def record(self, query_text: str, params: dict, success: bool,
               row_count: int = 0, error: Optional[str] = None):
        """Record a query interaction pattern."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "query": query_text,
            "params": params,
            "success": success,
            "row_count": row_count,
            "error": error,
        }
        self._patterns.append(entry)
        self._save()
        logger.debug("Recorded interaction: success=%s rows=%d", success, row_count)

    def find_similar(self, query_text: str, top_k: int = 3) -> list[dict]:
        """Find similar past queries by simple keyword overlap."""
        if not self._patterns:
            return []
        query_words = set(query_text.lower().split())
        scored = []
        for p in self._patterns:
            pw = set(p.get("query", "").lower().split())
            overlap = len(query_words & pw)
            if overlap > 0:
                scored.append((overlap, p))
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored[:top_k]]
```

- [ ] **步骤 2：Commit**

```bash
git add backend/sql_engine/memory.py
git commit -m "feat: add AgentMemory pattern store"
```

---

### 任务 3：LangChain Tools — 4 个安全工具

**文件：**
- 创建：`backend/sql_engine/tools.py`

- [ ] **步骤 1：创建 tools.py**

```python
"""LangChain tools for the FX trade query agent.

Each tool wraps an existing module — Agent cannot bypass rule engine or
generate SQL directly.
"""

import json
import logging
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from ..llm_parser.llm_client import llm_parse
from ..llm_parser.prompt_builder import build_system_prompt
from ..llm_parser.rules_engine import gatekeep
from ..llm_parser.parser import rule_based_parse, compute_comparison_dates
from ..db.connection import get_db
from .state import AgentState

logger = logging.getLogger(__name__)

# ── Input schemas ──────────────────────────────────────────

class ParseQueryInput(BaseModel):
    text: str = Field(description="Natural language query text")

class ExecuteSqlInput(BaseModel):
    sql: str = Field(description="SQL to execute")
    params: dict = Field(default_factory=dict, description="Original params for context")

class ComputeComparisonInput(BaseModel):
    params: dict = Field(description="Query parameters with date_start/date_end")
    sql: str = Field(description="Original SQL")
    rows: list = Field(description="Current query result rows")
    comparison_type: str = Field(description="'yoy' or 'mom'")

class GenerateChartInput(BaseModel):
    columns: list[str] = Field(description="Column names from query result")
    rows: list = Field(description="Data rows")
    query_text: str = Field(description="Original user query for context")

# ── Tools ──────────────────────────────────────────────────

class ParseQueryTool(BaseTool):
    name: str = "parse_query"
    description: str = (
        "Parse a natural language FX trading query into structured parameters. "
        "Returns validated params. Use this first to understand the user's query."
    )
    args_schema: Type[BaseModel] = ParseQueryInput

    def _run(self, text: str) -> dict:
        system_prompt = build_system_prompt()
        llm_result = llm_parse(text, system_prompt)
        if llm_result is not None:
            parsed = gatekeep(llm_result, text)
            logger.info("ParseQueryTool: LLM+gatekeep pipeline used")
        else:
            parsed = rule_based_parse(text)
            logger.info("ParseQueryTool: fallback rule_based_parse used")
        return parsed


class ExecuteSqlTool(BaseTool):
    name: str = "execute_sql"
    description: str = (
        "Execute a SQL query against the Oracle database and return results. "
        "Input must be a valid SQL string from route_sql."
    )
    args_schema: Type[BaseModel] = ExecuteSqlInput

    def _run(self, sql: str, params: dict = None) -> dict:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                cols = [desc[0] for desc in cur.description] if cur.description else []
                rows = [list(row) for row in cur.fetchall()]
        return {
            "columns": cols,
            "rows": rows,
            "row_count": len(rows),
        }


class ComputeComparisonTool(BaseTool):
    name: str = "compute_comparison"
    description: str = (
        "Compute YoY (同比) or MoM (环比) comparison data "
        "by running the same query against a shifted date range."
    )
    args_schema: Type[BaseModel] = ComputeComparisonInput

    @staticmethod
    def _build_comparison_sql(parsed: dict, date_start: str, date_end: str) -> str:
        """Rebuild SQL from parsed params with shifted dates."""
        from ..db.query_builder import TradeQueryBuilder

        buy_sell = parsed.get("buy_sell") or None
        cust_name = parsed.get("cust_name") or None
        special_states = parsed.get("special_states")
        if isinstance(special_states, str) and special_states:
            special_states = [s.strip() for s in special_states.split(",")]
        else:
            special_states = None
        amount_filter = parsed.get("amount_filter")
        top_n = parsed.get("top_n")

        if amount_filter:
            return TradeQueryBuilder.build_filtered_query(
                product_type=parsed["product_type"],
                date_start=date_start, date_end=date_end,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                amount_op=amount_filter["amount_op"],
                amount_value=amount_filter["amount_value"],
                hedge_ratio=parsed.get("hedge_ratio", False),
                dimension=parsed.get("dimension", "bank"),
                cust_name=cust_name, appid=parsed.get("appid"),
            )
        elif top_n and top_n > 0:
            return TradeQueryBuilder.build_ranking_query(
                product_type=parsed["product_type"],
                date_start=date_start, date_end=date_end,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None, top_n=top_n,
                dimension=parsed.get("dimension", "bank"),
                hedge_ratio=parsed.get("hedge_ratio", False),
                cust_name=cust_name, appid=parsed.get("appid"),
            )
        elif parsed.get("hedge_ratio"):
            return TradeQueryBuilder.build_hedge_ratio_query(
                product_type=parsed["product_type"],
                date_start=date_start, date_end=date_end,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                dimension=parsed.get("dimension", "bank"),
                cust_name=cust_name, appid=parsed.get("appid"),
            )
        elif parsed.get("aggregate"):
            return TradeQueryBuilder.build_aggregate_query(
                product_type=parsed["product_type"],
                date_start=date_start, date_end=date_end,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                cust_name=cust_name, appid=parsed.get("appid"),
                dimension=parsed.get("dimension"),
            )
        else:
            return TradeQueryBuilder.build_query(
                product_type=parsed["product_type"],
                date_start=date_start, date_end=date_end,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                cust_name=cust_name, appid=parsed.get("appid"),
            )

    def _compute(self, current_rows, compare_rows, comparison,
                 date_start, date_end, cmp_start, cmp_end):
        """Compute change_amount and change_rate."""
        if not current_rows or not compare_rows:
            return None
        current_row, compare_row = current_rows[0], compare_rows[0]
        try:
            if len(current_row) >= 2:
                amt_idx = 1
                current_amt = float(current_row[amt_idx]) if current_row[amt_idx] is not None else 0
                compare_amt = float(compare_row[amt_idx]) if compare_row[amt_idx] is not None else 0
            else:
                current_amt = float(current_row[0]) if current_row[0] is not None else 0
                compare_amt = float(compare_row[0]) if compare_row[0] is not None else 0
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

    def _run(self, params: dict, sql: str, rows: list, comparison_type: str) -> Optional[dict]:
        ds, de = params.get("date_start", ""), params.get("date_end", "")
        cmp_start, cmp_end = compute_comparison_dates(ds, de, comparison_type)
        if not cmp_start or not cmp_end:
            return None

        cmp_sql = self._build_comparison_sql(params, cmp_start, cmp_end)
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(cmp_sql)
                    cmp_rows = [list(row) for row in cur.fetchall()]
            if cmp_rows:
                return self._compute(rows, cmp_rows, comparison_type, ds, de, cmp_start, cmp_end)
        except Exception as exc:
            logger.warning("Comparison query failed: %s", exc)
        return None


class GenerateChartTool(BaseTool):
    name: str = "generate_chart"
    description: str = (
        "Generate an ECharts visualization configuration from query results. "
        "Automatically detects the best chart type based on data shape and query intent."
    )
    args_schema: Type[BaseModel] = GenerateChartInput

    def _run(self, columns: list[str], rows: list, query_text: str) -> Optional[dict]:
        from ..visualization.chart_detector import detect_chart_type
        from ..visualization.echarts_builder import EchartsBuilder

        if not rows or not columns:
            return None

        chart_type = detect_chart_type(columns, query_text, len(rows))
        if chart_type == "none":
            return None

        title = query_text[:50] + ("..." if len(query_text) > 50 else "")
        option = EchartsBuilder.build_option(columns, rows, chart_type, title)
        return {
            "type": chart_type,
            "option": option,
        }


# ── Tool registry ──────────────────────────────────────────

AGENT_TOOLS = [
    ParseQueryTool(),
    ExecuteSqlTool(),
    ComputeComparisonTool(),
    GenerateChartTool(),
]
```

- [ ] **步骤 2：Commit**

```bash
git add backend/sql_engine/tools.py
git commit -m "feat: add 4 LangChain agent tools"
```

---

### 任务 4：Graph 节点

**文件：**
- 创建：`backend/sql_engine/nodes.py`

- [ ] **步骤 1：创建 nodes.py**

```python
"""LangGraph agent nodes for the FX trade query pipeline."""

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.prebuilt import ToolExecutor

from ..db.query_builder import TradeQueryBuilder
from .state import AgentState
from .tools import AGENT_TOOLS
from .memory import AgentMemory

logger = logging.getLogger(__name__)

# Shared instances
_tool_executor = ToolExecutor(AGENT_TOOLS)
_memory = AgentMemory()


def _normalize_special_states(parsed: dict) -> list | None:
    special_states = parsed.get("special_states")
    if isinstance(special_states, str) and special_states:
        return [s.strip() for s in special_states.split(",")]
    return None


def _call_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return a string representation of the result."""
    result = _tool_executor.invoke({"name": tool_name, "input": tool_input})
    return str(result)


# ── Nodes ──────────────────────────────────────────────────

def agent_parse(state: AgentState) -> AgentState:
    """ReAct node: think → call parse_query → observe result."""
    messages = state.get("messages", [])

    # If pre-validated params provided from frontend, skip parsing
    if state.get("pre_parsed_params"):
        state["validated_params"] = state["pre_parsed_params"]
        state["pipeline"] = "direct"
        state["messages"] = messages + [
            AIMessage(content="Using pre-validated params from frontend.")
        ]
        return state

    query = state["query_text"]
    logger.info("agent_parse: parsing query '%s'", query)

    # Add user message if not already added
    if not messages or not any(isinstance(m, HumanMessage) for m in messages):
        messages.append(HumanMessage(content=query))

    # Call parse_query tool
    try:
        result_str = _call_tool("parse_query", {"text": query})
        parsed = eval(result_str) if isinstance(result_str, str) and result_str.startswith("{") else {}
        state["validated_params"] = parsed
        state["pipeline"] = "agent"
        messages.append(AIMessage(content=f"Parsed params: {parsed}"))
    except Exception as exc:
        logger.exception("agent_parse failed")
        state["error"] = f"Parse failed: {exc}"

    state["messages"] = messages
    return state


def reflect_node(state: AgentState) -> AgentState:
    """Check parsed params for consistency and completeness.
    
    If validation fails, sets error and the graph routes back to agent_parse.
    """
    params = state.get("validated_params")
    if not params:
        state["error"] = "No validated params to check"
        return state

    errors = []

    # Check 1: product_type is valid
    valid_types = {"all", "spot", "fwd", "swap"}
    pt = params.get("product_type")
    if pt not in valid_types:
        errors.append(f"Invalid product_type: {pt}")

    # Check 2: date range (if both provided)
    ds, de = params.get("date_start", ""), params.get("date_end", "")
    if ds and de and ds > de:
        errors.append(f"date_start ({ds}) > date_end ({de})")

    # Check 3: cust_name and bank_name are mutually exclusive
    if params.get("cust_name") and params.get("bank_name"):
        params["bank_name"] = ""
        logger.info("reflect: cleared bank_name because cust_name is set")

    # Check 4: buy_sell value
    bs = params.get("buy_sell")
    if bs and bs not in ("B", "S", ""):
        errors.append(f"Invalid buy_sell: {bs}")

    # Check 5: dimension is valid
    valid_dims = {"bank", "customer", "customer_id", "manager", "manager_name"}
    dim = params.get("dimension", "bank")
    if dim not in valid_dims:
        params["dimension"] = "bank"

    if errors:
        state["error"] = "; ".join(errors)
        logger.warning("reflect_node: %s", state["error"])
    else:
        logger.info("reflect_node: all checks passed")

    return state


def route_sql_node(state: AgentState) -> AgentState:
    """Deterministic SQL routing — no LLM involvement.
    
    This node is the core accuracy guarantee: SQL is built by TradeQueryBuilder
    only, using validated params from the rule engine.
    """
    params = state.get("validated_params")
    if not params:
        state["error"] = "No params available for SQL routing"
        return state

    if state.get("error"):
        return state  # Don't proceed if reflect already found errors

    buy_sell = params.get("buy_sell") or None
    cust_name = params.get("cust_name") or None
    special_states = _normalize_special_states(params)
    amount_filter = params.get("amount_filter")
    top_n = params.get("top_n")

    try:
        if amount_filter:
            sql = TradeQueryBuilder.build_filtered_query(
                product_type=params["product_type"],
                date_start=params.get("date_start") or None,
                date_end=params.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=params.get("bank_name") or None,
                amount_op=amount_filter["amount_op"],
                amount_value=amount_filter["amount_value"],
                hedge_ratio=params.get("hedge_ratio", False),
                dimension=params.get("dimension", "bank"),
                cust_name=cust_name, appid=params.get("appid"),
            )
        elif top_n and top_n > 0:
            sql = TradeQueryBuilder.build_ranking_query(
                product_type=params["product_type"],
                date_start=params.get("date_start") or None,
                date_end=params.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=params.get("bank_name") or None, top_n=top_n,
                dimension=params.get("dimension", "bank"),
                hedge_ratio=params.get("hedge_ratio", False),
                cust_name=cust_name, appid=params.get("appid"),
            )
        elif params.get("hedge_ratio"):
            sql = TradeQueryBuilder.build_hedge_ratio_query(
                product_type=params["product_type"],
                date_start=params.get("date_start") or None,
                date_end=params.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=params.get("bank_name") or None,
                dimension=params.get("dimension", "bank"),
                cust_name=cust_name, appid=params.get("appid"),
            )
        elif params.get("aggregate"):
            sql = TradeQueryBuilder.build_aggregate_query(
                product_type=params["product_type"],
                date_start=params.get("date_start") or None,
                date_end=params.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=params.get("bank_name") or None,
                cust_name=cust_name, appid=params.get("appid"),
                dimension=params.get("dimension"),
            )
        else:
            sql = TradeQueryBuilder.build_query(
                product_type=params["product_type"],
                date_start=params.get("date_start") or None,
                date_end=params.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=params.get("bank_name") or None,
                cust_name=cust_name, appid=params.get("appid"),
            )

        state["sql"] = sql
        logger.info("route_sql: SQL built successfully")
    except Exception as exc:
        state["error"] = f"SQL build failed: {exc}"
        logger.exception("route_sql failed")

    return state


def agent_execute(state: AgentState) -> AgentState:
    """Execute the SQL using the execute_sql tool."""
    sql = state.get("sql")
    if not sql or state.get("error"):
        return state

    logger.info("agent_execute: running SQL")
    try:
        result_str = _call_tool("execute_sql", {"sql": sql, "params": state.get("validated_params", {})})
        result = eval(result_str) if isinstance(result_str, str) and "columns" in result_str else {}
        state["columns"] = result.get("columns", [])
        state["rows"] = result.get("rows", [])
        state["row_count"] = result.get("row_count", 0)
    except Exception as exc:
        state["error"] = f"Execute failed: {exc}"
        logger.exception("agent_execute failed")

    return state


def verify_node(state: AgentState) -> AgentState:
    """Backtesting: validate query results for reasonableness."""
    if state.get("error"):
        return state

    rows = state.get("rows", [])
    params = state.get("validated_params", {})
    warnings = []

    # Check 1: rows are empty but query expected data
    if not rows:
        if params.get("date_start") or params.get("date_end"):
            warnings.append("Query returned no results for the specified date range")
    else:
        # Check 2: first numeric column (TOTAL_AMOUNT) seems reasonable
        try:
            if len(rows[0]) >= 2:
                first_val = float(rows[0][1]) if rows[0][1] is not None else 0
                if first_val < 0:
                    warnings.append(f"Negative amount detected: {first_val}")
        except (ValueError, IndexError, TypeError):
            pass

    if warnings:
        logger.warning("verify_node: %s", "; ".join(warnings))
        # Don't set error for warnings, just log them
        state["error_notes"] = warnings

    logger.info("verify_node: validation complete (%d rows)", len(rows))
    return state


def chart_compare_node(state: AgentState) -> AgentState:
    """Generate chart and/or comparison data."""
    if state.get("error"):
        return state

    params = state.get("validated_params", {})
    rows = state.get("rows", [])
    columns = state.get("columns", [])
    query = state.get("query_text", "")

    # Comparison (同比/环比)
    comparison_type = params.get("comparison")
    if comparison_type and rows:
        try:
            cmp_input = {
                "params": params,
                "sql": state["sql"],
                "rows": rows,
                "comparison_type": comparison_type,
            }
            cmp_str = _call_tool("compute_comparison", cmp_input)
            state["comparison"] = eval(cmp_str) if cmp_str and cmp_str != "None" else None
        except Exception as exc:
            logger.warning("chart_compare_node: comparison failed: %s", exc)

    # Chart generation
    try:
        chart_input = {
            "columns": columns,
            "rows": rows,
            "query_text": query,
        }
        chart_str = _call_tool("generate_chart", chart_input)
        state["visualization"] = eval(chart_str) if chart_str and chart_str != "None" else None
    except Exception as exc:
        logger.warning("chart_compare_node: chart failed: %s", exc)

    return state


def learn_node(state: AgentState) -> AgentState:
    """Record interaction pattern to memory."""
    params = state.get("validated_params", {})
    row_count = state.get("row_count", 0)

    _memory.record(
        query_text=state.get("query_text", ""),
        params=params,
        success=not state.get("error"),
        row_count=row_count,
        error=state.get("error"),
    )

    return state


def should_retry(state: AgentState) -> Literal["agent_parse", "route_sql_node"]:
    """Conditional edge: retry on error, otherwise continue."""
    if state.get("error") and state.get("retry_count", 0) < 3:
        state["retry_count"] = state.get("retry_count", 0) + 1
        state["error"] = None  # Clear error for retry
        return "agent_parse"
    return "route_sql_node"


def after_reflect(state: AgentState) -> Literal["route_sql_node", "agent_parse"]:
    """After reflect: if error found, go back for retry."""
    if state.get("error") and state.get("retry_count", 0) < 3:
        state["retry_count"] = state.get("retry_count", 0) + 1
        state["error"] = None
        return "agent_parse"
    return "route_sql_node"
```

- [ ] **步骤 2：Commit**

```bash
git add backend/sql_engine/nodes.py
git commit -m "feat: add all LangGraph agent nodes"
```

---

### 任务 5：Agent Graph 构建入口

**文件：**
- 创建：`backend/sql_engine/agent.py`

- [ ] **步骤 1：创建 agent.py**

```python
"""LangGraph agent graph build and compile."""

import logging

from langgraph.graph import StateGraph, END

from .state import AgentState
from .nodes import (
    agent_parse, reflect_node, route_sql_node,
    agent_execute, verify_node, chart_compare_node, learn_node,
    after_reflect,
)

logger = logging.getLogger(__name__)


def build_agent() -> StateGraph:
    """Build the LangGraph agent graph."""
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("agent_parse", agent_parse)
    workflow.add_node("reflect_node", reflect_node)
    workflow.add_node("route_sql_node", route_sql_node)
    workflow.add_node("agent_execute", agent_execute)
    workflow.add_node("verify_node", verify_node)
    workflow.add_node("chart_compare_node", chart_compare_node)
    workflow.add_node("learn_node", learn_node)

    # Set entry point
    workflow.set_entry_point("agent_parse")

    # Add edges
    workflow.add_edge("agent_parse", "reflect_node")
    workflow.add_conditional_edges(
        "reflect_node",
        after_reflect,
        {"route_sql_node": "route_sql_node", "agent_parse": "agent_parse"},
    )
    workflow.add_edge("route_sql_node", "agent_execute")
    workflow.add_edge("agent_execute", "verify_node")
    workflow.add_edge("verify_node", "chart_compare_node")
    workflow.add_edge("chart_compare_node", "learn_node")
    workflow.add_edge("learn_node", END)

    # Compile
    agent = workflow.compile()
    logger.info("LangGraph agent compiled successfully")
    return agent


# Global instance
agent_graph = build_agent()
```

- [ ] **步骤 2：Commit**

```bash
git add backend/sql_engine/agent.py
git commit -m "feat: add LangGraph agent graph build"
```

---

### 任务 6：Visualization 模块

**文件：**
- 创建：`backend/visualization/__init__.py`
- 创建：`backend/visualization/chart_detector.py`
- 创建：`backend/visualization/echarts_builder.py`

- [ ] **步骤 1：创建 __init__.py**

```python
```

- [ ] **步骤 2：创建 chart_detector.py**

```python
"""Chart type detection — rule-based, no LLM involved."""


def detect_chart_type(columns: list[str], query_text: str, row_count: int) -> str:
    """Determine the best ECharts chart type based on query context and data shape.

    Returns one of: 'bar', 'line', 'pie', 'comparison_bar', 'none'
    """
    text = query_text.lower()

    # Comparison (同比/环比) → grouped bar
    if "同比" in text or "环比" in text or "比较" in text or "对比" in text:
        return "comparison_bar"

    # 排名/排行/Top → horizontal bar
    if any(kw in text for kw in ["排名", "排行", "top", "前"]):
        return "bar"

    # 套保率 → bar
    if "套保率" in text:
        return "bar"

    # 占比 → pie
    if "占比" in text or "比例" in text or "分布" in text:
        return "pie"

    # 趋势/变化/走势 → line
    if any(kw in text for kw in ["趋势", "变化", "走势", "逐月", "逐日"]):
        return "line"

    # Aggregate with dimension and few rows → pie
    if row_count <= 8:
        return "pie"

    # Aggregate with many rows → bar
    if row_count > 0:
        return "bar"

    return "none"
```

- [ ] **步骤 3：创建 echarts_builder.py**

```python
"""Build ECharts option dictionaries from query results."""


def _dimension_column(columns: list[str]) -> int:
    """Find the dimension (label) column index (first non-numeric-like column)."""
    # The first column is typically the dimension/group label
    return 0


def _value_columns(columns: list[str]) -> list[tuple[int, str]]:
    """Find numeric value columns."""
    value_keywords = ["amount", "count", "ratio", "rate", "volume"]
    result = []
    for i, col in enumerate(columns):
        col_upper = col.upper()
        if any(kw in col_upper for kw in ["AMOUNT", "COUNT", "RATIO", "RATE", "TOTAL"]):
            result.append((i, col))
    # Fallback: second column is typically the value
    if not result and len(columns) >= 2:
        result.append((1, columns[1]))
    return result


class EchartsBuilder:

    @staticmethod
    def build_option(columns: list[str], rows: list[list],
                     chart_type: str, title: str) -> dict:
        """Build an ECharts option dict.

        Args:
            columns: Column names from query result.
            rows: Data rows (list of lists).
            chart_type: One of 'bar', 'line', 'pie', 'comparison_bar'.
            title: Chart title.
        """
        dim_idx = _dimension_column(columns)
        val_cols = _value_columns(columns)

        if not val_cols:
            return {"title": {"text": title}, "tooltip": {}}

        labels = [str(row[dim_idx]) if row[dim_idx] is not None else "" for row in rows]
        val_idx, val_name = val_cols[0]
        values = []
        for row in rows:
            try:
                v = float(row[val_idx]) if row[val_idx] is not None else 0
            except (ValueError, TypeError):
                v = 0
            values.append(round(v, 2))

        option = {
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "axis" if chart_type != "pie" else "item"},
            "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        }

        if chart_type == "pie":
            option["series"] = [{
                "type": "pie",
                "radius": ["0", "60%"],
                "data": [{"name": labels[i], "value": values[i]} for i in range(len(labels))],
                "label": {"show": True, "formatter": "{b}: {c}"},
            }]
        elif chart_type == "comparison_bar":
            # For comparison, use grouped bar with two series
            name_map = {"BAR": "Current"}
            option["xAxis"] = {"type": "category", "data": labels}
            option["yAxis"] = {"type": "value", "name": val_name}
            option["series"] = [{
                "name": val_name,
                "type": "bar",
                "data": values,
            }]
        else:
            # bar or line
            option["xAxis"] = {
                "type": "category",
                "data": labels,
                "axisLabel": {"rotate": 45 if len(labels) > 8 else 0},
            }
            option["yAxis"] = {"type": "value", "name": val_name}
            option["series"] = [{
                "name": val_name,
                "type": chart_type,
                "data": values,
                "itemStyle": {
                    "color": {"type": "palette", "key": "blue"}
                },
            }]

        return option
```

- [ ] **步骤 4：Commit**

```bash
git add backend/visualization/__init__.py backend/visualization/chart_detector.py backend/visualization/echarts_builder.py
git commit -m "feat: add visualization module with chart detection and ECharts builder"
```

---

### 任务 7：集成到 app.py

**文件：**
- 修改：`backend/app.py`

- [ ] **步骤 1：在 app.py 中添加 agent 初始化和新端点**

在 `app = FastAPI(title="Smart BI", version="1.0.0")` 之后添加：
```python
# LangGraph Agent (lazy-loaded)
_agent = None

def _get_agent():
    global _agent
    if _agent is None:
        from .sql_engine.agent import agent_graph
        _agent = agent_graph
    return _agent
```

在文件末尾（`/assets` 挂载之后）添加新端点：
```python
@app.post("/api/agent/query")
async def agent_query(request: Request):
    """新端点：走 LangGraph Agent 管道。
    
    输入格式与 /api/query 兼容（接受 text 和 params 参数）。
    输出格式也与 /api/query 兼容，额外包含 visualization 字段。
    """
    body = await request.json()
    text = body.get("text", "")
    pre_parsed = body.get("params")

    try:
        agent = _get_agent()
        result = agent.invoke({
            "query_text": text,
            "pre_parsed_params": pre_parsed,
            "messages": [],
            "validated_params": None,
            "pipeline": "",
            "sql": None,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "comparison": None,
            "visualization": None,
            "retry_count": 0,
            "error": None,
        })

        return {
            "sql": result.get("sql"),
            "params": result.get("validated_params"),
            "columns": result.get("columns", []),
            "rows": result.get("rows", []),
            "row_count": result.get("row_count", 0),
            "comparison": result.get("comparison"),
            "visualization": result.get("visualization"),
            "error": result.get("error", ""),
            "pipeline": result.get("pipeline", "agent"),
        }
    except Exception as exc:
        logger.exception("Agent query failed: %s", text)
        return JSONResponse(status_code=500, content={
            "error": f"{type(exc).__name__}: {exc}",
        })
```

- [ ] **步骤 2：Commit**

```bash
git add backend/app.py
git commit -m "feat: add /api/agent/query endpoint"
```

---

### 任务 8：运行验证

**文件：**

- [ ] **步骤 1：重启后端服务器并验证**

```bash
# Kill any existing uvicorn process (Windows)
taskkill /f /im uvicorn.exe 2>/dev/null; sleep 1

# Start backend
cd /d/AI/smartAi/smartbi0512/backend && uvicorn app:app --reload --host 0.0.0.0 --port 8000 &
sleep 3

# 1) Health check
curl -s http://localhost:8000/api/health
# 预期: {"status":"ok"}

# 2) Agent parse test (text only)
curl -s -X POST http://localhost:8000/api/parse -H "Content-Type: application/json" -d '{"text":"查询工商银行近3个月的远期结汇交易量排名"}'
# 预期: 返回解析的结构化参数

# 3) Agent query test (via new endpoint)
curl -s -X POST http://localhost:8000/api/agent/query -H "Content-Type: application/json" -d '{"text":"查询工商银行近3个月的远期结汇交易量排名"}'
# 预期: 返回完整的查询结果（含 sql, params, columns, rows, row_count）
```

- [ ] **步骤 2：验证导入（当数据库不可用时）**

```bash
# 验证所有模块可以导入
cd /d/AI/smartAi/smartbi0512/backend
python -c "
from sql_engine.state import AgentState; print('state OK')
from sql_engine.tools import AGENT_TOOLS; print(f'tools OK: {len(AGENT_TOOLS)} tools')
from sql_engine.memory import AgentMemory; m = AgentMemory(); print('memory OK')
from sql_engine.agent import agent_graph; print(f'graph OK: {agent_graph}')
from visualization.chart_detector import detect_chart_type; print('chart_detector OK')
from visualization.echarts_builder import EchartsBuilder; print('echarts_builder OK')
"
```
