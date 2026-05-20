"""LLM API client — OpenAI-compatible (阿里云 DashScope / DeepSeek / OpenRouter)."""

import json
import logging
import os
import re

from openai import OpenAI
from llm_parser.quality_router import quality_router
from db.mysql_store import insert_token_usage
from tools.registry import ToolRegistry
import time
import threading

logger = logging.getLogger(__name__)

_json_block_re = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def _write_token_log_async(request_id: str, session_id: str, call_site: str,
                            model_tier: str, model_name: str,
                            prompt_tokens: int, completion_tokens: int,
                            total_tokens: int, duration_ms: float):
    """fire-and-forget 写入 token_usage_log，不阻塞主调用"""
    try:
        insert_token_usage(request_id, session_id, call_site,
                          model_tier, model_name, prompt_tokens,
                          completion_tokens, total_tokens, duration_ms)
    except Exception:
        logger.debug("token_usage_log write failed for %s", request_id, exc_info=True)
        pass  # 写入失败不影响业务


def _extract_json(text: str) -> dict | None:
    m = _json_block_re.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    return None


def _fields_defaults() -> dict:
    return {
        "product_type": "all",
        "date_start": "",
        "date_end": "",
        "special_states": "",
        "lifecycle_status": "",
        "buy_sell": "",
        "bank_name": "",
        "cust_name": "",
        "aggregate": False,
        "top_n": None,
        "amount_filter": None,
        "dimension": "bank",
        "hedge_ratio": False,
        "appid": None,
        "profit_type": [],
    }


def llm_parse(text: str, system_prompt: str,
              task: str = "bi_parse", context_size_hint: int = 0,
              request_id: str = "", session_id: str = "") -> dict | None:
    """Call LLM to parse NL text into structured params.

    Uses QualityRouter for model selection and tracks token usage.
    """
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")

    if not api_key or not base_url:
        logger.warning(
            "LLM not configured: LLM_API_KEY=%s, LLM_BASE_URL=%s",
            "SET" if api_key else "MISSING",
            base_url or "MISSING",
        )
        return None

    profile = quality_router.route(task, context_size_hint)
    model = profile["model"]
    max_tokens = profile["max_tokens"]
    temperature = profile["temperature"]

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    t0 = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
            timeout=30,
        )
        # 读取 usage 并 fire-and-forget 写入
        usage = response.usage
        if usage:
            duration_ms = (time.monotonic() - t0) * 1000
            t = threading.Thread(target=_write_token_log_async, args=(
                request_id, session_id, task, profile["tier"], model,
                usage.prompt_tokens, usage.completion_tokens,
                usage.total_tokens, duration_ms
            ))
            t.daemon = True
            t.start()

        content = response.choices[0].message.content
        if not content:
            logger.warning("LLM returned empty content")
            return None

        result = _extract_json(content)
        if result is None:
            logger.warning("Failed to parse JSON from LLM response: %.200s", content)
            return None

        defaults = _fields_defaults()
        for key, default in defaults.items():
            result.setdefault(key, default)

        logger.info("LLM parse success (model=%s, tier=%s)", model, profile["tier"])
        return result

    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return None


def llm_chat(system_prompt: str, user_prompt: str,
             task: str = "llm_chat", context_size_hint: int = 0,
             request_id: str = "", session_id: str = "",
             timeout: int = 120) -> str | None:
    """Call LLM for free-text chat (analysis, explanation, etc.), returns text response.

    Args:
        timeout: Request timeout in seconds. Use shorter values (15-30) for simple tasks.
    """
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")

    if not api_key or not base_url:
        logger.warning("LLM not configured for chat")
        return None

    profile = quality_router.route(task, context_size_hint)
    model = profile["model"]
    max_tokens = profile["max_tokens"]
    temperature = profile["temperature"]

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    t0 = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=timeout,
        )
        # 读取 usage 并 fire-and-forget 写入
        usage = response.usage
        if usage:
            duration_ms = (time.monotonic() - t0) * 1000
            t = threading.Thread(target=_write_token_log_async, args=(
                request_id, session_id, task, profile["tier"], model,
                usage.prompt_tokens, usage.completion_tokens,
                usage.total_tokens, duration_ms
            ))
            t.daemon = True
            t.start()

        content = response.choices[0].message.content
        return content or None
    except Exception as exc:
        logger.warning("LLM chat call failed: %s", exc)
        return None


