"""FastAPI application — FX trade query service."""

import asyncio
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
from llm_parser.llm_client import llm_parse, llm_chat
from llm_parser.rules_engine import gatekeep, reload_rules
from llm_parser.prompt_builder import build_system_prompt, invalidate_cache
from db.query_builder import TradeQueryBuilder
from db.connection import get_db
from db.mysql_store import init_db, get_conn, _auto_migrate
from admin_routes import router as admin_router
import uuid
from datetime import datetime

# Initialize store on startup
init_db()
_auto_migrate()

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
app.mount("/mcp", _mcp_asgi)

# ── Static files ──────────────────────────────────────────────────────────────

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_dist_assets = _FRONTEND_DIR / "dist" / "assets"
if _dist_assets.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_dist_assets)), name="assets")
    _INDEX = _FRONTEND_DIR / "dist" / "index.html"
else:
    _INDEX = _FRONTEND_DIR / "index.html"


@app.get("/")
async def serve_index():
    if _INDEX.exists():
        return FileResponse(str(_INDEX))
    return JSONResponse(status_code=404, content={"error": "Frontend not built"})


app.include_router(admin_router)

# ── Helper functions ──────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_RESULT_MAX_CHARS = 50000


def _safe_truncate(text: str, max_chars: int = _RESULT_MAX_CHARS) -> str:
    """Truncate at a JSON-safe boundary, never mid-string."""
    if not text or len(text) <= max_chars:
        return text
    # Find the last '}' within the limit to avoid cutting mid-JSON
    truncated = text[:max_chars]
    last_brace = truncated.rfind("}")
    if last_brace > 0:
        return truncated[: last_brace + 1]
    # Fallback: if no '}' found, cut at max_chars (Python handles multi-byte)
    return truncated


def _build_sql(parsed, date_start=None, date_end=None):
    """Build SQL from parsed params with given date range.

    Shared by the main query endpoint and comparison SQL builder.
    """
    buy_sell = parsed.get("buy_sell") or None
    cust_name = parsed.get("cust_name") or None
    special_states = parsed.get("special_states", "")
    if isinstance(special_states, str) and special_states:
        special_states = [s.strip() for s in special_states.split(",")]
    else:
        special_states = None

    amount_filter = parsed.get("amount_filter")
    top_n = parsed.get("top_n")

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
            bank_name=parsed["bank_name"] or None,
            top_n=top_n, dimension=parsed.get("dimension", "bank"),
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


def _build_comparison_sql(parsed, date_start, date_end):
    """Rebuild SQL with comparison date range."""
    return _build_sql(parsed, date_start=date_start, date_end=date_end)


_MAX_ROWS = 10000


def _execute_oracle(sql: str) -> tuple:
    """Execute SQL against Oracle and return (columns, rows)."""
    logger = logging.getLogger(__name__)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [desc[0] for desc in cur.description] if cur.description else []
            rows = [list(row) for row in cur.fetchmany(_MAX_ROWS)]
            if cur.arraysize == _MAX_ROWS:
                more = cur.fetchone()
                if more is not None:
                    logger.warning("Query result exceeds %d rows, truncated", _MAX_ROWS)
    return cols, rows


