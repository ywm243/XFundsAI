"""规则 A/B 测试框架"""
import hashlib
from dataclasses import dataclass


@dataclass
class ABTest:
    test_id: str
    variant_a_rules: dict
    variant_b_rules: dict
    traffic_split: float = 0.5
    min_samples: int = 100

    def assign_variant(self, session_id: str) -> str:
        h = hashlib.sha256(f"{session_id}:{self.test_id}".encode()).hexdigest()
        bucket = int(h[:8], 16) % 100
        return "A" if bucket < self.traffic_split * 100 else "B"


class ABTestRegistry:
    _tests: dict[str, ABTest] = {}

    @classmethod
    def register(cls, test: ABTest):
        cls._tests[test.test_id] = test

    @classmethod
    def get(cls, test_id: str) -> ABTest | None:
        return cls._tests.get(test_id)
