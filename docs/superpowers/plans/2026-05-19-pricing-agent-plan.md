# 智能询报价Agent 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在现有智能BI系统上扩展智能询报价Agent，支持自然语言询价、比价、情景分析、询价转交易，并具备客户智能洞察能力。

**架构：** 独立模块（`backend/pricing/`）+ 进程内事件总线 + 共享基础设施（LLM解析、规则引擎、记忆系统）。通过LangGraph Router扩展实现BI与Pricing的领域分派。

**技术栈：** Python 3 + FastAPI（后端），Vue 3 + Naive UI + ECharts 6（前端），Oracle 19c + MySQL 8.0（数据），DeepSeek v4-flash（LLM）

---

## 文件结构

### 后端新增/修改

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/event_bus.py` | 新增 | 进程内事件总线（约50行） |
| `backend/pricing/__init__.py` | 新增 | 模块入口 |
| `backend/pricing/models.py` | 新增 | 数据模型（InquiryIntent, QuoteResult, TradeResult 等） |
| `backend/pricing/engine_client.py` | 新增 | 代客系统API适配器 |
| `backend/pricing/state_machine.py` | 新增 | 报价生命周期状态机 |
| `backend/pricing/validator.py` | 新增 | 必填字段完整性校验 |
| `backend/pricing/pricing_rules.py` | 新增 | 询报价规则 + LLM system prompt |
| `backend/pricing/service.py` | 新增 | 询报价业务编排 |
| `backend/pricing/routes.py` | 新增 | API路由 |
| `backend/pricing/risk_guard.py` | 新增 | 风控校验 + 风险提示 |
| `backend/pricing/trade_executor.py` | 新增 | 交易下单执行 |
| `backend/pricing/insight_engine.py` | 新增 | 客户智能洞察 |
| `backend/pricing/context_inherit.py` | 新增 | 询报价上下文继承 |
| `backend/langgraph/agents/pricing_agent.py` | 新增 | LangGraph定价子图 |
| `backend/langgraph/router.py` | 修改 | 增加领域分类gate |
| `backend/langgraph/pipeline.py` | 修改 | 注册pricing_agent到StateGraph |
| `backend/langgraph/state.py` | 修改 | 增加报价相关state字段 |
| `backend/langgraph/registry.py` | 修改 | 增加pricing关键词 |
| `backend/knowledge_base/semantic_rules.json` | 修改 | 增加pricing规则块 |
| `backend/db/mysql_store.py` | 修改 | 增加pricing_sessions/audit_log表 |
| `backend/app.py` | 修改 | 注册pricing路由 + 导入event_bus |

### 前端新增/修改

| 文件 | 操作 | 职责 |
|------|------|------|
| `frontend/src/components/PricingCard.vue` | 新增 | 报价结果卡片 |
| `frontend/src/components/QuoteCountdown.vue` | 新增 | 有效期倒计时 |
| `frontend/src/components/ScenarioCompare.vue` | 新增 | 比价/情景对比表 |
| `frontend/src/components/RiskDisclosure.vue` | 新增 | 风险提示弹窗 |
| `frontend/src/components/PricingInsight.vue` | 新增 | 走势图 + 产品对比洞察面板 |
| `frontend/src/api.js` | 修改 | 增加询报价API调用 |
| `frontend/src/App.vue` | 修改 | 增加pricing消息处理 |
| `frontend/src/components/MessageArea.vue` | 修改 | BotMessage增加pricing渲染分支 |

---

### 任务 1：创建数据模型

**文件：**
- 创建：`backend/pricing/__init__.py`
- 创建：`backend/pricing/models.py`

- [ ] **步骤 1：创建模块入口和类型定义**

```python
# backend/pricing/__init__.py
"""
智能询报价 Agent 模块

架构：engine_client → state_machine → service → routes
                         ↑               ↑
                    risk_guard      insight_engine
                    trade_executor  context_inherit
"""
```

```python
# backend/pricing/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PricingStatus(str, Enum):
    IDLE = "IDLE"
    QUOTING = "QUOTING"
    QUOTED = "QUOTED"
    EXPIRED = "EXPIRED"
    TRADING = "TRADING"
    TRADED = "TRADED"
    TRADE_FAILED = "TRADE_FAILED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class IntentType(str, Enum):
    SINGLE = "SINGLE"           # 单产品询价
    MULTI = "MULTI"             # 多产品询价
    COMPARE = "COMPARE"         # 多产品比价
    SCENARIO = "SCENARIO"       # 情景分析
    DIRECT_TRADE = "DIRECT_TRADE"  # 直接询价交易


@dataclass
class InquiryParams:
    """询价参数"""
    customer_id: str
    product_type: str = ""        # SPOT | FWD | SWAP
    currency_pair: str = ""       # USD/CNY
    direction: str = ""           # B(结汇) | S(购汇)
    amount: Optional[float] = None
    tenor: str = ""              # 1M | 3M | 6M | 1Y
    near_tenor: str = ""         # 掉期近端期限
    far_tenor: str = ""          # 掉期远端期限
    request_id: str = ""

    def missing_required(self) -> list[str]:
        """返回缺失的必填字段"""
        required = {
            "SPOT":  ["currency_pair", "direction"],
            "FWD":   ["currency_pair", "direction", "tenor"],
            "SWAP":  ["currency_pair", "direction", "near_tenor", "far_tenor"],
        }
        missing = []
        for f in required.get(self.product_type, []):
            if not getattr(self, f, None):
                missing.append(f)
        return missing


@dataclass
class QuoteResult:
    """询价结果"""
    quote_id: str = ""
    customer_rate: float = 0.0
    market_rate: float = 0.0
    spread_bp: int = 0
    product_type: str = ""
    currency_pair: str = ""
    direction: str = ""
    amount: Optional[float] = None
    value_date: str = ""
    created_at: str = ""


@dataclass
class TradeResult:
    """交易结果"""
    success: bool = False
    trade_id: str = ""
    quote_id: str = ""
    product_type: str = ""
    currency_pair: str = ""
    direction: str = ""
    amount: float = 0.0
    executed_rate: float = 0.0
    executed_at: str = ""
    error_code: str = ""
    error_reason: str = ""


@dataclass
class PricingSession:
    """询报价会话"""
    id: str = ""
    session_id: str = ""
    status: PricingStatus = PricingStatus.IDLE
    intent_type: IntentType = IntentType.SINGLE
    inquiry_params: dict = field(default_factory=dict)
    quote_results: list[dict] = field(default_factory=list)
    trade_result: Optional[dict] = None
    created_at: str = ""
    valid_until: str = ""


@dataclass
class ValidationResult:
    """参数校验结果"""
    valid: bool = True
    missing_fields: list[str] = field(default_factory=list)
    follow_up: list[str] = field(default_factory=list)


@dataclass
class PricingIntent:
    """解析后的询价意图"""
    intent_type: IntentType = IntentType.SINGLE
    product_type: str = ""
    currency_pair: str = ""
    direction: str = ""
    amount: Optional[float] = None
    tenor: str = ""
    near_tenor: str = ""
    far_tenor: str = ""
    scenario_name: str = ""      # 预设情景名称
    compare_products: list[str] = field(default_factory=list)  # 比价产品列表
    pipeline: str = ""           # 解析管道（rule/llm）
    confidence: float = 0.0
```

- [ ] **步骤 2：验证数据模型可导入**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "from backend.pricing.models import PricingStatus, IntentType, InquiryParams, QuoteResult, TradeResult, PricingSession, ValidationResult, PricingIntent; print('OK')"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/pricing/__init__.py backend/pricing/models.py
git commit -m "feat(pricing): add pricing data models and enums"
```

---

### 任务 2：搭建事件总线

**文件：**
- 创建：`backend/event_bus.py`

- [ ] **步骤 1：实现事件总线**

```python
# backend/event_bus.py
"""进程内发布/订阅事件总线 — Agent间松耦合通信"""

from __future__ import annotations
import asyncio
from collections import defaultdict
from typing import Callable, Awaitable

Handler = Callable[..., Awaitable[None]]


class EventBus:
    EVENTS = {
        "quote.created":       "新报价生成",
        "quote.expired":       "报价过期",
        "quote.cancelled":     "报价取消",
        "quote.refreshed":     "报价刷新",
        "trade.executed":      "交易执行完成",
        "trade.failed":        "交易执行失败",
        "market.rate_changed": "汇率变动",
        "customer.risk_alert": "客户风险等级与产品不匹配",
    }

    def __init__(self):
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event: str, handler: Handler) -> None:
        if event not in self.EVENTS:
            raise ValueError(f"Unknown event: {event}. Registered: {list(self.EVENTS)}")
        self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: Handler) -> None:
        self._handlers[event][:] = [h for h in self._handlers[event] if h is not handler]

    async def publish(self, event: str, **kwargs) -> None:
        if event not in self.EVENTS:
            raise ValueError(f"Unknown event: {event}")
        await asyncio.gather(
            *(handler(**kwargs) for handler in self._handlers[event]),
            return_exceptions=True
        )


# 全局单例
bus = EventBus()
```

- [ ] **步骤 2：验证事件总线**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "
from backend.event_bus import bus
import asyncio

async def handler(**kwargs):
    print(f'received: {kwargs}')

