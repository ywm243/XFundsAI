# LangChain Agent 重构实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 BI 项目从硬编码管道重构为 LangGraph ReAct Agent，支持自主多步分析和多轮对话。

**架构：** LangGraph ReAct Agent + 4 个工具（search_knowledge, get_schema, query, compare），FastAPI SSE 流式响应。

**技术栈：** Python 3.12, FastAPI, LangChain 1.2, LangGraph 1.1, DeepSeek (ChatOpenAI), Oracle (oracledb)

---

### 任务 1：安装 LangChain 相关依赖

**文件：**
- 修改：`backend/requirements.txt`

- [ ] **步骤 1：更新 requirements.txt**

```bash
cat >> backend/requirements.txt << 'EOF'
langchain>=1.0.0
langchain-openai>=0.3.0
langgraph>=1.0.0
langgraph-checkpoint-sqlite>=0.2.0
EOF
```

- [ ] **步骤 2：安装依赖**

```bash
pip install langchain langchain-openai langgraph langgraph-checkpoint-sqlite --break-system-packages 2>&1 | tail -5
```

预期输出：Successfully installed 若干包

- [ ] **步骤 3：验证导入**

```bash
python3 -c "from langchain_openai import ChatOpenAI; from langgraph.prebuilt import create_react_agent; from langgraph.checkpoint.sqlite import SqliteSaver; print('OK')"
```

预期输出：`OK`

- [ ] **步骤 4：Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add langchain/langgraph dependencies

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 2：创建 agent/state.py — 会话状态管理

**文件：**
- 创建：`backend/agent/__init__.py`
- 创建：`backend/agent/state.py`

- [ ] **步骤 1：创建 agent/__init__.py**

```python
"""Smart BI Agent — LangGraph ReAct Agent for FX trade queries."""
```

- [ ] **步骤 2：创建 agent/state.py**

```python
"""Session state management with SqliteSaver checkpointer."""

import os
from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver

_STATE_DIR = Path(__file__).resolve().parent.parent / ".agent_state"
_STATE_DIR.mkdir(exist_ok=True)

_DB_PATH = _STATE_DIR / "checkpoints.db"


def create_checkpointer() -> SqliteSaver:
    """Create a SqliteSaver connected to the local checkpoint database."""
    conn_string = str(_DB_PATH)
    return SqliteSaver.from_conn_string(conn_string)
```

- [ ] **步骤 3：验证 checkpointer 可创建**

```bash
cd /home/ywm/smart-bi && python3 -c "
from backend.agent.state import create_checkpointer
cp = create_checkpointer()
print('OK:', type(cp).__name__)
"
```

预期输出：`OK: SqliteSaver`

- [ ] **步骤 4：Commit**

```bash
git add backend/agent/__init__.py backend/agent/state.py
git commit -m "feat: add agent state management with SqliteSaver

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 3：创建 db/schema.py — 表结构信息

**文件：**
- 创建：`backend/db/schema.py`

- [ ] **步骤 1：创建 db/schema.py**

```python
"""Database schema information for the get_schema tool.

Each view is described with its DDL, field names, types, and Chinese meanings.
"""

