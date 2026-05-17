# backend/mcp/tools/get_session_context_tool.py
"""MCP tool: get_session_context — retrieve conversation history."""

import logging
from mcp.server.fastmcp import FastMCP
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_session_context(session_id: str, n: int = 20) -> list[dict]:
        """Get recent conversation turns for a session.

        Args:
            session_id: The session identifier.
            n: Number of recent turns to retrieve (default 20).

        Returns:
            list of dicts with keys: turn_index, user_query, parsed_params,
            executed_sql, result_summary.
        """
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT turn_index, user_query, parsed_params, "
                    "executed_sql, result_summary "
                    "FROM turns WHERE session_id = %s "
                    "ORDER BY turn_index DESC LIMIT %s",
                    (session_id, n),
                )
                rows = cur.fetchall()
                # Reverse to chronological order
                result = [dict(r) for r in reversed(rows)]
                logger.info("get_session_context(%s): %d turns", session_id, len(result))
                return result
        finally:
            conn.close()
