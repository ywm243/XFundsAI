"""Result formatting service — summary, chart, insights, comparison.

Extracted from app.py to eliminate circular imports (langgraph/bi_agent.py
previously imported these functions from app).
"""

import logging

from llm_parser.rules_engine import load_dimension_config

logger = logging.getLogger(__name__)


def _get_dimension_config():
    return load_dimension_config()


_PROFIT_COL_NAMES = {"BRANCH_PROFIT_USD", "BRANCH_PROFIT_CNY", "CUSTOMER_PROFIT_USD", "CUSTOMER_PROFIT_CNY"}

_LIFECYCLE_LABELS = {
    "not_due": "未到期",
    "overdue": "逾期",
    "due_today": "已到期",
    "unclosed": "未完结",
    "closed": "已完结",
}

_SPECIAL_STATE_LABELS = [
    ("0", "开仓"),
    ("1,2,6,7,10,11,15,17", "平仓"),
    ("3,5,12,13", "展期"),
    ("4,16", "提前交割"),
]


_PROFIT_LABELS = {
    "branch_profit_usd": "分行利润(美元)",
    "branch_profit_cny": "分行利润(人民币)",
    "customer_profit_usd": "客户损益(美元)",
    "customer_profit_cny": "客户损益(人民币)",
}


def _metric_label(parsed: dict) -> str:
    """Return the display label for the queried metric, accounting for profit/lifecycle/special states."""
    profit_type = parsed.get("profit_type", [])
    if profit_type:
        labels = [_PROFIT_LABELS.get(k, k) for k in profit_type]
        return "+".join(labels)

    lc = parsed.get("lifecycle_status", "")
    if lc in _LIFECYCLE_LABELS:
        return f"{_LIFECYCLE_LABELS[lc]}交易量"

    ss = parsed.get("special_states", "")
    if ss:
        for values, label in _SPECIAL_STATE_LABELS:
            if set(ss.split(",")) == set(values.split(",")):
                return f"{label}交易量"
        # Partial match: find the best label
        ss_set = set(ss.split(","))
        for values, label in _SPECIAL_STATE_LABELS:
            if ss_set <= set(values.split(",")):
                return f"{label}交易量"

    return "交易量"


def _amount_col_names():
    return _get_dimension_config().get("amount_col_names", {"USDAMOUNT", "TOTAL_AMOUNT", "DERIVATIVE_AMOUNT"}) | _PROFIT_COL_NAMES


def _label_col_names():
    return _get_dimension_config().get("label_col_names", {"DIPNAME", "BANKNAME", "银行", "客户经理", "CUSTMANAGERNAME"})


def find_amount_col(cols: list) -> int:
    """Find the index of the numeric amount column."""
    acn = _amount_col_names()
    for i, c in enumerate(cols):
        if c.upper() in acn:
            return i
    return 0


def find_label_col(cols: list) -> int:
    """Find the index of the label/dimension column (bank name, etc.)."""
    lcn = _label_col_names()
    for i, c in enumerate(cols):
        if c.upper() in lcn:
            return i
    return 0


def compute_comparison(current_rows, compare_rows, comparison, date_start, date_end, cmp_start, cmp_end, cols=None):
    """Compute change_amount and change_rate from current and comparison rows.

    Returns a dict with keys: type, label, change_amount, change_rate,
    compare_amount, date_start, date_end, cmp_start, cmp_end.
    """
    amt_idx = find_amount_col(cols) if cols else 0
    label_map = _get_dimension_config().get("comparison_labels", {"yoy": "同比", "mom": "环比"})
    total_current = sum(float(r[amt_idx] if isinstance(r, (list, tuple)) and r[amt_idx] is not None else 0) for r in current_rows) if current_rows else 0
    total_compare = sum(float(r[amt_idx] if isinstance(r, (list, tuple)) and r[amt_idx] is not None else 0) for r in compare_rows) if compare_rows else 0

    if total_compare == 0:
        return {
            "type": comparison,
            "label": label_map.get(comparison, comparison),
            "change_amount": 0,
            "change_rate": 0,
            "compare_amount": 0,
            "date_start": date_start, "date_end": date_end,
            "cmp_start": cmp_start, "cmp_end": cmp_end,
        }

    change_amount = total_current - total_compare
    change_rate = round((change_amount / total_compare) * 100, 2)

    return {
        "type": comparison,
        "label": label_map.get(comparison, comparison),
        "change_amount": round(change_amount, 2),
        "change_rate": change_rate,
        "compare_amount": round(total_compare, 2),
        "date_start": date_start, "date_end": date_end,
        "cmp_start": cmp_start, "cmp_end": cmp_end,
    }


