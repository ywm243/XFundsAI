# 查询示例逐层追踪：北京分公司今年一季度的交易量多少，同步增加多少

> 基于 main 分支实际代码，逐层展示每个函数的输入/输出和判定逻辑。
> 追踪日期：2026-05-14（系统当前日期）

---

## 查询原文

```
北京分公司今年一季度的交易量多少，同步增加多少
```

---

## 第一层：规则解析器 parser.py

### 1.1 `_parse_product_type("北京分公司今年一季度的交易量多少，同步增加多少")`

```
检查关键词:
  "即期" in text? → false
  "远期" in text? → false
  "掉期" in text? → false
matched = []
返回: "all"
```

### 1.2 `_parse_buy_sell(...)`

```
铁律检查:
  "结汇" in text? → false
  "购汇" or "售汇" in text? → false
可反转检查:
  "买入" in text? → false
  "卖出" in text? → false
返回: ""
```

### 1.3 `_parse_date_range(...)` ⚠️ 关键判定

```
today = 2026-05-14, year=2026, month=5

Priority 1: 显式日期 "YYYY-MM-DD 到 YYYY-MM-DD" → 不匹配
Priority 2: "YYYY年MM月DD日" → 不匹配
Priority 3: "YYYY年MM月" → 不匹配
Priority 4: "今年N月" → 不匹配（"今年一季度" 不是 "今年N月"）
Priority 5: "今年" in text? → TRUE ← 命中！
           返回: ("2026-01-01", "2026-05-14")  ← 今年至今，非 Q1 范围

⚠️ 问题: 规则解析器没有"一季度"模式。
   - "今年N月" 正则: r"今年\s*(\d{1,2})\s*月" → "一季" 不匹配 \d{1,2}
   - "本季度" 只能匹配字面"本季度"，不能匹配"今年一季度"
   - 兜底"今年"返回 YTD，与用户期望的 Q1(1-3月) 不符

返回: ("2026-01-01", "2026-05-14")  ← 错误范围（应为 2026-01-01 ~ 2026-03-31）
```

### 1.4 `_parse_bank_name(...)`

```
尝试匹配:
  "XX银行XX分行" 完整模式 → "北京分公司" 不含"银行" → 不匹配
  "XX银行" 模式 → 不匹配
  "XX分行/支行/分公司/营业部" 模式:
    正则: ([一-鿿]{2,}(?:分行|支行|分公司|营业部))
    → 匹配 "北京分公司" ← 命中！
返回: "北京分公司"
```

### 1.5 `_parse_special_states(...)`

```
检查: 在途/未到期 → 0, 逾期/已过期 → 1, 展期/延期 → 3,
      提前交割/提前交收 → 4, 平仓/已平仓 → 5
全部不匹配
返回: ""
```

### 1.6 `_parse_trade_class(...)`

```
精确匹配 14 组关键词 → 全部不匹配
泛化匹配 3 组 → 全部不匹配
返回: ""
```

### 1.7 `_parse_aggregate(...)`

```
keywords = ["交易量", "金额", "总额", "总计", "汇总"]
"交易量" in text? → true ← 命中！
返回: true
```

### 1.8 `_parse_top_n(...)`

```
"TOP N" → 不匹配
"前N" → 不匹配
"排名" or "排行" → 不匹配
返回: None
```

### 1.9 `_parse_amount_filter(...)`

```
操作符检测:
  大于等于/不低于/不少于 → 不匹配
  大于/超过/高于/以上 → 不匹配
  小于等于/不超过/不多于 → 不匹配
  小于/不足/低于/不到/以内/以下 → 不匹配
返回: None
```

### 1.10 `_parse_cust_name(...)`

```
模式1 "XX客户" → 不匹配
模式2 "XX的套保率" → 不匹配
返回: ""
```

### 1.11 `_parse_comparison_modifier(...)` ⚠️ 关键判定

```python
if "同比" in text: return "yoy"   # "同步增加" 不含 "同比"
if "环比" in text: return "mom"   # 也不含 "环比"
return ""
```

```
"同比" in "北京分公司今年一季度的交易量多少，同步增加多少"? → false
"环比" in text? → false
返回: ""

⚠️ 问题: "同步增加" 在中文金融语境中通常指"同比增加"，但解析器只识别
   精确关键词 "同比"/"环比"。规则解析器无法识别 "同步" = "同比"。
```