SCHEMA = {
    "views": {
        "XF_FX_SPOTTRADE_VIEW": {
            "description": "即期外汇交易视图",
            "product_type": "spot",
            "fields": {
                "USDAMOUNT": {"type": "NUMBER", "meaning": "折美元金额（美元）"},
                "TRADEDATE": {"type": "NUMBER(8)", "meaning": "交易日期，格式 YYYYMMDD"},
                "TRADESTATUS": {"type": "NUMBER", "meaning": "交易状态：0=有效"},
                "SPECIALSTATE": {"type": "NUMBER", "meaning": "特殊状态：0=在途 1=逾期 3=展期 4=提前交割 5=平仓"},
                "APPID": {"type": "NUMBER", "meaning": "业务系统：1=外汇 2=结售汇"},
                "BUYORSELL": {"type": "CHAR(1)", "meaning": "买卖方向：B=银行买入 S=银行卖出"},
                "BANKID": {"type": "NUMBER", "meaning": "机构ID，关联 XF_BASE_BANK.BANKID"},
                "CUSTNAME": {"type": "VARCHAR2", "meaning": "客户名称"},
                "CUSTOMERID": {"type": "VARCHAR2", "meaning": "客户号"},
                "CUSTMAINMANAGER": {"type": "VARCHAR2", "meaning": "客户经理ID"},
                "CUSTMANAGERNAME": {"type": "VARCHAR2", "meaning": "客户经理名称"},
            },
        },
        "XF_FX_FWDTRADE_VIEW": {
            "description": "远期外汇交易视图",
            "product_type": "fwd",
            "fields": {
                "USDAMOUNT": {"type": "NUMBER", "meaning": "折美元金额（美元）"},
                "TRADEDATE": {"type": "NUMBER(8)", "meaning": "交易日期，格式 YYYYMMDD"},
                "TRADESTATUS": {"type": "NUMBER", "meaning": "交易状态：0=有效"},
                "SPECIALSTATE": {"type": "NUMBER", "meaning": "特殊状态：0=在途 1=逾期 3=展期 4=提前交割 5=平仓"},
                "APPID": {"type": "NUMBER", "meaning": "业务系统：1=外汇 2=结售汇"},
                "BUYORSELL": {"type": "CHAR(1)", "meaning": "买卖方向：B=银行买入 S=银行卖出"},
                "BANKID": {"type": "NUMBER", "meaning": "机构ID，关联 XF_BASE_BANK.BANKID"},
                "CUSTNAME": {"type": "VARCHAR2", "meaning": "客户名称"},
                "CUSTOMERID": {"type": "VARCHAR2", "meaning": "客户号"},
                "CUSTMAINMANAGER": {"type": "VARCHAR2", "meaning": "客户经理ID"},
                "CUSTMANAGERNAME": {"type": "VARCHAR2", "meaning": "客户经理名称"},
            },
        },
        "XF_FX_SWAPTRADE_VIEW": {
            "description": "掉期外汇交易视图",
            "product_type": "swap",
            "fields": {
                "USDAMOUNT": {"type": "NUMBER", "meaning": "折美元金额（美元）"},
                "TRADEDATE": {"type": "NUMBER(8)", "meaning": "交易日期，格式 YYYYMMDD"},
                "TRADESTATUS": {"type": "NUMBER", "meaning": "交易状态：0=有效"},
                "SPECIALSTATE": {"type": "NUMBER", "meaning": "特殊状态：0=在途 1=逾期 3=展期 4=提前交割 5=平仓"},
                "APPID": {"type": "NUMBER", "meaning": "业务系统：1=外汇 2=结售汇"},
                "BUYORSELL": {"type": "CHAR(1)", "meaning": "买卖方向：B=银行买入 S=银行卖出"},
                "BANKID": {"type": "NUMBER", "meaning": "机构ID，关联 XF_BASE_BANK.BANKID"},
                "CUSTNAME": {"type": "VARCHAR2", "meaning": "客户名称"},
                "CUSTOMERID": {"type": "VARCHAR2", "meaning": "客户号"},
                "CUSTMAINMANAGER": {"type": "VARCHAR2", "meaning": "客户经理ID"},
                "CUSTMANAGERNAME": {"type": "VARCHAR2", "meaning": "客户经理名称"},
            },
        },
        "XF_BASE_BANK": {
            "description": "银行/机构基础信息表",
            "product_type": None,
            "fields": {
                "BANKID": {"type": "NUMBER", "meaning": "机构唯一ID"},
                "DIPNAME": {"type": "VARCHAR2", "meaning": "机构名称（如：工商银行、浙江分公司）"},
            },
        },
    },
    "dimensions": {
        "bank": {"select": "b.DIPNAME as 机构名称", "group": "b.DIPNAME", "need_join": True},
        "customer": {"select": "t.CUSTNAME as 客户名称", "group": "t.CUSTNAME", "need_join": False},
        "customer_id": {"select": "t.CUSTOMERID as 客户号", "group": "t.CUSTOMERID", "need_join": False},
        "manager": {"select": "t.CUSTMAINMANAGER as 客户经理ID", "group": "t.CUSTMAINMANAGER", "need_join": False},
        "manager_name": {"select": "t.CUSTMANAGERNAME as 客户经理名称", "group": "t.CUSTMANAGERNAME", "need_join": False},
    },
}


def get_ddl(view_name: str) -> str | None:
    """Get DDL-like description for a view."""
    info = SCHEMA["views"].get(view_name)
    if info is None:
        return None
    fields = "\n".join(
        f"  {name} {meta['type']}  -- {meta['meaning']}"
        for name, meta in info["fields"].items()
    )
    return f"-- {info['description']}\nCREATE VIEW {view_name} (\n{fields}\n)"


def get_dimensions() -> dict:
    """Get supported aggregation dimensions."""
    return SCHEMA["dimensions"]
```

- [ ] **步骤 2：验证 schema 可加载**

```bash
cd /home/ywm/smart-bi && python3 -c "
from backend.db.schema import get_ddl, get_dimensions
print(get_ddl('XF_FX_SPOTTRADE_VIEW')[:80])
print(get_dimensions().keys())
"
```

预期输出：DDL片段 + `dict_keys(['bank', 'customer', 'customer_id', 'manager', 'manager_name'])`

- [ ] **步骤 3：Commit**

```bash
git add backend/db/schema.py
git commit -m "feat: add database schema module for agent tools

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 4：创建 agent/query_executor.py — 确定性SQL构建+执行

**文件：**
- 创建：`backend/agent/query_executor.py`

- [ ] **步骤 1：创建 query_executor.py**

迁移 `TradeQueryBuilder` 的 SQL 构建逻辑，精简为以下核心功能：
- `build_aggregate_query(params)` — 聚合查询
- `build_ranking_query(params)` — 排名查询
- `build_detail_query(params)` — 明细查询
- `execute(params)` — 构建SQL并执行，返回结果

