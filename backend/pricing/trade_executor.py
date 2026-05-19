# backend/pricing/trade_executor.py
"""交易下单执行器"""

from __future__ import annotations
from typing import Optional

from .engine_client import PricingEngineClient
from .models import TradeResult


class TradeExecutor:
    """执行询价转交易"""

    def __init__(self, engine_client: PricingEngineClient):
        self.engine = engine_client

    async def execute(self, quote_id: str, customer_id: str,
                      amount: Optional[float] = None) -> TradeResult:
        """执行交易下单 — 同步调用代客系统交易接口"""
        result = await self.engine.execute_trade(quote_id, customer_id, amount)
        return result

    def format_result_for_client(self, result: TradeResult, is_novice: bool = False) -> dict:
        """将交易结果格式化为前端可展示的数据"""
        if result.success:
            msg = {
                "mode": "trade_success",
                "data": {
                    "trade_id": result.trade_id,
                    "product_type": result.product_type,
                    "currency_pair": result.currency_pair,
                    "direction": result.direction,
                    "amount": result.amount,
                    "executed_rate": result.executed_rate,
                    "executed_at": result.executed_at,
                    "summary": (
                        f"交易成功！\n"
                        f"交易编号：{result.trade_id}\n"
                        f"成交价格：{result.executed_rate}\n"
                        f"成交时间：{result.executed_at}"
                    ),
                }
            }
            if is_novice:
                msg["data"]["novice_tip"] = (
                    f"您已完成一笔{result.product_type}外汇交易，"
                    f"交割日期请关注后续通知。如需平仓或变更，请及时联系。"
                )
            return msg

        return {
            "mode": "trade_failed",
            "data": {
                "error_code": result.error_code,
                "error_reason": result.error_reason,
                "quote_id": result.quote_id,
            }
        }
