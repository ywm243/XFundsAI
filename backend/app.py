"""FastAPI application — FX trade query service."""

import json
import logging
import os
import traceback
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

from dotenv import load_dotenv
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE, override=True)

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

from llm_parser.parser import rule_based_parse, compute_comparison_dates, _rule_confidence
from llm_parser.llm_client import llm_parse
from llm_parser.rules_engine import gatekeep, reload_rules
from llm_parser.prompt_builder import build_system_prompt, invalidate_cache
from db.query_builder import TradeQueryBuilder
from db.connection import get_db
from db.mysql_store import init_db, get_conn
from admin_routes import router as admin_router
import uuid
from datetime import datetime

# Initialize store on startup
init_db()

logger = logging.getLogger(__name__)

from mcp.server import create_http_app, get_session_manager
_mcp_asgi = create_http_app()


@asynccontextmanager
async def _mcp_lifespan(app: FastAPI):
    """Run MCP session manager lifecycle."""
    sm = get_session_manager()
    if sm is not None:
        async with sm.run():
            yield
    else:
        yield


app = FastAPI(title="Smart BI", version="1.0.0", lifespan=_mcp_lifespan)
app.include_router(admin_router)
app.mount("/mcp", _mcp_asgi)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _build_comparison_sql(parsed, sql, date_start, date_end):
    """Rebuild the SQL with comparison date range, matching the same query type."""
    buy_sell = parsed.get("buy_sell") or None
    cust_name = parsed.get("cust_name") or None
    special_states = parsed.get("special_states")
    if isinstance(special_states, str) and special_states:
        special_states = [s.strip() for s in special_states.split(",")]
    else:
        special_states = None

    amount_filter = parsed.get("amount_filter")
    top_n = parsed.get("top_n")
    comparison = parsed.get("comparison")  # yoy or mom

    if amount_filter:
        return TradeQueryBuilder.build_filtered_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=parsed["bank_name"] or None,
            amount_op=amount_filter["amount_op"],
            amount_value=amount_filter["amount_value"],
            hedge_ratio=parsed.get("hedge_ratio", False),
            dimension=parsed.get("dimension", "bank"),
            cust_name=cust_name, appid=parsed.get("appid"),
        )
    elif top_n and top_n > 0:
        return TradeQueryBuilder.build_ranking_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=parsed["bank_name"] or None, top_n=top_n,
            dimension=parsed.get("dimension", "bank"),
            hedge_ratio=parsed.get("hedge_ratio", False),
            cust_name=cust_name, appid=parsed.get("appid"),
        )
    elif parsed.get("hedge_ratio"):
        return TradeQueryBuilder.build_hedge_ratio_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=parsed["bank_name"] or None,
            dimension=parsed.get("dimension", "bank"),
            cust_name=cust_name, appid=parsed.get("appid"),
        )
    elif parsed.get("aggregate"):
        return TradeQueryBuilder.build_aggregate_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=parsed["bank_name"] or None,
            cust_name=cust_name, appid=parsed.get("appid"),
            dimension=parsed.get("dimension"),
        )
    else:
        return TradeQueryBuilder.build_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=parsed["bank_name"] or None,
            cust_name=cust_name, appid=parsed.get("appid"),
        )