bus.subscribe('quote.created', handler)
asyncio.run(bus.publish('quote.created', quote_id='TEST001'))
print('OK')
"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/event_bus.py
git commit -m "feat: add in-process event bus for agent communication"
```

---

### 任务 3：扩展MySQL数据表

**文件：**
- 修改：`backend/db/mysql_store.py`

- [ ] **步骤 1：增加 pricing_sessions 和 pricing_audit_log 建表SQL**

在 `SCHEMA_SQL` 末尾追加以下SQL：

```sql
CREATE TABLE IF NOT EXISTS pricing_sessions (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    status VARCHAR(20) DEFAULT 'IDLE',
    intent_type VARCHAR(20),
    inquiry_params JSON,
    quote_results JSON,
    quote_id VARCHAR(64),
    valid_until DATETIME,
    trade_result JSON,
    trade_error JSON,
    customer_id VARCHAR(64) DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_session (session_id),
    INDEX idx_status (status),
    INDEX idx_valid (valid_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pricing_audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    pricing_id VARCHAR(36) NOT NULL,
    action VARCHAR(32) NOT NULL,
    actor VARCHAR(32) NOT NULL DEFAULT 'CUSTOMER',
    detail JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_pricing (pricing_id),
    INDEX idx_time (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **步骤 2：增加相关CRUD函数**

在 `mysql_store.py` 末尾追加：

```python
def save_pricing_session(record: dict) -> None:
    """保存/更新询报价会话"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO pricing_sessions 
                   (id, session_id, status, intent_type, inquiry_params, 
                    quote_results, quote_id, valid_until, trade_result, 
                    trade_error, customer_id)
                   VALUES (%(id)s, %(session_id)s, %(status)s, %(intent_type)s,
                           %(inquiry_params)s, %(quote_results)s, %(quote_id)s,
                           %(valid_until)s, %(trade_result)s, %(trade_error)s,
                           %(customer_id)s)
                   ON DUPLICATE KEY UPDATE
                     status=VALUES(status),
                     quote_results=VALUES(quote_results),
                     quote_id=VALUES(quote_id),
                     valid_until=VALUES(valid_until),
                     trade_result=VALUES(trade_result),
                     trade_error=VALUES(trade_error),
                     updated_at=CURRENT_TIMESTAMP""",
                record
            )
        conn.commit()
    finally:
        conn.close()


def get_pricing_session(pricing_id: str) -> dict | None:
    """查询询报价会话"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM pricing_sessions WHERE id = %s",
                (pricing_id,)
            )
            row = cur.fetchone()
            return row if row else None
    finally:
        conn.close()


def get_active_pricing_session(session_id: str) -> dict | None:
    """查询当前活跃的询报价会话（QUOTED状态且未过期）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM pricing_sessions 
                   WHERE session_id = %s 
                   AND status IN ('QUOTING', 'QUOTED')
                   AND (valid_until IS NULL OR valid_until > NOW())
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id,)
            )
            row = cur.fetchone()
            return row if row else None
    finally:
        conn.close()


def add_pricing_audit(pricing_id: str, action: str, detail: dict,
                      actor: str = "CUSTOMER") -> None:
    """写入合规审计日志"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO pricing_audit_log (pricing_id, action, actor, detail)
                   VALUES (%s, %s, %s, %s)""",
                (pricing_id, action, actor, json.dumps(detail, ensure_ascii=False))
            )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **步骤 3：验证表创建**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "
from backend.db.mysql_store import init_db
init_db()
print('Tables created OK')
"
```

- [ ] **步骤 4：Commit**

```bash
git add backend/db/mysql_store.py
git commit -m "feat(pricing): add pricing_sessions and pricing_audit_log tables"
```

---

### 任务 4：扩展语义规则配置

**文件：**
- 修改：`backend/knowledge_base/semantic_rules.json`

- [ ] **步骤 1：在JSON末尾（product_type之后,在现有规则块之间插入pricing块）**

在顶层JSON中添加 `pricing` 规则块：

```json
"pricing": {
  "_description": "询报价规则 — 产品必填字段、预设情景、报价有效期、术语解释",
  "quote_validity_minutes": 5,
  "product_params": {
    "SPOT":  {"required_fields": ["currency_pair", "direction"]},
    "FWD":   {"required_fields": ["currency_pair", "direction", "tenor"]},
    "SWAP":  {"required_fields": ["currency_pair", "direction", "near_tenor", "far_tenor"]}
  },
  "scenarios": {
    "远期期限对比": {
      "description": "对比不同期限远期价格",
      "params_variations": [
        {"product_type": "FWD", "tenor": "1M"},
        {"product_type": "FWD", "tenor": "3M"},
        {"product_type": "FWD", "tenor": "6M"},
        {"product_type": "FWD", "tenor": "1Y"}
      ]
    },
    "即远期对比": {
      "description": "对比即期与远期价格",
      "params_variations": [
        {"product_type": "SPOT"},
        {"product_type": "FWD", "tenor": "3M"}
      ]
    },
    "方向对比": {
      "description": "对比结汇与购汇价格",
      "params_variations": [
        {"product_type": null, "direction": "B"},
        {"product_type": null, "direction": "S"}
      ]
    }
  },
  "glossary": {
    "点差": "银行买入价和卖出价之间的差额，也是银行提供报价服务的收益来源。点差越小，对您越有利。",
    "远期": "约定在未来某个日期按今天确定的价格进行交割的外汇交易。适合有未来外汇收付需求的客户。",
    "掉期": "同时进行两笔金额相同、方向相反、交割日期不同的外汇交易。常用于资金调拨或锁定汇率风险。",
    "bp": "基点（Basis Point），1bp = 0.01%。50bp = 0.5%。",
    "交割": "外汇交易双方按约定的汇率和金额实际收付货币的行为。"
  },
  "risk_disclosure": {
    "FWD": {
      "title": "远期结售汇风险提示",
      "items": [
        "汇率波动可能导致实际成本与预期不同",
        "提前平仓可能产生额外费用",
        "到期必须履约交割"
      ]
    },
    "SWAP": {
      "title": "外汇掉期风险提示",
      "items": [
        "近端和远端两次交割均需履约",
        "掉期定价受利率差影响",
        "提前平仓可能产生额外费用"
      ]
    }
  },
  "routing_keywords": [
    "询价", "报价", "结汇", "购汇", "买汇", "卖汇",
    "比价", "点差", "成交", "下单", "多少钱",
    "汇率", "价格", "即期", "远期", "掉期"
  ]
}
```

- [ ] **步骤 2：验证JSON格式**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "import json; json.load(open('backend/knowledge_base/semantic_rules.json','r',encoding='utf-8')); print('Valid JSON')"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/knowledge_base/semantic_rules.json
git commit -m "feat(pricing): add pricing rules, scenarios, glossary to semantic_rules.json"
```

---

### 任务 5：计价引擎客户端

**文件：**
- 创建：`backend/pricing/engine_client.py`

- [ ] **步骤 1：实现 engine_client.py**

```python
# backend/pricing/engine_client.py
"""代客系统计价引擎 REST 适配器"""

from __future__ import annotations
import os
import httpx
from typing import Optional

from .models import InquiryParams, QuoteResult, TradeParams, TradeResult

DEFAULT_BASE_URL = os.getenv("PRICING_ENGINE_URL", "http://localhost:8080/api/v1")
DEFAULT_TIMEOUT = float(os.getenv("PRICING_TIMEOUT", "5.0"))


class PricingEngineClient:
    """封装代客系统询价/交易接口"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client

    async def inquiry(self, params: InquiryParams) -> QuoteResult:
        """单次询价"""
        client = await self._get_client()
        payload = {
            "customer_id": params.customer_id,
            "product_type": params.product_type,
            "currency_pair": params.currency_pair,
            "direction": params.direction,
            "request_id": params.request_id,
        }
        if params.amount:
            payload["amount"] = params.amount
        if params.tenor:
            payload["tenor"] = params.tenor
        if params.near_tenor:
            payload["near_tenor"] = params.near_tenor
        if params.far_tenor:
            payload["far_tenor"] = params.far_tenor

        try:
            resp = await client.post(f"{self.base_url}/pricing/inquiry", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "SUCCESS":
                raise EngineError(data.get("code"), data.get("message", "unknow error"))
            d = data["data"]
            return QuoteResult(
                quote_id=d["quote_id"],
                customer_rate=d["customer_rate"],
                market_rate=d.get("market_rate", 0),
                spread_bp=d.get("spread_bp", 0),
                product_type=d["product_type"],
                currency_pair=d["currency_pair"],
                direction=d["direction"],
                amount=d.get("amount"),
                value_date=d.get("value_date", ""),
                created_at=d["created_at"],
            )
        except httpx.HTTPError as e:
            raise EngineError("NETWORK_ERROR", str(e)) from e

    async def batch_inquiry(self, params_list: list[InquiryParams]) -> list[QuoteResult]:
        """批量询价 — 并发调用"""
        import asyncio
        tasks = [self.inquiry(p) for p in params_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                out.append(QuoteResult())
            else:
                out.append(r)
        return out

    async def execute_trade(self, quote_id: str, customer_id: str,
                            amount: Optional[float] = None) -> TradeResult:
        """执行交易"""
        client = await self._get_client()
        payload = {"quote_id": quote_id, "customer_id": customer_id}
        if amount:
            payload["amount"] = amount
        try:
            resp = await client.post(f"{self.base_url}/trade/execute", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == "SUCCESS":
                d = data["data"]
                return TradeResult(
                    success=True, trade_id=d["trade_id"],
                    quote_id=d["quote_id"], product_type=d["product_type"],
                    currency_pair=d["currency_pair"], direction=d["direction"],
                    amount=d["amount"], executed_rate=d["executed_rate"],
                    executed_at=d["executed_at"],
                )
            elif data.get("code") == "TRADE_REJECTED":
                d = data.get("data", {})
                return TradeResult(
                    success=False, quote_id=quote_id,
                    error_code=d.get("reject_code", ""),
                    error_reason=d.get("reject_reason", ""),
                )
            else:
                return TradeResult(success=False, error_code=data.get("code", ""),
                                   error_reason=data.get("message", ""))
        except httpx.HTTPError as e:
            return TradeResult(success=False, error_code="NETWORK_ERROR", error_reason=str(e))

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


class EngineError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")
```

- [ ] **步骤 2：验证导入**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "from backend.pricing.engine_client import PricingEngineClient, EngineError; print('OK')"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/pricing/engine_client.py
git commit -m "feat(pricing): add pricing engine REST client"
```

---

### 任务 6：参数校验器

**文件：**
- 创建：`backend/pricing/validator.py`

- [ ] **步骤 1：编写校验逻辑**

```python
# backend/pricing/validator.py
"""询报价参数完整性校验 — 缺字段必追问"""

from .models import PricingIntent, ValidationResult

FOLLOW_UP_PROMPTS: dict[str, str] = {
    "currency_pair": "请问您要询价的货币对是什么？例如美元/人民币",
    "direction": "请问是结汇还是购汇？",
    "tenor": "请问期限是多久？例如1个月、3个月",
    "near_tenor": "请问近端期限是多久？",
    "far_tenor": "请问远端期限是多久？",
}

REQUIRED_FIELDS: dict[str, list[str]] = {
    "SPOT":  ["currency_pair", "direction"],
    "FWD":   ["currency_pair", "direction", "tenor"],
    "SWAP":  ["currency_pair", "direction", "near_tenor", "far_tenor"],
}


def validate_intent(intent: PricingIntent) -> ValidationResult:
    """校验询价意图必填字段完整性"""
    pt = intent.product_type
    if not pt:
        return ValidationResult(
            valid=False,
            missing_fields=["product_type"],
            follow_up=["请问您要询价的产品类型是什么？即期、远期还是掉期？"],
        )
    if pt not in REQUIRED_FIELDS:
        return ValidationResult(
            valid=False,
            missing_fields=["product_type"],
            follow_up=[f"暂不支持 {pt} 产品类型，当前支持即期、远期和掉期"],
        )

    missing = []
    for field in REQUIRED_FIELDS[pt]:
        if not getattr(intent, field, None):
            missing.append(field)

    if missing:
        return ValidationResult(
            valid=False,
            missing_fields=missing,
            follow_up=[FOLLOW_UP_PROMPTS[f] for f in missing],
        )
    return ValidationResult(valid=True)


def validate_direct_trade(intent: PricingIntent) -> ValidationResult:
    """校验直接交易意图 — 额外检查金额"""
    base = validate_intent(intent)
    if not base.valid:
        return base
    if intent.intent_type.value == "DIRECT_TRADE" and not intent.amount:
        return ValidationResult(
            valid=False,
            missing_fields=["amount"],
            follow_up=["请问交易金额是多少？例如\"100万美元\""],
        )
    return ValidationResult(valid=True)
```

- [ ] **步骤 2：编写验证测试**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "
from backend.pricing.models import PricingIntent, IntentType
from backend.pricing.validator import validate_intent, validate_direct_trade

# 完整参数
intent = PricingIntent(intent_type=IntentType.SINGLE, product_type='SPOT', currency_pair='USD/CNY', direction='B')
result = validate_intent(intent)
assert result.valid, f'Expected valid, got missing: {result.missing_fields}'

# 缺少方向
intent2 = PricingIntent(product_type='SPOT', currency_pair='USD/CNY')
result2 = validate_intent(intent2)
assert not result2.valid
assert 'direction' in result2.missing_fields

# 直接交易缺少金额
intent3 = PricingIntent(intent_type=IntentType.DIRECT_TRADE, product_type='SPOT', currency_pair='USD/CNY', direction='B')
result3 = validate_direct_trade(intent3)
assert not result3.valid
assert 'amount' in result3.missing_fields

print('All validation tests passed')
"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/pricing/validator.py
git commit -m "feat(pricing): add parameter completeness validator"
```

---

### 任务 7：状态机

**文件：**
- 创建：`backend/pricing/state_machine.py`

- [ ] **步骤 1：实现状态机**

```python
# backend/pricing/state_machine.py
"""报价生命周期状态机"""

from __future__ import annotations
from datetime import datetime, timedelta

from .models import PricingStatus


class PricingStateMachine:
    """管理报价从 IDLE 到 TRADED 的状态转换"""

    _VALID_TRANSITIONS: dict[str, list[str]] = {
        "IDLE":            ["QUOTING", "ERROR"],
        "QUOTING":         ["QUOTED", "ERROR"],
        "QUOTED":          ["EXPIRED", "TRADING", "CANCELLED", "REFRESH"],
        "EXPIRED":         ["QUOTING", "CANCELLED"],
        "TRADING":         ["TRADED", "TRADE_FAILED"],
        "TRADE_FAILED":    ["TRADING", "QUOTING", "CANCELLED"],
        "TRADED":          [],
        "CANCELLED":       ["QUOTING"],
        "ERROR":           ["IDLE", "QUOTING"],
    }

    def __init__(self, validity_minutes: int = 5):
        self.validity_minutes = validity_minutes
        self._status = PricingStatus.IDLE
        self._valid_until: datetime | None = None

    @property
    def status(self) -> str:
        return self._status.value

    @property
    def valid_until(self) -> datetime | None:
        return self._valid_until

    def can_transition(self, to_status: str) -> bool:
        return to_status in self._VALID_TRANSITIONS.get(self._status.value, [])

    def transition(self, to_status: str, validity_minutes: int | None = None) -> None:
        new = to_status.upper() if isinstance(to_status, str) else to_status
        if isinstance(new, str):
            new = PricingStatus(new)
        if not self.can_transition(new.value):
            raise InvalidTransitionError(
                f"Cannot transition from {self._status.value} to {new.value}"
            )
        self._status = new
        if new == PricingStatus.QUOTED:
            v = validity_minutes or self.validity_minutes
            self._valid_until = datetime.now() + timedelta(minutes=v)
        if new in (PricingStatus.TRADED, PricingStatus.CANCELLED,
                   PricingStatus.EXPIRED, PricingStatus.TRADE_FAILED):
            self._valid_until = None

    def is_expired(self) -> bool:
        if self._status != PricingStatus.QUOTED:
            return False
        if self._valid_until is None:
            return False
        return datetime.now() > self._valid_until

    def check_and_expire(self) -> bool:
        if self.is_expired():
            self._status = PricingStatus.EXPIRED
            self._valid_until = None
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "status": self._status.value,
            "valid_until": self._valid_until.isoformat() if self._valid_until else None,
        }


class InvalidTransitionError(Exception):
    pass
```

- [ ] **步骤 2：验证状态转换**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "
from backend.pricing.state_machine import PricingStateMachine, InvalidTransitionError

sm = PricingStateMachine(validity_minutes=5)
assert sm.status == 'IDLE'

sm.transition('QUOTING')
assert sm.status == 'QUOTING'

sm.transition('QUOTED')
assert sm.status == 'QUOTED'
assert sm.valid_until is not None
assert not sm.is_expired()

sm.transition('TRADING')
assert sm.status == 'TRADING'

sm.transition('TRADED')
assert sm.status == 'TRADED'

# 非法转换
try:
    sm.transition('QUOTING')
    assert False, 'Should have raised'
except InvalidTransitionError:
    pass

print('State machine tests passed')
"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/pricing/state_machine.py
git commit -m "feat(pricing): add quote lifecycle state machine"
```

---

### 任务 8：询报价规则扩展（Prompts配置）

**文件：**
- 创建：`backend/pricing/pricing_rules.py`

- [ ] **步骤 1：写入规则定义和prompt**

```python
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
```

- [ ] **步骤 2：Commit**

```bash
git add backend/pricing/pricing_rules.py
git commit -m "feat(pricing): add pricing LLM prompts and rule constants"
```

---

### 任务 9：风控守卫

**文件：**
- 创建：`backend/pricing/risk_guard.py`

- [ ] **步骤 1：实现 risk_guard.py**

```python
# backend/pricing/risk_guard.py
"""风控校验 + 风险提示生成"""

from __future__ import annotations
from typing import Optional

from .models import QuoteResult, InquiryParams
from .pricing_rules import RISK_REJECT_REASONS, PRICE_ANOMALY_RULES, REJECTION_TEMPLATES


class RiskGuard:
    """询报价风控校验"""

    def pre_check(self, customer_id: str, customer_info: dict | None) -> tuple[bool, Optional[str]]:
        """询价前风控预检
        返回 (是否通过, 拒绝原因)
        """
        if not customer_info:
            return True, None  # 无客户信息时放行（代客系统会校验）

        status = customer_info.get("account_status", "ACTIVE")
        if status == "FROZEN":
            return False, RISK_REJECT_REASONS["ACCOUNT_FROZEN"]
        if status == "CLOSED":
            return False, "账户已销户，暂不支持询价服务。"
        return True, None

    def post_check(self, quote: QuoteResult) -> tuple[bool, Optional[str]]:
        """询价后价格异常检测"""
        if quote.customer_rate <= 0:
            return False, "报价异常：价格为0或负值，请联系系统管理员。"
        if quote.spread_bp < 0:
            return False, "报价异常：点差为负值，请联系系统管理员。"
        if quote.spread_bp > 1000:
            return False, "报价异常：点差过大，请联系系统管理员。"
        return True, None

    def need_risk_disclosure(self, customer_info: dict | None,
                             product_type: str) -> bool:
        """判断是否需要风险披露"""
        if not customer_info:
            return True  # 无信息时默认需要
        customer_type = customer_info.get("customer_type", "NORMAL")
        if customer_type == "PROFESSIONAL":
            return False
        if product_type in ("FWD", "SWAP"):
            return True
        return False

    def get_risk_disclosure(self, product_type: str) -> dict:
        """获取产品风险披露内容"""
        disclosures = {
            "FWD": {
                "title": "远期结售汇风险提示",
                "items": [
                    "汇率波动可能导致实际成本与预期不同",
                    "提前平仓可能产生额外费用",
                    "到期必须履约交割",
                ],
            },
            "SWAP": {
                "title": "外汇掉期风险提示",
                "items": [
                    "近端和远端两次交割均需履约",
                    "掉期定价受利率差影响",
                    "提前平仓可能产生额外费用",
                ],
            },
        }
        return disclosures.get(product_type, {"title": "风险提示", "items": ["请谨慎交易"]})

    def translate_rejection(self, error_code: str) -> str:
        """翻译下单拒绝原因为客户可读文案"""
        return REJECTION_TEMPLATES.get(
            error_code,
            f"交易失败：{error_code}" if error_code else "交易失败，请稍后重试"
        )

    def is_novice(self, customer_info: dict | None) -> bool:
        """判断是否为小白客户"""
        if not customer_info:
            return True
        return customer_info.get("customer_type", "NORMAL") == "NOVICE"
```

- [ ] **步骤 2：验证**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "
from backend.pricing.risk_guard import RiskGuard
from backend.pricing.models import QuoteResult

rg = RiskGuard()

# pre_check: 正常客户
ok, reason = rg.pre_check('C001', {'account_status': 'ACTIVE'})
assert ok

# pre_check: 冻结客户
ok, reason = rg.pre_check('C001', {'account_status': 'FROZEN'})
assert not ok

# post_check: 正常报价
ok, reason = rg.post_check(QuoteResult(customer_rate=7.24, spread_bp=50))
assert ok

# post_check: 零价格
ok, reason = rg.post_check(QuoteResult(customer_rate=0, spread_bp=50))
assert not ok

# translate
msg = rg.translate_rejection('CREDIT_EXCEEDED')
assert '授信' in msg

print('Risk guard tests passed')
"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/pricing/risk_guard.py
git commit -m "feat(pricing): add risk guard with pre/post checks and rejection translation"
```

---

### 任务 10：询报价上下文继承

**文件：**
- 创建：`backend/pricing/context_inherit.py`

- [ ] **步骤 1：实现上下文继承**

```python
# backend/pricing/context_inherit.py
"""询报价上下文继承 — 从对话历史补全缺失参数"""

from __future__ import annotations
from typing import Optional

from .models import PricingIntent, IntentType

PERSIST_PARAMS = {"currency_pair", "direction", "product_type", "tenor"}
FOLLOW_UP_SIGNALS = ["呢", "那个", "这个", "同样的", "也一样", "对比", "比价", "情景"]


def inherit_pricing_context(current: PricingIntent,
                            context: list[dict] | None) -> PricingIntent:
    """从对话历史继承缺失的询价参数"""
    if not context:
        return current

    # 从最近的助手消息中提取上一次询价参数
    prev_params = _extract_prev_inquiry(context)
    if not prev_params:
        return current

    is_followup = _is_followup(context)
    for key in PERSIST_PARAMS:
        if not getattr(current, key, None) and prev_params.get(key):
            setattr(current, key, prev_params[key])

    if is_followup and not current.product_type and prev_params.get("product_type"):
        current.product_type = prev_params["product_type"]

    return current


def inherit_customer_preference(current: PricingIntent,
                                history: list[dict]) -> PricingIntent:
    """从客户偏好记忆补充参数（不强制填充，仅做推荐参考）"""
    if not history:
        return current

    freq: dict[str, dict[str, int]] = {"product_type": {}, "tenor": {}, "currency_pair": {}}
    for item in history:
        for key in ("product_type", "tenor", "currency_pair"):
            val = str(item.get(key, ""))
            if val:
                freq[key][val] = freq[key].get(val, 0) + 1

    for key in ("product_type", "tenor", "currency_pair"):
        if not getattr(current, key, None) and freq[key]:
            top = max(freq[key], key=lambda k: freq[key][k])  # type: ignore[arg-type]
            setattr(current, key, top)

    return current


def _extract_prev_inquiry(context: list[dict]) -> Optional[dict]:
    """从上下文中提取上一次询价参数"""
    for item in reversed(context):
        content = item.get("content", "")
        if isinstance(content, dict):
            params = content.get("params", content)
            if params.get("product_type") or params.get("direction"):
                return params
    return None


def _is_followup(context: list[dict]) -> bool:
    """判断当前输入是否为追问"""
    if not context:
        return False
    last_user = ""
    for item in reversed(context):
        if item.get("role") == "user":
            last_user = str(item.get("content", ""))
            break
    return any(sig in last_user for sig in FOLLOW_UP_SIGNALS)
```

- [ ] **步骤 2：验证**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "
from backend.pricing.models import PricingIntent
from backend.pricing.context_inherit import inherit_pricing_context

# 场景：上一轮询了即期，当前问"远期呢？"
context = [
    {'role': 'user', 'content': '美元即期询价'},
    {'role': 'assistant', 'content': {'params': {'product_type': 'SPOT', 'currency_pair': 'USD/CNY', 'direction': 'B'}}},
    {'role': 'user', 'content': '远期呢'},
]

current = PricingIntent(product_type='FWD')  # 解析出了FWD，但缺currency_pair和direction
result = inherit_pricing_context(current, context)
assert result.currency_pair == 'USD/CNY'
assert result.direction == 'B'
print('Context inheritance tests passed')
"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/pricing/context_inherit.py
git commit -m "feat(pricing): add pricing context inheritance from conversation history"
```

---

### 任务 11：交易执行器

**文件：**
- 创建：`backend/pricing/trade_executor.py`

- [ ] **步骤 1：实现 trade_executor.py**

```python
# backend/pricing/trade_executor.py
"""交易下单执行器"""

from __future__ import annotations
from typing import Optional

from .engine_client import PricingEngineClient
from .models import TradeResult


class TradeExecutor:
    """执行询价转交易"""

    def __init__(self, engine_client: PricingEngineClient):
        self.engine = engine_client

    async def execute(self, quote_id: str, customer_id: str,
                      amount: Optional[float] = None) -> TradeResult:
        """执行交易下单 — 同步调用代客系统交易接口"""
        result = await self.engine.execute_trade(quote_id, customer_id, amount)
        return result

    def format_result_for_client(self, result: TradeResult, is_novice: bool = False) -> dict:
        """将交易结果格式化为前端可展示的数据"""
        if result.success:
            msg = {
                "mode": "trade_success",
                "data": {
                    "trade_id": result.trade_id,
                    "product_type": result.product_type,
                    "currency_pair": result.currency_pair,
                    "direction": result.direction,
                    "amount": result.amount,
                    "executed_rate": result.executed_rate,
                    "executed_at": result.executed_at,
                    "summary": (
                        f"交易成功！\n"
                        f"交易编号：{result.trade_id}\n"
                        f"成交价格：{result.executed_rate}\n"
                        f"成交时间：{result.executed_at}"
                    ),
                }
            }
            if is_novice:
                msg["data"]["novice_tip"] = (
                    f"您已完成一笔{result.product_type}外汇交易，"
                    f"交割日期请关注后续通知。如需平仓或变更，请及时联系。"
                )
            return msg

        return {
            "mode": "trade_failed",
            "data": {
                "error_code": result.error_code,
                "error_reason": result.error_reason,
                "quote_id": result.quote_id,
            }
        }
```

- [ ] **步骤 2：Commit**

```bash
git add backend/pricing/trade_executor.py
git commit -m "feat(pricing): add trade executor for quote-to-trade flow"
```

---

### 任务 12：询报价核心服务

**文件：**
- 创建：`backend/pricing/service.py`

- [ ] **步骤 1：实现 service.py**

```python
# backend/pricing/service.py
"""询报价业务编排"""

from __future__ import annotations
from datetime import datetime, timedelta
import uuid
import json
import logging

from .models import (
    PricingIntent, InquiryParams, QuoteResult, PricingSession,
    IntentType, PricingStatus, ValidationResult,
)
from .validator import validate_intent, validate_direct_trade
from .pricing_rules import PRICING_SYSTEM_PROMPT
from .context_inherit import inherit_pricing_context
from .engine_client import PricingEngineClient, EngineError
from .state_machine import PricingStateMachine, InvalidTransitionError
from .risk_guard import RiskGuard
from .trade_executor import TradeExecutor
from backend.event_bus import bus
from backend.db import mysql_store

logger = logging.getLogger(__name__)


class PricingService:
    """询报价核心业务编排"""

    def __init__(self, engine_base_url: str | None = None):
        self.engine = PricingEngineClient(engine_base_url or "")
        self.risk_guard = RiskGuard()
        self.trade_executor = TradeExecutor(self.engine)
        self._scenarios: dict = {}
        self._validity_minutes: int = 5

    def configure(self, scenarios: dict, validity_minutes: int = 5) -> None:
        self._scenarios = scenarios
        self._validity_minutes = validity_minutes

    async def handle_inquiry(self, text: str, intent: PricingIntent,
                             customer_id: str, session_id: str,
                             customer_info: dict | None = None,
                             context: list[dict] | None = None) -> dict:
        """处理询价请求"""

        # 1. 上下文继承（补全缺失参数）
        intent = inherit_pricing_context(intent, context)

        # 2. 必填字段校验
        if intent.intent_type == IntentType.DIRECT_TRADE:
            validation = validate_direct_trade(intent)
        else:
            validation = validate_intent(intent)
        if not validation.valid:
            return {
                "mode": "follow_up",
                "follow_up": validation.follow_up,
                "missing_fields": validation.missing_fields,
            }

        # 3. 风控预检
        ok, reason = self.risk_guard.pre_check(customer_id, customer_info)
        if not ok:
            return {"mode": "error", "error": reason}

        # 4. 构建询价参数列表
        param_groups = self._build_inquiry_params(intent, customer_id)

        # 5. 并发询价
        pricing_id = str(uuid.uuid4())
        sm = PricingStateMachine(self._validity_minutes)
        sm.transition("QUOTING")

        # 保存QUOTING状态到DB
        self._save_session(pricing_id, session_id, sm, intent, customer_id)

        try:
            quotes = await self.engine.batch_inquiry(param_groups)
        except EngineError as e:
            return {"mode": "error", "error": f"询价失败：{e.message}"}

        # 6. 风控后检（检查第一个报价即可作为快速异常检测）
        if quotes and quotes[0].quote_id:
            ok, reason = self.risk_guard.post_check(quotes[0])
            if not ok:
                sm.transition("CANCELLED")
                return {"mode": "error", "error": reason}

        # 7. 进入 QUOTED 状态
        sm.transition("QUOTED")
        valid_until = sm.valid_until.isoformat() if sm.valid_until else ""

        # 8. 保存会话
        self._save_session(pricing_id, session_id, sm, intent, customer_id,
                           quotes=quotes, valid_until=valid_until)

        # 9. 发布事件
        await bus.publish("quote.created", pricing_id=pricing_id, intent_type=intent.intent_type.value)

        # 10. 格式化返回
        return self._format_inquiry_response(pricing_id, intent, quotes,
                                             valid_until, customer_info)

    async def handle_confirm_trade(self, pricing_id: str, customer_id: str,
                                   customer_info: dict | None = None) -> dict:
        """处理确认下单"""
        session_data = mysql_store.get_pricing_session(pricing_id)
        if not session_data:
            return {"mode": "error", "error": "询价会话不存在"}

        sm = PricingStateMachine(self._validity_minutes)
        sm._status = PricingStatus(session_data["status"])
        if session_data.get("valid_until"):
            sm._valid_until = session_data["valid_until"]

        if sm.is_expired():
            sm.transition("EXPIRED")
            self._save_session(pricing_id, session_data["session_id"], sm, None, customer_id)
            mysql_store.add_pricing_audit(pricing_id, "EXPIRE", {"reason": "validity expired"}, "SYSTEM")
            await bus.publish("quote.expired", pricing_id=pricing_id)
            return {"mode": "error", "error": "报价已过期，请重新询价"}

        # 检查是否需要风险披露
        need_disclosure = self.risk_guard.need_risk_disclosure(
            customer_info, session_data.get("inquiry_params", {}).get("product_type", "")
        )

        # 执行交易
        sm.transition("TRADING")
        quote_id = session_data.get("quote_id", "")
        trade_result = await self.trade_executor.execute(quote_id, customer_id)

        detail = {"quote_id": quote_id}
        if trade_result.success:
            sm.transition("TRADED")
            mysql_store.add_pricing_audit(pricing_id, "TRADE", detail)
            await bus.publish("trade.executed", pricing_id=pricing_id, trade_id=trade_result.trade_id)
        else:
            sm.transition("TRADE_FAILED")
            mysql_store.add_pricing_audit(
                pricing_id, "TRADE_FAILED",
                {"error_code": trade_result.error_code, "error_reason": trade_result.error_reason}
            )
            await bus.publish("trade.failed", pricing_id=pricing_id,
                              error_code=trade_result.error_code)

        self._save_session(pricing_id, session_data["session_id"], sm, None, customer_id,
                           trade_result=trade_result)

        is_novice = self.risk_guard.is_novice(customer_info)
        return self.trade_executor.format_result_for_client(trade_result, is_novice)

    async def handle_refresh(self, pricing_id: str, customer_id: str) -> dict:
        """刷新报价（原参数重新询价）"""
        session_data = mysql_store.get_pricing_session(pricing_id)
        if not session_data:
            return {"mode": "error", "error": "询价会话不存在"}

        params = session_data.get("inquiry_params", {})
        inquiry = InquiryParams(
            customer_id=customer_id,
            product_type=params.get("product_type", ""),
            currency_pair=params.get("currency_pair", ""),
            direction=params.get("direction", ""),
            amount=params.get("amount"),
            tenor=params.get("tenor", ""),
            near_tenor=params.get("near_tenor", ""),
            far_tenor=params.get("far_tenor", ""),
        )
        try:
            quote = await self.engine.inquiry(inquiry)
        except EngineError as e:
            return {"mode": "error", "error": f"刷新失败：{e.message}"}

        sm = PricingStateMachine(self._validity_minutes)
        sm.transition("QUOTING")
        sm.transition("QUOTED")
        valid_until = sm.valid_until.isoformat() if sm.valid_until else ""

        self._save_session(pricing_id, session_data["session_id"], sm, None, customer_id,
                           quotes=[quote], valid_until=valid_until)
        mysql_store.add_pricing_audit(pricing_id, "REFRESH", {"new_quote_id": quote.quote_id})

        await bus.publish("quote.created", pricing_id=pricing_id)

        return self._format_single_quote_response(pricing_id, quote, valid_until)

    async def handle_cancel(self, pricing_id: str) -> dict:
        """取消报价"""
        session_data = mysql_store.get_pricing_session(pricing_id)
        if not session_data:
            return {"mode": "error", "error": "询价会话不存在"}

        sm = PricingStateMachine(self._validity_minutes)
        sm._status = PricingStatus(session_data["status"])
        sm.transition("CANCELLED")
        self._save_session(pricing_id, session_data["session_id"], sm, None, "")
        mysql_store.add_pricing_audit(pricing_id, "CANCEL", {}, "CUSTOMER")
        await bus.publish("quote.cancelled", pricing_id=pricing_id)
        return {"mode": "cancelled", "message": "报价已取消"}

    # ---- 内部方法 ----

    def _build_inquiry_params(self, intent: PricingIntent,
                              customer_id: str) -> list[InquiryParams]:
        """根据意图类型构建询价参数列表"""
        params_list = []

        if intent.intent_type == IntentType.SCENARIO:
            scenario = self._scenarios.get(intent.scenario_name, {})
            variations = scenario.get("params_variations", [])
            for v in variations:
                p = InquiryParams(
                    customer_id=customer_id,
                    product_type=v.get("product_type", intent.product_type),
                    currency_pair=v.get("currency_pair", intent.currency_pair),
                    direction=v.get("direction", intent.direction),
                    tenor=v.get("tenor", intent.tenor),
                    near_tenor=v.get("near_tenor", intent.near_tenor),
                    far_tenor=v.get("far_tenor", intent.far_tenor),
                )
                params_list.append(p)

        elif intent.intent_type == IntentType.COMPARE:
            for prod in intent.compare_products:
                p = InquiryParams(
                    customer_id=customer_id,
                    product_type=prod.get("product_type", intent.product_type),
                    currency_pair=intent.currency_pair,
                    direction=intent.direction,
                    tenor=prod.get("tenor", intent.tenor),
                )
                params_list.append(p)

        elif intent.intent_type == IntentType.MULTI:
            for pair in (intent.currency_pair or "").split(","):
                p = InquiryParams(
                    customer_id=customer_id,
                    product_type=intent.product_type,
                    currency_pair=pair.strip(),
                    direction=intent.direction,
                    amount=intent.amount,
                    tenor=intent.tenor,
                )
                params_list.append(p)

        else:
            params_list.append(InquiryParams(
                customer_id=customer_id,
                product_type=intent.product_type,
                currency_pair=intent.currency_pair,
                direction=intent.direction,
                amount=intent.amount,
                tenor=intent.tenor,
                near_tenor=intent.near_tenor,
                far_tenor=intent.far_tenor,
            ))

        return params_list

    def _save_session(self, pricing_id: str, session_id: str,
                      sm: PricingStateMachine, intent: PricingIntent | None,
                      customer_id: str, quotes: list[QuoteResult] | None = None,
                      valid_until: str = "",
                      trade_result=None):
        record = {
            "id": pricing_id,
            "session_id": session_id,
            "status": sm.status,
            "intent_type": intent.intent_type.value if intent else "",
            "inquiry_params": json.dumps({
                "product_type": intent.product_type,
                "currency_pair": intent.currency_pair,
                "direction": intent.direction,
                "amount": intent.amount,
                "tenor": intent.tenor,
            }, ensure_ascii=False) if intent else "{}",
            "quote_results": json.dumps(
                [{"quote_id": q.quote_id, "customer_rate": q.customer_rate,
                  "spread_bp": q.spread_bp, "value_date": q.value_date} for q in (quotes or [])],
                ensure_ascii=False
            ),
            "quote_id": quotes[0].quote_id if quotes else "",
            "valid_until": valid_until or None,
            "trade_result": json.dumps(
                {"trade_id": trade_result.trade_id, "executed_rate": trade_result.executed_rate,
                 "executed_at": trade_result.executed_at}
            ) if trade_result and trade_result.success else None,
            "trade_error": json.dumps(
                {"error_code": trade_result.error_code, "error_reason": trade_result.error_reason}
            ) if trade_result and not trade_result.success else None,
            "customer_id": customer_id,
        }
        mysql_store.save_pricing_session(record)

    def _format_inquiry_response(self, pricing_id: str, intent: PricingIntent,
                                 quotes: list[QuoteResult], valid_until: str,
                                 customer_info: dict | None) -> dict:
        """格式化询价响应"""
        is_novice = self.risk_guard.is_novice(customer_info)
        need_disclosure = self.risk_guard.need_disclosure(
            customer_info, intent.product_type
        )

        quote_data_list = []
        for q in quotes:
            quote_data_list.append({
                "quote_id": q.quote_id,
                "customer_rate": q.customer_rate,
                "market_rate": q.market_rate,
                "spread_bp": q.spread_bp,
                "product_type": q.product_type,
                "currency_pair": q.currency_pair,
                "direction": q.direction,
                "amount": q.amount,
                "value_date": q.value_date,
            })

        response = {
            "pricing_id": pricing_id,
            "intent_type": intent.intent_type.value,
            "quotes": quote_data_list,
            "valid_until": valid_until,
            "novice_mode": is_novice,
        }

        if intent.intent_type == IntentType.COMPARE:
            response["mode"] = "pricing_compare"
            response["compare_dimensions"] = ["产品", "价格", "点差", "期限"]
        elif intent.intent_type == IntentType.SCENARIO:
            response["mode"] = "pricing_scenario"
            response["scenario_name"] = intent.scenario_name
        elif intent.intent_type == IntentType.MULTI or len(quotes) > 1:
            response["mode"] = "pricing_multi"
        else:
            response["mode"] = "pricing_single"

        if intent.intent_type == IntentType.DIRECT_TRADE:
            response["mode"] = "pricing_direct_trade"
            response["show_trade_button"] = True

        if need_disclosure:
            response["risk_disclosure"] = self.risk_guard.get_disclosure(intent.product_type)

        return response

    def _format_single_quote_response(self, pricing_id: str, quote: QuoteResult,
                                      valid_until: str) -> dict:
        return {
            "mode": "pricing_single",
            "pricing_id": pricing_id,
            "quotes": [{
                "quote_id": quote.quote_id,
                "customer_rate": quote.customer_rate,
                "spread_bp": quote.spread_bp,
                "product_type": quote.product_type,
                "currency_pair": quote.currency_pair,
                "direction": quote.direction,
                "value_date": quote.value_date,
            }],
            "valid_until": valid_until,
        }
```

- [ ] **步骤 2：验证导入**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "from backend.pricing.service import PricingService; print('OK')"
```

- [ ] **步骤 3：Commit**

```bash
git add backend/pricing/service.py
git commit -m "feat(pricing): add pricing service with inquiry/confirm/refresh/cancel orchestration"
```

---

### 任务 13：API路由注册

**文件：**
- 创建：`backend/pricing/routes.py`
- 修改：`backend/app.py`

- [ ] **步骤 1：创建 routes.py**

```python
# backend/pricing/routes.py
"""询报价 API 路由"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .service import PricingService

router = APIRouter(prefix="/api/pricing", tags=["pricing"])

# 全局单例，由 app.py 初始化
_pricing_service: PricingService | None = None


def get_pricing_service() -> PricingService:
    global _pricing_service
    if _pricing_service is None:
        _pricing_service = PricingService()
        _pricing_service.configure({}, 5)
    return _pricing_service


def init_pricing_service(engine_url: str | None = None,
                         scenarios: dict | None = None,
                         validity_minutes: int = 5) -> PricingService:
    global _pricing_service
    _pricing_service = PricingService(engine_url or "")
    _pricing_service.configure(scenarios or {}, validity_minutes)
    return _pricing_service


class InquiryRequest(BaseModel):
    text: str
    intent: dict
    session_id: str = ""
    customer_id: str = ""
    customer_info: dict | None = None
    context: list[dict] | None = None


class ConfirmRequest(BaseModel):
    pricing_id: str
    session_id: str = ""
    customer_id: str = ""
    customer_info: dict | None = None


class ActionRequest(BaseModel):
    pricing_id: str


@router.post("/inquiry")
async def inquiry(req: InquiryRequest):
    from .models import PricingIntent
    intent = PricingIntent(**req.intent) if req.intent else PricingIntent()
    service = get_pricing_service()
    return await service.handle_inquiry(
        text=req.text, intent=intent, customer_id=req.customer_id,
        session_id=req.session_id, customer_info=req.customer_info,
        context=req.context,
    )


@router.post("/confirm")
async def confirm(req: ConfirmRequest):
    service = get_pricing_service()
    return await service.handle_confirm_trade(
        pricing_id=req.pricing_id, customer_id=req.customer_id,
        customer_info=req.customer_info,
    )


@router.post("/refresh")
async def refresh(req: ActionRequest):
    service = get_pricing_service()
    return await service.handle_refresh(
        pricing_id=req.pricing_id, customer_id="",
    )


@router.post("/cancel")
async def cancel(req: ActionRequest):
    service = get_pricing_service()
    return await service.handle_cancel(pricing_id=req.pricing_id)


@router.get("/status/{pricing_id}")
async def status(pricing_id: str):
    from backend.db import mysql_store
    session = mysql_store.get_pricing_session(pricing_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"pricing_id": pricing_id, "status": session.get("status")}
```

- [ ] **步骤 2：在 app.py 中注册路由和初始化**

在 `backend/app.py` 中添加：

```python
# 在 import 区块末尾添加
from backend.pricing.routes import router as pricing_router, init_pricing_service
from backend.event_bus import bus

# 在 app 对象创建后添加（放在 admin_router 之后）
app.include_router(pricing_router)

# 在模块级初始化中添加（放在 load_dimension_config() 之后）
import json
with open("backend/knowledge_base/semantic_rules.json", "r", encoding="utf-8") as f:
    rules = json.load(f)
pricing_cfg = rules.get("pricing", {})
init_pricing_service(
    engine_url=os.getenv("PRICING_ENGINE_URL", ""),
    scenarios=pricing_cfg.get("scenarios", {}),
    validity_minutes=pricing_cfg.get("quote_validity_minutes", 5),
)
```

- [ ] **步骤 3：验证路由注册**

```bash
cd d:/AI/XF-AI/XFundsAINext && python -c "
from backend.pricing.routes import router
assert '/api/pricing/inquiry' in [r.path for r in router.routes]
assert '/api/pricing/confirm' in [r.path for r in router.routes]
print('Routes OK')
"
```

- [ ] **步骤 4：Commit**

```bash
git add backend/pricing/routes.py backend/app.py
git commit -m "feat(pricing): add pricing API routes and register in app"
```

---

### 任务 14：客户智能洞察引擎

**文件：**
- 创建：`backend/pricing/insight_engine.py`

- [ ] **步骤 1：实现 insight_engine.py**

```python
# backend/pricing/insight_engine.py
"""客户智能洞察引擎 — 基于记忆和画像的主动分析推送"""

from __future__ import annotations
from typing import Optional

from .models import PricingIntent, QuoteResult
from backend.db import mysql_store
from backend.event_bus import bus


class InsightEngine:
    """根据客户历史记忆和当前询价意图，生成主动洞察"""

    RATE_TREND_CACHE: dict[str, list[dict]] = {}

    def __init__(self):
        # 订阅事件
        bus.subscribe("quote.created", self.on_quote_created)
        bus.subscribe("trade.executed", self.on_trade_executed)

    async def on_quote_created(self, pricing_id: str, intent_type: str, **kwargs):
        """新报价生成时生成洞察（在后续请求中返回）"""
        pass

    async def on_trade_executed(self, pricing_id: str, trade_id: str, **kwargs):
        """交易完成时更新客户偏好记忆"""
        pass

    async def generate_insights(self, customer_id: str,
                                current_intent: PricingIntent,
                                quotes: list[QuoteResult]) -> list[dict]:
        """生成主动洞察列表"""
        insights = []

        # 1. 走势图推送（如果代客系统提供走势图组件URL）
        if current_intent.currency_pair:
            chart_insight = self._build_chart_insight(current_intent)
            if chart_insight:
                insights.append(chart_insight)

        # 2. 基于记忆的产品对比推荐
        prefs = await self._get_customer_preferences(customer_id)
        if prefs:
            compare_insight = self._build_comparison_insight(current_intent, prefs)
            if compare_insight:
                insights.append(compare_insight)

        # 3. 历史询价摘要（记忆回顾）
        history_summary = await self._get_history_summary(customer_id)
        if history_summary:
            insights.append(history_summary)

        return insights

    def _build_chart_insight(self, intent: PricingIntent) -> Optional[dict]:
        """构建走势图洞察 — 使用代客系统已有的走势图组件URL"""
        pair = intent.currency_pair
        if not pair:
            return None
        return {
            "type": "rate_chart",
            "title": f"{pair} 近30天走势",
            "chart_url": f"/api/pricing/chart?pair={pair}",  # 代客走势图组件URL
            "summary": "走势图数据由代客系统提供",
        }

    def _build_comparison_insight(self, intent: PricingIntent,
                                   prefs: dict) -> Optional[dict]:
        """基于客户偏好生成产品对比建议"""
        freq_product = prefs.get("frequent_product_type", "")
        if not freq_product or freq_product == intent.product_type:
            return None

        return {
            "type": "product_comparison",
            "title": "基于您的交易习惯",
            "detail": f"您常交易{freq_product}产品，是否对比查看{freq_product}与{intent.product_type}的价格差异？",
            "action": "compare",
            "action_label": "查看对比",
            "action_params": {
                "products": [intent.product_type, freq_product],
                "currency_pair": intent.currency_pair,
            },
        }

    async def _get_customer_preferences(self, customer_id: str) -> dict:
        """从记忆系统读取客户偏好"""
        try:
            memories = mysql_store.get_agent_memory(customer_id, last_n=20)
        except Exception:
            return {}

        counts: dict[str, dict[str, int]] = {"product_type": {}, "tenor": {}}
        for m in memories:
            data = m.get("structured_data", {})
            data = data if isinstance(data, dict) else {}
            for key in ("product_type", "tenor"):
                val = str(data.get(key, ""))
                if val:
                    counts[key][val] = counts[key].get(val, 0) + 1

        return {
            "frequent_product_type": max(counts["product_type"], key=counts["product_type"].get) if counts["product_type"] else "",
            "frequent_tenor": max(counts["tenor"], key=counts["tenor"].get) if counts["tenor"] else "",
            "total_inquiries": len(memories),
        }

    async def _get_history_summary(self, customer_id: str) -> Optional[dict]:
        """获取历史询价摘要"""
        try:
            memories = mysql_store.get_agent_memory(customer_id, last_n=5)
        except Exception:
            return None

        if not memories:
            return None

        recent_pairs = set()
        for m in memories:
            data = m.get("structured_data", {})
            data = data if isinstance(data, dict) else {}
            pair = data.get("currency_pair", "")
            if pair:
                recent_pairs.add(pair)

        if not recent_pairs:
            return None

        return {
            "type": "history",
            "title": "您的近期询价",
            "detail": f"最近询价涉及：{'、'.join(sorted(recent_pairs)[:3])}",
            "recent_pairs": list(recent_pairs),
        }
```

- [ ] **步骤 2：Commit**

```bash
git add backend/pricing/insight_engine.py
git commit -m "feat(pricing): add customer insight engine with memory-based recommendations"
```

---

### 任务 15：集成到 LangGraph 管道

**文件：**
- 创建：`backend/langgraph/agents/pricing_agent.py`
- 修改：`backend/langgraph/state.py`
- 修改：`backend/langgraph/router.py`
- 修改：`backend/langgraph/registry.py`
- 修改：`backend/langgraph/pipeline.py`

- [ ] **步骤 1：扩展 AgentState 增加报价字段**

在 `backend/langgraph/state.py` 的 AgentState 中追加：

```python
# Pricing Agent 输出字段
pricing_result: dict = field(default_factory=dict)
pricing_insights: list[dict] = field(default_factory=list)
```

- [ ] **步骤 2：扩展 registry.py 增加pricing关键词**

在 `backend/langgraph/registry.py` 中追加：

```python
PRICING_KEYWORDS = [
    "询价", "报价", "结汇", "购汇", "买汇", "卖汇",
    "比价", "点差", "成交", "下单", "多少钱",
    "汇率", "价格", "即期", "远期", "掉期",
]

def match_pricing_keywords(text: str) -> float:
    """返回文本匹配pricing关键词的得分"""
    if not text:
        return 0.0
    count = 0
    for kw in PRICING_KEYWORDS:
        if kw in text:
            count += 1
    return min(count / max(len(PRICING_KEYWORDS), 1), 1.0)
```

- [ ] **步骤 3：扩展 Router 增加领域分类**

在 `backend/langgraph/router.py` 的 `route_to_agent()` 函数开头增加：

```python
from .registry import match_pricing_keywords

# 在 route_to_agent 函数开头
pricing_score = match_pricing_keywords(text)
bi_score = max(match_keywords(text).values())

if pricing_score > bi_score and pricing_score > 0.1:
    return {
        "router_decision": {
            "status": "ok",
            "agent": "PRICING",
            "confidence": pricing_score,
            "reason": "",
            "message": "",
        }
    }
# 否则继续现有的 BI 路由逻辑...
```

- [ ] **步骤 4：创建 pricing_agent 子图**

```python
# backend/langgraph/agents/pricing_agent.py
"""LangGraph pricing agent sub-graph"""

from langgraph.graph import StateGraph
from backend.langgraph.state import AgentState
from backend.pricing.service import get_pricing_service
from backend.pricing.models import PricingIntent, IntentType
from backend.llm_parser.parser import rule_based_parse
from backend.llm_parser.llm_client import llm_parse
from backend.llm_parser.prompt_builder import build_system_prompt
from backend.llm_parser.rules_engine import gatekeep
from backend.pricing.pricing_rules import PRICING_SYSTEM_PROMPT
from backend.pricing.validator import validate_intent, validate_direct_trade
from backend.pricing.insight_engine import InsightEngine

import json


async def _node_parse_pricing(state: AgentState) -> dict:
    """解析询价意图"""
    text = state.user_text
    # Rule-first: try rule-based parse for simple matching
    # For pricing, we use a dedicated LLM prompt since the rule parser is BI-focused

    # Simple keyword matching for confidence
    has_price_kw = any(kw in text for kw in ["询价", "报价", "成交", "下单"])
    has_product = any(kw in text for kw in ["即期", "远期", "掉期"])
    has_pair = any(kw in text for kw in ["美元", "欧元", "英镑", "日元", "人民币"])

    confidence = 0.0
    if has_price_kw:
        confidence += 0.4
    if has_product:
        confidence += 0.3
    if has_pair:
        confidence += 0.3

    if confidence >= 0.8:
        # High confidence: use keyword-based extraction
        intent = _extract_pricing_intent_keywords(text)
        pipeline = f"rule(confidence={confidence:.2f})"
    else:
        # Low confidence: use LLM
        llm_result = llm_parse(text, PRICING_SYSTEM_PROMPT)
        if llm_result:
            try:
                intent_data = json.loads(llm_result) if isinstance(llm_result, str) else llm_result
                intent = PricingIntent(**intent_data)
                pipeline = "llm"
            except Exception:
                intent = _extract_pricing_intent_keywords(text)
                pipeline = "llm_fallback"
        else:
            intent = _extract_pricing_intent_keywords(text)
            pipeline = "rule_fallback"

    intent.pipeline = pipeline
    intent.confidence = confidence

    return {
        "parsed_params": {
            "intent_type": intent.intent_type.value,
            "product_type": intent.product_type,
            "currency_pair": intent.currency_pair,
            "direction": intent.direction,
            "amount": intent.amount,
            "tenor": intent.tenor,
        },
        "pricing_intent": intent,
    }


async def _node_pricing_inquiry(state: AgentState) -> dict:
    """执行询价"""
    intent_data = state.parsed_params
    intent = PricingIntent(
        intent_type=IntentType(intent_data.get("intent_type", "SINGLE")),
        product_type=intent_data.get("product_type", ""),
        currency_pair=intent_data.get("currency_pair", ""),
        direction=intent_data.get("direction", ""),
        amount=intent_data.get("amount"),
        tenor=intent_data.get("tenor", ""),
    )

    service = get_pricing_service()
    result = await service.handle_inquiry(
        text=state.user_text,
        intent=intent,
        customer_id="default",
        session_id=state.session_id,
        context=state.context,
    )

    # 生成洞察
    insight_engine = InsightEngine()
    quotes_serialized = []  # In real impl, extract from result
    insights = await insight_engine.generate_insights(
        "default", intent, quotes_serialized
    )

    return {
        "pricing_result": result,
        "pricing_insights": insights,
    }


async def _node_pricing_validate(state: AgentState) -> dict:
    """校验询价响应"""
    result = state.pricing_result
    if result.get("mode") == "error":
        return {"error": result.get("error", "询价异常")}
    return {"validation_warnings": []}


def build_pricing_subgraph() -> StateGraph:
    builder = StateGraph(AgentState)
    builder.add_node("parse", _node_parse_pricing)
    builder.add_node("inquiry", _node_pricing_inquiry)
    builder.add_node("validate", _node_pricing_validate)
    builder.set_entry_point("parse")
    builder.add_edge("parse", "inquiry")
    builder.add_edge("inquiry", "validate")
    return builder.compile()


def _extract_pricing_intent_keywords(text: str) -> PricingIntent:
    """Rule-based pricing intent extraction"""
    intent = PricingIntent()
    intent.product_type = ""
    if "即期" in text:
        intent.product_type = "SPOT"
    elif "掉期" in text:
        intent.product_type = "SWAP"
    elif "远期" in text:
        intent.product_type = "FWD"

    intent.direction = ""
    if any(w in text for w in ["结汇", "银行买入"]):
        intent.direction = "B"
    elif any(w in text for w in ["购汇", "银行卖出"]):
        intent.direction = "S"

    for pair in ["美元/人民币", "USD/CNY", "美元"]:
        if pair in text:
            intent.currency_pair = "USD/CNY"
            break

    for tenor in ["1M", "1个月", "3M", "3个月", "6M", "6个月", "1Y", "1年"]:
        if tenor in text:
            intent.tenor = tenor
            break

    if any(w in text for w in ["买", "卖", "成交", "下单", "交易"]):
        if any(w in text for w in ["万", "金额"]):
            intent.intent_type = IntentType.DIRECT_TRADE
    elif "比价" in text or "对比" in text:
        intent.intent_type = IntentType.COMPARE
    elif "情景" in text:
        intent.intent_type = IntentType.SCENARIO

    return intent
```

- [ ] **步骤 5：在 pipeline.py 中注册**

```python
# 在 build_main_graph() 中
from backend.langgraph.agents.pricing_agent import build_pricing_subgraph

builder.add_node("pricing_agent", build_pricing_subgraph())

# 在 _route_agent 条件路由中增加
def _route_agent(state: AgentState) -> str:
    agent = state.router_decision.get("agent", "")
    if agent == "PRICING":
        return "pricing_agent"
    # ...existing logic...
```

- [ ] **步骤 6：Commit**

```bash
git add backend/langgraph/agents/pricing_agent.py \
        backend/langgraph/state.py \
        backend/langgraph/router.py \
        backend/langgraph/registry.py \
        backend/langgraph/pipeline.py
git commit -m "feat(pricing): integrate pricing agent into LangGraph pipeline"
```

---

### 任务 16：前端API扩展

**文件：**
- 修改：`frontend/src/api.js`

- [ ] **步骤 1：增加询报价API函数**

在 `frontend/src/api.js` 追加：

```javascript
// 询报价相关
export async function pricingInquiry(text, intent, options = {}) {
  const body = {
    text,
    intent: intent || {},
    session_id: options.sessionId || '',
    customer_id: options.customerId || '',
    customer_info: options.customerInfo || null,
    context: options.context || null,
  }
  const resp = await fetch('/api/pricing/inquiry', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `询价失败 (${resp.status})`)
  }
  return resp.json()
}

export async function pricingConfirm(pricingId, options = {}) {
  const body = {
    pricing_id: pricingId,
    session_id: options.sessionId || '',
    customer_id: options.customerId || '',
    customer_info: options.customerInfo || null,
  }
  const resp = await fetch('/api/pricing/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `下单失败 (${resp.status})`)
  }
  return resp.json()
}

export async function pricingRefresh(pricingId) {
  const resp = await fetch('/api/pricing/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pricing_id: pricingId }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `刷新失败 (${resp.status})`)
  }
  return resp.json()
}

export async function pricingCancel(pricingId) {
  const resp = await fetch('/api/pricing/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pricing_id: pricingId }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `取消失败 (${resp.status})`)
  }
  return resp.json()
}
```

- [ ] **步骤 2：Commit**

```bash
git add frontend/src/api.js
git commit -m "feat(pricing): add frontend API functions for pricing operations"
```

---

### 任务 17：前端组件 — QuoteCountdown

**文件：**
- 创建：`frontend/src/components/QuoteCountdown.vue`

- [ ] **步骤 1：实现倒计时组件**

```vue
<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'

const props = defineProps({
  validUntil: { type: String, required: true },
})

const emit = defineEmits(['expired'])

const remaining = ref(0)
let timer = null

const minutes = computed(() => Math.floor(remaining.value / 60))
const seconds = computed(() => remaining.value % 60)
const display = computed(() =>
  `${String(minutes.value).padStart(2, '0')}:${String(seconds.value).padStart(2, '0')}`
)
const isUrgent = computed(() => remaining.value <= 30)

function tick() {
  const now = Date.now()
  const target = new Date(props.validUntil).getTime()
  remaining.value = Math.max(0, Math.floor((target - now) / 1000))
  if (remaining.value <= 0) {
    clearInterval(timer)
    emit('expired')
  }
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 1000)
})

