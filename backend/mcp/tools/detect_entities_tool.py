# backend/mcp/tools/detect_entities_tool.py
"""MCP tool: detect_entities — extract bank/customer/APP entities from text."""

import json
import logging
import os
import re
from mcp.server.fastmcp import FastMCP
from openai import OpenAI
from db.mysql_store import get_conn

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def detect_entities(text: str) -> dict:
        """Detect bank names, customer names, and APP IDs from text.

        Uses LLM + MySQL rule lookup for entity resolution.

        Args:
            text: Natural language text.

        Returns:
            dict with keys: banks (list), customers (list), app_ids (list).
        """
        # First try LLM extraction
        api_key = os.environ.get("LLM_API_KEY", "")
        base_url = os.environ.get("LLM_BASE_URL", "")
        model = os.environ.get("LLM_MODEL", "")
        result = {"banks": [], "customers": [], "app_ids": []}

        if api_key and base_url and model:
            try:
                client = OpenAI(api_key=api_key, base_url=base_url)
                resp = client.chat.completions.create(
                    model=model,
                    temperature=0.0,
                    messages=[{"role": "user", "content": (
                        f"从文本中提取实体，返回JSON：\n"
                        f'{{"banks":["银行名"],"customers":["客户名"],"app_ids":["APPID"]}}\n'
                        f"无匹配返回空数组。文本：{text}"
                    )}],
                    timeout=10,
                )
                content = resp.choices[0].message.content or "{}"
                m = re.search(r"\{.*\}", content, re.DOTALL)
                if m:
                    result = json.loads(m.group(1))
            except Exception as exc:
                logger.warning("detect_entities LLM failed: %s", exc)

        # Fallback: match against known bank names from MySQL
        if not result.get("banks"):
            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT display_name FROM rule_items "
                        "WHERE category = 'bank_name' AND is_active = 1"
                    )
                    for row in cur.fetchall():
                        name = row["display_name"]
                        if name and name in text:
                            result["banks"].append(row["display_value"] or name)
            finally:
                conn.close()

        return result
