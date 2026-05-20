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

    def build_context_prompt(self, session_id: str, last_n: int = 3,
                             use_importance: bool = True) -> str:
        """Build a context prompt from conversation turns.

        When use_importance is True, high-importance turns are preferred
        over recent ones, keeping the most semantically useful context.

        Format:
            历史对话：
            用户：本月交易量
            系统：[已解析] product_type=all, aggregate=true, ...
            用户：上月呢
            系统：[已解析] product_type=all, aggregate=true, ... (继承上下文)
        """
        turns = self.get_turns(session_id)
        if not turns:
            return ""

        if use_importance:
            # 高 importance 轮次优先进入上下文
            turns = sorted(turns, key=lambda t: (-t.get("importance", 1), -t["turn_index"]))
        else:
            turns = sorted(turns, key=lambda t: t["turn_index"], reverse=True)

        # 分层: 最近 3 轮原始格式 + 更早用摘要
        recent_turns = turns[:min(3, last_n)]
        older_turns = turns[3:last_n] if last_n > 3 else []

        lines = []
        if recent_turns:
            lines.append("## 最近对话")
            for t in sorted(recent_turns, key=lambda x: x["turn_index"]):
                query = t.get("user_query", "")
                if query:
                    lines.append(f"用户: {query}")
                params = t.get("parsed_params", {})
                if params:
                    parts = []
                    for k, v in params.items():
                        if not k.startswith("_") and v:
                            parts.append(f"{k}={v}")
                    if parts:
                        lines.append(f"解析: {', '.join(parts)}")

        if older_turns:
            summaries = self.get_summaries(session_id)
            if summaries:
                lines.append("## 历史摘要")
                for s in summaries[-3:]:
                    content = s.get("content", "")
                    if isinstance(content, dict):
                        content = content.get("summary", str(content))
                    lines.append(str(content)[:300])

        return "\n".join(lines)

    def get_turn_count(self, session_id: str) -> int:
        """Get the number of turns in a session."""
        turns = mysql_store.get_session_context(session_id, last_n=1000)
        return len(turns)

    def get_turns(self, session_id: str) -> list[dict]:
        """Get all turns for a session."""
        return mysql_store.get_session_context(session_id, last_n=1000)

    # ---- Summaries ----

    def should_summarize(self, session_id: str) -> bool:
        """Check if the session needs summarization (every 5 turns)."""
        try:
            count = self.get_turn_count(session_id)
        except Exception:
            return False
        return count > 0 and count % 5 == 0

    async def generate_llm_summary(self, session_id: str) -> str:
        """Flash 生成压缩摘要 — 提炼信息而非砍内容"""
        try:
            turns = self.get_turns(session_id)[-5:]
        except Exception:
            return ""
        if not turns:
            return ""

        prompt = "将以下5轮对话压缩为一句话摘要，保留关键实体（产品、币种、金额）和查询意图：\n"
        for t in turns:
            query = t.get("user_query", "")[:80]
            if query:
                prompt += f"用户：{query}\n"

        try:
            from backend.llm_parser.llm_client import llm_chat
            summary = llm_chat(
                system_prompt="你是一个对话摘要生成器。输出一句中文摘要（50字以内），保留关键业务信息。",
                user_prompt=prompt,
                task="summary_generate",
                request_id=f"summary-{session_id}",
                session_id=session_id,
            )
            if summary:
                self.save_summary(session_id, "turn_group", {
                    "summary": summary,
                    "source_turns": [t["turn_index"] for t in turns],
                })
                return summary
        except Exception:
            pass

        # Fallback: 字段级摘要
        indices = [t["turn_index"] for t in turns]
        queries = [t.get("user_query", "")[:40] for t in turns]
        try:
            self.save_summary(session_id, "turn_group", {
                "turn_indices": indices,
                "queries": queries,
            })
        except Exception:
            pass
        return f"历史查询: {'; '.join(queries)}"

    def compute_importance(self, turn: dict) -> int:
        """Compute importance score for a conversation turn."""
        score = 1
        # User feedback
        feedback = turn.get("user_feedback", "")
        if feedback == "positive":
            score += 2
        elif feedback in ("negative", "correction"):
            score += 1
        # Has parsed parameters (meaningful query)
        params = turn.get("parsed_params", {})
        if params and isinstance(params, dict):
            score += 1
            # Pricing-related queries are more important
            if any(k in params for k in ("product_type", "buy_sell", "bank_name")):
                score += 1
        # Has SQL execution (data was fetched)
        if turn.get("executed_sql"):
            score += 1
        return min(score, 10)

    def add_summary(self, session_id: str, summary_type: str,
                    content: dict, source_turns: str | None = None) -> int:
        """Store a memory summary."""
        return mysql_store.add_summary(
            session_id=session_id,
            summary_type=summary_type,
            content=content,
            source_turns=source_turns,
        )

    def save_summary(self, session_id: str, summary_type: str,
                     content: dict) -> int:
        """Alias for add_summary."""
        return self.add_summary(session_id, summary_type, content)

    def get_summaries(self, session_id: str, last_n: int = 10) -> list[dict]:
        """Get recent memory summaries for a session."""
        try:
            return mysql_store.get_summaries(session_id, last_n)
        except Exception:
            return []

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
