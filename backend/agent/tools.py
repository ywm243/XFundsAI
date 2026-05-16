"""Analysis tools — query_metrics and decompose_change.

Both tools reuse TradeQueryBuilder for SQL generation and Oracle execution.
All return values are real data from database, never LLM-generated.
"""

import logging
from datetime import datetime

from db.query_builder import TradeQueryBuilder
from db.connection import get_db
from llm_parser.parser import compute_comparison_dates

logger = logging.getLogger(__name__)

# Known metrics registry
METRICS = {
    "trading_volume": {
        "label": "交易量",
        "sql_agg": "SUM(t.USDAMOUNT)",
    },
    "hedge_ratio": {
        "label": "套保率",
        "sql_agg": None,  # special handling
    },
}

# Known dimensions registry
DIMENSIONS = {
    "product_type": {"label": "产品类型", "group_col": "t.PT", "select_col": "t.PT as 产品类型"},
    "bank": {"label": "机构", "group_col": "b.DIPNAME", "select_col": "b.DIPNAME as 机构名称"},
    "manager_name": {"label": "客户经理", "group_col": "t.CUSTMANAGERNAME", "select_col": "t.CUSTMANAGERNAME as 客户经理名称"},
    "customer": {"label": "客户", "group_col": "t.CUSTNAME", "select_col": "t.CUSTNAME as 客户名称"},
    "month": {"label": "月份", "group_col": "TO_CHAR(t.TRADEDATE, 'YYYY-MM')", "select_col": "TO_CHAR(t.TRADEDATE, 'YYYY-MM') as 月份"},
}


