# Smart BI 测试场景文档

> 生成日期：2026-05-15 | 基于实际代码逻辑 | 共 45 个可验证场景

---

## 一、时间表达式（17 个场景）

### TC-001：今天

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `今天` |
| **预期 rule_based_parse** | `date_start` = 今天日期, `date_end` = 今天日期（两者相同）|
| **gatekeep 覆盖** | 无覆盖（规则已正确解析）|
| **预期置信度** | ~0.625（日期 1.5 + 无实体关键词 1.0 = 2.5/4.0），< 0.8，调用 LLM |
| **预期 SQL 路由** | 明细查询（`build_query`） |
| **验证要点** | `date_start == date_end == today.strftime("%Y-%m-%d")` |

**代码路径**：`_parse_date_range` Priority 9 `if "今天" in text` → `return (today, today)`

---

### TC-002：昨天

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `昨天` |
| **预期 rule_based_parse** | `date_start` = 昨天日期, `date_end` = 昨天日期 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start == date_end == (today - 1day)` |

**代码路径**：`_parse_date_range` Priority 8 `if "昨天" in text` → `yesterday = today - timedelta(days=1)`

---

### TC-003：本周

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `本周` |
| **预期 rule_based_parse** | `date_start` = 本周一, `date_end` = 今天 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start.weekday() == 0`（周一），`date_end` = 今天 |

**代码路径**：`_parse_date_range` Priority 6 `if "本周" in text` → Monday to today

---

### TC-004：本月

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `本月` |
| **预期 rule_based_parse** | `date_start` = 本月 1 日, `date_end` = 今天 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start.day == 1`, `date_end` = 今天, 同月 |

**代码路径**：`_parse_date_range` Priority 5 `if "本月" in text` → returns (本月1日, 今天)

---

### TC-005：今年（YTD）

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `今年` |
| **预期 rule_based_parse** | `date_start` = 2026-01-01, `date_end` = 今天 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start == "2026-01-01"`, `date_end` = 今天 |

**代码路径**：`_parse_date_range` Priority 5 `if "今年" in text` → returns (今年1月1日, 今天)

---

### TC-006：今年N月（今年3月）

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `今年3月` |
| **预期 rule_based_parse** | `date_start` = 2026-03-01, `date_end` = 2026-03-31 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start == "2026-03-01"`, `date_end == "2026-03-31"`（calendar.monthrange 自动获取月底）|

**代码路径**：`_parse_date_range` Priority 4 `今年\s*(\d{1,2})\s*月` → 完整月份范围

---

### TC-007：今年一季度

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `今年一季度` |
| **预期 rule_based_parse** | `date_start` = 2026-01-01, `date_end` = 2026-03-31 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM（No quarter mismatch: end month "03" in valid set）|
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | 季度区间正确；置信度非惩罚（end month="03"在有效集合中）|

**代码路径**：`_parse_date_range` Priority 4.5 `今年\s*(?:第)?\s*([一二三四1-4])\s*(?:季度|季)` 匹配"一"→Q1 → (1月1日, 3月31日)。
`_has_quarter_mismatch` 检测到"一季度"且 end month="03" → 无惩罚，confidence date=1.5。

---

### TC-008：今年第二季度

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `今年第二季度` |
| **预期 rule_based_parse** | `date_start` = 2026-04-01, `date_end` = 2026-06-30 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start == "2026-04-01"`, `date_end == "2026-06-30"` |

**代码路径**：Priority 4.5, `q_map["二"]=2` → Q2 → (4月1日, 6月30日)

---

### TC-009：今年第3季度（阿拉伯数字）

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `今年第3季度` |
| **预期 rule_based_parse** | `date_start` = 2026-07-01, `date_end` = 2026-09-30 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | 阿拉伯数字"3"通过 `q_map["3"]=3` 正确映射 |

**代码路径**：Priority 4.5, `[一二三四1-4]` 支持阿拉伯数字和中文

---

### TC-010：近N天（近7天）

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `近7天` |
| **预期 rule_based_parse** | `date_start` = 今天-7天, `date_end` = 今天 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_end - date_start == 7 days` |

**代码路径**：`_parse_date_range` Priority 12 `近(\d+)天` → `start = today - timedelta(days=n)`

---

### TC-011：近N个月（近3个月）

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `近3个月` |
| **预期 rule_based_parse** | `date_start` = 3个月前月初, `date_end` = 今天 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start.day == 1`（总月数计算回退到月初），`date_end` = 今天 |

