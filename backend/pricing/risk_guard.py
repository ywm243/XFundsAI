# backend/pricing/risk_guard.py
"""风控校验 + 风险提示生成"""

from __future__ import annotations
from typing import Optional

from .models import QuoteResult
from .pricing_rules import RISK_REJECT_REASONS, REJECTION_TEMPLATES


class RiskGuard:
    """询报价风控校验"""

    def pre_check(self, customer_id: str, customer_info: dict | None) -> tuple[bool, Optional[str]]:
        """询价前风控预检，返回 (是否通过, 拒绝原因)"""
        if not customer_info:
            return True, None

        status = customer_info.get("account_status", "ACTIVE")
        if status == "FROZEN":
            return False, RISK_REJECT_REASONS["ACCOUNT_FROZEN"]
        if status == "CLOSED":
            return False, "账户已销户，暂不支持询价服务。"
        return True, None

    def post_check(self, quote: QuoteResult) -> tuple[bool, Optional[str]]:
        """询价后价格异常检测"""
        if quote.customer_rate <= 0:
            return False, "报价异常：价格为0或负值，请联系系统管理员。"
        if quote.spread_bp < 0:
            return False, "报价异常：点差为负值，请联系系统管理员。"
        if quote.spread_bp > 1000:
            return False, "报价异常：点差过大，请联系系统管理员。"
        return True, None

    def need_risk_disclosure(self, customer_info: dict | None,
                             product_type: str) -> bool:
        """判断是否需要风险披露"""
        if not customer_info:
            return True
        customer_type = customer_info.get("customer_type", "NORMAL")
        if customer_type == "PROFESSIONAL":
            return False
        if product_type in ("FWD", "SWAP"):
            return True
        return False

    def get_risk_disclosure(self, product_type: str) -> dict:
        """获取产品风险披露内容"""
        disclosures = {
            "FWD": {
                "title": "远期结售汇风险提示",
                "items": [
                    "汇率波动可能导致实际成本与预期不同",
                    "提前平仓可能产生额外费用",
                    "到期必须履约交割",
                ],
            },
            "SWAP": {
                "title": "外汇掉期风险提示",
                "items": [
                    "近端和远端两次交割均需履约",
                    "掉期定价受利率差影响",
                    "提前平仓可能产生额外费用",
                ],
            },
        }
        return disclosures.get(product_type, {"title": "风险提示", "items": ["请谨慎交易"]})

    def translate_rejection(self, error_code: str) -> str:
        """翻译下单拒绝原因为客户可读文案"""
        return REJECTION_TEMPLATES.get(
            error_code,
            f"交易失败：{error_code}" if error_code else "交易失败，请稍后重试"
        )

    def is_novice(self, customer_info: dict | None) -> bool:
        """判断是否为小白客户"""
        if not customer_info:
            return True
        return customer_info.get("customer_type", "NORMAL") == "NOVICE"
