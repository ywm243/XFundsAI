# backend/pricing/risk_guard.py
"""风控校验 + 风险提示生成"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

from .models import QuoteResult
from .pricing_rules import REJECTION_TEMPLATES


class RiskGuard:
    """询报价风控校验"""

    def __init__(self):
        self._rate_cache: dict[str, float] = {}  # customer_id → last_inquiry_timestamp
        self._rate_limit_seconds: int = 5
        self._thresholds: dict = {"SPOT": 50000000, "FWD": 50000000, "SWAP": 50000000}
        self._session_timeout: int = 5  # minutes

    def configure(self, thresholds: dict | None = None, rate_limit: int = 5, session_timeout: int = 5):
        if thresholds:
            self._thresholds.update(thresholds)
        self._rate_limit_seconds = rate_limit
        self._session_timeout = session_timeout

    def pre_check(self, customer_id: str, customer_info: dict | None,
                  product_type: str = "", amount: float = 0) -> tuple[bool, Optional[str]]:
        """询价前风控（demo：仅频率 + 金额阈值，其余暂不启用）"""

        # 频率控制（每客户 5 秒冷却）
        rate_ok, rate_remaining = self.check_rate_limit(customer_id)
        if not rate_ok:
            return False, f"询价频率过快，请{rate_remaining}秒后重试。"

        # 金额阈值
        if amount > 0:
            ok, reason = self.check_amount_threshold(amount, product_type or "SPOT")
            if not ok:
                return False, reason

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

    def check_amount_threshold(self, amount: float, product_type: str = "SPOT") -> tuple[bool, Optional[str]]:
        """规则1：超阈值金额转线下"""
        threshold = self._thresholds.get(product_type, 50000000)
        if amount > threshold:
            label = f"大额交易（等值≥{threshold/10000:.0f}万美元）需走线下询价通道，请联系客户经理。\n如需AI快速询价，请输入较小金额后重试。"
            return False, label
        return True, None

    def check_sanctions(self, customer_info: dict | None) -> tuple[bool, Optional[str]]:
        """规则9第1层：制裁/黑名单 — wiki 预检 + 名单模糊匹配"""
        if not customer_info:
            return True, None

        # 第 1 层：wiki 中已标记的制裁状态（静默拒绝）
        if customer_info.get("sanctions_status") == "BLOCKED":
            return False, "暂不支持询价服务"

        # 第 2 层：本地制裁名单模糊匹配
        customer_name = customer_info.get("name") or customer_info.get("customer_name", "")
        country = customer_info.get("country_code", "")
        if customer_name:
            from .sanctions import check_sanctions as sanctions_check
            ok, reason, hits = sanctions_check(customer_name, country)
            if not ok:
                logger.warning(
                    "Sanctions hit: name=%s country=%s hits=%s",
                    customer_name, country, [h.get("name") for h in hits],
                )
                return False, "暂不支持询价服务"  # 静默拒绝

        return True, None

    def check_product_permission(self, customer_info: dict | None, product_type: str) -> tuple[bool, Optional[str]]:
        """规则9第3层：产品权限"""
        if not customer_info or not product_type:
            return True, None
        permissions = customer_info.get("product_permissions", [])
        if permissions and product_type not in permissions:
            labels = {"FWD": "远期结售汇", "SWAP": "外汇掉期"}
            return False, f"您尚未开通{labels.get(product_type, product_type)}权限，请联系客户经理开通后重试。"
        return True, None

    def check_rate_limit(self, customer_id: str) -> tuple[bool, int]:
        """规则17：频率控制"""
        now = time.time()
        last = self._rate_cache.get(customer_id, 0)
        elapsed = now - last
        remaining = max(0, int(self._rate_limit_seconds - elapsed))
        if elapsed < self._rate_limit_seconds:
            return False, remaining
        self._rate_cache[customer_id] = now
        return True, 0

    def get_rejection_guidance(self, reject_type: str) -> str:
        """规则7：拒绝引导"""
        GUIDANCE = {
            "UNSUPPORTED_PRODUCT": "暂不支持该产品类型。当前支持即期、远期、掉期询价。",
            "NON_TRADING_HOURS": "当前为非交易时段。您可以使用模拟询价体验流程。",
            "INVESTMENT_ADVICE": "根据监管要求，我们无法提供投资建议。您可以对比不同产品的价格差异。",
            "PRICE_PREDICTION": "我们无法预测汇率走势。如需了解不同情景下的价格差异，可使用情景分析。",
            "AMOUNT_TOO_LARGE": "大额交易需走线下询价通道。请联系客户经理或减少金额后重试。",
        }
        return GUIDANCE.get(reject_type, "暂无法处理您的请求，请重新输入。")
