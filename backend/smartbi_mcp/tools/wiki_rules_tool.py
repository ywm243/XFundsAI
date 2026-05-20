"""MCP 工具: wiki_query_rules — 从 wiki 知识库动态读取匹配规则"""
import logging
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@ToolRegistry.register("wiki_query_rules", category="wiki",
    input_schema={
        "type": "object",
        "properties": {
            "query_text": {"type": "string", "description": "用户查询文本"},
            "rule_categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选：限制的规则类别列表"
            },
        },
        "required": ["query_text"],
    })
async def wiki_query_rules(query_text: str, rule_categories: list[str] = None) -> dict:
    """从 wiki 读取匹配规则，补充 gatekeep 硬编码盲区"""
    try:
        from wiki.store import wiki_store
        if wiki_store is None:
            return {"rules": [], "count": 0, "hint": "wiki_store not initialized"}
        keywords = set()
        for kw in ["即期", "远期", "掉期", "结汇", "购汇", "交易量", "套保率",
                    "报价", "询价", "月", "季度", "年"]:
            if kw in query_text:
                keywords.add(kw)
        if not keywords:
            return {"rules": [], "hint": "no keywords matched"}
        rules = []
        seen = set()
        for kw in keywords:
            pages = wiki_store.query(keyword=kw, limit=3)
            for p in pages:
                slug = p.get("slug", "")
                if slug in seen:
                    continue
                seen.add(slug)
                rules.append({
                    "slug": slug,
                    "title": p.get("title", ""),
                    "body": (p.get("body", "") or "")[:600],
                })
        if rule_categories:
            rules = [r for r in rules if r.get("category", "") in rule_categories]
        return {"rules": rules[:5], "count": len(rules[:5])}
    except Exception as e:
        logger.warning(f"wiki_query_rules failed: {e}")
        return {"rules": [], "count": 0, "error": str(e)}


def register(mcp):
    tool_def = ToolRegistry.get("wiki_query_rules")
    if tool_def:
        mcp.tool()(tool_def.fn)
