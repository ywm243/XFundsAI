# MCP Phase 1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 MCP 工具层，暴露 3 个工具（oracle_query / mysql_query / llm_chat），挂载到 FastAPI `/mcp` 端点，不修改现有代码。

**Architecture:** 新增 `backend/mcp/` 目录，3 个工具文件各封装一个 MCP 工具，`server.py` 创建 FastMCP 实例并注册工具，`app.py` 加一行 `app.mount("/mcp", mcp.http_app())`。工具复用现有 `db/connection.py`、`db/mysql_store.py`、`llm_parser/llm_client.py`。

**Tech Stack:** Python 3.13 + FastMCP (mcp>=1.0.0) + FastAPI + oracledb + pymysql

---

### Task 1: 安装 MCP SDK

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: 安装 mcp 包**

```bash
pip install "mcp>=1.0.0"
```

- [ ] **Step 2: 验证导入**

```bash
python -c "from mcp.server.fastmcp import FastMCP; print('FastMCP', FastMCP.__module__)"
```

预期: `FastMCP mcp.server.fastmcp`

- [ ] **Step 3: 更新 requirements.txt**

在 `backend/requirements.txt` 末尾追加：

```
mcp>=1.0.0
```

- [ ] **Step 4: 提交**

```bash
git add backend/requirements.txt && git commit -m "chore: 添加 MCP SDK 依赖"
```

---

### Task 2: 创建 MCP Server 入口

**Files:**
- Create: `backend/mcp/__init__.py`
- Create: `backend/mcp/server.py`

- [ ] **Step 1: 创建 __init__.py**

```python
# backend/mcp/__init__.py
"""MCP tool layer — exposes Oracle/MySQL/LLM as standard MCP tools."""
```

- [ ] **Step 2: 创建 server.py**

```python
# backend/mcp/server.py
"""FastMCP server — registers and serves MCP tools."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("SmartBI")

# Tools are registered via @mcp.tool() in their respective modules.
# Import here to trigger registration.
from .tools import oracle_tool, mysql_tool, llm_tool  # noqa: F401
```

- [ ] **Step 3: 验证 server 导入**

```bash
cd backend && python -c "from mcp.server import mcp; print('MCP Server:', mcp.name)"
```

预期: `MCP Server: SmartBI`

- [ ] **Step 4: 提交**

```bash
git add backend/mcp/__init__.py backend/mcp/server.py && git commit -m "feat(mcp): FastMCP Server 入口"
```

---

### Task 3: 实现 oracle_query 工具

**Files:**
- Create: `backend/mcp/tools/__init__.py`
- Create: `backend/mcp/tools/oracle_tool.py`

- [ ] **Step 1: 创建 tools/__init__.py**

```python
# backend/mcp/tools/__init__.py
"""MCP tool implementations."""
```

- [ ] **Step 2: 创建 oracle_tool.py**

```python
# backend/mcp/tools/oracle_tool.py
"""MCP tool: oracle_query — execute read-only queries against Oracle FX database."""

import logging
from mcp.server.fastmcp import FastMCP
from db.connection import get_db

logger = logging.getLogger(__name__)

# Late-bound reference — set by server.py
_mcp: FastMCP | None = None


def register(mcp: FastMCP) -> None:
    """Register oracle_query tool on the given FastMCP instance."""
    global _mcp
    _mcp = mcp

    @mcp.tool()
    def oracle_query(sql: str) -> dict:
        """Execute a read-only SQL query against the Oracle FX trade database.

        Database contains views: XF_FX_SPOTTRADE_VIEW, XF_FX_FWDTRADE_VIEW,
        XF_FX_SWAPTRADE_VIEW. Common fields: USDAMOUNT, TRADEDATE, TRADESTATUS,
        SPECIALSTATE, APPID, BUYORSELL, BANKID, CUSTNAME, CUSTOMERID,
        CUSTMAINMANAGER, CUSTMANAGERNAME.

        Args:
            sql: A complete Oracle SQL SELECT statement.

        Returns:
            dict with keys: columns (list of column names),
            rows (list of lists), row_count (int).
        """
        safe = sql.strip().upper()
        if not safe.startswith("SELECT") and not safe.startswith("WITH"):
            return {"columns": [], "rows": [], "row_count": 0,
                    "error": "Only SELECT / WITH queries are allowed"}

        forbidden = ["DROP", "ALTER", "CREATE", "TRUNCATE", "INSERT",
                     "UPDATE", "DELETE", "MERGE", "GRANT", "REVOKE"]
        for kw in forbidden:
            if kw in safe:
                return {"columns": [], "rows": [], "row_count": 0,
                        "error": f"Forbidden keyword: {kw}"}

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                cols = [desc[0] for desc in cur.description] if cur.description else []
                rows = [list(row) for row in cur.fetchall()]
                logger.info("oracle_query: %d rows, %d cols", len(rows), len(cols))
                return {"columns": cols, "rows": rows, "row_count": len(rows)}
```

