# backend/pricing/service.py
"""询报价核心业务编排 — 依赖所有子模块的顶层服务"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from db import mysql_store
from event_bus import bus

from .context_inherit import inherit_pricing_context
from .engine_client import PricingEngineClient
from .models import (
    InquiryParams,
    IntentType,
    PricingIntent,
    PricingSession,
    PricingStatus,
    QuoteResult,
    TradeResult,
    ValidationResult,
)
from .risk_guard import RiskGuard
from .state_machine import InvalidTransitionError, PricingStateMachine
from .trade_executor import TradeExecutor
from .validator import validate_direct_trade, validate_intent

logger = logging.getLogger(__name__)

# 前端展示模式映射
_INTENT_MODE_MAP: dict[str, str] = {
    "SINGLE": "pricing_single",
    "MULTI": "pricing_multi",
    "COMPARE": "pricing_compare",
    "SCENARIO": "pricing_scenario",
    "DIRECT_TRADE": "pricing_direct_trade",
}


class PricingService:
    """询报价业务编排 — 串联校验、计价、风控、状态机、持久化、事件"""

    def __init__(
        self,
        engine_client: PricingEngineClient | None = None,
        validity_minutes: int = 5,
    ):
        self.engine_client = engine_client or PricingEngineClient()
        self.trade_executor = TradeExecutor(self.engine_client)
        self.risk_guard = RiskGuard()
        self.validity_minutes = validity_minutes
        # 情景配置：SCENARIO 模式下使用的期限列表
        self._scenarios: list[str] = ["1M", "3M", "6M", "1Y"]
        # 会话超时时间（分钟）
        self._session_timeout: int = 5
        # 运行中报价的状态机缓存 pricing_id → PricingStateMachine
        self._state_machines: dict[str, PricingStateMachine] = {}

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def configure(self, scenarios: list[str] | None = None,
                  validity_minutes: int | None = None,
                  compliance_config: dict | None = None) -> None:
        """配置情景期限列表、报价有效期及合规风控参数"""
        if scenarios is not None:
            self._scenarios = scenarios
        if validity_minutes is not None:
            self.validity_minutes = validity_minutes
        if compliance_config:
            self.risk_guard.configure(
                thresholds=compliance_config.get("amount_thresholds", {}),
                rate_limit=compliance_config.get("rate_limit_seconds", 5),
                session_timeout=compliance_config.get("session_timeout_minutes", 5),
            )
            self._session_timeout = compliance_config.get("session_timeout_minutes", 5)

    async def handle_inquiry(
        self,
        text: str,
        intent: PricingIntent,
        customer_id: str,
        session_id: str,
        customer_info: dict | None = None,
        context: list[dict] | None = None,
    ) -> dict:
        """处理询价请求

        流程：会话超时检查 → 上下文继承 → 必填字段校验 → 沙盒检测
              → 构建询价参数 → 风控预检 → 并发询价 → 风控后检
              → 状态机QUOTED → 保存会话 → 审计日志 → 发布事件
              → 格式化返回
        """
        # 0. 会话超时检查
        if self.check_session_timeout(session_id):
            return {
                "mode": "session_timeout",
                "reason": "会话已超时，请重新输入询价指令。",
            }

        # 1. 上下文继承
        intent = inherit_pricing_context(intent, context)

        # 2. 必填字段校验
        validation: ValidationResult = (
            validate_direct_trade(intent)
            if intent.intent_type == IntentType.DIRECT_TRADE
            else validate_intent(intent)
        )
        if not validation.valid:
            return {
                "mode": "pricing_missing",
                "missing_fields": validation.missing_fields,
                "follow_up": validation.follow_up,
            }

        # 3. 沙盒模式检测（规则2）
        is_sandbox = getattr(intent, 'sandbox', False) or any(
            kw in text for kw in ['模拟', '体验', '试算', '测试']
        )

        # 4. 构建询价参数
        params_list = self._build_inquiry_params(intent, customer_id)
        if not params_list:
            return {
                "mode": "pricing_error",
                "reason": "无法构建询价参数，请检查产品类型和必填字段",
            }

        # 5. 风控预检（含金额阈值，规则1）
        ok, reason = self.risk_guard.pre_check(
            customer_id, customer_info,
            product_type=intent.product_type,
            amount=params_list[0].amount or 0 if params_list else 0,
        )
        if not ok:
            return {"mode": "rejected", "reject_reason": reason}

        # 6. 创建状态机 + pricing_id
        pricing_id = str(uuid.uuid4())
        sm = PricingStateMachine(validity_minutes=self.validity_minutes)
        self._state_machines[pricing_id] = sm

        # IDLE → QUOTING
        sm.transition("QUOTING")

        # 7. 并发询价
        quotes = await self.engine_client.batch_inquiry(params_list)

        # 8. 风控后检 — 检查第一个有效报价
        for q in quotes:
            post_ok, post_reason = self.risk_guard.post_check(q)
            if not post_ok:
                sm.transition("ERROR")
                await self._save_session(
                    pricing_id=pricing_id,
                    session_id=session_id,
                    intent_type=intent.intent_type.value,
                    status=sm.status,
                    inquiry_params=[asdict(p) for p in params_list],
                    quote_results=[asdict(q) for q in quotes],
                    customer_id=customer_id,
                    valid_until=None,
                )
                return {
                    "mode": "pricing_error",
                    "reason": post_reason,
                    "pricing_id": pricing_id,
                }

        # 9. QUOTING → QUOTED
        sm.transition("QUOTED", validity_minutes=self.validity_minutes)

        # 10. 保存会话
        valid_until_str = (
            sm.valid_until.isoformat() if sm.valid_until else None
        )
        await self._save_session(
            pricing_id=pricing_id,
            session_id=session_id,
            intent_type=intent.intent_type.value,
            status=sm.status,
            inquiry_params=[asdict(p) for p in params_list],
            quote_results=[asdict(q) for q in quotes],
            customer_id=customer_id,
            valid_until=valid_until_str,
        )

        # 11. 审计日志（规则13 + 14：电子证据哈希）
        inquiry_detail = {
            "intent_type": intent.intent_type.value,
            "product_type": intent.product_type,
            "quote_count": len(quotes),
            "sandbox": is_sandbox,
        }
        evidence_payload = (
            f"{pricing_id}|INQUIRY|{json.dumps(inquiry_detail, sort_keys=True)}"
            f"|{datetime.now().isoformat()}"
        )
        evidence_hash = hashlib.sha256(evidence_payload.encode()).hexdigest()
        mysql_store.add_pricing_audit(
            pricing_id, "INQUIRY", inquiry_detail,
            evidence_hash=evidence_hash,
            evidence_type="quote",
        )

        # 12. 发布事件
        await bus.publish("quote.created", pricing_id=pricing_id,
                          customer_id=customer_id,
                          quote_count=len(quotes))

        # 13. 格式化返回
        need_disclosure = self.risk_guard.need_risk_disclosure(
            customer_info, intent.product_type
        )
        risk_disclosure = (
            self.risk_guard.get_risk_disclosure(intent.product_type)
            if need_disclosure
            else None
        )
        response = self._format_inquiry_response(
            intent=intent,
            quotes=quotes,
            pricing_id=pricing_id,
            valid_until=valid_until_str,
            risk_disclosure=risk_disclosure,
        )

        # 沙盒模式标记（规则2）
        if is_sandbox:
            response["sandbox_mode"] = True
            response["show_trade_button"] = False

        return response

    async def handle_confirm_trade(
        self,
        pricing_id: str,
        customer_id: str,
        customer_info: dict | None = None,
    ) -> dict:
        """确认下单

        流程：检查过期 → 执行交易 → 状态机转换 → 保存 → 发布事件 → 格式化
        """
        # 1. 获取会话
        record = mysql_store.get_pricing_session(pricing_id)
        if not record:
            return {"mode": "trade_failed", "reason": "报价不存在，请重新询价"}

        # 2. 检查过期
        sm = self._state_machines.get(pricing_id)
        if sm and sm.check_and_expire():
            await self._update_session_status(pricing_id, sm.status)
            await bus.publish("quote.expired", pricing_id=pricing_id)
            return {"mode": "trade_failed", "reason": "报价已过期，请重新询价"}

        # 恢复状态机（如进程重启后缓存丢失）
        if not sm:
            sm = PricingStateMachine(validity_minutes=self.validity_minutes)
            current_status = record.get("status", "QUOTED")
            if current_status == "QUOTED":
                sm._status = PricingStatus.QUOTED
            self._state_machines[pricing_id] = sm

        # 3. 取第一个报价的 quote_id
        quote_results = record.get("quote_results", "[]")
        if isinstance(quote_results, str):
            quote_results = json.loads(quote_results)
        if not quote_results:
            return {"mode": "trade_failed", "reason": "无有效报价"}

        quote_id = quote_results[0].get("quote_id", "")
        amount = quote_results[0].get("amount")

        # 4. QUOTED → TRADING
        try:
            sm.transition("TRADING")
        except InvalidTransitionError:
            return {
                "mode": "trade_failed",
                "reason": f"当前状态 {sm.status} 不允许下单",
            }

        # 5. 执行交易
        trade_result: TradeResult = await self.trade_executor.execute(
            quote_id=quote_id, customer_id=customer_id, amount=amount
        )

        # 6. 状态机转换
        is_novice = self.risk_guard.is_novice(customer_info)
        if trade_result.success:
            sm.transition("TRADED")
            event = "trade.executed"
        else:
            sm.transition("TRADE_FAILED")
            event = "trade.failed"

        # 7. 保存
        trade_result_dict = asdict(trade_result)
        valid_until = sm.valid_until.isoformat() if sm.valid_until else None
        await self._save_session(
            pricing_id=pricing_id,
            session_id=record.get("session_id", ""),
            intent_type=record.get("intent_type", "SINGLE"),
            status=sm.status,
            inquiry_params=record.get("inquiry_params", "[]"),
            quote_results=record.get("quote_results", "[]"),
            customer_id=customer_id,
            valid_until=valid_until,
            trade_result=trade_result_dict,
            trade_error=None if trade_result.success else {
                "error_code": trade_result.error_code,
                "error_reason": trade_result.error_reason,
            },
        )

        # 8. 审计日志（规则13 + 14：电子证据哈希）
        action_label = "TRADE_CONFIRMED" if trade_result.success else "TRADE_FAILED"
        evidence_payload = (
            f"{pricing_id}|{action_label}"
            f"|{json.dumps(trade_result_dict, sort_keys=True)}"
            f"|{datetime.now().isoformat()}"
        )
        evidence_hash = hashlib.sha256(evidence_payload.encode()).hexdigest()
        mysql_store.add_pricing_audit(
            pricing_id=pricing_id,
            action=action_label,
            detail=trade_result_dict,
            evidence_hash=evidence_hash,
            evidence_type="trade_confirm",
        )

        # 9. 发布事件
        await bus.publish(event, pricing_id=pricing_id,
                          customer_id=customer_id,
                          trade_id=trade_result.trade_id)

        # 10. 格式化返回
        if trade_result.success:
            result = self.trade_executor.format_result_for_client(
                trade_result, is_novice=is_novice
            )
            return result
        else:
            reason_text = self.risk_guard.translate_rejection(
                trade_result.error_code
            )
            return {
                "mode": "trade_failed",
                "reason": reason_text,
                "error_code": trade_result.error_code,
                "pricing_id": pricing_id,
            }

    async def handle_refresh(self, pricing_id: str,
                             customer_id: str) -> dict:
        """刷新报价 — 使用原询价参数重新询价"""
        record = mysql_store.get_pricing_session(pricing_id)
        if not record:
            return {"mode": "pricing_error", "reason": "报价不存在"}

        sm = self._state_machines.get(pricing_id)
        if not sm:
            sm = PricingStateMachine(validity_minutes=self.validity_minutes)
            current_status = record.get("status", "QUOTED")
            if current_status == "QUOTED":
                sm._status = PricingStatus.QUOTED
            self._state_machines[pricing_id] = sm

        # 检查是否可刷新（QUOTED 或 EXPIRED 状态）
        if not sm.can_transition("QUOTING") and sm.status not in ("QUOTED", "EXPIRED"):
            return {
                "mode": "pricing_error",
                "reason": f"当前状态 {sm.status} 不允许刷新",
            }

        # 从会话恢复询价参数
        inquiry_params_raw = record.get("inquiry_params", "[]")
        if isinstance(inquiry_params_raw, str):
            inquiry_params_raw = json.loads(inquiry_params_raw)

        params_list = []
        for p_dict in inquiry_params_raw:
            params_list.append(InquiryParams(**p_dict))

        # 状态转换到 QUOTING
        if sm.status == "QUOTED":
            sm.transition("QUOTING")
        elif sm.status == "EXPIRED":
            sm.transition("QUOTING")

        # 重新询价
        quotes = await self.engine_client.batch_inquiry(params_list)

        # 风控后检
        for q in quotes:
            post_ok, post_reason = self.risk_guard.post_check(q)
            if not post_ok:
                sm.transition("ERROR")
                return {"mode": "pricing_error", "reason": post_reason}

        # QUOTING → QUOTED
        sm.transition("QUOTED", validity_minutes=self.validity_minutes)

        valid_until_str = sm.valid_until.isoformat() if sm.valid_until else None
        intent_type = record.get("intent_type", "SINGLE")

        # 保存
        await self._save_session(
            pricing_id=pricing_id,
            session_id=record.get("session_id", ""),
            intent_type=intent_type,
            status=sm.status,
            inquiry_params=[asdict(p) for p in params_list],
            quote_results=[asdict(q) for q in quotes],
            customer_id=customer_id,
            valid_until=valid_until_str,
        )

        # 审计（规则13 + 14：电子证据哈希）
        refresh_detail = {"quote_count": len(quotes)}
        evidence_payload = (
            f"{pricing_id}|REFRESHED"
            f"|{json.dumps(refresh_detail, sort_keys=True)}"
            f"|{datetime.now().isoformat()}"
        )
        evidence_hash = hashlib.sha256(evidence_payload.encode()).hexdigest()
        mysql_store.add_pricing_audit(
            pricing_id=pricing_id,
            action="REFRESHED",
            detail=refresh_detail,
            evidence_hash=evidence_hash,
            evidence_type="quote_refresh",
        )

        # 发布事件
        await bus.publish("quote.refreshed", pricing_id=pricing_id,
                          customer_id=customer_id)

        # 格式化
        intent = PricingIntent(intent_type=IntentType(intent_type))
        return self._format_inquiry_response(
            intent=intent,
            quotes=quotes,
            pricing_id=pricing_id,
            valid_until=valid_until_str,
            risk_disclosure=None,
        )

    async def handle_cancel(self, pricing_id: str) -> dict:
        """取消报价"""
        record = mysql_store.get_pricing_session(pricing_id)
        if not record:
            return {"mode": "pricing_error", "reason": "报价不存在"}

        sm = self._state_machines.get(pricing_id)
        if not sm:
            sm = PricingStateMachine(validity_minutes=self.validity_minutes)
            current_status = record.get("status", "QUOTED")
            if current_status == "QUOTED":
                sm._status = PricingStatus.QUOTED
            self._state_machines[pricing_id] = sm

        try:
            sm.transition("CANCELLED")
        except InvalidTransitionError:
            return {
                "mode": "pricing_error",
                "reason": f"当前状态 {sm.status} 不允许取消",
            }

        # 保存
        await self._save_session(
            pricing_id=pricing_id,
            session_id=record.get("session_id", ""),
            intent_type=record.get("intent_type", "SINGLE"),
            status=sm.status,
            inquiry_params=record.get("inquiry_params", "[]"),
            quote_results=record.get("quote_results", "[]"),
            customer_id=record.get("customer_id", ""),
            valid_until=None,
        )

        # 审计（规则13 + 14：电子证据哈希）
        cancel_detail = {}
        evidence_payload = (
            f"{pricing_id}|CANCELLED"
            f"|{json.dumps(cancel_detail, sort_keys=True)}"
            f"|{datetime.now().isoformat()}"
        )
        evidence_hash = hashlib.sha256(evidence_payload.encode()).hexdigest()
        mysql_store.add_pricing_audit(
            pricing_id=pricing_id,
            action="CANCELLED",
            detail=cancel_detail,
            evidence_hash=evidence_hash,
            evidence_type="cancel",
        )

        # 发布事件
        await bus.publish("quote.cancelled", pricing_id=pricing_id)

        return {
            "mode": "pricing_cancelled",
            "pricing_id": pricing_id,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def check_session_timeout(self, session_id: str) -> bool:
        """检查会话是否超时（规则6）"""
        try:
            active = mysql_store.get_active_pricing_session(session_id)
            if active and active.get("last_activity"):
                elapsed = (datetime.now() - active["last_activity"]).total_seconds()
                return elapsed > self._session_timeout * 60
        except Exception:
            pass
        return False

    def _build_inquiry_params(self, intent: PricingIntent,
                              customer_id: str) -> list[InquiryParams]:
        """根据意图类型构建询价参数列表

        SINGLE  → 1 个 InquiryParams
        MULTI   → 1 个 InquiryParams（多产品待扩展）
        COMPARE → 多个 InquiryParams（对比产品）
        SCENARIO→ 多个 InquiryParams（不同期限情景）
        DIRECT_TRADE → 1 个 InquiryParams（带金额）
        """
        it = intent.intent_type

        if it == IntentType.SINGLE or it == IntentType.DIRECT_TRADE:
            # 双边报价（规则4）：direction 为空时同时询 B + S
            if it == IntentType.SINGLE and not intent.direction:
                return [
                    InquiryParams(
                        customer_id=customer_id,
                        product_type=intent.product_type,
                        currency_pair=intent.currency_pair,
                        direction="B",
                        amount=intent.amount,
                        tenor=intent.tenor,
                        near_tenor=intent.near_tenor,
                        far_tenor=intent.far_tenor,
                        request_id=str(uuid.uuid4()),
                    ),
                    InquiryParams(
                        customer_id=customer_id,
                        product_type=intent.product_type,
                        currency_pair=intent.currency_pair,
                        direction="S",
                        amount=intent.amount,
                        tenor=intent.tenor,
                        near_tenor=intent.near_tenor,
                        far_tenor=intent.far_tenor,
                        request_id=str(uuid.uuid4()),
                    ),
                ]
            return [InquiryParams(
                customer_id=customer_id,
                product_type=intent.product_type,
                currency_pair=intent.currency_pair,
                direction=intent.direction,
                amount=intent.amount,
                tenor=intent.tenor,
                near_tenor=intent.near_tenor,
                far_tenor=intent.far_tenor,
                request_id=str(uuid.uuid4()),
            )]

        if it == IntentType.MULTI:
            # 多产品询价 — 当前以主参数构建，后续可拆分为多个
            return [InquiryParams(
                customer_id=customer_id,
                product_type=intent.product_type,
                currency_pair=intent.currency_pair,
                direction=intent.direction,
                amount=intent.amount,
                tenor=intent.tenor,
                near_tenor=intent.near_tenor,
                far_tenor=intent.far_tenor,
                request_id=str(uuid.uuid4()),
            )]

        if it == IntentType.COMPARE:
            # 对比询价 — 为每个对比产品创建参数
            params_list = []
            for product in intent.compare_products:
                params_list.append(InquiryParams(
                    customer_id=customer_id,
                    product_type=product,
                    currency_pair=intent.currency_pair,
                    direction=intent.direction,
                    amount=intent.amount,
                    tenor=intent.tenor,
                    near_tenor=intent.near_tenor,
                    far_tenor=intent.far_tenor,
                    request_id=str(uuid.uuid4()),
                ))
            # 如果 compare_products 为空，回退到主参数
            if not params_list:
                params_list.append(InquiryParams(
                    customer_id=customer_id,
                    product_type=intent.product_type,
                    currency_pair=intent.currency_pair,
                    direction=intent.direction,
                    amount=intent.amount,
                    tenor=intent.tenor,
                    near_tenor=intent.near_tenor,
                    far_tenor=intent.far_tenor,
                    request_id=str(uuid.uuid4()),
                ))
            return params_list

        if it == IntentType.SCENARIO:
            # 情景询价 — 用不同期限创建多组参数
            params_list = []
            for tenor in self._scenarios:
                params_list.append(InquiryParams(
                    customer_id=customer_id,
                    product_type=intent.product_type,
                    currency_pair=intent.currency_pair,
                    direction=intent.direction,
                    amount=intent.amount,
                    tenor=tenor,
                    near_tenor=intent.near_tenor,
                    far_tenor=intent.far_tenor,
                    request_id=str(uuid.uuid4()),
                ))
            return params_list

        # 兜底：SINGLE
        return [InquiryParams(
            customer_id=customer_id,
            product_type=intent.product_type,
            currency_pair=intent.currency_pair,
            direction=intent.direction,
            amount=intent.amount,
            tenor=intent.tenor,
            near_tenor=intent.near_tenor,
            far_tenor=intent.far_tenor,
            request_id=str(uuid.uuid4()),
        )]

    async def _save_session(
        self,
        pricing_id: str,
        session_id: str,
        intent_type: str,
        status: str,
        inquiry_params: list | str,
        quote_results: list | str,
        customer_id: str,
        valid_until: str | None,
        trade_result: dict | None = None,
        trade_error: dict | None = None,
    ) -> None:
        """保存会话到 MySQL"""
        ip = (
            inquiry_params
            if isinstance(inquiry_params, str)
            else json.dumps(inquiry_params, ensure_ascii=False)
        )
        qr = (
            quote_results
            if isinstance(quote_results, str)
            else json.dumps(quote_results, ensure_ascii=False)
        )
        # 提取第一个报价的 quote_id 作为主 quote_id
        quote_id = ""
        if isinstance(quote_results, list) and quote_results:
            quote_id = quote_results[0].get("quote_id", "")
        elif isinstance(qr, str):
            try:
                parsed = json.loads(qr)
                if parsed:
                    quote_id = parsed[0].get("quote_id", "")
            except (json.JSONDecodeError, IndexError, KeyError):
                pass

        record = {
            "id": pricing_id,
            "session_id": session_id,
            "status": status,
            "intent_type": intent_type,
            "inquiry_params": ip,
            "quote_results": qr,
            "quote_id": quote_id,
            "valid_until": valid_until,
            "trade_result": (
                json.dumps(trade_result, ensure_ascii=False)
                if trade_result
                else None
            ),
            "trade_error": (
                json.dumps(trade_error, ensure_ascii=False)
                if trade_error
                else None
            ),
            "customer_id": customer_id,
            "last_activity": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        # mysql_store 是同步的，在线程池中执行以避免阻塞事件循环
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, mysql_store.save_pricing_session, record)

    async def _update_session_status(self, pricing_id: str,
                                     status: str) -> None:
        """仅更新会话状态（用于过期等场景）"""
        record = mysql_store.get_pricing_session(pricing_id)
        if not record:
            return
        record["status"] = status
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, mysql_store.save_pricing_session, record)

    def _format_inquiry_response(
        self,
        intent: PricingIntent,
        quotes: list[QuoteResult],
        pricing_id: str,
        valid_until: str | None,
        risk_disclosure: dict | None = None,
    ) -> dict:
        """格式化询价响应"""
        mode = _INTENT_MODE_MAP.get(
            intent.intent_type.value, "pricing_single"
        )
        response: dict = {
            "mode": mode,
            "pricing_id": pricing_id,
            "quotes": [asdict(q) for q in quotes],
            "valid_until": valid_until,
        }

        # DIRECT_TRADE 额外设置 show_trade_button
        if intent.intent_type == IntentType.DIRECT_TRADE:
            response["show_trade_button"] = True

        # 双边报价信号（规则4）：2条报价且无指定方向时告知前端展示双边
        if len(quotes) == 2 and not intent.direction:
            response["intent_params"] = {"direction": ""}

        # 风险披露
        if risk_disclosure:
            response["risk_disclosure"] = risk_disclosure

        return response

    def _format_single_quote_response(
        self,
        quote: QuoteResult,
        pricing_id: str,
        valid_until: str | None,
    ) -> dict:
        """格式化单报价响应"""
        return {
            "mode": "pricing_single",
            "pricing_id": pricing_id,
            "quotes": [asdict(quote)],
            "valid_until": valid_until,
        }
