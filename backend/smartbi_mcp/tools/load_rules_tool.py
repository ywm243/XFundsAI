# backend/mcp/tools/load_rules_tool.py
"""MCP tool: load_rules — query MySQL rule items by category."""

import json
import logging
from mcp.server.fastmcp import FastMCP
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def load_rules(category: str) -> list[dict]:
        """Load rule items for a given category from the MySQL rules store.

        Categories: product_type, buy_sell_direction, bank_name,
        special_states, amount_filter, app_id.

        Args:
            category: Rule category name (matches rule_categories.category).

        Returns:
            list of dicts from rule_items joined with rule_categories.
        """
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ri.id, rc.category, rc.display_name,
                              ri.keywords, ri.rule_data,
                              ri.is_ironclad, ri.priority
                       FROM rule_items ri
                       JOIN rule_categories rc ON ri.category_id = rc.id
                       WHERE rc.category = %s AND ri.is_active = 1
                       ORDER BY ri.priority""",
                    (category,),
                )
                rows = [dict(r) for r in cur.fetchall()]
                logger.info("load_rules(%s): %d items", category, len(rows))
                return rows
        finally:
            conn.close()
