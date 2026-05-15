# backend/mcp/tools/save_memory_tool.py
"""MCP tool: save_memory — persist session memory."""

import json
import logging
from mcp.server.fastmcp import FastMCP
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def save_memory(session_id: str, key: str, value: str) -> str:
        """Save a key-value memory entry for a session.

        Upserts into the memory_summaries table.

        Args:
            session_id: The session identifier.
            key: Memory key (e.g., 'last_params', 'user_preference').
            value: JSON-encoded value string.

        Returns:
            'ok' on success, error message on failure.
        """
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO memory_summaries (session_id, key, value) "
                    "VALUES (%s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE value = %s, updated_at = NOW()",
                    (session_id, key, value, value),
                )
            conn.commit()
            logger.info("save_memory(%s, %s): %d chars", session_id, key, len(value))
            return "ok"
        except Exception as exc:
            logger.warning("save_memory failed: %s", exc)
            return f"error: {exc}"
        finally:
            conn.close()