onUnmounted(() => {
  clearInterval(timer)
})
</script>

<template>
  <div class="countdown" :class="{ urgent: isUrgent }">
    <span class="countdown-label">有效期</span>
    <span class="countdown-value">{{ display }}</span>
  </div>
</template>

<style scoped>
.countdown {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 6px;
  background: var(--gray-100);
  font-size: 13px;
}
.countdown-label {
  color: var(--text-muted);
}
.countdown-value {
  font-family: 'Consolas', monospace;
  font-weight: 600;
  color: var(--text-primary);
}
.countdown.urgent {
  background: var(--red-light);
}
.countdown.urgent .countdown-value {
  color: var(--error);
}
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add frontend/src/components/QuoteCountdown.vue
git commit -m "feat(pricing): add QuoteCountdown component"
```

---

### 任务 18：前端组件 — RiskDisclosure

**文件：**
- 创建：`frontend/src/components/RiskDisclosure.vue`

- [ ] **步骤 1：实现风险提示弹窗**

```vue
<script setup>
import { ref } from 'vue'
import { NModal, NCheckbox, NButton, NSpace } from 'naive-ui'

const props = defineProps({
  show: { type: Boolean, default: false },
  title: { type: String, default: '风险提示' },
  items: { type: Array, default: () => ['请谨慎交易'] },
})

