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

    # Pricing Agent 输出字段
    pricing_result: dict = field(default_factory=dict)
    pricing_insights: list[dict] = field(default_factory=list)

    # Analysis Agent 输出字段
    analysis_data: dict = field(default_factory=dict)
    mode: str = ""

    # Validator output
    validation_warnings: list[str] = field(default_factory=list)

    # Formatter output
    summary: str = ""
    chart_option: dict | None = None
    insights: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    # 每个 error dict: {node: str, code: str, message: str,
    #                   severity: "fatal"|"warning"|"info", timestamp: float}

    # 后向兼容属性
    @property
    def error(self) -> str:
        fatals = [e for e in self.errors if e["severity"] == "fatal"]
        if fatals:
            return fatals[0]["message"]
        if self.errors:
            return self.errors[-1]["message"]
        return ""

    @error.setter
    def error(self, value: str):
        if value:
            self.errors.append({
                "node": "unknown",
                "code": "Error",
                "message": value,
                "severity": "warning",
                "timestamp": 0.0,
            })
