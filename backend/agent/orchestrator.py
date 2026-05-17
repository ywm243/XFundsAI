"""Agent orchestration — deterministic analysis pipeline.

Flow:
  1. Determine which dimensions to decompose based on already-specified filters
  2. Auto-execute query_metrics (baseline with comparison) + decompose_change per dimension
  3. Feed all real data to LLM — LLM only generates analysis text (no tools)
  4. Post-validate numbers in LLM output against tool data
"""

import logging
from datetime import datetime

from agent.tools import query_metrics, decompose_change
from services.result_formatter import _metric_label
from agent.post_validator import PostValidator
from agent.memory import AgentMemory
from llm_parser.llm_client import llm_tool_call

logger = logging.getLogger(__name__)

# Three core analysis dimensions
ALL_DIMENSIONS = ["product_type", "bank", "customer"]

DIMENSION_LABELS = {
    "product_type": "产品类型",
    "bank": "机构",
    "customer": "客户",
}

COMPARISON_LABELS = {
    "yoy": "同比",
    "mom": "环比",
}

PRODUCT_TYPE_LABELS = {
    "spot": "即期外汇",
    "fwd": "远期外汇",
    "swap": "外汇掉期",
    "all": "所有交易",
}


def _determine_analysis_dimensions(gatekeep_params: dict | None) -> list[str]:
    """Determine which dimensions to decompose.

    If a dimension is already specified in the filter, exclude it from decomposition.
    E.g. bank_name=浙江分公司 → 机构已指定 → 分析产品和客户维度.
    """
    params = gatekeep_params or {}
    specified = set()

    if params.get("product_type") and params["product_type"] != "all":
        specified.add("product_type")
    if params.get("bank_name"):
        specified.add("bank")
    if params.get("cust_name"):
        specified.add("customer")

    return [d for d in ALL_DIMENSIONS if d not in specified]


def _build_tool_filters(gatekeep_params: dict | None) -> dict:
    """Extract filter keys from gatekeep_params for tools (query_metrics / decompose_change)."""
    params = gatekeep_params or {}
    filters = {}
    if params.get("product_type") and params["product_type"] != "all":
        filters["product_type"] = params["product_type"]
    if params.get("bank_name"):
        filters["bank_name"] = params["bank_name"]
    if params.get("cust_name"):
        filters["cust_name"] = params["cust_name"]
    if params.get("buy_sell"):
        filters["buy_sell"] = params["buy_sell"]
    if params.get("special_states"):
        filters["special_states"] = params["special_states"]
    if params.get("appid"):
        filters["appid"] = params["appid"]
    if params.get("lifecycle_status"):
        filters["lifecycle_status"] = params["lifecycle_status"]
    return filters


def _build_system_prompt(context_prompt: str = "") -> str:
    """Build system prompt for text-only LLM analysis generation."""
    lines = [
        "你是一个专业的外汇交易数据分析助手。",
        "你的任务是根据提供的汇总数据和维度拆解数据，撰写简洁专业的分析文本。",
        "",
        "## 规则",
        "1. 只能使用下面提供的数据，不要编造任何数字",
        "2. 分析文本中提到的数字必须与提供的数据完全一致",
        "3. 分析要简洁专业，控制在 300 字以内",
        "4. 使用中文输出",
        "5. **强制要求**：分析时必须写出具体的客户名称、机构名称、产品名称，不得用泛指代称",
        "",
        "## 输出格式要求",
        "使用以下 markdown 格式输出：",
        "",
        "### 📊 总览",
        "一段总述：总交易量变化额、变化率、主要驱动因素概括。",
        "",
        "### 各维度分析",
        "每个有数据的维度用一个表格：",
        "",
        "**机构维度** / **客户维度** / **产品维度**",
        "| 名称 | 交易量变化 | 贡献度 |",
        "|------|-----------|-------|",
        "| xxx  | +xxx     | xx%   |",
        "",
        "### 📌 总结",
        "1. xxx",
        "2. xxx",
        "3. xxx",
    ]

    if context_prompt:
        lines.append("")
        lines.append(context_prompt)

    return "\n".join(lines)


