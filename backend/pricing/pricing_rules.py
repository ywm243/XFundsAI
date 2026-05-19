# backend/pricing/pricing_rules.py
"""询报价规则 + LLM system prompt"""

PRICING_SYSTEM_PROMPT = """你是外汇询报价助手，负责解析用户的询价意图。

严格规则：
1. 结汇 = 银行买入外币 (direction=B)，购汇 = 银行卖出外币 (direction=S)，不可覆盖
2. 必须识别：产品类型(product_type)、货币对(currency_pair)、方向(direction)
   - product_type: SPOT(即期) / FWD(远期) / SWAP(掉期)
   - currency_pair: USD/CNY(美元) / EUR/CNY(欧元) / GBP/CNY(英镑) / JPY/CNY(日元)
3. 远期(FWD)必须有期限(tenor)，掉期(SWAP)必须有近端期限(near_tenor)和远端期限(far_tenor)
4. intent_type 判断：
   - 用户说"买/卖"且带金额 → DIRECT_TRADE
   - 用户说"询价/报价/多少钱/价格" → SINGLE 或 MULTI
   - 用户说"对比/比价/哪个好" → COMPARE
   - 用户说"不同期限/情景" → SCENARIO
5. 模棱两可时，宁可归为 SINGLE，不要推断为 DIRECT_TRADE
6. 不要填充用户未提及的字段，缺失字段标记为null

输出JSON格式（仅输出JSON，不要其他内容）：
{
  "intent_type": "SINGLE|MULTI|COMPARE|SCENARIO|DIRECT_TRADE",
  "product_type": "SPOT|FWD|SWAP|null",
  "currency_pair": "USD/CNY|null",
  "direction": "B|S|null",
  "amount": 数字或null,
  "tenor": "1M|null",
  "near_tenor": "1M|null",
  "far_tenor": "3M|null"
}
"""

REJECTION_TEMPLATES: dict[str, str] = {
    "CREDIT_EXCEEDED": "当前可用授信额度不足，请联系客户经理调整授信。",
    "LIMIT_EXCEEDED": "超出交易限额。单笔限额或日累计限额已达上限。",
    "CUSTOMER_FROZEN": "客户账户状态异常，暂不支持交易。请联系客户经理。",
    "QUOTE_EXPIRED": "报价已过期，请重新发起询价。",
    "QUOTE_NOT_FOUND": "报价信息不存在，请重新询价。",
    "AMOUNT_MISMATCH": "成交金额与报价金额不一致，请确认后重试。",
    "SYSTEM_ERROR": "系统异常，请稍后重试。",
}

RISK_REJECT_REASONS: dict[str, str] = {
    "BLACKLIST": "客户暂不支持询价服务，请联系客户经理。",
    "ACCOUNT_FROZEN": "客户账户状态异常，暂不支持询价服务。",
}

PRICE_ANOMALY_RULES = {
    "zero_price_check": "customer_rate > 0",
    "excessive_spread": "spread_bp < 1000",
    "negative_spread": "spread_bp >= 0",
}
