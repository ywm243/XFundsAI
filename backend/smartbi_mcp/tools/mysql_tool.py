# backend/mcp/tools/mysql_tool.py
"""MCP tool: mysql_query — execute read-only queries against MySQL rules/memory store."""

import logging
from mcp.server.fastmcp import FastMCP
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """Register mysql_query tool on the given FastMCP instance."""

    @mcp.tool()
    def mysql_query(sql: str) -> list[dict]:
        """Execute a read-only SQL query against the MySQL rules and memory store.

        Tables: rule_categories, rule_items, rule_versions, sessions,
        turns, memory_summaries.

        Args:
            sql: A complete MySQL SELECT statement.

        Returns:
            list of dicts, each dict representing one result row.
        """
        safe = sql.strip().upper()
        if not safe.startswith("SELECT"):
            return [{"error": "Only SELECT queries are allowed"}]

        forbidden = ["DROP", "ALTER", "CREATE", "TRUNCATE", "INSERT",
                     "UPDATE", "DELETE", "GRANT", "REVOKE"]
        for kw in forbidden:
            if kw in safe:
                return [{"error": f"Forbidden keyword: {kw}"}]

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                result = [dict(r) for r in rows]
                logger.info("mysql_query: %d rows", len(result))
                return result
        finally:
            conn.close()