def _build_data_prompt(
    user_query: str,
    gatekeep_params: dict | None,
    all_tool_results: list[dict],
) -> str:
    """Build a comprehensive user prompt containing all tool data for the LLM."""
    params = gatekeep_params or {}
    lines = [f"用户问题：{user_query}"]

    if params.get("date_start"):
        lines.append(f"时间范围：{params['date_start']} ~ {params['date_end']}")

    # Filter info
    filter_parts = []
    if params.get("product_type") and params["product_type"] != "all":
        pt_label = PRODUCT_TYPE_LABELS.get(params["product_type"], params["product_type"])
        filter_parts.append(f"产品类型={pt_label}")
    if params.get("bank_name"):
        filter_parts.append(f"机构={params['bank_name']}")
    if params.get("cust_name"):
        filter_parts.append(f"客户={params['cust_name']}")
    if filter_parts:
        lines.append(f"过滤条件：{'，'.join(filter_parts)}")

    comparison = params.get("comparison") or "yoy"
    comp_label = COMPARISON_LABELS.get(comparison, comparison)
    lines.append(f"对比方式：{comp_label}")
    lines.append("")

    # Format tool results
    for r in all_tool_results:
        tool = r.get("tool", "")
        result = r.get("result", {})
        error = r.get("error")

        if error:
            lines.append(f"【{tool}】执行出错：{error}\n")
            continue

        if tool == "query_metrics":
            summary = result.get("summary", {})
            total = summary.get("total_trading_volume", 0)
            prev = summary.get("prev_total_trading_volume", 0)
            change = summary.get("total_change", 0)
            change_pct = summary.get("total_change_pct", 0)
            lines.append("【汇总数据】")
            lines.append(f"  当前期总交易量：{total:,.2f}")
            lines.append(f"  上期（{comp_label}）总交易量：{prev:,.2f}")
            lines.append(f"  变化量：{change:,.2f}（{change_pct:+.2f}%）")
            lines.append("")

        elif tool == "decompose_change":
            dim = result.get("by_dimension", "")
            dim_label = DIMENSION_LABELS.get(dim, dim)
            drivers = result.get("drivers", [])

            lines.append(f"【按{dim_label}拆解变化（贡献度排序）】")
            if not drivers:
                lines.append("  （无拆解数据）")
            for d in drivers:
                lines.append(
                    f"  - {d['dimension_value']}: "
                    f"当前值={d['current_value']:,.2f}, "
                    f"上期={d['previous_value']:,.2f}, "
                    f"变化={d['change_value']:,.2f}（贡献度{d['contrib_pct']:+.2f}%）"
                )
            lines.append("")

    lines.append("请严格按照系统提示中的输出格式要求来组织分析文本，使用表格展示各维度数据，并以1、2、3总结结尾。")
    return "\n".join(lines)