### 1.12 `_parse_dimension(...)`

```
"客户号/客户编号/客户ID" → 不匹配
"客户经理ID/客户经理编号" → 不匹配
"客户经理名称/客户经理姓名/客户经理" → 不匹配
"客户" → 不匹配（文本中无"客户"）
返回: "bank"（默认）
```

### 1.13 `_parse_hedge_ratio(...)`

```
"套保率" in text? → false
返回: false
```

### 1.14 `rule_based_parse` 汇总输出

```json
{
  "product_type": "all",
  "date_start": "2026-01-01",
  "date_end": "2026-05-14",
  "special_states": "",
  "trade_class": "",
  "buy_sell": "",
  "bank_name": "北京分公司",
  "cust_name": "",
  "aggregate": true,
  "top_n": null,
  "amount_filter": null,
  "dimension": "bank",
  "hedge_ratio": false,
  "appid": null,
  "comparison": ""
}
```

**规则解析器结论：**
- 日期解析错误：返回了今年至今（1/1~5/14），而非用户期望的 Q1（1/1~3/31）
- 对比识别失败：未识别出"同步增加"=同比，comparison 为空
- 银行名称正确：识别出"北京分公司"
- 聚合标记正确：识别出"交易量"需要聚合

`rule_based_parse` 无法正确处理"一季度"和"同步"这两个表达。

---

## 第二层：LLM 解析器 llm_client.py

### 2.1 LLM 调用

```
API: https://api.deepseek.com
Model: deepseek-v4-flash
Temperature: 0.1
Timeout: 30s

System Prompt 关键片段:
  "当前日期：2026-05-14（所有日期计算以此为准）"
  "同比/环比：出现"同比"则 comparison="yoy"，出现"环比"则 comparison="mom"，
   否则 comparison="""

User Message: "北京分公司今年一季度的交易量多少，同步增加多少"
```

### 2.2 LLM 推定输出（DeepSeek V4 Flash 语义理解）

```json
{
  "product_type": "all",
  "date_start": "2026-01-01",
  "date_end": "2026-03-31",
  "special_states": "",
  "buy_sell": "",
  "bank_name": "北京分公司",
  "cust_name": "",
  "aggregate": true,
  "top_n": null,
  "amount_filter": null,
  "dimension": "bank",
  "hedge_ratio": false,
  "appid": null,
  "comparison": "yoy"
}
```

**LLM 优势体现：**
- 日期："今年一季度" → 正确拆解为 `2026-01-01 ~ 2026-03-31`（Q1 = 前 3 个月）
- 对比："同步增加" → 语义映射到 `comparison="yoy"`（但存在不确定性，参见下方分析）
- 银行/聚合：与规则解析器一致

### 2.3 LLM vs 规则解析器差异对比

| 字段 | 规则解析器 | LLM | 正确答案 |
|------|----------|-----|---------|
| date_start | 2026-01-01 | 2026-01-01 | 2026-01-01 |
| date_end | **2026-05-14** ❌ | **2026-03-31** ✓ | 2026-03-31 |
| comparison | **""** ❌ | **"yoy"**（推定）✓ | "yoy" |

---

## 第三层：守门验证 rules_engine.py

LLM 结果送入 `gatekeep(parsed, original_text)`，逐阶段检查：

### 阶段追踪