def _compute_comparison(current_rows, compare_rows, comparison, date_start, date_end, cmp_start, cmp_end, cols=None):
    """Compute change_amount and change_rate from current and comparison rows.

    Returns a dict with keys: type, label, change_amount, change_rate,
    compare_amount, date_start, date_end, cmp_start, cmp_end.
    """
    amt_idx = _find_amount_col(cols) if cols else 0
    label_map = {"yoy": "同比", "mom": "环比"}
    total_current = sum(float(r[amt_idx] if isinstance(r, (list, tuple)) and r[amt_idx] is not None else 0) for r in current_rows) if current_rows else 0
    total_compare = sum(float(r[amt_idx] if isinstance(r, (list, tuple)) and r[amt_idx] is not None else 0) for r in compare_rows) if compare_rows else 0

    if total_compare == 0:
        return {
            "type": comparison,
            "label": label_map.get(comparison, comparison),
            "change_amount": 0,
            "change_rate": 0,
            "compare_amount": 0,
            "date_start": date_start, "date_end": date_end,
            "cmp_start": cmp_start, "cmp_end": cmp_end,
        }

    change_amount = total_current - total_compare
    change_rate = round((change_amount / total_compare) * 100, 2)

    return {
        "type": comparison,
        "label": label_map.get(comparison, comparison),
        "change_amount": round(change_amount, 2),
        "change_rate": change_rate,
        "compare_amount": round(total_compare, 2),
        "date_start": date_start, "date_end": date_end,
        "cmp_start": cmp_start, "cmp_end": cmp_end,
    }


def _execute_query_sync(sql: str, parsed: dict) -> tuple:
    """Run Oracle query and optional comparison query, returns result tuple.

    This is a blocking sync function — run via asyncio.to_thread.
    Returns (cols, rows, comparison_data, cmp_rows, comparison_sql).
    """
    # Step c: main query
    cols, rows = _execute_oracle(sql)

    # Step d: comparison (同比/环比)
    comparison = parsed.get("comparison")
    comparison_data = None
    cmp_rows = []
    comparison_sql = None

    if comparison and sql and rows:
        cmp_start, cmp_end = compute_comparison_dates(
            parsed["date_start"] or "", parsed["date_end"] or "", comparison
        )
        if cmp_start and cmp_end:
            comparison_sql = _build_comparison_sql(
                parsed=parsed,
                date_start=cmp_start, date_end=cmp_end,
            )
            try:
                # Reuse the same Oracle connection pattern
                cmp_cols, cmp_rows = _execute_oracle(comparison_sql)
                if cmp_rows:
                    comparison_data = _compute_comparison(
                        current_rows=rows, compare_rows=cmp_rows,
                        comparison=comparison,
                        date_start=parsed["date_start"] or "",
                        date_end=parsed["date_end"] or "",
                        cmp_start=cmp_start, cmp_end=cmp_end,
                        cols=cmp_cols,
                    )
            except Exception as exc:
                logger.warning("Comparison query failed: %s", exc)

    return cols, rows, comparison_data, cmp_rows, comparison_sql


def _merge_comparison_into_rows(rows: list, cmp_rows: list, cols: list, comparison_label: str) -> tuple[list, list]:
    """Add comparison change rate as a new column to each row.

    Returns (new_columns, new_rows) with an added comparison column.
    """
    if not cmp_rows or not rows:
        return cols, rows

    # Build map: bank_name → comparison value
    bank_idx = None
    for i, c in enumerate(cols):
        if c in ("BANKNAME", "银行"):
            bank_idx = i
            break
    if bank_idx is None:
        return cols, rows

    cmp_map = {}
    for cr in cmp_rows:
        if len(cr) > bank_idx:
            key = str(cr[bank_idx])
            cmp_map[key] = cr[0]  # comparison value (first column)

    new_cols = list(cols) + [f"{comparison_label}_CHANGE"]
    new_rows = []
    for row in rows:
        new_row = list(row)
        bank_val = str(row[bank_idx]) if len(row) > bank_idx else ""
        cmp_val = cmp_map.get(bank_val, 0)
        current_val = float(row[0]) if row and row[0] is not None else 0
        if current_val and cmp_val:
            rate = round(((current_val - float(cmp_val)) / float(cmp_val)) * 100, 2)
        else:
            rate = 0
        new_row.append(f"{rate:+.2f}%")
        new_rows.append(new_row)

    return new_cols, new_rows


# ── Session endpoints ─────────────────────────────────────────────────────────


@app.post("/api/sessions")
def create_session():
    import secrets
    conn = get_conn()
    sid = secrets.token_hex(4)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (id) VALUES (%s)", (sid,)
            )
        conn.commit()
        return {"session_id": sid}
    finally:
        conn.close()


