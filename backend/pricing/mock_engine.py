# backend/pricing/mock_engine.py
"""预埋数据模拟定价引擎 — 无外部依赖，自动返回报价"""

from __future__ import annotations
import time
import uuid
import random
from datetime import datetime, timedelta
from .models import InquiryParams, QuoteResult, TradeResult

# ═══════════════════════════════════════════════════════════════
# 预埋基础汇率数据（2026-05-20 参考价）
# ═══════════════════════════════════════════════════════════════

_BASE_RATES: dict[str, float] = {
    "USD/CNY": 7.2450,
    "EUR/CNY": 7.8520,
    "GBP/CNY": 9.1680,
    "JPY/CNY": 0.0468,      # 100 JPY ≈ 4.68 CNY
    "HKD/CNY": 0.9270,
    "AUD/CNY": 4.7850,
    "EUR/USD": 1.0837,
    "GBP/USD": 1.2655,
    "USD/JPY": 154.80,
    "AUD/USD": 0.6605,
}

# FWD 掉期点（单位：bp，即 0.0001）
_FWD_POINTS: dict[str, dict[str, float]] = {
    # tenor -> swap_points_in_bp (正=升水, 负=贴水)
    "USD/CNY": {"1W": 12, "2W": 25, "1M": 52, "3M": 158, "6M": 310, "1Y": 580},
    "EUR/CNY": {"1W": 8,  "2W": 18, "1M": 38, "3M": 115, "6M": 220, "1Y": 420},
    "EUR/USD": {"1W": 3,  "2W": 7,  "1M": 15, "3M": 45,  "6M": 88,  "1Y": 168},
    "GBP/USD": {"1W": 5,  "2W": 10, "1M": 22, "3M": 65,  "6M": 125, "1Y": 240},
}

_DEFAULT_FWD_POINTS = {"1W": 4, "2W": 8, "1M": 18, "3M": 55, "6M": 108, "1Y": 200}

# SWAP 近端/远端掉期点差值
_SWAP_SPREAD: dict[str, dict[str, tuple[float, float]]] = {
    # pair -> tenor_pair -> (near_points, far_points)
    "USD/CNY": {"1W*1M": (12, 52), "1M*3M": (52, 158), "3M*6M": (158, 310), "1W*2W": (12, 25)},
}

# ═══════════════════════════════════════════════════════════════
# 模拟引擎
# ═══════════════════════════════════════════════════════════════