```
阶段 1a (buy_sell 铁律):
  遍历 4 条不可反转规则 → 关键词均不在文本中 → 无覆盖

阶段 1b (结售汇特例):
  "结售汇" in text? → false → 跳过

阶段 1c (客户前缀反转):
  overrides 中没有 customer_reversible 条目
  "客户" in text? → false → 跳过

阶段 1d (special_states):
  5 组关键词逐一检查 → 全部不匹配 → 无覆盖

阶段 1d2 (trade_class):
  _parser._parse_trade_class(text) → "" → 无覆盖

阶段 1d3 (签约交易):
  "签约" in text? → false → 跳过

阶段 1e (product_type):
  4 组关键词逐一检查 → 全部不匹配 → 无覆盖

阶段 1f (app_id):
  parsed.appid 为 null → 进入回退
  "外汇/外汇交易/外汇买卖" → 不匹配
  "结售汇/结汇售汇" → 不匹配 → 保持 null

阶段 2 (日期回退):
  parsed.date_start="2026-01-01" → 不为空，不触发回退
  parsed.date_end="2026-03-31" → 不为空，不触发回退

阶段 3 (客户名称):
  parsed.cust_name="" → _parser._parse_cust_name(text) → "" → 无覆盖

阶段 4 (银行名称回退):
  parsed.dimension="bank", parsed.bank_name="北京分公司" → 不为空，不触发

阶段 5 (互斥校验):
  cust_name="" → 不触发

聚合检测:
  "交易量" in text → true → parsed["aggregate"]=true（LLM 已设，一致）

套保率检测:
  "套保率" in text → false → 不触发

TopN 回退:
  parsed.top_n=null → _parser._parse_top_n(text) → null → 保持 null

金额过滤回退:
  parsed.amount_filter=null → _parser._parse_amount_filter(text) → null → 保持 null

维度回退:
  _parser._parse_dimension(text) → "bank"（默认）→ 不覆盖
```

### Gatekeep 最终输出（与 LLM 输出一致，无覆盖）

```json
{
  "product_type": "all",
  "date_start": "2026-01-01",
  "date_end": "2026-03-31",
  "special_states": "",
  "trade_class": "",
  "buy_sell": "",
  "bank_name": "北京分公司",
  "cust_name": "",
  "aggregate": true,
  "top_n": null,
  "amount_filter": null,
  "dimension": "bank",
  "hedge_ratio": false,
  "appid": null,
  "comparison": "yoy"
}
```

**pipeline 标记：** `"llm+gatekeep"`

Gatekeep 日志输出（本例中无任何 override）：
```
（无日志输出，因为没有发生任何 override）
```

---

## 第四层：SQL 构建与路由 app.py

### 4.1 `/api/parse` 返回给前端

```json
{
  "params": { /* 上述 parsed 对象 */ },
  "pipeline": "llm+gatekeep"
}
```

### 4.2 前端确认后 `/api/query` 收到

```json
{
  "params": {
    "product_type": "all",
    "date_start": "2026-01-01",
    "date_end": "2026-03-31",
    "bank_name": "北京分公司",
    "aggregate": true,
    "comparison": "yoy",
    ...
  }
}
```

### 4.3 参数归一化（app.py:203-210）

```python
buy_sell = "" or None → None
cust_name = "" or None → None
special_states = "" → isinstance check → "" 不是 str → None
# wait, isinstance("", str) is True, and "" is truthy? No, "" is falsy
# So: isinstance("", str) and "" → False (因为 "" 是 falsy)
# → special_states = None
```

### 4.4 SQL 路由决策（app.py:215-278）

```
amount_filter? → null → 跳过
top_n? → null or 0 → 跳过 (top_n and top_n > 0 → False)
hedge_ratio? → False → 跳过
aggregate? → True → 命中！
```

### 4.5 生成的当期 SQL

调用 `TradeQueryBuilder.build_aggregate_query(...)`：

```sql
WITH matched_banks AS (
    SELECT BANKID FROM XF_BASE_BANK
    WHERE DIPNAME LIKE '%北京分公司%' ESCAPE '\'
)
SELECT b.DIPNAME as 机构名称,
       SUM(t.USDAMOUNT) as TOTAL_AMOUNT,
       COUNT(*) as TRADE_COUNT
FROM (
    SELECT USDAMOUNT, TRADEDATE, TRADESTATUS, SPECIALSTATE, APPID,
           BUYORSELL, BANKID, CUSTNAME, CUSTOMERID, CUSTMAINMANAGER, CUSTMANAGERNAME
    FROM XF_FX_SPOTTRADE_VIEW
    UNION ALL
    SELECT USDAMOUNT, TRADEDATE, TRADESTATUS, SPECIALSTATE, APPID,
           BUYORSELL, BANKID, CUSTNAME, CUSTOMERID, CUSTMAINMANAGER, CUSTMANAGERNAME
    FROM XF_FX_FWDTRADE_VIEW
    UNION ALL
    SELECT USDAMOUNT, TRADEDATE, TRADESTATUS, SPECIALSTATE, APPID,
           BUYORSELL, BANKID, CUSTNAME, CUSTOMERID, CUSTMAINMANAGER, CUSTMANAGERNAME
    FROM XF_FX_SWAPTRADE_VIEW
) t
LEFT JOIN XF_BASE_BANK b ON t.BANKID = b.BANKID
WHERE t.TRADESTATUS=0
  AND t.APPID IN (1,2)
  AND t.TRADEDATE>=20260101
  AND t.TRADEDATE<=20260331
  AND t.BANKID IN (SELECT BANKID FROM matched_banks)
GROUP BY b.DIPNAME
ORDER BY TOTAL_AMOUNT DESC
```

