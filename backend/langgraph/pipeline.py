# backend/langgraph/pipeline.py
"""Main LangGraph DAG — Context Resolver → Router → Agent → Validator → Format."""

import logging
from langgraph.graph import StateGraph
from langgraph.state import AgentState
from langgraph.agents.bi_agent import build_bi_subgraph
from langgraph.agents.pricing_agent import build_pricing_subgraph
from langgraph.context_resolver import resolve_context
from langgraph.router import route_to_agent
from langgraph.validators import node_validate

logger = logging.getLogger(__name__)


def _route_agent(state: AgentState) -> str:
    """Route to the appropriate agent sub-graph based on router decision."""
    decision = state.router_decision or {}
    status = decision.get("status", "ok")
    if status in ("rejected", "confirm"):
        return "__end__"
    agent = decision.get("agent", "BI")
    if agent == "PRICING":
        return "pricing_agent"
    return "bi_agent"


def build_main_graph() -> StateGraph:
    """Build the full orchestration graph."""
    builder = StateGraph(AgentState)

    # Nodes
    builder.add_node("context_resolver", resolve_context)
    builder.add_node("router", route_to_agent)
    builder.add_node("bi_agent", build_bi_subgraph())
    builder.add_node("pricing_agent", build_pricing_subgraph())
    builder.add_node("validate", node_validate)

    # Entry point → Context Resolver
    builder.set_entry_point("context_resolver")
    builder.add_edge("context_resolver", "router")

    # BI Agent → Validator
    builder.add_edge("bi_agent", "validate")
    builder.add_edge("pricing_agent", "validate")

    # Router → conditional agent dispatch
    builder.add_conditional_edges(
        "router",
        _route_agent,
        {"bi_agent": "bi_agent", "pricing_agent": "pricing_agent", "__end__": "__end__"},
    )

    return builder.compile()
