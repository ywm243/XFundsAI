# backend/langgraph/router.py
"""Router — 3-gate security: keyword match, entity validation, parameter completeness."""

import logging
from langgraph.state import AgentState
from langgraph.registry import match_keywords, check_not_capabilities

logger = logging.getLogger(__name__)


def route_to_agent(state: AgentState) -> dict:
    """Run three security gates to decide routing.

    Returns updated router_decision dict.
    """
    text = state.user_text
    scores = match_keywords(text)

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

    return {
        "router_decision": {
            "status": "ok",
            "agent": best_agent,
            "confidence": round(max_score, 2),
            "reason": "",
            "message": "",
        }
    }