def run_analysis(
    user_query: str,
    session_id: str = "",
    gatekeep_params: dict | None = None,
) -> dict:
    """Run the deterministic analysis pipeline.

    Args:
        user_query: The user's natural language query.
        session_id: Optional session ID for memory retrieval.
        gatekeep_params: Pre-computed gatekeep params (filters, dates, etc.).

    Returns:
        dict with keys: summary, insights, mode
    """
    # ---- Build context from memory ----
    context_prompt = ""
    memory = None
    if session_id:
        memory = AgentMemory()
        context_prompt = memory.build_context_prompt(session_id)

    params = gatekeep_params or {}
    date_start = params.get("date_start")
    date_end = params.get("date_end")

    if not date_start or not date_end:
        return {
            "summary": "缺少时间范围，无法进行变化原因分析。",
            "insights": [],
            "mode": "analyze",
        }

    # ---- Determine dimensions and execute tools ----
    dimensions = _determine_analysis_dimensions(params)
    comparison = params.get("comparison") or "yoy"
    filters = _build_tool_filters(params)

    all_tool_results: list[dict] = []
    tool_call_summary: list[dict] = []

    # Step 1: Baseline query with comparison
    logger.info("Auto-execute: query_metrics (baseline, %s)", comparison)
    try:
        baseline = query_metrics(
            metrics=["trading_volume"],
            filters=filters,
            date_start=date_start,
            date_end=date_end,
            comparison=comparison,
        )
        all_tool_results.append({"tool": "query_metrics", "result": baseline})
        tool_call_summary.append({
            "tool": "query_metrics",
            "params": {"date_start": date_start, "date_end": date_end, "comparison": comparison, "filters": filters},
            "result_summary": _summarize_tool_result(baseline),
        })
        logger.info("Baseline: total=%s, change=%s%%",
                     baseline.get("summary", {}).get("total_trading_volume"),
                     baseline.get("summary", {}).get("total_change_pct"))
    except Exception as exc:
        logger.exception("Baseline query failed: %s", exc)
        all_tool_results.append({"tool": "query_metrics", "error": f"{type(exc).__name__}: {exc}"})

    # Step 2: Decompose by each dimension
    for dim in dimensions:
        dim_label = DIMENSION_LABELS.get(dim, dim)
        logger.info("Auto-execute: decompose_change by %s", dim_label)
        try:
            decomp = decompose_change(
                metric="trading_volume",
                date_start=date_start,
                date_end=date_end,
                comparison=comparison,
                by_dimension=dim,
                top_n=8,
                filters=filters,
            )
            # Debug: log driver values to verify names
            for d in decomp.get("drivers", [])[:3]:
                logger.info("  driver: [%s] value=%.2f contrib=%.2f%%",
                            d.get("dimension_value", "?"), d.get("current_value", 0), d.get("contrib_pct", 0))
            all_tool_results.append({"tool": "decompose_change", "result": decomp})
            tool_call_summary.append({
                "tool": "decompose_change",
                "params": {"by_dimension": dim, "date_start": date_start, "date_end": date_end, "comparison": comparison},
                "result_summary": f"按{dim_label}拆解，{len(decomp.get('drivers', []))}条",
            })
            logger.info("Decompose by %s: %d drivers", dim_label, len(decomp.get("drivers", [])))
        except Exception as exc:
            logger.exception("Decompose by %s failed: %s", dim_label, exc)
            all_tool_results.append({"tool": "decompose_change", "error": f"{type(exc).__name__}: {exc}"})

    # ---- Extract structured data for frontend ----
    analysis_data = _extract_analysis_data(all_tool_results, parsed=gatekeep_params)

    # ---- LLM generates analysis text from data (no tools) ----
    system_prompt = _build_system_prompt(context_prompt)
    data_prompt = _build_data_prompt(user_query, params, all_tool_results)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": data_prompt},
    ]

    logger.info("Calling LLM for analysis text generation")
    result = llm_tool_call(messages=messages, tools=[], temperature=0.1, max_tokens=2048, timeout=120)

    if result and result["type"] == "text":
        analysis_text = result["content"]

        # Post-validate
        validator = PostValidator()
        mismatches = validator.validate(analysis_text, all_tool_results)

        if mismatches:
            logger.warning("Post-validation found %d mismatches, attempting correction", len(mismatches))
            messages.append({"role": "assistant", "content": analysis_text})
            messages.append({
                "role": "user",
                "content": _build_correction_prompt(mismatches),
            })
            retry = llm_tool_call(messages=messages, tools=[], temperature=0.1, max_tokens=2048, timeout=120)
            if retry and retry["type"] == "text":
                analysis_text = retry["content"]
                mismatches = validator.validate(analysis_text, all_tool_results)
                if mismatches:
                    logger.warning("Correction still has %d mismatches, using original", len(mismatches))

        # Save to memory
        if session_id and memory:
            try:
                turn_id = int(datetime.now().timestamp())
                memory.save(session_id, turn_id, user_query, {
                    "reasoning": "deterministic_analysis",
                    "tool_calls": tool_call_summary,
                    "key_entities": _extract_entities(gatekeep_params),
                })
            except Exception as exc:
                logger.warning("Failed to save agent memory: %s", exc)

        return {
            "summary": analysis_text,
            "insights": _build_insights_from_tools(all_tool_results),
            "mode": "analyze",
            "analysis_data": analysis_data,
        }

    # LLM failed — template fallback
    logger.warning("LLM text generation failed, using template fallback")
    return {
        "summary": _generate_fallback_summary(all_tool_results),
        "insights": _build_insights_from_tools(all_tool_results),
        "mode": "analyze",
        "analysis_data": analysis_data,
    }


