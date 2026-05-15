# backend/langgraph/agents/bi_agent.py
"""BI Agent sub-graph — parse, gatekeep, build SQL, execute, compare, format."""

import logging
from langgraph.graph import StateGraph
from llm_parser.parser import rule_based_parse, _rule_confidence, compute_comparison_dates
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
    if not parsed or not parsed.get("product_type"):
        return {"sql": "", "sql_validated": False, "error": "Missing product_type in parsed params"}

    product_type = parsed["product_type"]
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
            amt_op = amount_filter.get("amount_op")
            amt_val = amount_filter.get("amount_value")
            sql = TradeQueryBuilder.build_filtered_query(
                product_type=product_type,
                date_start=parsed.get("date_start") or None,
                date_end=parsed.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                amount_op=amt_op,
                amount_value=amt_val,
                hedge_ratio=parsed.get("hedge_ratio", False),
                dimension=parsed.get("dimension", "bank"),
                cust_name=cust_name, appid=parsed.get("appid"),
            )
        elif top_n and top_n > 0:
            sql = TradeQueryBuilder.build_ranking_query(
                product_type=product_type,
                date_start=parsed.get("date_start") or None,
                date_end=parsed.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                amount_op=amt_op,
                amount_value=amt_val,
                hedge_ratio=parsed.get("hedge_ratio", False),
                dimension=parsed.get("dimension", "bank"),
                cust_name=cust_name, appid=parsed.get("appid"),
            )
        elif top_n and top_n > 0:
            sql = TradeQueryBuilder.build_ranking_query(
                product_type=product_type,
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
                product_type=product_type,
                date_start=parsed.get("date_start") or None,
                date_end=parsed.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                dimension=parsed.get("dimension", "bank"),
                cust_name=cust_name, appid=parsed.get("appid"),
            )
        elif parsed.get("aggregate"):
            sql = TradeQueryBuilder.build_aggregate_query(
                product_type=product_type,
                date_start=parsed.get("date_start") or None,
                date_end=parsed.get("date_end") or None,
                special_states=special_states, buy_sell=buy_sell,
                bank_name=parsed.get("bank_name") or None,
                cust_name=cust_name, appid=parsed.get("appid"),
                dimension=parsed.get("dimension"),
            )
        else:
            sql = TradeQueryBuilder.build_query(
                product_type=product_type,
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
    """Build comparison data: compute YoY/MoM via second SQL execution."""
    parsed = state.parsed_params
    comparison = parsed.get("comparison") if parsed else None
    rows = state.rows
    sql = state.sql

    if not comparison or not sql or not rows:
        return {}

    date_start = parsed.get("date_start") or ""
    date_end = parsed.get("date_end") or ""
    if not date_start or not date_end:
        return {}

    cmp_start, cmp_end = compute_comparison_dates(date_start, date_end, comparison)
    if not cmp_start or not cmp_end:
        return {}

    try:
        # Build comparison SQL with shifted dates
        from app import _build_comparison_sql, _compute_comparison, _merge_comparison_into_rows

        cmp_sql = _build_comparison_sql(parsed, sql, cmp_start, cmp_end)
        if not cmp_sql:
            return {}

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(cmp_sql)
                cmp_cols = [desc[0] for desc in cur.description] if cur.description else []
                cmp_rows = [list(row) for row in cur.fetchall()]

        if not cmp_rows:
            return {}

        comparison_data = _compute_comparison(
            current_rows=rows, compare_rows=cmp_rows,
            comparison=comparison,
            date_start=date_start, date_end=date_end,
            cmp_start=cmp_start, cmp_end=cmp_end,
        )

        # Merge per-row comparison data into columns
        if comparison_data and cmp_rows:
            cmp_label = comparison_data.get("label", "对比")
            merged_cols, merged_rows = _merge_comparison_into_rows(
                rows, cmp_rows, state.columns, cmp_label
            )
            return {
                "comparison": comparison_data,
                "columns": merged_cols,
                "rows": merged_rows,
            }

        return {"comparison": comparison_data}
    except Exception as exc:
        logger.warning("build_comparison failed: %s", exc)
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
