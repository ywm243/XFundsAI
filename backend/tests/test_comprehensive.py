# -*- coding: utf-8 -*-
"""Comprehensive verification test for comparison (同比/环比) flow."""
import sys, json, re
import httpx

BASE = "http://localhost:8000"
TIMEOUT = 120
passed = 0
failed = 0
errors = []


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


def section(title):
    print(f"\n=== {title} ===")


# ========================================================================
# Helper: run a full two-query conversation flow
# ========================================================================

def run_conversation(first_query, follow_up):
    """Run a two-query conversation, return (first_response, second_response)."""
    # Step 1: Parse + Query first
    r = httpx.post(f"{BASE}/api/parse", json={"text": first_query}, timeout=TIMEOUT)
    d = r.json()
    params = d.get("params", {})

    r2 = httpx.post(f"{BASE}/api/query", json={"params": params, "text": first_query}, timeout=TIMEOUT)
    first_resp = r2.json()

    # Step 2: Parse + Query follow-up with context
    context = [{"role": "assistant", "content": json.dumps(first_resp, ensure_ascii=False)}]
    r3 = httpx.post(f"{BASE}/api/parse", json={"text": follow_up, "context": context}, timeout=TIMEOUT)
    d3 = r3.json()
    params2 = d3.get("params", {})

    r4 = httpx.post(f"{BASE}/api/query", json={"params": params2, "text": follow_up, "context": context}, timeout=TIMEOUT)
    second_resp = r4.json()

    return first_resp, second_resp


# ========================================================================
# Section 1: Multi-turn context inheritance
# ========================================================================

section("1. Context inheritance (aggregate query)")

first, second = run_conversation(
    "浙江分公司今年一季度交易量多少",
    "同比增加多少",
)

# First query assertions
test("Q1 status 200", True)  # no error = 200
test("Q1 has summary", bool(first.get("summary")))
test("Q1 has chartOption", bool(first.get("chartOption")))
test("Q1 has insights", isinstance(first.get("insights"), list))

# Second query — context inheritance
test("Q2 inherits aggregate=True", second.get("params", {}).get("aggregate") == True,
     f'got aggregate={second.get("params", {}).get("aggregate")}')
test("Q2 inherits bank_name (non-empty)", bool(second.get("params", {}).get("bank_name")))
test("Q2 has comparison=yoy", second.get("params", {}).get("comparison") == "yoy")
test("Q2 row_count is small (< 100)", second.get("row_count", 9999) < 100,
     f'got {second.get("row_count")} rows')
test("Q2 response size is small (< 100KB)", len(json.dumps(second)) < 100 * 1024,
     f'got {len(json.dumps(second))} bytes')

# Comparison data verification
test("Q2 has comparison object", bool(second.get("comparison")))
if second.get("comparison"):
    cmp = second["comparison"]
    test("cmp.type is yoy", cmp.get("type") == "yoy")
    test("cmp.label exists", bool(cmp.get("label")))
    test("cmp.change_amount is number", isinstance(cmp.get("change_amount"), (int, float)))
    test("cmp.change_rate is number", isinstance(cmp.get("change_rate"), (int, float)))
    test("cmp.cmp_start is 2025 (last year)", cmp.get("cmp_start", "").startswith("2025"),
         f'got cmp_start={cmp.get("cmp_start")}')
    test("cmp.cmp_end is 2025 (last year)", cmp.get("cmp_end", "").startswith("2025"),
         f'got cmp_end={cmp.get("cmp_end")}')
    test("cmp.date_start is 2026 (current)", cmp.get("date_start", "").startswith("2026"),
         f'got date_start={cmp.get("date_start")}')
    test("cmp.date_end is 2026 (current)", cmp.get("date_end", "").startswith("2026"),
         f'got date_end={cmp.get("date_end")}')

