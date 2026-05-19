from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PricingStatus(str, Enum):
    IDLE = "IDLE"
    QUOTING = "QUOTING"
    QUOTED = "QUOTED"
    EXPIRED = "EXPIRED"
    TRADING = "TRADING"
    TRADED = "TRADED"
    TRADE_FAILED = "TRADE_FAILED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class IntentType(str, Enum):
    SINGLE = "SINGLE"
    MULTI = "MULTI"
    COMPARE = "COMPARE"
    SCENARIO = "SCENARIO"
    DIRECT_TRADE = "DIRECT_TRADE"


@dataclass
class InquiryParams:
    """询价参数"""
    customer_id: str
    product_type: str = ""
    currency_pair: str = ""
    direction: str = ""
    amount: Optional[float] = None
    tenor: str = ""
    near_tenor: str = ""
    far_tenor: str = ""
    request_id: str = ""

    def missing_required(self) -> list[str]:
        required = {
            "SPOT":  ["currency_pair", "direction"],
            "FWD":   ["currency_pair", "direction", "tenor"],
            "SWAP":  ["currency_pair", "direction", "near_tenor", "far_tenor"],
        }
        missing = []
        for f in required.get(self.product_type, []):
            if not getattr(self, f, None):
                missing.append(f)
        return missing


@dataclass
class QuoteResult:
    """询价结果"""
    quote_id: str = ""
    customer_rate: float = 0.0
    market_rate: float = 0.0
    spread_bp: int = 0
    product_type: str = ""
    currency_pair: str = ""
    direction: str = ""
    amount: Optional[float] = None
    value_date: str = ""
    created_at: str = ""


@dataclass
class TradeResult:
    """交易结果"""
    success: bool = False
    trade_id: str = ""
    quote_id: str = ""
    product_type: str = ""
    currency_pair: str = ""
    direction: str = ""
    amount: float = 0.0
    executed_rate: float = 0.0
    executed_at: str = ""
    error_code: str = ""
    error_reason: str = ""


@dataclass
class PricingSession:
    """询报价会话"""
    id: str = ""
    session_id: str = ""
    status: PricingStatus = PricingStatus.IDLE
    intent_type: IntentType = IntentType.SINGLE
    inquiry_params: dict = field(default_factory=dict)
    quote_results: list[dict] = field(default_factory=list)
    trade_result: Optional[dict] = None
    created_at: str = ""
    valid_until: str = ""


@dataclass
class ValidationResult:
    """参数校验结果"""
    valid: bool = True
    missing_fields: list[str] = field(default_factory=list)
    follow_up: list[str] = field(default_factory=list)


@dataclass
class PricingIntent:
    """解析后的询价意图"""
    intent_type: IntentType = IntentType.SINGLE
    product_type: str = ""
    currency_pair: str = ""
    direction: str = ""
    amount: Optional[float] = None
    tenor: str = ""
    near_tenor: str = ""
    far_tenor: str = ""
    scenario_name: str = ""
    compare_products: list[str] = field(default_factory=list)
    pipeline: str = ""
    confidence: float = 0.0
