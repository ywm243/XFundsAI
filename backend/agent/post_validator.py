"""Post-validation — extract numbers from LLM output, compare against tool data.

LLM may hallucinate numbers even with tool data provided.
This layer catches mismatches and triggers regeneration.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Tolerance by value range
TOLERANCE_PCT_HIGH = 0.01      # ±1% for values > 1000
TOLERANCE_ABS_MEDIUM = 1.0     # ±1 for values 10-1000
TOLERANCE_PCT_POINTS = 0.5     # ±0.5 percentage points for ratios


class PostValidator:
    """Validate LLM output numbers against tool-returned data."""

    def validate(self, text: str, tool_results: list[dict]) -> list[str]:
        """Compare numbers in LLM output against tool data.

        Returns list of mismatch descriptions (empty = valid).
        """
        if not tool_results:
            return []

        # Collect all real numbers from tool results
        real_numbers = self._extract_real_numbers(tool_results)
        if not real_numbers:
            return []

        # Extract numbers from LLM text
        text_numbers = self._extract_text_numbers(text)

        mismatches = []
        for tn in text_numbers:
            if not self._is_match(tn, real_numbers):
                mismatches.append(
                    f"数字「{tn['raw']}」与工具返回的数据不匹配"
                )

        return mismatches

    def _extract_real_numbers(self, tool_results: list[dict]) -> list[float]:
        """Collect all numeric values from tool results."""
        numbers = []
        for r in tool_results:
            result = r.get("result", {})
            # Summary numbers
            summary = result.get("summary", {})
            for v in summary.values():
                if isinstance(v, (int, float)):
                    numbers.append(float(v))

            # Data rows
            for row in result.get("data", []):
                for v in row.values():
                    if isinstance(v, (int, float)):
                        numbers.append(float(v))

            # Drivers (decompose_change)
            for driver in result.get("drivers", []):
                for v in driver.values():
                    if isinstance(v, (int, float)):
                        numbers.append(float(v))

        return numbers

    def _extract_text_numbers(self, text: str) -> list[dict]:
        """Extract numbers with their text context from LLM output."""
        numbers = []
        # Match patterns like: "1,234.56万", "15%", "123456"
        for match in re.finditer(r'(-?[\d,]+\.?\d*)\s*(万|亿|%|美元|人民币)?', text):
            raw = match.group(0).strip()
            try:
                value = float(match.group(1).replace(",", ""))
            except ValueError:
                continue
            unit = match.group(2) or ""

            # Normalize
            if unit == "万":
                value *= 10000
            elif unit == "亿":
                value *= 100000000

            # Skip year-like numbers (1900-2099) without unit context
            if not unit and 1900 <= value <= 2099 and raw.isdigit():
                continue

            numbers.append({"raw": raw, "value": value, "unit": unit})

        return numbers

    def _is_match(self, text_num: dict, real_numbers: list[float]) -> bool:
        """Check if a text number matches any real number within tolerance."""
        tv = text_num["value"]

        for rn in real_numbers:
            if rn == 0 and tv == 0:
                return True
            if rn == 0:
                continue

            if abs(tv) > 1000:
                # Percentage tolerance
                if abs(tv - rn) / abs(rn) <= TOLERANCE_PCT_HIGH:
                    return True
            elif abs(tv) >= 10:
                if abs(tv - rn) <= TOLERANCE_ABS_MEDIUM:
                    return True
            else:
                if abs(tv - rn) <= TOLERANCE_PCT_POINTS:
                    return True

            # Also check raw percentages — compare absolute values
            if text_num["unit"] == "%":
                if abs(abs(tv) - abs(rn)) <= TOLERANCE_PCT_POINTS:
                    return True

        return False
