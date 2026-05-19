# backend/langgraph/registry.py
"""Agent registry — capability definitions and routing metadata."""

from dataclasses import dataclass, field


@dataclass
class AgentCapability:
    """Capability definition for a single Agent."""
    name: str
    keywords: list[str]
    capabilities: list[str]
    NOT_capabilities: list[str]
    subgraph: str = ""


AGENT_REGISTRY: dict[str, AgentCapability] = {
    "BI": AgentCapability(
        name="BI",
        keywords=["交易量", "排名", "套保率", "金额", "笔数",
                  "银行", "客户", "同比", "环比", "汇总", "趋势",
                  "外汇", "交易", "美元", "人民币"],
        capabilities=["聚合查询", "排名查询", "套保率计算",
                      "同比环比对比", "条件过滤"],
        NOT_capabilities=["预测", "预估", "趋势预测",
                          "风险评估", "异常检测", "汇率报价",
                          "客户信用", "合规检查"],
        subgraph="bi_agent",
    ),
}


def match_keywords(text: str) -> dict[str, float]:
    """Score each agent by keyword match ratio.

    Returns dict of {agent_name: score}.
    """
    scores: dict[str, float] = {}
    for name, cap in AGENT_REGISTRY.items():
        hits = sum(1 for kw in cap.keywords if kw in text)
        scores[name] = hits / max(len(cap.keywords), 1)
    return scores


def check_not_capabilities(text: str) -> list[str]:
    """Check if text hits any NOT_capabilities across all agents.

    Returns list of agents with blocked capabilities hit.
    """
    blocked = []
    for name, cap in AGENT_REGISTRY.items():
        for nc in cap.NOT_capabilities:
            if nc in text:
                blocked.append(name)
                break
    return blocked


PRICING_KEYWORDS = [
    "询价", "报价", "结汇", "购汇", "买汇", "卖汇",
    "比价", "点差", "成交", "下单", "多少钱",
    "汇率", "价格", "即期", "远期", "掉期",
]


def match_pricing_keywords(text: str) -> float:
    """返回文本匹配pricing关键词的得分"""
    if not text:
        return 0.0
    count = 0
    for kw in PRICING_KEYWORDS:
        if kw in text:
            count += 1
    return min(count / max(len(PRICING_KEYWORDS), 1), 1.0)