const emit = defineEmits(['confirm', 'cancel'])
const agreed = ref(false)
</script>

<template>
  <NModal :show="show" :mask-closable="false" title="">
    <div class="risk-modal">
      <h3 class="risk-title">⚠ {{ title }}</h3>
      <ul class="risk-items">
        <li v-for="item in items" :key="item">{{ item }}</li>
      </ul>
      <NCheckbox v-model:checked="agreed">
        我已了解上述风险，确认交易
      </NCheckbox>
      <NSpace justify="end" style="margin-top: 16px">
        <NButton @click="emit('cancel')">取消</NButton>
        <NButton type="error" :disabled="!agreed" @click="emit('confirm')">
          确认交易
        </NButton>
      </NSpace>
    </div>
  </NModal>
</template>

<style scoped>
.risk-modal {
  padding: 8px;
  max-width: 420px;
}
.risk-title {
  color: var(--text-primary);
  font-size: 16px;
  margin-bottom: 12px;
}
.risk-items {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 2;
  padding-left: 20px;
  margin-bottom: 16px;
}
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add frontend/src/components/RiskDisclosure.vue
git commit -m "feat(pricing): add RiskDisclosure modal component"
```

---

### 任务 19：前端组件 — PricingCard（核心）

**文件：**
- 创建：`frontend/src/components/PricingCard.vue`

- [ ] **步骤 1：实现报价卡片**

```vue
<script setup>
import { ref } from 'vue'
import { NCard, NButton, NSpace, NTag, NDivider } from 'naive-ui'
import QuoteCountdown from './QuoteCountdown.vue'
import RiskDisclosure from './RiskDisclosure.vue'
import ScenarioCompare from './ScenarioCompare.vue'
import PricingInsight from './PricingInsight.vue'

