"""Keywords-based NL parser for FX transaction queries.

No LLM dependency — pure rule matching.
"""

import calendar
import re
import datetime
from typing import Optional


def _parse_product_type(text: str) -> str:
    """Extract product type from query text."""
    has_spot = "即期" in text
    has_fwd = "远期" in text
    has_swap = "掉期" in text

    matched = [t for t, v in [("spot", has_spot), ("fwd", has_fwd), ("swap", has_swap)] if v]
    if len(matched) > 1:
        return "all"
    if len(matched) == 1:
        return matched[0]
    return "all"


def _parse_buy_sell(text: str) -> str:
    """Extract buy/sell direction from query text.

    银行视角映射（与 semantic_rules.json buy_sell_direction 一致）：
      B（银行买入）= 结汇 / 买入
      S（银行卖出）= 购汇 / 售汇 / 卖出
    注意：结汇/购汇/售汇为铁律，不受客户前缀影响
    """
    # 铁律先行
    has_jiehui = "结汇" in text
    has_gouhui_or_shouhui = "购汇" in text or "售汇" in text

    # 结售汇同时出现 → 不筛选方向
    if has_jiehui and has_gouhui_or_shouhui:
        return ""

    if has_jiehui:
        return "B"  # 结汇 = 银行买入
    if has_gouhui_or_shouhui:
        return "S"  # 购汇/售汇 = 银行卖出

    # 可反转规则：买入/卖出（含掉期近远组合）
    has_buy = "买入" in text or "近卖远买" in text
    has_sell = "卖出" in text or "近买远卖" in text

    if has_buy and has_sell:
        return ""
    if has_buy:
        return "B"
    if has_sell:
        return "S"
    return ""


def _parse_date_range(text: str) -> tuple[str, str]:
    """Parse date range from query text.

    Returns (date_start, date_end) as "YYYY-MM-DD" strings.
    """
    today = datetime.date.today()
    year = today.year
    month = today.month

    # Priority 1: explicit "YYYY-MM-DD 到 YYYY-MM-DD"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})\s*到\s*(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return (
            f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
            f"{m.group(4)}-{m.group(5)}-{m.group(6)}",
        )

    # Priority 2: "YYYY年MM月DD日" (single date)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if m:
        d = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return (d, d)

    # Priority 3: "YYYY年MM月" (whole month)
    m = re.search(r"(\d{4})年(\d{1,2})月", text)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        last_day = calendar.monthrange(y, mo)[1]
        return (f"{y:04d}-{mo:02d}-01", f"{y:04d}-{mo:02d}-{last_day:02d}")

    # Priority 4: "今年N月"
    m = re.search(r"今年\s*(\d{1,2})\s*月", text)
    if m:
        mo = int(m.group(1))
        last_day = calendar.monthrange(year, mo)[1]
        return (f"{year:04d}-{mo:02d}-01", f"{year:04d}-{mo:02d}-{last_day:02d}")

    # Priority 4.5: "今年N季度" / "今年第N季度"
    m = re.search(r"今年\s*(?:第)?\s*([一二三四1-4])\s*(?:季度|季)", text)
    if m:
        q_map = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}
        q = q_map.get(m.group(1))
        if q:
            start_month = (q - 1) * 3 + 1
            end_month = q * 3
            last_day = calendar.monthrange(year, end_month)[1]
            return (
                f"{year:04d}-{start_month:02d}-01",
                f"{year:04d}-{end_month:02d}-{last_day:02d}",
            )

    # Priority 5: "今年"
    if "今年" in text:
        return (f"{year}-01-01", today.strftime("%Y-%m-%d"))

    # Priority 5: "本月"
    if "本月" in text:
        return (f"{year}-{month:02d}-01", today.strftime("%Y-%m-%d"))

    # Priority 6: "本周"
    if "本周" in text:
        weekday = today.weekday()
        monday = today - datetime.timedelta(days=weekday)
        return (monday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))

    # Priority 7: 上旬/中旬/下旬 (隐含本月)
    if "上旬" in text:
        return (f"{year}-{month:02d}-01", f"{year}-{month:02d}-10")
    if "中旬" in text:
        return (f"{year}-{month:02d}-11", f"{year}-{month:02d}-20")
    if "下旬" in text:
        last_day = calendar.monthrange(year, month)[1]
        return (f"{year}-{month:02d}-21", f"{year}-{month:02d}-{last_day:02d}")

    # Priority 8: "昨天"
    if "昨天" in text:
        yesterday = today - datetime.timedelta(days=1)
        d = yesterday.strftime("%Y-%m-%d")
        return (d, d)

    # Priority 9: "今天"
    if "今天" in text:
        d = today.strftime("%Y-%m-%d")
        return (d, d)

    # Priority 9.5: "第N季度" / "N季度"（隐含今年）
    m = re.search(r"(?:第)?\s*([一二三四1-4])\s*(?:季度|季)", text)
    if m:
        q_map = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}
        q = q_map.get(m.group(1))
        if q:
            start_month = (q - 1) * 3 + 1
            end_month = q * 3
            last_day = calendar.monthrange(year, end_month)[1]
            return (
                f"{year:04d}-{start_month:02d}-01",
                f"{year:04d}-{end_month:02d}-{last_day:02d}",
            )

    # Priority 10: "上月" / "上个月"
    if "上月" in text or "上个月" in text:
        first_of_this_month = today.replace(day=1)
        last_month_end = first_of_this_month - datetime.timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return (
            last_month_start.strftime("%Y-%m-%d"),
            last_month_end.strftime("%Y-%m-%d"),
        )

    # Priority 10: "近N个月"
    m = re.search(r"近(\d+)个?月", text)
    if m:
        n = int(m.group(1))
        total_months = today.year * 12 + today.month - 1 - n
        start_year, start_month = total_months // 12, total_months % 12 + 1
        return (
            f"{start_year:04d}-{start_month:02d}-01",
            today.strftime("%Y-%m-%d"),
        )

    # Priority 11: "近N年"
    m = re.search(r"近(\d+)年", text)
    if m:
        n = int(m.group(1))
        start = today.replace(year=today.year - n)
        return (start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))

    # Priority 12: "近N天"
    m = re.search(r"近(\d+)天", text)
    if m:
        n = int(m.group(1))
        start = today - datetime.timedelta(days=n)
        return (start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))

    # Priority 13: "本季度"
    if "本季度" in text:
        quarter_start_month = (month - 1) // 3 * 3 + 1
        quarter_start = today.replace(month=quarter_start_month, day=1)
        return (
            quarter_start.strftime("%Y-%m-%d"),
            today.strftime("%Y-%m-%d"),
        )

    return ("", "")