**代码路径**：`_parse_date_range` Priority 10 `近(\d+)个?月` → 总月数 = year*12 + month - 1 - n, start = (总月数//12, 总月数%12+1, 1)

---

### TC-012：近N年（近1年）

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `近1年` |
| **预期 rule_based_parse** | `date_start` = 去年今天, `date_end` = 今天 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start == today.replace(year=today.year-1)` |

**代码路径**：`_parse_date_range` Priority 11 `近(\d+)年` → `start = today.replace(year=today.year - n)`，注意闰年 2/29 可能触发 ValueError（未在代码中处理）

---

### TC-013：上月 / 上个月

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `上月` |
| **预期 rule_based_parse** | `date_start` = 上月 1 日, `date_end` = 上月最后一天 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start.month == today.month - 1`（或 12月→11月）, `date_end` = 上月最后一天 |

**代码路径**：`_parse_date_range` Priority 10 `if "上月" in text or "上个月" in text` → 本月1日-1天 = 上月最后一天, day=1 → 上月1日

---

### TC-014：本季度

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `本季度` |
| **预期 rule_based_parse** | `date_start` = 本季度首月 1 日, `date_end` = 今天 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start.month` 属于 {1,4,7,10}，`date_start.day == 1`，同季度 |

**代码路径**：`_parse_date_range` Priority 13 `if "本季度" in text` → `quarter_start_month = (month-1)//3*3+1`

---

### TC-015：上旬 / 中旬 / 下旬

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `上旬` |
| **预期 rule_based_parse** | `date_start` = 本月 1 日, `date_end` = 本月 10 日 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_end.day == 10`；中旬 → 11-20；下旬 → 21-月底 |

**代码路径**：`_parse_date_range` Priority 7 `if "上旬" in text` → (本月1日, 本月10日)

---

### TC-016：显式完整日期（YYYY年MM月DD日）

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `2025年3月15日` |
| **预期 rule_based_parse** | `date_start` = 2025-03-15, `date_end` = 2025-03-15 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `date_start == date_end == "2025-03-15"` |

**代码路径**：`_parse_date_range` Priority 2 `(\d{4})年(\d{1,2})月(\d{1,2})日`

---

### TC-017：显式范围（YYYY-MM-DD 到 YYYY-MM-DD）

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 |
| **自然语言输入** | `2025-01-01 到 2025-03-31` |
| **预期 rule_based_parse** | `date_start` = 2025-01-01, `date_end` = 2025-03-31 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | 精确匹配显式范围，最高优先级（Priority 1）|

**代码路径**：`_parse_date_range` Priority 1 `(\d{4})-(\d{2})-(\d{2})\s*到\s*(\d{4})-(\d{2})-(\d{2})`

---

### TC-018：上半年（规则不支持 -- 已知缺陷）

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 -- 边界情况 |
| **自然语言输入** | `上半年` |
| **预期 rule_based_parse** | `date_start` = "", `date_end` = ""（空字符串）|
| **gatekeep 覆盖** | gatekeep 阶段 2 时间回退重新调用 `_parse_date_range`，同样返回空 |
| **预期置信度** | ~0.25（日期 0 + 无实体 1.0 = 1.0/4.0）|
| **预期 SQL 路由** | 明细查询（无日期过滤，全量扫描） |
| **验证要点** | "上半年" 虽在 semantic_rules.json 中有定义，但 parser 中无对应实现。验证解析结果日期为空。 |

**代码路径**：`_parse_date_range` 无 "上半年" 匹配逻辑 → fall through → `return ("", "")`。semantic_rules.json 中有描述但代码中未实现。

---

### TC-019：不存在的日期（2月30日）

| 项目 | 内容 |
|------|------|
| **测试分类** | 日期解析 -- 边界情况 |
| **自然语言输入** | `2025年2月30日` |
| **预期 rule_based_parse** | `date_start` = 2025-02-28, `date_end` = 2025-02-28（regex 只验证格式，不验证合法性）|
| **gatekeep 覆盖** | 无覆盖（gatekeep 不校验日期合法性） |
| **预期置信度** | ~0.625 |
| **预期 SQL 路由** | 明细查询（SQL 中 `20250230` 被当作无效整数比较） |
| **验证要点** | regex `(\d{4})年(\d{1,2})月(\d{1,2})日` 只捕获数字不验证日期合法性。SQL 端的 `TRADEDATE<=20250230` 在 Oracle 中可能有不可预期行为。这是已知安全边界，应由上层校验。 |

---

## 二、银行/客户（6 个场景）

### TC-020：XX银行

| 项目 | 内容 |
|------|------|
| **测试分类** | 银行名称 |
| **自然语言输入** | `工商银行` |
| **预期 rule_based_parse** | `bank_name` = "工商银行", `dimension` = "bank" |
| **gatekeep 覆盖** | 无覆盖（规则已解析） |
| **预期置信度** | ~0.25（无日期 0 + bank_name 1.0 + 无意向 0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `bank_name == "工商银行"` |

**代码路径**：`_parse_bank_name` regex `([一-鿿]{2,}银行)` → 匹配"工商银行"

---

### TC-021：XX分行

| 项目 | 内容 |
|------|------|
| **测试分类** | 银行名称 |
| **自然语言输入** | `北京分行` |
| **预期 rule_based_parse** | `bank_name` = "北京分行", `dimension` = "bank" |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `bank_name == "北京分行"` |

**代码路径**：`_parse_bank_name` regex `([一-鿿]{2,}(?:分行|支行|分公司|营业部))` → 匹配"北京分行"

---

### TC-022：XX银行XX分行（全名组合）

| 项目 | 内容 |
|------|------|
| **测试分类** | 银行名称 |
| **自然语言输入** | `中国银行北京分行` |
| **预期 rule_based_parse** | `bank_name` = "中国银行北京分行", `dimension` = "bank" |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `bank_name == "中国银行北京分行"` |

**代码路径**：`_parse_bank_name` 优先匹配全名 `([一-鿿]{2,}(?:银行|公司))([一-鿿]{2,}(?:分行|支行|分公司|营业部))` → "中国银行"+"北京分行"

---

### TC-023：XX客户

| 项目 | 内容 |
|------|------|
| **测试分类** | 客户名称 |
| **自然语言输入** | `测试客户` |
| **预期 rule_based_parse** | `cust_name` = "测试客户", `dimension` = "customer", `bank_name` = "" |
| **gatekeep 覆盖** | `dimension=customer (cust_name present)`（阶段 3） |
| **预期置信度** | ~0.25（无日期 0 + cust_name 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `cust_name == "测试客户"`, `dimension == "customer"`, `bank_name == ""` |

**代码路径**：`_parse_cust_name` Pattern 1 → 匹配"测试客户"。然后在 `rule_based_parse` 中因为 cust_name 非空，覆盖 `dimension="customer"`, `bank_name=""`。gatekeep 阶段 3 再次确认。

---

### TC-024：XX的套保率（客户维度+套保率）

| 项目 | 内容 |
|------|------|
| **测试分类** | 客户名称 + 套保率 |
| **自然语言输入** | `小鱼儿的套保率` |
| **预期 rule_based_parse** | `cust_name` = "小鱼儿", `hedge_ratio` = true, `dimension` = "customer", `bank_name` = "" |
| **gatekeep 覆盖** | `dimension=customer (cust_name present)`, 套保率检测 `hedge_ratio=True`（阶段聚合检测） |
| **预期置信度** | ~1.0（无日期但 entity 1.0 + hedge_ratio intent 1.5 = 2.5/4.0 = 0.625？）<br>不对：无日期→0, 有 cust_name→1.0, hedge_ratio→1.5 = 2.5/4=0.625，调用 LLM（date 未命中） |
| **预期 SQL 路由** | 套保率查询（`build_hedge_ratio_query`），dimension="customer" |
| **验证要点** | `cust_name == "小鱼儿"`, `hedge_ratio == True`, `dimension == "customer"` |

**代码路径**：`_parse_cust_name` Pattern 2 `XX的套保率` → "小鱼儿", `_parse_hedge_ratio` → True

---

### TC-025：客户+银行互斥

| 项目 | 内容 |
|------|------|
| **测试分类** | 互斥校验 |
| **自然语言输入** | `工商银行 测试客户 的交易量` |
| **预期 rule_based_parse** | `cust_name` = "测试客户", `bank_name` = ""（客户优先）|
| **gatekeep 覆盖** | `dimension=customer (cust_name present)`；阶段 5 互斥校验确保 `bank_name=""` |
| **预期置信度** | ~0.625（日期 0 + entity 1.0 + 无意向信号...等等"交易量"会触发 aggregate）→ aggregate=True → 日期 0 + entity 1.0 + intent 1.5 = 2.5/4 = 0.625，< 0.8 调用 LLM |
| **预期 SQL 路由** | 聚合查询（`build_aggregate_query`） |
| **验证要点** | `cust_name` 非空时 `bank_name` 必须为 `""` |

**代码路径**：`rule_based_parse` 中 `if cust_name: dimension="customer"; bank_name=""`。gatekeep 阶段 5 互斥校验再次确认。

---

## 三、买卖方向（7 个场景）

### TC-026：结汇（铁律 B + appid=2）

| 项目 | 内容 |
|------|------|
| **测试分类** | 买卖方向 -- 铁律 |
| **自然语言输入** | `今天结汇` |
| **预期 rule_based_parse** | `buy_sell` = "B", `appid` = 2 |
| **gatekeep 覆盖** | `buy_sell=B,appid=2 (结汇=银行买入外汇，属结售汇业务，不受客户前缀影响)` |
| **预期置信度** | ~0.625（日期 1.5 + 无实体 1.0 + 无意向 0 = 2.5/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询（含 `BUYORSELL='B'` 和 `APPID=2`） |
| **验证要点** | `buy_sell == "B"`, `appid == 2`；gatekeep 铁律覆盖写入日志 |

**代码路径**：`_parse_buy_sell` 中铁律先行 → "结汇"→"B"。`rule_based_parse` 中 `is_jieshouhui` 检测到"结汇"→ appid=2。
gatekeep 阶段 1a 再次通过 `buy_sell_direction` rules 确认：`customer_reversible=false, direction="B", set_app_id=2`。

---

### TC-027：购汇（铁律 S + appid=2）

| 项目 | 内容 |
|------|------|
| **测试分类** | 买卖方向 -- 铁律 |
| **自然语言输入** | `购汇` |
| **预期 rule_based_parse** | `buy_sell` = "S", `appid` = 2 |
| **gatekeep 覆盖** | `buy_sell=S,appid=2 (购汇/售汇=银行卖出外汇，属结售汇业务)` |
| **预期置信度** | ~0.25（无日期 0 + 无实体 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询（`BUYORSELL='S'`, `APPID=2`） |
| **验证要点** | `buy_sell == "S"`, `appid == 2` |

---

### TC-028：售汇（铁律 S + appid=2）

| 项目 | 内容 |
|------|------|
| **测试分类** | 买卖方向 -- 铁律 |
| **自然语言输入** | `售汇交易` |
| **预期 rule_based_parse** | `buy_sell` = "S", `appid` = 2 |
| **gatekeep 覆盖** | `buy_sell=S,appid=2`（售汇匹配购汇/售汇规则） |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `buy_sell == "S"`, `appid == 2`；"售汇"和"购汇"共用同一铁律规则 |

---

### TC-029：结售汇（同时出现 → 方向清空 + appid=2）

| 项目 | 内容 |
|------|------|
| **测试分类** | 买卖方向 -- 特例 |
| **自然语言输入** | `本月结售汇` |
| **预期 rule_based_parse** | `buy_sell` = "", `appid` = 2 |
| **gatekeep 覆盖** | 阶段 1b："结售汇"特例 → `appid=2`, `buy_sell=""` |
| **预期置信度** | ~0.625（日期 1.5 + 无实体 1.0 = 2.5/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询（不过滤 `BUYORSELL`，但 `APPID=2`） |
| **验证要点** | `buy_sell == ""`, `appid == 2`；"结售汇"同时含结汇和售汇，不筛选方向 |

**代码路径**：`rule_based_parse` 中 `if "结售汇" in text: buy_sell = ""`；`is_jieshouhui` 检测到 "结售汇" → `appid=2`。
gatekeep 阶段 1b 再次确认。

---

### TC-030：买入（可反转规则 B）

| 项目 | 内容 |
|------|------|
| **测试分类** | 买卖方向 -- 可反转 |
| **自然语言输入** | `买入` |
| **预期 rule_based_parse** | `buy_sell` = "B", `appid` = None |
| **gatekeep 覆盖** | 无客户前缀 → 不可反转 → 保持 B。（或者如果之前被 LLM 设置，铁律阶段不匹配，可反转阶段无客户也不覆盖） |
| **预期置信度** | ~0.25（无日期 0 + 无实体 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询（`BUYORSELL='B'`） |
| **验证要点** | `buy_sell == "B"`, `appid` 为 None（非结售汇业务） |

---

### TC-031：卖出（可反转规则 S）

| 项目 | 内容 |
|------|------|
| **测试分类** | 买卖方向 -- 可反转 |
| **自然语言输入** | `卖出` |
| **预期 rule_based_parse** | `buy_sell` = "S", `appid` = None |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询（`BUYORSELL='S'`） |
| **验证要点** | `buy_sell == "S"`, `appid` == None |

---

### TC-032：客户买入（客户前缀反转 → S）

| 项目 | 内容 |
|------|------|
| **测试分类** | 买卖方向 -- 客户反转 |
| **自然语言输入** | `客户买入` |
| **预期 rule_based_parse** | `buy_sell` = "B"（parser 不处理客户前缀） |
| **gatekeep 覆盖** | `customer_reversal buy_sell→S (即期/远期：银行买入(B)；客户买入→银行卖出(S))` |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询（最终 `BUYORSELL='S'`） |
| **验证要点** | 最终 `buy_sell == "S"`（客户前缀反转生效）。关键：parser 输出 B，gatekeep 反转为 S。 |

**代码路径**：`_parse_buy_sell` → "买入"→"B"。gatekeep 阶段 1c `has_customer=True` → 匹配买入可反转规则 → `customer_direction="S"` 覆盖。

---

### TC-033：客户卖出（客户前缀反转 → B）

| 项目 | 内容 |
|------|------|
| **测试分类** | 买卖方向 -- 客户反转 |
| **自然语言输入** | `客户卖出` |
| **预期 rule_based_parse** | `buy_sell` = "S"（parser 不处理客户前缀） |
| **gatekeep 覆盖** | `customer_reversal buy_sell→B` |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询（最终 `BUYORSELL='B'`） |
| **验证要点** | 最终 `buy_sell == "B"`（客户卖出 = 银行买入） |

---

## 四、产品类型（3 个场景）

### TC-034：即期

| 项目 | 内容 |
|------|------|
| **测试分类** | 产品类型 |
| **自然语言输入** | `即期交易` |
| **预期 rule_based_parse** | `product_type` = "spot" |
| **gatekeep 覆盖** | gatekeep 阶段 1e product_type 精确匹配 → "spot" |
| **预期置信度** | ~0.25（无日期 0 + 无实体 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询（仅查 `XF_FX_SPOTTRADE_VIEW`） |
| **验证要点** | SQL FROM 子句只包含 `XF_FX_SPOTTRADE_VIEW` |

---

### TC-035：远期

| 项目 | 内容 |
|------|------|
| **测试分类** | 产品类型 |
| **自然语言输入** | `远期结售汇` |
| **预期 rule_based_parse** | `product_type` = "fwd", `appid` = 2（"结售汇"关键词触发） |
| **gatekeep 覆盖** | product_type="fwd", appid=2, buy_sell="" (结售汇特殊处理) |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询（`XF_FX_FWDTRADE_VIEW`） |
| **验证要点** | `product_type == "fwd"`, `appid == 2` |

---

### TC-036：混合产品（即期+远期同时出现 → all）

| 项目 | 内容 |
|------|------|
| **测试分类** | 产品类型 |
| **自然语言输入** | `即期和远期交易` |
| **预期 rule_based_parse** | `product_type` = "all" |
| **gatekeep 覆盖** | gatekeep 阶段 1e：matched_types = ["spot", "fwd"] → len>1 → "all" |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询（UNION ALL 三个视图） |
| **验证要点** | `product_type == "all"`，SQL FROM 包含三个视图的 UNION ALL |

**代码路径**：`_parse_product_type` 中 has_spot=True, has_fwd=True → matched > 1 → "all"。
gatekeep：matched_types=["spot","fwd"] → len>1 → "all"。

---

## 五、聚合排名（6 个场景）

### TC-037：交易量（聚合触发）

| 项目 | 内容 |
|------|------|
| **测试分类** | 聚合排名 |
| **自然语言输入** | `今天交易量` |
| **预期 rule_based_parse** | `aggregate` = true, `date_start` = 今天, `date_end` = 今天 |
| **gatekeep 覆盖** | gatekeep 聚合检测阶段：`aggregate=True` |
| **预期置信度** | ~1.0（日期 1.5 + 无实体关键词 1.0 + aggregate intent 1.5 = 4.0/4.0），**跳过 LLM** |
| **预期 SQL 路由** | 聚合查询（`build_aggregate_query`，无 dimension 时返回单行 SUM+COUNT） |
| **验证要点** | `aggregate == True`, `confidence >= 0.8` → pipeline 为 `rule(confidence=100%)` |

**代码路径**：`_parse_aggregate` 关键词匹配 → True。置信度日期 1.5 + 无实体 1.0 + intent 1.5 = 4.0/4.0 = 1.0 >= 0.8 → 跳过 LLM。

---

### TC-038：TOP N（阿拉伯数字）

| 项目 | 内容 |
|------|------|
| **测试分类** | 聚合排名 |
| **自然语言输入** | `TOP 10 银行` |
| **预期 rule_based_parse** | `top_n` = 10, `dimension` = "bank" |
| **gatekeep 覆盖** | gatekeep TopN 回退阶段确认 `top_n=10` |
| **预期置信度** | ~0.625（日期 0 + entity(bank keyword but no bank_name matched→0) + intent 1.5 = 1.5/4.0 = 0.375...等等） |

让我重新计算："银行"在文本中 → `_text_has_entity_keyword` → True。但是 bank_name = ""（"TOP 10 银行" 中"银行"前没有两个以上中文字符，regex `[一-鿿]{2,}银行` 不匹配"10 银行"中的"银行"（"10 "中的0不是中文字符））→ entity=0。
<br>日期 0 + entity 0 + top_n intent 1.5 = 1.5/4.0 = 0.375。调用 LLM。

| **预期 SQL 路由** | 排名查询（`build_ranking_query`，top_n=10） |
| **验证要点** | `top_n == 10`, SQL 含 `ROWNUM <= 10` |

**代码路径**：`_parse_top_n` Priority 1 `[Tt][Oo][Pp]\s*([\d]+)` → 10

---

### TC-039：前N（中文数字）

| 项目 | 内容 |
|------|------|
| **测试分类** | 聚合排名 |
| **自然语言输入** | `前五` |
| **预期 rule_based_parse** | `top_n` = 5 |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.625（日期 0 + 无实体 1.0 + intent 1.5 = 2.5/4.0），调用 LLM |
| **预期 SQL 路由** | 排名查询（`build_ranking_query`，top_n=5） |
| **验证要点** | `top_n == 5`, `_cn_to_int("五") == 5` |

---

### TC-040：排名（默认 Top 10）

| 项目 | 内容 |
|------|------|
| **测试分类** | 聚合排名 |
| **自然语言输入** | `本月交易量排名` |
| **预期 rule_based_parse** | `top_n` = 10, `aggregate` = true, `date_start` = 本月 1 日, `date_end` = 今天 |
| **gatekeep 覆盖** | aggregate=True, top_n=10 |
| **预期置信度** | ~1.0（日期 1.5 + 无实体 1.0 + top_n intent 1.5 = 4.0/4.0），**跳过 LLM** |
| **预期 SQL 路由** | 排名查询（`build_ranking_query`，top_n=10；SQL 路由中 top_n 优先于 aggregate） |
| **验证要点** | `top_n == 10`（默认值）；路由优先级：top_n > aggregate |

**代码路径**：`_parse_top_n` Priority 3 "排名" without number → 10。SQL 路由中 `elif top_n and top_n > 0` 优先于 `elif parsed.get("aggregate")`。

---

### TC-041：金额过滤（大于+万）

| 项目 | 内容 |
|------|------|
| **测试分类** | 金额过滤 |
| **自然语言输入** | `大于100万` |
| **预期 rule_based_parse** | `amount_filter` = `{"amount_op": "gt", "amount_value": 1000000}` |
| **gatekeep 覆盖** | gatekeep 金额过滤回退：`amount_filter={"amount_op":"gt","amount_value":1000000}` |
| **预期置信度** | ~0.625（日期 0 + 无实体 1.0 + amount_filter intent 1.5 = 2.5/4.0），调用 LLM |
| **预期 SQL 路由** | 金额过滤查询（`build_filtered_query`, `HAVING SUM(t.USDAMOUNT) > 1000000`） |
| **验证要点** | `amount_op == "gt"`, `amount_value == 1000000`（100万 = 100 * 10000） |

**代码路径**：`_parse_amount_filter` gt_pat 匹配"大于" → op="gt"；提取数字 100；单位"万"→ multiplier=10000 → value=1000000。

---

### TC-042：金额过滤（小于+亿+套保率）

| 项目 | 内容 |
|------|------|
| **测试分类** | 金额过滤 + 套保率 |
| **自然语言输入** | `套保率低于50%` |
| **预期 rule_based_parse** | `hedge_ratio` = true, `amount_filter` = `{"amount_op": "lt", "amount_value": 50}` |
| **gatekeep 覆盖** | hedge_ratio=True（阶段套保率检测） |
| **预期置信度** | ~0.625（日期 0 + 无实体 1.0 + amount_filter intent 1.5 = 2.5/4.0），调用 LLM |
| **预期 SQL 路由** | 金额过滤查询（`build_filtered_query` with `hedge_ratio=True`，HAVING 使用套保率公式） |
| **验证要点** | `amount_op == "lt"`, `amount_value == 50`（%不触发万/亿乘法）; `hedge_ratio == True` |

**代码路径**：`_parse_amount_filter` lt_pat 匹配"低于"；数字 50；after_text="%" → multiplier=1 → value=50。当 hedge_ratio=True 时，`build_filtered_query` 的 HAVING 子句使用套保率公式。

---

## 六、对比（3 个场景）

### TC-043：同比（YoY）

| 项目 | 内容 |
|------|------|
| **测试分类** | 对比 |
| **自然语言输入** | `本月交易量同比` |
| **预期 rule_based_parse** | `comparison` = "yoy", `aggregate` = true, 日期=本月 1 日到今日 |
| **gatekeep 覆盖** | gatekeep 对比回退确认 `comparison=yoy` |
| **预期置信度** | ~1.0（日期 1.5 + 无实体 1.0 + aggregate intent 1.5 = 4.0/4.0），**跳过 LLM** |
| **预期 SQL 路由** | 聚合查询 + 对比 SQL（额外执行去年同期的 SQL） |
| **验证要点** | `comparison == "yoy"`；`compute_comparison_dates` 计算出的对比日期 = 去年同期 |

**代码路径**：`_parse_comparison_modifier` → "同比"→"yoy"。`compute_comparison_dates` 将日期整体前移一年。

---

### TC-044：环比（MoM）

| 项目 | 内容 |
|------|------|
| **测试分类** | 对比 |
| **自然语言输入** | `环比` |
| **预期 rule_based_parse** | `comparison` = "mom" |
| **gatekeep 覆盖** | gatekeep 对比回退：`comparison=mom` |
| **预期置信度** | ~0.25（日期 0 + 无实体 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询 + 对比 SQL |
| **验证要点** | `comparison == "mom"`；对比日期 = 前一等长周期 |

**代码路径**：`_parse_comparison_modifier` → "环比"→"mom"。`compute_comparison_dates` 中 delta = end-start, cmp_end = start-1day, cmp_start = cmp_end-delta。

---

### TC-045：同步（等价于同比）

| 项目 | 内容 |
|------|------|
| **测试分类** | 对比 |
| **自然语言输入** | `同步增加` |
| **预期 rule_based_parse** | `comparison` = "yoy"（"同步"在金融语境中等价于"同比"） |
| **gatekeep 覆盖** | gatekeep 对比回退：`comparison=yoy` |
| **预期置信度** | ~0.25（日期 0 + 无实体 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询 + 对比 SQL（YoY） |
| **验证要点** | `comparison == "yoy"` |

**代码路径**：`_parse_comparison_modifier` → `if "同步" in text: return "yoy"`。

---

## 七、特殊状态（5 个场景）

### TC-046：逾期

| 项目 | 内容 |
|------|------|
| **测试分类** | 特殊状态 |
| **自然语言输入** | `逾期交易` |
| **预期 rule_based_parse** | `special_states` = "1" |
| **gatekeep 覆盖** | gatekeep 阶段 1d `special_states=1` |
| **预期置信度** | ~0.25（日期 0 + 无实体 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询（`SPECIALSTATE IN (1)`） |
| **验证要点** | `special_states == "1"`, SQL WHERE 含 `t.SPECIALSTATE IN (1)` |

---

### TC-047：展期

| 项目 | 内容 |
|------|------|
| **测试分类** | 特殊状态 |
| **自然语言输入** | `展期` |
| **预期 rule_based_parse** | `special_states` = "3" |
| **gatekeep 覆盖** | `special_states=3` |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询（`SPECIALSTATE IN (3)`） |
| **验证要点** | `special_states == "3"` |

---

### TC-048：提前交割

| 项目 | 内容 |
|------|------|
| **测试分类** | 特殊状态 |
| **自然语言输入** | `提前交割` |
| **预期 rule_based_parse** | `special_states` = "4" |
| **gatekeep 覆盖** | `special_states=4` |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询（`SPECIALSTATE IN (4)`） |
| **验证要点** | `special_states == "4"` |

---

### TC-049：平仓

| 项目 | 内容 |
|------|------|
| **测试分类** | 特殊状态 |
| **自然语言输入** | `已平仓` |
| **预期 rule_based_parse** | `special_states` = "5"；`trade_class` = "1,2,6,7,10,11,15,17" |
| **gatekeep 覆盖** | `special_states=5`, `trade_class=1,2,6,7,10,11,15,17` |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询（`SPECIALSTATE IN (5)`，trade_class 不体现在 SQL 中） |
| **验证要点** | `special_states == "5"`; `trade_class` 包含全部平仓子类 |

**代码路径**：`_parse_special_states`: "已平仓"→"5"。`_parse_trade_class`: 无精确匹配"已平仓" → 泛化规则 `["平仓","平盘"]` → "1,2,6,7,10,11,15,17"。

注意：trade_class 字段目前不在 query_builder 的 SQL WHERE 中使用（仅 special_states 用于过滤）。

---

### TC-050：在途（NOT 特殊状态）

| 项目 | 内容 |
|------|------|
| **测试分类** | 特殊状态 -- 边界情况 |
| **自然语言输入** | `在途` |
| **预期 rule_based_parse** | `special_states` = ""（空字符串），`trade_class` = "" |
| **gatekeep 覆盖** | 无覆盖（"在途"不在 special_states 规则里，也不在 trade_class 规则里） |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询（无 SPECIALSTATE 过滤） |
| **验证要点** | `special_states == ""`，无 SQL WHERE 中的 SPECIALSTATE 条件 |

**代码路径**：`_parse_special_states` 的规则列表不包含"在途"。注释明确说明："在途"不是 SPECIALSTATE 字段，而是 totaldelivery 表剩余金额>0（未完结）。

---

## 八、交易类别（3 个场景）

### TC-051：精确匹配 -- 全部平仓

| 项目 | 内容 |
|------|------|
| **测试分类** | 交易类别 |
| **自然语言输入** | `全部平仓` |
| **预期 rule_based_parse** | `trade_class` = "6"（精确匹配） |
| **gatekeep 覆盖** | `trade_class=6` |
| **预期置信度** | ~0.25（日期 0 + 无实体 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询（trade_class 当前不参与 SQL WHERE 过滤） |
| **验证要点** | `trade_class == "6"`（精确匹配，不触发泛化规则） |

**代码路径**：`_parse_trade_class` 精确规则 `["全部平仓"]` → "6"

---

### TC-052：精确匹配 -- 提前平仓（多个值）

| 项目 | 内容 |
|------|------|
| **测试分类** | 交易类别 |
| **自然语言输入** | `提前平仓` |
| **预期 rule_based_parse** | `trade_class` = "1,10" |
| **gatekeep 覆盖** | `trade_class=1,10` |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `trade_class == "1,10"`（按数值排序）；精确匹配"提前平仓"优先于泛化"平仓" |

**代码路径**：精确规则 `["提前平仓"]` → "1,10"

---

### TC-053：泛化匹配 -- 仅"平仓"（未在精确列表中）

| 项目 | 内容 |
|------|------|
| **测试分类** | 交易类别 |
| **自然语言输入** | `平仓` |
| **预期 rule_based_parse** | `trade_class` = "1,2,6,7,10,11,15,17"（泛化规则，所有平仓子类） |
| **gatekeep 覆盖** | `trade_class=1,2,6,7,10,11,15,17` |
| **预期置信度** | ~0.25，调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `trade_class` 包含所有平仓子类（1,2,6,7,10,11,15,17）；排除了展期类（3,5,12,13）和提前交割（4,16） |

**代码路径**：精确规则中无"平仓"单独匹配 → `matched_set` 为空 → 泛化规则 `["平仓","平盘"]` → "1,2,6,7,10,11,15,17"

---

## 九、维度解析（2 个场景）

### TC-054：客户经理维度

| 项目 | 内容 |
|------|------|
| **测试分类** | 维度解析 |
| **自然语言输入** | `客户经理的交易量` |
| **预期 rule_based_parse** | `dimension` = "manager_name", `aggregate` = true |
| **gatekeep 覆盖** | `dimension=manager_name`（阶段维度回退） |
| **预期置信度** | ~0.625（日期 0 + entity 客户关键词但无 cust_name 匹配→0 + aggregate intent 1.5 = 1.5/4.0 = 0.375）<br>重新计算：`_text_has_entity_keyword("客户经理的交易量")` → has_cust=True（"客户"在 text）但 cust_name=""（"客户经理的交易量"中"客户"在开头，regex 无法捕获前面的字符），bank_name 也没有。entity=0。日期 0 + 0 + 1.5 = 1.5/4 = 0.375。调用 LLM。 |
| **预期 SQL 路由** | 聚合查询（`build_aggregate_query`，dimension="manager_name" → GROUP BY t.CUSTMANAGERNAME） |
| **验证要点** | `dimension == "manager_name"`, SQL GROUP BY 列 = `t.CUSTMANAGERNAME` |

**代码路径**：`_parse_dimension` 中"客户经理"匹配 Priority 3 `manager_name`。因为"客户经"前面没有字符满足 `{1,}`，所以 `_parse_cust_name` Pattern 1 无法匹配 → cust_name="" → dimension 保持 "manager_name"。

---

### TC-055：客户号维度

| 项目 | 内容 |
|------|------|
| **测试分类** | 维度解析 |
| **自然语言输入** | `客户编号` |
| **预期 rule_based_parse** | `dimension` = "customer_id" |
| **gatekeep 覆盖** | `dimension=customer_id` |
| **预期置信度** | ~0.25（日期 0 + entity "客户"关键词→has_cust=True 但无 cust_name 匹配→0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `dimension == "customer_id"` |

**代码路径**：`_parse_dimension` Priority 1，`re.search(r"客户号|客户编号|客户ID|客户\s*ID", text)` 匹配"客户编号"。

---

## 十、多轮对话（3 个场景）

### TC-056：上下文继承实体

| 项目 | 内容 |
|------|------|
| **测试分类** | 多轮对话 |
| **自然语言输入** | 第一轮：`工商银行的交易量`<br>第二轮：`排名前5`（携带 context） |
| **预期 rule_based_parse**（第二轮） | `top_n` = 5（规则解析）；日期和实体由 LLM 从 context 继承 |
| **gatekeep 覆盖** | 根据 LLM 输出做 gatekeep |
| **预期置信度** | ~0.625（日期 0 + 实体关键词但无匹配→0 + top_n intent 1.5 = 1.5/4.0 = 0.375），调用 LLM |
| **预期 SQL 路由** | LLM 从 context 继承 bank_name="工商银行" → 排名查询 |
| **验证要点** | 第二轮能正确从上一轮继承实体（银行名），并执行排名查询 |

**代码路径**：`/api/parse` 接收 `context` 参数，传入 `build_system_prompt(context)` 和 `llm_parse(text, system_prompt)`。LLM 被提示从 context 中提取继承信息。

---

### TC-057：上下文继承日期

| 项目 | 内容 |
|------|------|
| **测试分类** | 多轮对话 |
| **自然语言输入** | 第一轮：`本月交易量`<br>第二轮：`工商银行呢`（携带 context） |
| **预期 rule_based_parse**（第二轮） | `bank_name` = "工商银行"（规则解析）；无日期 |
| **gatekeep 覆盖** | 根据 LLM 输出做 gatekeep |
| **预期置信度** | ~0.25（日期 0 + bank_name 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | LLM 从 context 继承日期 → 聚合查询 |
| **验证要点** | 第二轮能从上一轮继承日期范围 |

---

### TC-058：追问分析（/api/analyze）

| 项目 | 内容 |
|------|------|
| **测试分类** | 多轮对话 -- 分析 |
| **自然语言输入** | 第一轮：`本月交易量同比`（获取对比数据）<br>第二轮：`为什么同比增加`（携带 previous_data） |
| **预期** | 第二轮调用 `/api/analyze` → LLM 自动决定需要哪些补充查询 → 执行 → 生成分析总结 |
| **gatekeep 覆盖** | analyze 内部对每个 sub-query 执行 rule_based_parse + gatekeep |
| **预期 SQL 路由** | analyze 流程：LLM 规划 → 多次 `/api/query` 等效调用 → 汇总分析 |
| **验证要点** | 响应含 `summary` 字段（自然语言分析文本）；LLM 可能自动查询排名等补充数据 |

**代码路径**：`/api/analyze` 端点。step1 LLM 规划查询 → step2 逐个执行 → step3 LLM 汇总分析。

---

## 十一、置信度分流（3 个场景）

### TC-059：高置信度 -- 跳过 LLM

| 项目 | 内容 |
|------|------|
| **测试分类** | 置信度分流 |
| **自然语言输入** | `今天工商银行交易量` |
| **预期 rule_based_parse** | `date_start` = 今天, `date_end` = 今天, `bank_name` = "工商银行", `aggregate` = true |
| **预期置信度** | 1.0（日期 1.5 + bank_name 1.0 + aggregate intent 1.5 = 4.0/4.0） |
| **pipeline** | `rule(confidence=100%)` -- 不调用 LLM |
| **预期 SQL 路由** | 聚合查询 |
| **验证要点** | `/api/parse` 响应 `pipeline` 字段不包含 "llm" |

**代码路径**：`_rule_confidence` 返回 1.0 >= 0.8 → `app.py` line 177-179, pipeline = "rule(confidence=100%)"。

---

### TC-060：低置信度 -- 调用 LLM

| 项目 | 内容 |
|------|------|
| **测试分类** | 置信度分流 |
| **自然语言输入** | `今天` |
| **预期 rule_based_parse** | `date_start` = 今天, `date_end` = 今天, 无其他填充 |
| **预期置信度** | 0.625（日期 1.5 + 无实体关键词 1.0 = 2.5/4.0） |
| **pipeline** | `llm+gatekeep(rule_confidence=62%)` -- 调用 LLM 补充解析 |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | `/api/parse` 响应 `pipeline` 包含 "llm" |

---

### TC-061：LLM 未配置 -- 回退到规则

| 项目 | 内容 |
|------|------|
| **测试分类** | 置信度分流 |
| **自然语言输入** | `今天`（LLM_API_KEY 未设置时） |
| **预期 rule_based_parse** | 同上 |
| **预期置信度** | 0.625 |
| **pipeline** | `rule_fallback(confidence=62%)` -- LLM 返回 None，回退到规则结果 |
| **预期 SQL 路由** | 明细查询 |
| **验证要点** | 当 LLM_API_KEY 未配置或为空时，`llm_parse` 返回 None → `app.py` line 190-191 走 fallback 路径 |

**代码路径**：`llm_client.py` line 64-71 检查 API_KEY/BASE_URL/MODEL，缺失时 `return None`。`app.py` line 187-191 捕获 None → 规则回退。

---

## 十二、边界情况（3 个场景）

### TC-062：空查询

| 项目 | 内容 |
|------|------|
| **测试分类** | 边界情况 |
| **自然语言输入** | ``（空字符串） |
| **预期 rule_based_parse** | 全部为默认值：`product_type="all"`, `date_start=""`, `date_end=""`, `special_states=""`, `buy_sell=""` 等 |
| **gatekeep 覆盖** | 无覆盖（所有回退均无匹配） |
| **预期置信度** | ~0.25（日期 0 + 无实体 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询（无任何过滤条件，全量扫描） |
| **验证要点** | 不应抛出异常；`/api/parse` 返回 `{"params": {...}, "pipeline": "...", "confidence": 0.25}` |

---

### TC-063：无意义文本

| 项目 | 内容 |
|------|------|
| **测试分类** | 边界情况 |
| **自然语言输入** | `阿巴阿巴` |
| **预期 rule_based_parse** | 全部为默认值（无任何关键词匹配） |
| **gatekeep 覆盖** | 无覆盖 |
| **预期置信度** | ~0.25（日期 0 + 无实体 1.0 = 1.0/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询（全量） |
| **验证要点** | 不崩溃，返回默认参数；LLM 可能返回有意义的解析或默认值 |

---

### TC-064：超长输入

| 项目 | 内容 |
|------|------|
| **测试分类** | 边界情况 |
| **自然语言输入** | 一段 500+ 字符的自然语言描述，其中包含多个日期、多家银行、多种方向关键词混合 |
| **预期 rule_based_parse** | 规则解析只取首个匹配（如日期取最高优先级匹配，银行取最长的 regex 匹配） |
| **gatekeep 覆盖** | gatekeep 铁律覆盖保证 buy_sell/appid 正确 |
| **预期置信度** | 取决于是否命中日期/实体/意图信号。大概率 < 0.8 → 调用 LLM |
| **预期 SQL 路由** | 取决于解析结果 |
| **验证要点** | 不因输入过长而崩溃；规则解析结果具有确定性（非随机） |

---

## 十三、综合场景（2 个场景）

### TC-065：全链路 -- 日期+银行+聚合+高置信度

| 项目 | 内容 |
|------|------|
| **测试分类** | 综合 |
| **自然语言输入** | `本月工商银行结汇交易量` |
| **预期 rule_based_parse** | `date_start` = 本月1日, `date_end` = 今天, `bank_name` = "工商银行", `buy_sell` = "B", `appid` = 2, `aggregate` = true |
| **gatekeep 覆盖** | `buy_sell=B,appid=2 (结汇=银行买入外汇)`（铁律）；`aggregate=True`（聚合检测） |
| **预期置信度** | 1.0（日期 1.5 + bank_name 1.0 + aggregate intent 1.5 = 4.0/4.0），**跳过 LLM** |
| **预期 SQL 路由** | 聚合查询（`build_aggregate_query`），WHERE 含 `BUYORSELL='B'` 和 `APPID=2` |
| **验证要点** | 完整链路：日期+银行+方向+appid+聚合 全部正确；pipeline 不含 "llm" |

---

### TC-066：展期+远期+银行+日期（综合）

| 项目 | 内容 |
|------|------|
| **测试分类** | 综合 |
| **自然语言输入** | `今年一季度工商银行远期展期交易` |
| **预期 rule_based_parse** | `date_start` = 2026-01-01, `date_end` = 2026-03-31, `bank_name` = "工商银行", `product_type` = "fwd", `special_states` = "3", `trade_class` = "3,5,12,13" |
| **gatekeep 覆盖** | `special_states=3`, `trade_class=3,5,12,13`（gatekeep 阶段 1d 精确匹配展期→3；阶段 1d2 trade_class 泛化匹配展期→3,5,12,13） |
| **预期置信度** | 0.625（日期 1.5 + bank_name 1.0 + 无意向（aggregate/hedge_ratio/top_n/amount_filter 均无） = 2.5/4.0），调用 LLM |
| **预期 SQL 路由** | 明细查询（`XF_FX_FWDTRADE_VIEW`, `SPECIALSTATE IN (3)`） |
| **验证要点** | 多个维度同时正确：日期（季度）+ 银行 + 产品类型 + 特殊状态 + 交易类别 |

---

## 十四、已知缺陷 / 待实现场景（1 个）

### TC-KNOWN-01：去年 / 前年（未实现）

| 项目 | 内容 |
|------|------|
| **测试分类** | 已知缺陷 |
| **自然语言输入** | `去年` |
| **预期 rule_based_parse** | `date_start` = "", `date_end` = ""（空字符串） |
| **原因** | semantic_rules.json 中定义了"去年"的时间表达式，但 `_parse_date_range` 中未实现对应解析逻辑 |
| **影响** | 查询"去年"会全量扫描，不会过滤到去年的数据范围 |
| **建议** | 在 `_parse_date_range` 中增加"去年"/"前年"等相对年份的优先级处理 |

---

## 附录：验证方法

### 单元测试验证（推荐）

```python
from llm_parser.parser import rule_based_parse, _rule_confidence
from llm_parser.rules_engine import gatekeep

text = "本月工商银行结汇交易量"
parsed = rule_based_parse(text)
confidence = _rule_confidence(text, parsed)
result = gatekeep(parsed, text)

# 断言
assert parsed["bank_name"] == "工商银行"
assert parsed["buy_sell"] == "B"
assert parsed["appid"] == 2
assert parsed["aggregate"] == True
assert confidence >= 0.8  # 高置信度跳过 LLM
```

### API 集成测试

```bash
curl -X POST http://localhost:8000/api/parse \
  -H "Content-Type: application/json" \
  -d '{"text": "本月工商银行结汇交易量"}'
```

检查响应中：
- `params.bank_name == "工商银行"`
- `params.buy_sell == "B"`
- `pipeline` 是否包含 "llm"（高置信度时不应包含）
- `confidence` 值

### 测试执行顺序建议

1. 先跑全部日期解析场景（TC-001 至 TC-019）：验证时间计算正确性
2. 再跑买卖方向（TC-026 至 TC-033）：验证铁律和客户反转
3. 然后跑银行/客户（TC-020 至 TC-025）：验证名称提取和互斥
4. 再跑产品类型/聚合/对比/特殊状态/交易类别
5. 最后跑综合场景和边界情况
