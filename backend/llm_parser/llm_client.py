"""LLM API client — OpenAI-compatible (阿里云 DashScope / DeepSeek / OpenRouter)."""

import json
import logging
import os
import re

from openai import OpenAI

logger = logging.getLogger(__name__)

_json_block_re = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


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
        "buy_sell": "",
        "bank_name": "",
        "cust_name": "",
        "aggregate": False,
        "top_n": None,
        "amount_filter": None,
        "dimension": "bank",
        "hedge_ratio": False,
        "appid": None,
    }


def llm_parse(text: str, system_prompt: str) -> dict | None:
    """Call LLM to parse NL text into structured params.

    Reads configuration from environment variables:
      LLM_API_KEY  — API key (required)
      LLM_BASE_URL — API base URL (required, e.g. https://dashscope.aliyuncs.com/compatible-mode/v1)
      LLM_MODEL    — Model name (required, e.g. qwen-plus)

    Supports any OpenAI-compatible API:
      阿里云 DashScope:  https://dashscope.aliyuncs.com/compatible-mode/v1
      DeepSeek:          https://api.deepseek.com
      OpenRouter:        https://openrouter.ai/api/v1
    """
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")
    model = os.environ.get("LLM_MODEL", "")

    if not api_key or not base_url or not model:
        logger.warning(
            "LLM not configured: LLM_API_KEY=%s, LLM_BASE_URL=%s, LLM_MODEL=%s",
            "SET" if api_key else "MISSING",
            base_url or "MISSING",
            model or "MISSING",
        )
        return None

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            timeout=2,
        )
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

        logger.info("LLM parse success (model=%s)", model)
        return result

    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return None


def llm_chat(system_prompt: str, user_prompt: str, timeout: int = 120) -> str | None:
    """Call LLM for free-text chat (analysis, explanation, etc.), returns text response.

    Args:
        timeout: Request timeout in seconds. Use shorter values (15-30) for simple tasks.
    """
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")
    model = os.environ.get("LLM_MODEL", "")

    if not api_key or not base_url or not model:
        logger.warning("LLM not configured for chat")
        return None

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=timeout,
        )
        content = response.choices[0].message.content
        return content or None
    except Exception as exc:
        logger.warning("LLM chat call failed: %s", exc)
        return None


def llm_tool_call(
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 4096,
    timeout: int = 60,
) -> dict | None:
    """Call LLM with tool calling support.

    Args:
        messages: Conversation messages (system + user/assistant).
        tools: OpenAI-compatible tool definitions.
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
    model = os.environ.get("LLM_MODEL", "")

    if not api_key or not base_url or not model:
        logger.warning("LLM not configured for tool calling")
        return None

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

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
        choice = response.choices[0]
        msg = choice.message

        if msg.tool_calls:
            calls = []
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
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
