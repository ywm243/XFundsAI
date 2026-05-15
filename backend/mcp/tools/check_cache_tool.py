# backend/mcp/tools/check_cache_tool.py
"""MCP tool: check_cache — query result cache lookup.

Stub implementation — cache layer comes in Phase 4.
"""

import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def check_cache(params_hash: str) -> dict | None:
        """Check if a cached query result exists for the given params hash.

        Args:
            params_hash: SHA-256 hash of serialized query parameters.

        Returns:
            Cached result dict, or None (cache not yet implemented).
        """
        logger.debug("check_cache(%s): miss (cache not implemented)", params_hash)
        return None
