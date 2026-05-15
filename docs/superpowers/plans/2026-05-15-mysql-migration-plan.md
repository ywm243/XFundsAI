# MySQL 迁移实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Agent Memory 和规则引擎从 SQLite 完全迁移至本地 MySQL，保持上层业务代码不变。

**Architecture:** 删除 `sqlite_store.py`，新建 `mysql_store.py` 提供完全相同的函数签名。MySQL 通过 Docker 运行，`pymysql` 作为驱动（纯 Python，无 C 依赖）。`config.py` 新增 MySQLConfig 读取环境变量。

**Tech Stack:** Python 3.13 + PyMySQL 1.4 + MySQL 8.0 (Docker) + oracledb（不变）

---

### Task 1: MySQL 安装（Docker）

**Files:** 无（基础设施）

- [ ] **Step 1: 启动 MySQL Docker 容器**

```bash
docker run -d \
  --name smartbi-mysql \
  -e MYSQL_ROOT_PASSWORD=smartbi123 \
  -e MYSQL_DATABASE=smartbi \
  -p 3306:3306 \
  mysql:8.0 \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_unicode_ci
```

- [ ] **Step 2: 等待 MySQL 就绪**

```bash
echo "Waiting for MySQL to be ready..."
for i in $(seq 1 30); do
  if docker exec smartbi-mysql mysqladmin ping -uroot -psmartbi123 --silent 2>/dev/null; then
    echo "MySQL is ready (attempt $i)"
    break
  fi
  sleep 2
done
```

- [ ] **Step 3: 验证连接**

```bash
docker exec smartbi-mysql mysql -uroot -psmartbi123 -e "SELECT VERSION() AS version, @@character_set_database AS charset, @@collation_database AS collation;"
```

预期输出:
```
version  charset  collation
8.0.x   utf8mb4  utf8mb4_unicode_ci
```

- [ ] **Step 4: 提交（环境就绪记录）**

```bash
git add -A && git commit -m "chore: 启动 MySQL 8.0 Docker 容器，数据库 smartbi"
```

---

### Task 2: 安装 Python 驱动

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: 更新 requirements.txt**

在 `backend/requirements.txt` 末尾新增一行：

```text
pymysql>=1.4.0
```

> 选 PyMySQL 而非 mysql-connector-python：更轻量（单文件 ~100KB vs ~30MB），纯 Python 无 C 扩展，与 oracledb 同为 Python 原生驱动。MySQL 8.0 完全兼容。

- [ ] **Step 2: 安装依赖**

```bash
cd backend && pip install pymysql>=1.4.0
```

- [ ] **Step 3: 验证安装**

```bash
python -c "import pymysql; print('PyMySQL', pymysql.__version__)"
```

预期输出: `PyMySQL 1.4.x`

- [ ] **Step 4: 提交**

```bash
git add backend/requirements.txt && git commit -m "chore: 添加 PyMySQL 依赖"
```

---

### Task 3: 新增 MySQL 配置

**Files:**
- Modify: `backend/db/config.py`

- [ ] **Step 1: 扩展 config.py**

在 `DBConfig` 类后新增 `MySQLConfig` 类。

```python
import os


class DBConfig:
    host = os.environ.get("DB_HOST", "localhost")
    port = int(os.environ.get("DB_PORT", "1521"))
    service = os.environ.get("DB_SERVICE", "orclutf")
    user = os.environ.get("DB_USER", "")
    password = os.environ.get("DB_PASSWORD", "")

    @property
    def dsn(self) -> str:
        return f"{self.host}:{self.port}/{self.service}"


class MySQLConfig:
    host = os.environ.get("MYSQL_HOST", "localhost")
    port = int(os.environ.get("MYSQL_PORT", "3306"))
    user = os.environ.get("MYSQL_USER", "root")
    password = os.environ.get("MYSQL_PASSWORD", "smartbi123")
    database = os.environ.get("MYSQL_DATABASE", "smartbi")

    @property
    def dsn(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": "utf8mb4",
        }
```

- [ ] **Step 2: 创建 .env 配置**

追加到项目根目录 `.env`：

```bash
# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=smartbi123
MYSQL_DATABASE=smartbi
```

- [ ] **Step 3: 验证配置加载**

```bash
cd backend && python -c "from db.config import MySQLConfig; c=MySQLConfig(); print(c.dsn)"
```

预期输出: `{'host': 'localhost', 'port': 3306, 'user': 'root', 'password': 'smartbi123', 'database': 'smartbi', 'charset': 'utf8mb4'}`

