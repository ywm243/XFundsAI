"""Comprehensive E2E test suite for Smart BI - with timeouts."""
import sys, io, json, re, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import httpx

BASE = "http://localhost:8000"
passed = 0
failed = 0
errors = []
TIMEOUT = 10.0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        msg = f"{name} | {detail}" if detail else name
        errors.append(msg)
        print(f"  FAIL: {msg}")


def get(path):
    return httpx.get(f"{BASE}{path}", timeout=TIMEOUT)

def post(path, json_data=None):
    return httpx.post(f"{BASE}{path}", json=json_data, timeout=TIMEOUT)


# ─── 1. Root page ───────────────────────────────────────────────────────────

print("=== 1. Root page & static assets ===")
r = get("/")
test("GET / 200", r.status_code == 200)
html = r.text
test("/ returns index.html", 'id="app"' in html)
test("JS bundle referenced", "assets/index" in html)
test("CSS referenced", ".css" in html)

asset_match = re.findall(r'(assets/index-[^"\']+)', html)
for asset in asset_match:
    r2 = get(f"/{asset}")
    test(f"Static {asset[:25]} accessible", r2.status_code == 200)
print()

# ─── 2. Health ──────────────────────────────────────────────────────────────

print("=== 2. Health ===")
r = get("/api/health")
test("GET /api/health 200", r.status_code == 200)
test("status ok", r.json() == {"status": "ok"})
print()

# ─── 3. Parse ───────────────────────────────────────────────────────────────

print("=== 3. Parse endpoint ===")
for text, label in [
    ("本月交易量", "normal"),
    ("工行上月交易量排名", "ranking"),
    ("同比外汇交易量", "yoy"),
    ("查询交易量", "vague"),
    ("", "empty"),
]:
    r = post("/api/parse", {"text": text})
    test(f"Parse: {label} 200", r.status_code == 200)
    d = r.json()
    test(f"Parse: {label} has params", "params" in d)
    if text:
        test(f"Parse: {label} no error", not d.get("error"))
    if "同比" in text:
        test(f"Parse: {label} comparison=yoy", d.get("params", {}).get("comparison") == "yoy")
print()

# ─── 4. Query ───────────────────────────────────────────────────────────────

print("=== 4. Query endpoint ===")
r = post("/api/query", {"text": "本月交易量"})
d = r.json()
required = ["summary","chartOption","insights","comparison","columns","rows","sql"]
missing = [k for k in required if k not in d]
test("Query: ResultCard fields", not missing, f"missing={missing}")
test("Query: comparison_sql field", "comparison_sql" in d)
print()

print("=== 4b. Multi-turn comparison flow ===")
# Step 1: First query — aggregate with bank filter
r1 = post("/api/parse", {"text": "浙江分公司今年一季度交易量多少"})
p1 = r1.json().get("params", {})
q1 = post("/api/query", {"params": p1, "text": "浙江分公司今年一季度交易量多少"})
d1 = q1.json()
test("Turn1: ResultCard fields", all(k in d1 for k in required),
     f"missing={[k for k in required if k not in d1]}")
test("Turn1: aggregate query", d1.get("row_count", 999) < 100,
     f"got {d1.get('row_count')} rows — likely detail query")
test("Turn1: has params.bank_name", bool(d1.get("params", {}).get("bank_name")))

# Step 2: Follow-up 同比 with context
context = [{"role": "assistant", "content": json.dumps(d1, ensure_ascii=False)}]
r2 = post("/api/parse", {"text": "同比增加多少", "context": context})
p2 = r2.json().get("params", {})
test("Turn2: comparison=yoy", p2.get("comparison") == "yoy")
test("Turn2: inherited bank_name", bool(p2.get("bank_name")),
     f"got empty bank_name — context inheritance broken")
test("Turn2: inherited aggregate", p2.get("aggregate") == True,
     f"got aggregate={p2.get('aggregate')} — will cause OOM")

