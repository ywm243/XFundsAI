"""MySQL store for rules and memory persistence.

Replaces the SQLite backend with MySQL 8.0.
All public function signatures are identical to sqlite_store.py.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

from db.config import MySQLConfig

logger = logging.getLogger(__name__)

_config = MySQLConfig()
_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> pymysql.Connection:
    """Get a new MySQL connection with DictCursor."""
    return pymysql.connect(
        cursorclass=DictCursor,
        autocommit=False,
        **_config.dsn,
    )


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rule_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    agent_type ENUM('common','bi','quoting','risk') NOT NULL,
    category VARCHAR(64) NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    priority INT DEFAULT 0,
    UNIQUE KEY uq_agent_category (agent_type, category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rule_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_id INT NOT NULL,
    keywords JSON NOT NULL,
    rule_data JSON NOT NULL,
    is_ironclad TINYINT DEFAULT 0,
    priority INT DEFAULT 0,
    is_active TINYINT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES rule_categories(id) ON DELETE CASCADE,
    INDEX idx_category (category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rule_versions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_id INT NOT NULL,
    version_num INT NOT NULL,
    snapshot JSON NOT NULL,
    created_by VARCHAR(64) DEFAULT 'system',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES rule_categories(id) ON DELETE CASCADE,
    INDEX idx_category_ver (category_id, version_num)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(128) PRIMARY KEY,
    agent_type VARCHAR(32) NOT NULL DEFAULT 'bi',
    user_id VARCHAR(64) DEFAULT 'default',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active TINYINT DEFAULT 1,
    INDEX idx_agent_user (agent_type, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS turns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    turn_index INT NOT NULL,
    user_query TEXT NOT NULL,
    parsed_params JSON NULL,
    executed_sql TEXT NULL,
    result_summary TEXT NULL,
    user_feedback TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    INDEX idx_session_turn (session_id, turn_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS memory_summaries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(128),
    scope VARCHAR(32) DEFAULT 'session',
    summary_type VARCHAR(64) NOT NULL,
    content JSON NOT NULL,
    source_turns VARCHAR(128) NULL,
    embedding_id VARCHAR(64) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def init_db() -> None:
    """Create tables if they don't exist."""
    with _lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                for stmt in SCHEMA_SQL.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        cur.execute(stmt)
            conn.commit()
            logger.info("MySQL database initialized at %s:%s/%s",
                        _config.host, _config.port, _config.database)
        finally:
            conn.close()


# ============================================================
# Rule CRUD (used by rules_engine and admin API)
# ============================================================

def load_rules_from_db() -> dict:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM rule_categories ORDER BY agent_type, priority"
            )
            categories = cur.fetchall()

            result: dict[str, dict] = {}
            for cat in categories:
                cur.execute(
                    """SELECT * FROM rule_items
                       WHERE category_id=%s AND is_active=1
                       ORDER BY priority""",
                    (cat["id"],),
                )
                items = cur.fetchall()

                rules_list = []
                for item in items:
                    rule = item["rule_data"]
                    if isinstance(rule, str):
                        rule = json.loads(rule)
                    keywords = item["keywords"]
                    if isinstance(keywords, str):
                        keywords = json.loads(keywords)
                    rule["keywords"] = keywords
                    if item["is_ironclad"]:
                        rule["_ironclad"] = True
                    rules_list.append(rule)

                if cat["category"] == "special_trade_type":
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
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if agent_type:
                cur.execute(
                    "SELECT * FROM rule_categories WHERE agent_type=%s ORDER BY priority",
                    (agent_type,),
                )
            else:
                cur.execute(
                    "SELECT * FROM rule_categories ORDER BY agent_type, priority"
                )
            return cur.fetchall()
    finally:
        conn.close()


def get_category(category_id: int) -> dict | None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM rule_categories WHERE id=%s", (category_id,)
            )
            return cur.fetchone()
    finally:
        conn.close()


def get_items(category_id: int) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM rule_items WHERE category_id=%s ORDER BY priority",
                (category_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def add_item(category_id: int, keywords: list[str], rule_data: dict,
             is_ironclad: bool = False, priority: int = 0) -> int:
    with _lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO rule_items (category_id, keywords, rule_data, is_ironclad, priority)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (category_id,
                     json.dumps(keywords, ensure_ascii=False),
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
    with _lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT category_id FROM rule_items WHERE id=%s", (item_id,))
                item = cur.fetchone()
                if not item:
                    return False

                sets = []
                params: list = []
                if keywords is not None:
                    sets.append("keywords=%s")
                    params.append(json.dumps(keywords, ensure_ascii=False))
                if rule_data is not None:
                    sets.append("rule_data=%s")
                    params.append(json.dumps(rule_data, ensure_ascii=False))
                if is_ironclad is not None:
                    sets.append("is_ironclad=%s")
                    params.append(1 if is_ironclad else 0)
                if priority is not None:
                    sets.append("priority=%s")
                    params.append(priority)
                if is_active is not None:
                    sets.append("is_active=%s")
                    params.append(1 if is_active else 0)

                if not sets:
                    return False

                sets.append("updated_at=%s")
                params.append(_now())
                params.append(item_id)

                cur.execute(
                    f"UPDATE rule_items SET {', '.join(sets)} WHERE id=%s",
                    params,
                )
                _backup_category(conn, item["category_id"])
                conn.commit()
                return True
        finally:
            conn.close()


def delete_item(item_id: int) -> bool:
    return update_item(item_id, is_active=False)


def _backup_category(conn: pymysql.Connection, category_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM rule_items WHERE category_id=%s ORDER BY priority",
            (category_id,),
        )
        items = cur.fetchall()
        serializable = []
        for r in items:
            d = dict(r)
            for k, v in d.items():
                if isinstance(v, datetime):
                    d[k] = v.strftime("%Y-%m-%d %H:%M:%S")
            serializable.append(d)
        snapshot = json.dumps(serializable, ensure_ascii=False)

        cur.execute(
            "SELECT MAX(version_num) FROM rule_versions WHERE category_id=%s",
            (category_id,),
        )
        latest = cur.fetchone()
        max_ver = list(latest.values())[0] if latest else 0
        next_ver = max_ver + 1

        cur.execute(
            "INSERT INTO rule_versions (category_id, version_num, snapshot) VALUES (%s, %s, %s)",
            (category_id, next_ver, snapshot),
        )


def get_versions(category_id: int) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM rule_versions WHERE category_id=%s ORDER BY version_num DESC LIMIT 50",
                (category_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def rollback_category(category_id: int, version_num: int) -> bool:
    with _lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM rule_versions WHERE category_id=%s AND version_num=%s",
                    (category_id, version_num),
                )
                ver = cur.fetchone()
                if not ver:
                    return False

                snapshot = json.loads(ver["snapshot"])

                cur.execute(
                    "DELETE FROM rule_items WHERE category_id=%s", (category_id,)
                )

                for item in snapshot:
                    cur.execute(
                        """INSERT INTO rule_items
                           (id, category_id, keywords, rule_data, is_ironclad, priority, is_active)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (item["id"], item["category_id"],
                         item["keywords"] if isinstance(item["keywords"], str)
                         else json.dumps(item["keywords"], ensure_ascii=False),
                         item["rule_data"] if isinstance(item["rule_data"], str)
                         else json.dumps(item["rule_data"], ensure_ascii=False),
                         item["is_ironclad"], item.get("priority", 0),
                         item.get("is_active", 1)),
                    )

                conn.commit()
                return True
        finally:
            conn.close()
