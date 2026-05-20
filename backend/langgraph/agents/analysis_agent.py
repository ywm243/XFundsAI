"""Analysis Agent -- LangGraph subgraph, executes change attribution analysis and LLM text generation.

Integrates the deterministic analysis pipeline from agent.orchestrator into the
LangGraph DAG: tool execution (query_metrics + decompose_change) -> LLM text generation -> format.
"""

import logging

from langgraph.graph import StateGraph, END

from langgraph.state import AgentState

logger = logging.getLogger(__name__)


def build_analysis_graph():
    """Build the Analysis Agent sub-graph.

    Nodes:
      analysis_execute_tools -- runs query_metrics + decompose_change
      analysis_generate_text -- LLM generates analysis text from tool data
      analysis_format        -- formats output for frontend consumption
    """
    builder = StateGraph(AgentState)
    builder.add_node("analysis_execute_tools", _node_analysis_execute_tools)
    builder.add_node("analysis_generate_text", _node_analysis_generate_text)
    builder.add_node("analysis_format", _node_analysis_format)

    builder.set_entry_point("analysis_execute_tools")
    builder.add_edge("analysis_execute_tools", "analysis_generate_text")
    builder.add_edge("analysis_generate_text", "analysis_format")
    builder.add_edge("analysis_format", END)
    return builder.compile()


def _node_analysis_execute_tools(state: AgentState) -> dict:
    """Execute query_metrics (baseline with comparison) and decompose_change per dimension.

    Uses the same tool functions and helper logic as agent.orchestrator.run_analysis.
    """
    from agent.tools import query_metrics, decompose_change
    from agent.orchestrator import _determine_analysis_dimensions, _build_tool_filters

    params = dict(state.parsed_params or {})
    date_start = params.get("date_start")
    date_end = params.get("date_end")

    if not date_start or not date_end:
        logger.warning("analysis_agent: missing date_start/date_end in parsed_params")
        return {
            "analysis_data": {"tool_results": [], "error": "missing_dates"},
            "mode": "analyze",
        }

    comparison = params.get("comparison") or "yoy"
    filters = _build_tool_filters(params)
    results: list[dict] = []

    # Step 1: Baseline query with comparison
    logger.info("analysis_agent: query_metrics (comparison=%s)", comparison)
    try:
        baseline = query_metrics(
            metrics=["trading_volume"],
            filters=filters,
            date_start=date_start,
            date_end=date_end,
            comparison=comparison,
        )
        results.append({"tool": "query_metrics", "type": "baseline", "data": baseline})
    except Exception as exc:
        logger.exception("analysis_agent: baseline query_metrics failed")
        results.append({"tool": "query_metrics", "type": "baseline", "error": str(exc)})

    # Step 2: Decompose by each applicable dimension
    dimensions = _determine_analysis_dimensions(params)
    for dim in dimensions:
        logger.info("analysis_agent: decompose_change by %s", dim)
        try:
            decomp = decompose_change(
                metric="trading_volume",
                date_start=date_start,
                date_end=date_end,
                comparison=comparison,
                by_dimension=dim,
                top_n=8,
                filters=filters,
            )
            results.append({"tool": "decompose_change", "dimension": dim, "data": decomp})
        except Exception:
            logger.exception("analysis_agent: decompose_change by %s failed", dim)

    return {
        "analysis_data": {"tool_results": results},
        "mode": "analyze",
    }


def _node_analysis_generate_text(state: AgentState) -> dict:
    """Generate analysis text via LLM using tool results as data context.

    Reuses the prompt builders from agent.orchestrator for consistent output format.
    """
    from agent.orchestrator import _build_system_prompt, _build_data_prompt
    from llm_parser.llm_client import llm_chat

    data = state.analysis_data or {}
    tool_results = data.get("tool_results", [])

    if not tool_results:
        return {
            "summary": "",
            "mode": "analyze",
        }

    system_prompt = _build_system_prompt()
    user_prompt = _build_data_prompt(state.user_text, state.parsed_params, tool_results)

    summary = llm_chat(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        task="analysis_text",
        request_id=state.request_id,
        session_id=state.session_id,
        timeout=120,
    )

    return {
        "summary": summary or "",
        "mode": "analyze",
    }


def _node_analysis_format(state: AgentState) -> dict:
    """Format analysis output for frontend consumption.

    Produces the same shape as the orchestrator's run_analysis return value
    so the frontend ResultCard can render it consistently.
    """
    data = state.analysis_data or {}
    return {
        "summary": state.summary,
        "insights": [],
        "mode": "analyze",
        "analysis_data": {
            "tool_calls": data.get("tool_results", []),
        },
    }
