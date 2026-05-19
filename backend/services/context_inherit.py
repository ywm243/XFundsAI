"""Context inheritance service — inherit params/dates from conversation history.

Extracted from app.py to enable reuse by langgraph/bi_agent.py without
circular imports.

Strategy: "follow-up detection + blacklist"
- If the current query is a follow-up (同比呢？环比呢？换个维度？), inherit ALL
  params including special_states/lifecycle_status.
- If the current query is a new independent question, only inherit framework
  params (bank_name, product_type, etc.) — never inherit query-specific
  filters like special_states, lifecycle_status, trade_class.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# Framework params: safe to inherit for both follow-ups and new queries.
_INHERIT_PARAMS = {
    "bank_name", "cust_name", "product_type", "aggregate", "dimension",
    "top_n", "amount_filter", "hedge_ratio", "appid", "profit_type",
}

# Query-specific params: only inherited when the current query is a follow-up.
_FOLLOW_UP_ONLY_PARAMS = {"special_states", "lifecycle_status", "trade_class"}

# Patterns that indicate a follow-up question (not a new independent query).
_FOLLOW_UP_PATTERNS = re.compile(
    r"(?:同比|环比|对比|对比期|变化|增长|下降|涨|跌|换|呢|再|还|也|那|继续|其他|别的|"
    r"换个|按.*分|按.*看|按.*拆|维度|排名|top|前\d+)",
    re.IGNORECASE,
)


def _is_follow_up(text: str) -> bool:
    """Return True if the query text looks like a follow-up, not a new question."""
    return bool(_FOLLOW_UP_PATTERNS.search(text))


def inherit_params_from_context(context: list | None, current: dict, user_text: str = "") -> dict | None:
    """Inherit structural query params from the previous assistant turn.

    Args:
        context: Conversation history (list of {role, content} dicts).
        current: Parsed params for the current query.
        user_text: The raw user query text, used for follow-up detection.
    """
    if not context or not isinstance(context, list):
        return None

    is_followup = _is_follow_up(user_text)
    inheritable_keys = _INHERIT_PARAMS | (_FOLLOW_UP_ONLY_PARAMS if is_followup else set())

    for msg in reversed(context):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            try:
                prev = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            prev_params = prev.get("params", prev) or prev
            inherited = {}
            for key in inheritable_keys:
                val = prev_params.get(key)
                if val is not None and val != "" and val != False and val != []:
                    current_val = current.get(key)
                    if current_val is None or current_val == "" or current_val == False or current_val == []:
                        inherited[key] = val
            if inherited:
                logger.info("Context inherit (followup=%s): %s", is_followup, list(inherited.keys()))
            return inherited if inherited else None
    return None


def inherit_dates_from_context(context: list | None) -> dict | None:
    """Try to inherit date range from the most recent assistant turn in context.

    Returns {date_start, date_end} or None if no dates found.
    """
    if not context or not isinstance(context, list):
        return None
    for msg in reversed(context):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            try:
                prev = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            prev_data = prev.get("params", prev)
            ds = prev_data.get("date_start", "") or prev.get("date_start", "") or ""
            de = prev_data.get("date_end", "") or prev.get("date_end", "") or ""
            if ds and de:
                return {"date_start": ds, "date_end": de}
    return None
