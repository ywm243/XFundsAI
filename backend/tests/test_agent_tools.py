"""Tests for agent tools — query_metrics and decompose_change."""
import sys, json, math
sys.path.insert(0, "backend")
from agent.tools import query_metrics, decompose_change

passed = 0
failed = 0
errors = []

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        errors.append(f"{name} | {detail}" if detail else name)

# query_metrics with no dimensions should return summary
result = query_metrics(
    metrics=["trading_volume"],
    date_start="2026-01-01",
    date_end="2026-04-30",
)
test("query_metrics returns dict", isinstance(result, dict))
test("query_metrics has metrics", "metrics" in result)
test("query_metrics has summary", "summary" in result)
test("summary has total_trading_volume", "total_trading_volume" in result["summary"])
test("summary total is numeric", isinstance(result["summary"]["total_trading_volume"], (int, float)))

# query_metrics with top_n should limit rows
result2 = query_metrics(
    metrics=["trading_volume"],
    dimensions=["bank"],
    date_start="2026-01-01",
    date_end="2026-04-30",
    top_n=5,
)
test("query_metrics with top_n returns <=5 rows", len(result2.get("data", [])) <= 5)
test("query_metrics with top_n has total in summary", "total_trading_volume" in result2["summary"])

# decompose_change
result3 = decompose_change(
    metric="trading_volume",
    date_start="2026-01-01",
    date_end="2026-04-30",
    comparison="yoy",
    by_dimension="bank",
    top_n=3,
)
test("decompose_change returns dict", isinstance(result3, dict))
test("decompose_change has drivers", "drivers" in result3)
test("decompose_change has total_change_pct", "total_change_pct" in result3)
test("decompose_change has drivers list", isinstance(result3["drivers"], list))

# query_metrics with comparison
result4 = query_metrics(
    metrics=["trading_volume"],
    date_start="2026-01-01",
    date_end="2026-04-30",
    comparison="yoy",
)
test("query_metrics with comparison has prev_total", "prev_total_trading_volume" in result4.get("summary", {}))
test("query_metrics with comparison has total_change_pct", "total_change_pct" in result4.get("summary", {}))

print(f"\nResults: {passed} passed, {failed} failed")
if errors:
    for e in errors:
        print(f"  Error: {e}")