def _parse_bank_name(text: str) -> str:
    """Extract bank / institution name from query text.

    Supports patterns:
      - XX银行             → 工商银行
      - XX分行/支行/分公司/营业部  → 北京分公司
      - XX银行XX分行       → 中国银行北京分行
    """
    # Full match: "XX银行XX分行/支行"
    m = re.search(
        r"([一-鿿]{2,}(?:银行|公司))([一-鿿]{2,}(?:分行|支行|分公司|营业部))",
        text,
    )
    if m:
        return m.group(0)

    # Bank name: "XX银行"
    m = re.search(r"([一-鿿]{2,}银行)", text)
    if m:
        return m.group(1)

    # Branch name: "XX分行/支行/分公司/营业部"
    m = re.search(r"([一-鿿]{2,}(?:分行|支行|分公司|营业部))", text)
    if m:
        return m.group(1)

    return ""


def _parse_special_states(text: str) -> str:
    """Extract special state filter from query text.

    返回逗号分隔的状态值，如 "0,1"。
    映射（与 semantic_rules.json 一致）：
      逾期/已过期 → 1, 展期/延期 → 3, 提前交割 → 4, 平仓/已平仓 → 5

    注意："在途"不是 SPECIALSTATE 字段，不在此处处理。
    "在途"=totaldelivery 表剩余金额>0（未完结），可能表现为签约、展期远端、提前交割近端。
    """
    rules = [
        (["逾期", "已过期"], "1"),
        (["展期", "延期"], "3"),
        (["提前交割", "提前交收"], "4"),
        (["平仓", "已平仓"], "5"),
    ]
    matched = []
    for keywords, value in rules:
        if any(kw in text for kw in keywords):
            matched.append(value)
    return ",".join(matched) if matched else ""


