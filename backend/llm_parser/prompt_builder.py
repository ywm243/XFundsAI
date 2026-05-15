import logging
from datetime import date

logger = logging.getLogger(__name__)

from db import mysql_store

_cache: str | None = None


def _load_rules() -> dict:
    """Load rules from SQLite."""
    return mysql_store.load_rules_from_db()


def _render_buy_sell(rules: list[dict]) -> str:
    lines = []
    lines.append('铁律规则（不可因"客户"前缀反转，必须严格遵守）：')
    rev = []
    for r in rules:
        if not r["customer_reversible"]:
            appid_note = f", 同时设置 appid={r['set_app_id']}" if r.get("set_app_id") else ""
            lines.append(
                f"  关键词 {r['keywords']} → buy_sell=\"{r['direction']}\"{appid_note}"
                f"  ({r['description']})"
            )
        else:
            rev.append(r)
    lines.append("")
    lines.append('可反转规则（带"客户"前缀时方向反转为 customer_direction）：')
    for r in rev:
        lines.append(
            f"  {r['product_types']}: 关键词 {r['keywords']} →"
            f" 默认 buy_sell=\"{r['direction']}\""
            f" / 客户视角 buy_sell=\"{r['customer_direction']}\""
            f"  ({r['description']})"
        )
    return "\n".join(lines)


def _render_time(rules: list[dict]) -> str:
    lines = ["将中文时间表达式转换为具体 YYYY-MM-DD 日期："]
    for r in rules:
        lines.append(f"  {r['pattern']}{' (参数N)' if r.get('param') else ''} → {r['example']}")
    return "\n".join(lines)


def _render_special_states(rules: list[dict]) -> str:
    lines = []
    for r in rules:
        lines.append(f"  {r['keywords']} → special_states=\"{r['value']}\" ({r['meaning']})")
    return "\n".join(lines)


def _render_app_id(rules: list[dict]) -> str:
    lines = []
    for r in rules:
        lines.append(f"  {r['keywords']} → appid={r['value']} ({r['meaning']})")
    return "\n".join(lines)


def _render_product_type(rules: list[dict]) -> str:
    lines = []
    for r in rules:
        lines.append(f"  {r['keywords']} → \"{r['value']}\" ({r['meaning']})")
    return "\n".join(lines)


def build_system_prompt(context: list | None = None) -> str:
    global _cache
    # Don't cache when context is provided (dynamic per request)
    if context:
        rules = _load_rules()
        prompt = _build_base_prompt(rules)
        ctx_lines = ["## 对话上下文（多轮对话历史）"]
        for item in context:
            role = item.get("role", "user")
            content = item.get("content", "")
            ctx_lines.append(f"- {role}: {content}")
        ctx_lines.append("请根据上下文理解当前查询，继承上一轮的实体、日期等参数。")
        return prompt + "\n" + "\n".join(ctx_lines)

    if _cache is not None:
        return _cache

    rules = _load_rules()
    _cache = _build_base_prompt(rules)
    return _cache


def _build_base_prompt(rules: dict) -> str:

    prompt = f"""你是一个外汇交易查询参数提取器。将用户自然语言查询转换为严格 JSON。

## 输出 JSON 格式
```json
{{
  "product_type": "all" | "spot" | "fwd" | "swap",
  "date_start": "YYYY-MM-DD 字符串，无则空字符串",
  "date_end": "YYYY-MM-DD 字符串，无则空字符串",
  "special_states": "逗号分隔的枚举值如 '0,1'，无则空字符串",
  "buy_sell": "B" | "S" | "",
  "bank_name": "银行名称字符串，无则空字符串",
  "cust_name": "客户名称字符串，无则空字符串",
  "aggregate": true | false,
  "top_n": 整数或 null,
  "amount_filter": {{ "amount_op": "gte"|"gt"|"lte"|"lt", "amount_value": 数值 }} 或 null,
  "dimension": "bank" | "customer",
  "hedge_ratio": true | false,
  "appid": 1 | 2 | null,
  "comparison": "yoy" | "mom" | ""
}}
```

## 产品类型映射
{_render_product_type(rules["product_type"]["rules"])}

## 买卖方向规则（银行视角）
{_render_buy_sell(rules["buy_sell_direction"]["rules"])}
重要：若查询同时包含买入和卖出类关键词（如"结售汇"），则 buy_sell="" 且 appid=2

## 时间表达式
当前日期：{date.today().strftime('%Y-%m-%d')}（所有日期计算以此为准）
{_render_time(rules["time_expressions"]["rules"])}

## 特殊状态映射（SPECIALSTATE）
{_render_special_states(rules["special_states"]["rules"])}
注意：
- 没有"挂账"状态，不要在 special_states 中使用 2
- "在途"不是 SPECIALSTATE 字段。"在途"=totaldelivery 表剩余金额>0（未完结），可能表现为签约交易、展期远端、提前交割近端

## 特殊交易类别（SPECTRADECLASS）
{_render_special_states(rules["trade_class"]["rules"])}
分类规则：
- 关键词含「平仓」或「平盘」→ 平仓交易
- 关键词含「提前交割」→ 提前交割交易
- 关键词含「展期」→ 展期交易

## 签约交易
- 签约交易（ISSIGNTRADE=0）：关键词含「签约」

## 在途交易
- "在途"表示未完结交易：查询 totaldelivery 表 WHERE 剩余金额 > 0
- 在途可能出现在：签约交易、展期远端、提前交割近端
- "在途"不作为 special_states 参数，而是作为独立的查询条件

## 业务系统
{_render_app_id(rules["app_id"]["rules"])}

## 金额过滤
- 单位：万=10000, 亿=100000000
- 运算符：大于等于/不低于/不少于=gte, 大于/超过/高于=gt, 小于等于/不超过=lte, 小于/低于/不足=lt

## 其他
- 银行名称模式：XX银行、XX分行/支行、XX银行XX分行
- 客户名称模式：XX客户、XX的套保率
- TopN：TOP N、前N、排名/排行（默认10）
- 套保率：出现"套保率"则 hedge_ratio=true
- 维度：按以下优先级判断（长关键词优先，不可因含"客户"子串而降级）
  - 客户号/客户编号/客户ID → dimension="customer_id"
  - 客户经理ID/客户经理编号 → dimension="manager"
  - 客户经理名称/客户经理姓名/客户经理 → dimension="manager_name"
  - 客户名称/客户 → dimension="customer"
  - 无上述关键词 → dimension="bank"
- 聚合：交易量/金额/总额/总计/汇总 → aggregate=true，其余情况 aggregate=false
- 当查询是询问某个具体客户的套保率或交易量时，需要在 cust_name 中提取客户名称
- 同比/环比/同步：出现"同比"或"同步"（如"同步增加""同步增长"）则 comparison="yoy"，出现"环比"则 comparison="mom"，否则 comparison=""。同比表示与去年同期对比（日期前移一年，如2月29日平年取2月28日），环比表示与上一周期对比

用 ```json 代码块包裹输出。"""

    _cache = prompt
    return _cache


def invalidate_cache() -> None:
    global _cache
    _cache = None
    logger.info("Prompt cache invalidated")