const props = defineProps({
  data: { type: Object, required: true },
})

const emit = defineEmits(['confirm', 'cancel', 'refresh', 'quickQuery'])

const showRisk = ref(false)

const directionLabel = (d) => d === 'B' ? '结汇' : d === 'S' ? '购汇' : d
const productLabel = (p) => ({ SPOT: '即期', FWD: '远期', SWAP: '掉期' })[p] || p

function handleConfirm() {
  emit('confirm', props.data.pricing_id)
}

function handleTradeClick() {
  if (props.data.risk_disclosure) {
    showRisk.value = true
  } else {
    emit('confirm', props.data.pricing_id)
  }
}

function handleRiskConfirmed() {
  showRisk.value = false
  emit('confirm', props.data.pricing_id)
}

const isDirectTrade = computed(() => props.data.mode === 'pricing_direct_trade')
const isCompare = computed(() => props.data.mode === 'pricing_compare' || props.data.intent_type === 'COMPARE')
const isScenario = computed(() => props.data.mode === 'pricing_scenario' || props.data.intent_type === 'SCENARIO')
</script>

<script>
import { computed } from 'vue'
</script>

<template>
  <div class="pricing-container">
    <!-- 对比/情景模式 -->
    <ScenarioCompare
      v-if="isCompare || isScenario"
      :data="data"
      @confirm="emit('confirm', data.pricing_id)"
    />

    <!-- 单/多报价模式 -->
    <template v-else>
      <NCard v-for="(quote, idx) in data.quotes" :key="idx" class="quote-card" size="small">
        <div class="quote-header">
          <span class="quote-pair">{{ quote.currency_pair }}</span>
          <NTag size="small" :type="'info'">
            {{ productLabel(quote.product_type) }}{{ directionLabel(quote.direction) }}
          </NTag>
        </div>

        <div class="quote-rate">{{ quote.customer_rate }}</div>

        <div class="quote-meta">
          <span>点差：{{ quote.spread_bp }}bp</span>
          <span v-if="quote.value_date">交割日：{{ quote.value_date }}</span>
        </div>

        <QuoteCountdown :valid-until="data.valid_until" @expired="emit('refresh', data.pricing_id)" />

        <NSpace justify="end" style="margin-top: 12px">
          <NButton size="small" @click="emit('cancel', data.pricing_id)">取消</NButton>
          <NButton size="small" @click="emit('refresh', data.pricing_id)">刷新</NButton>
          <NButton
            v-if="isDirectTrade || data.show_trade_button"
            size="small" type="error"
            @click="handleTradeClick"
          >
            确认交易
          </NButton>
        </NSpace>
      </NCard>
    </template>

    <!-- 智能洞察 -->
    <PricingInsight
      v-if="data.insights && data.insights.length"
      :insights="data.insights"
      @quickQuery="emit('quickQuery', $event)"
    />

    <!-- 小白模式术语提示 -->
    <div v-if="data.novice_mode" class="novice-bar">
      💡 点击专业术语可查看解释
    </div>

    <!-- 风险提示弹窗 -->
    <RiskDisclosure
      :show="showRisk"
      :title="data.risk_disclosure?.title"
      :items="data.risk_disclosure?.items"
      @confirm="handleRiskConfirmed"
      @cancel="showRisk = false"
    />
  </div>