**WHERE 条件来源：**

| 条件 | 来源 |
|------|------|
| `t.TRADESTATUS=0` | `_build_where_conditions` 固定条件 |
| `t.APPID IN (1,2)` | `_appid_filter(None)` → 默认值 |
| `t.TRADEDATE>=20260101` | `date_start="2026-01-01"` → 去掉 `-` 转整数 |
| `t.TRADEDATE<=20260331` | `date_end="2026-03-31"` → 去掉 `-` 转整数 |
| `t.BANKID IN (SELECT BANKID FROM matched_banks)` | `_build_cte("北京分公司")` → 模糊搜索 |

---

## 第五层：对比计算

### 5.1 对比日期计算

`compute_comparison_dates("2026-01-01", "2026-03-31", "yoy")`：

```python
start = date(2026, 1, 1)
end = date(2026, 3, 31)

# YoY: 前移一年
cmp_start = date(2025, 1, 1)  # 2026-01-01 → 2025-01-01
cmp_end = date(2025, 3, 31)   # 2026-03-31 → 2025-03-31
# 3月31日在2025年存在，无需闰年兜底

返回: ("2025-01-01", "2025-03-31")
```

### 5.2 对比 SQL

`_build_comparison_sql()` 判断路由（与当期相同的 aggregate 分支）：

```sql
WITH matched_banks AS (
    SELECT BANKID FROM XF_BASE_BANK
    WHERE DIPNAME LIKE '%北京分公司%' ESCAPE '\'
)
SELECT b.DIPNAME as 机构名称,
       SUM(t.USDAMOUNT) as TOTAL_AMOUNT,
       COUNT(*) as TRADE_COUNT
FROM ( ... 同上 UNION ALL ... ) t
LEFT JOIN XF_BASE_BANK b ON t.BANKID = b.BANKID
WHERE t.TRADESTATUS=0
  AND t.APPID IN (1,2)
  AND t.TRADEDATE>=20250101    -- ← 去年
  AND t.TRADEDATE<=20250331    -- ← 去年
  AND t.BANKID IN (SELECT BANKID FROM matched_banks)
GROUP BY b.DIPNAME
ORDER BY TOTAL_AMOUNT DESC
```

### 5.3 执行与计算

假设 Oracle 返回：

```
当期 (2026 Q1):  [{ "机构名称": "北京分公司", "TOTAL_AMOUNT": 500000000, "TRADE_COUNT": 120 }]
对比 (2025 Q1):  [{ "机构名称": "北京分公司", "TOTAL_AMOUNT": 400000000, "TRADE_COUNT": 100 }]
```

`_compute_comparison(current_rows, compare_rows, "yoy", ...)`：

```python
current_row = ["北京分公司", 500000000, 120]
compare_row = ["北京分公司", 400000000, 100]

amt_idx = 1  # TOTAL_AMOUNT 列
current_amt = float(500000000) = 500000000.0
compare_amt = float(400000000) = 400000000.0

change_amount = 500000000 - 400000000 = 100000000.0   # +1亿
change_rate = round(abs(100000000 / 400000000) * 100, 2) = 25.0

返回:
{
  "type": "yoy",
  "label": "同比",
  "current_period": "2026-01-01 ~ 2026-03-31",
  "compare_period": "2025-01-01 ~ 2025-03-31",
  "current_amount": 500000000.0,
  "compare_amount": 400000000.0,
  "change_amount": 100000000.0,
  "change_rate": 25.0
}
```

---

## 第六层：前端展示

### 6.1 `/api/query` 返回给前端

