"""MySQL store for rules and memory persistence.

Replaces the old SQLite backend with MySQL 8.0.
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
    importance TINYINT DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS audit_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    raw_input TEXT NULL,
    router_decision JSON NULL,
    resolved_params JSON NULL,
    sql_executed TEXT NULL,
    result_rows INT DEFAULT 0,
    result_hash VARCHAR(64) NULL,
    response_to_user TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_request (request_id),
    INDEX idx_session (session_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_memory (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(64) NOT NULL,
    turn_id INTEGER NOT NULL,
    user_query TEXT NOT NULL,
    structured_data JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_agent_memory_session (session_id),
    INDEX idx_agent_memory_turn (session_id, turn_id)
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

                # Migrate: add importance column to existing turns tables
                _migrate_add_column(cur, "turns", "importance",
                                    "ALTER TABLE turns ADD COLUMN importance TINYINT DEFAULT 0")

            conn.commit()
            logger.info("MySQL database initialized at %s:%s/%s",
                        _config.host, _config.port, _config.database)
        finally:
            conn.close()


def _migrate_add_column(cur, table: str, column: str, ddl: str) -> None:
    """Safely add a column if it doesn't exist (MySQL < 8.0.29 compat)."""
    try:
        cur.execute(ddl)
        logger.info("Migration: added column %s to %s", column, table)
    except Exception:
        pass  # Column already exists


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
                cur.execute("SELECT category_id FROM rule_items WHERE id=%s AND is_active=1", (item_id,))
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
        if max_ver is None:
            max_ver = 0
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


# ============================================================
# Session / Memory (used by agent memory layer)
# ============================================================

def create_session(session_id: str, agent_type: str = "bi",
                   user_id: str = "default") -> None:
    with _lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sessions (id, agent_type, user_id, updated_at)
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           agent_type=VALUES(agent_type),
                           user_id=VALUES(user_id),
                           updated_at=VALUES(updated_at)""",
                    (session_id, agent_type, user_id, _now()),
                )
                conn.commit()
        finally:
            conn.close()


def add_turn(session_id: str, turn_index: int, user_query: str,
             parsed_params: dict | None = None, executed_sql: str | None = None,
             result_summary: str | None = None, user_feedback: str | None = None,
             importance: int = 0) -> int:
    with _lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO turns (session_id, turn_index, user_query,
                       parsed_params, executed_sql, result_summary, user_feedback, importance)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (session_id, turn_index, user_query,
                     json.dumps(parsed_params, ensure_ascii=False) if parsed_params else None,
                     executed_sql, result_summary, user_feedback, importance),
                )
                cur.execute(
                    "UPDATE sessions SET updated_at=%s WHERE id=%s",
                    (_now(), session_id),
                )
                conn.commit()
                return cur.lastrowid
        finally:
            conn.close()


def get_session_context(session_id: str, last_n: int = 3) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM turns WHERE session_id=%s
                   ORDER BY turn_index DESC LIMIT %s""",
                (session_id, last_n),
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if isinstance(d.get("parsed_params"), str):
                    d["parsed_params"] = json.loads(d["parsed_params"])
                result.append(d)
            return list(reversed(result))
    finally:
        conn.close()


def add_summary(session_id: str, summary_type: str, content: dict,
                source_turns: str | None = None) -> int:
    with _lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO memory_summaries (session_id, summary_type, content, source_turns)
                       VALUES (%s, %s, %s, %s)""",
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


def _ensure_category(conn, agent_type: str, category: str, display_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT IGNORE INTO rule_categories (agent_type, category, display_name)
               VALUES (%s, %s, %s)""",
            (agent_type, category, display_name),
        )
        cur.execute(
            "SELECT id FROM rule_categories WHERE agent_type=%s AND category=%s",
            (agent_type, category),
        )
        return cur.fetchone()["id"]


