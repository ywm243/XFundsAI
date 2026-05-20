# backend/langgraph/router.py
"""Router — 3-gate security: keyword match, entity validation, parameter completeness."""

import logging
import re
from langgraph.state import AgentState
from langgraph.registry import match_keywords, check_not_capabilities, match_pricing_keywords

logger = logging.getLogger(__name__)

# Keywords that signal the user is asking about a specific product
_PRODUCT_KEYWORDS = ["外汇", "即期", "远期", "掉期", "期权", "结汇", "售汇", "spot", "forward"]

# Keywords that signal a time-bound query
_TIME_KEYWORDS = ["月", "年", "日", "周", "今天", "昨天", "明天", "本季度",
                  "同比", "环比", "yoy", "mom", "最近"]

# Keywords that signal an analysis/attribution query
_ANALYSIS_KEYWORDS = {"为什么", "原因", "分析", "怎么回事", "解释", "怎么变化", "趋势说明"}


def _check_bi_completeness(text: str, resolved: dict) -> list[str]:
    """Check BI query parameter completeness.

    Returns list of missing parameter names (empty = complete).
    """
    needs = []
    text_lower = text.lower()

    # product_type — essential for any BI query
    if not resolved.get("product_type"):
        if not any(kw in text_lower for kw in _PRODUCT_KEYWORDS):
            needs.append("product_type")

    # date_range — flag if text implies time but no dates resolved,
    #              and text doesn't contain a concrete date like "2024年1月"
    if not resolved.get("date_start") or not resolved.get("date_end"):
        has_time_ref = any(kw in text_lower for kw in _TIME_KEYWORDS)
        has_concrete_date = bool(re.search(r'\d{4}年\d{1,2}月', text_lower))
        if has_time_ref and not has_concrete_date:
            needs.append("date_range")

    # bank_name — text mentions a specific bank but not resolved
    specific_banks = ["工行", "中行", "建行", "农行", "招行",
                      "工商银行", "中国银行", "建设银行", "农业银行", "招商银行"]
    if any(kw in text_lower for kw in specific_banks) and not resolved.get("bank_name"):
        needs.append("bank_name")

    return needs


def _match_analysis_keywords(text: str) -> float:
    """Score analysis intent by keyword match ratio."""
    if not text:
        return 0.0
    hits = sum(1 for kw in _ANALYSIS_KEYWORDS if kw in text)
    return hits / max(len(_ANALYSIS_KEYWORDS), 1)


def route_to_agent(state: AgentState) -> dict:
    """Run three security gates to decide routing.

    Returns updated router_decision dict.
    """
    text = state.user_text

    # Pricing domain check — if pricing keywords dominate, route to PRICING agent
    pricing_score = match_pricing_keywords(text)
    bi_scores = match_keywords(text)
    bi_score = max(bi_scores.values()) if bi_scores else 0

    if pricing_score > bi_score and pricing_score > 0.1:
        return {
            "router_decision": {
                "status": "ok",
                "agent": "PRICING",
                "confidence": pricing_score,
                "reason": "",
                "message": "",
            }
        }

    scores = bi_scores

    # Analysis domain check — if analysis keywords dominate BI keywords, route to ANALYSIS agent
    analysis_score = _match_analysis_keywords(text)
    bi_score = scores.get("BI", 0)
    if analysis_score > 0.3 and analysis_score > bi_score:
        return {
            "router_decision": {
                "status": "ok",
                "agent": "ANALYSIS",
                "confidence": round(analysis_score, 2),
                "reason": "analysis_intent_detected",
                "message": "",
            }
        }

    # Gate 1: lowest confidence. If no agent scores above 0.05 → unknown topic
    max_score = max(scores.values()) if scores else 0
    if max_score < 0.05:
        return {
            "router_decision": {
                "status": "rejected",
                "agent": "fallback",
                "confidence": 0.0,
                "reason": "out_of_scope",
                "message": "该查询超出我目前的分析范围。请尝试查询交易量、排名或套保率数据。",
            }
        }

    # Gate 2: NOT_capabilities check (hard block)
    blocked = check_not_capabilities(text)
    if blocked:
        return {
            "router_decision": {
                "status": "rejected",
                "agent": blocked[0],
                "confidence": 0.0,
                "reason": "not_capability",
                "message": "抱歉，我不支持该类查询。可以查询交易数据或排名信息。",
            }
        }

    # Gate 3: parameter completeness check
    best_agent = max(scores, key=scores.get)
    resolved = state.resolved_params or {}
    needs_confirm: list[str] = []

    if best_agent == "BI":
        needs_confirm = _check_bi_completeness(text, resolved)

    if needs_confirm:
        return {
            "router_decision": {
                "status": "confirm",
                "agent": best_agent,
                "confidence": round(max_score, 2),
                "reason": "incomplete_params",
                "message": "请确认或补充查询参数",
                "needs_confirm": needs_confirm,
            }
        }

    return {
        "router_decision": {
            "status": "ok",
            "agent": best_agent,
            "confidence": round(max_score, 2),
            "reason": "",
            "message": "",
        }
    }