q2 = post("/api/query", {"params": p2, "text": "同比增加多少", "context": context})
d2 = q2.json()
test("Turn2: ResultCard fields", all(k in d2 for k in required),
     f"missing={[k for k in required if k not in d2]}")
test("Turn2: row_count safe (< 100)", d2.get("row_count", 9999) < 100,
     f"got {d2.get('row_count')} rows — browser OOM risk")
test("Turn2: has comparison data", bool(d2.get("comparison")))

if d2.get("comparison"):
    cmp = d2["comparison"]
    test("Turn2: cmp.type=yoy", cmp.get("type") == "yoy")
    test("Turn2: cmp.cmp_start is last year",
         cmp.get("cmp_start", "").startswith("2025"),
         f'got {cmp.get("cmp_start")}')
    test("Turn2: cmp.cmp_end is last year",
         cmp.get("cmp_end", "").startswith("2025"),
         f'got {cmp.get("cmp_end")}')
    test("Turn2: cmp.change_amount is number",
         isinstance(cmp.get("change_amount"), (int, float)))
    test("Turn2: cmp.change_rate is number",
         isinstance(cmp.get("change_rate"), (int, float)))

test("Turn2: has comparison_sql", bool(d2.get("comparison_sql")))
if d2.get("comparison_sql"):
    csql = d2["comparison_sql"]
    test("Turn2: comparison_sql has 2025 dates",
         "20250101" in csql,
         f"comparison_sql missing 2025 dates")
    test("Turn2: comparison_sql aggregates", "SUM(t.USDAMOUNT)" in csql)
    test("Turn2: comparison_sql filters bank",
         "matched_banks" in csql or "BANKID" in csql)

# Summary must mention 同比
test("Turn2: summary mentions 同比", "同比" in d2.get("summary", ""),
     f'summary={d2.get("summary","")[:100]}')

# Step 3: MoM follow-up
r3 = post("/api/parse", {"text": "环比增加多少", "context": context})
p3 = r3.json().get("params", {})
test("Turn3: comparison=mom", p3.get("comparison") == "mom")
q3 = post("/api/query", {"params": p3, "text": "环比增加多少", "context": context})
d3 = q3.json()
test("Turn3: row_count safe", d3.get("row_count", 9999) < 100,
     f'got {d3.get("row_count")} rows')
test("Turn3: has comparison", bool(d3.get("comparison")))
test("Turn3: cmp.type=mom",
     d3.get("comparison", {}).get("type") == "mom") if d3.get("comparison") else test("Turn3: cmp.type=mom", False)

# Step 4: Standalone 同比 without context → should return confirm_date
r4 = post("/api/parse", {"text": "同比增加多少"})
p4 = r4.json().get("params", {})
test("Standalone 同比 comparison=yoy", p4.get("comparison") == "yoy")
q4 = post("/api/query", {"params": p4, "text": "同比增加多少"})
d4 = q4.json()
test("Standalone 同比 confirm_date", d4.get("confirm_date") == True)
test("Standalone 同比 0 rows", d4.get("row_count", -1) == 0)
print()

# ─── 5. Chat / LangGraph ───────────────────────────────────────────────────

print("=== 5. Chat endpoint (LangGraph) ===")

r = post("/api/chat", {"text": "本月交易量", "session_id": "test-001"})
test("Chat: 200 status", r.status_code in (200, 422))
d = r.json()
test("Chat: has router_decision", "router_decision" in d)
rd = d.get("router_decision", {})
if rd:
    test("Chat: router status valid", rd.get("status") in ("ok","confirm","rejected"))

r = post("/api/chat", {"text": "帮我预测下个月美元走势"})
test("Chat: out-of-scope 422", r.status_code == 422)
d = r.json()
test("Chat: reject message", "不支持" in d.get("summary","") or "超出" in d.get("summary",""))

r = post("/api/chat", {"text": "风险评估报告"})
test("Chat: risk rejected", r.status_code == 422)