def _parse_trade_class(text: str) -> str:
    """Extract trade class (SPECTRADECLASS) from query text."""
    # 先精确匹配（长关键词优先），再泛化匹配
    specific_rules = [
        (["全部平仓"], "6"),
        (["交割日平仓"], "2"),
        (["提前平仓"], "1,10"),
        (["到期平仓"], "11"),
        (["近端提前平仓"], "17"),
        (["近端到期平仓"], "15"),
        (["反向平盘"], "7"),
        (["近端原价展期"], "12"),
        (["近端市价展期"], "13"),
        (["原价展期"], "5"),
        (["市价展期"], "3"),
        (["近端提前交割"], "16"),
        (["近端到期交割"], "14"),
        (["普通交易", "正常交易"], "0"),
    ]
    # 泛化规则（仅在没有精确匹配时生效）
    broad_rules = [
        (["平仓", "平盘"], "1,2,6,7,10,11,15,17"),
        (["展期"], "3,5,12,13"),
        (["提前交割"], "4,16"),
    ]

    matched_set = set()

    # 先精确匹配
    for keywords, value_str in specific_rules:
        if any(kw in text for kw in keywords):
            for v in value_str.split(","):
                matched_set.add(v)

    # 如果没有精确匹配，才使用泛化规则
    if not matched_set:
        for keywords, value_str in broad_rules:
            if any(kw in text for kw in keywords):
                for v in value_str.split(","):
                    matched_set.add(v)

    return ",".join(sorted(matched_set, key=int)) if matched_set else ""


_CN_NUM = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100, "千": 1000, "万": 10000,
}


def _cn_to_int(s: str) -> Optional[int]:
    """Convert a Chinese numeral string to integer.  Returns None on failure.

    Supports patterns: 十(10), 十五(15), 二十(20), 二十五(25), 九十九(99),
    一百(100), 一百零五(105), 一百二十(120).
    """
    s = s.strip()
    if not s:
        return None
    # Already an Arabic number
    if s.isdigit():
        return int(s)
    # Hybrid: "100强" or "100多名" — extract leading digits
    m = re.match(r"(\d+)", s)
    if m:
        return int(m.group(1))

    if s == "十":
        return 10

    total = 0
    section = 0
    for ch in s:
        v = _CN_NUM.get(ch)
        if v is None:
            return None
        if v >= 10:
            section = (section or 1) * v
            if v >= 100:
                total += section
                section = 0
        else:
            section += v  # digit after multiplier adds (十五=10+5)
    total += section
    return total if total > 0 else None


def _parse_top_n(text: str) -> Optional[int]:
    """Extract top-N ranking count from query text.

    Supports: TOP 10, top10, 前10, 前十, top十, 前二十, TOP 100, 排名/排行(默认10).
    """
    # Priority 1: TOP N / top N (Arabic or Chinese numeral, optional space)
    m = re.search(r"[Tt][Oo][Pp]\s*([\d十百千万两零一二三四五六七八九]+)", text)
    if m:
        n = _cn_to_int(m.group(1))
        if n is not None:
            return n

    # Priority 2: 前N (Arabic or Chinese numeral)
    m = re.search(r"前\s*([\d十百千万两零一二三四五六七八九]+)", text)
    if m:
        n = _cn_to_int(m.group(1))
        if n is not None:
            return n

    # Priority 3: 排名 / 排行 without a number → default 10
    if "排名" in text or "排行" in text:
        return 10

    return None


def _parse_aggregate(text: str) -> bool:
    """Detect whether the user wants aggregated summary rather than detail rows."""
    keywords = ["交易量", "金额", "总额", "总计", "汇总"]
    return any(kw in text for kw in keywords)


def _parse_hedge_ratio(text: str) -> bool:
    """Detect whether the query mentions hedge ratio (套保率)."""
    return "套保率" in text


def _parse_amount_filter(text: str) -> Optional[dict]:
    """Extract amount filter condition from query text.

    Returns dict with keys amount_op / amount_value, or None.
    """
    # Priority keywords for operator detection
    gte_pat = re.compile(r"大于等于|不低于|不少于")
    gt_pat = re.compile(r"大于|超过|高于|以上")
    lte_pat = re.compile(r"小于等于|不超过|不多于")
    lt_pat = re.compile(r"小于|不足|低于|不到|以内|以下")

    op = None
    if gte_pat.search(text):
        op = "gte"
    elif gt_pat.search(text):
        op = "gt"
    elif lte_pat.search(text):
        op = "lte"
    elif lt_pat.search(text):
        op = "lt"

    if op is None:
        return None

    # Extract number
    m = re.search(r"\d+(?:\.\d+)?", text)
    if m is None:
        return None
    num = float(m.group())

    # Detect unit right after the number (look at most 5 chars forward)
    after_text = text[m.end():m.end() + 5]
    multiplier = 1
    if "万美元" in after_text:
        multiplier = 10000
    elif "万元" in after_text:
        multiplier = 10000
    elif "%" in after_text or "％" in after_text:
        multiplier = 1
    elif "万" in after_text:
        multiplier = 10000
    elif "亿" in after_text:
        multiplier = 100000000

    return {
        "amount_op": op,
        "amount_value": num * multiplier,
    }


