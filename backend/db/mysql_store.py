"""MySQL store for rules and memory persistence.

Replaces the old SQLite backend with MySQL 8.0.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

import pymysql
from dbutils.pooled_db import PooledDB
from pymysql.cursors import DictCursor

from db.config import MySQLConfig

logger = logging.getLogger(__name__)

_config = MySQLConfig()
_lock = threading.Lock()

_pool: PooledDB | None = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get_pool() -> PooledDB:
    """Lazily create the MySQL connection pool."""
    global _pool
    if _pool is None:
        _pool = PooledDB(
            creator=pymysql,
            maxconnections=10,
            mincached=2,
            cursorclass=DictCursor,
            autocommit=False,
            **_config.dsn,
        )
    return _pool


def get_conn() -> pymysql.Connection:
    """Get a connection from the pool."""
    return _get_pool().connection()


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

CREATE TABLE IF NOT EXISTS pricing_sessions (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    status VARCHAR(20) DEFAULT 'IDLE',
    intent_type VARCHAR(20),
    inquiry_params JSON,
    quote_results JSON,
    quote_id VARCHAR(64),
    valid_until DATETIME,
    trade_result JSON,
    trade_error JSON,
    customer_id VARCHAR(64) DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_session (session_id),
    INDEX idx_status (status),
    INDEX idx_valid (valid_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pricing_audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    pricing_id VARCHAR(36) NOT NULL,
    action VARCHAR(32) NOT NULL,
    actor VARCHAR(32) NOT NULL DEFAULT 'CUSTOMER',
    detail JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_pricing (pricing_id),
    INDEX idx_time (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wiki_pages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    slug VARCHAR(128) NOT NULL,
    title VARCHAR(256) NOT NULL,
    page_type ENUM('concept','entity','reference','synthesis','source','stub') NOT NULL DEFAULT 'concept',
    body MEDIUMTEXT NOT NULL,
    frontmatter JSON NULL,
    sources JSON NULL,
    tags JSON NULL,
    confidence FLOAT NULL,
    reliability ENUM('high','mixed','unverified') NULL,
    parent_slug VARCHAR(128) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_slug (slug),
    INDEX idx_type (page_type),
    INDEX idx_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS token_usage_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL DEFAULT '',
    session_id VARCHAR(128) NOT NULL DEFAULT '',
    call_site VARCHAR(32) NOT NULL DEFAULT '' COMMENT '调用点: bi_parse/context_resolve/llm_chat/...',
    model_tier VARCHAR(8) NOT NULL DEFAULT '' COMMENT 'flash / pro',
    model_name VARCHAR(64) NOT NULL DEFAULT '',
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL DEFAULT 0,
    duration_ms FLOAT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_session_id (session_id),
    INDEX idx_call_site (call_site),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS request_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL DEFAULT '',
    method VARCHAR(8) NOT NULL DEFAULT '',
    path VARCHAR(256) NOT NULL DEFAULT '',
    status_code INT NOT NULL DEFAULT 0,
    duration_ms FLOAT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS error_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL DEFAULT '',
    method VARCHAR(8) NOT NULL DEFAULT '',
    path VARCHAR(256) NOT NULL DEFAULT '',
    error_type VARCHAR(64) NOT NULL DEFAULT '',
    error_message TEXT,
    traceback TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_error_type (error_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    thread_id VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(64) NOT NULL DEFAULT '',
    parent_id VARCHAR(64) NOT NULL DEFAULT '',
    data JSON,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_thread (thread_id, checkpoint_ns, checkpoint_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS api_keys (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    key_hash VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'SHA-256 of API key',
    permissions JSON COMMENT '["bi","pricing","admin"]',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME DEFAULT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    INDEX idx_key_hash (key_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tool_calls_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    tool_name VARCHAR(64) NOT NULL DEFAULT '',
    duration_ms FLOAT NOT NULL DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_type VARCHAR(64) NOT NULL DEFAULT '',
    session_id VARCHAR(128) NOT NULL DEFAULT '',
    request_id VARCHAR(64) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tool_name (tool_name),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS evaluation_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL DEFAULT '',
    session_id VARCHAR(128) NOT NULL DEFAULT '',
    agent_type VARCHAR(16) NOT NULL DEFAULT '' COMMENT 'BI/PRICING/ANALYSIS',
    router_confidence FLOAT NOT NULL DEFAULT 0,
    parse_confidence FLOAT NOT NULL DEFAULT 0,
    post_validation_mismatches JSON COMMENT '数字不匹配列表',
    sql_validated BOOLEAN NOT NULL DEFAULT TRUE,
    validation_warnings_count INT NOT NULL DEFAULT 0,
    total_duration_ms FLOAT NOT NULL DEFAULT 0,
    wiki_hit BOOLEAN NOT NULL DEFAULT FALSE,
    errors_count INT NOT NULL DEFAULT 0,
    fatal_errors INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session_id (session_id),
    INDEX idx_agent_type (agent_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
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

                # Migrate: compliance fields for pricing_sessions (Task 27)
                _migrate_add_column(cur, "pricing_sessions", "last_activity",
                                    "ALTER TABLE pricing_sessions ADD COLUMN last_activity DATETIME DEFAULT NULL")

                # Migrate: compliance audit fields for pricing_audit_log (Task 27)
                _migrate_add_column(cur, "pricing_audit_log", "engine_raw_response",
                                    "ALTER TABLE pricing_audit_log ADD COLUMN engine_raw_response JSON")
                _migrate_add_column(cur, "pricing_audit_log", "llm_decision_steps",
                                    "ALTER TABLE pricing_audit_log ADD COLUMN llm_decision_steps JSON")
                _migrate_add_column(cur, "pricing_audit_log", "evidence_hash",
                                    "ALTER TABLE pricing_audit_log ADD COLUMN evidence_hash VARCHAR(64)")
                _migrate_add_column(cur, "pricing_audit_log", "evidence_type",
                                    "ALTER TABLE pricing_audit_log ADD COLUMN evidence_type VARCHAR(32)")

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


def get_summaries(session_id: str, last_n: int = 10) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM memory_summaries WHERE session_id=%s
                   ORDER BY created_at DESC LIMIT %s""",
                (session_id, last_n),
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if isinstance(d.get("content"), str):
                    d["content"] = json.loads(d["content"])
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
        "lifecycle_status":      ("lifecycle_status",      "交易生命周期状态", "common", None),
        "profit_type":           ("profit_type",           "利润类型映射",     "common", None),
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


