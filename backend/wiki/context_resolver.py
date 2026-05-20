"""Unified context resolver — wiki-first + conversation fallback."""
import logging
from typing import Optional
from .query import get_customer_profile, search_concepts

logger = logging.getLogger(__name__)

def resolve_bi_context(customer_id: str, current_params: dict,
                       conversation_context: list | None,
                       user_text: str = "") -> dict:
    """Resolve BI query context using wiki + conversation history."""
    inherited = {}

    # 1. Customer profile from wiki
    if customer_id:
        profile = get_customer_profile(customer_id)
        if profile:
            fm = profile.get("frontmatter", {})
            for key in ("dimension", "bank_name", "product_type", "appid"):
                if not current_params.get(key) and fm.get(key):
                    inherited[key] = fm[key]

    # 2. Conversation history fallback
    if conversation_context:
        from services.context_inherit import inherit_params_from_context, inherit_dates_from_context
        conv_inherited = inherit_params_from_context(conversation_context, current_params, user_text)
        if conv_inherited:
            for k, v in conv_inherited.items():
                if k not in inherited:
                    inherited[k] = v
        dates = inherit_dates_from_context(conversation_context)
        if dates and not current_params.get("date_start"):
            inherited.update(dates)

    if inherited:
        logger.info("Wiki context resolved: %s", list(inherited.keys()))
    return inherited

def resolve_pricing_context(customer_id: str, current_intent,
                             conversation_context: list | None) -> dict:
    """Resolve pricing intent context using wiki + conversation history."""
    inherited = {}

    # 1. Customer profile from wiki
    if customer_id:
        profile = get_customer_profile(customer_id)
        if profile:
            fm = profile.get("frontmatter", {})
            for key in ("product_type", "tenor", "currency_pair"):
                if not getattr(current_intent, key, None) and fm.get(key):
                    inherited[key] = fm[key]

    # 2. Conversation history fallback
    if conversation_context:
        from pricing.context_inherit import inherit_pricing_context
        updated = inherit_pricing_context(current_intent, conversation_context)
        for key in ("product_type", "tenor", "currency_pair", "direction"):
            if not inherited.get(key) and getattr(updated, key, None) and not getattr(current_intent, key, None):
                inherited[key] = getattr(updated, key)

    if inherited:
        logger.info("Wiki pricing context resolved: %s", list(inherited.keys()))
    return inherited
