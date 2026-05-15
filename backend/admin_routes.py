"""Admin API for rule management — CRUD + preview + hot-reload."""

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from db import sqlite_store
from llm_parser.parser import rule_based_parse, _rule_confidence
from llm_parser.rules_engine import gatekeep, reload_rules
from llm_parser.prompt_builder import invalidate_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _validate_rule_item(category: dict, keywords: list[str], rule_data: dict,
                         is_ironclad: bool, item_id: int | None = None) -> list[str]:
    """Validate a rule item before save. Returns list of Chinese error messages."""
    errors = []

    # Uniqueness check
    existing_items = sqlite_store.get_items(category["id"])
    existing_kw = {}
    for item in existing_items:
        if item_id and item["id"] == item_id:
            continue
        try:
            kws = json.loads(item["keywords"])
        except (json.JSONDecodeError, TypeError):
            kws = []
        for k in kws:
            existing_kw[k] = item["id"]

    for kw in keywords:
        if kw in existing_kw:
            errors.append(f"关键词'{kw}'已存在于该分类中，不能重复使用")

    # State code range (for special_trade_type with sub_type=state*)
    if category["category"] == "special_trade_type" and (rule_data.get("sub_type") or "").startswith("state"):
        try:
            val = int(rule_data.get("value", -1))
        except (ValueError, TypeError):
            val = -1
        if val not in {1, 3, 4, 5}:
            errors.append(f"特殊状态值'{val}'不在允许范围内，有效值为 1(逾期),3(展期),4(提前交割),5(平仓)。注意：在途不是SPECIALSTATE，在途=totaldelivery剩余金额>0")

    # Trade class code range (for special_trade_type with sub_type containing 'class')
    if category["category"] == "special_trade_type" and "class" in (rule_data.get("sub_type") or ""):
        try:
            val = int(rule_data.get("value", -1))
        except (ValueError, TypeError):
            val = -1
        VALID_TRADE_CLASSES = {0,1,2,3,4,5,6,7,10,11,12,13,14,15,16,17}
        if val not in VALID_TRADE_CLASSES:
            errors.append(f"交易类别值'{val}'不在允许范围内")

    # Product type
    if category["category"] == "product_type":
        val = rule_data.get("value", "")
        if val not in ("spot", "fwd", "swap", "all"):
            errors.append(f"未知的产品类型: {val}，有效值为 spot/fwd/swap/all")

    # Direction required
    if category["category"] == "buy_sell_direction" and not rule_data.get("direction"):
        errors.append("买卖方向规则的'方向'字段不能为空")

    return errors


# ---- Request/Response models ----

class RuleItemCreate(BaseModel):
    keywords: list[str]
    rule_data: dict
    is_ironclad: bool = False
    priority: int = 0


class RuleItemUpdate(BaseModel):
    keywords: list[str] | None = None
    rule_data: dict | None = None
    is_ironclad: bool | None = None
    priority: int | None = None
    is_active: bool | None = None


class PreviewRequest(BaseModel):
    text: str


# ---- Categories ----

@router.get("/rules/categories")
def list_categories(agent_type: str | None = None):
    """List all rule categories, optionally filtered by agent_type."""
    cats = sqlite_store.get_categories(agent_type)
    result = []
    for c in cats:
        items = sqlite_store.get_items(c["id"])
        result.append({
            **c,
            "item_count": len(items),
            "active_count": sum(1 for i in items if i.get("is_active")),
        })
    return {"categories": result}


# ---- Items ----

@router.get("/rules/categories/{category_id}/items")
def list_items(category_id: int):
    """Get all rule items for a category."""
    cat = sqlite_store.get_category(category_id)
    if not cat:
        raise HTTPException(404, "Category not found")
    items = sqlite_store.get_items(category_id)
    # Parse JSON fields for frontend
    for item in items:
        try:
            item["keywords"] = json.loads(item["keywords"])
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            item["rule_data"] = json.loads(item["rule_data"])
        except (json.JSONDecodeError, TypeError):
            pass
    return {"category": cat, "items": items}