完整的 `backend/agent/query_executor.py`：

```python
"""Deterministic SQL builder and executor for Agent query tool.

Agent provides structured params, this module builds syntactically correct Oracle SQL.
Agent NEVER writes SQL strings — all SQL is generated here from validated params.
"""

import calendar
import datetime
import oracledb
from backend.db.connection import get_db

VIEW_MAP = {
    "spot": "XF_FX_SPOTTRADE_VIEW",
    "fwd": "XF_FX_FWDTRADE_VIEW",
    "swap": "XF_FX_SWAPTRADE_VIEW",
}

COMMON_FIELDS = [
    "USDAMOUNT", "TRADEDATE", "TRADESTATUS", "SPECIALSTATE",
    "APPID", "BUYORSELL", "BANKID",
    "CUSTNAME", "CUSTOMERID", "CUSTMAINMANAGER", "CUSTMANAGERNAME",
]

DIMENSION_MAP = {
    "bank": {"select": "b.DIPNAME as 机构名称", "group": "b.DIPNAME", "need_join": True},
    "customer": {"select": "t.CUSTNAME as 客户名称", "group": "t.CUSTNAME", "need_join": False},
    "customer_id": {"select": "t.CUSTOMERID as 客户号", "group": "t.CUSTOMERID", "need_join": False},
    "manager": {"select": "t.CUSTMAINMANAGER as 客户经理ID", "group": "t.CUSTMAINMANAGER", "need_join": False},
    "manager_name": {"select": "t.CUSTMANAGERNAME as 客户经理名称", "group": "t.CUSTMANAGERNAME", "need_join": False},
}


def _date_str_to_int(s: str) -> int:
    """Convert YYYY-MM-DD to YYYYMMDD integer."""
    return int(s.replace("-", ""))


def _escape_like(val: str) -> str:
    return val.replace("\\", "\\\\").replace("'", "''").replace("%", "\\%").replace("_", "\\_")


def _build_from(product_type: str) -> str:
    """Build FROM subquery (UNION ALL of views)."""
    if product_type == "all":
        subqueries = [
            f"SELECT {', '.join(COMMON_FIELDS)} FROM {v}"
            for v in VIEW_MAP.values()
        ]
        return "(\n    " + "\n    UNION ALL\n    ".join(subqueries) + "\n) t"
    view = VIEW_MAP[product_type]
    return f"(\n    SELECT {', '.join(COMMON_FIELDS)} FROM {view}\n) t"


def _join_clause(dimension: str, bank_name: str | None) -> str:
    """LEFT JOIN XF_BASE_BANK only when needed."""
    dim_info = DIMENSION_MAP.get(dimension, DIMENSION_MAP["bank"])
    if dim_info["need_join"] or bank_name:
        return "LEFT JOIN XF_BASE_BANK b ON t.BANKID = b.BANKID"
    return ""


def _build_where(date_start: str | None, date_end: str | None,
                 buy_sell: str | None, special_states: list | None,
                 bank_name: str | None, cust_name: str | None,
                 appid: int | None) -> list[str]:
    """Build WHERE conditions from validated params."""
    conditions = ["t.TRADESTATUS=0"]

    if appid is not None:
        conditions.append(f"t.APPID={appid}")
    else:
        conditions.append("t.APPID IN (1,2)")

    if date_start:
        conditions.append(f"t.TRADEDATE>={_date_str_to_int(date_start)}")
    if date_end:
        conditions.append(f"t.TRADEDATE<={_date_str_to_int(date_end)}")

    if buy_sell:
        conditions.append(f"t.BUYORSELL='{buy_sell}'")

    if cust_name:
        safe = cust_name.replace("'", "''")
        conditions.append(f"t.CUSTNAME='{safe}'")

    if special_states:
        vals = ",".join(str(s) for s in special_states)
        conditions.append(f"t.SPECIALSTATE IN ({vals})")

    if bank_name:
        safe = _escape_like(bank_name)
        conditions.append(
            f"t.BANKID IN (SELECT BANKID FROM XF_BASE_BANK WHERE DIPNAME LIKE '%{safe}%' ESCAPE '\\')"
        )

    return conditions


def build_aggregate_query(params: dict) -> str:
    """Build GROUP BY aggregate SQL with SUM + COUNT."""
    product_type = params.get("product_type", "all")
    date_start = params.get("date_start") or None
    date_end = params.get("date_end") or None
    buy_sell = params.get("buy_sell") or None
    special_states = params.get("special_states") or None
    bank_name = params.get("bank_name") or None
    cust_name = params.get("cust_name") or None
    appid = params.get("appid")
    dimension = params.get("dimension", "bank")

    dim = DIMENSION_MAP.get(dimension, DIMENSION_MAP["bank"])
    conditions = _build_where(date_start, date_end, buy_sell, special_states,
                               bank_name, cust_name, appid)
    where = "\n  AND ".join(conditions)
    from_sql = _build_from(product_type)
    join = _join_clause(dimension, bank_name)

    return (
        f"SELECT {dim['select']}, SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT\n"
        f"FROM {from_sql}\n"
        f"{join}\n"
        f"WHERE {where}\n"
        f"GROUP BY {dim['group']}\n"
        f"ORDER BY TOTAL_AMOUNT DESC"
    )


def build_ranking_query(params: dict) -> str:
    """Build TOP N ranking SQL."""
    product_type = params.get("product_type", "all")
    date_start = params.get("date_start") or None
    date_end = params.get("date_end") or None
    buy_sell = params.get("buy_sell") or None
    special_states = params.get("special_states") or None
    bank_name = params.get("bank_name") or None
    cust_name = params.get("cust_name") or None
    appid = params.get("appid")
    dimension = params.get("dimension", "bank")
    top_n = params.get("top_n") or 10

    dim = DIMENSION_MAP.get(dimension, DIMENSION_MAP["bank"])
    conditions = _build_where(date_start, date_end, buy_sell, special_states,
                               bank_name, cust_name, appid)
    where = "\n  AND ".join(conditions)
    from_sql = _build_from(product_type)
    join = _join_clause(dimension, bank_name)

    return (
        f"SELECT * FROM (\n"
        f"  SELECT {dim['select']}, SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT\n"
        f"  FROM {from_sql}\n"
        f"  {join}\n"
        f"  WHERE {where}\n"
        f"  GROUP BY {dim['group']}\n"
        f"  ORDER BY SUM(t.USDAMOUNT) DESC\n"
        f") WHERE ROWNUM <= {top_n}"
    )


def build_detail_query(params: dict) -> str:
    """Build detail rows query (no aggregation)."""
    product_type = params.get("product_type", "all")
    date_start = params.get("date_start") or None
    date_end = params.get("date_end") or None
    buy_sell = params.get("buy_sell") or None
    special_states = params.get("special_states") or None
    bank_name = params.get("bank_name") or None
    cust_name = params.get("cust_name") or None
    appid = params.get("appid")

    conditions = _build_where(date_start, date_end, buy_sell, special_states,
                               bank_name, cust_name, appid)
    where = "\n  AND ".join(conditions)
    from_sql = _build_from(product_type)

    return (
        f"SELECT t.{', t.'.join(COMMON_FIELDS)}, b.DIPNAME\n"
        f"FROM {from_sql}\n"
        f"LEFT JOIN XF_BASE_BANK b ON t.BANKID = b.BANKID\n"
        f"WHERE {where}"
    )


def execute(params: dict) -> dict:
    """Execute query from structured params. Returns {sql, columns, rows, row_count}.

    Architecture: Agent → params dict → execute() → SQL build → Oracle → result dict → Agent
    Agent never touches SQL string.
    """
    params = dict(params)
    aggregate = params.pop("aggregate", False)
    top_n = params.pop("top_n", None)

    if top_n and int(top_n) > 0:
        sql = build_ranking_query(params)
    elif aggregate:
        sql = build_aggregate_query(params)
    else:
        sql = build_detail_query(params)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [desc[0] for desc in cur.description] if cur.description else []
            rows = [list(row) for row in cur.fetchall()]

    return {
        "sql": sql,
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
    }
```

