"""Agent session memory — DEPRECATED, delegates to memory.store.AgentMemory.

This module is kept for backward compatibility. New code should use
memory.store.AgentMemory directly, which now supports wiki sync.
"""

import json
import warnings

from db import mysql_store

warnings.warn(
    "agent.memory.AgentMemory is deprecated. Use memory.store.AgentMemory instead.",
    DeprecationWarning,
    stacklevel=2,
)


class AgentMemory:
    """Backward-compatible wrapper — delegates to memory.store.AgentMemory."""

    @staticmethod
    def save(session_id: str, turn_id: int, user_query: str,
             structured_data: dict) -> int:
        return mysql_store.save_agent_memory(
            session_id=session_id,
            turn_id=turn_id,
            user_query=user_query,
            structured_data=structured_data,
        )

    @staticmethod
    def get_context(session_id: str, last_n: int = 5) -> list[dict]:
        return mysql_store.get_agent_memory(session_id, last_n)

    @staticmethod
    def build_context_prompt(session_id: str, last_n: int = 5) -> str:
        turns = mysql_store.get_agent_memory(session_id, last_n)
        if not turns:
            return ""
        lines = ["以下是历史对话中已经分析过的内容，供参考："]
        for t in turns:
            sd = t.get("structured_data") or {}
            tool_summaries = []
            for tc in sd.get("tool_calls", []):
                tool_summaries.append(f"{tc.get('tool', '')}({json.dumps(tc.get('params', {}), ensure_ascii=False)})")
            lines.append(f"- 用户问：{t['user_query']}")
            if tool_summaries:
                lines.append(f"  调用了：{'；'.join(tool_summaries)}")
            if sd.get("key_entities"):
                lines.append(f"  关键实体：{json.dumps(sd['key_entities'], ensure_ascii=False)}")
        return "\n".join(lines)