@router.post("/rules/categories/{category_id}/items")
def create_item(category_id: int, body: RuleItemCreate):
    """Add a new rule item."""
    cat = sqlite_store.get_category(category_id)
    if not cat:
        raise HTTPException(404, "Category not found")

    # Validate keywords don't conflict in same category
    errors = _validate_rule_item(cat, body.keywords, body.rule_data, body.is_ironclad)
    if errors:
        raise HTTPException(422, detail="; ".join(errors))

    item_id = sqlite_store.add_item(
        category_id=category_id,
        keywords=body.keywords,
        rule_data=body.rule_data,
        is_ironclad=body.is_ironclad,
        priority=body.priority,
    )
    return {"id": item_id, "status": "created"}


@router.put("/rules/items/{item_id}")
def update_item(item_id: int, body: RuleItemUpdate):
    """Update a rule item."""
    # Validate if keywords or rule_data are being updated
    if body.keywords is not None or body.rule_data is not None:
        # Look up the item to find its category
        conn = sqlite_store.get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM rule_items WHERE id=?", (item_id,)
            ).fetchone()
        finally:
            conn.close()
        if row:
            cat = sqlite_store.get_category(row["category_id"])
            keywords = body.keywords or []
            rule_data = body.rule_data or {}
            is_ironclad = body.is_ironclad if body.is_ironclad is not None else False
            errors = _validate_rule_item(cat, keywords, rule_data, is_ironclad, item_id=item_id)
            if errors:
                raise HTTPException(422, detail="; ".join(errors))

    ok = sqlite_store.update_item(
        item_id=item_id,
        keywords=body.keywords,
        rule_data=body.rule_data,
        is_ironclad=body.is_ironclad,
        priority=body.priority,
        is_active=body.is_active,
    )
    if not ok:
        raise HTTPException(404, "Item not found")
    return {"id": item_id, "status": "updated"}


@router.delete("/rules/items/{item_id}")
def delete_item(item_id: int):
    """Soft-delete a rule item."""
    ok = sqlite_store.delete_item(item_id)
    if not ok:
        raise HTTPException(404, "Item not found")
    return {"id": item_id, "status": "deleted"}


# ---- Versions ----

@router.get("/rules/categories/{category_id}/versions")
def list_versions(category_id: int):
    """Get version history for a category."""
    cat = sqlite_store.get_category(category_id)
    if not cat:
        raise HTTPException(404, "Category not found")
    versions = sqlite_store.get_versions(category_id)
    return {"category": cat, "versions": versions}


@router.post("/rules/categories/{category_id}/rollback")
def rollback_category(category_id: int, version_num: int):
    """Rollback a category to a specific version."""
    ok = sqlite_store.rollback_category(category_id, version_num)
    if not ok:
        raise HTTPException(404, f"Version {version_num} not found")
    # Clear caches so changes take effect
    _reload_all()
    return {"status": "rollback", "version": version_num}


# ---- Preview ----

@router.post("/rules/preview")
def preview_rules(body: PreviewRequest):
    """Preview rule matching for a query text.

    Returns the rule_based_parse result + confidence,
    so admins can test rules before deploying.
    """
    parsed = rule_based_parse(body.text)
    confidence = _rule_confidence(body.text, parsed)
    # Also show what gatekeep would do
    gatekept = gatekeep(parsed.copy(), body.text)
    return {
        "text": body.text,
        "rule_parsed": parsed,
        "confidence": confidence,
        "would_skip_llm": confidence >= 0.8,
        "after_gatekeep": gatekept,
    }


# ---- Hot-reload ----

@router.post("/rules/reload")
def api_reload_rules():
    """Clear all rule caches so next request picks up SQLite changes."""
    _reload_all()
    return {"status": "ok", "message": "Rules reloaded from SQLite, caches cleared"}


def _reload_all():
    reload_rules()
    invalidate_cache()
    logger.info("Admin: all rule caches cleared")