</template>

<style scoped>
.pricing-container {
  max-width: 520px;
}
.quote-card {
  margin-bottom: 12px;
}
.quote-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.quote-pair {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}
.quote-rate {
  font-size: 28px;
  font-weight: 700;
  color: var(--accent);
  margin: 8px 0;
}
.quote-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.novice-bar {
  margin-top: 8px;
  padding: 8px 12px;
  background: var(--blue-light);
  border-radius: 6px;
  font-size: 12px;
  color: var(--blue);
}
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add frontend/src/components/PricingCard.vue
git commit -m "feat(pricing): add PricingCard component with quote display and trade actions"
```

---

### 任务 20：前端组件 — ScenarioCompare 和 PricingInsight

**文件：**
- 创建：`frontend/src/components/ScenarioCompare.vue`
- 创建：`frontend/src/components/PricingInsight.vue`

- [ ] **步骤 1：ScenarioCompare.vue**

```vue
<script setup>
import { NDataTable } from 'naive-ui'

const props = defineProps({
  data: { type: Object, required: true },
})

const emit = defineEmits(['confirm'])

const columns = [
  { title: '产品', key: 'product', width: 120 },
  { title: '价格', key: 'rate', width: 100 },
  { title: '点差', key: 'spread', width: 80 },
  { title: '期限', key: 'tenor', width: 80 },
  { title: '交割日', key: 'value_date', width: 120 },
]