def _seed_lifecycle_status_if_missing() -> None:
    """Idempotently seed lifecycle_status category if not present."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM rule_categories WHERE category=%s AND agent_type=%s",
                ("lifecycle_status", "common"),
            )
            if cur.fetchone():
                return

        rules_path = str(
            Path(__file__).resolve().parent.parent / "knowledge_base" / "semantic_rules.json"
        )
        with open(rules_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        lc_data = data.get("lifecycle_status")
        if not lc_data or "rules" not in lc_data:
            logger.warning("lifecycle_status not found in semantic_rules.json, skipping")
            return

        rules_list = lc_data["rules"]
        cat_id = _ensure_category(conn, "common", "lifecycle_status", "交易生命周期状态")
        _insert_rules(conn, cat_id, rules_list)
        conn.commit()
        logger.info("Seeded lifecycle_status category with %d items", len(rules_list))
    finally:
        conn.close()


def _seed_profit_type_if_missing() -> None:
    """Idempotently seed profit_type category if not present."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM rule_categories WHERE category=%s AND agent_type=%s",
                ("profit_type", "common"),
            )
            if cur.fetchone():
                return

        rules_path = str(
            Path(__file__).resolve().parent.parent / "knowledge_base" / "semantic_rules.json"
        )
        with open(rules_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        pt_data = data.get("profit_type")
        if not pt_data or "rules" not in pt_data:
            logger.warning("profit_type not found in semantic_rules.json, skipping")
            return

        rules_list = pt_data["rules"]
        cat_id = _ensure_category(conn, "common", "profit_type", "利润类型映射")
        _insert_rules(conn, cat_id, rules_list)
        conn.commit()
        logger.info("Seeded profit_type category with %d items", len(rules_list))
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
            _seed_lifecycle_status_if_missing()
            _seed_profit_type_if_missing()
    finally:
        conn.close()


# ============================================================
# Pricing session / audit (used by quoting agent)
# ============================================================

def save_pricing_session(record: dict) -> None:
    """保存/更新询报价会话"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO pricing_sessions
                   (id, session_id, status, intent_type, inquiry_params,
                    quote_results, quote_id, valid_until, trade_result,
                    trade_error, customer_id, last_activity)
                   VALUES (%(id)s, %(session_id)s, %(status)s, %(intent_type)s,
                           %(inquiry_params)s, %(quote_results)s, %(quote_id)s,
                           %(valid_until)s, %(trade_result)s, %(trade_error)s,
                           %(customer_id)s, %(last_activity)s)
                   ON DUPLICATE KEY UPDATE
                     status=VALUES(status),
                     quote_results=VALUES(quote_results),
                     quote_id=VALUES(quote_id),
                     valid_until=VALUES(valid_until),
                     trade_result=VALUES(trade_result),
                     trade_error=VALUES(trade_error),
                     last_activity=VALUES(last_activity),
                     updated_at=CURRENT_TIMESTAMP""",
                record
            )
        conn.commit()
    finally:
        conn.close()


