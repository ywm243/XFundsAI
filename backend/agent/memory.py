"""Agent session memory — stores structured reasoning + tool call data per turn.

Multi-turn context: loads recent N turns for LLM to judge relevance.
"""

import json
import logging

from db import mysql_store

logger = logging.getLogger(__name__)


class AgentMemory:
    """Agent memory for analysis pipeline multi-turn context."""

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
        return mysql_store.get_agent_memory(
            session_id=session_id,
            last_n=last_n,
        )

    @staticmethod
    def build_context_prompt(session_id: str, last_n: int = 5) -> str:
        """Build a structured context prompt from recent turns."""
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