- [ ] **步骤 2：验证 execute 函数**

```bash
cd /home/ywm/smart-bi && python3 -c "
from backend.agent.query_executor import execute
import json
# Simple aggregate query
result = execute({
    'product_type': 'all',
    'aggregate': True,
    'dimension': 'bank',
})
print('columns:', result['columns'])
print('rows count:', result['row_count'])
print('OK - query_executor works')
"
```

预期：返回数据，打印 columns 和 rows count

- [ ] **步骤 3：Commit**

```bash
git add backend/agent/query_executor.py
git commit -m "feat: add deterministic query executor for agent

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 5：创建 agent/tools.py — Agent 工具定义

**文件：**
- 创建：`backend/agent/tools.py`

- [ ] **步骤 1：创建 tools.py**

```python
"""LangChain tools for the BI Agent.

Four tools:
  - search_knowledge: search business rules (product type, buy/sell, time, etc.)
  - get_schema: get table/view schema information
  - query: execute structured query (Agent provides params, NOT SQL)
  - compare: year-over-year / month-over-month comparison
"""

import datetime
import json
import calendar
from pathlib import Path
from langchain_core.tools import tool
from backend.db.schema import get_ddl, get_dimensions
from backend.agent.query_executor import execute as execute_query

_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


def _load_rules() -> dict:
    rules_file = _KNOWLEDGE_DIR / "semantic_rules.json"
    with open(rules_file, "r", encoding="utf-8") as f:
        return json.load(f)


