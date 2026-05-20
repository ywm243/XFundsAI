"""Agent memory persistence layer.

Replaces the in-memory dict approach with SQL-backed session storage.
Supports: session CRUD, turn recording, context retrieval, memory summaries.
"""

import logging
import math
from collections import Counter
from typing import Optional

from db import mysql_store

logger = logging.getLogger(__name__)


# ── Char n-gram similarity (pure Python, no deps) ──────────────────────
# Character 2/3/4-grams handle Chinese text naturally because they capture
# sub-word patterns without needing a tokenizer like jieba.


def _char_ngrams(text: str, n_range: tuple = (2, 4)) -> Counter:
    """Extract character n-grams as a sparse frequency vector."""
    ngrams = Counter()
    for n in range(n_range[0], n_range[1] + 1):
        for i in range(len(text) - n + 1):
            ngrams[text[i:i + n]] += 1
    return ngrams


def _cosine_similarity(a: Counter, b: Counter) -> float:
    """Cosine similarity between two sparse Counter vectors."""
    dot = sum(a[k] * b[k] for k in a if k in b)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


class AgentMemory:
    """Agent memory for multi-turn conversations.

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
        """Find similar historical queries by char n-gram cosine similarity.

        Pure-Python vector search — no external embedding service needed.
        Searches the last 200 turns across all sessions of this agent type.
        Can be upgraded to Chroma vector search later (Phase 3).
        """
        if not query_text or not query_text.strip():
            return []

        conn = mysql_store.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT t.user_query, t.parsed_params
                    FROM turns t
                    JOIN sessions s ON s.id = t.session_id
                    WHERE s.agent_type = %s AND t.user_query IS NOT NULL
                    ORDER BY t.created_at DESC LIMIT 200
                """, (self.agent_type,))
                rows = cur.fetchall()

            query_vec = _char_ngrams(query_text.strip())
            scored = []
            for row in rows:
                text = (row["user_query"] or "").strip()
                if not text:
                    continue
                row_vec = _char_ngrams(text)
                sim = _cosine_similarity(query_vec, row_vec)
                if sim > 0.25:
                    scored.append((sim, dict(row)))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [item for _, item in scored[:limit]]
        finally:
            conn.close()

    # ---- Wiki sync ----

    def add_turn_with_wiki(self, session_id: str, turn_index: int, user_query: str,
                           parsed_params: dict | None = None,
                           executed_sql: str | None = None,
                           result_summary: str | None = None,
                           user_feedback: str | None = None,
                           customer_id: str = "") -> int:
        """Record a turn AND sync important turns to wiki.

        A turn is 'important' if it has user_feedback or pricing-related data.
        """
        turn_id = self.add_turn(session_id, turn_index, user_query,
                                parsed_params, executed_sql, result_summary, user_feedback)

        is_important = (user_feedback == "positive" or
                        (parsed_params and parsed_params.get("product_type")))
        if is_important and customer_id:
            try:
                from wiki.store import wiki_store
                slug = f"entity-{customer_id}"
                existing = wiki_store.get(slug)
                fm = existing.get("frontmatter", {}) if existing else {}
                if isinstance(fm, str):
                    import json as _json
                    fm = _json.loads(fm)
                queries = fm.get("recent_queries", [])
                queries.append({"q": user_query, "params": parsed_params})
                fm["recent_queries"] = queries[-10:]
                body = existing["body"] if existing else f"客户 {customer_id} 的画像页面。"
                wiki_store.save(
                    slug=slug, title=f"客户 {customer_id}", page_type="entity",
                    body=body, frontmatter=fm, tags=["customer"],
                )
            except Exception:
                pass

        return turn_id
