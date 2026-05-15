"""SQLite store for rules and memory persistence.

Single SQLite database for both rule engine and agent memory.
Rules are loaded into memory cache on first access; admin writes
clear the cache so next request picks up changes.
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "smartbi.db"

_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    """Get a thread-safe SQLite connection."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ============================================================
# Schema
# ============================================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rule_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_type TEXT NOT NULL CHECK(agent_type IN ('common','bi','quoting','risk')),
    category TEXT NOT NULL,
    display_name TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    UNIQUE(agent_type, category)
);

CREATE TABLE IF NOT EXISTS rule_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES rule_categories(id) ON DELETE CASCADE,
    keywords TEXT NOT NULL,
    rule_data TEXT NOT NULL,
    is_ironclad INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS rule_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL,
    version_num INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    created_by TEXT DEFAULT 'system',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL DEFAULT 'bi',
    user_id TEXT DEFAULT 'default',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_index INTEGER NOT NULL,
    user_query TEXT NOT NULL,
    parsed_params TEXT,
    executed_sql TEXT,
    result_summary TEXT,
    user_feedback TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS memory_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    scope TEXT NOT NULL DEFAULT 'session',
    summary_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source_turns TEXT,
    embedding_id TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_rule_items_category ON rule_items(category_id);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_type, user_id);
"""


def init_db() -> None:
    """Create tables if they don't exist."""
    with _lock:
        conn = get_conn()
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            logger.info("SQLite database initialized at %s", DB_PATH)
        finally:
            conn.close()


# ============================================================
# Rule CRUD (used by rules_engine and admin API)
# ============================================================

def load_rules_from_db() -> dict:
    """Load all active rules from SQLite.

    Returns the same nested dict structure that semantic_rules.json used,
    so rules_engine.py and prompt_builder.py don't need to change.

    special_trade_type category is split back into special_states and trade_class
    keys (filtered by sub_type) for backward compatibility.
    """
    conn = get_conn()
    try:
        categories = conn.execute(
            "SELECT * FROM rule_categories ORDER BY agent_type, priority"
        ).fetchall()

        result: dict[str, dict] = {}
        for cat in categories:
            items = conn.execute(
                """SELECT * FROM rule_items
                   WHERE category_id=? AND is_active=1
                   ORDER BY priority""",
                (cat["id"],),
            ).fetchall()

            rules_list = []
            for item in items:
                rule = json.loads(item["rule_data"])
                rule["keywords"] = json.loads(item["keywords"])
                if item["is_ironclad"]:
                    rule["_ironclad"] = True
                rules_list.append(rule)

            if cat["category"] == "special_trade_type":
                # Split back into special_states and trade_class for rules_engine compat
                state_rules = [r for r in rules_list if (r.get("sub_type") or "").startswith("state")]
                class_rules = [r for r in rules_list if "class" in (r.get("sub_type") or "")]
                if state_rules:
                    result["special_states"] = {
                        "_agent_type": cat["agent_type"],
                        "_display_name": cat["display_name"],
                        "rules": state_rules,
                    }
                if class_rules:
                    result["trade_class"] = {
                        "_agent_type": cat["agent_type"],
                        "_display_name": cat["display_name"],
                        "rules": class_rules,
                    }
            else:
                result[cat["category"]] = {
                    "_agent_type": cat["agent_type"],
                    "_display_name": cat["display_name"],
                    "rules": rules_list,
                }

        return result
    finally:
        conn.close()