- [ ] **Step 4: 提交**

```bash
git add backend/db/config.py .env && git commit -m "feat(config): 新增 MySQLConfig 配置类"
```

---

### Task 4: 新建 mysql_store.py（建表）

**Files:**
- Create: `backend/db/mysql_store.py`

- [ ] **Step 1: 编写建表模块骨架**

```python
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
            for stmt in SCHEMA_SQL.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.cursor().execute(stmt)
            conn.commit()
            logger.info("MySQL database initialized at %s:%s/%s",
                        _config.host, _config.port, _config.database)
        finally:
            conn.close()
```

- [ ] **Step 2: 执行建表验证**

```bash
cd backend && python -c "from db.mysql_store import init_db; init_db(); print('Tables created')"
```

- [ ] **Step 3: 验证表结构**

```bash
docker exec smartbi-mysql mysql -uroot -psmartbi123 smartbi -e "SHOW TABLES;"
```

预期输出: 6 张表 (rule_categories, rule_items, rule_versions, sessions, turns, memory_summaries)

- [ ] **Step 4: 提交**

```bash
git add backend/db/mysql_store.py && git commit -m "feat(db): MySQL store 建表模块"
```

---

### Task 5: 规则 CRUD 方法（mysql_store.py）

**Files:**
- Modify: `backend/db/mysql_store.py`

- [ ] **Step 1: 追加规则 CRUD 方法**

在 `mysql_store.py` 中追加以下方法：

```python
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
        # Convert datetime objects to strings for JSON serialization
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
```

- [ ] **Step 2: 验证规则 CRUD 基本操作**

```bash
cd backend && python -c "
from db.mysql_store import init_db, get_categories, get_items, add_item
init_db()
cats = get_categories()
print(f'Categories: {len(cats)}')
for c in cats:
    items = get_items(c['id'])
    print(f'  {c[\"category\"]}: {len(items)} items')
"
```

- [ ] **Step 3: 提交**

```bash
git add backend/db/mysql_store.py && git commit -m "feat(db): MySQL 规则 CRUD 方法"
```

---

### Task 6: Session/Memory 方法 + 自动迁移（mysql_store.py）

**Files:**
- Modify: `backend/db/mysql_store.py`

- [ ] **Step 1: 追加 Session/Memory 方法 + 迁移**

```python
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
             result_summary: str | None = None, user_feedback: str | None = None) -> int:
    with _lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO turns (session_id, turn_index, user_query,
                       parsed_params, executed_sql, result_summary, user_feedback)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (session_id, turn_index, user_query,
                     json.dumps(parsed_params, ensure_ascii=False) if parsed_params else None,
                     executed_sql, result_summary, user_feedback),
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
            # DictCursor already returns dicts, just reverse
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
    }
    BI_CATEGORIES = {"comparison_modifiers"}

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
    finally:
        conn.close()


_auto_migrate()
```

- [ ] **Step 2: 执行自动迁移并验证**

```bash
cd backend && python -c "
from db.mysql_store import get_categories, get_items, create_session, add_turn, get_session_context
cats = get_categories()
print(f'Categories after migration: {len(cats)}')
# Should be > 0 if semantic_rules.json exists
for c in cats:
    items = get_items(c['id'])
    print(f'  {c[\"category\"]}: {len(items)} items')

# Test session
create_session('test-s1', 'bi', 'default')
add_turn('test-s1', 0, '本月交易量', {'product_type': 'all'})
ctx = get_session_context('test-s1')
print(f'Context: {len(ctx)} turns')
print(f'Query: {ctx[0][\"user_query\"]}')
"
```

- [ ] **Step 3: 提交**

```bash
git add backend/db/mysql_store.py && git commit -m "feat(db): MySQL session/memory 方法与自动迁移"
```

---

### Task 7: 批量更新 import 路径

**Files:**
- Modify: `backend/memory/store.py`
- Modify: `backend/llm_parser/rules_engine.py`
- Modify: `backend/llm_parser/prompt_builder.py`
- Modify: `backend/admin_routes.py`

- [ ] **Step 1: 查找并替换所有 import**

当前所有文件都从 `db.sqlite_store` 导入。需要改为 `db.mysql_store`。

```bash
cd backend && grep -rn "sqlite_store" --include="*.py" .
```

预期找到的文件:
- `memory/store.py:10:from db import sqlite_store`
- `llm_parser/rules_engine.py:  from db import sqlite_store`
- `llm_parser/prompt_builder.py:  from db import sqlite_store`
- `admin_routes.py:  from db import sqlite_store`

