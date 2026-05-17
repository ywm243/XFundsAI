# backend/mcp/tools/llm_tool.py
"""MCP tool: llm_chat — send prompts to DeepSeek LLM."""

import logging
import os
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """Register llm_chat tool on the given FastMCP instance."""

    @mcp.tool()
    def llm_chat(prompt: str) -> str:
        """Send a prompt to the configured LLM and return its response.

        Uses the same configuration as the main parser:
          LLM_API_KEY, LLM_BASE_URL, LLM_MODEL from environment / .env.

        Args:
            prompt: The text prompt to send to the LLM.

        Returns:
            The LLM's text response, or an error message on failure.
        """
        api_key = os.environ.get("LLM_API_KEY", "")
        base_url = os.environ.get("LLM_BASE_URL", "")
        model = os.environ.get("LLM_MODEL", "")

        if not api_key or not base_url or not model:
            return "LLM not configured: missing LLM_API_KEY/LLM_BASE_URL/LLM_MODEL"

        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
                timeout=30,
            )
            content = response.choices[0].message.content
            logger.info("llm_chat: model=%s, len=%d", model, len(content or ""))
            return content or "(empty response)"
        except Exception as exc:
            logger.warning("llm_chat failed: %s", exc)
            return f"LLM call failed: {exc}"