def get_categories(agent_type: str | None = None) -> list[dict]:
    """List rule categories, optionally filtered by agent_type."""
    conn = get_conn()
    try:
        if agent_type:
            rows = conn.execute(
                "SELECT * FROM rule_categories WHERE agent_type=? ORDER BY priority",
                (agent_type,),
            )
        else:
            rows = conn.execute(
                "SELECT * FROM rule_categories ORDER BY agent_type, priority"
            )
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_category(category_id: int) -> dict | None:
    """Get a single category by id."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM rule_categories WHERE id=?", (category_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_items(category_id: int) -> list[dict]:
    """Get all rule items for a category."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM rule_items WHERE category_id=? ORDER BY priority",
            (category_id,),
        )
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_item(category_id: int, keywords: list[str], rule_data: dict,
             is_ironclad: bool = False, priority: int = 0) -> int:
    """Add a rule item. Returns new item id."""
    with _lock:
        conn = get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO rule_items (category_id, keywords, rule_data, is_ironclad, priority)
                   VALUES (?, ?, ?, ?, ?)""",
                (category_id, json.dumps(keywords, ensure_ascii=False),
                 json.dumps(rule_data, ensure_ascii=False),
                 1 if is_ironclad else 0, priority),
            )
            _backup_category(conn, category_id)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def update_item(item_id: int, keywords: list[str] | None = None,
                rule_data: dict | None = None, is_ironclad: bool | None = None,
                priority: int | None = None, is_active: bool | None = None) -> bool:
    """Update a rule item. Returns True if updated."""
    with _lock:
        conn = get_conn()
        try:
            item = conn.execute(
                "SELECT category_id FROM rule_items WHERE id=?", (item_id,)
            ).fetchone()
            if not item:
                return False

            sets = []
            params: list = []
            if keywords is not None:
                sets.append("keywords=?")
                params.append(json.dumps(keywords, ensure_ascii=False))
            if rule_data is not None:
                sets.append("rule_data=?")
                params.append(json.dumps(rule_data, ensure_ascii=False))
            if is_ironclad is not None:
                sets.append("is_ironclad=?")
                params.append(1 if is_ironclad else 0)
            if priority is not None:
                sets.append("priority=?")
                params.append(priority)
            if is_active is not None:
                sets.append("is_active=?")
                params.append(1 if is_active else 0)

            if not sets:
                return False

            sets.append("updated_at=?")
            params.append(_now())
            params.append(item_id)

            conn.execute(
                f"UPDATE rule_items SET {', '.join(sets)} WHERE id=?",
                params,
            )
            _backup_category(conn, item["category_id"])
            conn.commit()
            return True
        finally:
            conn.close()


def delete_item(item_id: int) -> bool:
    """Soft-delete a rule item (set is_active=0)."""
    return update_item(item_id, is_active=False)


def _backup_category(conn: sqlite3.Connection, category_id: int) -> None:
    """Auto-backup a category's rules before modification."""
    items = conn.execute(
        "SELECT * FROM rule_items WHERE category_id=? ORDER BY priority",
        (category_id,),
    ).fetchall()
    snapshot = json.dumps([dict(r) for r in items], ensure_ascii=False)

    latest = conn.execute(
        "SELECT MAX(version_num) FROM rule_versions WHERE category_id=?",
        (category_id,),
    ).fetchone()
    next_ver = (latest[0] or 0) + 1

    conn.execute(
        "INSERT INTO rule_versions (category_id, version_num, snapshot) VALUES (?, ?, ?)",
        (category_id, next_ver, snapshot),
    )


def get_versions(category_id: int) -> list[dict]:
    """Get version history for a category."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM rule_versions WHERE category_id=? ORDER BY version_num DESC LIMIT 50",
            (category_id,),
        )
        return [dict(r) for r in rows]
    finally:
        conn.close()


def rollback_category(category_id: int, version_num: int) -> bool:
    """Rollback a category to a specific version."""
    with _lock:
        conn = get_conn()
        try:
            ver = conn.execute(
                "SELECT * FROM rule_versions WHERE category_id=? AND version_num=?",
                (category_id, version_num),
            ).fetchone()
            if not ver:
                return False

            snapshot = json.loads(ver["snapshot"])

            # Delete current items for this category
            conn.execute(
                "DELETE FROM rule_items WHERE category_id=?", (category_id,)
            )

            # Re-insert from snapshot
            for item in snapshot:
                conn.execute(
                    """INSERT INTO rule_items
                       (id, category_id, keywords, rule_data, is_ironclad, priority, is_active)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (item["id"], item["category_id"], item["keywords"],
                     item["rule_data"], item["is_ironclad"],
                     item.get("priority", 0), item.get("is_active", 1)),
                )

            conn.commit()
            return True
        finally:
            conn.close()


# ============================================================
# Session / Memory (used by agent memory layer)
# ============================================================

def create_session(session_id: str, agent_type: str = "bi",
                   user_id: str = "default") -> None:
    with _lock:
        conn = get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO sessions (id, agent_type, user_id, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (session_id, agent_type, user_id, _now()),
            )
            conn.commit()
        finally:
            conn.close()


def add_turn(session_id: str, turn_index: int, user_query: str,
             parsed_params: dict | None = None, executed_sql: str | None = None,
             result_summary: str | None = None, user_feedback: str | None = None) -> int:
    with _lock:
        conn = get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO turns (session_id, turn_index, user_query,
                   parsed_params, executed_sql, result_summary, user_feedback)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, turn_index, user_query,
                 json.dumps(parsed_params, ensure_ascii=False) if parsed_params else None,
                 executed_sql, result_summary, user_feedback),
            )
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (_now(), session_id),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def get_session_context(session_id: str, last_n: int = 3) -> list[dict]:
    """Get the last N turns of a session for context injection."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM turns WHERE session_id=?
               ORDER BY turn_index DESC LIMIT ?""",
            (session_id, last_n),
        )
        return list(reversed([dict(r) for r in rows]))
    finally:
        conn.close()


