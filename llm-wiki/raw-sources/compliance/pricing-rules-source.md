---
title: 询报价合规规则原始材料
type: source
updated: 2026-05-20
sources:
  - backend/pricing/pricing_rules.py
  - backend/knowledge_base/semantic_rules.json
reliability: high
---

从 pricing_rules.py 和 semantic_rules.json 中提取的合规相关源材料。

## PRICING_SYSTEM_PROMPT 合规红线

（原始内容见 pricing_rules.py 的 PRICING_SYSTEM_PROMPT 变量）

## semantic_rules.json pricing 区块

- quote_validity_minutes: 5
- product_params: SPOT/FWD/SWAP 必填参数
- scenarios: 远期期限对比、即期远期对比、多期限对比
- glossary: 结汇、购汇、掉期、点差等术语
- risk_disclosure: 风险揭示模板
- routing_keywords: 询价路由关键词
- amount_thresholds: 金额阈值
- session_timeout_minutes: 30