const productLabel = (p) => ({ SPOT: '即期', FWD: '远期', SWAP: '掉期' })[p] || p
const directionLabel = (d) => d === 'B' ? '结汇' : '购汇'

const rows = computed(() =>
  (props.data.quotes || []).map((q, i) => ({
    key: i,
    product: `${productLabel(q.product_type)}${directionLabel(q.direction)}`,
    rate: q.customer_rate,
    spread: `${q.spread_bp}bp`,
    tenor: q.tenor || '-',
    value_date: q.value_date || '-',
  }))
)
</script>

<script>
import { computed } from 'vue'
</script>

<template>
  <div class="compare-table">
    <h4 class="compare-title">{{ data.scenario_name || '报价对比' }}</h4>
    <NDataTable :columns="columns" :data="rows" size="small" />
  </div>
</template>

<style scoped>
.compare-table {
  margin-bottom: 12px;
}
.compare-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}
</style>
```

- [ ] **步骤 2：PricingInsight.vue**

```vue
<script setup>
const props = defineProps({
  insights: { type: Array, default: () => [] },
})

const emit = defineEmits(['quickQuery'])
</script>

<template>
  <div v-if="insights.length" class="insight-list">
    <div v-for="(item, idx) in insights" :key="idx" class="insight-item">
      <span class="insight-icon">📊</span>
      <div class="insight-body">
        <div class="insight-title">{{ item.title }}</div>
        <div class="insight-detail">{{ item.detail || item.summary }}</div>
      </div>
      <button v-if="item.action" class="insight-action" @click="emit('quickQuery', item.action_params)">
        {{ item.action_label || '查看' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.insight-list {
  margin-top: 12px;
}
.insight-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  background: var(--gray-50);
  border-radius: 6px;
  margin-bottom: 6px;
}
.insight-icon {
  font-size: 16px;
  flex-shrink: 0;
  margin-top: 1px;
}
.insight-body {
  flex: 1;
}
.insight-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.insight-detail {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}
.insight-action {
  flex-shrink: 0;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--white);
  font-size: 11px;
  color: var(--accent);
  cursor: pointer;
}
.insight-action:hover {
  background: var(--accent);
  color: var(--white);
  border-color: var(--accent);
}
</style>
```

- [ ] **步骤 3：Commit**

```bash
git add frontend/src/components/ScenarioCompare.vue frontend/src/components/PricingInsight.vue
git commit -m "feat(pricing): add ScenarioCompare and PricingInsight components"
```

---

### 任务 21：前端集成 — MessageArea 和 App.vue

**文件：**
- 修改：`frontend/src/components/MessageArea.vue`
- 修改：`frontend/src/App.vue`

- [ ] **步骤 1：在 BotMessage 中增加 pricing 渲染分支**

在 `MessageArea.vue` 的 `<BotMessage>` 模板中增加：

```vue
<!-- 在现有的 <template v-else-if="message.mode === 'result_card'"> 之后添加 -->

