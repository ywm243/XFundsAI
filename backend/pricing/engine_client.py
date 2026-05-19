# backend/pricing/engine_client.py
"""代客系统计价引擎 REST 适配器"""

from __future__ import annotations
import os
import httpx
from typing import Optional

from .models import InquiryParams, QuoteResult, TradeResult

DEFAULT_BASE_URL = os.getenv("PRICING_ENGINE_URL", "http://localhost:8080/api/v1")
DEFAULT_TIMEOUT = float(os.getenv("PRICING_TIMEOUT", "5.0"))


class PricingEngineClient:
    """封装代客系统询价/交易接口"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client

    async def inquiry(self, params: InquiryParams) -> QuoteResult:
        """单次询价"""
        client = await self._get_client()
        payload = {
            "customer_id": params.customer_id,
            "product_type": params.product_type,
            "currency_pair": params.currency_pair,
            "direction": params.direction,
            "request_id": params.request_id,
        }
        if params.amount:
            payload["amount"] = params.amount
        if params.tenor:
            payload["tenor"] = params.tenor
        if params.near_tenor:
            payload["near_tenor"] = params.near_tenor
        if params.far_tenor:
            payload["far_tenor"] = params.far_tenor

        try:
            resp = await client.post(f"{self.base_url}/pricing/inquiry", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "SUCCESS":
                raise EngineError(data.get("code"), data.get("message", "unknown error"))
            d = data["data"]
            return QuoteResult(
                quote_id=d["quote_id"],
                customer_rate=d["customer_rate"],
                market_rate=d.get("market_rate", 0),
                spread_bp=d.get("spread_bp", 0),
                product_type=d["product_type"],
                currency_pair=d["currency_pair"],
                direction=d["direction"],
                amount=d.get("amount"),
                value_date=d.get("value_date", ""),
                created_at=d["created_at"],
            )
        except httpx.HTTPError as e:
            raise EngineError("NETWORK_ERROR", str(e)) from e

    async def batch_inquiry(self, params_list: list[InquiryParams]) -> list[QuoteResult]:
        """批量询价 — 并发调用"""
        import asyncio
        tasks = [self.inquiry(p) for p in params_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = []
        for r in results:
            if isinstance(r, Exception):
                out.append(QuoteResult())
            else:
                out.append(r)
        return out

    async def execute_trade(self, quote_id: str, customer_id: str,
                            amount: Optional[float] = None) -> TradeResult:
        """执行交易"""
        client = await self._get_client()
        payload = {"quote_id": quote_id, "customer_id": customer_id}
        if amount:
            payload["amount"] = amount
        try:
            resp = await client.post(f"{self.base_url}/trade/execute", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == "SUCCESS":
                d = data["data"]
                return TradeResult(
                    success=True, trade_id=d["trade_id"],
                    quote_id=d["quote_id"], product_type=d["product_type"],
                    currency_pair=d["currency_pair"], direction=d["direction"],
                    amount=d["amount"], executed_rate=d["executed_rate"],
                    executed_at=d["executed_at"],
                )
            elif data.get("code") == "TRADE_REJECTED":
                d = data.get("data", {})
                return TradeResult(
                    success=False, quote_id=quote_id,
                    error_code=d.get("reject_code", ""),
                    error_reason=d.get("reject_reason", ""),
                )
            else:
                return TradeResult(success=False, error_code=data.get("code", ""),
                                   error_reason=data.get("message", ""))
        except httpx.HTTPError as e:
            return TradeResult(success=False, error_code="NETWORK_ERROR", error_reason=str(e))

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


class EngineError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")
