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

    from llm_parser.rules_engine import load_dimension_config
    label_map = load_dimension_config().get("comparison_labels", {"yoy": "同比", "mom": "环比"})
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
