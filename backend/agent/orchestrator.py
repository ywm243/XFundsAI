"""Agent orchestration main loop.

Flow (max 2 rounds):
  1. LLM receives system prompt + user query
  2. LLM decides to call tools (query_metrics / decompose_change)
  3. ToolValidator validates parameters
  4. Execute tool(s)
  5. Return results to LLM
  6. LLM decides if data is sufficient
     - If yes: generate analysis text
     - If no (and < 2 rounds): call more tools
  7. Post-validate: extract numbers from LLM output, compare against tool data
"""

import json
import logging
from datetime import datetime

from agent.tools import query_metrics, decompose_change, TOOL_DEFINITIONS
from agent.validator import ToolValidator
from agent.post_validator import PostValidator
from agent.memory import AgentMemory
from llm_parser.llm_client import llm_tool_call

logger = logging.getLogger(__name__)

_TOOL_MAP = {
    "query_metrics": query_metrics,
    "decompose_change": decompose_change,
}

MAX_ROUNDS = 2


def _build_system_prompt(user_query: str, context_prompt: str = "") -> str:
    """Build system prompt for the analysis agent."""
    lines = [
        "你是一个专业的外汇交易数据分析助手。你的任务是根据用户的提问，使用提供的工具查询真实数据并进行分析。",
        "",
        "## 规则",
        "1. 使用工具获取数据，不要编造任何数字",
        "2. 每个工具返回的所有数字都是真实数据，你只能基于这些数据进行解读",
        "3. 第一步总是调用 query_metrics 获取汇总数据",
        "4. 如果需要分析变化原因，再调用 decompose_change",
        "5. 分析文本中提到的数字必须与工具返回的数据一致",
        "6. 如果工具返回的数据不足以回答问题，说明缺少什么数据",
        "7. 分析要简洁专业，控制在 300 字以内",
        "8. 使用中文输出",
        "",
    ]

    if context_prompt:
        lines.append(context_prompt)
        lines.append("")

    lines.extend([
        "## 输出要求",
        "输出分析文本即可，不要包含 JSON 或其他格式标记。",
    ])

    return "\n".join(lines)


def run_analysis(
    user_query: str,
    session_id: str = "",
    gatekeep_params: dict | None = None,
) -> dict:
    """Run the full analysis pipeline.

    Args:
        user_query: The user's natural language query.
        session_id: Optional session ID for memory retrieval.
        gatekeep_params: Pre-computed gatekeep params (filters, dates, etc.).

    Returns:
        dict with keys: summary, insights, mode
    """
    # ---- Build context from memory ----
    context_prompt = ""
    if session_id:
        memory = AgentMemory()
        context_prompt = memory.build_context_prompt(session_id)

    system_prompt = _build_system_prompt(user_query, context_prompt)

    # ---- Agent loop ----
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _build_user_prompt(user_query, gatekeep_params)},
    ]

    all_tool_results = []
    tool_call_summary = []

    for round_num in range(MAX_ROUNDS):
        logger.info("Agent round %d/%d", round_num + 1, MAX_ROUNDS)

        result = llm_tool_call(messages=messages, tools=TOOL_DEFINITIONS)

        if result is None:
            return {
                "summary": "抱歉，分析服务暂不可用，请稍后重试。",
                "insights": [],
                "mode": "analyze",
                "error": "LLM tool call failed",
            }

        if result["type"] == "text":
            # LLM generated final analysis text
            analysis_text = result["content"]

            # Post-validate
            validator = PostValidator()
            mismatches = validator.validate(analysis_text, all_tool_results)

            if mismatches:
                logger.warning("Post-validation found %d mismatches", len(mismatches))
                if round_num < MAX_ROUNDS - 1:
                    # Give LLM one more chance to fix
                    messages.append({"role": "assistant", "content": analysis_text})
                    messages.append({
                        "role": "user",
                        "content": _build_correction_prompt(mismatches),
                    })
                    continue

            # Save to memory
            if session_id:
                try:
                    turn_id = int(datetime.now().timestamp())
                    memory.save(session_id, turn_id, user_query, {
                        "reasoning": "tool_calls_completed",
                        "tool_calls": tool_call_summary,
                        "key_entities": _extract_entities(gatekeep_params),
                    })
                except Exception as exc:
                    logger.warning("Failed to save agent memory: %s", exc)

            return {
                "summary": analysis_text,
                "insights": _build_insights_from_tools(all_tool_results),
                "mode": "analyze",
            }

        elif result["type"] == "tool_calls":
            # Execute tool calls
            round_results = []
            for call in result["calls"]:
                func_name = call["function"]
                args = call["arguments"]

                # Validate
                validator = ToolValidator()
                if func_name == "query_metrics":
                    validation_errors = validator.validate_query_metrics(args)
                elif func_name == "decompose_change":
                    validation_errors = validator.validate_decompose_change(args)
                else:
                    validation_errors = [f"未知工具：{func_name}"]

                if validation_errors:
                    error_msg = "；".join(validation_errors)
                    round_results.append({
                        "tool": func_name,
                        "params": args,
                        "error": error_msg,
                    })
                    logger.warning("Validation failed for %s: %s", func_name, error_msg)
                    continue

                # Execute
                try:
                    fn = _TOOL_MAP.get(func_name)
                    if fn:
                        tool_result = fn(**args)
                        round_results.append({
                            "tool": func_name,
                            "params": args,
                            "result": tool_result,
                        })
                        tool_call_summary.append({
                            "tool": func_name,
                            "params": args,
                            "result_summary": _summarize_tool_result(tool_result),
                        })
                        logger.info("Tool %s executed successfully", func_name)
                except Exception as exc:
                    logger.exception("Tool %s failed: %s", func_name, exc)
                    round_results.append({
                        "tool": func_name,
                        "params": args,
                        "error": f"{type(exc).__name__}: {exc}",
                    })

            all_tool_results.extend(round_results)

            # Feed results back to LLM
            messages.append({
                "role": "assistant",
                "content": json.dumps({
                    "tool": "batch_execution",
                    "results": round_results,
                }, ensure_ascii=False),
            })

    # Max rounds reached without text response — fallback
    return {
        "summary": _generate_fallback_summary(all_tool_results),
        "insights": _build_insights_from_tools(all_tool_results),
        "mode": "analyze",
    }


def _build_user_prompt(user_query: str, gatekeep_params: dict | None = None) -> str:
    lines = [f"用户问题：{user_query}"]
    if gatekeep_params:
        filters = {k: v for k, v in gatekeep_params.items()
                   if v not in (None, "", False, [])}
        if filters:
            lines.append(f"已知过滤条件：{json.dumps(filters, ensure_ascii=False)}")
    return "\n".join(lines)


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
    if summary.get("total_trading_volume"):
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
        total = summary.get("total_trading_volume", 0)
        if total:
            parts.append(f"总交易量为 {total:,.0f} 美元")
        change = summary.get("total_change_pct")
        if change is not None:
            direction = "增长" if change >= 0 else "下降"
            parts.append(f"同比{direction} {abs(change):.2f}%")
    return "；".join(parts) + "。" if parts else "暂时无法获取分析数据。"
