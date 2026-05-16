import re


class TradeQueryBuilder:
    VIEW_MAP = {
        "spot": "XF_FX_SPOTTRADE_VIEW",
        "fwd": "XF_FX_FWDTRADE_VIEW",
        "swap": "XF_FX_SWAPTRADE_VIEW",
    }

    COMMON_FIELDS = ["USDAMOUNT", "TRADEDATE", "TRADESTATUS", "SPECIALSTATE", "APPID", "BUYORSELL", "BANKID", "CUSTNAME", "CUSTOMERID", "CUSTMAINMANAGER", "CUSTMANAGERNAME"]

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
        if appid is not None:
            return f"t.APPID={appid}"
        return "t.APPID IN (1,2)"

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

        if special_states is not None and len(special_states) > 0:
            vals = ",".join(str(s) for s in special_states)
            conditions.append(f"t.SPECIALSTATE IN ({vals})")
        elif hedge_ratio_default:
            conditions.append("t.SPECIALSTATE=0")

        if bank_condition:
            conditions.append(bank_condition)

        return conditions

    @classmethod
    def _build_from(cls, product_type, with_pt=False):
        """Build FROM sub-query (UNION ALL of views)."""
        if product_type == "all":
            subqueries = []
            if with_pt:
                for pt, view in cls.VIEW_MAP.items():
                    subqueries.append(
                        f"SELECT {', '.join(cls.COMMON_FIELDS)}, '{pt}' as PT FROM {view}"
                    )
            else:
                for view in cls.VIEW_MAP.values():
                    subqueries.append(f"SELECT {', '.join(cls.COMMON_FIELDS)} FROM {view}")
            return "(\n    " + "\n    UNION ALL\n    ".join(subqueries) + "\n) t"
        else:
            view = cls.VIEW_MAP[product_type]
            if with_pt:
                return f"(\n    SELECT {', '.join(cls.COMMON_FIELDS)}, '{product_type}' as PT FROM {view}\n) t"
            else:
                return f"(\n    SELECT {', '.join(cls.COMMON_FIELDS)} FROM {view}\n) t"

    # ---- query builders ----

    @classmethod
    def build_query(cls, product_type="all", date_start=None, date_end=None,
                    special_states=None, buy_sell=None, bank_name=None,
                    cust_name=None, appid=None):
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(date_start, date_end, buy_sell, special_states, appid, bank_cond, cust_name=cust_name)
        where_clause = "\n  AND ".join(conditions)
        from_sql = cls._build_from(product_type)

        sql = (
            f"{cte}"
            f"SELECT t.{', t.'.join(cls.COMMON_FIELDS)}, b.DIPNAME\n"
            f"FROM {from_sql}\n"
            f"LEFT JOIN XF_BASE_BANK b ON t.BANKID = b.BANKID\n"
            f"WHERE {where_clause}"
        )
        return sql

    @classmethod
    def _join_clause(cls, dimension, bank_name):
        """LEFT JOIN XF_BASE_BANK, only needed for bank dimension queries."""
        if dimension == "bank" or bank_name:
            return "LEFT JOIN XF_BASE_BANK b ON t.BANKID = b.BANKID"
        return ""

    @classmethod
    def build_aggregate_query(cls, product_type="all", date_start=None, date_end=None,
                               special_states=None, buy_sell=None, bank_name=None,
                               cust_name=None, appid=None, dimension=None):
        """Build an aggregate SQL that returns SUM and COUNT.

        When dimension is provided, groups by that dimension (e.g. 客户经理名称).
        Otherwise returns a single total row.
        """
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(date_start, date_end, buy_sell, special_states, appid, bank_cond, cust_name=cust_name)
        where_clause = "\n  AND ".join(conditions)
        from_sql = cls._build_from(product_type)
        join = cls._join_clause(dimension, bank_name)

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
                                 dimension="bank", cust_name=None, appid=None):
        """Build a grouped SQL that returns hedge ratio by dimension."""
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(date_start, date_end, buy_sell, special_states, appid, bank_cond,
                                                  cust_name=cust_name, hedge_ratio_default=True)
        where_clause = "\n  AND ".join(conditions)
        from_sql = cls._build_from(product_type, with_pt=True)
        select_col, group_col = cls._group_cols(dimension)
        join = cls._join_clause(dimension, bank_name)

        sql = (
            f"{cte}"
            f"SELECT {select_col}, {cls.HEDGE_RATIO_SQL} as HEDGE_RATIO,\n"
            f"       SUM(CASE WHEN t.PT IN ('fwd','swap') THEN t.USDAMOUNT ELSE 0 END) as DERIVATIVE_AMOUNT,\n"
            f"       SUM(CASE WHEN t.PT IN ('fwd','swap') THEN 1 ELSE 0 END) as DERIVATIVE_COUNT,\n"
            f"       SUM(t.USDAMOUNT) as TOTAL_AMOUNT, COUNT(*) as TRADE_COUNT\n"
            f"FROM {from_sql}\n"
            f"{join}\n"
            f"WHERE {where_clause}\n"
            f"GROUP BY {group_col}\n"
            f"ORDER BY HEDGE_RATIO DESC"
        )
        return sql

    @classmethod
    def _group_cols(cls, dimension):
        """Return (select_col, group_col) based on dimension.

        Supported dimensions:
          bank           → 机构名称 (b.DIPNAME)
          customer       → 客户名称 (t.CUSTNAME)
          customer_id    → 客户号   (t.CUSTOMERID)
          manager        → 客户经理ID (t.CUSTMAINMANAGER)
          manager_name   → 客户经理名称 (t.CUSTMANAGERNAME)
        """
        mapping = {
            "bank": ("b.DIPNAME as 机构名称", "b.DIPNAME"),
            "customer": ("t.CUSTNAME as 客户名称", "t.CUSTNAME"),
            "customer_id": ("t.CUSTOMERID as 客户号", "t.CUSTOMERID"),
            "manager": ("t.CUSTMAINMANAGER as 客户经理ID", "t.CUSTMAINMANAGER"),
            "manager_name": ("t.CUSTMANAGERNAME as 客户经理名称", "t.CUSTMANAGERNAME"),
        }
        return mapping.get(dimension, mapping["bank"])

    @classmethod
    def build_ranking_query(cls, product_type="all", date_start=None, date_end=None,
                             special_states=None, buy_sell=None, bank_name=None, top_n=10,
                             dimension="bank", hedge_ratio=False, cust_name=None, appid=None):
        """Build a ranking SQL grouped by institution, ordered by SUM(USDAMOUNT) DESC, limited by top_n.
        When hedge_ratio=True, orders by HEDGE_RATIO DESC instead."""
        cls._validate_product_type(product_type)
        cls._validate_buy_sell(buy_sell)
        cls._validate_top_n(top_n)

        cte, bank_cond = cls._build_cte(bank_name)
        conditions = cls._build_where_conditions(date_start, date_end, buy_sell, special_states, appid, bank_cond,
                                                  cust_name=cust_name, hedge_ratio_default=hedge_ratio)
        where_clause = "\n  AND ".join(conditions)
        from_sql = cls._build_from(product_type, with_pt=hedge_ratio)
        select_col, group_col = cls._group_cols(dimension)
        join = cls._join_clause(dimension, bank_name)

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
                              dimension="bank", hedge_ratio=False, cust_name=None, appid=None):
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
        where_clause = "\n  AND ".join(conditions)
        from_sql = cls._build_from(product_type, with_pt=hedge_ratio)

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
        join = cls._join_clause(dimension, bank_name)

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
