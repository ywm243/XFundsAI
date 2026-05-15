# backend/mcp/tools/write_audit_log_tool.py
"""MCP tool: write_audit_log — append-only audit trail."""

import json
import logging
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def write_audit_log(request_id: str, data: str) -> str:
        """Write an entry to the append-only audit log.

        Args:
            request_id: Unique identifier for the request.
            data: JSON string containing audit fields. Must include
                  session_id, user_text, router_decision, resolved_params,
                  sql_executed, result_rows, response_to_user.

        Returns:
            'ok' on success, error message on failure.
        """
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            return f"error: invalid JSON - {exc}"

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO audit_log
                       (request_id, session_id, raw_input, router_decision,
                        resolved_params, sql_executed, result_rows,
                        result_hash, response_to_user, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        request_id,
                        payload.get("session_id", ""),
                        payload.get("user_text", ""),
                        json.dumps(payload.get("router_decision", {}), ensure_ascii=False),
                        json.dumps(payload.get("resolved_params", {}), ensure_ascii=False),
                        payload.get("sql_executed", ""),
                        payload.get("result_rows", 0),
                        payload.get("result_hash", ""),
                        payload.get("response_to_user", ""),
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
            conn.commit()
            logger.info("write_audit_log(%s): OK", request_id)
            return "ok"
        except Exception as exc:
            logger.warning("write_audit_log failed: %s", exc)
            return f"error: {exc}"
        finally:
            conn.close()
