# backend/mcp/server.py
"""FastMCP server — registers and serves MCP tools."""

import sys
import importlib
import os

# HACK: Our local mcp/ package shadows the installed mcp SDK (v1.27.1).
# Temporarily remove our packages from sys.modules and backend from sys.path
# so the installed SDK can be imported, then restore everything.
_our_mcp = sys.modules.pop('mcp', None)
_our_mcp_server = sys.modules.pop('mcp.server', None)
_backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_old_path = sys.path[:]
sys.path = [p for p in sys.path if p not in ('', '.', _backend_path)]

try:
    _mod = importlib.import_module("mcp.server.fastmcp")
    FastMCP = _mod.FastMCP
finally:
    # Restore our packages
    if _our_mcp:
        sys.modules['mcp'] = _our_mcp
    if _our_mcp_server:
        sys.modules['mcp.server'] = _our_mcp_server
    # Keep the installed fastmcp module accessible for submodule imports
    sys.modules.setdefault('mcp.server.fastmcp', _mod)
    sys.path = _old_path

mcp = FastMCP("SmartBI", streamable_http_path="/", stateless_http=True)

from .tools import oracle_tool  # noqa: E402
oracle_tool.register(mcp)

from .tools import mysql_tool  # noqa: E402
mysql_tool.register(mcp)

from .tools import llm_tool  # noqa: E402
llm_tool.register(mcp)

from .tools import load_rules_tool  # noqa: E402
load_rules_tool.register(mcp)

from .tools import parse_date_tool  # noqa: E402
parse_date_tool.register(mcp)

from .tools import detect_entities_tool  # noqa: E402
detect_entities_tool.register(mcp)

from .tools import compute_comparison_tool  # noqa: E402
compute_comparison_tool.register(mcp)

from .tools import get_session_context_tool  # noqa: E402
get_session_context_tool.register(mcp)

from .tools import save_memory_tool  # noqa: E402
save_memory_tool.register(mcp)

from .tools import write_audit_log_tool  # noqa: E402
write_audit_log_tool.register(mcp)

from .tools import check_cache_tool  # noqa: E402
check_cache_tool.register(mcp)


def create_http_app():
    """Create the ASGI app and initialize the session manager.

    Returns the Starlette ASGI app. The caller is responsible for
    running the session manager lifespan via:

        async with mcp._session_manager.run():
            ...
    """
    return mcp.streamable_http_app()


def get_session_manager():
    """Return the session manager (must call create_http_app first)."""
    return mcp._session_manager