r = post("/api/chat", {"text": "查询交易量"})
d = r.json()
rd = d.get("router_decision", {})
test("Chat: confirm status", rd.get("status") == "confirm")
test("Chat: needs_confirm", len(rd.get("needs_confirm", [])) > 0)

r = post("/api/chat", {"text": "外汇交易量排名"})
d = r.json()
if r.status_code == 200:
    test("Chat: ResultCard fields",
         all(k in d for k in ["summary","chartOption","insights","columns","rows"]))
print()

# ─── 6. Sessions ───────────────────────────────────────────────────────────

print("=== 6. Sessions CRUD ===")

r = post("/api/sessions")
test("POST session 200", r.status_code == 200)
d = r.json()
test("Session has id", "session_id" in d)
sid = d["session_id"]

r = get("/api/sessions")
test("GET sessions 200", r.status_code == 200)
test("Sessions is list", isinstance(r.json(), list))

r = get(f"/api/sessions/{sid}")
test("GET session by id 200", r.status_code == 200)
test("Session id matches", r.json().get("id") == sid)

r = post(f"/api/sessions/{sid}/turns", json_data={
    "user_query": "本月交易量",
    "parsed_params": {"product_type": "all", "date_start": "2026-05-01"},
    "executed_sql": "SELECT * FROM XF_FX_ALLTRADE_VIEW",
    "result_summary": "本月交易量汇总",
})
test("POST turn 200", r.status_code == 200)
test("Turn has index", "turn_index" in r.json())

r = get(f"/api/sessions/{sid}")
d = r.json()
test("Session has turns", "turns" in d)
test("Turn count > 0", len(d.get("turns", [])) > 0)

r = post(f"/api/sessions/{sid}/turns", json_data={
    "user_query": "同比增加多少",
    "parsed_params": {"comparison": "yoy"},
})
test("POST 2nd turn 200", r.status_code == 200)

r = get(f"/api/sessions/{sid}")
test("2 turns saved", len(r.json().get("turns", [])) == 2, f'got {len(r.json().get("turns",[]))}')

r = get(f"/api/sessions/nonexist123")
test("Non-existent 404", r.status_code == 404)

r = delete = httpx.delete(f"{BASE}/api/sessions/{sid}", timeout=TIMEOUT)
test("DELETE session 200", r.status_code == 200)
test("Delete ok", r.json().get("status") == "ok")

r = get(f"/api/sessions/{sid}")
test("Deleted 404", r.status_code == 404)
print()

# ─── 7. Admin Rules ─────────────────────────────────────────────────────────

print("=== 7. Admin Rules API ===")

r = get("/api/admin/rules/categories")
test("Categories 200", r.status_code == 200)
d = r.json()
test("Has categories list", "categories" in d)
cats = d["categories"]
test("6 categories", len(cats) == 6, f'got {len(cats)}')

r = get("/api/admin/rules/categories?agent_type=bi")
d = r.json()
if d["categories"]:
    test("BI type filter works", all(c.get("agent_type") == "bi" for c in d["categories"]))

if cats:
    cid = cats[0]["id"]
    r = get(f"/api/admin/rules/categories/{cid}/items")
    test(f"Items cat {cid} 200", r.status_code == 200)
    d2 = r.json()
    test("Has items list", "items" in d2)

    r = get(f"/api/admin/rules/categories/{cid}/versions")
    test(f"Versions 200", r.status_code == 200)
    test("Has versions", "versions" in r.json())

r = post("/api/admin/rules/preview", {"text": "本月交易量"})
test("Preview 200", r.status_code == 200)
d = r.json()
test("Preview has rule_parsed", "rule_parsed" in d)
test("Preview has confidence", "confidence" in d)
test("Preview would_skip_llm", "would_skip_llm" in d)

r = post("/api/admin/rules/preview", {"text": ""})
test("Preview empty 200", r.status_code == 200)

r = post("/api/admin/rules/reload")
test("Reload 200", r.status_code == 200)
test("Reload ok", r.json().get("status") == "ok")

