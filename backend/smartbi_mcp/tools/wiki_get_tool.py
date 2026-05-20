"""MCP 工具: wiki_get — 获取指定 slug 的 wiki 页面"""
import logging
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@ToolRegistry.register("wiki_get", category="wiki",
    input_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "页面 slug"},
        },
        "required": ["slug"],
    })
async def wiki_get(slug: str) -> dict:
    """获取指定 slug 的 wiki 页面"""
    try:
        from wiki.store import wiki_store
        if wiki_store is None:
            return {"found": False, "error": "wiki_store not initialized"}
        page = wiki_store.get(slug)
        if page:
            return {"found": True, "page": page}
        return {"found": False, "error": f"Page not found: {slug}"}
    except Exception as e:
        logger.warning(f"wiki_get failed: {e}")
        return {"found": False, "error": str(e)}


def register(mcp):
    tool_def = ToolRegistry.get("wiki_get")
    if tool_def:
        mcp.tool()(tool_def.fn)
