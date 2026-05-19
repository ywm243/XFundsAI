# backend/pricing/validator.py
"""询报价参数完整性校验 — 缺字段必追问"""

from .models import PricingIntent, ValidationResult

FOLLOW_UP_PROMPTS: dict[str, str] = {
    "currency_pair": "请问您要询价的货币对是什么？例如美元/人民币",
    "direction": "请问是结汇还是购汇？",
    "tenor": "请问期限是多久？例如1个月、3个月",
    "near_tenor": "请问近端期限是多久？",
    "far_tenor": "请问远端期限是多久？",
}

# 规则4：direction缺失 → 默认双边报价（B+S），不追问
REQUIRED_FIELDS: dict[str, list[str]] = {
    "SPOT":  ["currency_pair"],
    "FWD":   ["currency_pair", "tenor"],
    "SWAP":  ["currency_pair", "near_tenor", "far_tenor"],
}


def validate_intent(intent: PricingIntent) -> ValidationResult:
    """校验询价意图必填字段完整性"""
    pt = intent.product_type
    if not pt:
        return ValidationResult(
            valid=False,
            missing_fields=["product_type"],
            follow_up=["请问您要询价的产品类型是什么？即期、远期还是掉期？"],
        )
    if pt not in REQUIRED_FIELDS:
        return ValidationResult(
            valid=False,
            missing_fields=["product_type"],
            follow_up=[f"暂不支持 {pt} 产品类型，当前支持即期、远期和掉期"],
        )

    missing = []
    for field in REQUIRED_FIELDS[pt]:
        if not getattr(intent, field, None):
            missing.append(field)

    if missing:
        return ValidationResult(
            valid=False,
            missing_fields=missing,
            follow_up=[FOLLOW_UP_PROMPTS[f] for f in missing],
        )
    return ValidationResult(valid=True)


def validate_direct_trade(intent: PricingIntent) -> ValidationResult:
    """校验直接交易意图 — 额外检查金额"""
    base = validate_intent(intent)
    if not base.valid:
        return base
    if intent.intent_type.value == "DIRECT_TRADE" and not intent.amount:
        return ValidationResult(
            valid=False,
            missing_fields=["amount"],
            follow_up=["请问交易金额是多少？例如\"100万美元\""],
        )
    return ValidationResult(valid=True)