class MockPricingEngine:
    """基于预埋数据生成报价，模拟真实定价引擎行为

    规则：
    - SPOT: 基准价 + 随机点差 (1-10 bp)
    - FWD:  基准价 + 掉期点 + 随机点差
    - SWAP: 近远端双报价
    - 交易执行: 90% 成功率模拟
    """

    def __init__(self, seed: int = None):
        self._rng = random.Random(seed or int(time.time() * 1000) % (2**31))
        self._trade_counter = 0

    # ── 询价 ──────────────────────────────────────────────

    def generate_quote(self, params: InquiryParams) -> QuoteResult:
        """根据 InquiryParams 生成一个报价"""
        pair = params.currency_pair or "USD/CNY"
        product_type = params.product_type or "SPOT"

        base_rate = _BASE_RATES.get(pair, 7.2000)

        if product_type == "SPOT":
            customer_rate = self._spot_rate(base_rate)
        elif product_type == "FWD":
            customer_rate = self._fwd_rate(base_rate, pair, params.tenor)
        elif product_type == "SWAP":
            near_rate, far_rate = self._swap_rates(base_rate, pair,
                                                    params.near_tenor, params.far_tenor)
            # SWAP 返回近端汇率作为 customer_rate，远端存在 market_rate 位置
            customer_rate = near_rate
            market_rate = far_rate
        else:
            customer_rate = self._spot_rate(base_rate)

        spread_bp = int(round(abs(customer_rate - base_rate) * 10000))
        now = datetime.now()

        return QuoteResult(
            quote_id=f"QT{now.strftime('%Y%m%d%H%M%S')}{self._rng.randint(1000,9999)}",
            customer_rate=round(customer_rate, 4),
            market_rate=round(getattr(locals().get('market_rate', None), 'market_rate', base_rate)
                              if product_type == "SWAP" else base_rate, 4),
            spread_bp=spread_bp,
            product_type=product_type,
            currency_pair=pair,
            direction=params.direction or "B",
            amount=params.amount,
            value_date=self._value_date(product_type, params.tenor),
            created_at=now.isoformat() + "+08:00",
        )

    def _spot_rate(self, base: float) -> float:
        """即期：基准价 ± 1-10 bp 随机点差"""
        spread = self._rng.randint(10, 100) / 10000  # 1-10 bp
        direction = self._rng.choice([-1, 1])
        return base + spread * direction

    def _fwd_rate(self, base: float, pair: str, tenor: str) -> float:
        """远期：基准价 + 掉期点 + 随机点差"""
        points_map = _FWD_POINTS.get(pair, _DEFAULT_FWD_POINTS)
        fwd_points_bp = points_map.get(tenor, 25)
        fwd_adjustment = fwd_points_bp / 10000
        spread = self._rng.randint(5, 30) / 10000
        return base + fwd_adjustment + spread * self._rng.choice([-1, 1])

    def _swap_rates(self, base: float, pair: str,
                    near_tenor: str, far_tenor: str) -> tuple[float, float]:
        """掉期：近端和远端两个汇率"""
        key = f"{near_tenor}*{far_tenor}"
        swap_map = _SWAP_SPREAD.get(pair, {})
        near_pts, far_pts = swap_map.get(key, (15, 50))
        near_rate = base + near_pts / 10000
        far_rate = base + far_pts / 10000
        jitter = self._rng.randint(3, 15) / 10000
        return (
            near_rate + jitter * self._rng.choice([-1, 1]),
            far_rate + jitter * self._rng.choice([-1, 1]),
        )

    def _value_date(self, product_type: str, tenor: str) -> str:
        """计算交割日"""
        today = datetime.now()
        if product_type == "SPOT":
            return (today + timedelta(days=2)).strftime("%Y-%m-%d")
        if product_type == "FWD" and tenor:
            return self._tenor_date(today, tenor)
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    def _tenor_date(self, today: datetime, tenor: str) -> str:
        """掉期期限 → 日期"""
        unit = tenor[-1].upper()
        num = int(tenor[:-1]) if tenor[:-1].isdigit() else 1
        if unit == "W":
            return (today + timedelta(weeks=num)).strftime("%Y-%m-%d")
        elif unit == "M":
            return (today + timedelta(days=num * 30)).strftime("%Y-%m-%d")
        elif unit == "Y":
            return (today + timedelta(days=num * 365)).strftime("%Y-%m-%d")
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    # ── 批量询价 ──────────────────────────────────────────

    async def batch_inquiry(self, params_list: list[InquiryParams]) -> list[QuoteResult]:
        """批量询价（同步生成，模拟并发）"""
        import asyncio
        results = []
        for p in params_list:
            results.append(self.generate_quote(p))
            await asyncio.sleep(0.01)  # 模拟轻微延迟
        return results

    # ── 交易执行 ──────────────────────────────────────────

    def execute_trade(self, quote_id: str, customer_id: str,
                      amount: float = None) -> TradeResult:
        """模拟交易执行（90% 成功率）"""
        self._trade_counter += 1
        success = self._rng.random() < 0.90

        if success:
            return TradeResult(
                success=True,
                trade_id=f"TD{datetime.now().strftime('%Y%m%d')}{self._trade_counter:06d}",
                quote_id=quote_id,
                product_type="SPOT",
                currency_pair="USD/CNY",
                direction="B",
                amount=amount,
                executed_rate=round(_BASE_RATES["USD/CNY"] + self._rng.randint(-5, 5) / 10000, 4),
                executed_at=datetime.now().isoformat() + "+08:00",
            )
        else:
            return TradeResult(
                success=False,
                quote_id=quote_id,
                error_code="TRADE_TIMEOUT",
                error_reason="交易执行超时，请稍后重试",
            )
