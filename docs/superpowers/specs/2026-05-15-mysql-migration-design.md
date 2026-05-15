# Agent Memory MySQL 迁移设计说明书

> 版本：v1.0 | 日期：2026-05-15 | 状态：待实现

---

## 1. 动机

当前 Agent Memory 和规则引擎使用 SQLite 持久化。SQLite 在不跨实例部署时够用，但单文件架构无法支撑多进程/多服务器共享，且本地文件有丢失风险。MySQL 作为替代可提供统一存储、多实例共享、原生 JSON 支持和生产级运维能力。

---

## 2. 方案

**方案 A：纯 MySQL 直接替换** — 删除 SQLite，完全迁移到 MySQL。所有调用方只改 import 路径，不改业务逻辑。

## 3. 架构变更

```
改造前                            改造后
backend/db/                       backend/db/
├── sqlite_store.py   ← 删除      ├── mysql_store.py    ← 新增
├── connection.py                  ├── connection.py
├── config.py                     ├── config.py         ← 加 MySQLConfig
├── query_builder.py              ├── query_builder.py
└── __init__.py                   └── __init__.py

backend/memory/                   backend/memory/
└── store.py         ← 改 import  └── store.py          ← 从 mysql_store 导入

backend/data/smartbi.db  ← 删除
```

`mysql_store.py` 保持与 `sqlite_store.py` 完全相同的函数签名：

```
init_db(), load_rules_from_db(), get_categories(), get_category(),
get_items(), add_item(), update_item(), delete_item(),
get_versions(), rollback_category(), migrate_from_json(),

create_session(), add_turn(), get_session_context(), add_summary()
```

调用方（`memory/store.py`、`admin_routes.py`、`rules_engine.py`、`prompt_builder.py`）仅需修改 import 语句，内部逻辑完全不变。

---

## 4. 表结构

所有表从 SQLite 移植到 MySQL，字段语义不变，类型适配：

### rule_categories

| 字段 | MySQL 类型 | 约束 |
|------|-----------|------|
| id | INT AUTO_INCREMENT | PRIMARY KEY |
| agent_type | ENUM('common','bi','quoting','risk') | NOT NULL |
| category | VARCHAR(64) | NOT NULL |
| display_name | VARCHAR(128) | NOT NULL |
| priority | INT | DEFAULT 0 |
| | UNIQUE(agent_type, category) | |

### rule_items

| 字段 | MySQL 类型 | 约束 |
|------|-----------|------|
| id | INT AUTO_INCREMENT | PRIMARY KEY |
| category_id | INT | NOT NULL, FK → rule_categories.id ON DELETE CASCADE |
| keywords | JSON | NOT NULL |
| rule_data | JSON | NOT NULL |
| is_ironclad | TINYINT | DEFAULT 0 |
| priority | INT | DEFAULT 0 |
| is_active | TINYINT | DEFAULT 1 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP |

### rule_versions

| 字段 | MySQL 类型 | 约束 |
|------|-----------|------|
| id | INT AUTO_INCREMENT | PRIMARY KEY |
| category_id | INT | NOT NULL, FK |
| version_num | INT | NOT NULL |
| snapshot | JSON | NOT NULL |
| created_by | VARCHAR(64) | DEFAULT 'system' |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### sessions

| 字段 | MySQL 类型 | 约束 |
|------|-----------|------|
| id | VARCHAR(128) | PRIMARY KEY |
| agent_type | VARCHAR(32) | NOT NULL DEFAULT 'bi' |
| user_id | VARCHAR(64) | DEFAULT 'default' |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP |
| is_active | TINYINT | DEFAULT 1 |

### turns

| 字段 | MySQL 类型 | 约束 |
|------|-----------|------|
| id | INT AUTO_INCREMENT | PRIMARY KEY |
| session_id | VARCHAR(128) | NOT NULL, FK → sessions.id ON DELETE CASCADE |
| turn_index | INT | NOT NULL |
| user_query | TEXT | NOT NULL |
| parsed_params | JSON | NULL |
| executed_sql | TEXT | NULL |
| result_summary | TEXT | NULL |
| user_feedback | TEXT | NULL |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### memory_summaries

| 字段 | MySQL 类型 | 约束 |
|------|-----------|------|
| id | INT AUTO_INCREMENT | PRIMARY KEY |
| session_id | VARCHAR(128) | FK → sessions.id ON DELETE SET NULL |
| scope | VARCHAR(32) | DEFAULT 'session' |
| summary_type | VARCHAR(64) | NOT NULL |
| content | JSON | NOT NULL |
| source_turns | VARCHAR(128) | NULL |
| embedding_id | VARCHAR(64) | NULL |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

---

## 5. 配置变更

`.env` 删除 SQLite 路径配置，新增 MySQL 配置项：

```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=smartbi
```

`config.py` 新增 `MySQLConfig` 类，读取上述环境变量。

---

## 6. 依赖变更

`requirements.txt` 新增：

```
mysql-connector-python>=9.0.0
```

选择 mysql-connector-python（Oracle 官方驱动）而非 PyMySQL，原因：纯 Python 实现，无 C 依赖，安装简单，与 oracledb 一致都是官方驱动。

---

## 7. 首次启动自动迁移

`mysql_store.py` 提供 `init_db()` 函数，首次调用时：

1. `CREATE TABLE IF NOT EXISTS` 建表
2. 检测 `rule_items` 是否为空
3. 为空则从 `backend/knowledge_base/semantic_rules.json` 调用 `migrate_from_json()` 导入

与现有 `sqlite_store.py` 的 `_auto_migrate()` 逻辑完全一致。

---

## 8. 事务与并发

- **写操作**：保持 `threading.Lock` 互斥锁机制不变
- **连接池**：使用 `mysql.connector.pooling.MySQLConnectionPool`，pool_size=5
- **外键**：`SET FOREIGN_KEY_CHECKS=1`，启用级联删除
- **字符集**：`utf8mb4`，`collation=utf8mb4_unicode_ci`

---

## 9. 改动文件清单

| 文件 | 操作 | 行数估算 |
|------|------|---------|
| `db/mysql_store.py` | 新增 | ~550 行 |
| `db/sqlite_store.py` | 删除 | -563 行 |
| `db/config.py` | 修改 | +15 行 |
| `requirements.txt` | 修改 | +1 行 |
| `memory/store.py` | 修改 | ~5 行（改 import） |
| `admin_routes.py` | 修改 | ~1 行（改 import） |
| `rules_engine.py` | 修改 | ~1 行（改 import） |
| `prompt_builder.py` | 修改 | ~1 行（改 import） |

**净增代码约 30 行**（删除 563-写入 550+配置 15=28 行），改动风险可控。

---

## 10. 性能评估

| 操作 | SQLite | MySQL (localhost) |
|------|--------|-------------------|
| 规则加载（缓存后 0） | <1ms | ~1ms |
| session CRUD | <1ms | ~1-3ms |
| get_context (LIMIT 3) | <1ms | ~1-2ms |
| find_similar（全扫） | ~2ms | ~2-5ms |

业务瓶颈在 Oracle 查询（50-500ms），MySQL 增加的 1-3ms 网络往返可忽略。

---

## 11. 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| MySQL 未安装 | 服务无法启动 | 文档明确要求；后续可加 Docker Compose |
| 规则迁移失败 | 空规则库 | `migrate_from_json()` 有日志和异常处理 |
| 字符编码问题 | 中文乱码 | 统一 utf8mb4 |
| 连接池耗尽 | 请求阻塞 | pool_size=5，监控等待时间 |