@tool
def search_knowledge(query: str) -> str:
    """Search business knowledge base for rules about product types, buy/sell direction,
    time expressions, special states, and dimensions.

    Use this tool when you need to understand:
    - How to map product names (即期/远期/掉期) to product_type values (spot/fwd/swap)
    - How to determine buy/sell direction (B/S) from Chinese terms
    - How to interpret time expressions (今年1月, 上月, 昨天, etc.)
    - What special state keywords map to which codes
    - What dimensions are available for aggregation

    Args:
        query: Keywords or question to search for (e.g. "买卖方向", "时间表达式", "维度")

    Returns:
        Matched rule descriptions as text.
    """
    rules = _load_rules()
    results = []

    # Search across all rule categories
    for category in rules:
        if category.startswith("_"):
            continue
        cat_data = rules[category]
        if isinstance(cat_data, dict) and "rules" in cat_data:
            for rule in cat_data["rules"]:
                rule_str = json.dumps(rule, ensure_ascii=False)
                if any(kw in rule_str for kw in query.split()):
                    results.append(f"[{category}] {rule_str}")

    if not results:
        # Return category overview
        cats = [k for k in rules if not k.startswith("_")]
        return f"可用知识类别: {cats}。请用更具体的关键词搜索。"

    return "\n".join(results)


@tool
def get_schema(view_name: str = "") -> str:
    """Get database schema information for views and tables.

    Use this tool to understand table structure, field names, and their meanings.
    Call without arguments to list all available views.

    Args:
        view_name: Optional view name (e.g. 'XF_FX_SPOTTRADE_VIEW'). Empty to list all.

    Returns:
        Schema description with field names, types, and Chinese meanings.
    """
    if view_name:
        ddl = get_ddl(view_name)
        if ddl:
            return ddl
        return f"视图 '{view_name}' 不存在。可用视图见无参数调用。"

    views = []
    for vname, info in __import__("backend.db.schema", fromlist=["SCHEMA"]).SCHEMA["views"].items():
        if info["product_type"]:
            views.append(f"  {vname} — {info['description']} (product_type={info['product_type']})")
        else:
            views.append(f"  {vname} — {info['description']}")

    dims = get_dimensions()
    dim_list = "\n".join(f"  {k}: {v['select']}" for k, v in dims.items())

    return (
        "可用视图:\n" + "\n".join(views) + "\n\n"
        "可用聚合维度 (用于 query 工具的 dimension 参数):\n" + dim_list + "\n"
    )


@tool
def query(params: dict) -> dict:
    """Execute a structured query on the FX trading database.

    IMPORTANT: You must provide structured parameters, NOT SQL. The SQL is built
    deterministically from your params to guarantee 100% correctness.

    Args:
        params: Dict with these keys:
            product_type: "all" | "spot" | "fwd" | "swap"
            date_start: "YYYY-MM-DD" or empty string
            date_end: "YYYY-MM-DD" or empty string
            buy_sell: "B" | "S" | "" (empty = all)
            special_states: list of codes or null (e.g. ["0","1"])
            bank_name: bank/organization name for fuzzy match, or empty
            cust_name: exact customer name, or empty
            appid: 1 | 2 | null (null = all)
            dimension: "bank" | "customer" | "customer_id" | "manager" | "manager_name"
            aggregate: true | false
            top_n: integer or null (if set, returns top N by amount)

    Returns:
        Dict with 'columns', 'rows', 'row_count', and 'sql' keys.
    """
    return execute_query(params)


def _compute_comparison_dates(date_start: str, date_end: str, comparison: str) -> tuple:
    """Compute comparison date range."""
    if not date_start or not date_end:
        return ("", "")

    start = datetime.date.fromisoformat(date_start)
    end = datetime.date.fromisoformat(date_end)

    if comparison == "yoy":
        try:
            cmp_start = start.replace(year=start.year - 1)
        except ValueError:
            cmp_start = start.replace(year=start.year - 1, day=start.day - 1)
        try:
            cmp_end = end.replace(year=end.year - 1)
        except ValueError:
            cmp_end = end.replace(year=end.year - 1, day=end.day - 1)
        return (cmp_start.strftime("%Y-%m-%d"), cmp_end.strftime("%Y-%m-%d"))

    elif comparison == "mom":
        delta = end - start
        cmp_end = start - datetime.timedelta(days=1)
        cmp_start = cmp_end - delta
        return (cmp_start.strftime("%Y-%m-%d"), cmp_end.strftime("%Y-%m-%d"))

    return ("", "")


