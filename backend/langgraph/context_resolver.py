# backend/langgraph/context_resolver.py
"""Context Resolver — LLM-based full conversation history analysis."""

import asyncio
import json
import logging
import os
import re
from openai import OpenAI
from langgraph.state import AgentState
from langgraph.context_assembler import ContextAssembler

logger = logging.getLogger(__name__)


def _resolve_fallback(state: AgentState) -> dict:
    """Fallback: take most recent assistant date from context."""
    ctx = state.context or []
    for msg in reversed(ctx):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            try:
                prev = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            # Previous API response may nest dates inside "params"
            prev_data = prev.get("params", prev)
            ds = prev_data.get("date_start", "") or prev.get("date_start", "") or ""
            de = prev_data.get("date_end", "") or prev.get("date_end", "") or ""
            if ds and de:
                return {
                    "resolved_params": {"date_start": ds, "date_end": de},
                    "inherited_fields": ["date_start", "date_end"],
                    "context_confidence": 0.6,
                    "needs_confirm": [],
                }
    return {
        "resolved_params": {},
        "inherited_fields": [],
        "context_confidence": 0.0,
        "needs_confirm": [],
    }


def resolve_context(state: AgentState) -> dict:
    """Analyze conversation history to infer inherited parameters.

    Priority: ContextAssembler (Wiki + history + memory),
    falls back to LLM-based analysis, then rule-based last-turn matching.
    """
    # ── Priority path: ContextAssembler (Wiki + conversation + memory) ──
    wiki_store = None
    try:
        from wiki.store import wiki_store as _ws  # noqa: F811
        wiki_store = _ws
    except Exception:
        pass

    assembler = ContextAssembler()
    assembled_ctx = None
    try:
        try:
            loop = asyncio.get_running_loop()
            # Running in async context — schedule on existing loop
            future = asyncio.run_coroutine_threadsafe(
                assembler.assemble(
                    state.session_id or "",
                    state.user_text or "",
                    (state.router_decision or {}).get("agent", "BI"),
                    wiki_store,
                ),
                loop,
            )
            assembled_ctx = future.result(timeout=3)
        except RuntimeError:
            # No running loop — use asyncio.run directly
            assembled_ctx = asyncio.run(assembler.assemble(
                state.session_id or "",
                state.user_text or "",
                (state.router_decision or {}).get("agent", "BI"),
                wiki_store,
            ))
    except Exception as e:
        logger.warning("ContextAssembler failed, falling back to LLM path: %s", e)

    if assembled_ctx and assembled_ctx.resolved_params:
        return {
            "resolved_params": assembled_ctx.resolved_params,
            "inherited_fields": list(assembled_ctx.resolved_params.keys()),
            "context_confidence": 0.9 if assembled_ctx.wiki_hit else 0.7,
            "needs_confirm": [],
            "_assembled_context": assembled_ctx.total_context,
            "wiki_hit": assembled_ctx.wiki_hit,
        }

    # ── Fallback: original LLM + rule-based path ──
    context_list = state.context or []
    if not context_list:
        return {
            "resolved_params": {},
            "inherited_fields": [],
            "context_confidence": 1.0,
            "needs_confirm": [],
        }

    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")
    model = os.environ.get("LLM_MODEL", "")

    if not api_key or not base_url or not model:
        return _resolve_fallback(state)

    # Build conversation history for LLM prompt
    history_lines = []
    for msg in context_list[-20:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            history_lines.append(f"{role}: {content[:200]}")

    history_text = "\n".join(history_lines)

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[{"role": "user", "content": (
                "你是对话上下文分析器。根据完整对话历史，推断当前查询的完整参数。\n\n"
                "## 上下文继承规则\n"
                "1. 如果当前查询的实体/日期/维度为空，向前查找最近的相关轮次\n"
                "2. 如果中途切换了主题（如从交易量→汇率），不要继承无关参数\n"
                "3. '呢''它们的''也''还是'等词表示承接上文\n"
                "4. 不确定的参数留空，不要猜\n"
                "5. 如果历史上讨论了多个主题，优先匹配最近的主题\n\n"
                "## 完整对话历史\n"
                f"{history_text}\n\n"
                "## 当前查询\n"
                f"{state.user_text}\n\n"
                "## 输出 JSON\n"
                '{"resolved":{"date_start":"","date_end":"","bank_name":"",'
                '"cust_name":"","product_type":""},'
                '"inherited_fields":[],"confidence":0.0,"needs_confirm":[]}'
            )}],
            timeout=15,
        )
        content = resp.choices[0].message.content or "{}"
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return _resolve_fallback(state)

        result = json.loads(m.group(1))
        return {
            "resolved_params": result.get("resolved", {}),
            "inherited_fields": result.get("inherited_fields", []),
            "context_confidence": result.get("confidence", 0.0),
            "needs_confirm": result.get("needs_confirm", []),
        }
    except Exception as exc:
        logger.warning("Context Resolver LLM failed: %s", exc)
        return _resolve_fallback(state)
