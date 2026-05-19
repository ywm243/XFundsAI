# backend/pricing/insight_engine.py
"""客户智能洞察引擎 — 基于记忆和画像的主动分析推送"""

from __future__ import annotations
from typing import Optional

from .models import PricingIntent, QuoteResult
from db import mysql_store
from event_bus import bus


class InsightEngine:
    """根据客户历史记忆和当前询价意图，生成主动洞察"""

    def __init__(self):
        bus.subscribe("quote.created", self.on_quote_created)
        bus.subscribe("trade.executed", self.on_trade_executed)

    async def on_quote_created(self, pricing_id: str, intent_type: str, **kwargs):
        """新报价生成时 — 预留处理"""
        pass

    async def on_trade_executed(self, pricing_id: str, trade_id: str, **kwargs):
        """交易完成时 — 预留处理"""
        pass

    async def generate_insights(self, customer_id: str,
                                current_intent: PricingIntent,
                                quotes: list[QuoteResult]) -> list[dict]:
        """生成主动洞察列表"""
        insights = []

        # 1. 走势图洞察（使用代客系统走势图组件URL）
        if current_intent.currency_pair:
            chart_insight = self._build_chart_insight(current_intent)
            if chart_insight:
                insights.append(chart_insight)

        # 2. 基于记忆的产品对比推荐
        prefs = await self._get_customer_preferences(customer_id)
        if prefs:
            compare_insight = self._build_comparison_insight(current_intent, prefs)
            if compare_insight:
                insights.append(compare_insight)

        # 3. 历史询价摘要
        history_summary = await self._get_history_summary(customer_id)
        if history_summary:
            insights.append(history_summary)

        return insights

    def _build_chart_insight(self, intent: PricingIntent) -> Optional[dict]:
        """构建走势图洞察"""
        pair = intent.currency_pair
        if not pair:
            return None
        return {
            "type": "rate_chart",
            "title": f"{pair} 近30天走势",
            "chart_url": f"/api/pricing/chart?pair={pair}",
            "summary": "走势图数据由代客系统提供",
        }

    def _build_comparison_insight(self, intent: PricingIntent,
                                   prefs: dict) -> Optional[dict]:
        """基于客户偏好生成产品对比建议"""
        freq_product = prefs.get("frequent_product_type", "")
        if not freq_product or freq_product == intent.product_type:
            return None

        return {
            "type": "product_comparison",
            "title": "基于您的交易习惯",
            "detail": f"您常交易{freq_product}产品，是否对比查看{freq_product}与{intent.product_type}的价格差异？",
            "action": "compare",
            "action_label": "查看对比",
            "action_params": {
                "products": [intent.product_type, freq_product],
                "currency_pair": intent.currency_pair,
            },
        }

    async def _get_customer_preferences(self, customer_id: str) -> dict:
        """从记忆系统读取客户偏好"""
        try:
            memories = mysql_store.get_agent_memory(customer_id, last_n=20)
        except Exception:
            return {}

        counts: dict[str, dict[str, int]] = {"product_type": {}, "tenor": {}}
        for m in memories:
            data = m.get("structured_data", {})
            data = data if isinstance(data, dict) else {}
            for key in ("product_type", "tenor"):
                val = str(data.get(key, ""))
                if val:
                    counts[key][val] = counts[key].get(val, 0) + 1

        return {
            "frequent_product_type": max(counts["product_type"], key=counts["product_type"].get) if counts["product_type"] else "",
            "frequent_tenor": max(counts["tenor"], key=counts["tenor"].get) if counts["tenor"] else "",
            "total_inquiries": len(memories),
        }

    async def _get_history_summary(self, customer_id: str) -> Optional[dict]:
        """获取历史询价摘要"""
        try:
            memories = mysql_store.get_agent_memory(customer_id, last_n=5)
        except Exception:
            return None

        if not memories:
            return None

        recent_pairs = set()
        for m in memories:
            data = m.get("structured_data", {})
            data = data if isinstance(data, dict) else {}
            pair = data.get("currency_pair", "")
            if pair:
                recent_pairs.add(pair)

        if not recent_pairs:
            return None

        return {
            "type": "history",
            "title": "您的近期询价",
            "detail": f"最近询价涉及：{'、'.join(sorted(recent_pairs)[:3])}",
            "recent_pairs": list(recent_pairs),
        }