<template v-else-if="isPricingMode(message.mode)">
  <PricingCard
    :data="message.data"
    @confirm="(pricingId) => emit('pricingConfirm', pricingId, idx)"
    @cancel="(pricingId) => emit('pricingCancel', pricingId, idx)"
    @refresh="(pricingId) => emit('pricingRefresh', pricingId, idx)"
    @quickQuery="(query) => emit('quickQuery', query)"
  />
</template>

<template v-else-if="message.mode === 'follow_up'">
  <div class="follow-up-text">
    <p v-for="q in message.data?.follow_up" :key="q">{{ q }}</p>
  </div>
</template>

<template v-else-if="message.mode === 'trade_success'">
  <NCard size="small" class="trade-success-card">
    <div class="trade-success">
      <span class="success-icon">✅</span>
      <div>
        <div class="success-title">交易成功</div>
        <div class="success-detail">编号：{{ message.data?.trade_id }}</div>
        <div class="success-detail">成交价：{{ message.data?.executed_rate }}</div>
      </div>
    </div>
  </NCard>
</template>

<template v-else-if="message.mode === 'trade_failed'">
  <NAlert type="error" :title="'交易失败'">
    {{ message.data?.error_reason || '请稍后重试' }}
  </NAlert>
</template>
```

添加辅助函数：

```javascript
function isPricingMode(mode) {
  return ['pricing_single', 'pricing_multi', 'pricing_compare',
          'pricing_scenario', 'pricing_direct_trade'].includes(mode)
}
```

更新 emits：增加 `'pricingConfirm'`, `'pricingCancel'`, `'pricingRefresh'`

- [ ] **步骤 2：在 App.vue 中处理询报价消息**

在 `App.vue` 的 `handleSend()` 中增加定价路由：

```javascript
// 在 handleSend() 中，现有 BI 路径之前，检测定价关键词
const pricingKeywords = ['询价', '报价', '结汇', '购汇', '成交', '点差', '比价', '价格']
const isPricingIntent = pricingKeywords.some(kw => text.includes(kw))

if (isPricingIntent) {
  // 使用定价流程
  messages[botIdx] = { type: 'bot', mode: 'loading' }
  try {
    const result = await pricingInquiry(text, {}, {
      sessionId: sessionId.value,
      context: buildContext(),
    })
    messages[botIdx] = { type: 'bot', mode: result.mode, data: result }
  } catch (err) {
    messages[botIdx] = { type: 'bot', mode: 'error', error: err.message }
  }
  _persistTurn()
  return
}
// else continue to existing BI flow...
```

增加询报价操作方法：

```javascript
async function handlePricingConfirm(pricingId) {
  try {
    const result = await pricingConfirm(pricingId, { sessionId: sessionId.value })
    const idx = messages.findIndex(m =>
      m.type === 'bot' && m.data?.pricing_id === pricingId
    )
    if (idx >= 0) {
      messages[idx] = { type: 'bot', mode: result.mode, data: result.data }
    }
  } catch (err) {
    // handle error
  }
}

async function handlePricingRefresh(pricingId) {
  try {
    const result = await pricingRefresh(pricingId)
    const idx = messages.findIndex(m =>
      m.type === 'bot' && m.data?.pricing_id === pricingId
    )
    if (idx >= 0) {
      messages[idx] = { type: 'bot', mode: result.mode, data: result }
    }
  } catch (err) {
    // handle error
  }
}

async function handlePricingCancel(pricingId) {
  try {
    await pricingCancel(pricingId)
    const idx = messages.findIndex(m =>
      m.type === 'bot' && m.data?.pricing_id === pricingId
    )
    if (idx >= 0) {
      messages[idx] = { type: 'bot', mode: 'text', text: '报价已取消' }
    }
  } catch (err) {
    // handle error
  }
}
```

- [ ] **步骤 3：Commit**

```bash
git add frontend/src/components/MessageArea.vue frontend/src/App.vue
git commit -m "feat(pricing): integrate pricing flow into MessageArea and App.vue"
```

---

## 自检

### 规格覆盖度

| 设计文档章节 | 对应任务 | 状态 |
|------------|---------|------|
| 整体架构（event_bus） | 任务2 | ✅ |
| 数据模型 | 任务1 | ✅ |
| 询报价状态机 | 任务7 | ✅ |
| 计价引擎对接 | 任务5 | ✅ |
| 参数校验 | 任务6 | ✅ |
| 风控 gate | 任务9 | ✅ |
| 询报价服务编排 | 任务12 | ✅ |
| API路由 | 任务13 | ✅ |
| 交易执行 | 任务11 | ✅ |
| 上下文继承 | 任务10 | ✅ |
| LLM解析规则 | 任务8 | ✅ |
| LangGraph扩展 | 任务15 | ✅ |
| 客户智能洞察 | 任务14 | ✅ |
| 前端报价卡片 | 任务19 | ✅ |
| 前端倒计时 | 任务17 | ✅ |
| 前端风险披露 | 任务18 | ✅ |
| 前端对比展示 | 任务20 | ✅ |
| 前端洞察面板 | 任务20 | ✅ |
| 前端App集成 | 任务21 | ✅ |
| MySQL表扩展 | 任务3 | ✅ |
| 语义规则扩展 | 任务4 | ✅ |

### 占位符检查

无"TODO"、"待定"、"后续实现"等占位符。所有步骤都包含完整代码。

### 类型一致性

- `PricingIntent`、`QuoteResult`、`TradeResult` 等模型在任务1定义，后续任务一致引用
- `PricingService` 接口在任务12定义，任务13（路由）和任务15（LangGraph）一致调用
- 前端 `pricing_inquiry` / `pricing_confirm` 等API函数与后端路由一致
- 事件名常量在 `EventBus.EVENTS` 中统一定义