def _insert_rules(conn, category_id: int, rules: list, sub_type: str | None = None) -> int:
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

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO rule_items (category_id, keywords, rule_data, is_ironclad)
                   VALUES (%s, %s, %s, %s)""",
                (category_id, json.dumps(keywords, ensure_ascii=False),
                 json.dumps(rule_data, ensure_ascii=False),
                 1 if is_ironclad else 0),
            )
        n += 1
    return n


def migrate_from_json(rules_path: str | None = None) -> int:
    if rules_path is None:
        rules_path = str(
            Path(__file__).resolve().parent.parent / "knowledge_base" / "semantic_rules.json"
        )

    with open(rules_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    init_db()
    count = 0

    CATEGORY_MAP: dict[str, tuple[str, str, str, str | None]] = {
        "app_id":               ("app_id",               "产品类型映射",     "common", None),
        "buy_sell_direction":    ("buy_sell_direction",    "买卖方向映射",     "common", None),
        "product_type":          ("product_type",          "交易类型映射",     "common", None),
        "special_states":        ("special_trade_type",    "特殊交易类型映射", "common", "state"),
        "trade_class":           ("special_trade_type",    "特殊交易类型映射", "common", "class"),
        "time_expressions":      ("time_expressions",      "时间表达式映射",   "common", None),
        "dimension_labels":      ("dimension_labels",      "维度标签配置",     "common", None),
    }
    BI_CATEGORIES = {"comparison_modifiers"}

    with _lock:
        conn = get_conn()
        try:
            for category_key, category_val in data.items():
                if category_key.startswith("_"):
                    continue

                if category_key in CATEGORY_MAP:
                    (cat_key, display_name, agent_type, sub_type) = CATEGORY_MAP[category_key]
                    rules_list = category_val.get("rules", [])
                    if not rules_list:
                        continue
                    cat_id = _ensure_category(conn, agent_type, cat_key, display_name)
                    count += _insert_rules(conn, cat_id, rules_list, sub_type)

                if isinstance(category_val, dict) and category_key == "time_expressions":
                    for nested_key, nested_val in category_val.items():
                        if nested_key in BI_CATEGORIES and isinstance(nested_val, dict) and "rules" in nested_val:
                            display_name = nested_val.get("_description", nested_key)
                            cat_id = _ensure_category(conn, "bi", nested_key, display_name)
                            count += _insert_rules(conn, cat_id, nested_val["rules"])

            conn.commit()
            logger.info("Migrated %d rules from %s to MySQL", count, rules_path)
            return count
        finally:
            conn.close()


def save_agent_memory(session_id: str, turn_id: int, user_query: str,
                      structured_data: dict) -> int:
    """Save an agent memory turn."""
    with _lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_memory (session_id, turn_id, user_query, structured_data)
                       VALUES (%s, %s, %s, %s)""",
                    (session_id, turn_id, user_query,
                     json.dumps(structured_data, ensure_ascii=False) if structured_data else None),
                )
                conn.commit()
                return cur.lastrowid
        except pymysql.err.ProgrammingError:
            logger.warning("agent_memory table does not exist, skipping save")
            return 0
        finally:
            conn.close()


def get_agent_memory(session_id: str, last_n: int = 5) -> list[dict]:
    """Get recent agent memory turns."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM agent_memory WHERE session_id=%s
                   ORDER BY turn_id DESC LIMIT %s""",
                (session_id, last_n),
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if isinstance(d.get("structured_data"), str):
                    d["structured_data"] = json.loads(d["structured_data"])
                result.append(d)
            return list(reversed(result))
    except pymysql.err.ProgrammingError:
        logger.warning("agent_memory table does not exist, returning empty")
        return []
    finally:
        conn.close()


def load_dimension_labels_from_db() -> dict | None:
    """Load dimension labels config from DB rules.

    Returns dict with keys:
      - dimensions: {dim_key: {display_label, count_unit, sql_select_col,
                               sql_group_col, join_clause, label_col_names}}
      - comparison_labels: {yoy: "同比", ...}
      - amount_col_names: set of column name strings
      - label_col_names: set of all label column names (union)
    """
    init_db()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM rule_categories WHERE category=%s AND agent_type=%s",
                ("dimension_labels", "common"),
            )
            cat = cur.fetchone()
            if not cat:
                return None

            cur.execute(
                "SELECT keywords, rule_data FROM rule_items WHERE category_id=%s AND is_active=1",
                (cat["id"],),
            )
            items = cur.fetchall()

        dim_config = {}
        comparison_labels = None
        amount_col_names = None
        all_label_cols = set()

        for item in items:
            rd = item["rule_data"]
            if isinstance(rd, str):
                rd = json.loads(rd)
            kw = item["keywords"]
            if isinstance(kw, str):
                kw = json.loads(kw)

            dim_key = kw[0] if kw else None
            if dim_key == "_meta":
                comparison_labels = rd.get("comparison_labels", {})
                amount_col_names = set(rd.get("amount_col_names", []))
            elif dim_key:
                dim_config[dim_key] = {
                    "display_label": rd.get("display_label", dim_key),
                    "count_unit": rd.get("count_unit", "个"),
                    "sql_select_col": rd.get("sql_select_col", ""),
                    "sql_group_col": rd.get("sql_group_col", ""),
                    "join_clause": rd.get("join_clause", ""),
                    "label_col_names": rd.get("label_col_names", []),
                }
                for col in rd.get("label_col_names", []):
                    all_label_cols.add(col.upper())

        if not dim_config:
            return None

        return {
            "dimensions": dim_config,
            "comparison_labels": comparison_labels or {},
            "amount_col_names": amount_col_names or set(),
            "label_col_names": all_label_cols,
        }
    finally:
        conn.close()


def _seed_dimension_labels_if_missing() -> None:
    """Idempotently seed dimension_labels category if not present."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM rule_categories WHERE category=%s AND agent_type=%s",
                ("dimension_labels", "common"),
            )
            if cur.fetchone():
                return

        rules_path = str(
            Path(__file__).resolve().parent.parent / "knowledge_base" / "semantic_rules.json"
        )
        with open(rules_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        dim_data = data.get("dimension_labels")
        if not dim_data or "rules" not in dim_data:
            logger.warning("dimension_labels not found in semantic_rules.json, skipping")
            return

        rules_list = dim_data["rules"]
        cat_id = _ensure_category(conn, "common", "dimension_labels", "维度标签配置")
        _insert_rules(conn, cat_id, rules_list)
        conn.commit()
        logger.info("Seeded dimension_labels category with %d items", len(rules_list))
    finally:
        conn.close()


def _auto_migrate() -> None:
    init_db()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM rule_items")
            cnt = cur.fetchone()["cnt"]
        if cnt == 0:
            logger.info("MySQL rule store is empty, running auto-migration...")
            migrate_from_json()
        else:
            _seed_dimension_labels_if_missing()
    finally:
        conn.close()


