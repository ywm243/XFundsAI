"""LangGraph pricing agent sub-graph — 询报价意图解析 + 询价执行"""

from __future__ import annotations
import json
import logging

from langgraph.graph import StateGraph
from langgraph.state import AgentState
from llm_parser.llm_client import llm_parse
from pricing.routes import get_pricing_service
from pricing.models import PricingIntent, IntentType

logger = logging.getLogger(__name__)


PRICING_KW_SET = {
    "询价", "报价", "结汇", "购汇", "成交", "下单", "点差",
    "即期", "远期", "掉期", "比价", "对比", "情景",
}
PAIR_MAP = {"美元": "USD/CNY", "欧元": "EUR/CNY", "英镑": "GBP/CNY", "日元": "JPY/CNY"}
TENOR_MAP = {
    "1M": "1M", "1个月": "1M", "3M": "3M", "3个月": "3M",
    "6M": "6M", "6个月": "6M", "1Y": "1Y", "1年": "1Y",
}


def _extract_pricing_intent(text: str) -> PricingIntent:
    """Rule-based pricing intent extraction from Chinese text."""
    intent = PricingIntent()
    text_lower = text.lower()

    if "掉期" in text:
        intent.product_type = "SWAP"
    elif "远期" in text:
        intent.product_type = "FWD"
    elif "即期" in text:
        intent.product_type = "SPOT"

    if any(w in text for w in ["结汇", "银行买入"]):
        intent.direction = "B"
    elif any(w in text for w in ["购汇", "银行卖出"]):
        intent.direction = "S"

    for cn, pair in PAIR_MAP.items():
        if cn in text:
            intent.currency_pair = pair
            break

    for cn, tenor in TENOR_MAP.items():
        if cn in text:
            intent.tenor = tenor
            break

    if any(w in text for w in ["买", "卖", "成交", "下单", "交易"]) and \
       any(w in text for w in ["万", "金额", "100", "200", "500"]):
        intent.intent_type = IntentType.DIRECT_TRADE
    elif any(w in text for w in ["比价", "对比", "vs", "VS"]):
        intent.intent_type = IntentType.COMPARE
    elif "情景" in text:
        intent.intent_type = IntentType.SCENARIO
    elif any(w in text for w in ["和", "与", "以及"]) and not intent.compare_products:
        intent.intent_type = IntentType.MULTI

    return intent


async def _node_parse_pricing(state: AgentState) -> dict:
    """Parse pricing intent from user text — rule-first, LLM fallback."""
    text = state.user_text

    has_price_kw = sum(1 for kw in PRICING_KW_SET if kw in text)
    has_pair = any(pair in text for pair in PAIR_MAP)
    confidence = min((has_price_kw * 0.25) + (0.4 if has_pair else 0.0), 1.0)

    if confidence >= 0.6:
        intent = _extract_pricing_intent(text)
        pipeline = f"rule(confidence={confidence:.2f})"
    else:
        from pricing.pricing_rules import PRICING_SYSTEM_PROMPT
        llm_result = llm_parse(text, PRICING_SYSTEM_PROMPT)
        if llm_result:
            try:
                intent_data = json.loads(llm_result) if isinstance(llm_result, str) else llm_result
                intent = PricingIntent(**intent_data)
                pipeline = "llm"
            except Exception:
                intent = _extract_pricing_intent(text)
                pipeline = "llm_fallback"
        else:
            intent = _extract_pricing_intent(text)
            pipeline = "rule_fallback"

    intent.pipeline = pipeline
    intent.confidence = confidence

    return {
        "parsed_params": {
            "intent_type": intent.intent_type.value,
            "product_type": intent.product_type,
            "currency_pair": intent.currency_pair,
            "direction": intent.direction,
            "amount": intent.amount,
            "tenor": intent.tenor,
        },
    }


async def _node_pricing_inquiry(state: AgentState) -> dict:
    """Execute pricing inquiry via PricingService."""
    intent_data = state.parsed_params or {}
    intent = PricingIntent(
        intent_type=IntentType(intent_data.get("intent_type", "SINGLE")),
        product_type=intent_data.get("product_type", ""),
        currency_pair=intent_data.get("currency_pair", ""),
        direction=intent_data.get("direction", ""),
        amount=intent_data.get("amount"),
        tenor=intent_data.get("tenor", ""),
    )

    service = get_pricing_service()
    result = await service.handle_inquiry(
        text=state.user_text,
        intent=intent,
        customer_id="default",
        session_id=state.session_id,
        context=state.context,
    )

    return {"pricing_result": result}


async def _node_pricing_validate(state: AgentState) -> dict:
    """Validate pricing response."""
    result = state.pricing_result
    if not result:
        return {"error": "询价未返回结果"}
    if result.get("mode") == "error":
        return {"error": result.get("error", "询价异常")}
    if result.get("mode") == "follow_up":
        return {}
    return {"validation_warnings": []}


def build_pricing_subgraph() -> StateGraph:
    builder = StateGraph(AgentState)
    builder.add_node("parse", _node_parse_pricing)
    builder.add_node("inquiry", _node_pricing_inquiry)
    builder.add_node("validate", _node_pricing_validate)
    builder.set_entry_point("parse")
    builder.add_edge("parse", "inquiry")
    builder.add_edge("inquiry", "validate")
    return builder.compile()
