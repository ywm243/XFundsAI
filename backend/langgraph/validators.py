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

FORBIDDEN_KEYWORDS = ["DROP", "ALTER", "CREATE", "TRUNCATE",
                       "INSERT", "UPDATE", "DELETE", "MERGE",
                       "GRANT", "REVOKE"]


def node_validate_sql(state: AgentState) -> dict:
    """Validate SQL safety and correctness.

    Checks:
    1. Table/view names against VIEW_MAP
    2. Forbidden keyword detection
    3. Must be SELECT or WITH statement

    Returns updated validation_warnings list.
    """
    sql = state.sql
    warnings = []

    if not sql:
        return {"sql_validated": False}

    sql_upper = sql.strip().upper()

    # Must be SELECT or WITH (read-only)
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        warnings.append("SQL rejected: only SELECT/WITH statements are allowed")
        return {"sql_validated": False, "validation_warnings": warnings}

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
    # 如果有 fatal 错误，跳过验证直接返回
    fatals = [e for e in state.errors if e["severity"] == "fatal"]
    if fatals:
        return {
            "validation_warnings": [f["message"] for f in fatals],
            "sql_validated": False,
        }

    sql_result = node_validate_sql(state)
    result_result = node_validate_result(state)
    return {
        "sql_validated": sql_result.get("sql_validated", True),
        "validation_warnings": (
            sql_result.get("validation_warnings", [])
            + result_result.get("validation_warnings", [])
        ),
    }