def _attempt_repair(args: dict, schema: dict, error) -> dict:
    """尝试修复常见的 LLM 输出错误（缺失必填字段填充默认值、类型转换）"""
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    for key in required:
        if key not in args and key in properties:
            default = properties[key].get("default")
            if default is not None:
                args[key] = default
        if key in args and key in properties:
            ptype = properties[key].get("type", "")
            if ptype == "number" and isinstance(args[key], str):
                try:
                    args[key] = float(args[key])
                except ValueError:
                    pass
            elif ptype == "integer" and isinstance(args[key], str):
                try:
                    args[key] = int(args[key])
                except ValueError:
                    pass
    return args


def llm_tool_call(
    messages: list[dict],
    tools: list[dict],
    task: str = "analysis_text", context_size_hint: int = 0,
    request_id: str = "", session_id: str = "",
    temperature: float = 0.1,
    max_tokens: int = 4096,
    timeout: int = 60,
) -> dict | None:
    """Call LLM with tool calling support.

    Args:
        messages: Conversation messages (system + user/assistant).
        tools: OpenAI-compatible tool definitions.
        task: Task name for QualityRouter routing.
        context_size_hint: Context size estimate for tier upgrade decisions.
        request_id: Request ID for usage tracking.
        session_id: Session ID for usage tracking.
        temperature: Sampling temperature (default 0.1 for precision).
        max_tokens: Max output tokens.
        timeout: Request timeout in seconds.

    Returns:
        dict with either:
          - {"type": "tool_calls", "calls": [...]}  — LLM wants to call tools
          - {"type": "text", "content": "..."}       — LLM final response
          - None on failure
    """
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")

    if not api_key or not base_url:
        logger.warning("LLM not configured for tool calling")
        return None

    # 如果 task 在 QualityRouter 中，用 profile 覆盖调用方传入的默认值
    if task in quality_router.TASK_PROFILES:
        profile = quality_router.route(task, context_size_hint)
        model = profile["model"]
        max_tokens = profile["max_tokens"]
        temperature = profile["temperature"]
        tier = profile["tier"]
    else:
        model = os.environ.get("LLM_MODEL_PRO", os.environ.get("LLM_MODEL", ""))
        tier = "pro"
        if not model:
            logger.warning("LLM not configured for tool calling (no model)")
            return None

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    t0 = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=max_tokens,
            timeout=timeout,
        )
        # 读取 usage 并 fire-and-forget 写入
        usage = response.usage
        if usage:
            duration_ms = (time.monotonic() - t0) * 1000
            t = threading.Thread(target=_write_token_log_async, args=(
                request_id, session_id, task, tier, model,
                usage.prompt_tokens, usage.completion_tokens,
                usage.total_tokens, duration_ms
            ))
            t.daemon = True
            t.start()

        choice = response.choices[0]
        msg = choice.message

        if msg.tool_calls:
            calls = []
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                # JSON Schema validation + auto-repair
                fn_name = tc.function.name
                tool_def = ToolRegistry.get(fn_name)
                if tool_def and tool_def.input_schema:
                    try:
                        import jsonschema
                        jsonschema.validate(args, tool_def.input_schema)
                    except jsonschema.ValidationError as e:
                        logger.warning(
                            "Tool call schema validation failed for %s: %s",
                            fn_name, e.message,
                        )
                        try:
                            args = _attempt_repair(args, tool_def.input_schema, e)
                        except Exception:
                            pass
                    except ImportError:
                        pass  # jsonschema not installed, skip validation
                calls.append({
                    "id": tc.id,
                    "function": tc.function.name,
                    "arguments": args,
                })
            return {"type": "tool_calls", "calls": calls}

        if msg.content:
            return {"type": "text", "content": msg.content}

        return None

    except Exception as exc:
        logger.warning("LLM tool call failed: %s", exc)
        return None