@app.get("/api/sessions")
def list_sessions():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, agent_type, created_at, updated_at FROM sessions WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 50"
            )
            return cur.fetchall()
    finally:
        conn.close()


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    """Get all turns for a session."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM sessions WHERE id = %s AND is_active = 1", (session_id,)
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
                "user_feedback": t["user_feedback"],
                "created_at": t["created_at"],
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
                    (session_id, _now()),
                )

            # Get next turn_index
            cur.execute(
                "SELECT COALESCE(MAX(turn_index), -1) FROM turns WHERE session_id = %s",
                (session_id,),
            )
            max_idx = cur.fetchone()["COALESCE(MAX(turn_index), -1)"]

            cur.execute(
                """INSERT INTO turns (session_id, turn_index, user_query,
                   parsed_params, executed_sql, result_summary)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (session_id, max_idx + 1,
                 body.get("user_query", ""),
                 json.dumps(body.get("parsed_params"), ensure_ascii=False) if body.get("parsed_params") else None,
                 body.get("executed_sql"),
                 _safe_truncate(body.get("result_summary") or "") or None),
            )
            cur.execute(
                "UPDATE sessions SET updated_at = %s WHERE id = %s",
                (_now(), session_id),
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


# ── Parse endpoint ────────────────────────────────────────────────────────────


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
        if confidence >= 0.8 or context:
            # High confidence or multi-turn context — skip LLM, use rules
            # (context provides the specific params, LLM adds no value for follow-ups)
            parsed = gatekeep(rule_parsed, text)
            pipeline = f"rule(confidence={confidence:.0%})"
        else:
            # Low confidence — need LLM (with conversation context)
            system_prompt = build_system_prompt(context)
            llm_result = await asyncio.to_thread(llm_parse, text, system_prompt)
            if llm_result is not None:
                parsed = gatekeep(llm_result, text)
                pipeline = f"llm+gatekeep(rule_confidence={confidence:.0%})"
            else:
                # LLM failed, fallback to rules (still gatekeep)
                parsed = gatekeep(rule_parsed, text)
                pipeline = f"rule_fallback(confidence={confidence:.0%})"

        # --- 从上下文继承参数（同比跟进查询等需要继承 bank_name、aggregate 等）---
        if context:
            inherited = _inherit_params_from_context(context, parsed)
            if inherited:
                for k, v in inherited.items():
                    if k not in parsed or not parsed.get(k):
                        parsed[k] = v
                logger.info("Parse inherited params from context: %s", {
                    k: v for k, v in inherited.items() if v
                })

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


# ── Query endpoint ────────────────────────────────────────────────────────────


@app.post("/api/query")
async def query(request: Request):
    body = await request.json()
    text = body.get("text", "")
    pre_parsed = body.get("params")
    context = body.get("context")

    sql = None
    parsed = {}

    try:
        if pre_parsed:
            parsed = pre_parsed
            logger.info("Using pre-parsed params from frontend")
        else:
            rule_parsed = rule_based_parse(text)
            confidence = _rule_confidence(text, rule_parsed)
            if confidence >= 0.8 or context:
                parsed = gatekeep(rule_parsed, text)
                logger.info("Rule-only pipeline used (confidence=%.0%%)", confidence)
            else:
                system_prompt = build_system_prompt()
                llm_result = await asyncio.to_thread(llm_parse, text, system_prompt)
                if llm_result is not None:
                    parsed = gatekeep(llm_result, text)
                    logger.info("LLM+Gatekeep pipeline used (rule_confidence=%.0%%)", confidence)
                else:
                    parsed = gatekeep(rule_parsed, text)
                    logger.info("Rule fallback (LLM failed, confidence=%.0%%)", confidence)

        # ---- 从上下文继承参数（同比/环比等跟进查询需要继承上一轮的查询参数）----
        if context:
            inherited = _inherit_params_from_context(context, parsed)
            if inherited:
                for k, v in inherited.items():
                    if k not in parsed or not parsed.get(k):
                        parsed[k] = v
                logger.info("Inherited params from context: %s", {k: v for k, v in inherited.items() if v})

              # ---- 同比/环比缺少日期时仍需要上下文日期 ----
        if parsed.get("comparison") and not (parsed.get("date_start") and parsed.get("date_end")):
            if context:
                inherited = _inherit_dates_from_context(context)
                if inherited:
                    parsed["date_start"] = inherited["date_start"]
                    parsed["date_end"] = inherited["date_end"]
                    logger.info("Inherited dates from context: %s ~ %s", inherited["date_start"], inherited["date_end"])
                else:
                    # Context exists but no dates (ranking query case) → default to current year
                    now = datetime.now()
                    parsed["date_start"] = f"{now.year}-01-01"
                    parsed["date_end"] = now.strftime("%Y-%m-%d")
                    logger.info("Defaulted dates for comparison (context exists, no inherited dates): %s ~ %s", parsed["date_start"], parsed["date_end"])
            # else: no context, leave dates empty → confirm_date below

        # If comparison is set but still no dates → ask user for confirmation
        if parsed.get("comparison") and not (parsed.get("date_start") and parsed.get("date_end")):
            logger.info("No dates available for comparison query, returning confirm_date")
            return {
                "confirm_date": True,
                "params": parsed,
                "columns": [], "rows": [], "row_count": 0,
                "sql": None, "comparison_sql": None,
                "comparison": None,
                "summary": None,
                "chartOption": None,
                "insights": [],
            }

        # Step b: build SQL (shared with comparison builder)
        sql = _build_sql(parsed, date_start=parsed.get("date_start") or None, date_end=parsed.get("date_end") or None)

        # Steps c+d: execute main + comparison query in thread pool
        cols, rows, comparison_data, cmp_rows, comparison_sql = await asyncio.to_thread(
            _execute_query_sync, sql, parsed
        )

        # Merge per-row comparison data
        if comparison_data and cmp_rows:
            cmp_label = comparison_data.get("label", "对比")
            cols, rows = _merge_comparison_into_rows(rows, cmp_rows, cols, cmp_label)

    except Exception as exc:
        logger.exception("查询执行失败: %s", text)
        return JSONResponse(status_code=500, content={
            "sql": sql, "params": parsed,
            "columns": [], "rows": [], "row_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        })

    return {
        "sql": sql,
        "comparison_sql": comparison_sql,
        "params": parsed,
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
        "comparison": comparison_data,
        "summary": _build_summary(parsed, rows, cols, comparison_data),
        "chartOption": _build_chart_option(parsed, rows, cols, comparison_data),
        "insights": _build_insights(parsed, rows, cols, comparison_data),
        "validation_warnings": [],
        "sql_validated": True,
    }


# ---- ResultCard builders ----


_AMOUNT_COL_NAMES = {"USDAMOUNT", "TOTAL_AMOUNT", "DERIVATIVE_AMOUNT"}
_LABEL_COL_NAMES = {"DIPNAME", "BANKNAME", "银行", "客户经理", "CUSTMANAGERNAME"}


def _find_amount_col(cols: list) -> int:
    """Find the index of the numeric amount column."""
    for i, c in enumerate(cols):
        if c.upper() in _AMOUNT_COL_NAMES:
            return i
    return 0  # fallback


def _find_label_col(cols: list) -> int:
    """Find the index of the label/dimension column (bank name, etc.)."""
    for i, c in enumerate(cols):
        if c.upper() in _LABEL_COL_NAMES:
            return i
    return 0  # fallback


def _build_summary(parsed: dict, rows: list, cols: list, comparison: dict | None) -> str:
    """Build natural language summary for ResultCard section 1."""
    if not rows or not cols:
        return ""

    amt_idx = _find_amount_col(cols)
    date_start = parsed.get("date_start", "") or ""
    date_end = parsed.get("date_end", "") or ""
    bank_name = (parsed.get("bank_name") or "")

    total_usd = sum(float(r[amt_idx]) for r in rows if r and r[amt_idx] is not None) / 10000 if rows else 0
    total_count = len(rows)

    parts = [f"{date_start} ~ {date_end}"]
    if bank_name:
        parts.append(f"{bank_name}")
    parts.append(f"全市场共{total_count}家交易对手")
    parts.append(f"合计{total_usd:,.2f}万美元")

    if comparison:
        cmp_label = comparison.get("label", "")
        rate = comparison.get("change_rate")
        direction = "增长" if (comparison.get("change_amount") or 0) >= 0 else "下降"
        amt = abs(comparison.get("change_amount", 0) or 0) / 10000
        if rate is not None:
            parts.append(f"{cmp_label}{direction}{amt:,.2f}万美元（{rate:+.2f}%）")
        else:
            parts.append(f"{cmp_label}{direction}{amt:,.2f}万美元")

    return "，".join(parts) + "。"


def _build_chart_option(parsed: dict, rows: list, cols: list, comparison: dict | None) -> dict | None:
    """Build ECharts option for ResultCard section 2."""
    if not rows or not cols:
        return None

    amt_idx = _find_amount_col(cols)
    label_idx = _find_label_col(cols)

    bank_name = (parsed.get("bank_name") or "").strip() or "全市场"
    title_parts = [f"{bank_name}交易量"]
    date_start = parsed.get("date_start", "") or ""
    date_end = parsed.get("date_end", "") or ""
    if date_start and date_end:
        title_parts.append(f"（{date_start} ~ {date_end}）")

    x_data = [str(r[label_idx]) if r else "" for r in rows]
    series_data = [float(r[amt_idx]) if r and r[amt_idx] is not None else 0 for r in rows]

    series = [{"name": "交易量", "type": "bar", "data": series_data, "itemStyle": {"color": "#3b82f6"}}]

    if comparison:
        cmp_label = comparison.get("label", "对比")
        cmp_amt = comparison.get("compare_amount", 0) / 10000
        series.append({
            "name": cmp_label,
            "type": "bar",
            "data": [round(cmp_amt, 2)] * len(series_data),
            "itemStyle": {"color": "#94a3b8"},
        })

    return {
        "title": {"text": "".join(title_parts), "left": "center"},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [s["name"] for s in series], "bottom": 0},
        "xAxis": {"type": "category", "data": x_data, "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "value", "name": "万美元"},
        "series": series,
        "grid": {"left": 60, "right": 20, "bottom": 40, "top": 40},
    }


def _build_insights(parsed: dict, rows: list, cols: list, comparison: dict | None) -> list[dict]:
    """Build analysis insights for ResultCard section 3."""
    if not rows:
        return []

    amt_idx = _find_amount_col(cols)
    label_idx = _find_label_col(cols)
    insights = []

    # Insight 1: Comparison
    if comparison:
        rate = comparison.get("change_rate")
        direction = "增长" if (comparison.get("change_amount") or 0) >= 0 else "下降"
        cmp_label = comparison.get("label", "对比")
        amt = abs(comparison.get("change_amount", 0) or 0) / 10000
        if rate is not None:
            insights.append({
                "type": "comparison",
                "text": f"较{cmp_label}{direction}了{amt:,.2f}万美元（{rate:+.2f}%）",
            })
        else:
            insights.append({
                "type": "comparison",
                "text": f"较{cmp_label}{direction}了{amt:,.2f}万美元",
            })
    else:
        total = sum(float(r[amt_idx]) for r in rows if r and r[amt_idx] is not None) / 10000 if rows else 0
        insights.append({
            "type": "overview",
            "text": f"查询到交易共合计 {total:,.2f} 万美元",
        })

    # Insight 2: Volume insight
    bank_idx = None
    for i, c in enumerate(cols):
        if c in ("BANKNAME", "银行", "DIPNAME"):
            bank_idx = i
            break
    if bank_idx is not None and len(rows) > 1:
        vals = [(float(r[amt_idx]) if len(r) > amt_idx and r[amt_idx] is not None else 0) for r in rows]
        if vals:
            max_val = max(vals)
            min_val = min(vals)
            max_row = rows[vals.index(max_val)]
            min_row = rows[vals.index(min_val)]
            max_name = str(max_row[bank_idx]) if max_row and len(max_row) > bank_idx else ""
            min_name = str(min_row[bank_idx]) if min_row and len(min_row) > bank_idx else ""
            if max_name and max_val > 0:
                insights.append({
                    "type": "distribution",
                    "text": f"交易量最高为 {max_name}（{max_val/10000:,.2f} 万美元），最低为 {min_name}（{min_val/10000:,.2f} 万美元）",
                })

    return insights


_INHERIT_PARAMS = {
    "bank_name", "cust_name", "product_type", "aggregate", "dimension",
    "top_n", "amount_filter", "hedge_ratio", "appid", "special_states",
}


def _inherit_params_from_context(context: list | None, current: dict) -> dict | None:
    """Inherit structural query params from the previous assistant turn.

    This ensures follow-up queries like "同比增加多少" keep the same
    filters (bank_name, aggregate, dimension, etc.) from the previous query.
    """
    if not context or not isinstance(context, list):
        return None
    for msg in reversed(context):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            try:
                prev = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            prev_params = prev.get("params", prev) or prev
            inherited = {}
            for key in _INHERIT_PARAMS:
                val = prev_params.get(key)
                if val is not None and val != "" and val != False and val != []:
                    # Only inherit if current doesn't have a meaningful value
                    current_val = current.get(key)
                    if current_val is None or current_val == "" or current_val == False:
                        inherited[key] = val
            return inherited if inherited else None
    return None


def _inherit_dates_from_context(context: list | None) -> dict | None:
    """Try to inherit date range from the most recent assistant turn in context.

    Returns {date_start, date_end} or None if no dates found.
    """
    if not context or not isinstance(context, list):
        return None
    for msg in reversed(context):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            try:
                prev = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            prev_data = prev.get("params", prev)
            ds = prev_data.get("date_start", "") or prev.get("date_start", "") or ""
            de = prev_data.get("date_end", "") or prev.get("date_end", "") or ""
            if ds and de:
                return {"date_start": ds, "date_end": de}
    return None


# ── LangGraph orchestration endpoint ──────────────────────────────────────────

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
        })


# ── Analysis endpoint ─────────────────────────────────────────────────────────


@app.post("/api/analyze")
async def analyze(body: dict):
    """Use LLM to analyze previous query results."""
    text = body.get("text", "")
    previous_data = body.get("previous_data", {})
    context = body.get("context", [])

    summary = previous_data.get("summary", "")
    comparison = previous_data.get("comparison", {})

    system_prompt = (
        "你是一个外汇交易数据分析助手。根据用户的问题和已有的查询结果数据，"
        "给出专业、简洁的分析。分析要基于数据说话，不要编造数字。"
        "回答控制在 200 字以内。"
    )

    cmp_info = ""
    if comparison:
        cmp_type = comparison.get("type", "")
        label = comparison.get("label", cmp_type)
        change = comparison.get("change_amount", 0)
        rate = comparison.get("change_rate", 0)
        cmp_info = f"\n{label}变化: {change:+,.2f} USD ({rate:+.2f}%)"

    user_prompt = (
        f"用户问题: {text}\n"
        f"当前数据摘要: {summary}{cmp_info}\n"
        f"请分析可能的原因。"
    )

    result_text = await asyncio.to_thread(llm_chat, system_prompt, user_prompt)
    if not result_text:
        return JSONResponse(status_code=503, content={"error": "分析服务暂不可用，请稍后重试"})

    return {"summary": result_text}


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/api/health")
def health():
    return {"status": "ok"}