def merge_comparison_into_rows(rows: list, cmp_rows: list, cols: list, comparison_label: str) -> tuple[list, list]:
    """Add comparison change rate as a new column to each row.

    Returns (new_columns, new_rows) with an added comparison column.
    """
    if not cmp_rows or not rows:
        return cols, rows

    bank_idx = None
    for i, c in enumerate(cols):
        if c in ("BANKNAME", "银行"):
            bank_idx = i
            break
    if bank_idx is None:
        return cols, rows

    cmp_map = {}
    for cr in cmp_rows:
        if len(cr) > bank_idx:
            key = str(cr[bank_idx])
            cmp_map[key] = cr[0]

    new_cols = list(cols) + [f"{comparison_label}_CHANGE"]
    new_rows = []
    for row in rows:
        new_row = list(row)
        bank_val = str(row[bank_idx]) if len(row) > bank_idx else ""
        cmp_val = cmp_map.get(bank_val, 0)
        current_val = float(row[0]) if row and row[0] is not None else 0
        if current_val and cmp_val:
            rate = round(((current_val - float(cmp_val)) / float(cmp_val)) * 100, 2)
        else:
            rate = 0
        new_row.append(f"{rate:+.2f}%")
        new_rows.append(new_row)

    return new_cols, new_rows


def build_summary(parsed: dict, rows: list, cols: list, comparison: dict | None) -> str:
    """Build natural language summary for ResultCard section 1."""
    if not rows or not cols:
        return ""

    date_start = parsed.get("date_start", "") or ""
    date_end = parsed.get("date_end", "") or ""
    bank_name = (parsed.get("bank_name") or "")

    parts = [f"{date_start} ~ {date_end}"]
    if bank_name:
        parts.append(f"{bank_name}")

    # Profit metrics summary
    profit_type = parsed.get("profit_type", [])
    if profit_type:
        dim = parsed.get("dimension", "bank")
        dimensions_cfg = _get_dimension_config().get("dimensions", {})
        dim_info = dimensions_cfg.get(dim, {})
        dim_label = dim_info.get("display_label", "机构")
        count_unit = dim_info.get("count_unit", "家")
        total_count = len(rows)
        if not (bank_name and total_count == 1):
            parts.append(f"共{total_count}{count_unit}{dim_label}")

        # Find each profit column and summarize
        for metric_key in profit_type:
            alias = {"branch_profit_usd": "BRANCH_PROFIT_USD", "branch_profit_cny": "BRANCH_PROFIT_CNY",
                     "customer_profit_usd": "CUSTOMER_PROFIT_USD", "customer_profit_cny": "CUSTOMER_PROFIT_CNY"}.get(metric_key, "")
            if alias and alias in [c.upper() for c in cols]:
                col_idx = [c.upper() for c in cols].index(alias)
                total = sum(float(r[col_idx]) for r in rows if r and len(r) > col_idx and r[col_idx] is not None)
                label = _PROFIT_LABELS.get(metric_key, metric_key)
                unit = "万元" if "CNY" in metric_key else "万美元"
                parts.append(f"{label}{total/10000:,.2f}{unit}")

        # Also include trade volume if present
        if "TOTAL_AMOUNT" in [c.upper() for c in cols]:
            amt_idx = [c.upper() for c in cols].index("TOTAL_AMOUNT")
            total_amt = sum(float(r[amt_idx]) for r in rows if r and len(r) > amt_idx and r[amt_idx] is not None)
            parts.append(f"交易量{total_amt/10000:,.2f}万美元")

        # Add comparison info for profit queries
        if comparison:
            cmp_label = comparison.get("label", "")
            rate = comparison.get("change_rate")
            direction = "增长" if (comparison.get("change_amount") or 0) >= 0 else "下降"
            amt = abs(comparison.get("change_amount", 0) or 0) / 10000
            if rate is not None:
                parts.append(f"{cmp_label}{direction}{amt:,.2f}万美元（{rate:+.2f}%）")
            else:
                parts.append(f"{cmp_label}{direction}{amt:,.2f}万美元")

        return "，".join(parts) + "。"

    # Original volume-only summary
    amt_idx = find_amount_col(cols)
    total_usd = sum(float(r[amt_idx]) for r in rows if r and r[amt_idx] is not None) / 10000 if rows else 0
    total_count = len(rows)

    dim = parsed.get("dimension", "bank")
    dimensions_cfg = _get_dimension_config().get("dimensions", {})
    dim_info = dimensions_cfg.get(dim, {})
    dim_label = dim_info.get("display_label", "机构")
    count_unit = dim_info.get("count_unit", "家")

    if parsed.get("aggregate"):
        if not (bank_name and total_count == 1):
            parts.append(f"共{total_count}{count_unit}{dim_label}")
    else:
        parts.append(f"共{total_count}笔交易")

    parts.append(f"合计{_metric_label(parsed)}{total_usd:,.2f}万美元")

    if comparison:
        cmp_label = comparison.get("label", "")
        rate = comparison.get("change_rate")
        direction = "增长" if (comparison.get("change_amount") or 0) >= 0 else "下降"
        amt = abs(comparison.get("change_amount", 0) or 0) / 10000
        if rate is not None:
            parts.append(f"{cmp_label}{direction}{amt:,.2f}万美元（{rate:+.2f}%）")
        else:
            parts.append(f"{cmp_label}{direction}{amt:,.2f}万美元")

    return "，".join(parts) + "。"


