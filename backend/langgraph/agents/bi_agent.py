"""BI Agent sub-graph — parse, gatekeep, build SQL, execute, compare, format.

Uses services layer instead of importing from app.py (fixes circular dependency).
"""

import logging
from langgraph.graph import StateGraph
from llm_parser.parser import rule_based_parse, _rule_confidence, compute_comparison_dates
from llm_parser.rules_engine import gatekeep
from llm_parser.llm_client import llm_parse
from llm_parser.prompt_builder import build_system_prompt
from langgraph.state import AgentState
from services.sql_executor import execute_oracle
from services.query_service import build_sql, build_comparison_sql
from services.result_formatter import (
    compute_comparison, merge_comparison_into_rows,
    build_summary, build_chart_option, build_insights,
)

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
        # 优先使用 ContextAssembler 组装好的上下文（已包含 wiki + 对话历史 + agent 记忆）
        # 不再传入原始 state.context，消除双重发送
        assembled = getattr(state, "_assembled_context", None)
        system_prompt = build_system_prompt(
            context=None,                      # 不再发送原始 context
            query_text=getattr(state, "user_text", ""),
            assembled_context=assembled
        )
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
    """Build SQL from parsed params using query service."""
    parsed = state.parsed_params
    if not parsed or not parsed.get("product_type"):
        return {"sql": "", "sql_validated": False, "error": "Missing product_type in parsed params"}

    try:
        sql = build_sql(parsed, date_start=parsed.get("date_start") or None, date_end=parsed.get("date_end") or None)
        return {"sql": sql, "sql_validated": True}
    except Exception as exc:
        logger.warning("build_sql failed: %s", exc)
        return {"sql": "", "sql_validated": False, "error": str(exc)}


def _node_execute(state: AgentState) -> dict:
    """Execute SQL against Oracle."""
    if not state.sql:
        return {"columns": [], "rows": [], "row_count": 0}

    try:
        cols, rows = execute_oracle(state.sql)
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
        cmp_sql = build_comparison_sql(parsed, cmp_start, cmp_end)
        if not cmp_sql:
            return {}

        cmp_cols, cmp_rows = execute_oracle(cmp_sql)

        if not cmp_rows:
            return {}

        comparison_data = compute_comparison(
            current_rows=rows, compare_rows=cmp_rows,
            comparison=comparison,
            date_start=date_start, date_end=date_end,
            cmp_start=cmp_start, cmp_end=cmp_end,
            cols=cmp_cols,
        )

        if comparison_data and cmp_rows:
            cmp_label = comparison_data.get("label", "对比")
            merged_cols, merged_rows = merge_comparison_into_rows(
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
    if not state.rows or not state.columns:
        return {"summary": "", "chart_option": None, "insights": []}

    summary = build_summary(state.parsed_params, state.rows,
                            state.columns, state.comparison)
    chart_option = build_chart_option(state.parsed_params, state.rows,
                                      state.columns, state.comparison)
    insights = build_insights(state.parsed_params, state.rows,
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
