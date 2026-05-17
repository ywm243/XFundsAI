"""Oracle SQL execution service."""

import logging

from db.connection import get_db

logger = logging.getLogger(__name__)

_MAX_ROWS = 10000


def execute_oracle(sql: str) -> tuple[list, list]:
    """Execute SQL against Oracle, return (columns, rows)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [desc[0] for desc in cur.description] if cur.description else []
            rows = [list(row) for row in cur.fetchmany(_MAX_ROWS)]
            if cur.fetchone() is not None:
                logger.warning("Query result exceeds %d rows, truncated", _MAX_ROWS)
    return cols, rows
