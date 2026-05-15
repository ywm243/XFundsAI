# backend/mcp/tools/oracle_tool.py
"""MCP tool: oracle_query — execute read-only queries against Oracle FX database."""

import logging
from mcp.server.fastmcp import FastMCP
from db.connection import get_db

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """Register oracle_query tool on the given FastMCP instance."""

    @mcp.tool()
    def oracle_query(sql: str) -> dict:
        """Execute a read-only SQL query against the Oracle FX trade database.

        Database contains views: XF_FX_SPOTTRADE_VIEW, XF_FX_FWDTRADE_VIEW,
        XF_FX_SWAPTRADE_VIEW. Common fields: USDAMOUNT, TRADEDATE, TRADESTATUS,
        SPECIALSTATE, APPID, BUYORSELL, BANKID, CUSTNAME, CUSTOMERID,
        CUSTMAINMANAGER, CUSTMANAGERNAME.

        Args:
            sql: A complete Oracle SQL SELECT statement.

        Returns:
            dict with keys: columns (list of column names),
            rows (list of lists), row_count (int).
        """
        safe = sql.strip().upper()
        if not safe.startswith("SELECT") and not safe.startswith("WITH"):
            return {"columns": [], "rows": [], "row_count": 0,
                    "error": "Only SELECT / WITH queries are allowed"}

        forbidden = ["DROP", "ALTER", "CREATE", "TRUNCATE", "INSERT",
                     "UPDATE", "DELETE", "MERGE", "GRANT", "REVOKE"]
        for kw in forbidden:
            if kw in safe:
                return {"columns": [], "rows": [], "row_count": 0,
                        "error": f"Forbidden keyword: {kw}"}

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                cols = [desc[0] for desc in cur.description] if cur.description else []
                rows = [list(row) for row in cur.fetchall()]
                logger.info("oracle_query: %d rows, %d cols", len(rows), len(cols))
                return {"columns": cols, "rows": rows, "row_count": len(rows)}
