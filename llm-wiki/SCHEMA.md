---
title: XFundsAI Wiki Schema
updated: 2026-05-20
---

# 项目约定

## 页面类型

| Type | 用途 | 最小深度 |
|------|------|---------|
| `concept` | 合规规则、术语、产品参数 | ≥1 表格 + ≥3 段正文 |
| `entity` | 客户画像 | metadata + 交易偏好 + 风险标注 |
| `reference` | 解析规则、API 映射 | 查找表/命令列表 |
| `synthesis` | 跨页面综合分析 | cites ≥2 wiki pages |
| `source` | 原始材料注册 | metadata + key content |
| `stub` | 待编译占位 | frontmatter + 1 段说明 |

## 目录结构

```
llm-wiki/
├── SCHEMA.md            # 本文件
├── index.md             # 页面目录（自动生成）
├── log.md               # 操作日志
├── raw-sources/         # 原始材料（不可变、追加写入）
│   ├── index.md         # 源材料注册表
│   ├── compliance/      # 合规文件
│   ├── product/         # 产品手册
│   └── sessions/        # 会话记录
├── concepts/            # 编译后概念页
└── entities/            # 编译后实体页（客户画像）
```

## Frontmatter 规范

必填字段：`title`, `type`, `updated`, `sources`

可选字段：`tags`, `confidence`, `reliability`, `contradictedBy`

## 编译规则

1. 每个概念一个文件，文件名 = slug
2. 页面间用 `[[wikilinks]]` 互联
3. 合规规则页必须标注 `reliability: high`
4. 客户画像页标注 `type: entity`
