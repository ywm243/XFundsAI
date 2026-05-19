import logging

from . import parser as _parser
from db import mysql_store

logger = logging.getLogger(__name__)

_rules_cache: dict | None = None

# ---- Dimension config defaults (fallback when DB unavailable) ----

_DEFAULT_DIMENSION_CONFIG: dict = {
    "bank": {
        "display_label": "机构", "count_unit": "家",
        "sql_select_col": "b.DIPNAME as 机构名称", "sql_group_col": "b.DIPNAME",
        "join_clause": "LEFT JOIN XF_BASE_BANK b ON t.BANKID = b.BANKID",
        "label_col_names": ["DIPNAME", "BANKNAME"],
    },
    "customer": {
        "display_label": "客户", "count_unit": "个",
        "sql_select_col": "t.CUSTNAME as 客户名称", "sql_group_col": "t.CUSTNAME",
        "join_clause": "", "label_col_names": ["CUSTNAME"],
    },
    "customer_id": {
        "display_label": "客户", "count_unit": "个",
        "sql_select_col": "t.CUSTOMERID as 客户号", "sql_group_col": "t.CUSTOMERID",
        "join_clause": "", "label_col_names": ["CUSTOMERID"],
    },
    "manager": {
        "display_label": "客户经理", "count_unit": "位",
        "sql_select_col": "t.CUSTMAINMANAGER as 客户经理ID", "sql_group_col": "t.CUSTMAINMANAGER",
        "join_clause": "", "label_col_names": ["CUSTMAINMANAGER"],
    },
    "manager_name": {
        "display_label": "客户经理", "count_unit": "位",
        "sql_select_col": "t.CUSTMANAGERNAME as 客户经理名称", "sql_group_col": "t.CUSTMANAGERNAME",
        "join_clause": "", "label_col_names": ["CUSTMANAGERNAME"],
    },
}
_DEFAULT_COMPARISON_LABELS = {"yoy": "同比", "mom": "环比"}
_DEFAULT_AMOUNT_COL_NAMES = {"USDAMOUNT", "TOTAL_AMOUNT", "DERIVATIVE_AMOUNT"}
_DEFAULT_LABEL_COL_NAMES = {"DIPNAME", "BANKNAME", "银行", "客户经理", "CUSTMANAGERNAME"}

_dimension_config_cache: dict | None = None


def _get_default_dimension_config() -> dict:
    """Return the full default dimension config dict (same shape as DB loader)."""
    all_label_cols = set(_DEFAULT_LABEL_COL_NAMES)
    return {
        "dimensions": dict(_DEFAULT_DIMENSION_CONFIG),
        "comparison_labels": dict(_DEFAULT_COMPARISON_LABELS),
        "amount_col_names": set(_DEFAULT_AMOUNT_COL_NAMES),
        "label_col_names": all_label_cols,
    }


def load_dimension_config() -> dict:
    """Load dimension configuration from DB rules (with memory cache).

    Falls back to hardcoded defaults if DB is unavailable or not yet seeded.
    """
    global _dimension_config_cache
    if _dimension_config_cache is not None:
        return _dimension_config_cache

    try:
        result = mysql_store.load_dimension_labels_from_db()
        if result and result.get("dimensions"):
            _dimension_config_cache = result
            logger.info("Loaded dimension config from DB (%d dimensions)", len(result["dimensions"]))
            return result
    except Exception:
        logger.warning("Could not load dimension labels from DB, using defaults")

    _dimension_config_cache = _get_default_dimension_config()
    return _dimension_config_cache


def reload_rules() -> None:
    """Clear cache so next request reloads from MySQL."""
    global _rules_cache, _dimension_config_cache
    _rules_cache = None
    _dimension_config_cache = None
    mysql_store.init_db()
    logger.info("Rules engine cache cleared, will reload from MySQL on next request")


def _load_rules() -> dict:
    """Load rules from MySQL (with memory cache).

    Returns the same nested dict format as the old semantic_rules.json,
    so gatekeep() doesn't need to change.
    """
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    _rules_cache = mysql_store.load_rules_from_db()
    return _rules_cache


def _has_keyword(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def gatekeep(parsed: dict, original_text: str) -> dict:
    rules = _load_rules()
    overrides: list[str] = []

    # ---- Collect ALL matching app_ids (additive, not override) ----
    appid_set: set[int] = set()
    if parsed.get("appid") is not None:
        appid_set.add(parsed["appid"])

    # ---- 阶段 1a: 铁律 buy_sell 规则 ----
    buy_sell_rules = rules["buy_sell_direction"]["rules"]
    for rule in buy_sell_rules:
        if not rule["customer_reversible"]:
            if _has_keyword(original_text, rule["keywords"]):
                parsed["buy_sell"] = rule["direction"]
                if rule.get("set_app_id"):
                    appid_set.add(rule["set_app_id"])
                overrides.append(
                    f"buy_sell={rule['direction']},appid={rule.get('set_app_id')} ({rule['description']})"
                )
                break

    # ---- 阶段 1b: "结售汇" 特例 ----
    if "结售汇" in original_text:
        appid_set.add(2)
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

    # ---- 阶段 1d: special_states 匹配（使用 parser 的泛化逻辑） ----
    ss = _parser._parse_special_states(original_text)
    if ss:
        parsed["special_states"] = ss
        overrides.append(f"special_states={ss}")

    # ---- 阶段 1d1: lifecycle_status 匹配（使用 parser 的解析逻辑） ----
    ls = _parser._parse_lifecycle_status(original_text)
    if ls:
        parsed["lifecycle_status"] = ls
        overrides.append(f"lifecycle_status={ls}")
        # 如果 lifecycle_status 被检测到，清除可能冲突的 special_states
        # （"逾期"同时出现在 special_states 和 lifecycle_status 中）
        if parsed.get("special_states"):
            parsed["special_states"] = ""
            overrides.append("special_states cleared (lifecycle_status takes priority)")

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
    product_default = rules["product_type"].get("default", "all")
    matched_types = []
    for pr in product_rules:
        if _has_keyword(original_text, pr["keywords"]):
            matched_types.append(pr["value"])
    if len(matched_types) > 1:
        parsed["product_type"] = "all"
    elif len(matched_types) == 1:
        parsed["product_type"] = matched_types[0]
    else:
        parsed["product_type"] = product_default

    # ---- 阶段 1f: app_id 匹配（收集所有匹配项） ----
    appid_rules = rules["app_id"]["rules"]
    for ar in appid_rules:
        if _has_keyword(original_text, ar["keywords"]):
            appid_set.add(ar["value"])
            overrides.append(f"appid={ar['value']} ({ar.get('meaning', '')})")

    # ---- 汇总 appid ----
    if appid_set:
        ids = sorted(appid_set)
        parsed["appid"] = ids if len(ids) > 1 else ids[0]
        if len(ids) > 1:
            overrides.append(f"multi_appid={ids}")
    else:
        parsed["appid"] = None

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

    # ---- 利润检测 ----
    if not parsed.get("profit_type"):
        profit = _parser._parse_profit_type(original_text)
        if profit:
            parsed["profit_type"] = profit
            overrides.append(f"profit_type={profit}")

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