def _build_correction_prompt(mismatches: list) -> str:
    lines = ["你输出的分析与实际数据不一致，请修正："]
    for m in mismatches:
        lines.append(f"- {m}")
    lines.append("请重新输出修正后的分析文本。")
    return "\n".join(lines)


def _summarize_tool_result(result: dict) -> str:
    """Create a short summary of tool result for memory."""
    summary = result.get("summary", {})
    data = result.get("data", [])
    parts = [f"返回{len(data)}条数据"]
    if summary.get("total_trading_volume") is not None:
        parts.append(f"总交易量={summary['total_trading_volume']}")
    if summary.get("total_change_pct") is not None:
        parts.append(f"变化率={summary['total_change_pct']}%")
    return ", ".join(parts)


def _build_insights_from_tools(all_results: list) -> list:
    """Build insight dicts from tool results for frontend display."""
    insights = []
    for r in all_results:
        if "result" not in r:
            continue
        result = r["result"]
        summary = result.get("summary", {})
        if summary.get("total_change_pct") is not None:
            direction = "增长" if summary.get("total_change", 0) >= 0 else "下降"
            insights.append({
                "type": "growth" if summary.get("total_change", 0) >= 0 else "risk",
                "title": "指标变化",
                "detail": f"总交易量{direction}了{abs(summary.get('total_change', 0)):,.0f}美元（{summary['total_change_pct']:+.2f}%）",
            })
    return insights


def _extract_analysis_data(all_tool_results: list[dict], parsed: dict | None = None) -> dict:
    """Extract structured analysis data from tool results for frontend rendering."""
    analysis = {
        "baseline": {},
        "dimensions": [],
        "metric_label": _metric_label(parsed) if parsed else "交易量",
    }
    for r in all_tool_results:
        if "result" not in r:
            continue
        result = r["result"]
        if r["tool"] == "query_metrics":
            summary = result.get("summary", {})
            analysis["baseline"] = {
                "total_trading_volume": summary.get("total_trading_volume"),
                "prev_total_trading_volume": summary.get("prev_total_trading_volume"),
                "total_change": summary.get("total_change"),
                "total_change_pct": summary.get("total_change_pct"),
            }
        elif r["tool"] == "decompose_change":
            dim = result.get("by_dimension", "")
            dim_label = DIMENSION_LABELS.get(dim, dim)
            drivers = result.get("drivers", [])
            analysis["dimensions"].append({
                "dimension": dim,
                "dim_label": dim_label,
                "drivers": [
                    {
                        "dimension_value": d["dimension_value"],
                        "current_value": d["current_value"],
                        "previous_value": d["previous_value"],
                        "change_value": d["change_value"],
                        "contrib_pct": d["contrib_pct"],
                    }
                    for d in drivers
                ],
            })
    return analysis


def _extract_entities(gatekeep_params: dict | None) -> dict:
    """Extract key entities from gatekeep params for memory."""
    if not gatekeep_params:
        return {}
    return {
        k: gatekeep_params[k]
        for k in ("dimension", "appid", "product_type", "bank_name", "cust_name")
        if gatekeep_params.get(k)
    }


def _generate_fallback_summary(all_tool_results: list) -> str:
    """Generate a simple template-based summary when LLM fails."""
    parts = []
    for r in all_tool_results:
        if "result" not in r:
            continue
        result = r["result"]
        summary = result.get("summary", {})
        total = summary.get("total_trading_volume")
        if total is not None:
            parts.append(f"总交易量为 {total:,.0f} 美元")
        change = summary.get("total_change_pct")
        if change is not None:
            direction = "增长" if change >= 0 else "下降"
            parts.append(f"同比{direction} {abs(change):.2f}%")
    return "；".join(parts) + "。" if parts else "暂时无法获取分析数据。"
