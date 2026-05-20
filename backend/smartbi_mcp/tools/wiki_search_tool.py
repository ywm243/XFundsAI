"""MCP 工具: wiki_search — 搜索 wiki 概念/实体页面"""
import logging
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@ToolRegistry.register("wiki_search", category="wiki",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "page_type": {"type": "string", "enum": ["concept", "entity", "reference"]},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    })
async def wiki_search(query: str, page_type: str = None, limit: int = 5) -> dict:
    """搜索 wiki 概念/实体页面"""
    try:
        from backend.wiki.store import wiki_store
        if wiki_store is None:
            return {"results": [], "count": 0, "error": "wiki_store not initialized"}
        results = wiki_store.query(keyword=query, limit=limit)
        if page_type:
            results = [r for r in results if r.get("page_type") == page_type]
        return {"results": results[:limit], "count": len(results[:limit])}
    except Exception as e:
        logger.warning(f"wiki_search failed: {e}")
        return {"results": [], "count": 0, "error": str(e)}


def register(mcp):
    tool_def = ToolRegistry.get("wiki_search")
    if tool_def:
        mcp.tool()(tool_def.fn)
