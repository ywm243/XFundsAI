"""E2E test for agent analysis pipeline."""
import sys, json
sys.path.insert(0, "backend")

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
    else:
        failed += 1
        msg = f"{name} | {detail}" if detail else name
        errors.append(msg)


# Test 1: mode=analyze returns correct format
r = httpx.post(f"{BASE}/api/query", json={
    "text": "上月各机构交易量分析",
    "mode": "analyze",
}, timeout=TIMEOUT)
d = r.json()
test("mode=analyze returns 200", r.status_code == 200)
test("mode=analyze has summary", bool(d.get("summary")))
test("mode=analyze has mode=analyze", d.get("mode") == "analyze")
test("mode=analyze has insights list", isinstance(d.get("insights"), list))
test("mode=analyze has params", isinstance(d.get("params"), dict))

# Test 2: Default mode still works
r2 = httpx.post(f"{BASE}/api/query", json={
    "text": "上月交易量",
}, timeout=TIMEOUT)
d2 = r2.json()
test("default mode returns 200", r2.status_code == 200)
test("default mode has summary", "summary" in d2)

print(f"\nResults: {passed} passed, {failed} failed")
if errors:
    for e in errors:
        print(f"  Error: {e}")
