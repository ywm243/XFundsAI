"""Wiki query interface — structured retrieval for agent consumption.

Provides typed accessors that validate page types and format results
with only the fields an agent needs, excluding internal DB metadata.
"""

import json
import logging
from datetime import datetime

from .store import wiki_store

logger = logging.getLogger(__name__)

# Page types considered "concept-like" for get_concept validation
_CONCEPT_TYPES = {"concept", "reference", "synthesis"}


# ── Public query functions ────────────────────────────────────────────

def get_concept(slug: str) -> dict | None:
    """Retrieve a concept/reference/synthesis page by slug.

    Returns the agent-formatted page dict, or None if not found or
    the page_type is not in (concept, reference, synthesis).
    """
    page = wiki_store.get(slug)
    if page is None:
        return None
    if page.get("page_type") not in _CONCEPT_TYPES:
        logger.debug(
            "get_concept: slug=%s has type=%s, expected one of %s",
            slug, page.get("page_type"), _CONCEPT_TYPES,
        )
        return None
    return _format_for_agent(page)


def get_customer_profile(customer_id: str) -> dict | None:
    """Retrieve an entity page representing a customer profile.

    Uses wiki_store.get_entity() which looks up by slug or keyword.
    Returns the agent-formatted page dict, or None.
    """
    page = wiki_store.get_entity(customer_id)
    if page is None:
        return None
    return _format_for_agent(page)


def search_concepts(keyword: str, limit: int = 10) -> list[dict]:
    """Search concept/reference/synthesis pages by keyword.

    Searches title and body for the given keyword string.
    Only returns pages whose page_type is concept, reference, or synthesis.
    """
    results = wiki_store.query(keyword=keyword, limit=limit)
    filtered = [r for r in results if r.get("page_type") in _CONCEPT_TYPES]
    return [_format_for_agent(r) for r in filtered]


def get_pages_by_tag(tag: str, limit: int = 20) -> list[dict]:
    """Retrieve pages matching a specific tag.

    Returns agent-formatted page dicts, ordered by most recently updated.
    """
    results = wiki_store.query(tag=tag, limit=limit)
    return [_format_for_agent(r) for r in results]


# ── Internal formatting ──────────────────────────────────────────────

def _format_for_agent(page: dict) -> dict:
    """Strip internal DB fields, return only what an agent needs.

    Returned keys: slug, title, type, body, frontmatter, tags,
                   confidence, reliability, updated_at
    """
    fm = page.get("frontmatter")
    if isinstance(fm, str):
        try:
            fm = json.loads(fm)
        except (json.JSONDecodeError, TypeError):
            fm = None

    tags = page.get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = None

    updated_at = page.get("updated_at")
    if isinstance(updated_at, datetime):
        updated_at = updated_at.isoformat()

    return {
        "slug": page.get("slug", ""),
        "title": page.get("title", ""),
        "type": page.get("page_type", ""),
        "body": page.get("body", ""),
        "frontmatter": fm,
        "tags": tags,
        "confidence": page.get("confidence"),
        "reliability": page.get("reliability"),
        "updated_at": updated_at,
    }