def _compute_comparison(current_rows, compare_rows, comparison, date_start, date_end, cmp_start, cmp_end):
    """Compute change_amount and change_rate from current and comparison rows.

    For aggregate queries: compares TOTAL_AMOUNT (column index 1) and TRADE_COUNT (column index 2).
    For ranking/detail queries: sums TOTAL_AMOUNT across all rows.
    """
    if not current_rows or not compare_rows:
        return None

    # Detect if this is a ranking/detail query (multiple rows) or aggregate (single row)
    current_row = current_rows[0]
    compare_row = compare_rows[0]

    # TOTAL_AMOUNT is typically the second column (index 1), first is the dimension label
    try:
        if len(current_row) >= 2:
            amt_idx = 1  # TOTAL_AMOUNT
            current_amt = float(current_row[amt_idx]) if current_row[amt_idx] is not None else 0
            compare_amt = float(compare_row[amt_idx]) if compare_row[amt_idx] is not None else 0
        else:
            current_amt = float(current_row[0]) if current_row[0] is not None else 0
            compare_amt = float(compare_row[0]) if compare_row[0] is not None else 0
    except (ValueError, IndexError, TypeError):
        return None

    change_amount = current_amt - compare_amt
    if compare_amt != 0:
        change_rate = round(abs(change_amount / compare_amt) * 100, 2)
    else:
        change_rate = None

    label_map = {"yoy": "同比", "mom": "环比"}
    return {
        "type": comparison,
        "label": label_map.get(comparison, comparison),
        "current_period": f"{date_start} ~ {date_end}",
        "compare_period": f"{cmp_start} ~ {cmp_end}",
        "current_amount": round(current_amt, 2),
        "compare_amount": round(compare_amt, 2),
        "change_amount": round(change_amount, 2),
        "change_rate": change_rate,
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---- Session / History API ----

def _utcnow() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.get("/api/sessions")
def list_sessions():
    """List all sessions with metadata (first query, turn count, etc.)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.id, s.agent_type, s.created_at, s.updated_at,
                       (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id) AS turn_count,
                       (SELECT t.user_query FROM turns t WHERE t.session_id = s.id
                        ORDER BY t.turn_index ASC LIMIT 1) AS first_query
                FROM sessions s
                WHERE s.is_active = 1
                ORDER BY s.updated_at DESC
                LIMIT 50
            """)
            rows = cur.fetchall()
        return [{
            "id": r["id"],
            "agent_type": r["agent_type"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "turn_count": r["turn_count"],
            "first_query": (r["first_query"] or "")[:80],
        } for r in rows]
    finally:
        conn.close()


@app.post("/api/sessions")
def create_new_session():
    """Create a new session, return its ID."""
    session_id = str(uuid.uuid4())[:8]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (id, updated_at) VALUES (%s, %s)",
                (session_id, _utcnow()),
            )
        conn.commit()
    finally:
        conn.close()
    return {"session_id": session_id}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    """Get all turns for a session."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM sessions WHERE id = %s", (session_id,)
            )
            session_row = cur.fetchone()
        if not session_row:
            return JSONResponse(status_code=404, content={"error": "Session not found"})

        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM turns WHERE session_id = %s ORDER BY turn_index ASC",
                (session_id,),
            )
            turns = cur.fetchall()
        return {
            "id": session_row["id"],
            "agent_type": session_row["agent_type"],
            "created_at": session_row["created_at"],
            "updated_at": session_row["updated_at"],
            "turns": [{
                "turn_index": t["turn_index"],
                "user_query": t["user_query"],
                "parsed_params": json.loads(t["parsed_params"]) if t["parsed_params"] else None,
                "executed_sql": t["executed_sql"],
                "result_summary": t["result_summary"],
            } for t in turns],
        }
    finally:
        conn.close()


@app.post("/api/sessions/{session_id}/turns")
async def save_turn(session_id: str, request: Request):
    """Save a conversation turn to the session."""
    body = await request.json()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Ensure session exists
            cur.execute(
                "SELECT 1 FROM sessions WHERE id = %s", (session_id,)
            )
            exists = cur.fetchone()
            if not exists:
                cur.execute(
                    "INSERT INTO sessions (id, updated_at) VALUES (%s, %s)",
                    (session_id, _utcnow()),
                )

            # Get next turn_index
            cur.execute(
                "SELECT COALESCE(MAX(turn_index), -1) FROM turns WHERE session_id = %s",
                (session_id,),
            )
            max_idx = cur.fetchone()[0]

            cur.execute(
                """INSERT INTO turns (session_id, turn_index, user_query,
                   parsed_params, executed_sql, result_summary)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (session_id, max_idx + 1,
                 body.get("user_query", ""),
                 json.dumps(body.get("parsed_params"), ensure_ascii=False) if body.get("parsed_params") else None,
                 body.get("executed_sql"),
                 body.get("result_summary")),
            )
            cur.execute(
                "UPDATE sessions SET updated_at = %s WHERE id = %s",
                (_utcnow(), session_id),
            )
        conn.commit()
        return {"status": "ok", "turn_index": max_idx + 1}
    finally:
        conn.close()


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """Soft-delete a session."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET is_active = 0 WHERE id = %s", (session_id,)
            )
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.post("/api/reload-rules")
def api_reload_rules():
    reload_rules()
    invalidate_cache()
    return {"status": "ok", "message": "Rules and prompt cache refreshed"}


@app.post("/api/parse")
async def api_parse(request: Request):
    """解析自然语言为结构化参数（不执行 SQL）。

    Pipeline: rule_based_parse → confidence check → LLM only if needed.
    Supports multi-turn context.
    """
    body = await request.json()
    text = body.get("text", "")
    context = body.get("context")  # optional conversation history

    try:
        # Step 1: Run rules first (free, <1ms)
        rule_parsed = rule_based_parse(text)
        confidence = _rule_confidence(text, rule_parsed)

        # Step 2: Route based on confidence
        if confidence >= 0.8:
            # High confidence — skip LLM, save API call
            parsed = gatekeep(rule_parsed, text)
            pipeline = f"rule(confidence={confidence:.0%})"
        else:
            # Low confidence — need LLM (with conversation context)
            system_prompt = build_system_prompt(context)
            llm_result = llm_parse(text, system_prompt)
            if llm_result is not None:
                parsed = gatekeep(llm_result, text)
                pipeline = f"llm+gatekeep(rule_confidence={confidence:.0%})"
            else:
                # LLM failed, fallback to rules (still gatekeep)
                parsed = gatekeep(rule_parsed, text)
                pipeline = f"rule_fallback(confidence={confidence:.0%})"

        return {
            "params": parsed,
            "pipeline": pipeline,
            "confidence": confidence,
        }
    except Exception as exc:
        logger.exception("Parse failed: %s", text)
        return JSONResponse(status_code=500, content={
            "error": f"{type(exc).__name__}: {exc}",
        })


@app.post("/api/query")
async def query(request: Request):
    body = await request.json()
    text = body.get("text", "")
    pre_parsed = body.get("params")  # 前端确认卡传来的结构化参数
    context = body.get("context")     # 多轮对话上下文

    sql = None
    parsed = {}

    try:
        if pre_parsed:
            parsed = pre_parsed
            logger.info("Using pre-parsed params from frontend")
        else:
            # 解析方式：规则先行 + 置信度分流
            rule_parsed = rule_based_parse(text)
            confidence = _rule_confidence(text, rule_parsed)
            if confidence >= 0.8:
                parsed = gatekeep(rule_parsed, text)
                logger.info("Rule-only pipeline used (confidence=%.0%%)", confidence)
            else:
                system_prompt = build_system_prompt()
                llm_result = llm_parse(text, system_prompt)
                if llm_result is not None:
                    parsed = gatekeep(llm_result, text)
                    logger.info("LLM+Gatekeep pipeline used (rule_confidence=%.0%%)", confidence)
                else:
                    parsed = gatekeep(rule_parsed, text)
                    logger.info("Rule fallback (LLM failed, confidence=%.0%%)", confidence)

        # ---- 同比/环比缺少日期时从上下文继承 ----
        if parsed.get("comparison") and not (parsed.get("date_start") and parsed.get("date_end")):
            inherited = _inherit_dates_from_context(context)
            if inherited:
                parsed["date_start"] = inherited["date_start"]
                parsed["date_end"] = inherited["date_end"]
                logger.info("Inherited dates from context: %s ~ %s", inherited["date_start"], inherited["date_end"])
            else:
                return {
                    "params": parsed,
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "comparison": None,
                    "summary": "",
                    "chartOption": {},
                    "insights": [],
                    "error": "",
                    "confirm_date": True,
                }

        # Normalize empty values before passing to builder
        buy_sell = parsed["buy_sell"] or None
        cust_name = parsed.get("cust_name") or None
        special_states = parsed["special_states"]
        if isinstance(special_states, str) and special_states:
            special_states = [s.strip() for s in special_states.split(",")]
        else:
            special_states = None

        # Step b: build SQL (amount_filter, ranking, aggregate, or detail)
        amount_filter = parsed.get("amount_filter")
        top_n = parsed.get("top_n")
        if amount_filter:
            sql = TradeQueryBuilder.build_filtered_query(
                product_type=parsed["product_type"],
                date_start=parsed["date_start"] or None,
                date_end=parsed["date_end"] or None,
                special_states=special_states,
                buy_sell=buy_sell,
                bank_name=parsed["bank_name"] or None,
                amount_op=amount_filter["amount_op"],
                amount_value=amount_filter["amount_value"],
                hedge_ratio=parsed.get("hedge_ratio", False),
                dimension=parsed.get("dimension", "bank"),
                cust_name=cust_name,
                appid=parsed.get("appid"),
            )
        elif top_n and top_n > 0:
            sql = TradeQueryBuilder.build_ranking_query(
                product_type=parsed["product_type"],
                date_start=parsed["date_start"] or None,
                date_end=parsed["date_end"] or None,
                special_states=special_states,
                buy_sell=buy_sell,
                bank_name=parsed["bank_name"] or None,
                top_n=top_n,
                dimension=parsed.get("dimension", "bank"),
                hedge_ratio=parsed.get("hedge_ratio", False),
                cust_name=cust_name,
                appid=parsed.get("appid"),
            )
        elif parsed.get("hedge_ratio"):
            sql = TradeQueryBuilder.build_hedge_ratio_query(
                product_type=parsed["product_type"],
                date_start=parsed["date_start"] or None,
                date_end=parsed["date_end"] or None,
                special_states=special_states,
                buy_sell=buy_sell,
                bank_name=parsed["bank_name"] or None,
                dimension=parsed.get("dimension", "bank"),
                cust_name=cust_name,
                appid=parsed.get("appid"),
            )
        elif parsed.get("aggregate"):
            sql = TradeQueryBuilder.build_aggregate_query(
                product_type=parsed["product_type"],
                date_start=parsed["date_start"] or None,
                date_end=parsed["date_end"] or None,
                special_states=special_states,
                buy_sell=buy_sell,
                bank_name=parsed["bank_name"] or None,
                cust_name=cust_name,
                appid=parsed.get("appid"),
                dimension=parsed.get("dimension"),
            )
        else:
            sql = TradeQueryBuilder.build_query(
                product_type=parsed["product_type"],
                date_start=parsed["date_start"] or None,
                date_end=parsed["date_end"] or None,
                special_states=special_states,
                buy_sell=buy_sell,
                bank_name=parsed["bank_name"] or None,
                cust_name=cust_name,
                appid=parsed.get("appid"),
            )

        # Step c: execute
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                cols = [desc[0] for desc in cur.description] if cur.description else []
                rows = [list(row) for row in cur.fetchall()]

        # Step d: comparison (同比/环比)
        comparison = parsed.get("comparison")
        comparison_data = None
        cmp_rows = []
        if comparison and sql and rows:
            cmp_start, cmp_end = compute_comparison_dates(
                parsed["date_start"] or "", parsed["date_end"] or "", comparison
            )
            if cmp_start and cmp_end:
                # Build comparison SQL with shifted dates
                cmp_sql = _build_comparison_sql(
                    parsed=parsed, sql=sql,
                    date_start=cmp_start, date_end=cmp_end,
                )
                try:
                    with get_db() as conn:
                        with conn.cursor() as cur:
                            cur.execute(cmp_sql)
                            cmp_rows = [list(row) for row in cur.fetchall()]
                    if cmp_rows:
                        comparison_data = _compute_comparison(
                            current_rows=rows, compare_rows=cmp_rows,
                            comparison=comparison,
                            date_start=parsed["date_start"] or "",
                            date_end=parsed["date_end"] or "",
                            cmp_start=cmp_start, cmp_end=cmp_end,
                        )
                except Exception as exc:
                    logger.warning("Comparison query failed: %s", exc)

            # Merge per-row comparison data into table columns
            if comparison_data and cmp_rows:
                cmp_label = comparison_data.get("label", "对比")
                cols, rows = _merge_comparison_into_rows(rows, cmp_rows, cols, cmp_label)

    except Exception as exc:
        logger.exception("查询执行失败: %s", text)
        return JSONResponse(status_code=500, content={
            "sql": sql,
            "params": parsed,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        })

    return {
        "sql": sql,
        "params": parsed,
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
        "comparison": comparison_data,
        "summary": _build_summary(parsed, rows, cols, comparison_data),
        "chartOption": _build_chart_option(parsed, rows, cols, comparison_data),
        "insights": _build_insights(parsed, rows, cols, comparison_data),
        "error": "",
    }


# ---- Result enrichment helpers ----

def _inherit_dates_from_context(context: list | None) -> dict | None:
    """Try to inherit date range from the most recent assistant turn in context.

    Returns {date_start, date_end} or None if no dates found.
    """
    if not context:
        return None
    # Walk context in reverse to find the most recent assistant parsed params
    for msg in reversed(context):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            try:
                prev = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            # Dates may be nested inside "params" (API response format)
            prev_data = prev.get("params", prev)
            ds = prev_data.get("date_start", "") or prev.get("date_start", "") or ""
            de = prev_data.get("date_end", "") or prev.get("date_end", "") or ""
            if ds and de:
                return {"date_start": ds, "date_end": de}
    return None


def _build_summary(parsed: dict, rows: list, cols: list, comparison: dict | None) -> str:
    """Generate a natural-language summary from query results."""
    if not rows or not cols:
        return ""

    # Find amount column
    amount_idx = next((i for i, c in enumerate(cols) if c in ("TOTAL_AMOUNT", "USDAMOUNT")), None)
    count_idx = next((i for i, c in enumerate(cols) if c == "TRADE_COUNT"), None)
    label_idx = 0 if len(cols) > 0 else None

    total_amount = sum(float(r[amount_idx] or 0) for r in rows) if amount_idx is not None else 0
    total_count = sum(int(r[count_idx] or 0) for r in rows) if count_idx is not None else 0

    date_start = parsed.get("date_start", "") or ""
    date_end = parsed.get("date_end", "") or ""
    bank_name = parsed.get("bank_name", "") or ""
    cust_name = parsed.get("cust_name", "") or ""

    # Entity name
    entity = bank_name or cust_name or "全市场"
    date_desc = f"{date_start} ~ {date_end}" if date_start else ""

    parts = [f"{date_desc}{entity}"]
    if parsed.get("aggregate"):
        parts.append(f"交易总量{_fmt_amount(total_amount)}万美元")
        if total_count > 0:
            parts.append(f"共{total_count}笔")

    # Top entity
    if len(rows) > 1 and label_idx is not None and amount_idx is not None:
        top_row = max(rows, key=lambda r: float(r[amount_idx] or 0))
        top_label = str(top_row[label_idx]) if top_row[label_idx] else ""
        top_amt = float(top_row[amount_idx] or 0) if top_row[amount_idx] else 0
        if top_label and total_amount > 0:
            pct = round(top_amt / total_amount * 100)
            parts.append(f"{top_label}以{_fmt_amount(top_amt)}万美元占比{pct}%居首")

    if comparison:
        cmp_label = comparison.get("label", "")
        rate = comparison.get("change_rate")
        if rate is not None:
            direction = "增长" if (comparison.get("change_amount") or 0) >= 0 else "下降"
            parts.append(f"{cmp_label}{direction}{rate}%")

    return "，".join(parts) + "。"


def _fmt_amount(val: float) -> str:
    """Format amount in wan (divided by 10000). Always use 万美元, never 亿."""
    v = val / 10000
    return f"{v:,.2f}"


def _build_chart_option(parsed: dict, rows: list, cols: list, comparison: dict | None) -> dict | None:
    """Build a simple ECharts chart option from result data."""
    if not rows or not cols:
        return None

    label_idx = 0 if len(cols) > 0 else None
    amount_idx = next((i for i, c in enumerate(cols) if c in ("TOTAL_AMOUNT", "USDAMOUNT")), None)
    if amount_idx is None:
        return None

    # X-axis labels: use date range for single-row, entity names for multi-row
    date_start = parsed.get("date_start", "") or ""
    date_end = parsed.get("date_end", "") or ""
    if len(rows) == 1 and date_start:
        labels = [f"{date_start}\n~\n{date_end}"]
    else:
        labels = [str(r[label_idx]) if label_idx is not None else f"#{i}" for i, r in enumerate(rows)]
    values = [float(r[amount_idx] or 0) / 10000 for r in rows]  # Convert to wan

    chart_type = "bar"

    option = {
        "_title": _chart_title(parsed),
        "tooltip": {"trigger": "axis", "formatter": "{b}<br/>{a0}: {c0}万美元"},
        "xAxis": {"type": "category", "data": labels, "axisLabel": {"rotate": 0 if len(labels) <= 1 else (30 if len(labels) > 4 else 0)}},
        "yAxis": {"type": "value", "name": "金额（万美元）", "nameTextStyle": {"fontSize": 11}},
        "series": [{
            "name": "当期",
            "type": chart_type,
            "data": values,
            "itemStyle": {"color": "#3b82f6"},
        }],
    }

    # Add comparison series
    if comparison:
        cmp_label = comparison.get("label", "对比")
        cmp_amt = comparison.get("compare_amount", 0) / 10000
        option["series"].append({
            "name": cmp_label,
            "type": chart_type,
            "data": [cmp_amt],
            "itemStyle": {"color": "#22c55e"},
        })

    return option


def _chart_title(parsed: dict) -> str:
    """Generate a chart title from parsed params."""
    parts = []
    if parsed.get("bank_name"):
        parts.append(parsed["bank_name"])
    if parsed.get("cust_name"):
        parts.append(parsed["cust_name"])
    if parsed.get("aggregate"):
        parts.append("交易量统计")
    if parsed.get("hedge_ratio"):
        parts.append("套保率分析")
    if parsed.get("top_n"):
        parts.append(f"TOP{parsed['top_n']}")
    return " ".join(parts) if parts else "数据图表"


def _build_insights(parsed: dict, rows: list, cols: list, comparison: dict | None) -> list[dict]:
    """Generate data insights from query results. Always returns at least 2 if data available."""
    if not rows or not cols:
        return [{"type": "quality", "title": "数据提示",
                 "detail": "查询结果为空，请检查查询条件或确认该时段是否有交易数据。",
                 "query": "本月交易量"}]

    insights = []
    amount_idx = next((i for i, c in enumerate(cols) if c in ("TOTAL_AMOUNT", "USDAMOUNT")), None)
    if amount_idx is None:
        return insights

    label_idx = 0
    total = sum(float(r[amount_idx] or 0) for r in rows)
    count_idx = next((i for i, c in enumerate(cols) if c == "TRADE_COUNT"), None)
    total_count = sum(int(r[count_idx] or 0) for r in rows) if count_idx is not None else 0

    entity = parsed.get("bank_name") or parsed.get("cust_name") or ""

    # Insight 1: Comparison (always shows if comparison exists, otherwise shows overall summary)
    if comparison:
        rate = comparison.get("change_rate")
        direction = "增长" if (comparison.get("change_amount") or 0) >= 0 else "下降"
        cmp_label = comparison.get("label", "对比")
        # Build actionable query: reuse current date range and entity
        entity_query = (entity + " ") if entity else ""
        if rate is not None:
            if abs(rate) > 20:
                insights.append({
                    "type": "growth" if rate > 0 else "risk",
                    "title": f"{cmp_label}显著变化",
                    "detail": f"较对比期{direction}{abs(rate)}%，变化幅度较大。",
                    "query": f"{entity_query}交易量排名",
                })
            else:
                insights.append({
                    "type": "quality",
                    "title": f"{cmp_label}变化",
                    "detail": f"较对比期{direction}{abs(rate)}%。",
                    "query": f"{entity_query}上月交易量{cmp_label}",
                })
    else:
        insights.append({
            "type": "quality",
            "title": "交易概览",
            "detail": f"共计{_fmt_amount(total)}万美元，{total_count}笔交易。",
            "query": f"{entity} 交易量排名" if entity else "本月各机构交易量排名",
        })

    # Insight 2: Top contributor or ranking
    if len(rows) > 1 and total > 0:
        top = max(rows, key=lambda r: float(r[amount_idx] or 0))
        top_label = str(top[label_idx]) if top[label_idx] else ""
        top_amt = float(top[amount_idx] or 0)
        pct = round(top_amt / total * 100)
        if pct >= 30:
            insights.append({
                "type": "risk",
                "title": "集中度提示",
                "detail": f"前三大机构合计占比超50%？{top_label}以{_fmt_amount(top_amt)}万美元占比{pct}%居首。",
                "query": f"{entity} 交易量排名前5" if entity else "各机构交易量排名前5",
            })
        else:
            insights.append({
                "type": "growth",
                "title": "排名分布",
                "detail": f"{top_label}以{_fmt_amount(top_amt)}万美元（{pct}%）居首，分布相对均衡。",
                "query": entity + " 交易量排名前3" if entity else "交易量排名前3",
            })
    else:
        # Single-row result: suggest ranking/detail queries
        insights.append({
            "type": "quality",
            "title": "深入分析",
            "detail": "查看交易量排名，了解各银行/客户的分布情况。",
            "query": entity + " 各银行交易量排名" if entity else "各银行交易量排名",
        })

    # Ensure at least 2 insights
    if len(insights) < 2:
        insights.append({
            "type": "quality",
            "title": "趋势分析",
            "detail": "查看近6个月的趋势变化，了解交易量走势。",
            "query": entity + " 近6个月每月交易量趋势" if entity else "近6个月每月交易量趋势",
        })

    return insights


def _merge_comparison_into_rows(rows: list, cmp_rows: list, cols: list, comparison_label: str) -> tuple[list, list]:
    """Add comparison change rate as a new column to each row.

    Returns (new_columns, new_rows) with an added comparison column.
    """
    if not cmp_rows or not rows:
        return cols, rows

    # Build lookup from cmp_rows by label (index 0)
    cmp_map = {}
    for r in cmp_rows:
        key = str(r[0]) if r[0] else ""
        cmp_map[key] = r

    new_cols = list(cols) + [f"{comparison_label}_CHANGE"]
    new_rows = []
    for r in rows:
        key = str(r[0]) if r[0] else ""
        cmp_row = cmp_map.get(key)
        new_row = list(r)
        if cmp_row and len(cmp_row) >= 2:
            # TOTAL_AMOUNT is typically index 1
            cur_amt = float(r[1]) if len(r) > 1 and r[1] is not None else 0
            cmp_amt = float(cmp_row[1]) if len(cmp_row) > 1 and cmp_row[1] is not None else 0
            if cmp_amt != 0:
                change = round((cur_amt - cmp_amt) / cmp_amt * 100, 1)
                new_row.append(change)
            else:
                new_row.append(None)
        elif len(new_row) == len(new_cols) - 1:
            new_row.append(None)
        new_rows.append(new_row)
    return new_cols, new_rows


@app.post("/api/analyze")
async def api_analyze(request: Request):
    """Analyze previous query results with LLM — LLM decides what data to query, then analyzes.

    Flow: LLM first thinks → outputs follow-up queries → backend executes them →
          LLM receives all data → produces final analysis.
    """
    body = await request.json()
    text = body.get("text", "")
    context = body.get("context")
    previous_data = body.get("previous_data")

    system_prompt = build_system_prompt(context)
    data_desc = ""
    if previous_data:
        cols = previous_data.get("columns", [])
        rows = previous_data.get("rows", [])
        row_count = previous_data.get("row_count", 0)
        comp = previous_data.get("comparison")
        data_desc = f"\n上一轮查询结果：列={cols}，行数={row_count}，前5行={rows[:5]}"
        if comp:
            data_desc += f"，对比数据={comp}"

    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")
    model = os.environ.get("LLM_MODEL", "")

    if not api_key or not base_url or not model:
        return {"summary": "LLM 未配置，无法进行分析。"}

    client = OpenAI(api_key=api_key, base_url=base_url)

    try:
        # Step 1: LLM decides what additional queries are needed
        plan_prompt = f"""{system_prompt}

