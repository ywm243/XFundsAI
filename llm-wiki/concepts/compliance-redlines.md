---
title: 询报价合规红线
type: concept
updated: 2026-05-20
sources:
  - pricing/pricing_rules.py
tags: [合规, 询报价, 红线]
reliability: high
confidence: 0.95
---

询报价Agent的7条不可违反合规红线，LLM 输出必须遵守。

## 红线清单

| 编号 | 规则 | 违反后果 |
|------|------|---------|
| 1 | 不预测汇率走势 | 误导客户投资决策 |
| 2 | 不承诺点差优惠 | 利益输送风险 |
| 3 | 不提供投资建议 | 超范围经营 |
| 4 | 不隐瞒风险 | 信息披露不充分 |
| 5 | 不替代客户决策 | 客户自主权 |
| 6 | 不绕过审批流程 | 合规审查缺失 |
| 7 | 不修改报价精度 | 定价透明度 |

## 实施机制

1. `PRICING_SYSTEM_PROMPT` 中写入红线指令
2. `risk_guard.post_check()` 校验 LLM 输出
3. 违反时返回 `risk_rejected` 模式 + 拒绝原因

## See also

- [[risk-check-procedure]]
- [[sanctions-screening]]
