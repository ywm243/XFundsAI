"""统一工具注册表 — 装饰器注册 + 自动发现"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class ToolDef:
    name: str
    fn: Callable
    input_schema: dict
    output_schema: dict | None = None
    category: str = "system"
    writes: bool = False
    requires_auth: bool = False
    model_tier: str = "flash"


class ToolRegistry:
    _tools: dict[str, ToolDef] = {}

    @classmethod
    def register(cls, name: str, category: str = "system",
                 input_schema: dict = None, output_schema: dict = None,
                 writes: bool = False, requires_auth: bool = False,
                 model_tier: str = "flash"):
        """装饰器：注册工具"""
        def decorator(fn):
            cls._tools[name] = ToolDef(
                name=name, fn=fn,
                input_schema=input_schema or {},
                output_schema=output_schema,
                category=category,
                writes=writes,
                requires_auth=requires_auth,
                model_tier=model_tier,
            )
            return fn
        return decorator

    @classmethod
    def get(cls, name: str) -> ToolDef | None:
        return cls._tools.get(name)

    @classmethod
    def list(cls, category: str = None) -> list[ToolDef]:
        tools = list(cls._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    @classmethod
    def list_names(cls, category: str = None) -> list[str]:
        return [t.name for t in cls.list(category)]

    @classmethod
    def as_openai_tools(cls, category: str = None) -> list[dict]:
        """转为 OpenAI tool-calling 格式"""
        tools = []
        for t in cls.list(category):
            tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": getattr(t.fn, "__doc__", "") or "",
                    "parameters": t.input_schema,
                }
            })
        return tools