@tool
def compare(params: dict, comparison_type: str = "yoy") -> dict:
    """Perform year-over-year (YoY) or month-over-month (MoM) comparison.

    Runs the same query for two periods and computes change.

    Args:
        params: Same structured params as the 'query' tool (without comparison_type).
        comparison_type: "yoy" for 同比 (year-over-year) or "mom" for 环比 (month-over-month).

    Returns:
        Dict with current_period, compare_period, current_amount, compare_amount,
        change_amount, change_rate (percentage).
    """
    # Remove aggregate/top_n to get raw amounts for both periods
    current_params = dict(params)
    current_params["aggregate"] = True
    compare_params = dict(params)
    compare_params["aggregate"] = True

    # Compute comparison dates
    cmp_start, cmp_end = _compute_comparison_dates(
        current_params.get("date_start", ""),
        current_params.get("date_end", ""),
        comparison_type,
    )
    compare_params["date_start"] = cmp_start
    compare_params["date_end"] = cmp_end

    # Execute both
    current_result = execute_query(current_params)
    compare_result = execute_query(compare_params)

    if not current_result["rows"] or not compare_result["rows"]:
        return {"error": "No data for comparison"}

    current_row = current_result["rows"][0]
    compare_row = compare_result["rows"][0]

    idx = 1  # TOTAL_AMOUNT column
    current_amt = float(current_row[idx]) if current_row[idx] is not None else 0
    compare_amt = float(compare_row[idx]) if compare_row[idx] is not None else 0

    change_amount = round(current_amt - compare_amt, 2)
    if compare_amt != 0:
        change_rate = round(abs(change_amount / compare_amt) * 100, 2)
    else:
        change_rate = None

    label = "同比" if comparison_type == "yoy" else "环比"
    return {
        "type": comparison_type,
        "label": label,
        "current_period": f"{params.get('date_start')} ~ {params.get('date_end')}",
        "compare_period": f"{cmp_start} ~ {cmp_end}",
        "current_amount": round(current_amt, 2),
        "compare_amount": round(compare_amt, 2),
        "change_amount": change_amount,
        "change_rate": change_rate,
    }
```

- [ ] **步骤 2：验证工具可加载**

```bash
cd /home/ywm/smart-bi && python3 -c "
from backend.agent.tools import search_knowledge, get_schema, query, compare
print('search_knowledge:', type(search_knowledge).__name__)
print('get_schema:', type(get_schema).__name__)
print('query:', type(query).__name__)
print('compare:', type(compare).__name__)
print('OK - all tools loaded')
"
```

预期输出：`OK - all tools loaded`

- [ ] **步骤 3：Commit**

```bash
git add backend/agent/tools.py
git commit -m "feat: add agent tools (search_knowledge, get_schema, query, compare)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 6：创建 agent/prompts.py — 系统提示词

**文件：**
- 创建：`backend/agent/prompts.py`

- [ ] **步骤 1：创建 prompts.py**

```python
"""System prompt for the BI Agent."""

from datetime import date


def build_system_prompt() -> str:
    """Build the system prompt with current date context."""
    today = date.today()

    return f"""你是 Smart BI 分析助手，帮助用户查询外汇交易数据并进行分析。

## 核心规则

1. **数据准确性优先**：查询数据库必须使用 query 工具，传入结构化参数。绝对禁止自行构造 SQL。
2. **先理解再查询**：不确定的参数（产品类型、买卖方向等）先用 search_knowledge 查业务规则。
3. **自动对比**：用户问"同比"或"环比"时，使用 compare 工具。
4. **分析步骤**：复杂问题拆成多步——先查总量，再按维度下钻，最后对比分析。

## 当前日期

{today.strftime('%Y-%m-%d')}（所有时间计算以此为准）

## 工具使用指南

### query 工具 — 查询数据库
参数说明：
- product_type: "all" | "spot" | "fwd" | "swap"
- date_start / date_end: "YYYY-MM-DD" 格式
- buy_sell: "B"=银行买入, "S"=银行卖出, ""=不限
- dimension: "bank"=机构, "customer"=客户, "customer_id"=客户号, "manager"=客户经理ID, "manager_name"=客户经理名称
- bank_name: 银行/分公司名称模糊匹配
- cust_name: 客户名称精确匹配
- appid: 1=外汇, 2=结售汇, null=全部
- aggregate: true=聚合汇总, false=明细
- top_n: 数字=排名TOP N, null=不限
- special_states: ["0"]=在途, ["1"]=逾期, ["3"]=展期, ["4"]=提前交割, ["5"]=平仓

### compare 工具 — 同比/环比对比
参数与 query 相同，额外加 comparison_type: "yoy"=同比, "mom"=环比

### search_knowledge 工具 — 查询业务规则
当你不确定某个参数如何映射时使用。例如：
- "买卖方向" → 了解 B/S 与中文术语的对应关系
- "时间表达式" → 了解时间关键词的计算规则
- "特殊状态" → 了解状态码的含义

### get_schema 工具 — 获取表结构
了解可用的视图、字段名和含义。

## 响应风格

- 用中文回复，简洁专业
- 查询结果用金额（万美元）和笔数呈现
- 对比分析给出变化量和变化率
- 不暴露 SQL 给用户"""
```

- [ ] **步骤 2：验证提示词可生成**

```bash
cd /home/ywm/smart-bi && python3 -c "
from backend.agent.prompts import build_system_prompt
prompt = build_system_prompt()
print(f'Prompt length: {len(prompt)} chars')
print('Contains today date:', '2026' in prompt)
print('OK')
"
```

预期：Prompt length > 1000，Contains today date: True

- [ ] **步骤 3：Commit**

