---
title: 制裁名单筛查
type: concept
updated: 2026-05-20
sources:
  - pricing/risk_guard.py
tags: [合规, 制裁, 筛查]
reliability: high
confidence: 0.95
---

对交易客户的制裁状态进行预检。

## 筛查规则

| 状态 | 含义 | 处理 |
|------|------|------|
| `clear` | 无制裁记录 | 通过 |
| `watchlist` | 观察名单 | 需人工审核 |
| `sanctioned` | 制裁名单 | 直接拒绝 |

## 拒绝引导

制裁客户不可进行任何询报价操作。系统返回合规拒绝原因，不暴露内部筛查机制细节。

## See also

- [[compliance-redlines]]
- [[risk-check-procedure]]
