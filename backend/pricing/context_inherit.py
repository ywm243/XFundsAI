# backend/pricing/context_inherit.py
"""询报价上下文继承 — 从对话历史补全缺失参数"""

from __future__ import annotations
from typing import Optional

from .models import PricingIntent, IntentType

PERSIST_PARAMS = {"currency_pair", "direction", "product_type", "tenor"}
FOLLOW_UP_SIGNALS = ["呢", "那个", "这个", "同样的", "也一样", "对比", "比价", "情景"]


def inherit_pricing_context(current: PricingIntent,
                            context: list[dict] | None) -> PricingIntent:
    """从对话历史继承缺失的询价参数"""
    if not context:
        return current

    prev_params = _extract_prev_inquiry(context)
    if not prev_params:
        return current

    is_followup = _is_followup(context)
    for key in PERSIST_PARAMS:
        if not getattr(current, key, None) and prev_params.get(key):
            setattr(current, key, prev_params[key])

    if is_followup and not current.product_type and prev_params.get("product_type"):
        current.product_type = prev_params["product_type"]

    return current


def inherit_customer_preference(current: PricingIntent,
                                history: list[dict]) -> PricingIntent:
    """从客户偏好记忆补充参数（不强制填充，仅做推荐参考）"""
    if not history:
        return current

    freq: dict[str, dict[str, int]] = {"product_type": {}, "tenor": {}, "currency_pair": {}}
    for item in history:
        for key in ("product_type", "tenor", "currency_pair"):
            val = str(item.get(key, ""))
            if val:
                freq[key][val] = freq[key].get(val, 0) + 1

    for key in ("product_type", "tenor", "currency_pair"):
        if not getattr(current, key, None) and freq[key]:
            top = max(freq[key], key=lambda k: freq[key][k])
            setattr(current, key, top)

    return current


def _extract_prev_inquiry(context: list[dict]) -> Optional[dict]:
    """从上下文中提取上一次询价参数"""
    for item in reversed(context):
        content = item.get("content", "")
        if isinstance(content, dict):
            params = content.get("params", content)
            if params.get("product_type") or params.get("direction"):
                return params
    return None


def _is_followup(context: list[dict]) -> bool:
    """判断当前输入是否为追问"""
    if not context:
        return False
    last_user = ""
    for item in reversed(context):
        if item.get("role") == "user":
            last_user = str(item.get("content", ""))
            break
    return any(sig in last_user for sig in FOLLOW_UP_SIGNALS)