```bash
git add backend/agent/prompts.py
git commit -m "feat: add agent system prompt

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 7：创建 agent/agent.py — LangGraph Agent 定义

**文件：**
- 创建：`backend/agent/agent.py`

- [ ] **步骤 1：读取 .env 中的 DEEPSEEK 配置**

```bash
grep -E "DEEPSEEK|LLM" /home/ywm/smart-bi/.env 2>/dev/null || echo "check config"
```

- [ ] **步骤 2：检查 llm_client.py 中的 DeepSeek 配置**

```bash
grep -E "base_url|api_key|model" /home/ywm/smart-bi/backend/llm_parser/llm_client.py
```

- [ ] **步骤 3：创建 agent.py**

```python
"""LangGraph ReAct Agent for Smart BI."""

import os
import logging
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from .tools import search_knowledge, get_schema, query, compare
from .prompts import build_system_prompt
from .state import create_checkpointer

logger = logging.getLogger(__name__)

TOOLS = [search_knowledge, get_schema, query, compare]

_agent_cache = None


def _create_llm() -> ChatOpenAI:
    """Create ChatOpenAI instance configured for DeepSeek."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        timeout=60,
    )


def get_agent():
    """Create or retrieve the cached LangGraph ReAct agent."""
    global _agent_cache
    if _agent_cache is not None:
        return _agent_cache

    llm = _create_llm()
    system_prompt = build_system_prompt()
    checkpointer = create_checkpointer()

    _agent_cache = create_react_agent(
        model=llm,
        tools=TOOLS,
        prompt=system_prompt,
        checkpointer=checkpointer,
    )

    logger.info("Agent created with %d tools, model=%s", len(TOOLS), llm.model_name)
    return _agent_cache


def reset_agent():
    """Reset cached agent (useful after config changes)."""
    global _agent_cache
    _agent_cache = None
    logger.info("Agent cache reset")
```

- [ ] **步骤 4：验证 Agent 可创建（不实际调用 LLM）**

```bash
cd /home/ywm/smart-bi && python3 -c "
import os
os.environ['DEEPSEEK_API_KEY'] = 'test-key'
from backend.agent.agent import get_agent, reset_agent
agent = get_agent()
print('Agent created:', type(agent).__name__)
print('OK')
"
```

预期：`Agent created: CompiledStateGraph`

注意：如果 DEEPSEEK_API_KEY 不存在会报错，先设置临时的。

- [ ] **步骤 5：Commit**

```bash
git add backend/agent/agent.py
git commit -m "feat: add LangGraph ReAct agent definition

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 8：重写 app.py — SSE 流式聊天端点

**文件：**
- 修改：`backend/app.py`（重写）

- [ ] **步骤 1：检查 .env 中的 DeepSeek 配置**

```bash
grep -E "DEEPSEEK" /home/ywm/smart-bi/.env
```

- [ ] **步骤 2：重写 app.py**

移除所有旧端点（/api/parse, /api/query, /api/reload-rules），只保留 /api/health 和新增 /api/chat。

```python
"""FastAPI application — Smart BI Agent with SSE streaming."""

import json
import logging
import traceback
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE, override=True)

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage

from .agent.agent import get_agent, reset_agent

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

app = FastAPI(title="Smart BI Agent", version="2.0.0")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _sse(data: dict) -> str:
    """Format a dict as an SSE event."""
    event = data.pop("event", "message")
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _stream_agent(thread_id: str, text: str):
    """Run agent with SSE streaming of thinking/tool_call/result events."""
    agent = get_agent()
    config = {"configurable": {"thread_id": thread_id}}

    yield _sse({"event": "thinking", "text": "正在分析您的问题..."})

    try:
        # Stream agent events
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=text)]},
            config,
            version="v2",
        ):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    yield _sse({"event": "token", "text": content})

            elif kind == "on_tool_start":
                tool_name = event["name"]
                tool_input = event["data"].get("input", {})
                yield _sse({
                    "event": "tool_start",
                    "tool": tool_name,
                    "args": tool_input,
                })

            elif kind == "on_tool_end":
                output = event["data"].get("output")
                # Serialize tool output for frontend
                if isinstance(output, dict) and "columns" in output:
                    yield _sse({
                        "event": "data",
                        "type": "table",
                        "columns": output["columns"],
                        "rows": output["rows"],
                        "row_count": output["row_count"],
                    })
                elif isinstance(output, dict) and "comparison" in output:
                    yield _sse({"event": "comparison", "data": output})
                elif isinstance(output, dict) and "change_rate" in output:
                    yield _sse({"event": "comparison", "data": output})

        yield _sse({"event": "done"})

    except Exception as exc:
        logger.exception("Agent stream failed")
        yield _sse({
            "event": "error",
            "error": f"{type(exc).__name__}: {exc}",
        })


@app.post("/api/chat")
async def chat(request: Request):
    """Streaming chat endpoint — agent plans and executes tools autonomously."""
    body = await request.json()
    text = body.get("text", "").strip()
    thread_id = body.get("thread_id", "").strip()

    if not text:
        return StreamingResponse(
            iter([_sse({"event": "error", "error": "Empty query"})]),
            media_type="text/event-stream",
        )
    if not thread_id:
        import uuid
        thread_id = str(uuid.uuid4())

    return StreamingResponse(
        _stream_agent(thread_id, text),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-ID": thread_id,
        },
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/reset")
async def api_reset():
    """Reset agent cache (useful after rule/config changes)."""
    reset_agent()
    return {"status": "ok", "message": "Agent cache reset"}


# ---- Static file serving (production) ----

@app.get("/")
def index():
    dist_index = FRONTEND_DIR / "dist" / "index.html"
    if dist_index.exists():
        return FileResponse(dist_index)
    return FileResponse(FRONTEND_DIR / "index.html")


_dist_assets = FRONTEND_DIR / "dist" / "assets"
if _dist_assets.exists():
    app.mount("/assets", StaticFiles(directory=str(_dist_assets)), name="assets")
```

- [ ] **步骤 3：验证 FastAPI 启动**

```bash
cd /home/ywm/smart-bi && timeout 5 python3 -c "
import sys
sys.path.insert(0, '.')
from backend.app import app
print('App routes:')
for route in app.routes:
    print(f'  {getattr(route, \"methods\", None)} {getattr(route, \"path\", route)}')
print('OK')
" 2>&1 || true
```

- [ ] **步骤 4：Commit**

```bash
git add backend/app.py
git commit -m "feat: rewrite app.py with SSE streaming agent chat endpoint

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 9：清理旧模块

**文件：**
- 删除：`backend/llm_parser/`（整个目录）
- 删除：`backend/sql_engine/`（空目录）
- 删除：`backend/visualization/`（空目录）

- [ ] **步骤 1：删除旧模块**

```bash
rm -rf /home/ywm/smart-bi/backend/llm_parser/
rm -rf /home/ywm/smart-bi/backend/sql_engine/
rm -rf /home/ywm/smart-bi/backend/visualization/
```

- [ ] **步骤 2：验证启动不报导入错误**

```bash
cd /home/ywm/smart-bi && python3 -c "
from backend.app import app
print('OK - app imports without error')
"
```

- [ ] **步骤 3：Commit**

```bash
git add -A backend/
git commit -m "refactor: remove old llm_parser module, replaced by agent

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 10：端到端测试

**文件：**
- 创建：`backend/tests/test_agent.py`（如果有 tests 目录结构）

- [ ] **步骤 1：启动后端（带 Oracle LD_LIBRARY_PATH）**

```bash
export LD_LIBRARY_PATH=/home/ywm/oracle/instantclient_21_12:$LD_LIBRARY_PATH
cd /home/ywm/smart-bi && uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000 &
sleep 3
```

- [ ] **步骤 2：测试健康检查**

```bash
curl -s http://localhost:8000/api/health | python3 -m json.tool
```

预期：`{"status": "ok"}`

- [ ] **步骤 3：测试 SSE 聊天端点**

```bash
curl -s -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "今年1月交易量多少", "thread_id": "test-001"}' \
  2>&1 | head -20
```

预期：SSE 事件流，包含 thinking → tool_start → data → done 事件

- [ ] **步骤 4：测试多轮对话**

```bash
curl -s -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "同比呢", "thread_id": "test-001"}' \
  2>&1 | head -20
```

预期：Agent 能利用同一 thread_id 的上下文，自动补全"今年1月"的信息并执行同比对比

- [ ] **步骤 5：验证旧端点已移除**

```bash
curl -s -X POST http://localhost:8000/api/parse -H "Content-Type: application/json" -d '{"text":"test"}' | python3 -c "import json,sys;d=json.load(sys.stdin);print('status:',d.get('detail',''))"
```

预期：404 Not Found

- [ ] **步骤 6：Commit（如有修改）**

```bash
git add -A
git commit -m "test: add end-to-end agent verification

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### 任务 11：更新 .gitignore 和文档

**文件：**
- 修改：`.gitignore`

- [ ] **步骤 1：添加 agent state 到 .gitignore**

```bash
echo "
# Agent state (会话历史)
backend/.agent_state/
" >> .gitignore
```

- [ ] **步骤 2：更新 CLAUDE.md 操作层命令**

操作层命令更新为：

```markdown
| 场景 | 命令 | 说明 |
|------|------|------|
| 启动后端 | `cd backend && uvicorn app:app --reload --host 0.0.0.0 --port 8000` | FastAPI + Agent |
| 测试API | `curl -X POST http://localhost:8000/api/chat -H 'Content-Type: application/json' -d '{"text":"test","thread_id":"x"}'` | SSE流式 |
| 重置Agent | `curl -X POST http://localhost:8000/api/reset` | 清除Agent缓存 |
```

- [ ] **步骤 3：Commit**

```bash
git add .gitignore CLAUDE.md
git commit -m "chore: update gitignore and docs for agent architecture

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```
