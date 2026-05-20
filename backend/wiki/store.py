"""High-level wiki store — wraps mysql_store wiki functions with caching."""

import logging
from functools import lru_cache

from db import mysql_store

logger = logging.getLogger(__name__)


class WikiStore:
    """Unified read/write interface for wiki pages."""

    def save(self, slug: str, title: str, page_type: str, body: str, **kwargs) -> int:
        """Save or update a wiki page. Invalidates cache for this slug."""
        _page_cache.cache_clear()
        return mysql_store.save_wiki_page(slug, title, page_type, body, **kwargs)

    def get(self, slug: str) -> dict | None:
        """Get a wiki page by slug (cached)."""
        return _page_cache(slug)

    def query(self, **kwargs) -> list[dict]:
        """Search wiki pages. Not cached — queries are diverse."""
        return mysql_store.query_wiki_pages(**kwargs)

    def delete(self, slug: str) -> bool:
        """Delete a wiki page. Invalidates cache."""
        _page_cache.cache_clear()
        return mysql_store.delete_wiki_page(slug)

    def get_entity(self, entity_id: str) -> dict | None:
        """Shortcut: get a page of type 'entity' by slug."""
        page = self.get(f"entity-{entity_id}")
        if page and page.get("page_type") == "entity":
            return page
        results = self.query(page_type="entity", keyword=entity_id, limit=1)
        return results[0] if results else None


@lru_cache(maxsize=200)
def _page_cache(slug: str) -> dict | None:
    return mysql_store.get_wiki_page(slug)


# Global singleton
wiki_store = WikiStore()