def _execute_sql(sql: str) -> tuple[list, list]:
    """Execute SQL against Oracle and return (columns, rows)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [desc[0] for desc in cur.description] if cur.description else []
            rows = [list(row) for row in cur.fetchmany(10000)]
    return cols, rows


def _build_filters(filters: dict | None) -> dict:
    """Convert generic filters dict to TradeQueryBuilder-compatible params."""
    f = filters or {}
    params = {}
    if f.get("product_type"):
        params["product_type"] = f["product_type"]
    if f.get("bank_name"):
        params["bank_name"] = f["bank_name"]
    if f.get("cust_name"):
        params["cust_name"] = f["cust_name"]
    if f.get("buy_sell"):
        params["buy_sell"] = f["buy_sell"]
    if f.get("special_states"):
        raw = f["special_states"]
        if isinstance(raw, str):
            params["special_states"] = [s.strip() for s in raw.split(",") if s.strip().isdigit()]
    if f.get("appid"):
        params["appid"] = f["appid"]
    return params


def _convert_rows_to_dicts(cols: list, rows: list) -> list[dict]:
    """Convert (cols, rows) to list of dicts."""
    return [dict(zip(cols, row)) for row in rows]


# ---- Public tools ----


def query_metrics(
    metrics: list[str],
    dimensions: list[str] | None = None,
    filters: dict | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    comparison: str = "",
    top_n: int = 0,
) -> dict:
    """Generic metric query tool.

    Args:
        metrics: List of metric names (e.g. ["trading_volume"]).
        dimensions: Optional list of dimension names for grouping.
        filters: Optional dict of filter conditions.
        date_start: Start date YYYY-MM-DD.
        date_end: End date YYYY-MM-DD.
        comparison: "yoy", "mom", or "".
        top_n: Limit rows (0 = no limit).

    Returns:
        dict with keys: metrics, dimensions, date_range, comparison, data, summary
    """
    f = _build_filters(filters)
    f.setdefault("product_type", "all")

    # Determine if we need hedge_ratio special handling
    is_hedge_ratio = "hedge_ratio" in metrics

    # ---- Execute SQL ----
    if is_hedge_ratio and not dimensions:
        # Hedge ratio aggregate query
        sql = TradeQueryBuilder.build_hedge_ratio_query(
            product_type=f.get("product_type", "all"),
            dimension="bank",
            date_start=date_start or None,
            date_end=date_end or None,
            buy_sell=f.get("buy_sell"),
            special_states=f.get("special_states"),
            appid=f.get("appid"),
            bank_name=f.get("bank_name"),
            cust_name=f.get("cust_name"),
        )
        cols, rows = _execute_sql(sql)
        data_rows = _convert_rows_to_dicts(cols, rows)

        total_hedge_ratio = 0
        total_derivative = 0
        total_amount = 0
        for r in rows:
            try:
                total_derivative += float(r[2] or 0)  # DERIVATIVE_AMOUNT
                total_amount += float(r[4] or 0)      # TOTAL_AMOUNT
            except (ValueError, IndexError):
                pass
        summary = {
            "total_hedge_ratio": round(total_derivative / total_amount * 100, 2) if total_amount else 0,
            "total_derivative_amount": total_derivative,
            "total_amount": total_amount,
        }
        data = data_rows

    elif dimensions:
        # Grouped query
        dim = dimensions[0]
        dim_info = DIMENSIONS.get(dim, DIMENSIONS["bank"])

        # Custom dimensions that TradeQueryBuilder._group_cols() doesn't support
        if dim in ("month", "product_type"):
            # f already built above, reuse it
            select_col = dim_info["select_col"]
            group_col = dim_info["group_col"]

            # Build WHERE conditions
            conditions = ["t.TRADESTATUS=0"]
            appid_val = f.get("appid")
            if appid_val is not None:
                if isinstance(appid_val, list):
                    vals = ",".join(str(a) for a in appid_val)
                    conditions.append(f"t.APPID IN ({vals})")
                else:
                    conditions.append(f"t.APPID={appid_val}")
            if date_start:
                conditions.append(f"t.TRADEDATE>={int(date_start.replace('-', ''))}")
            if date_end:
                conditions.append(f"t.TRADEDATE<={int(date_end.replace('-', ''))}")
            if f.get("bank_name"):
                safe_name = TradeQueryBuilder._escape_bank_name(f["bank_name"])
                conditions.append(f"t.BANKID IN (SELECT BANKID FROM XF_BASE_BANK WHERE DIPNAME LIKE '%{safe_name}%' ESCAPE '\\')")
            if f.get("buy_sell"):
                conditions.append(f"t.BUYORSELL='{f['buy_sell']}'")
            if f.get("special_states"):
                raw = f["special_states"]
                if isinstance(raw, str):
                    vals = [s.strip() for s in raw.split(",") if s.strip().isdigit()]
                    if vals:
                        conditions.append(f"t.SPECIALSTATE IN ({','.join(vals)})")

            where_clause = "\n  AND ".join(conditions)

            # Build FROM clause (UNION ALL of views)
            pt = f.get("product_type", "all")
            VIEW_MAP = {"spot": "XF_FX_SPOTTRADE_VIEW", "fwd": "XF_FX_FWDTRADE_VIEW", "swap": "XF_FX_SWAPTRADE_VIEW"}
            COMMON_FIELDS = ["USDAMOUNT", "TRADEDATE", "TRADESTATUS", "SPECIALSTATE", "APPID", "BUYORSELL", "BANKID", "CUSTNAME", "CUSTOMERID", "CUSTMAINMANAGER", "CUSTMANAGERNAME"]

            if dim == "product_type":
                # Need PT column to group by product type
                if pt == "all":
                    subs = []
                    for pt_name, view_name in VIEW_MAP.items():
                        subs.append(f"SELECT {', '.join(COMMON_FIELDS)}, '{pt_name}' as PT FROM {view_name}")
                    from_sql = "(\n    " + "\n    UNION ALL\n    ".join(subs) + "\n) t"
                else:
                    view = VIEW_MAP.get(pt)
                    from_sql = f"(\n    SELECT {', '.join(COMMON_FIELDS)}, '{pt}' as PT FROM {view}\n) t"
            elif pt == "all":
                subs = []
                for view in VIEW_MAP.values():
                    subs.append(f"SELECT {', '.join(COMMON_FIELDS)} FROM {view}")
                from_sql = "(\n    " + "\n    UNION ALL\n    ".join(subs) + "\n) t"
            else:
                view = VIEW_MAP.get(pt)
                from_sql = f"(\n    SELECT {', '.join(COMMON_FIELDS)} FROM {view}\n) t"

            sql = (
                f"SELECT {select_col}, SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT\n"
                f"FROM {from_sql}\n"
                f"WHERE {where_clause}\n"
                f"GROUP BY {group_col}\n"
                f"ORDER BY TOTAL_AMOUNT DESC"
            )

            cols, rows = _execute_sql(sql)
            data = _convert_rows_to_dicts(cols, rows)

            total_amount = sum(float(r[0]) for r in rows if r and r[0] is not None) if rows else 0
            summary = {"total_trading_volume": total_amount}

        elif is_hedge_ratio:
            sql = TradeQueryBuilder.build_hedge_ratio_query(
                product_type=f.get("product_type", "all"),
                dimension=dim,
                date_start=date_start or None,
                date_end=date_end or None,
                buy_sell=f.get("buy_sell"),
                special_states=f.get("special_states"),
                appid=f.get("appid"),
                bank_name=f.get("bank_name"),
                cust_name=f.get("cust_name"),
            )
            cols, rows = _execute_sql(sql)
            data = _convert_rows_to_dicts(cols, rows)
            total_amount = 0
            summary = {}

        else:
            sql = TradeQueryBuilder.build_ranking_query(
                product_type=f.get("product_type", "all"),
                dimension=dim,
                top_n=top_n if top_n and top_n > 0 else 100,
                date_start=date_start or None,
                date_end=date_end or None,
                buy_sell=f.get("buy_sell"),
                special_states=f.get("special_states"),
                appid=f.get("appid"),
                bank_name=f.get("bank_name"),
                cust_name=f.get("cust_name"),
            )
            cols, rows = _execute_sql(sql)
            data = _convert_rows_to_dicts(cols, rows)
            total_amount = sum(
                float(r[0]) for r in rows if r and r[0] is not None
            )
            summary = {"total_trading_volume": total_amount}

    else:
        # Aggregate (single total) query
        sql = TradeQueryBuilder.build_aggregate_query(
            product_type=f.get("product_type", "all"),
            date_start=date_start or None,
            date_end=date_end or None,
            buy_sell=f.get("buy_sell"),
            special_states=f.get("special_states"),
            appid=f.get("appid"),
            bank_name=f.get("bank_name"),
            cust_name=f.get("cust_name"),
        )
        cols, rows = _execute_sql(sql)
        data = _convert_rows_to_dicts(cols, rows)
        total_amount = float(rows[0][0]) if rows and rows[0][0] is not None else 0
        total_count = int(rows[0][1]) if rows and len(rows[0]) > 1 and rows[0][1] is not None else 0
        summary = {"total_trading_volume": total_amount, "total_count": total_count}

    # ---- Comparison ----
    if comparison and date_start and date_end:
        cmp_start, cmp_end = compute_comparison_dates(date_start, date_end, comparison)
        if cmp_start and cmp_end:
            cmp_result = query_metrics(
                metrics=metrics,
                dimensions=dimensions,
                filters=filters,
                date_start=cmp_start,
                date_end=cmp_end,
                comparison="",
                top_n=top_n,
            )
            # Merge comparison data
            prev_total = cmp_result.get("summary", {}).get("total_trading_volume", 0)
            current_total = summary.get("total_trading_volume", 0)
            change = current_total - prev_total
            change_pct = round((change / prev_total) * 100, 2) if prev_total else 0
            summary["prev_total_trading_volume"] = prev_total
            summary["total_change"] = change
            summary["total_change_pct"] = change_pct

            # Per-row comparison (only when dimensions present)
            if dimensions:
                prev_map = {}
                if cmp_result.get("data"):
                    dim_key = DIMENSIONS.get(dimensions[0], {}).get("label", "机构名称")
                    for row in cmp_result["data"]:
                        prev_map[row.get(dim_key, "")] = row

                dim_key = DIMENSIONS.get(dimensions[0], {}).get("label", "机构名称")
                for row in data:
                    key = row.get(dim_key, "")
                    prev_row = prev_map.get(key, {})
                    prev_val = 0
                    if is_hedge_ratio:
                        prev_val = prev_row.get("HEDGE_RATIO", 0)
                    else:
                        prev_val = prev_row.get("TOTAL_AMOUNT", 0) or 0
                    try:
                        prev_val = float(prev_val)
                    except (ValueError, TypeError):
                        prev_val = 0

                    current_val = 0
                    if is_hedge_ratio:
                        current_val = float(row.get("HEDGE_RATIO", 0) or 0)
                    else:
                        current_val = float(row.get("TOTAL_AMOUNT", 0) or 0)

                    row["prev_value"] = prev_val
                    row["change_value"] = current_val - prev_val
                    row["change_pct"] = round((current_val - prev_val) / prev_val * 100, 2) if prev_val else None

    return {
        "metrics": metrics,
        "dimensions": dimensions or [],
        "date_range": [date_start or "", date_end or ""],
        "comparison": comparison,
        "data": data,
        "summary": summary,
    }


def decompose_change(
    metric: str,
    date_start: str,
    date_end: str,
    comparison: str,
    by_dimension: str,
    top_n: int = 5,
    filters: dict | None = None,
) -> dict:
    """Change attribution analysis.

    Decomposes total change into per-dimension-member contributions.

    Returns:
        dict with drivers array, each item has contrib_pct calculated by API.
    """
    if comparison not in ("yoy", "mom"):
        raise ValueError(f"comparison must be 'yoy' or 'mom', got '{comparison}'")

    cmp_start, cmp_end = compute_comparison_dates(date_start, date_end, comparison)

    # Current period data
    current = query_metrics(
        metrics=[metric],
        dimensions=[by_dimension],
        filters=filters,
        date_start=date_start,
        date_end=date_end,
        top_n=top_n,
    )

    # Previous period data
    previous = query_metrics(
        metrics=[metric],
        dimensions=[by_dimension],
        filters=filters,
        date_start=cmp_start,
        date_end=cmp_end,
        top_n=top_n,
    )

    # Build change drivers
    total_current = current.get("summary", {}).get("total_trading_volume", 0)
    total_previous = previous.get("summary", {}).get("total_trading_volume", 0)
    total_change = total_current - total_previous
    total_change_pct = round((total_change / total_previous) * 100, 2) if total_previous else 0

    # Build per-driver map
    prev_map = {}
    dim_label = DIMENSIONS.get(by_dimension, {}).get("label", "机构名称")
    for row in previous.get("data", []):
        key = row.get(dim_label, "")
        prev_map[key] = row

    drivers = []
    for row in current.get("data", []):
        key = row.get(dim_label, "")
        previous_row = prev_map.get(key, {})
        current_value = float(row.get("TOTAL_AMOUNT", 0) or 0)
        previous_value = float(previous_row.get("TOTAL_AMOUNT", 0) or 0) if previous_row else 0
        change_value = current_value - previous_value
        contrib_pct = round((change_value / total_change) * 100, 2) if total_change else 0

        drivers.append({
            "dimension_value": key,
            "current_value": current_value,
            "previous_value": previous_value,
            "change_value": change_value,
            "contrib_pct": contrib_pct,
        })

    # Sort by absolute contribution descending, limit top_n
    drivers.sort(key=lambda x: abs(x["contrib_pct"]), reverse=True)
    drivers = drivers[:top_n]

    return {
        "metric": metric,
        "date_range": [date_start, date_end],
        "comparison": comparison,
        "comparison_date_range": [cmp_start or "", cmp_end or ""],
        "by_dimension": by_dimension,
        "total_current": total_current,
        "total_previous": total_previous,
        "total_change": total_change,
        "total_change_pct": total_change_pct,
        "drivers": drivers,
    }


# OpenAI-compatible tool definitions for LLM tool calling
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_metrics",
            "description": "查询指定的业务指标数据，支持按维度分组、按时间范围过滤、同比/环比对比、取 Top N。"
                           "可用于查询交易量、套保率等指标。如果用户问的是汇总数据（如\"总交易量多少\"），"
                           "应查询带\"yoy\"或\"mom\"对比的版本以获得变化率。",
            "parameters": {
                "type": "object",
                "properties": {
                    "metrics": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(METRICS.keys())},
                        "description": "要查询的指标列表",
                    },
                    "dimensions": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(DIMENSIONS.keys())},
                        "description": "分组维度（不传则返回汇总）",
                    },
                    "filters": {
                        "type": "object",
                        "description": "过滤条件，可选字段：product_type, bank_name, cust_name, buy_sell, special_states, appid",
                    },
                    "date_start": {
                        "type": "string",
                        "description": "开始日期 YYYY-MM-DD",
                    },
                    "date_end": {
                        "type": "string",
                        "description": "结束日期 YYYY-MM-DD",
                    },
                    "comparison": {
                        "type": "string",
                        "enum": ["yoy", "mom", ""],
                        "description": "对比模式：yoy=同比, mom=环比",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回前 N 条（默认不限）",
                    },
                },
                "required": ["metrics"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decompose_change",
            "description": "分析指标变化的原因，按指定维度拆解各成员的贡献度。"
                           "例如：交易量同比增加了1000万，各机构分别贡献了多少。"
                           "contrib_pct 表示该成员对总变化的贡献百分比。",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": list(METRICS.keys()),
                        "description": "要分析的指标",
                    },
                    "date_start": {
                        "type": "string",
                        "description": "当前期开始日期 YYYY-MM-DD",
                    },
                    "date_end": {
                        "type": "string",
                        "description": "当前期结束日期 YYYY-MM-DD",
                    },
                    "comparison": {
                        "type": "string",
                        "enum": ["yoy", "mom"],
                        "description": "对比模式：yoy=同比, mom=环比",
                    },
                    "by_dimension": {
                        "type": "string",
                        "enum": list(DIMENSIONS.keys()),
                        "description": "按哪个维度拆解变化",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回贡献度最大的前 N 个（默认5）",
                    },
                    "filters": {
                        "type": "object",
                        "description": "过滤条件",
                    },
                },
                "required": ["metric", "date_start", "date_end", "comparison", "by_dimension"],
            },
        },
    },
]
