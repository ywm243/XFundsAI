"""Tool parameter validation with Chinese error messages.

Validates parameters before tool execution, returns human-readable
Chinese error descriptions that the LLM can self-heal from.
"""

from agent.tools import METRICS, DIMENSIONS

_KNOWN_METRICS = set(METRICS.keys())
_KNOWN_DIMENSIONS = set(DIMENSIONS.keys())
_VALID_COMPARISONS = {"yoy", "mom"}


class ToolValidator:
    """Validate tool parameters and return Chinese error messages."""

    @staticmethod
    def validate_query_metrics(params: dict) -> list[str]:
        errors = []

        metrics = params.get("metrics", [])
        if not metrics:
            errors.append("参数「metrics」不能为空，请指定要查询的指标")
        else:
            unknown = [m for m in metrics if m not in _KNOWN_METRICS]
            if unknown:
                known_str = "、".join(sorted(_KNOWN_METRICS))
                errors.append(f"未知指标「{'、'.join(unknown)}」，当前支持的指标：{known_str}")

        dimensions = params.get("dimensions", [])
        if dimensions:
            unknown_dim = [d for d in dimensions if d not in _KNOWN_DIMENSIONS]
            if unknown_dim:
                known_dim = "、".join(sorted(_KNOWN_DIMENSIONS))
                errors.append(f"未知维度「{'、'.join(unknown_dim)}」，当前支持的维度：{known_dim}")

        top_n = params.get("top_n", 0)
        if top_n and not (1 <= top_n <= 100):
            errors.append(f"参数「top_n」必须介于 1~100 之间，当前值为 {top_n}")

        date_start = params.get("date_start", "")
        date_end = params.get("date_end", "")
        if date_start and date_end and date_start > date_end:
            errors.append(f"日期范围有误：开始日期 {date_start} 晚于结束日期 {date_end}")

        comparison = params.get("comparison", "")
        if comparison and comparison not in _VALID_COMPARISONS:
            errors.append(f"对比模式「{comparison}」不支持，请使用 yoy（同比）或 mom（环比）")

        return errors

    @staticmethod
    def validate_decompose_change(params: dict) -> list[str]:
        errors = []

        metric = params.get("metric", "")
        if not metric:
            errors.append("参数「metric」不能为空，请指定要分析的指标")
        elif metric not in _KNOWN_METRICS:
            known_str = "、".join(sorted(_KNOWN_METRICS))
            errors.append(f"未知指标「{metric}」，当前支持的指标：{known_str}")

        comparison = params.get("comparison", "")
        if not comparison:
            errors.append("参数「comparison」不能为空，必须指定 yoy（同比）或 mom（环比）")
        elif comparison not in _VALID_COMPARISONS:
            errors.append(f"对比模式「{comparison}」不支持，请使用 yoy（同比）或 mom（环比）")

        by_dimension = params.get("by_dimension", "")
        if by_dimension and by_dimension not in _KNOWN_DIMENSIONS:
            known_dim = "、".join(sorted(_KNOWN_DIMENSIONS))
            errors.append(f"未知维度「{by_dimension}」，当前支持的维度：{known_dim}")

        date_start = params.get("date_start", "")
        date_end = params.get("date_end", "")
        if not date_start or not date_end:
            errors.append("参数「date_start」和「date_end」不能为空，请指定分析的时间范围")
        if date_start and date_end and date_start > date_end:
            errors.append(f"日期范围有误：开始日期 {date_start} 晚于结束日期 {date_end}")

        top_n = params.get("top_n", 5)
        if top_n and not (1 <= top_n <= 100):
            errors.append(f"参数「top_n」必须介于 1~100 之间，当前值为 {top_n}")

        return errors