def _parse_cust_name(text: str) -> str:
    """Extract specific customer name from query text.

    匹配模式：
      1. XX客户 → "XX客户"（XX 为至少一个中文字符）
      2. XX的套保率 → "XX"（客户维度下，提取"的套保率"之前的名称）

    例如：
      "测试客户的套保率"  → "测试客户"
      "小鱼儿的套保率"    → "小鱼儿"
    """
    # Pattern 1: "XX客户"
    m = re.search(r"([一-鿿a-zA-Z0-9]{1,})客户", text)
    if m:
        name = m.group(1) + "客户"
        # 去掉时间前缀干扰（如 "今年测试客户" → "测试客户"）
        time_prefixes = ["今年", "本月", "本周", "本季度", "上月", "上个月", "昨天", "今天"]
        for prefix in time_prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        # 排除纯排序词、空名称、含排名关键词的名称
        if name in ("客户", "前客户", "个客户", "的客户"):
            return ""
        if re.search(r"排名|前\d+|TOP\d*", name, re.IGNORECASE):
            return ""
        # 排除 "N的客户" / "N个客户" 等排名修饰模式（如 "10的客户" 实为 TOP 10 客户）
        if re.match(r"^\d+(个|的)客户$", name):
            return ""
        return name

    # Pattern 2: "XX的套保率"（客户维度但名称不含"客户"后缀）
    m = re.search(r"([一-鿿a-zA-Z0-9]{1,})的套保率", text)
    if m:
        name = m.group(1)
        skip = {"客户", "机构"}
        if name not in skip and not re.search(r"排名|前\d+|TOP\d*", name, re.IGNORECASE):
            return name

    return ""


def _parse_comparison_modifier(text: str) -> str:
    """Detect comparison modifiers: 同比 (YoY) / 环比 (MoM).

    Returns "yoy", "mom", or "".
    "同步" is semantically equivalent to "同比" in financial context (同步增加=YoY increase).
    """
    if "同比" in text:
        return "yoy"
    if "环比" in text:
        return "mom"
    if "同步" in text:
        return "yoy"
    return ""


def compute_comparison_dates(date_start: str, date_end: str, comparison: str) -> tuple[str, str]:
    """Compute the comparison date range for YoY/MoM queries.

    Returns (compare_start, compare_end) as "YYYY-MM-DD" strings.
    Handles leap-year edge cases: Feb 29 → Feb 28 in non-leap years.
    """
    if not date_start or not date_end or not comparison:
        return ("", "")

    start = datetime.date.fromisoformat(date_start)
    end = datetime.date.fromisoformat(date_end)
    _calendar = calendar.Calendar()

    if comparison == "yoy":
        try:
            cmp_start = start.replace(year=start.year - 1)
        except ValueError:
            cmp_start = start.replace(year=start.year - 1, day=start.day - 1)  # Feb 29 → Feb 28

        try:
            cmp_end = end.replace(year=end.year - 1)
        except ValueError:
            cmp_end = end.replace(year=end.year - 1, day=end.day - 1)

    elif comparison == "mom":
        # Shift back by the interval length between start and end
        delta = end - start
        cmp_end = start - datetime.timedelta(days=1)
        cmp_start = cmp_end - delta
    else:
        return ("", "")

    return (cmp_start.strftime("%Y-%m-%d"), cmp_end.strftime("%Y-%m-%d"))


def _parse_dimension(text: str) -> str:
    """Detect aggregation dimension from query text.

    Priority (longest match first):
      customer_id   — 客户号 / 客户编号 / 客户ID
      manager       — 客户经理ID / 客户经理编号
      manager_name  — 客户经理名称 / 客户经理姓名 / 客户经理
      customer      — 客户名称 / 客户
      bank          — default
    """
    if re.search(r"客户号|客户编号|客户ID|客户\s*ID", text):
        return "customer_id"
    if re.search(r"客户经理\s*ID|客户经理编号", text):
        return "manager"
    if re.search(r"客户经理名称|客户经理姓名|客户经理", text):
        return "manager_name"
    if "客户" in text:
        return "customer"
    return "bank"


