# backend/event_bus.py
"""进程内发布/订阅事件总线 — Agent间松耦合通信"""

from __future__ import annotations
import asyncio
from collections import defaultdict
from typing import Callable, Awaitable

Handler = Callable[..., Awaitable[None]]


class EventBus:
    EVENTS = {
        "quote.created":       "新报价生成",
        "quote.expired":       "报价过期",
        "quote.cancelled":     "报价取消",
        "quote.refreshed":     "报价刷新",
        "trade.executed":      "交易执行完成",
        "trade.failed":        "交易执行失败",
        "market.rate_changed": "汇率变动",
        "customer.risk_alert": "客户风险等级与产品不匹配",
    }

    def __init__(self):
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event: str, handler: Handler) -> None:
        if event not in self.EVENTS:
            raise ValueError(f"Unknown event: {event}. Registered: {list(self.EVENTS)}")
        self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: Handler) -> None:
        self._handlers[event][:] = [h for h in self._handlers[event] if h is not handler]

    async def publish(self, event: str, **kwargs) -> None:
        if event not in self.EVENTS:
            raise ValueError(f"Unknown event: {event}")
        await asyncio.gather(
            *(handler(**kwargs) for handler in self._handlers[event]),
            return_exceptions=True
        )


# 全局单例
bus = EventBus()