逐一修改每个文件的 import 行：

**memory/store.py:10** — 将 `from db import sqlite_store` 改为 `from db import mysql_store`，同时将函数调用 `sqlite_store.xxx` 改为 `mysql_store.xxx`。

**llm_parser/rules_engine.py** — 同样将 `sqlite_store` → `mysql_store`

**llm_parser/prompt_builder.py** — 同样将 `sqlite_store` → `mysql_store`

**admin_routes.py** — 同样将 `sqlite_store` → `mysql_store`

- [ ] **Step 2: 逐文件修改并验证导入**

```bash
# 验证所有文件能正常 import
cd backend && python -c "
from memory.store import AgentMemory
from llm_parser.rules_engine import gatekeep
from llm_parser.prompt_builder import build_system_prompt
from admin_routes import router
print('All imports OK')
"
```

- [ ] **Step 3: 提交**

```bash
git add backend/memory/store.py backend/llm_parser/rules_engine.py backend/llm_parser/prompt_builder.py backend/admin_routes.py
git commit -m "refactor: 批量替换 sqlite_store → mysql_store import"
```

---

### Task 8: 清理 SQLite 残留

**Files:**
- Delete: `backend/db/sqlite_store.py`
- Delete: `backend/data/smartbi.db`（如果存在）

- [ ] **Step 1: 删除 SQLite 文件**

```bash
rm -f backend/db/sqlite_store.py
rm -f backend/data/smartbi.db
# 如果 data 目录为空也删除（_auto_migrate 中会重建）
rmdir backend/data 2>/dev/null || true
```

- [ ] **Step 2: 确认无残留引用**

```bash
cd backend && grep -rn "sqlite" --include="*.py" .
```

预期输出: 空（无匹配）

- [ ] **Step 3: 提交**

```bash
git rm backend/db/sqlite_store.py
git rm -f backend/data/smartbi.db 2>/dev/null || true
git commit -m "chore: 删除 sqlite_store.py 和 smartbi.db"
```

---

### Task 9: 端到端验证

**Files:** 无（验证）

- [ ] **Step 1: 启动后端服务**

```bash
cd backend && uvicorn app:app --host 0.0.0.0 --port 8000 &
sleep 3
```

- [ ] **Step 2: 健康检查**

```bash
curl -s http://localhost:8000/api/health
```

预期: `{"status":"ok"}`

- [ ] **Step 3: 查询验证（数据类）**

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"text": "本月交易量"}'
```

预期: 返回包含 `summary`, `chartOption`, `insights`, `comparison` 的 JSON

- [ ] **Step 4: Admin API 验证**

```bash
curl -s http://localhost:8000/api/admin/rules/categories
```

预期: 返回规则分类列表（>0 条）

- [ ] **Step 5: 解析验证**

```bash
curl -s -X POST http://localhost:8000/api/parse \
  -H "Content-Type: application/json" \
  -d '{"text": "本月工商银行交易量"}'
```

预期: `pipeline` 字段为 `"rule(confidence=XX%)"`，`params` 包含 `bank_name: "工商银行"`

- [ ] **Step 6: 停止后端**

```bash
pkill -f "uvicorn app:app"
```

- [ ] **Step 7: 运行验收断言（按 CLAUDE.md 规范）**

```bash
python -c "import requests; r=requests.post('http://localhost:8000/api/query',json={'text':'本月交易量'}); d=r.json(); assert all(k in d for k in ['summary','chartOption','insights','comparison']), f'Missing: {[k for k in ['summary','chartOption','insights','comparison'] if k not in d]}'; print('PASS')"
```

预期: `PASS`

- [ ] **Step 8: 提交**

```bash
git commit --allow-empty -m "test: MySQL 迁移端到端验证通过"
```

---

## 任务依赖图

```
Task 1 (MySQL Docker) ──┬──> Task 3 (config) ──> Task 4 (建表) ──> Task 5 (规则 CRUD)
                        │                                                    │
                        └──> Task 2 (PyMySQL) ───────────────────────────────┘
                                                                              │
                                                                              v
                                                                     Task 6 (Session/Memory + 迁移)
                                                                              │
                                                                              v
                                                                     Task 7 (批量改 import)
                                                                              │
                                                                              v
                                                                     Task 8 (清理 SQLite)
                                                                              │
                                                                              v
                                                                     Task 9 (端到端验证)
```