```json
{
  "sql": "WITH matched_banks AS (...) SELECT ...",
  "params": { /* parsed 对象 */ },
  "columns": ["机构名称", "TOTAL_AMOUNT", "TRADE_COUNT"],
  "rows": [["北京分公司", 500000000, 120]],
  "row_count": 1,
  "comparison": {
    "type": "yoy",
    "label": "同比",
    "current_period": "2026-01-01 ~ 2026-03-31",
    "compare_period": "2025-01-01 ~ 2025-03-31",
    "current_amount": 500000000.0,
    "compare_amount": 400000000.0,
    "change_amount": 100000000.0,
    "change_rate": 25.0
  },
  "error": ""
}
```

### 6.2 前端渲染

**ResultPanel - 数据标签页：**

| 机构名称 | 总交易量（万美元） | 总笔数 |
|---------|-----------------|--------|
| 北京分公司 | 50,000.00 | 120 |
| *共 1 行* | | |

**ResultPanel - 对比卡片（在标签页上方）：**

```
┌─────────────────────────────────────────────┐
│ 同比对比                          [+25.0%]  │
│                                             │
│ 当期 (2026-01-01 ~ 2026-03-31)              │
│ 500,000,000 万美元                          │
│                                             │
│ 同比 (2025-01-01 ~ 2025-03-31)              │
│ 400,000,000 万美元                          │
│                                             │
│ 变化                                        │
│ +100,000,000 万美元                         │
└─────────────────────────────────────────────┘
```

---

## 全链路总结

```
用户输入: "北京分公司今年一季度的交易量多少，同步增加多少"
    │
    ├─ 规则解析器 (parser.py)
    │   ├─ product_type: "all" ✓
    │   ├─ date_range: 2026-01-01 ~ 2026-05-14 ✗ (应为 03-31)
    │   ├─ bank_name: "北京分公司" ✓
    │   ├─ aggregate: true ✓
    │   └─ comparison: "" ✗ (未识别"同步")
    │
    ├─ LLM 解析器 (llm_client.py) ← 对复杂表达更准确
    │   ├─ date_range: 2026-01-01 ~ 2026-03-31 ✓
    │   └─ comparison: "yoy" ✓ (推定，"同步"→"同比")
    │
    ├─ 守门验证 (rules_engine.py)
    │   └─ 无覆盖（LLM 结果全部通过）
    │
    ├─ SQL 路由 (app.py)
    │   └─ aggregate=true → build_aggregate_query()
    │       生成分组聚合 SQL + CTE 模糊匹配银行
    │
    ├─ 数据库执行 (Oracle)
    │   ├─ 当期: 2026 Q1 → 500M 美元, 120 笔
    │   └─ 对比: 2025 Q1 → 400M 美元, 100 笔
    │
    ├─ 对比计算 (app.py:_compute_comparison)
    │   └─ 同比变化: +1亿 (+25%)
    │
    └─ 前端展示 (ResultPanel.vue)
        ├─ 数据表格: 1 行 (北京分公司)
        └─ 对比卡片: 同比 +25%
```

### 关键风险点

| 风险 | 说明 | 影响 |
|------|------|------|
| **规则解析器不支持"一季度"** | parser.py 只支持"今年N月"、"本季度"，没有"今年一季度"模式。LLM 失败时会回退到"今年"(YTD) | 日期范围错误 |
| **"同步"→"同比"映射依赖 LLM** | prompt 只写"出现'同比'则 comparison='yoy'"，LLM 能否把"同步"映射到"同比"取决于模型理解能力 | comparison 可能丢失 |
| **Gatekeep 无 comparison 回退** | 即使 LLM 没设置 comparison，gatekeep 也不会从规则补充 | 对比功能静默失效 |
| **"北京分公司"模糊搜索** | CTE 用 `LIKE '%北京分公司%'` 匹配，若 XF_BASE_BANK 中无此名称或匹配多条，结果可能为空或不准确 | 查询结果偏差 |

---

> **建议：** 在 parser.py 中增加"今年一季度/二季度/三季度/四季度"和"第N季度"的时间模式，在 `_parse_comparison_modifier` 中增加"同步"→"yoy"的映射，减少对 LLM 的依赖。