def add_summary(session_id: str, summary_type: str, content: dict,
                source_turns: str | None = None) -> int:
    with _lock:
        conn = get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO memory_summaries (session_id, summary_type, content, source_turns)
                   VALUES (?, ?, ?, ?)""",
                (session_id, summary_type,
                 json.dumps(content, ensure_ascii=False), source_turns),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


# ============================================================
# Migration from JSON files
# ============================================================

def migrate_from_json(rules_path: str | None = None) -> int:
    """Import rules from semantic_rules.json into SQLite.

    Returns number of items imported.

    Maps 6 original JSON keys into 5 user-facing categories:
      app_id, buy_sell_direction, product_type, special_trade_type, time_expressions
    special_states + trade_class merge into special_trade_type (differentiated by sub_type).
    """
    if rules_path is None:
        rules_path = str(
            Path(__file__).resolve().parent.parent / "knowledge_base" / "semantic_rules.json"
        )

    with open(rules_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    init_db()
    count = 0

    # New category mapping: old JSON key -> (category_key, display_name, agent_type, [sub_type])
    CATEGORY_MAP: dict[str, tuple[str, str, str, str | None]] = {
        "app_id":               ("app_id",               "产品类型映射",     "common", None),
        "buy_sell_direction":    ("buy_sell_direction",    "买卖方向映射",     "common", None),
        "product_type":          ("product_type",          "交易类型映射",     "common", None),
        "special_states":        ("special_trade_type",    "特殊交易类型映射", "common", "state"),
        "trade_class":           ("special_trade_type",    "特殊交易类型映射", "common", "class"),
        "time_expressions":      ("time_expressions",      "时间表达式映射",   "common", None),
    }
    BI_CATEGORIES = {"comparison_modifiers"}

    def _ensure_category(conn, agent_type: str, category: str, display_name: str) -> int:
        """Insert or get a category row, return its id."""
        conn.execute(
            """INSERT OR IGNORE INTO rule_categories (agent_type, category, display_name)
               VALUES (?, ?, ?)""",
            (agent_type, category, display_name),
        )
        row = conn.execute(
            "SELECT id FROM rule_categories WHERE agent_type=? AND category=?",
            (agent_type, category),
        ).fetchone()
        return row["id"]

    def _insert_rules(conn, category_id: int, rules: list, sub_type: str | None = None) -> int:
        """Insert a list of rule dicts. Returns number inserted."""
        n = 0
        for rule in rules:
            keywords = rule.pop("keywords", None) or rule.pop("keyword", None)
            if isinstance(keywords, str):
                keywords = [keywords]
            if not keywords:
                keywords = []
            rule_data = {k: v for k, v in rule.items() if not k.startswith("_")}
            if sub_type:
                rule_data["sub_type"] = sub_type
            is_ironclad = not rule.get("customer_reversible", True)

            conn.execute(
                """INSERT INTO rule_items (category_id, keywords, rule_data, is_ironclad)
                   VALUES (?, ?, ?, ?)""",
                (category_id, json.dumps(keywords, ensure_ascii=False),
                 json.dumps(rule_data, ensure_ascii=False),
                 1 if is_ironclad else 0),
            )
            n += 1
        return n

    with _lock:
        conn = get_conn()
        try:
            for category_key, category_val in data.items():
                if category_key.startswith("_"):
                    continue

                # --- Main categories (the 5 user-facing groups) ---
                if category_key in CATEGORY_MAP:
                    (cat_key, display_name, agent_type, sub_type) = CATEGORY_MAP[category_key]
                    rules_list = category_val.get("rules", [])
                    if not rules_list:
                        continue
                    cat_id = _ensure_category(conn, agent_type, cat_key, display_name)
                    count += _insert_rules(conn, cat_id, rules_list, sub_type)

                # --- Nested BI categories (comparison_modifiers inside time_expressions) ---
                if isinstance(category_val, dict) and category_key == "time_expressions":
                    for nested_key, nested_val in category_val.items():
                        if nested_key in BI_CATEGORIES and isinstance(nested_val, dict) and "rules" in nested_val:
                            display_name = nested_val.get("_description", nested_key)
                            cat_id = _ensure_category(conn, "bi", nested_key, display_name)
                            count += _insert_rules(conn, cat_id, nested_val["rules"])

            conn.commit()
            logger.info("Migrated %d rules from %s to SQLite", count, rules_path)
            return count
        finally:
            conn.close()


# Run migration on import if DB is empty
def _auto_migrate() -> None:
    init_db()
    conn = get_conn()
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM rule_items").fetchone()[0]
        if cnt == 0:
            logger.info("SQLite rule store is empty, running auto-migration...")
            migrate_from_json()
    finally:
        conn.close()


_auto_migrate()