def get_pricing_session(pricing_id: str) -> dict | None:
    """查询询报价会话"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM pricing_sessions WHERE id = %s",
                (pricing_id,)
            )
            row = cur.fetchone()
            return row if row else None
    finally:
        conn.close()


def get_active_pricing_session(session_id: str) -> dict | None:
    """查询当前活跃的询报价会话（QUOTING/QUOTED状态且未过期）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM pricing_sessions
                   WHERE session_id = %s
                   AND status IN ('QUOTING', 'QUOTED')
                   AND (valid_until IS NULL OR valid_until > NOW())
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id,)
            )
            row = cur.fetchone()
            return row if row else None
    finally:
        conn.close()


def add_pricing_audit(pricing_id: str, action: str, detail: dict,
                      actor: str = "CUSTOMER",
                      engine_raw: dict | None = None,
                      llm_steps: list | None = None,
                      evidence_hash: str = "",
                      evidence_type: str = "") -> None:
    """写入合规审计日志"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO pricing_audit_log (pricing_id, action, actor, detail,
                   engine_raw_response, llm_decision_steps, evidence_hash, evidence_type)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (pricing_id, action, actor,
                 json.dumps(detail, ensure_ascii=False),
                 json.dumps(engine_raw, ensure_ascii=False) if engine_raw else None,
                 json.dumps(llm_steps, ensure_ascii=False) if llm_steps else None,
                 evidence_hash, evidence_type)
            )
        conn.commit()
    finally:
        conn.close()


# ---- Wiki pages ----

def save_wiki_page(slug: str, title: str, page_type: str, body: str,
                   frontmatter: dict | None = None, sources: list | None = None,
                   tags: list | None = None, confidence: float | None = None,
                   reliability: str | None = None, parent_slug: str | None = None) -> int:
    """Insert or update a wiki page. Returns page id."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO wiki_pages (slug, title, page_type, body, frontmatter, sources, tags, confidence, reliability, parent_slug)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title=VALUES(title), page_type=VALUES(page_type), body=VALUES(body),
                    frontmatter=VALUES(frontmatter), sources=VALUES(sources), tags=VALUES(tags),
                    confidence=VALUES(confidence), reliability=VALUES(reliability),
                    parent_slug=VALUES(parent_slug), updated_at=NOW()
            """, (slug, title, page_type, body,
                  json.dumps(frontmatter, ensure_ascii=False) if frontmatter else None,
                  json.dumps(sources, ensure_ascii=False) if sources else None,
                  json.dumps(tags, ensure_ascii=False) if tags else None,
                  confidence, reliability, parent_slug))
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM wiki_pages WHERE slug=%s", (slug,))
            return cur.fetchone()["id"]
    finally:
        conn.close()


def get_wiki_page(slug: str) -> dict | None:
    """Get a wiki page by slug."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM wiki_pages WHERE slug=%s", (slug,))
            return cur.fetchone()
    finally:
        conn.close()


