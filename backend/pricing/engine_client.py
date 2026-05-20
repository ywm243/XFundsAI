# backend/pricing/engine_client.py
"""代客系统计价引擎 REST 适配器 — 支持真实引擎 / Mock 模式自动切换

mock 模式触发条件（任一满足即启用）：
  - PRICING_ENGINE_URL 为空或等于 "mock"
  - PRICING_ENGINE_URL 为 localhost 默认值且 MockEngine 显式声明优先
  - 启动参数 mock_engine=True
"""

from __future__ import annotations
import os
import httpx
from typing import Optional

from .models import InquiryParams, QuoteResult, TradeResult

DEFAULT_BASE_URL = os.getenv("PRICING_ENGINE_URL", "http://localhost:8080/api/v1")
DEFAULT_TIMEOUT = float(os.getenv("PRICING_TIMEOUT", "5.0"))


def _is_mock_mode(base_url: str) -> bool:
    """判断是否启用 mock 模式"""
    url = base_url.strip().rstrip("/").lower()
    if not url or url == "mock":
        return True
    if os.getenv("PRICING_ENGINE_MOCK", "").lower() == "true":
        return True
    return False


class PricingEngineClient:
    """封装代客系统询价/交易接口 — 自动切换真实引擎 / Mock"""

    def __init__(self, base_url: str = None, mock_engine: bool = None):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._mock = mock_engine if mock_engine is not None else _is_mock_mode(self.base_url)
        self._mock_engine = None

        if self._mock:
            from .mock_engine import MockPricingEngine
            self._mock_engine = MockPricingEngine()
            import logging
            logger = logging.getLogger(__name__)
            logger.info("PricingEngineClient running in MOCK mode")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client

    # ── 询价 ──────────────────────────────────────────────

    async def inquiry(self, params: InquiryParams) -> QuoteResult:
        """单次询价"""
        if self._mock:
            import asyncio
            await asyncio.sleep(0.02)  # 模拟轻微延迟
            return self._mock_engine.generate_quote(params)

        # 真实引擎路径（保持不变）
        client = await self._get_client()
        payload = self._build_payload(params)
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
        """批量询价"""
        if self._mock:
            return await self._mock_engine.batch_inquiry(params_list)

        # 真实引擎并发调用
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

    # ── 交易执行 ──────────────────────────────────────────

    async def execute_trade(self, quote_id: str, customer_id: str,
                            amount: Optional[float] = None) -> TradeResult:
        """执行交易"""
        if self._mock:
            import asyncio
            await asyncio.sleep(0.03)
            return self._mock_engine.execute_trade(quote_id, customer_id, amount)

        # 真实引擎路径
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

    @staticmethod
    def _build_payload(params: InquiryParams) -> dict:
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
        return payload


class EngineError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")
