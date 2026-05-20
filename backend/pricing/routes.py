# backend/pricing/routes.py
"""询报价 API 路由"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .service import PricingService

router = APIRouter(prefix="/api/pricing", tags=["pricing"])

_pricing_service: PricingService | None = None


def get_pricing_service() -> PricingService:
    global _pricing_service
    if _pricing_service is None:
        _pricing_service = PricingService()
        _pricing_service.configure({}, 5)
    return _pricing_service


def init_pricing_service(engine_url: str | None = None,
                         scenarios: dict | None = None,
                         validity_minutes: int = 5) -> PricingService:
    global _pricing_service
    _pricing_service = PricingService(engine_url or "")
    _pricing_service.configure(scenarios or {}, validity_minutes)
    return _pricing_service


class InquiryRequest(BaseModel):
    text: str
    intent: dict
    session_id: str = ""
    customer_id: str = ""
    customer_info: dict | None = None
    context: list[dict] | None = None


class ConfirmRequest(BaseModel):
    pricing_id: str
    session_id: str = ""
    customer_id: str = ""
    customer_info: dict | None = None


class ActionRequest(BaseModel):
    pricing_id: str


@router.post("/inquiry")
async def inquiry(req: InquiryRequest):
    from .models import PricingIntent
    intent = PricingIntent(**req.intent) if req.intent else PricingIntent()
    service = get_pricing_service()
    return await service.handle_inquiry(
        text=req.text, intent=intent, customer_id=req.customer_id,
        session_id=req.session_id, customer_info=req.customer_info,
        context=req.context,
    )


@router.post("/confirm")
async def confirm(req: ConfirmRequest):
    service = get_pricing_service()
    return await service.handle_confirm_trade(
        pricing_id=req.pricing_id, customer_id=req.customer_id,
        customer_info=req.customer_info,
    )


@router.post("/refresh")
async def refresh(req: ActionRequest):
    service = get_pricing_service()
    return await service.handle_refresh(
        pricing_id=req.pricing_id, customer_id="",
    )


@router.post("/cancel")
async def cancel(req: ActionRequest):
    service = get_pricing_service()
    return await service.handle_cancel(pricing_id=req.pricing_id)


@router.get("/chart")
async def rate_chart(pair: str = "USD/CNY", days: int = 30):
    """汇率走势图数据（预埋模拟数据）"""
    import random
    from datetime import datetime, timedelta

    rng = random.Random(hash(pair) % (2**31))
    base_rates = {
        "USD/CNY": 7.2450, "EUR/CNY": 7.8520, "GBP/CNY": 9.1680,
        "JPY/CNY": 0.0468, "EUR/USD": 1.0837,
    }
    base = base_rates.get(pair, 7.2000)
    dates = []
    values = []
    current = base
    for i in range(days):
        date = (datetime.now() - timedelta(days=days - i)).strftime("%m-%d")
        jitter = rng.randint(-80, 80) / 10000
        current = round(base + jitter, 4)
        dates.append(date)
        values.append(current)

    return {
        "pair": pair,
        "days": days,
        "dates": dates,
        "values": values,
        "unit": "CNY" if "/CNY" in pair else "USD",
    }


@router.get("/status/{pricing_id}")
async def status(pricing_id: str):
    from db import mysql_store
    session = mysql_store.get_pricing_session(pricing_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"pricing_id": pricing_id, "status": session.get("status")}
