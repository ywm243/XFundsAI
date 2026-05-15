# backend/langgraph/graph/__init__.py
"""Main LangGraph DAG — resolves installed langgraph.graph subpackage first."""

import os

# ── Resolve subpackage shadowing ───────────────────────────────────────────
# Our local graph/ directory shadows the installed langgraph.graph subpackage.
_pkg_path = os.path.dirname(os.path.abspath(__file__))
_OUR_PARENT = os.path.dirname(_pkg_path)

for _site_dir in __import__("site").getsitepackages():
    _installed = os.path.join(_site_dir, "langgraph", "graph")
    if os.path.isdir(_installed) and os.path.exists(
        os.path.join(_installed, "__init__.py")
    ):
        # Installed path first so StateGraph etc. resolve from there
        __path__ = [_installed, _pkg_path]  # type: ignore[valid-type]
        break
else:
    __path__ = [_pkg_path]  # type: ignore[valid-type]

# ── Now safe to import from the installed langgraph.graph ──────────────────
import logging
from langgraph.graph import StateGraph
from langgraph.state import AgentState
from langgraph.agents.bi_agent import build_bi_subgraph

logger = logging.getLogger(__name__)


def _route_agent(state: AgentState) -> str:
    """Route to the appropriate agent sub-graph based on router decision."""
    decision = state.router_decision or {}
    status = decision.get("status", "ok")
    if status in ("rejected", "confirm"):
        return "__end__"
    return "bi_agent"


def build_main_graph() -> StateGraph:
    """Build the full orchestration graph."""
    builder = StateGraph(AgentState)

    # Nodes
    builder.add_node("bi_agent", build_bi_subgraph())

    # Entry point
    builder.set_entry_point("bi_agent")

    return builder.compile()
