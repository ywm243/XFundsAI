---
title: 询报价产品参数
type: reference
updated: 2026-05-20
sources:
  - pricing/validator.py
  - knowledge_base/semantic_rules.json
tags: [产品, 参数, 询报价]
reliability: high
confidence: 0.95
---

各产品类型的必填参数和可选参数。

## 参数矩阵

| 产品 | 必填参数 | 可选参数 |
|------|---------|---------|
| 即期(SPOT) | currency_pair | direction, amount |
| 远期(FWD) | currency_pair, tenor | direction, amount |
| 掉期(SWAP) | currency_pair, near_tenor, far_tenor | direction, amount |

## 规则4：direction 非必填

direction 缺失时，系统默认执行双边报价（B+S并行询价），不追问用户。用户可从双边报价中选择一侧成交。

## 期限映射

| 中文 | 标准代码 |
|------|---------|
| 1个月 | 1M |
| 3个月 | 3M |
| 6个月 | 6M |
| 1年 | 1Y |

## See also

- [[compliance-redlines]]
- [[risk-check-procedure]]
