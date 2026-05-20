# backend/pricing/sanctions.py
"""制裁名单筛查 — 本地维护的受限实体名单 + 模糊匹配

注意：生产环境应接入 OFAC SDN / 联合国 / 欧盟制裁名单 API。
本模块提供本地名单作为离线 fallback 和开发/测试使用。
"""

import re
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 制裁名单（本地维护）
# ═══════════════════════════════════════════════════════════════

# 受限实体（模糊匹配时会忽略大小写、空格、标点）
_BLOCKED_ENTITIES: list[dict] = [
    # ── OFAC SDN 示例（中文名 / 英文名 / 别名） ──
    {"name": "朝鲜贸易银行", "aliases": ["Foreign Trade Bank", "FTB", "Mooyokbank"],
     "program": "DPRK", "risk": "HIGH"},
    {"name": "朝鲜光鲜银行", "aliases": ["Kwangson Banking Corp", "KBC"],
     "program": "DPRK", "risk": "HIGH"},
    {"name": "伊朗中央银行", "aliases": ["Central Bank of Iran", "Bank Markazi"],
     "program": "IRAN", "risk": "HIGH"},
    {"name": "伊朗国家石油公司", "aliases": ["NIOC", "National Iranian Oil Company"],
     "program": "IRAN", "risk": "HIGH"},
    {"name": "苏丹革命阵线", "aliases": ["SRF", "Sudan Revolutionary Front"],
     "program": "SUDAN", "risk": "MEDIUM"},
    {"name": "叙利亚中央银行", "aliases": ["Central Bank of Syria", "CBS"],
     "program": "SYRIA", "risk": "HIGH"},

    # ── 中国公安部 / 反洗钱名单示例 ──
    {"name": "东伊运组织", "aliases": ["ETIM", "Turkistan Islamic Party", "TIP"],
     "program": "TERRORISM", "risk": "HIGH"},

    # ── 联合国制裁示例 ──
    {"name": "朝鲜大成银行", "aliases": ["Daesong Bank", "DCB Financial"],
     "program": "UN1718", "risk": "HIGH"},
]

# 受限国家/地区（禁止与其居民交易）
_BLOCKED_COUNTRIES: set[str] = {
    "KP",   # 朝鲜
    "IR",   # 伊朗
    "SY",   # 叙利亚
    "CU",   # 古巴
}


# ═══════════════════════════════════════════════════════════════
# 模糊匹配引擎
# ═══════════════════════════════════════════════════════════════

def _normalize(s: str) -> str:
    """规范化字符串：小写、去空格、去标点"""
    return re.sub(r"[^a-z0-9一-鿿]", "", s.lower())


def _name_similarity(a: str, b: str) -> float:
    """基于公共子串的简单相似度评分

    0.0 = 完全不相似，1.0 = 完全相同
    """
    a_norm = _normalize(a)
    b_norm = _normalize(b)
    if not a_norm or not b_norm:
        return 0.0

    # 完全匹配
    if a_norm == b_norm:
        return 1.0

    # 公共字符比例
    common = sum(1 for c in a_norm if c in b_norm)
    return common / max(len(a_norm), len(b_norm))


# ═══════════════════════════════════════════════════════════════
# 筛查入口
# ═══════════════════════════════════════════════════════════════

def check_sanctions(name: str, country_code: str = "",
                    sensitivity: float = 0.85) -> tuple[bool, str | None, list[dict]]:
    """筛查一个实体/个人是否命中制裁名单

    Args:
        name: 客户/公司名称
        country_code: ISO 3166-1 alpha-2 国家代码（可选）
        sensitivity: 模糊匹配阈值 (0.0-1.0)，越低越严格

    Returns:
        (是否通过, 拒绝原因, 命中记录列表)
    """
    # 1. 国家/地区检查
    if country_code and country_code.upper() in _BLOCKED_COUNTRIES:
        return False, f"受制裁国家/地区限制（{country_code.upper()}）", []

    # 2. 实体名称精确匹配
    name_norm = _normalize(name)
    for entity in _BLOCKED_ENTITIES:
        if name_norm == _normalize(entity["name"]):
            return False, f"命中制裁名单：{entity['name']} ({entity['program']})", [entity]

        for alias in entity.get("aliases", []):
            if name_norm == _normalize(alias):
                return False, f"命中制裁名单别名：{alias} → {entity['name']} ({entity['program']})", [entity]

    # 3. 模糊匹配
    hits = []
    for entity in _BLOCKED_ENTITIES:
        score = _name_similarity(name, entity["name"])
        if score >= sensitivity:
            hits.append({**entity, "match_score": round(score, 3)})

        for alias in entity.get("aliases", []):
            score = _name_similarity(name, alias)
            if score >= sensitivity:
                hits.append({**entity, "match_score": round(score, 3),
                            "matched_alias": alias})

    if hits:
        top = sorted(hits, key=lambda h: -h["match_score"])[0]
        return False, (
            f"疑似命中制裁名单：{top['name']} "
            f"(匹配度 {top['match_score']:.0%}, 项目 {top['program']})"
        ), hits

    return True, None, []


def check_transaction_amount(amount: float, threshold: float = 50_000_000) -> tuple[bool, str | None]:
    """大额交易阈值检查（P0: 默认 5000 万美元）"""
    if amount > threshold:
        return False, f"交易金额 {amount:,.0f} 超出单笔限额 {threshold:,.0f}，需走线下询价通道"
    return True, None
