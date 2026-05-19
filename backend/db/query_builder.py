import re


class TradeQueryBuilder:
    _dimension_config: dict | None = None

    @classmethod
    def configure_dimensions(cls, config: dict | None) -> None:
        """Set dimension configuration from the rule engine (injected by app.py)."""
        cls._dimension_config = config
    VIEW_MAP = {
        "spot": "XF_FX_SPOTTRADE_VIEW",
        "fwd": "XF_FX_FWDTRADE_VIEW",
        "swap": "XF_FX_SWAPTRADE_VIEW",
    }

    COMMON_FIELDS = ["USDAMOUNT", "TRADEDATE", "TRADESTATUS", "SPECIALSTATE", "APPID", "BUYORSELL", "BANKID", "CUSTNAME", "CUSTOMERID", "CUSTMAINMANAGER", "CUSTMANAGERNAME", "DOWNLOADKEY", "DOWNLOADKEYINT"]

    @staticmethod
    def _validate_buy_sell(buy_sell):
        if buy_sell is not None and buy_sell not in ("B", "S"):
            raise ValueError(f"Invalid buy_sell: {buy_sell!r}, expected 'B' or 'S'")

    @staticmethod
    def _validate_top_n(top_n):
        if top_n is not None and not (1 <= top_n <= 100):
            raise ValueError(f"top_n must be between 1 and 100, got {top_n}")

    @staticmethod
    def _validate_product_type(product_type):
        if product_type != "all" and product_type not in TradeQueryBuilder.VIEW_MAP:
            raise ValueError(f"Unknown product_type: {product_type!r}")

    @staticmethod
    def _appid_filter(appid):
        if appid is None:
            return "t.APPID IN (1,2)"
        if isinstance(appid, list):
            vals = ",".join(str(int(a)) for a in appid)
            return f"t.APPID IN ({vals})"
        return f"t.APPID={int(appid)}"

    HEDGE_RATIO_SQL = (
        "ROUND(SUM(CASE WHEN t.PT IN ('fwd','swap') THEN t.USDAMOUNT ELSE 0 END) "
        "/ NULLIF(SUM(t.USDAMOUNT), 0) * 100, 2)"
    )

    # ---- shared helpers ----

    _BANK_NAME_RE = re.compile(r'^[一-龯\w\s()（）\-]+$')
    _CUST_NAME_RE = re.compile(r'^[一-龯\w\s()（）.]+$')

    @staticmethod
    def _validate_name(value):
        if value and not TradeQueryBuilder._BANK_NAME_RE.fullmatch(value):
            raise ValueError(f"Invalid name input: {value!r}")

    @classmethod
    def _escape_bank_name(cls, bank_name):
        return bank_name.replace("\\", "\\\\").replace("'", "''").replace("%", "\\%").replace("_", "\\_")

    @classmethod
    def _build_cte(cls, bank_name):
        """Build CTE for bank name fuzzy search. Returns (cte_sql, extra_condition)."""
        if bank_name:
            cls._validate_name(bank_name)
            safe_name = cls._escape_bank_name(bank_name)
            cte = (
                f"WITH matched_banks AS (\n"
                f"    SELECT BANKID FROM XF_BASE_BANK WHERE DIPNAME LIKE '%{safe_name}%' ESCAPE '\\'\n"
                f")\n"
            )
            return cte, "t.BANKID IN (SELECT BANKID FROM matched_banks)"
        return "", None

    @classmethod
    def _build_where_conditions(cls, date_start, date_end, buy_sell, special_states, appid,
                                 bank_condition=None, cust_name=None, hedge_ratio_default=False):
        """Build list of WHERE conditions shared by all query methods.

        special_states: list of state values or None.
        cust_name: exact customer name for CUSTNAME = 'xxx' filter, or None.
        hedge_ratio_default: if True and special_states is None, add t.SPECIALSTATE=0.
        """
        conditions = ["t.TRADESTATUS=0", cls._appid_filter(appid)]

        if date_start is not None:
            conditions.append(f"t.TRADEDATE>={int(date_start.replace('-', ''))}")

        if date_end is not None:
            conditions.append(f"t.TRADEDATE<={int(date_end.replace('-', ''))}")

        if buy_sell is not None:
            conditions.append(f"t.BUYORSELL='{buy_sell}'")

        if cust_name:
            cls._validate_name(cust_name)
            safe_cust = cust_name.replace("'", "''")
            conditions.append(f"t.CUSTNAME='{safe_cust}'")

        if special_states is not None and str(special_states).strip():
            if isinstance(special_states, str):
                vals = ",".join(str(int(s.strip())) for s in special_states.split(",") if s.strip())
            else:
                vals = ",".join(str(int(s)) for s in special_states)
            conditions.append(f"t.SPECIALSTATE IN ({vals})")
        elif hedge_ratio_default:
            conditions.append("t.SPECIALSTATE=0")

        if bank_condition:
            conditions.append(bank_condition)

        return conditions

    @classmethod
    def _build_from(cls, product_type, with_pt=False, with_maturity=False):
        """Build FROM sub-query (UNION ALL of views).

        with_maturity: add MATURITYDATE column (spot uses VALUEDATE as fallback).
        """
        if product_type == "all":
            subqueries = []
            for pt, view in cls.VIEW_MAP.items():
                extras = []
                if with_pt:
                    extras.append(f"'{pt}' as PT")
                if with_maturity:
                    maturity_col = "VALUEDATE" if pt == "spot" else "MATURITYDATE"
                    extras.append(f"{maturity_col} as MATURITYDATE")
                cols = ", ".join(cls.COMMON_FIELDS + extras) if extras else ", ".join(cls.COMMON_FIELDS)
                subqueries.append(f"SELECT {cols} FROM {view}")
            return "(\n    " + "\n    UNION ALL\n    ".join(subqueries) + "\n) t"
        else:
            view = cls.VIEW_MAP[product_type]
            extras = []
            if with_pt:
                extras.append(f"'{product_type}' as PT")
            if with_maturity:
                maturity_col = "VALUEDATE" if product_type == "spot" else "MATURITYDATE"
                extras.append(f"{maturity_col} as MATURITYDATE")
            cols = ", ".join(cls.COMMON_FIELDS + extras) if extras else ", ".join(cls.COMMON_FIELDS)
            return f"(\n    SELECT {cols} FROM {view}\n) t"

    # ---- query builders ----

    @classmethod
    def build_query(cls, product_type="all", date_start=None, date_end=None,
                    special_states=None, buy_sell=None, bank_name=None,
                    cust_name=None, appid=None, lifecycle_status=None):
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(date_start, date_end, buy_sell, special_states, appid, bank_cond, cust_name=cust_name)
        with_maturity = lifecycle_status is not None
        from_sql = cls._build_from(product_type, with_pt=with_maturity, with_maturity=with_maturity)

        extra_joins = []
        if bank_name or (cls._dimension_config and cls._dimension_config.get("bank", {}).get("join_clause")):
            extra_joins.append("LEFT JOIN XF_BASE_BANK b ON t.BANKID = b.BANKID")

        if lifecycle_status:
            lc_join, lc_conds = cls._lifecycle_join_and_conditions(lifecycle_status, product_type)
            extra_joins.append(lc_join)
            conditions.extend(lc_conds)

        where_clause = "\n  AND ".join(conditions)
        joins_sql = "\n".join(extra_joins)

        sql = (
            f"{cte}"
            f"SELECT t.{', t.'.join(cls.COMMON_FIELDS)}, b.DIPNAME\n"
            f"FROM {from_sql}\n"
            f"{joins_sql}\n"
            f"WHERE {where_clause}"
        )
        return sql

    @classmethod
    def _join_clause(cls, dimension, bank_name):
        """LEFT JOIN XF_BASE_BANK, only needed for bank dimension queries.

        Uses dimension_config from rules when available, falls back to hardcoded logic.
        """
        if cls._dimension_config:
            dim = cls._dimension_config.get(dimension)
            if dim and dim.get("join_clause"):
                return dim["join_clause"]
            if bank_name:
                bank_dim = cls._dimension_config.get("bank")
                if bank_dim and bank_dim.get("join_clause"):
                    return bank_dim["join_clause"]
        if dimension == "bank" or bank_name:
            return "LEFT JOIN XF_BASE_BANK b ON t.BANKID = b.BANKID"
        return ""

    @classmethod
    def build_aggregate_query(cls, product_type="all", date_start=None, date_end=None,
                               special_states=None, buy_sell=None, bank_name=None,
                               cust_name=None, appid=None, dimension=None, lifecycle_status=None):
        """Build an aggregate SQL that returns SUM and COUNT.

        When dimension is provided, groups by that dimension (e.g. 客户经理名称).
        Otherwise returns a single total row.
        """
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(date_start, date_end, buy_sell, special_states, appid, bank_cond, cust_name=cust_name)
        needs_pt = dimension == "product_type" or lifecycle_status is not None
        with_maturity = lifecycle_status is not None
        from_sql = cls._build_from(product_type, with_pt=needs_pt, with_maturity=with_maturity)
        join = cls._join_clause(dimension, bank_name)

        if lifecycle_status:
            lc_join, lc_conds = cls._lifecycle_join_and_conditions(lifecycle_status, product_type)
            if lc_join:
                join = join + "\n" + lc_join if join else lc_join
            conditions.extend(lc_conds)

        where_clause = "\n  AND ".join(conditions)

        if dimension:
            select_col, group_col = cls._group_cols(dimension)
            sql = (
                f"{cte}"
                f"SELECT {select_col}, SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT\n"
                f"FROM {from_sql}\n"
                f"{join}\n"
                f"WHERE {where_clause}\n"
                f"GROUP BY {group_col}\n"
                f"ORDER BY TOTAL_AMOUNT DESC"
            )
        else:
            sql = (
                f"{cte}"
                f"SELECT SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT\n"
                f"FROM {from_sql}\n"
                f"{join}\n"
                f"WHERE {where_clause}"
            )
        return sql

    @classmethod
    def build_hedge_ratio_query(cls, product_type="all", date_start=None, date_end=None,
                                 special_states=None, buy_sell=None, bank_name=None,
                                 dimension="bank", cust_name=None, appid=None,
                                 lifecycle_status=None):
        """Build a grouped SQL that returns hedge ratio by dimension."""
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(date_start, date_end, buy_sell, special_states, appid, bank_cond,
                                                  cust_name=cust_name, hedge_ratio_default=True)
        where_clause = "\n  AND ".join(conditions)
        from_sql = cls._build_from(product_type, with_pt=True,
                                    with_maturity=lifecycle_status is not None)
        select_col, group_col = cls._group_cols(dimension)
        join = cls._join_clause(dimension, bank_name)

        extra_joins = []
        if join:
            extra_joins.append(join)
        if lifecycle_status:
            lc_join, lc_conds = cls._lifecycle_join_and_conditions(lifecycle_status, product_type)
            if lc_join:
                extra_joins.append(lc_join)
            if lc_conds:
                where_clause += "\n  AND " + "\n  AND ".join(lc_conds)

        join_sql = "\n".join(extra_joins) if extra_joins else ""

        sql = (
            f"{cte}"
            f"SELECT {select_col}, {cls.HEDGE_RATIO_SQL} as HEDGE_RATIO,\n"
            f"       SUM(CASE WHEN t.PT IN ('fwd','swap') THEN t.USDAMOUNT ELSE 0 END) as DERIVATIVE_AMOUNT,\n"
            f"       SUM(CASE WHEN t.PT IN ('fwd','swap') THEN 1 ELSE 0 END) as DERIVATIVE_COUNT,\n"
            f"       SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT\n"
            f"FROM {from_sql}\n"
            f"{join_sql}\n"
            f"WHERE {where_clause}\n"
            f"GROUP BY {group_col}\n"
            f"ORDER BY HEDGE_RATIO DESC"
        )
        return sql

    @classmethod
    def _group_cols(cls, dimension):
        """Return (select_col, group_col) based on dimension.

        Uses dimension_config from rules when available, falls back to hardcoded defaults.
        """
        if cls._dimension_config:
            dim = cls._dimension_config.get(dimension)
            if dim and dim.get("sql_select_col") and dim.get("sql_group_col"):
                return (dim["sql_select_col"], dim["sql_group_col"])
        mapping = {
            "bank": ("b.DIPNAME as 机构名称", "b.DIPNAME"),
            "customer": ("t.CUSTNAME as 客户名称", "t.CUSTNAME"),
            "customer_id": ("t.CUSTOMERID as 客户号", "t.CUSTOMERID"),
            "manager": ("t.CUSTMAINMANAGER as 客户经理ID", "t.CUSTMAINMANAGER"),
            "manager_name": ("t.CUSTMANAGERNAME as 客户经理名称", "t.CUSTMANAGERNAME"),
            "month": ("TO_CHAR(t.TRADEDATE, 'YYYY-MM') as 月份", "TO_CHAR(t.TRADEDATE, 'YYYY-MM')"),
            "product_type": ("t.PT as 产品类型", "t.PT"),
        }
        return mapping.get(dimension, mapping["bank"])

    @classmethod
    def build_ranking_query(cls, product_type="all", date_start=None, date_end=None,
                             special_states=None, buy_sell=None, bank_name=None, top_n=10,
                             dimension="bank", hedge_ratio=False, cust_name=None, appid=None,
                             lifecycle_status=None):
        """Build a ranking SQL grouped by institution, ordered by SUM(USDAMOUNT) DESC, limited by top_n.
        When hedge_ratio=True, orders by HEDGE_RATIO DESC instead."""
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)
        cls._validate_top_n(top_n)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(date_start, date_end, buy_sell, special_states, appid, bank_cond,
                                                  cust_name=cust_name, hedge_ratio_default=hedge_ratio)
        from_sql = cls._build_from(product_type, with_pt=hedge_ratio or lifecycle_status is not None,
                                    with_maturity=lifecycle_status is not None)
        join = cls._join_clause(dimension, bank_name)

        if lifecycle_status:
            lc_join, lc_conds = cls._lifecycle_join_and_conditions(lifecycle_status, product_type)
            if lc_join:
                join = join + "\n" + lc_join if join else lc_join
            conditions.extend(lc_conds)

        where_clause = "\n  AND ".join(conditions)
        select_col, group_col = cls._group_cols(dimension)

        if hedge_ratio:
            inner_select = (
                f"SELECT {select_col}, {cls.HEDGE_RATIO_SQL} as HEDGE_RATIO,\n"
                f"       SUM(CASE WHEN t.PT IN ('fwd','swap') THEN t.USDAMOUNT ELSE 0 END) as DERIVATIVE_AMOUNT,\n"
                f"       SUM(CASE WHEN t.PT IN ('fwd','swap') THEN 1 ELSE 0 END) as DERIVATIVE_COUNT,\n"
                f"       SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT"
            )
            order_by = "HEDGE_RATIO DESC"
        else:
            inner_select = (
                f"SELECT {select_col}, SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT"
            )
            order_by = "SUM(t.USDAMOUNT) DESC"

        sql = (
            f"{cte}"
            f"SELECT * FROM (\n"
            f"  {inner_select}\n"
            f"  FROM {from_sql}\n"
            f"  {join}\n"
            f"  WHERE {where_clause}\n"
            f"  GROUP BY {group_col}\n"
            f"  ORDER BY {order_by}\n"
            f") WHERE ROWNUM <= {top_n}"
        )
        return sql

    OP_MAP = {
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
    }

    @classmethod
    def build_filtered_query(cls, product_type="all", date_start=None, date_end=None,
                              special_states=None, buy_sell=None, bank_name=None,
                              amount_op=None, amount_value=None,
                              dimension="bank", hedge_ratio=False, cust_name=None, appid=None,
                              lifecycle_status=None):
        """Build a grouped SQL with HAVING filter on SUM(USDAMOUNT).

        amount_op mapping: "gt"→">", "gte"→">=", "lt"→"<", "lte"→"<=".
        amount_value is the raw USD value for the HAVING comparison.
        When hedge_ratio=True, amount_value is a percentage and HAVING uses the hedge ratio formula.
        """
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(date_start, date_end, buy_sell, special_states, appid, bank_cond,
                                                  cust_name=cust_name, hedge_ratio_default=hedge_ratio)
        from_sql = cls._build_from(product_type, with_pt=hedge_ratio or lifecycle_status is not None,
                                    with_maturity=lifecycle_status is not None)
        join = cls._join_clause(dimension, bank_name)

        if lifecycle_status:
            lc_join, lc_conds = cls._lifecycle_join_and_conditions(lifecycle_status, product_type)
            if lc_join:
                join = join + "\n" + lc_join if join else lc_join
            conditions.extend(lc_conds)

        where_clause = "\n  AND ".join(conditions)

        # --- HAVING clause ---
        having_clause = ""
        if amount_op is not None and amount_value is not None:
            op = cls.OP_MAP.get(amount_op)
            if op is None:
                raise ValueError(f"Unknown amount_op: {amount_op}")
            if hedge_ratio:
                having_clause = f"HAVING {cls.HEDGE_RATIO_SQL} {op} {amount_value}"
            else:
                having_clause = f"HAVING SUM(t.USDAMOUNT) {op} {amount_value}"

        select_col, group_col = cls._group_cols(dimension)

        if hedge_ratio:
            inner_select = (
                f"SELECT {select_col}, {cls.HEDGE_RATIO_SQL} as HEDGE_RATIO,\n"
                f"       SUM(CASE WHEN t.PT IN ('fwd','swap') THEN t.USDAMOUNT ELSE 0 END) as DERIVATIVE_AMOUNT,\n"
                f"       SUM(CASE WHEN t.PT IN ('fwd','swap') THEN 1 ELSE 0 END) as DERIVATIVE_COUNT,\n"
                f"       SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT"
            )
            order_by = "HEDGE_RATIO DESC"
        else:
            inner_select = (
                f"SELECT {select_col}, SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT"
            )
            order_by = "TOTAL_AMOUNT DESC"

        sql = (
            f"{cte}"
            f"{inner_select}\n"
            f"FROM {from_sql}\n"
            f"{join}\n"
            f"WHERE {where_clause}\n"
            f"GROUP BY {group_col}\n"
            f"{having_clause}\n"
            f"ORDER BY {order_by}"
        )
        return sql

    # ---- Lifecycle status helpers ----

    LIFECYCLE_STATUS_OPTIONS = {"not_due", "overdue", "due_today", "unclosed", "closed"}

    @classmethod
    def _lifecycle_join_and_conditions(cls, lifecycle_status, product_type):
        """Return (join_sql, extra_conditions) for lifecycle status filtering.

        Join: LEFT JOIN XF_FX_TOTALDELIVERY d ON t.DOWNLOADKEY = d.DOWNLOADKEY
        Conditions vary by lifecycle_status and product_type (spot/fwd vs swap).
        """
        join = "LEFT JOIN XF_FX_TOTALDELIVERY d ON t.DOWNLOADKEY = d.DOWNLOADKEY"
        conditions = []

        # Delivery amount columns differ by product type
        if product_type == "swap":
            nd1, nd2 = "d.NOFARDELIVERYAMOUNT1", "d.NOFARDELIVERYAMOUNT2"
        else:
            nd1, nd2 = "d.NODELIVERYAMOUNT1", "d.NODELIVERYAMOUNT2"

        if lifecycle_status == "not_due":
            # Has undelivered amounts (OR) AND maturity > sysdate
            if product_type == "all":
                conditions.append(
                    f"(CASE WHEN t.PT = 'swap' THEN d.NOFARDELIVERYAMOUNT1 ELSE d.NODELIVERYAMOUNT1 END > 0"
                    f" OR CASE WHEN t.PT = 'swap' THEN d.NOFARDELIVERYAMOUNT2 ELSE d.NODELIVERYAMOUNT2 END > 0)"
                )
            else:
                conditions.append(f"({nd1} > 0 OR {nd2} > 0)")
            conditions.append("t.MATURITYDATE > TO_NUMBER(TO_CHAR(SYSDATE, 'YYYYMMDD'))")

        elif lifecycle_status == "overdue":
            if product_type == "all":
                conditions.append(
                    f"(CASE WHEN t.PT = 'swap' THEN d.NOFARDELIVERYAMOUNT1 ELSE d.NODELIVERYAMOUNT1 END > 0"
                    f" OR CASE WHEN t.PT = 'swap' THEN d.NOFARDELIVERYAMOUNT2 ELSE d.NODELIVERYAMOUNT2 END > 0)"
                )
            else:
                conditions.append(f"({nd1} > 0 OR {nd2} > 0)")
            conditions.append("t.MATURITYDATE < TO_NUMBER(TO_CHAR(SYSDATE, 'YYYYMMDD'))")

        elif lifecycle_status == "due_today":
            if product_type == "all":
                conditions.append(
                    f"(CASE WHEN t.PT = 'swap' THEN d.NOFARDELIVERYAMOUNT1 ELSE d.NODELIVERYAMOUNT1 END > 0"
                    f" OR CASE WHEN t.PT = 'swap' THEN d.NOFARDELIVERYAMOUNT2 ELSE d.NODELIVERYAMOUNT2 END > 0)"
                )
            else:
                conditions.append(f"({nd1} > 0 OR {nd2} > 0)")
            conditions.append("t.MATURITYDATE = TO_NUMBER(TO_CHAR(SYSDATE, 'YYYYMMDD'))")

        elif lifecycle_status == "unclosed":
            # unclosed = not_due OR overdue OR due_today (has undelivered amounts)
            if product_type == "all":
                conditions.append(
                    f"(CASE WHEN t.PT = 'swap' THEN d.NOFARDELIVERYAMOUNT1 ELSE d.NODELIVERYAMOUNT1 END > 0"
                    f" OR CASE WHEN t.PT = 'swap' THEN d.NOFARDELIVERYAMOUNT2 ELSE d.NODELIVERYAMOUNT2 END > 0)"
                )
            else:
                conditions.append(f"({nd1} > 0 OR {nd2} > 0)")

        elif lifecycle_status == "closed":
            if product_type == "all":
                conditions.append(
                    f"CASE WHEN t.PT = 'swap' THEN d.NOFARDELIVERYAMOUNT1 ELSE d.NODELIVERYAMOUNT1 END = 0"
                )
                conditions.append(
                    f"CASE WHEN t.PT = 'swap' THEN d.NOFARDELIVERYAMOUNT2 ELSE d.NODELIVERYAMOUNT2 END = 0"
                )
            else:
                conditions.append(f"{nd1} = 0")
                conditions.append(f"{nd2} = 0")

        return join, conditions

    # ---- Profit query helpers ----

    PROFIT_METRICS = {
        "branch_profit_usd": {
            "profit_state": 0, "group_type": 0, "profitcycode": "USD",
            "join_key": "DOWNLOADKEYINT", "alias": "BRANCH_PROFIT_USD",
            "label": "分行利润(美元)",
        },
        "branch_profit_cny": {
            "profit_state": 0, "group_type": 0, "profitcycode": "CNY",
            "join_key": "DOWNLOADKEYINT", "alias": "BRANCH_PROFIT_CNY",
            "label": "分行利润(人民币)",
        },
        "customer_profit_usd": {
            "profit_state": 2, "group_type": 0, "profitcycode": "USD",
            "join_key": "DOWNLOADKEY", "alias": "CUSTOMER_PROFIT_USD",
            "label": "客户损益(美元)",
        },
        "customer_profit_cny": {
            "profit_state": 2, "group_type": 0, "profitcycode": "CNY",
            "join_key": "DOWNLOADKEY", "alias": "CUSTOMER_PROFIT_CNY",
            "label": "客户损益(人民币)",
        },
    }

    @classmethod
    def _build_profit_join(cls, profit_type: list[str],
                           date_start: str | None = None,
                           date_end: str | None = None) -> tuple[str, list[str]]:
        """Build JOIN clause and CASE expressions for profit metrics.

        Returns (join_sql, case_exprs).
        """
        has_branch = any(k.startswith("branch_") for k in profit_type)
        has_customer = any(k.startswith("customer_") for k in profit_type)

        if has_branch and has_customer:
            join_on = "(p.DOWNLOADKEY = t.DOWNLOADKEYINT OR p.DOWNLOADKEY = t.DOWNLOADKEY)"
        elif has_branch:
            join_on = "p.DOWNLOADKEY = t.DOWNLOADKEYINT"
        else:
            join_on = "p.DOWNLOADKEY = t.DOWNLOADKEY"

        join = f"LEFT JOIN XF_FX_PROFIT p ON {join_on}"

        case_exprs = []
        for metric_key in profit_type:
            m = cls.PROFIT_METRICS[metric_key]
            conditions = [
                f"p.PROFITSTATE={m['profit_state']}",
                f"p.GROUPTYPE={m['group_type']}",
                f"p.PROFITCYCODE='{m['profitcycode']}'",
                "p.TRADESTATUS=0",
                "p.APPID IN (1,2)",
            ]
            if date_start is not None:
                conditions.append(f"p.TRADEDATE>={int(date_start.replace('-', ''))}")
            if date_end is not None:
                conditions.append(f"p.TRADEDATE<={int(date_end.replace('-', ''))}")
            cond_sql = " AND ".join(conditions)
            case_exprs.append(
                f"SUM(CASE WHEN {cond_sql} "
                f"THEN p.PROFITAMT ELSE 0 END) as {m['alias']}"
            )

        return join, case_exprs

    @classmethod
    def build_profit_query(cls, profit_type: list[str], product_type: str = "all",
                           date_start: str | None = None, date_end: str | None = None,
                           special_states=None, buy_sell: str | None = None,
                           bank_name: str | None = None, cust_name: str | None = None,
                           appid=None, dimension: str | None = None,
                           top_n: int | None = None, amount_op: str | None = None,
                           amount_value: float | None = None) -> str:
        """Build a profit-only query joining trade views to XF_FX_PROFIT."""
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(
            date_start, date_end, buy_sell, special_states, appid, bank_cond, cust_name=cust_name,
        )

        from_sql = cls._build_from(product_type, with_pt=True, with_maturity=False)
        profit_join, case_exprs = cls._build_profit_join(profit_type, date_start, date_end)
        join = cls._join_clause(dimension, bank_name)

        extra_joins = []
        if join:
            extra_joins.append(join)
        extra_joins.append(profit_join)

        where_clause = "\n  AND ".join(conditions)
        joins_sql = "\n".join(extra_joins)
        profit_select = ",\n       ".join(case_exprs)

        if dimension:
            select_col, group_col = cls._group_cols(dimension)
            primary_alias = cls.PROFIT_METRICS[profit_type[0]]["alias"]
            order_by = f"{primary_alias} DESC"

            inner_sql = (
                f"{cte}"
                f"SELECT {select_col}, {profit_select}\n"
                f"FROM {from_sql}\n"
                f"{joins_sql}\n"
                f"WHERE {where_clause}\n"
                f"GROUP BY {group_col}\n"
                f"ORDER BY {order_by}"
            )
        else:
            inner_sql = (
                f"{cte}"
                f"SELECT {profit_select}\n"
                f"FROM {from_sql}\n"
                f"{joins_sql}\n"
                f"WHERE {where_clause}"
            )

        # HAVING filter for amount
        having_clause = ""
        if amount_op is not None and amount_value is not None and dimension:
            op = cls.OP_MAP.get(amount_op, ">")
            primary_alias = cls.PROFIT_METRICS[profit_type[0]]["alias"]
            having_clause = f"\nHAVING {primary_alias} {op} {amount_value}"

        if top_n and top_n > 0 and dimension:
            return f"SELECT * FROM (\n  {inner_sql}\n{having_clause}) WHERE ROWNUM <= {top_n}"

        if having_clause:
            return inner_sql + having_clause
        return inner_sql

    @classmethod
    def build_profit_volume_query(cls, profit_type: list[str], product_type: str = "all",
                                  date_start: str | None = None, date_end: str | None = None,
                                  special_states=None, buy_sell: str | None = None,
                                  bank_name: str | None = None, cust_name: str | None = None,
                                  appid=None, dimension: str | None = None,
                                  top_n: int | None = None, hedge_ratio: bool = False,
                                  amount_op: str | None = None,
                                  amount_value: float | None = None) -> str:
        """Build a combined profit + volume query."""
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(
            date_start, date_end, buy_sell, special_states, appid, bank_cond,
            cust_name=cust_name, hedge_ratio_default=hedge_ratio,
        )

        from_sql = cls._build_from(product_type, with_pt=True, with_maturity=False)
        profit_join, case_exprs = cls._build_profit_join(profit_type, date_start, date_end)
        join = cls._join_clause(dimension, bank_name)

        extra_joins = []
        if join:
            extra_joins.append(join)
        extra_joins.append(profit_join)

        where_clause = "\n  AND ".join(conditions)
        joins_sql = "\n".join(extra_joins)

        select_parts = list(case_exprs)
        select_parts.append("SUM(t.USDAMOUNT) as TOTAL_AMOUNT")
        select_parts.append("COUNT(*) as TRADE_COUNT")

        if hedge_ratio:
            select_parts.append(f"{cls.HEDGE_RATIO_SQL} as HEDGE_RATIO")
            select_parts.append(
                "SUM(CASE WHEN t.PT IN ('fwd','swap') THEN t.USDAMOUNT ELSE 0 END) as DERIVATIVE_AMOUNT"
            )
            select_parts.append(
                "SUM(CASE WHEN t.PT IN ('fwd','swap') THEN 1 ELSE 0 END) as DERIVATIVE_COUNT"
            )

        select_sql = ",\n       ".join(select_parts)

        if dimension:
            select_col, group_col = cls._group_cols(dimension)
            primary_alias = cls.PROFIT_METRICS[profit_type[0]]["alias"]
            order_by = f"{primary_alias} DESC" if not hedge_ratio else "HEDGE_RATIO DESC"

            inner_sql = (
                f"{cte}"
                f"SELECT {select_col}, {select_sql}\n"
                f"FROM {from_sql}\n"
                f"{joins_sql}\n"
                f"WHERE {where_clause}\n"
                f"GROUP BY {group_col}\n"
                f"ORDER BY {order_by}"
            )
        else:
            inner_sql = (
                f"{cte}"
                f"SELECT {select_sql}\n"
                f"FROM {from_sql}\n"
                f"{joins_sql}\n"
                f"WHERE {where_clause}"
            )

        # HAVING filter
        having_clause = ""
        if amount_op is not None and amount_value is not None and dimension:
            op = cls.OP_MAP.get(amount_op, ">")
            primary_alias = cls.PROFIT_METRICS[profit_type[0]]["alias"]
            having_clause = f"\nHAVING {primary_alias} {op} {amount_value}"

        if top_n and top_n > 0 and dimension:
            return f"SELECT * FROM (\n  {inner_sql}\n{having_clause}) WHERE ROWNUM <= {top_n}"

        if having_clause:
            return inner_sql + having_clause
        return inner_sql
