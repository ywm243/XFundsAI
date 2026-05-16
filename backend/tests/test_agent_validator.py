"""Tests for agent ToolValidator."""
import sys
sys.path.insert(0, "backend")
from agent.validator import ToolValidator

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

v = ToolValidator()

# validate_query_metrics
errors1 = v.validate_query_metrics({
    "metrics": ["trading_volume"],
    "date_start": "2026-01-01",
    "date_end": "2026-04-30",
})
test("valid query_metrics: no errors", len(errors1) == 0)

# Missing metrics
errors2 = v.validate_query_metrics({
    "metrics": [],
    "date_start": "2026-01-01",
})
test("empty metrics: has error", any("指标" in e for e in errors2))

# Unknown metric
errors3 = v.validate_query_metrics({
    "metrics": ["invalid_metric"],
})
test("unknown metric: has error", any("未知" in e for e in errors3))

# Bad top_n
errors4 = v.validate_query_metrics({
    "metrics": ["trading_volume"],
    "top_n": 200,
})
test("top_n > 100: has error", any("top_n" in e.lower() or "200" in e for e in errors4))

# validate_decompose_change
errors5 = v.validate_decompose_change({
    "metric": "trading_volume",
    "date_start": "2026-01-01",
    "date_end": "2026-04-30",
    "comparison": "yoy",
    "by_dimension": "bank",
})
test("valid decompose_change: no errors", len(errors5) == 0)

# Missing comparison
errors6 = v.validate_decompose_change({
    "metric": "trading_volume",
    "date_start": "2026-01-01",
    "date_end": "2026-04-30",
    "comparison": "",
    "by_dimension": "bank",
})
test("empty comparison: has error", any("comparison" in e for e in errors6))

# Missing date fields
errors7 = v.validate_decompose_change({
    "metric": "trading_volume",
    "date_start": "",
    "date_end": "",
    "comparison": "yoy",
    "by_dimension": "bank",
})
test("missing dates: has error", any("时间范围" in e for e in errors7))

print(f"\nResults: {passed} passed, {failed} failed")
if errors:
    for e in errors:
        print(f"  Error: {e}")