def query_wiki_pages(page_type: str | None = None, tag: str | None = None,
                     keyword: str | None = None, limit: int = 20) -> list[dict]:
    """Search wiki pages by type, tag, or keyword in title/body."""
    conn = get_conn()
    try:
        conditions, params = [], []
        if page_type:
            conditions.append("page_type=%s")
            params.append(page_type)
        if tag:
            conditions.append("JSON_CONTAINS(tags, %s)")
            params.append(json.dumps(tag))
        if keyword:
            conditions.append("(title LIKE %s OR body LIKE %s)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        where = " AND ".join(conditions) if conditions else "1=1"
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM wiki_pages WHERE {where} ORDER BY updated_at DESC LIMIT %s", params + [limit])
            return cur.fetchall()
    finally:
        conn.close()


def delete_wiki_page(slug: str) -> bool:
    """Delete a wiki page by slug. Returns True if deleted."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wiki_pages WHERE slug=%s", (slug,))
            deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


# ============================================================
# Token usage tracking (Phase 0 — observability)
# ============================================================

def insert_token_usage(request_id: str, session_id: str, call_site: str,
                       model_tier: str, model_name: str,
                       prompt_tokens: int, completion_tokens: int,
                       total_tokens: int, duration_ms: float) -> int:
    conn = get_conn()
    try:
        sql = """INSERT INTO token_usage_log (request_id, session_id, call_site,
                  model_tier, model_name, prompt_tokens, completion_tokens,
                  total_tokens, duration_ms)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        with conn.cursor() as cur:
            cur.execute(sql, (request_id, session_id, call_site, model_tier,
                             model_name, prompt_tokens, completion_tokens,
                             total_tokens, duration_ms))
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()


def query_token_usage(call_site: str = None, session_id: str = None,
                      window_hours: int = 24) -> list[dict]:
    """聚合查询 token 使用数据"""
    conn = get_conn()
    try:
        where = ["created_at >= NOW() - INTERVAL %s HOUR"]
        params = [window_hours]
        if call_site:
            where.append("call_site = %s")
            params.append(call_site)
        if session_id:
            where.append("session_id = %s")
            params.append(session_id)
        sql = f"""SELECT call_site, model_tier,
                         SUM(total_tokens) AS total_tokens,
                         COUNT(*) AS call_count,
                         AVG(duration_ms) AS avg_duration_ms
                  FROM token_usage_log
                  WHERE {' AND '.join(where)}
                  GROUP BY call_site, model_tier
                  ORDER BY total_tokens DESC"""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
    finally:
        conn.close()


# ============================================================
# Request / Error logging (Phase 0 — middleware observability)
# ============================================================


def insert_request_log(request_id: str, method: str, path: str,
                       status_code: int, duration_ms: float) -> int:
    conn = get_conn()
    try:
        sql = """INSERT INTO request_log (request_id, method, path, status_code, duration_ms)
                 VALUES (%s, %s, %s, %s, %s)"""
        with conn.cursor() as cur:
            cur.execute(sql, (request_id, method, path, status_code, duration_ms))
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()


def insert_error_log(request_id: str, method: str, path: str,
                     error_type: str, error_message: str, traceback: str) -> int:
    conn = get_conn()
    try:
        sql = """INSERT INTO error_log (request_id, method, path, error_type, error_message, traceback)
                 VALUES (%s, %s, %s, %s, %s, %s)"""
        with conn.cursor() as cur:
            cur.execute(sql, (request_id, method, path, error_type, error_message, traceback))
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()


def insert_evaluation_record(record: dict) -> int:
    """Insert an evaluation record after each LangGraph execution."""
    conn = get_conn()
    try:
        sql = """INSERT INTO evaluation_records
                 (request_id, session_id, agent_type, router_confidence,
                  parse_confidence, post_validation_mismatches, sql_validated,
                  validation_warnings_count, total_duration_ms, wiki_hit,
                  errors_count, fatal_errors)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        with conn.cursor() as cur:
            import json
            cur.execute(sql, (
                record["request_id"], record["session_id"], record["agent_type"],
                record["router_confidence"], record["parse_confidence"],
                json.dumps(record.get("post_validation_mismatches", [])),
                record.get("sql_validated", True), record.get("validation_warnings_count", 0),
                record.get("total_duration_ms", 0), record.get("wiki_hit", False),
                record.get("errors_count", 0), record.get("fatal_errors", 0),
            ))
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()


def query_evaluation_metrics(window_hours: int = 24, agent_type: str = None) -> list[dict]:
    """Aggregate evaluation metrics over a time window, optionally filtered by agent_type."""
    conn = get_conn()
    try:
        where = ["created_at >= NOW() - INTERVAL %s HOUR"]
        params = [window_hours]
        if agent_type:
            where.append("agent_type = %s")
            params.append(agent_type)
        sql = f"""SELECT agent_type,
                         COUNT(*) AS total_requests,
                         AVG(router_confidence) AS avg_router_conf,
                         AVG(parse_confidence) AS avg_parse_conf,
                         AVG(total_duration_ms) AS avg_duration_ms,
                         SUM(CASE WHEN wiki_hit THEN 1 ELSE 0 END) / COUNT(*) AS wiki_hit_rate,
                         SUM(CASE WHEN fatal_errors > 0 THEN 1 ELSE 0 END) / COUNT(*) AS error_rate
                  FROM evaluation_records
                  WHERE {' AND '.join(where)}
                  GROUP BY agent_type"""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    finally:
        conn.close()