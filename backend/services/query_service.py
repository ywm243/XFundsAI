"""Query orchestration service — SQL building and execution pipeline.

Extracted from app.py to enable reuse by langgraph/bi_agent.py without
circular imports.
"""

import logging

from db.query_builder import TradeQueryBuilder
from llm_parser.parser import compute_comparison_dates
from services.sql_executor import execute_oracle
from services.result_formatter import compute_comparison

logger = logging.getLogger(__name__)


def build_sql(parsed, date_start=None, date_end=None):
    """Build SQL from parsed params with given date range.

    Shared by the main query endpoint and comparison SQL builder.
    """
    buy_sell = parsed.get("buy_sell") or None
    cust_name = parsed.get("cust_name") or None
    bank_name = parsed.get("bank_name") or None
    special_states = parsed.get("special_states", "")
    if isinstance(special_states, str) and special_states:
        special_states = [s.strip() for s in special_states.split(",")]
    else:
        special_states = None

    lifecycle_status = parsed.get("lifecycle_status") or None
    amount_filter = parsed.get("amount_filter")
    top_n = parsed.get("top_n")

    if amount_filter:
        return TradeQueryBuilder.build_filtered_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=bank_name,
            amount_op=amount_filter["amount_op"],
            amount_value=amount_filter["amount_value"],
            hedge_ratio=parsed.get("hedge_ratio", False),
            dimension=parsed.get("dimension", "bank"),
            cust_name=cust_name, appid=parsed.get("appid"),
            lifecycle_status=lifecycle_status,
        )
    elif top_n and top_n > 0:
        return TradeQueryBuilder.build_ranking_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=bank_name,
            top_n=top_n, dimension=parsed.get("dimension", "bank"),
            hedge_ratio=parsed.get("hedge_ratio", False),
            cust_name=cust_name, appid=parsed.get("appid"),
            lifecycle_status=lifecycle_status,
        )
    elif parsed.get("hedge_ratio"):
        return TradeQueryBuilder.build_hedge_ratio_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=bank_name,
            dimension=parsed.get("dimension", "bank"),
            cust_name=cust_name, appid=parsed.get("appid"),
        )
    elif parsed.get("aggregate"):
        return TradeQueryBuilder.build_aggregate_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=bank_name,
            cust_name=cust_name, appid=parsed.get("appid"),
            dimension=parsed.get("dimension"),
            lifecycle_status=lifecycle_status,
        )
    else:
        return TradeQueryBuilder.build_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=bank_name,
            cust_name=cust_name, appid=parsed.get("appid"),
            lifecycle_status=lifecycle_status,
        )


def build_comparison_sql(parsed, date_start, date_end):
    """Rebuild SQL with comparison date range."""
    return build_sql(parsed, date_start=date_start, date_end=date_end)


def execute_query_sync(sql: str, parsed: dict) -> tuple:
    """Run Oracle query and optional comparison query, returns result tuple.

    This is a blocking sync function — run via asyncio.to_thread.
    Returns (cols, rows, comparison_data, cmp_rows, comparison_sql).
    """
    cols, rows = execute_oracle(sql)

    comparison = parsed.get("comparison")
    comparison_data = None
    cmp_rows = []
    comparison_sql = None

    if comparison and sql and rows:
        cmp_start, cmp_end = compute_comparison_dates(
            parsed["date_start"] or "", parsed["date_end"] or "", comparison
        )
        if cmp_start and cmp_end:
            comparison_sql = build_comparison_sql(
                parsed=parsed,
                date_start=cmp_start, date_end=cmp_end,
            )
            try:
                cmp_cols, cmp_rows = execute_oracle(comparison_sql)
                if cmp_rows:
                    comparison_data = compute_comparison(
                        current_rows=rows, compare_rows=cmp_rows,
                        comparison=comparison,
                        date_start=parsed["date_start"] or "",
                        date_end=parsed["date_end"] or "",
                        cmp_start=cmp_start, cmp_end=cmp_end,
                        cols=cmp_cols,
                    )
            except Exception as exc:
                logger.warning("Comparison query failed: %s", exc)

    return cols, rows, comparison_data, cmp_rows, comparison_sql


def fetch_breakdown_text(params: dict, date_start: str, date_end: str, label: str) -> str:
    """Fetch breakdown by product type for a given period, return formatted text."""
    lines = []
    bank_name = (params.get("bank_name") or "") or None
    appid = params.get("appid")

    for pt in ("spot", "fwd", "swap"):
        try:
            sql = TradeQueryBuilder.build_aggregate_query(
                product_type=pt,
                date_start=date_start or None,
                date_end=date_end or None,
                bank_name=bank_name,
                appid=appid,
            )
            cols, rows = execute_oracle(sql)
            if rows and rows[0][0] is not None:
                amt = float(rows[0][0])
                cnt = int(rows[0][1])
                lines.append(f"  {pt}: 金额={amt:,.2f}, 笔数={cnt}")
            else:
                lines.append(f"  {pt}: 无数据")
        except Exception as exc:
            lines.append(f"  {pt}: 查询异常({exc})")
    return "\n".join(lines)