- [ ] **Step 3: 更新 server.py 调用 register**

更新 `backend/mcp/server.py`：

```python
# backend/mcp/server.py
"""FastMCP server — registers and serves MCP tools."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("SmartBI")

from .tools import oracle_tool  # noqa: E402
oracle_tool.register(mcp)
```

- [ ] **Step 4: 验证工具注册**

```bash
cd backend && python -c "
from mcp.server import mcp
tools = mcp._tool_manager._tools if hasattr(mcp, '_tool_manager') else {}
print('Tools:', list(tools.keys()) if tools else 'check FastMCP internals')
print('MCP name:', mcp.name)
"
```

- [ ] **Step 5: 验证工具可直接调用**

```bash
cd backend && python -c "
import json
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('..') / '.env', override=True)
from mcp.tools.oracle_tool import oracle_query
result = oracle_query('SELECT 1 AS test_value FROM DUAL')
print(json.dumps(result, default=str))
"
```

预期: `{"columns": ["TEST_VALUE"], "rows": [[1]], "row_count": 1}`

- [ ] **Step 6: 提交**

```bash
git add backend/mcp/ && git commit -m "feat(mcp): oracle_query 工具 — Oracle 只读查询"
```

---

### Task 4: 实现 mysql_query 工具

**Files:**
- Create: `backend/mcp/tools/mysql_tool.py`

- [ ] **Step 1: 创建 mysql_tool.py**

```python
# backend/mcp/tools/mysql_tool.py
"""MCP tool: mysql_query — execute read-only queries against MySQL rules/memory store."""

import logging
from mcp.server.fastmcp import FastMCP
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """Register mysql_query tool on the given FastMCP instance."""

    @mcp.tool()
    def mysql_query(sql: str) -> list[dict]:
        """Execute a read-only SQL query against the MySQL rules and memory store.

        Tables: rule_categories, rule_items, rule_versions, sessions,
        turns, memory_summaries.

        Args:
            sql: A complete MySQL SELECT statement.

        Returns:
            list of dicts, each dict representing one result row.
        """
        safe = sql.strip().upper()
        if not safe.startswith("SELECT"):
            return [{"error": "Only SELECT queries are allowed"}]

        forbidden = ["DROP", "ALTER", "CREATE", "TRUNCATE", "INSERT",
                     "UPDATE", "DELETE", "GRANT", "REVOKE"]
        for kw in forbidden:
            if kw in safe:
                return [{"error": f"Forbidden keyword: {kw}"}]

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                result = [dict(r) for r in rows]
                logger.info("mysql_query: %d rows", len(result))
                return result
        finally:
            conn.close()
```

- [ ] **Step 2: 更新 server.py 注册**

更新 `backend/mcp/server.py`，追加 `mysql_tool` 注册：

```python
from .tools import mysql_tool  # noqa: E402
mysql_tool.register(mcp)
```

- [ ] **Step 3: 验证工具调用**

```bash
cd backend && python -c "
from mcp.tools.mysql_tool import mysql_query
result = mysql_query('SELECT category, display_name FROM rule_categories LIMIT 3')
print('Rows:', len(result))
for r in result:
    print(f'  {r[\"category\"]}: {r[\"display_name\"]}')
"
```

预期: 3 行，包含 product_type / buy_sell_direction 等分类。

- [ ] **Step 4: 提交**

```bash
git add backend/mcp/ && git commit -m "feat(mcp): mysql_query 工具 — MySQL 规则库查询"
```

---

### Task 5: 实现 llm_chat 工具

**Files:**
- Create: `backend/mcp/tools/llm_tool.py`

- [ ] **Step 1: 创建 llm_tool.py**

```python
# backend/mcp/tools/llm_tool.py
"""MCP tool: llm_chat — send prompts to DeepSeek LLM."""

import logging
import os
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """Register llm_chat tool on the given FastMCP instance."""

    @mcp.tool()
    def llm_chat(prompt: str) -> str:
        """Send a prompt to the configured LLM and return its response.

        Uses the same configuration as the main parser:
          LLM_API_KEY, LLM_BASE_URL, LLM_MODEL from environment / .env.

        Args:
            prompt: The text prompt to send to the LLM.

        Returns:
            The LLM's text response, or an error message on failure.
        """
        api_key = os.environ.get("LLM_API_KEY", "")
        base_url = os.environ.get("LLM_BASE_URL", "")
        model = os.environ.get("LLM_MODEL", "")

        if not api_key or not base_url or not model:
            return "LLM not configured: missing LLM_API_KEY/LLM_BASE_URL/LLM_MODEL"

        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
                timeout=30,
            )
            content = response.choices[0].message.content
            logger.info("llm_chat: model=%s, len=%d", model, len(content or ""))
            return content or "(empty response)"
        except Exception as exc:
            logger.warning("llm_chat failed: %s", exc)
            return f"LLM call failed: {exc}"
```

