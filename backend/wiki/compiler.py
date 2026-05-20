"""Wiki compiler — reads markdown files from llm-wiki/ and upserts into MySQL.

Incremental compilation: skips files whose mtime hasn't changed since the last
DB update, avoiding redundant writes on every compile_all() call.
"""

import json
import logging
import re
from pathlib import Path

import yaml

from .store import wiki_store

logger = logging.getLogger(__name__)

WIKI_ROOT = Path(__file__).resolve().parent.parent.parent / "llm-wiki"

# ── Frontmatter parsing ──────────────────────────────────────────────

_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body.

    Returns (frontmatter_dict, body_text).
    If no valid frontmatter is found, returns ({}, original_text).
    """
    m = _FM_PATTERN.match(text)
    if not m:
        return {}, text
    fm_raw = m.group(1)
    try:
        fm = yaml.safe_load(fm_raw)
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        logger.warning("Failed to parse frontmatter, treating as plain markdown")
        fm = {}
    body = text[m.end():]
    return fm, body


# ── Incremental compilation ──────────────────────────────────────────

def _needs_compile(md_path: Path, slug: str) -> bool:
    """Check if a file needs recompilation by comparing mtime vs DB updated_at."""
    existing = wiki_store.get(slug)
    if existing is None:
        return True
    db_updated = existing.get("updated_at")
    if db_updated is None:
        return True
    # Compare file modification time with DB timestamp
    file_mtime = md_path.stat().st_mtime
    db_epoch = db_updated.timestamp() if hasattr(db_updated, "timestamp") else 0
    return file_mtime > db_epoch


def compile_directory(directory: str, page_type: str = "concept") -> dict:
    """Compile all .md files in a subdirectory of WIKI_ROOT.

    Args:
        directory: Subdirectory name under WIKI_ROOT (e.g. "concepts", "entities").
        page_type: Default page_type when not specified in frontmatter.

    Returns:
        {"compiled": int, "skipped": int, "errors": list[str]}
    """
    dir_path = WIKI_ROOT / directory
    if not dir_path.is_dir():
        logger.warning("Wiki directory not found: %s", dir_path)
        return {"compiled": 0, "skipped": 0, "errors": [f"Directory not found: {dir_path}"]}

    compiled = 0
    skipped = 0
    errors = []

    for md_path in sorted(dir_path.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(text)

            slug = fm.get("slug", md_path.stem)
            title = fm.get("title", slug.replace("-", " ").replace("_", " ").title())
            ptype = fm.get("type", page_type)

            if not _needs_compile(md_path, slug):
                skipped += 1
                continue

            # Extract optional fields from frontmatter
            kwargs = {}
            if "sources" in fm:
                kwargs["sources"] = fm["sources"]
            if "tags" in fm:
                kwargs["tags"] = fm["tags"]
            if "confidence" in fm:
                kwargs["confidence"] = float(fm["confidence"])
            if "reliability" in fm:
                kwargs["reliability"] = fm["reliability"]
            if "parent_slug" in fm:
                kwargs["parent_slug"] = fm["parent_slug"]

            # Pass remaining frontmatter as the frontmatter JSON field
            kwargs["frontmatter"] = fm

            wiki_store.save(slug=slug, title=title, page_type=ptype, body=body, **kwargs)
            compiled += 1
            logger.debug("Compiled wiki page: %s (type=%s)", slug, ptype)

        except Exception as e:
            err_msg = f"{md_path.name}: {e}"
            errors.append(err_msg)
            logger.error("Failed to compile %s: %s", md_path, e)

    logger.info(
        "Compiled %s/: %d compiled, %d skipped, %d errors",
        directory, compiled, skipped, len(errors),
    )
    return {"compiled": compiled, "skipped": skipped, "errors": errors}


def compile_all() -> dict:
    """Compile both concepts/ and entities/ directories.

    Returns:
        {"compiled": int, "skipped": int, "errors": list[str]}
    """
    result_concepts = compile_directory("concepts", page_type="concept")
    result_entities = compile_directory("entities", page_type="entity")

    return {
        "compiled": result_concepts["compiled"] + result_entities["compiled"],
        "skipped": result_concepts["skipped"] + result_entities["skipped"],
        "errors": result_concepts["errors"] + result_entities["errors"],
    }
