"""Agent memory persistence layer.

Replaces the in-memory dict approach with SQLite-backed session storage.
Supports: session CRUD, turn recording, context retrieval, memory summaries.
"""

import logging
from typing import Optional

from db import mysql_store

logger = logging.getLogger(__name__)


class AgentMemory:
    """SQLite-backed agent memory for multi-turn conversations.

    Usage:
        memory = AgentMemory()
        memory.ensure_session("session-001", agent_type="bi")
        memory.add_turn("session-001", 0, "本月交易量", parsed_params={...})
        ctx = memory.get_context("session-001", last_n=3)
    """

    def __init__(self, agent_type: str = "bi"):
        self.agent_type = agent_type

    # ---- Session ----

    def ensure_session(self, session_id: str, user_id: str = "default") -> None:
        mysql_store.create_session(session_id, self.agent_type, user_id)

    # ---- Turns ----

    def add_turn(self, session_id: str, turn_index: int, user_query: str,
                 parsed_params: dict | None = None,
                 executed_sql: str | None = None,
                 result_summary: str | None = None,
                 user_feedback: str | None = None) -> int:
        """Record a conversation turn. Returns turn id."""
        return mysql_store.add_turn(
            session_id=session_id,
            turn_index=turn_index,
            user_query=user_query,
            parsed_params=parsed_params,
            executed_sql=executed_sql,
            result_summary=result_summary,
            user_feedback=user_feedback,
        )

    def get_context(self, session_id: str, last_n: int = 3) -> list[dict]:
        """Get the last N turns for LLM context injection."""
        turns = mysql_store.get_session_context(session_id, last_n)
        return turns

    def build_context_prompt(self, session_id: str, last_n: int = 3) -> str:
        """Build a context prompt from recent conversation turns.

        Format:
            历史对话：
            用户：本月交易量
            系统：[已解析] product_type=all, aggregate=true, ...
            用户：上月呢
            系统：[已解析] product_type=all, aggregate=true, ... (继承上下文)
        """
        turns = self.get_context(session_id, last_n)
        if not turns:
            return ""

        lines = ["历史对话："]
        for t in turns:
            lines.append(f"用户：{t['user_query']}")
            if t.get("parsed_params"):
                lines.append(f"系统：[已解析] {t['parsed_params']}")
        return "\n".join(lines)

    def get_turn_count(self, session_id: str) -> int:
        """Get the number of turns in a session."""
        turns = mysql_store.get_session_context(session_id, last_n=1000)
        return len(turns)

    # ---- Summaries ----

    def should_summarize(self, session_id: str) -> bool:
        """Check if the session needs summarization (every 5 turns)."""
        count = self.get_turn_count(session_id)
        return count > 0 and count % 5 == 0

    def add_summary(self, session_id: str, summary_type: str,
                    content: dict, source_turns: str | None = None) -> int:
        """Store a memory summary."""
        return mysql_store.add_summary(
            session_id=session_id,
            summary_type=summary_type,
            content=content,
            source_turns=source_turns,
        )

    def find_similar(self, query_text: str, limit: int = 3) -> list[dict]:
        """Find similar historical queries by keyword overlap.

        Simple approach: check keyword overlap in recent turns.
        Can be upgraded to vector similarity later (Phase 3).
        """
        # For now, use keyword overlap on the query text
        # Future: replace with Chroma vector search
        import sqlite3
        conn = mysql_store.get_conn()
        try:
            rows = conn.execute(
                """SELECT DISTINCT user_query, parsed_params FROM turns
                   WHERE agent_type=? AND user_query IS NOT NULL
                   ORDER BY created_at DESC LIMIT 200""",
                (self.agent_type,),
            ).fetchall()

            query_words = set(query_text)
            scored = []
            for row in rows:
                row_words = set(row["user_query"] or "")
                overlap = len(query_words & row_words) / max(len(query_words), 1)
                if overlap > 0.3:
                    scored.append((overlap, dict(row)))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [item for _, item in scored[:limit]]
        finally:
            conn.close()