- [ ] **Step 2: 更新 server.py 注册**

更新 `backend/mcp/server.py`，追加 `llm_tool` 注册：

```python
from .tools import llm_tool  # noqa: E402
llm_tool.register(mcp)
```

- [ ] **Step 3: 验证工具调用**

```bash
cd backend && python -c "
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('..') / '.env', override=True)
from mcp.tools.llm_tool import llm_chat
result = llm_chat('回复OK')
print('LLM:', result[:100])
"
```

- [ ] **Step 4: 提交**

```bash
git add backend/mcp/ && git commit -m "feat(mcp): llm_chat 工具 — LLM 调用"
```

---

### Task 6: 挂载 MCP 到 FastAPI

**Files:**
- Modify: `backend/app.py` (+1 行)
- Modify: `backend/mcp/server.py` (+ http_app 导出)

- [ ] **Step 1: 更新 server.py 导出 http_app**

在 `backend/mcp/server.py` 末尾追加：

```python
def create_http_app():
    """Return an ASGI app for mounting on FastAPI."""
    return mcp.http_app()
```

- [ ] **Step 2: 修改 app.py 挂载**

在 `backend/app.py` 中，找到 `app = FastAPI(...)` 之后的路由注册区域，添加：

```python
from mcp.server import create_http_app
app.mount("/mcp", create_http_app())
```

- [ ] **Step 3: 启动服务测试**

```bash
# 确保 Oracle 可达 + .env 配置正确
cd backend && uvicorn app:app --host 0.0.0.0 --port 8000 &
sleep 4
curl -s http://localhost:8000/mcp
```

预期: 返回 MCP Server 信息 JSON。

- [ ] **Step 4: 验证现有 API 不受影响**

```bash
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/admin/rules/categories | python -c "import sys,json;d=json.load(sys.stdin);print(len(d['categories']),'categories')"
```

预期: `{"status":"ok"}` 和 `6 categories`。

- [ ] **Step 5: 提交**

```bash
git add backend/app.py backend/mcp/server.py && git commit -m "feat(mcp): 挂载 /mcp 端点到 FastAPI"
```

---

### Task 7: 端到端验证

**Files:** 无（验证）

- [ ] **Step 1: 启动服务**

```bash
cd c:/AIProject/smartbi0512/backend && python -m uvicorn app:app --host 0.0.0.0 --port 8000 &
sleep 5
```

- [ ] **Step 2: 验证 MCP 端点可访问**

```bash
curl -s http://localhost:8000/mcp
```

预期: 返回 MCP Server 元信息 JSON。

- [ ] **Step 3: 验证全部 3 个工具可通过 Python 调用**

```python
import requests, json

# oracle_query
r = requests.post("http://localhost:8000/mcp", json={
    "jsonrpc": "2.0", "method": "tools/call",
    "params": {"name": "oracle_query", "arguments": {"sql": "SELECT 1 AS TEST FROM DUAL"}},
    "id": 1
})
print("oracle_query:", r.status_code)

# mysql_query
r = requests.post("http://localhost:8000/mcp", json={
    "jsonrpc": "2.0", "method": "tools/call",
    "params": {"name": "mysql_query", "arguments": {"sql": "SELECT category FROM rule_categories LIMIT 1"}},
    "id": 2
})
print("mysql_query:", r.status_code)

# llm_chat
r = requests.post("http://localhost:8000/mcp", json={
    "jsonrpc": "2.0", "method": "tools/call",
    "params": {"name": "llm_chat", "arguments": {"prompt": "回复OK"}},
    "id": 3
})
print("llm_chat:", r.status_code)
```

- [ ] **Step 4: 验证现有 API 全部正常**

```bash
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/admin/rules/categories | python -c "import sys,json;d=json.load(sys.stdin);print('categories:', len(d['categories']))"
curl -s -X POST http://localhost:8000/api/parse -H "Content-Type: application/json" -d '{"text":"本月交易量"}' | python -c "import sys,json;d=json.load(sys.stdin);print('pipeline:', d['pipeline'])"
```

预期: 全部返回正常。

- [ ] **Step 5: 提交**

```bash
git commit --allow-empty -m "test: MCP Phase 1 端到端验证通过"
```

---

## 任务依赖图

```
Task 1 (MCP SDK) ──> Task 2 (Server入口) ──> Task 3 (oracle_query)
                                                  │
                                          Task 4 (mysql_query)
                                                  │
                                          Task 5 (llm_chat)
                                                  │
                                          Task 6 (挂载FastAPI)
                                                  │
                                          Task 7 (端到端验证)
```
