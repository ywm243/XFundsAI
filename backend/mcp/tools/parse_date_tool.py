# backend/mcp/tools/parse_date_tool.py
"""MCP tool: parse_date — extract date range from natural language text."""

import json
import logging
import os
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def parse_date(text: str) -> dict:
        """Extract a date range from natural language text using LLM.

        Args:
            text: Natural language text containing date references.

        Returns:
            dict with keys: date_start (str), date_end (str), display (str).
            Empty dict if no date found.
        """
        api_key = os.environ.get("LLM_API_KEY", "")
        base_url = os.environ.get("LLM_BASE_URL", "")
        model = os.environ.get("LLM_MODEL", "")
        if not api_key or not base_url or not model:
            return {}

        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                temperature=0.0,
                messages=[{"role": "user", "content": (
                    f"从以下文本中提取日期范围，返回JSON格式：\n"
                    f'{{"date_start":"YYYY-MM-DD","date_end":"YYYY-MM-DD",'
                    f'"display":"中文描述"}}\n'
                    f"如果无明确日期返回{{}}\n文本：{text}"
                )}],
                timeout=10,
            )
            content = resp.choices[0].message.content or "{}"
            # Extract JSON from response
            import re
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                return json.loads(m.group(1))
            return {}
        except Exception as exc:
            logger.warning("parse_date failed: %s", exc)
            return {}
