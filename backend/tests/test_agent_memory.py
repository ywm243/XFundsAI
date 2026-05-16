"""Tests for AgentMemory."""
import sys
sys.path.insert(0, "backend")
from agent.memory import AgentMemory

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

# Test save and get_context
memory = AgentMemory()

# Empty context (no DB table or no data)
ctx = memory.get_context("test-session", last_n=5)
test("get_context returns list", isinstance(ctx, list))

# build_context_prompt with no data
prompt = memory.build_context_prompt("test-session")
test("build_context_prompt returns string", isinstance(prompt, str))
test("empty context returns empty string", prompt == "")

print(f"\nResults: {passed} passed, {failed} failed")
if errors:
    for e in errors:
        print(f"  Error: {e}")