你是一个外汇交易数据分析助手。用户正在追问之前查询结果的原因。
请先判断：需要查询哪些额外数据才能回答用户的问题？

输出JSON格式：
```json
{{
  "queries": [
    {{"text": "自然语言查询", "reason": "为什么需要这个数据"}}
  ]
}}
```
如果不需要额外数据，返回空数组。

{data_desc}

用户问题：{text}"""

        plan_resp = client.chat.completions.create(
            model=model, temperature=0.1,
            messages=[{"role": "user", "content": plan_prompt}],
            timeout=30,
        )
        plan_content = plan_resp.choices[0].message.content or "{}"
        # Parse JSON from LLM response
        plan = _extract_json_from_text(plan_content) or {"queries": []}
        queries = plan.get("queries", [])

        # Step 2: Execute each follow-up query
        extra_data = []
        for q in queries[:3]:  # Max 3 follow-up queries
            q_text = q.get("text", "")
            if not q_text:
                continue
            # Parse the query
            q_parsed = rule_based_parse(q_text)
            q_confidence = _rule_confidence(q_text, q_parsed)
            if q_confidence < 0.8:
                llm_result = llm_parse(q_text, system_prompt)
                if llm_result:
                    q_parsed = gatekeep(llm_result, q_text)
                else:
                    q_parsed = gatekeep(q_parsed, q_text)
            # Build and execute SQL
            try:
                q_sql = _route_sql(q_parsed)
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(q_sql)
                        q_cols = [desc[0] for desc in cur.description] if cur.description else []
                        q_rows = [list(row) for row in cur.fetchall()]
                extra_data.append({
                    "query": q_text,
                    "columns": q_cols,
                    "rows": q_rows[:20],
                    "row_count": len(q_rows),
                })
            except Exception as exc:
                extra_data.append({"query": q_text, "error": str(exc)})

        # Step 3: LLM synthesizes final analysis
        analysis_prompt = f"""你是一个外汇交易数据分析助手。