r = get("/api/admin/rules/categories/9999/items")
test("Non-existent cat 404", r.status_code == 404)

if cats:
    cid = cats[0]["id"]
    r = httpx.post(f"{BASE}/api/admin/rules/categories/{cid}/rollback?version_num=9999", timeout=TIMEOUT)
    test("Rollback bad version 404", r.status_code == 404)

# CRUD: create/update/delete rule item
if cats:
    cid = cats[0]["id"]
    ts = str(int(time.time()))
    kw = f"__test_e2e_{ts}__"
    # Determine valid rule_data based on category type
    test_rules = {"value": "spot"} if cats[0]["category"] == "product_type" else {"test": True}
    r = post(f"/api/admin/rules/categories/{cid}/items", {
        "keywords": [kw],
        "rule_data": test_rules,
        "is_ironclad": False,
        "priority": 0,
    })
    if r.status_code == 200:
        item_id = r.json().get("id")
        test(f"Create item {item_id}", item_id is not None)

        r = httpx.put(f"{BASE}/api/admin/rules/items/{item_id}", json={"priority": 99}, timeout=TIMEOUT)
        test(f"Update item {item_id} 200", r.status_code == 200)

        r = httpx.delete(f"{BASE}/api/admin/rules/items/{item_id}", timeout=TIMEOUT)
        test(f"Delete item {item_id} 200", r.status_code == 200)

        r = httpx.delete(f"{BASE}/api/admin/rules/items/{item_id}", timeout=TIMEOUT)
        test(f"Delete already-deleted 404", r.status_code == 404)
    else:
        err = r.json()
        test(f"Create item API {cats[0]['category']}", False, err.get("detail",""))
print()

# ─── 8. MCP ──────────────────────────────────────────────────────────────────

print("=== 8. MCP Endpoint ===")

# MCP uses StreamableHTTP: requires Accept header for both JSON and SSE
_mcp_headers = {"Accept": "application/json, text/event-stream"}
with httpx.Client(timeout=TIMEOUT) as client:
    r = client.post(f"{BASE}/mcp/",
        headers=_mcp_headers,
        json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1})
    mcp_tools = []
    for line in r.text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            d = json.loads(line[5:])
            mcp_tools = [t["name"] for t in d.get("result", {}).get("tools", [])]
            break
    test("MCP tools/list", len(mcp_tools) > 0)
    test("11 MCP tools", len(mcp_tools) == 11, f'got {len(mcp_tools)}')

    for t in ["oracle_query","mysql_query","llm_chat","load_rules","parse_date",
              "detect_entities","compute_comparison","get_session_context",
              "save_memory","write_audit_log","check_cache"]:
        test(f"MCP tool: {t}", t in mcp_tools)

    # mysql_query tool call
    r = client.post(f"{BASE}/mcp/",
        headers=_mcp_headers,
        json={"jsonrpc": "2.0", "method": "tools/call",
              "params": {"name": "mysql_query",
                         "arguments": {"sql": "SELECT category FROM rule_categories LIMIT 3"}},
              "id": 2})
    result = None
    for line in r.text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            d = json.loads(line[5:])
            content = d.get("result", {}).get("content", [])
            if content:
                result = content
            break
    test("MCP mysql_query works", result is not None)

    # load_rules tool call
    r = client.post(f"{BASE}/mcp/",
        headers=_mcp_headers,
        json={"jsonrpc": "2.0", "method": "tools/call",
              "params": {"name": "load_rules", "arguments": {"category": "product_type"}},
              "id": 3})
    result = None
    for line in r.text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            d = json.loads(line[5:])
            content = d.get("result", {}).get("content", [])
            if content:
                result = content
            break
    test("MCP load_rules works", result is not None)

print()

# ─── Summary ────────────────────────────────────────────────────────────────

print(f"=== SUMMARY: {passed} passed, {failed} failed ===")
if errors:
    print("FAILURES:")
    for e in errors:
        print(f"  - {e}")
sys.exit(0 if failed == 0 else 1)
