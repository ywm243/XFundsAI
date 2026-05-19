# backend/pricing/state_machine.py
"""报价生命周期状态机"""

from __future__ import annotations
from datetime import datetime, timedelta

from .models import PricingStatus


class PricingStateMachine:
    """管理报价从 IDLE 到 TRADED 的状态转换"""

    _VALID_TRANSITIONS: dict[str, list[str]] = {
        "IDLE":            ["QUOTING", "ERROR"],
        "QUOTING":         ["QUOTED", "ERROR"],
        "QUOTED":          ["EXPIRED", "TRADING", "CANCELLED", "REFRESH"],
        "EXPIRED":         ["QUOTING", "CANCELLED"],
        "TRADING":         ["TRADED", "TRADE_FAILED"],
        "TRADE_FAILED":    ["TRADING", "QUOTING", "CANCELLED"],
        "TRADED":          [],
        "CANCELLED":       ["QUOTING"],
        "ERROR":           ["IDLE", "QUOTING"],
    }

    def __init__(self, validity_minutes: int = 5):
        self.validity_minutes = validity_minutes
        self._status = PricingStatus.IDLE
        self._valid_until: datetime | None = None

    @property
    def status(self) -> str:
        return self._status.value

    @property
    def valid_until(self) -> datetime | None:
        return self._valid_until

    def can_transition(self, to_status: str) -> bool:
        return to_status in self._VALID_TRANSITIONS.get(self._status.value, [])

    def transition(self, to_status: str, validity_minutes: int | None = None) -> None:
        new = to_status.upper() if isinstance(to_status, str) else to_status
        if isinstance(new, str):
            new = PricingStatus(new)
        if not self.can_transition(new.value):
            raise InvalidTransitionError(
                f"Cannot transition from {self._status.value} to {new.value}"
            )
        self._status = new
        if new == PricingStatus.QUOTED:
            v = validity_minutes or self.validity_minutes
            self._valid_until = datetime.now() + timedelta(minutes=v)
        if new in (PricingStatus.TRADED, PricingStatus.CANCELLED,
                   PricingStatus.EXPIRED, PricingStatus.TRADE_FAILED):
            self._valid_until = None

    def is_expired(self) -> bool:
        if self._status != PricingStatus.QUOTED:
            return False
        if self._valid_until is None:
            return False
        return datetime.now() > self._valid_until

    def check_and_expire(self) -> bool:
        if self.is_expired():
            self._status = PricingStatus.EXPIRED
            self._valid_until = None
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "status": self._status.value,
            "valid_until": self._valid_until.isoformat() if self._valid_until else None,
        }


class InvalidTransitionError(Exception):
    pass