def build_chart_option(parsed: dict, rows: list, cols: list, comparison: dict | None) -> dict | None:
    """Build ECharts option for ResultCard section 2."""
    if not rows or not cols:
        return None

    label_idx = find_label_col(cols)
    cols_upper = [c.upper() for c in cols]

    bank_name = (parsed.get("bank_name") or "").strip() or "全市场"
    metric = _metric_label(parsed)
    title_parts = [f"{bank_name}{metric}"]
    date_start = parsed.get("date_start", "") or ""
    date_end = parsed.get("date_end", "") or ""
    if date_start and date_end:
        title_parts.append(f"（{date_start} ~ {date_end}）")

    x_data = [str(r[label_idx]) if r else "" for r in rows]

    # Multi-metric chart for profit queries
    profit_type = parsed.get("profit_type", [])
    chart_colors = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6"]
    series = []

    if profit_type:
        for i, metric_key in enumerate(profit_type):
            alias = {"branch_profit_usd": "BRANCH_PROFIT_USD", "branch_profit_cny": "BRANCH_PROFIT_CNY",
                     "customer_profit_usd": "CUSTOMER_PROFIT_USD", "customer_profit_cny": "CUSTOMER_PROFIT_CNY"}.get(metric_key, "")
            if alias and alias in cols_upper:
                col_idx = cols_upper.index(alias)
                data = [float(r[col_idx]) / 10000 if r and len(r) > col_idx and r[col_idx] is not None else 0 for r in rows]
                series.append({
                    "name": _PROFIT_LABELS.get(metric_key, metric_key),
                    "type": "bar",
                    "data": data,
                    "itemStyle": {"color": chart_colors[i % len(chart_colors)]},
                })

        # Add trade volume if present
        if "TOTAL_AMOUNT" in cols_upper:
            vol_idx = cols_upper.index("TOTAL_AMOUNT")
            data = [float(r[vol_idx]) / 10000 if r and len(r) > vol_idx and r[vol_idx] is not None else 0 for r in rows]
            series.append({
                "name": "交易量(万美元)",
                "type": "bar",
                "data": data,
                "itemStyle": {"color": chart_colors[len(profit_type) % len(chart_colors)]},
            })
    else:
        # Single-metric chart (original logic)
        amt_idx = find_amount_col(cols)
        series_data = [float(r[amt_idx]) if r and r[amt_idx] is not None else 0 for r in rows]
        series = [{"name": metric, "type": "bar", "data": series_data, "itemStyle": {"color": "#3b82f6"}}]

    if comparison:
        cmp_label = comparison.get("label", "对比")
        cmp_amt = comparison.get("compare_amount", 0) / 10000
        series.append({
            "name": cmp_label,
            "type": "bar",
            "data": [round(cmp_amt, 2)] * len(x_data),
            "itemStyle": {"color": "#94a3b8"},
        })

    return {
        "title": {"text": "".join(title_parts), "left": "center"},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [s["name"] for s in series], "bottom": 0},
        "xAxis": {"type": "category", "data": x_data, "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "value", "name": "万"},
        "series": series,
        "grid": {"left": 60, "right": 20, "bottom": 40, "top": 40},
    }


def build_insights(parsed: dict, rows: list, cols: list,
                    comparison: dict | None, user_query: str = "") -> list[dict]:
    """Build analysis insights from templates (deep analysis via /api/analyze)."""
    if not rows:
        return []

    amt_idx = find_amount_col(cols)
    fallback = []

    if comparison:
        rate = comparison.get("change_rate")
        direction = "增长" if (comparison.get("change_amount") or 0) >= 0 else "下降"
        cmp_label = comparison.get("label", "对比")
        amt = abs(comparison.get("change_amount", 0) or 0) / 10000
        text = f"较{cmp_label}{direction}了{amt:,.2f}万美元"
        text += f"（{rate:+.2f}%）" if rate is not None else ""
        fallback.append({
            "type": "growth" if (comparison.get("change_amount") or 0) >= 0 else "risk",
            "title": f"{cmp_label}变化",
            "detail": text,
        })

    bank_idx = find_label_col(cols) if cols else None
    if bank_idx is not None and len(rows) > 1:
        vals = [(float(r[amt_idx]) if len(r) > amt_idx and r[amt_idx] is not None else 0) for r in rows]
        max_val = max(vals)
        max_row = rows[vals.index(max_val)]
        max_name = str(max_row[bank_idx]) if max_row and len(max_row) > bank_idx else ""
        if max_name and max_val > 0:
            fallback.append({
                "type": "quality",
                "title": f"{_metric_label(parsed)}分布",
                "detail": f"最高为 {max_name}（{max_val/10000:,.2f} 万美元）",
            })

    return fallback
