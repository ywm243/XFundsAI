"""SessionStrategy — 根据会话状态自适应调整策略。升级不降级。"""


class SessionStrategy:
    """根据会话状态调整模型和上下文策略

    核心原则: 升级不降级。复杂场景用更强的模型和更深的上下文。
    """

    def __init__(self):
        self._memory = None

    @property
    def memory(self):
        if self._memory is None:
            from backend.memory.store import AgentMemory
            self._memory = AgentMemory()
        return self._memory

    def get_strategy(self, session_id: str) -> dict:
        turn_count = self._get_turn_count(session_id)
        complexity = self._estimate_complexity(session_id)

        if turn_count <= 3 and complexity == "simple":
            return {
                "model_tier": "flash",
                "context_depth": 3,
                "wiki_injection": True,
                "summary_mode": "none",
            }
        if turn_count <= 10:
            return {
                "model_tier": "flash",
                "context_depth": 5,
                "wiki_injection": True,
                "summary_mode": "compress_old",
            }
        # 长会话/复杂 → 升级到 Pro
        return {
            "model_tier": "pro",
            "context_depth": 10,
            "wiki_injection": True,
            "summary_mode": "llm_summary",
        }

    def _get_turn_count(self, session_id: str) -> int:
        try:
            return self.memory.get_turn_count(session_id)
        except Exception:
            return 0

    def _estimate_complexity(self, session_id: str) -> str:
        try:
            recent = self.memory.get_context(session_id, last_n=3)
        except Exception:
            return "simple"
        for t in recent:
            params = t.get("parsed_params", {})
            if params.get("comparison") or params.get("hedge_ratio") \
               or params.get("aggregate"):
                return "complex"
        return "simple"