def rule_based_parse(text: str) -> dict:
    """Parse a natural-language FX transaction query into structured fields.

    Returns
    -------
    dict with keys: product_type, date_start, date_end, special_states,
                    buy_sell, bank_name, aggregate, top_n, amount_filter,
                    dimension, hedge_ratio, appid
    """
    date_start, date_end = _parse_date_range(text)

    amount_filter = _parse_amount_filter(text) or {}
    cust_name = _parse_cust_name(text)
    dimension = _parse_dimension(text)
    bank_name = _parse_bank_name(text)

    # 明确指定客户名称时，强制按客户维度聚合
    if cust_name:
        dimension = "customer"
        bank_name = ""
    elif dimension == "customer":
        # When query is customer-oriented, bank name filter should not apply
        bank_name = ""

    # 结售汇相关词 → 自动设置 appid=2
    is_jieshouhui = any(kw in text for kw in ["结汇", "购汇", "售汇", "结售汇", "近购远结", "近售远结", "近结远购", "近结远售"])
    if is_jieshouhui:
        appid = 2
    else:
        appid = None

    # "结售汇" 同时含结汇和售汇 → 不筛选方向
    if "结售汇" in text:
        buy_sell = ""
    else:
        buy_sell = _parse_buy_sell(text)

    return {
        "product_type": _parse_product_type(text),
        "date_start": date_start,
        "date_end": date_end,
        "special_states": _parse_special_states(text),
        "trade_class": _parse_trade_class(text),
        "buy_sell": buy_sell,
        "bank_name": bank_name,
        "cust_name": cust_name,
        "aggregate": _parse_aggregate(text),
        "top_n": _parse_top_n(text),
        "amount_filter": amount_filter if amount_filter else None,
        "dimension": dimension,
        "hedge_ratio": _parse_hedge_ratio(text),
        "appid": appid,
        "comparison": _parse_comparison_modifier(text),
    }


# ---- Confidence scoring ----

def _has_quarter_mismatch(text: str, parsed: dict) -> bool:
    """Detect if query mentions a specific quarter but rule parser returned YTD.

    E.g. "今年一季度" matched "今年" (Priority 5) → returns YTD instead of Q1.
    """
    has_quarter = bool(re.search(r"[一二三四1-4]\s*(?:季度|季)", text))
    if not has_quarter:
        return False
    end = parsed.get("date_end", "")
    if not end or len(end) < 7:
        return False
    # If date_end ends with 03/06/09/12, it's likely a correct quarter boundary
    month_part = end[-5:-3] if len(end) >= 7 else ""
    return month_part not in ("03", "06", "09", "12")


def _text_has_entity_keyword(text: str) -> bool:
    """Check if the query text contains any entity (bank/customer) keyword."""
    has_bank = bool(re.search(
        r"(?:银行|分行|支行|分公司|营业部|公司)",
        text,
    ))
    has_cust = bool(re.search(r"客户", text))
    return has_bank or has_cust


def _rule_confidence(text: str, parsed: dict) -> float:
    """Calculate rule-based parse confidence 0.0~1.0.

    Measures whether core required fields were successfully extracted
    from the query text. Default values (like product_type='all') don't
    contribute to confidence.

    Core fields:
      Date (weight 1.5): Most critical — wrong dates mean wrong results.
      Entity (weight 1.0): Bank or customer name, or text has no entity.
      Intent (weight 1.5): aggregate/hedge_ratio/top_n/amount_filter.

    Returns 0.0~1.0. >=0.8 means rules are confident, skip LLM.
    """
    core_score = 0.0
    core_total = 4.0

    # Date (weight 1.5)
    if parsed.get("date_start") and parsed.get("date_end"):
        if _has_quarter_mismatch(text, parsed):
            core_score += 0.3   # Quarter detected but YTD returned → penalty
        else:
            core_score += 1.5

    # Entity (weight 1.0)
    if parsed.get("bank_name") or parsed.get("cust_name"):
        core_score += 1.0
    elif not _text_has_entity_keyword(text):
        core_score += 1.0   # No entity in query → not a failure

    # Intent (weight 1.5)
    if any([
        parsed.get("aggregate"),
        parsed.get("hedge_ratio"),
        parsed.get("top_n"),
        parsed.get("amount_filter"),
    ]):
        core_score += 1.5

    return min(core_score / core_total, 1.0)