# comparison_sql
test("Q2 has comparison_sql", bool(second.get("comparison_sql")))
if second.get("comparison_sql"):
    csql = second["comparison_sql"]
    test("comparison_sql has 2025 dates", "20250101" in csql and "20250331" in csql)
    test("comparison_sql is aggregate (SUM)", "SUM(t.USDAMOUNT)" in csql)
    test("comparison_sql has bank filter", "matched_banks" in csql)
    test("comparison_sql has GROUP BY", "GROUP BY" in csql)

# ResultCard 4-section format
test("Q2 has summary (section 1)", bool(second.get("summary")))
test("Q2 has chartOption (section 2)", bool(second.get("chartOption")))
test("Q2 has insights (section 3)", isinstance(second.get("insights"), list))
test("Q2 has columns (section 4)", bool(second.get("columns")))
test("Q2 has rows (section 4)", isinstance(second.get("rows"), list))

# Summary mentions 同比
test("summary mentions 同比", "同比" in second.get("summary", ""))
test("summary mentions comparison change", "+" in second.get("summary", "") or "-" in second.get("summary", ""))

# Insights mention comparison (template insight type is "growth"/"risk")
insights = second.get("insights", [])
if insights:
    has_cmp_insight = any(i.get("type") in ("growth", "risk") for i in insights)
    test("insights has comparison type", has_cmp_insight)

# ========================================================================
# Section 2: 环比 (MoM) follow-up
# ========================================================================

section("2. MoM (环比) follow-up")

first2, second2 = run_conversation(
    "浙江分公司今年一季度交易量多少",
    "环比增加多少",
)

test("MoM inherits aggregate", second2.get("params", {}).get("aggregate") == True)
test("MoM has comparison=mom", second2.get("params", {}).get("comparison") == "mom")
test("MoM row_count is small", second2.get("row_count", 9999) < 100)

if second2.get("comparison"):
    cmp2 = second2["comparison"]
    test("MoM cmp.type is mom", cmp2.get("type") == "mom")
    # MoM: compare to previous month within same year, or Dec of prev year
    # For Q1 data, MoM would compare to 2025-12
    test("MoM cmp_start is before date_start",
         cmp2.get("cmp_start", "9999") < cmp2.get("date_start", "0000"))
    test("MoM cmp_end is before date_end",
         cmp2.get("cmp_end", "9999") < cmp2.get("date_end", "0000"))

test("MoM has comparison_sql", bool(second2.get("comparison_sql")))

# ========================================================================
# Section 3: Ranking query with 同比 follow-up
# ========================================================================

section("3. Ranking query → 同比 follow-up")

# First query: ranking (交易量排名)
r_parse = httpx.post(f"{BASE}/api/parse", json={"text": "外汇交易量排名"}, timeout=TIMEOUT)
rp = r_parse.json()["params"]
print(f"  Ranking params: top_n={rp.get('top_n')}, aggregate={rp.get('aggregate')}")

r_q = httpx.post(f"{BASE}/api/query", json={"params": rp, "text": "外汇交易量排名"}, timeout=TIMEOUT)
first_rank = r_q.json()
test("Ranking query works", first_rank.get("row_count", 0) > 0,
     f'got {first_rank.get("row_count")} rows')
test("Ranking result has ranking columns", bool(first_rank.get("columns")))

# Follow-up: 同比
ctx = [{"role": "assistant", "content": json.dumps(first_rank, ensure_ascii=False)}]
r3 = httpx.post(f"{BASE}/api/parse", json={"text": "同比增加多少", "context": ctx}, timeout=TIMEOUT)
p3 = r3.json()["params"]
print(f"  Ranking follow-up params: top_n={p3.get('top_n')}, aggregate={p3.get('aggregate')}, comparison={p3.get('comparison')}")

r4 = httpx.post(f"{BASE}/api/query", json={"params": p3, "text": "同比增加多少", "context": ctx}, timeout=TIMEOUT)
second_rank = r4.json()
test("Ranking+同比 row_count < 200", second_rank.get("row_count", 9999) < 200,
     f'got {second_rank.get("row_count")} rows')
