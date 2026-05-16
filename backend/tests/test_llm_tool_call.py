"""Tests for LLM tool calling."""
import sys, json
sys.path.insert(0, "backend")
from llm_parser.llm_client import llm_tool_call

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

# Test with no API key (simulate unconfigured)
result = llm_tool_call(
    messages=[{"role": "user", "content": "上月各机构交易量"}],
    tools=[],
)
test("returns None when LLM not configured", result is None)

print(f"\nResults: {passed} passed, {failed} failed")
if errors:
    for e in errors:
        print(f"  Error: {e}")