{data_desc}

额外查询的数据：
{json.dumps(extra_data, ensure_ascii=False, indent=2) if extra_data else "（无需额外查询）"}

请基于以上所有数据，分析用户问题的具体原因。用中文自然语言回答。
如果发现了突增的客户或银行，说明是哪些。如果数据不足以分析，诚实说明。

用户问题：{text}"""

        analysis_resp = client.chat.completions.create(
            model=model, temperature=0.3,
            messages=[{"role": "user", "content": analysis_prompt}],
            timeout=60,
        )
        content = analysis_resp.choices[0].message.content or ""
        return {"summary": content.strip()}

    except Exception as exc:
        logger.exception("Analysis failed")
        return {"summary": f"分析请求失败：{exc}"}


def _extract_json_from_text(text: str) -> dict | None:
    """Extract JSON object from LLM text response."""
    import re as _re
    m = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, _re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _route_sql(parsed: dict) -> str:
    """Build SQL from parsed params (same routing as /api/query)."""
    buy_sell = parsed.get("buy_sell") or None
    cust_name = parsed.get("cust_name") or None
    special_states = parsed.get("special_states")
    if isinstance(special_states, str) and special_states:
        special_states = [s.strip() for s in special_states.split(",")]
    else:
        special_states = None

    amount_filter = parsed.get("amount_filter")
    top_n = parsed.get("top_n")

    if amount_filter:
        return TradeQueryBuilder.build_filtered_query(
            product_type=parsed["product_type"],
            date_start=parsed.get("date_start") or None,
            date_end=parsed.get("date_end") or None,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=parsed.get("bank_name") or None,
            amount_op=amount_filter["amount_op"],
            amount_value=amount_filter["amount_value"],
            hedge_ratio=parsed.get("hedge_ratio", False),
            dimension=parsed.get("dimension", "bank"),
            cust_name=cust_name, appid=parsed.get("appid"),
        )
    elif top_n and top_n > 0:
        return TradeQueryBuilder.build_ranking_query(
            product_type=parsed["product_type"],
            date_start=parsed.get("date_start") or None,
            date_end=parsed.get("date_end") or None,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=parsed.get("bank_name") or None, top_n=top_n,
            dimension=parsed.get("dimension", "bank"),
            hedge_ratio=parsed.get("hedge_ratio", False),
            cust_name=cust_name, appid=parsed.get("appid"),
        )
    elif parsed.get("hedge_ratio"):
        return TradeQueryBuilder.build_hedge_ratio_query(
            product_type=parsed["product_type"],
            date_start=parsed.get("date_start") or None,
            date_end=parsed.get("date_end") or None,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=parsed.get("bank_name") or None,
            dimension=parsed.get("dimension", "bank"),
            cust_name=cust_name, appid=parsed.get("appid"),
        )
    elif parsed.get("aggregate"):
        return TradeQueryBuilder.build_aggregate_query(
            product_type=parsed["product_type"],
            date_start=parsed.get("date_start") or None,
            date_end=parsed.get("date_end") or None,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=parsed.get("bank_name") or None,
            cust_name=cust_name, appid=parsed.get("appid"),
            dimension=parsed.get("dimension"),
        )
    else:
        return TradeQueryBuilder.build_query(
            product_type=parsed["product_type"],
            date_start=parsed.get("date_start") or None,
            date_end=parsed.get("date_end") or None,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=parsed.get("bank_name") or None,
            cust_name=cust_name, appid=parsed.get("appid"),
        )


@app.get("/")
def index():
    dist_index = FRONTEND_DIR / "dist" / "index.html"
    if dist_index.exists():
        return FileResponse(dist_index)
    return FileResponse(FRONTEND_DIR / "index.html")


# Serve static assets from Vite build output (production mode)
_dist_assets = FRONTEND_DIR / "dist" / "assets"
if _dist_assets.exists():
    app.mount("/assets", StaticFiles(directory=str(_dist_assets)), name="assets")


# ---- LangGraph orchestration endpoint ----

from langgraph.pipeline import build_main_graph
_langgraph_app = build_main_graph()


@app.post("/api/chat")
async def api_chat(request: Request):
    """Run the LangGraph orchestration pipeline.

    Parallel to /api/query — both return the same ResultCard-compatible format.
    """
    from langgraph.state import AgentState

    body = await request.json()
    text = body.get("text", "")
    session_id = body.get("session_id", "")
    context = body.get("context")

    state = AgentState(
        request_id=str(uuid.uuid4())[:8],
        session_id=session_id,
        user_text=text,
        context=context,
    )

    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=True)

        final = await _langgraph_app.ainvoke(state)

        router_decision = final.get("router_decision", {})
        router_status = router_decision.get("status", "ok") if router_decision else "ok"

        result = {
            "sql": final.get("sql", ""),
            "params": final.get("parsed_params", {}),
            "columns": final.get("columns", []),
            "rows": final.get("rows", []),
            "row_count": final.get("row_count", 0),
            "comparison": final.get("comparison"),
            "summary": final.get("summary", ""),
            "chartOption": final.get("chart_option"),
            "insights": final.get("insights", []),
            "validation_warnings": final.get("validation_warnings", []),
            "sql_validated": final.get("sql_validated", False),
            "router_decision": router_decision,
            "error": final.get("error", ""),
        }

        if router_status == "rejected":
            return JSONResponse(
                status_code=422,
                content=result | {"summary": router_decision.get("message", "")},
            )

        if router_status == "confirm":
            return JSONResponse(
                status_code=200,
                content=result | {
                    "summary": router_decision.get("message", "请确认查询参数"),
                    "confirm_needed": router_decision.get("needs_confirm", []),
                },
            )

        return result
    except Exception as exc:
        logger.exception("LangGraph /api/chat failed: %s", text)
        return JSONResponse(status_code=500, content={
            "error": f"{type(exc).__name__}: {exc}",
            "sql": "",
            "params": {},
            "columns": [],
            "rows": [],
            "row_count": 0,
            "comparison": None,
            "summary": "",
            "chartOption": {},
            "insights": [],
        })
