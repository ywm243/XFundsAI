import logging

from . import parser as _parser
from db import sqlite_store

logger = logging.getLogger(__name__)

_rules_cache: dict | None = None


def _load_rules() -> dict:
    """Load rules from SQLite (with memory cache).

    Returns the same nested dict format as the old semantic_rules.json,
    so gatekeep() doesn't need to change.
    """
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    _rules_cache = sqlite_store.load_rules_from_db()
    return _rules_cache


def reload_rules() -> None:
    """Clear cache so next request reloads from SQLite."""
    global _rules_cache
    _rules_cache = None
    sqlite_store.init_db()
    logger.info("Rules engine cache cleared, will reload from SQLite on next request")


def _has_keyword(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def gatekeep(parsed: dict, original_text: str) -> dict:
    rules = _load_rules()
    overrides: list[str] = []

    # ---- 阶段 1a: 铁律 buy_sell 规则 ----
    buy_sell_rules = rules["buy_sell_direction"]["rules"]
    for rule in buy_sell_rules:
        if not rule["customer_reversible"]:
            if _has_keyword(original_text, rule["keywords"]):
                parsed["buy_sell"] = rule["direction"]
                if rule.get("set_app_id"):
                    parsed["appid"] = rule["set_app_id"]
                overrides.append(
                    f"buy_sell={rule['direction']},appid={rule.get('set_app_id')} ({rule['description']})"
                )
                break

    # ---- 阶段 1b: "结售汇" 特例 ----
    if "结售汇" in original_text:
        parsed["appid"] = 2
        parsed["buy_sell"] = ""

    # ---- 阶段 1c: 可反转规则 + 客户前缀检测 ----
    # 若 buy_sell 尚未被铁律设置，且文本含"客户"前缀
    if not any("customer_reversible" in o for o in overrides):
        has_customer = "客户" in original_text
        if has_customer:
            for rule in buy_sell_rules:
                if rule["customer_reversible"] and _has_keyword(original_text, rule["keywords"]):
                    # 仅在 LLM 未输出或可反转时覆盖
                    if rule.get("customer_direction"):
                        parsed["buy_sell"] = rule["customer_direction"]
                        overrides.append(
                            f"customer_reversal buy_sell→{rule['customer_direction']} ({rule['description']})"
                        )
                        break

    # ---- 阶段 1d: special_states 精确匹配 ----
    state_rules = rules["special_states"]["rules"]
    matched_states = []
    for sr in state_rules:
        if _has_keyword(original_text, sr["keywords"]):
            matched_states.append(sr["value"])
    if matched_states:
        parsed["special_states"] = ",".join(matched_states)
        overrides.append(f"special_states={parsed['special_states']}")

    # ---- 阶段 1d2: trade_class 匹配（使用 parser 的两遍匹配逻辑） ----
    tc = _parser._parse_trade_class(original_text)
    if tc:
        parsed["trade_class"] = tc
        overrides.append(f"trade_class={tc}")

    # ---- 阶段 1d3: 签约交易检测 ----
    if "签约" in original_text:
        parsed["sign_trade"] = 0
        overrides.append("sign_trade=0 (签约交易)")

    # ---- 阶段 1e: product_type 精确匹配 ----
    product_rules = rules["product_type"]["rules"]
    matched_types = []
    for pr in product_rules:
        if _has_keyword(original_text, pr["keywords"]):
            matched_types.append(pr["value"])
    if len(matched_types) > 1:
        parsed["product_type"] = "all"
    elif len(matched_types) == 1:
        parsed["product_type"] = matched_types[0]

    # ---- 阶段 1f: app_id 匹配（仅在未设置时） ----
    if parsed.get("appid") is None or parsed.get("appid") == "":
        appid_rules = rules["app_id"]["rules"]
        for ar in appid_rules:
            if _has_keyword(original_text, ar["keywords"]):
                parsed["appid"] = ar["value"]
                overrides.append(f"appid={ar['value']} ({ar['meaning']})")
                break

    # ---- 阶段 2: 时间回退 ----
    if not parsed.get("date_start") or not parsed.get("date_end"):
        ds, de = _parser._parse_date_range(original_text)
        if ds and not parsed.get("date_start"):
            parsed["date_start"] = ds
        if de and not parsed.get("date_end"):
            parsed["date_end"] = de
        if ds or de:
            overrides.append(f"date_fallback [{parsed.get('date_start', '')}, {parsed.get('date_end', '')}]")

    # ---- 阶段 3: 客户名称 ----
    if not parsed.get("cust_name"):
        cust = _parser._parse_cust_name(original_text)
        if cust:
            parsed["cust_name"] = cust

    if parsed.get("cust_name"):
        parsed["dimension"] = "customer"
        parsed["bank_name"] = ""
        overrides.append("dimension=customer (cust_name present)")

    # ---- 阶段 4: 银行名称回退 ----
    if parsed.get("dimension") == "bank" and not parsed.get("bank_name"):
        bank = _parser._parse_bank_name(original_text)
        if bank:
            parsed["bank_name"] = bank

    # ---- 阶段 5: 互斥校验 ----
    if parsed.get("cust_name") and parsed.get("bank_name"):
        parsed["bank_name"] = ""

    # ---- 聚合检测 ----
    agg_keywords = ["交易量", "金额", "总额", "总计", "汇总"]
    if _has_keyword(original_text, agg_keywords):
        parsed["aggregate"] = True

    # ---- 套保率检测 ----
    if "套保率" in original_text:
        parsed["hedge_ratio"] = True

    # ---- TopN 回退 ----
    if parsed.get("top_n") is None:
        parsed["top_n"] = _parser._parse_top_n(original_text)

    # ---- 金额过滤回退 ----
    if parsed.get("amount_filter") is None:
        af = _parser._parse_amount_filter(original_text)
        if af:
            parsed["amount_filter"] = af

    # ---- 维度回退 ----
    parsed_dim = _parser._parse_dimension(original_text)
    if parsed_dim != "bank":
        parsed["dimension"] = parsed_dim
        overrides.append(f"dimension={parsed_dim}")

    # ---- 对比回退 ----
    if not parsed.get("comparison"):
        cmp = _parser._parse_comparison_modifier(original_text)
        if cmp:
            parsed["comparison"] = cmp
            overrides.append(f"comparison={cmp}")

    if overrides:
        logger.info("Gatekeep overrides: %s", "; ".join(overrides))

    return parsed
