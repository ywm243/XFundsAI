"""QualityRouter — 按任务复杂度路由到最优模型，提升准确性"""
import os
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


class RouteResult(TypedDict):
    model: str
    tier: str
    max_tokens: int
    temperature: float


class QualityRouter:
    """让每次 LLM 调用都用最优配置产出最准确结果

    不是省 token，不是降级。简单任务用 Flash 保持速度，
    复杂分析/长上下文用 Pro 保证准确性。
    """

    MODEL_TIERS = {
        "flash": os.getenv("LLM_MODEL_FLASH", "deepseek-v4-flash"),
        "pro": os.getenv("LLM_MODEL_PRO", "deepseek-v4-pro"),
    }

    TASK_PROFILES = {
        "entity_extract":  {"tier": "flash", "max_tokens": 200,  "temperature": 0.0},
        "date_parse":      {"tier": "flash", "max_tokens": 100,  "temperature": 0.0},
        "context_resolve": {"tier": "flash", "max_tokens": 300,  "temperature": 0.0},
        "bi_parse":        {"tier": "flash", "max_tokens": 500,  "temperature": 0.1},
        "pricing_parse":   {"tier": "flash", "max_tokens": 300,  "temperature": 0.0},
        "wiki_rule_read":  {"tier": "flash", "max_tokens": 500,  "temperature": 0.0},
        "summary_generate":{"tier": "flash", "max_tokens": 800,  "temperature": 0.3},
        "analysis_text":   {"tier": "pro",   "max_tokens": 2048, "temperature": 0.1},
        "analysis_retry":  {"tier": "pro",   "max_tokens": 2048, "temperature": 0.1},
        "insight_generate":{"tier": "pro",   "max_tokens": 1024, "temperature": 0.3},
    }

    CONTEXT_UPGRADE_THRESHOLD = 4000

    def route(self, task: str, context_size_hint: int = 0) -> RouteResult:
        """返回 {model, tier, max_tokens, temperature}

        Args:
            task: 任务名（TASK_PROFILES 的 key）
            context_size_hint: 上下文大小估计（字符数），用于决定是否升级到 Pro
        """
        if task not in self.TASK_PROFILES:
            logger.warning("Unknown task '%s', falling back to bi_parse", task)
            profile = dict(self.TASK_PROFILES["bi_parse"])
        else:
            profile = dict(self.TASK_PROFILES[task])

        # 长上下文解析自动升级到 Pro，保证准确
        if (
            profile["tier"] == "flash"
            and task in ("bi_parse", "pricing_parse")
            and context_size_hint > self.CONTEXT_UPGRADE_THRESHOLD
        ):
            profile["tier"] = "pro"

        profile["model"] = self.MODEL_TIERS[profile["tier"]]
        return profile


# 全局单例
quality_router = QualityRouter()