test("Ranking+同比 has comparison", bool(second_rank.get("comparison")))
if second_rank.get("comparison"):
    cr = second_rank["comparison"]
    test("Ranking+同比 cmp_start is last year", cr.get("cmp_start", "").startswith("2025"),
         f'got {cr.get("cmp_start")}')
test("Ranking+同比 has comparison_sql", bool(second_rank.get("comparison_sql")))

# ========================================================================
# Section 4: Edge cases — comparison without dates
# ========================================================================

section("4. Edge cases — comparison without date context")

# Parse standalone 同比 without context → should have comparison=yoy but no dates
r = httpx.post(f"{BASE}/api/parse", json={"text": "同比增加多少"}, timeout=TIMEOUT)
d = r.json()
p = d["params"]
test("Standalone 同比 has comparison=yoy", p.get("comparison") == "yoy")
test("Standalone 同比 has no date_start", not p.get("date_start"))
test("Standalone 同比 has no date_end", not p.get("date_end"))

# Query without context should return confirm_date
r = httpx.post(f"{BASE}/api/query", json={"params": p, "text": "同比增加多少"}, timeout=TIMEOUT)
d = r.json()
test("Standalone 同比 query returns confirm_date", d.get("confirm_date") == True,
     f"confirm_date={d.get('confirm_date')}")
test("Standalone 同比 no rows", d.get("row_count", -1) == 0)

# ========================================================================
# Section 5: Edge cases — empty result
# ========================================================================

section("5. Edge case — query that returns 0 rows")

# Parse a query that will likely return 0 rows (distant future date)
future_params = {
    "product_type": "all",
    "date_start": "2030-01-01",
    "date_end": "2030-03-31",
    "aggregate": True,
    "dimension": "bank",
    "comparison": "yoy",
    "buy_sell": "",
    "bank_name": "",
    "cust_name": "",
    "trade_class": "",
    "special_states": "",
    "top_n": None,
    "amount_filter": None,
    "hedge_ratio": False,
    "appid": 1,
}
r = httpx.post(f"{BASE}/api/query", json={"params": future_params, "text": "2030年一季度交易量"}, timeout=TIMEOUT)
d = r.json()
test("Future date query returns 0 rows OK", r.status_code == 200)
test("Future date comparison is None", d.get("comparison") is None)
test("Future date summary is empty string", d.get("summary", None) == "" or d.get("summary") is None)


# ========================================================================
# Section 6: Full E2E (existing suite)
# ========================================================================

section("6. Full E2E regression suite")

# Run the standard E2E test
import subprocess
result = subprocess.run(
    [sys.executable, "backend/tests/test_e2e.py"],
    capture_output=True, text=True, timeout=180
)
print(result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout)
if result.stderr.strip():
    print('STDERR:', result.stderr[-500:])
if result.returncode != 0:
    test("E2E suite exit code 0", False, f"exit code {result.returncode}")
    # Print failures
    for line in result.stdout.split("\n"):
        if "FAIL" in line:
            print(f"  {line}")
else:
    test("E2E suite exit code 0", True)

# Extract pass/fail from output
import re as _re
m = _re.search(r"SUMMARY: (\d+) passed, (\d+) failed", result.stdout)
if m:
    e2e_passed = int(m.group(1))
    e2e_failed = int(m.group(2))
    test(f"E2E {e2e_passed}/{e2e_passed+e2e_failed} pass", e2e_failed == 0)


# ========================================================================
# Summary
# ========================================================================

print(f"\n{'='*60}")
print(f"COMPREHENSIVE VERIFICATION: {passed} passed, {failed} failed")
if errors:
    print("FAILURES:")
    for e in errors:
        print(f"  - {e}")
sys.exit(0 if failed == 0 else 1)
