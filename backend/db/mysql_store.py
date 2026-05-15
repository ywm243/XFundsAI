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
