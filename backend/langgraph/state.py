# backend/langgraph/state.py
"""AgentState — shared state for the LangGraph pipeline."""
from dataclasses import dataclass, field


@dataclass
class AgentState:
    """Pipeline state flowing through Context Resolver → Router → Agent → Validator."""

    # Input
    request_id: str = ""
    session_id: str = ""
    user_text: str = ""
    context: list[dict] | None = None  # optional frontend-provided context

    # Context Resolver output
    resolved_params: dict = field(default_factory=dict)
    inherited_fields: list[str] = field(default_factory=list)
    context_confidence: float = 0.0
    needs_confirm: list[str] = field(default_factory=list)

    # Router output
    router_decision: dict = field(default_factory=dict)

    # BI Agent output
    parsed_params: dict = field(default_factory=dict)
    pipeline: str = ""
    sql: str = ""
    sql_validated: bool = False
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    comparison: dict | None = None

    # Validator output
    validation_warnings: list[str] = field(default_factory=list)

    # Formatter output
    summary: str = ""
    chart_option: dict | None = None
    insights: list[dict] = field(default_factory=list)
    error: str = ""
