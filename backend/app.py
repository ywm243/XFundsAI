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
from llm_parser.rules_engine import gatekeep, reload_rules, load_dimension_config
from llm_parser.prompt_builder import build_system_prompt, invalidate_cache
from db.query_builder import TradeQueryBuilder
from db.connection import get_db
from db.mysql_store import init_db, get_conn, _auto_migrate
from admin_routes import router as admin_router
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

# Initialize store on startup
init_db()
_auto_migrate()

# Load dimension config from rules DB and inject into query builder
_dimension_config = load_dimension_config()
TradeQueryBuilder.configure_dimensions(_dimension_config.get("dimensions", {}))
logger.info("Dimension config loaded (%d dimensions)", len(_dimension_config.get("dimensions", {})))

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


def _compute_importance(user_query: str, parsed_params: dict | None = None) -> int:
    """Score a turn's importance from 1 (routine) to 5 (critical).

    Factors: comparison queries, multi-filter specificity, aggregation,
    hedge ratio, query length.
    """
    score = 1  # baseline
    if not parsed_params:
        return min(score, 5)

    if parsed_params.get("comparison"):
        score += 1                      # 同比/环比查询更关键
    if parsed_params.get("aggregate") or parsed_params.get("top_n"):
        score += 1                      # 聚合/排名有分析价值
    if parsed_params.get("hedge_ratio"):
        score += 1                      # 套保率是高级分析
    filters = sum(1 for k in ("bank_name", "cust_name", "appid",
                               "special_states", "amount_filter")
                  if parsed_params.get(k))
    if filters >= 2:
        score += 1                      # 多维度过滤 → 查询更具体
    if len(user_query) > 15:
        score += 1                      # 详细提问 → 更有价值

    return min(score, 5)


def _build_sql(parsed, date_start=None, date_end=None):
    """Build SQL from parsed params with given date range.

    Shared by the main query endpoint and comparison SQL builder.
    """
    buy_sell = parsed.get("buy_sell") or None
    cust_name = parsed.get("cust_name") or None
    bank_name = parsed.get("bank_name") or None
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
            bank_name=bank_name,
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
            bank_name=bank_name,
            top_n=top_n, dimension=parsed.get("dimension", "bank"),
            hedge_ratio=parsed.get("hedge_ratio", False),
            cust_name=cust_name, appid=parsed.get("appid"),
        )
    elif parsed.get("hedge_ratio"):
        return TradeQueryBuilder.build_hedge_ratio_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=bank_name,
            dimension=parsed.get("dimension", "bank"),
            cust_name=cust_name, appid=parsed.get("appid"),
        )
    elif parsed.get("aggregate"):
        return TradeQueryBuilder.build_aggregate_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=bank_name,
            cust_name=cust_name, appid=parsed.get("appid"),
            dimension=parsed.get("dimension"),
        )
    else:
        return TradeQueryBuilder.build_query(
            product_type=parsed["product_type"],
            date_start=date_start, date_end=date_end,
            special_states=special_states, buy_sell=buy_sell,
            bank_name=bank_name,
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
            if cur.fetchone() is not None:
                logger.warning("Query result exceeds %d rows, truncated", _MAX_ROWS)
    return cols, rows


def _compute_comparison(current_rows, compare_rows, comparison, date_start, date_end, cmp_start, cmp_end, cols=None):
    """Compute change_amount and change_rate from current and comparison rows.

    Returns a dict with keys: type, label, change_amount, change_rate,
    compare_amount, date_start, date_end, cmp_start, cmp_end.
    """
    amt_idx = _find_amount_col(cols) if cols else 0
    label_map = _dimension_config.get("comparison_labels", {"yoy": "同比", "mom": "环比"})
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
                "importance": t.get("importance", 0),
                "user_feedback": t["user_feedback"],
                "created_at": t["created_at"],
            } for t in turns],
        }
    finally:
        conn.close()


@app.post("/api/sessions/{session_id}/turns")
async def save_turn(session_id: str, request: Request):
    """Save a conversation turn to the session, compute importance,
    and auto-summarize every 5 turns."""
    body = await request.json()
    user_query = body.get("user_query", "")
    parsed_params = body.get("parsed_params")
    importance = _compute_importance(user_query, parsed_params)

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
                   parsed_params, executed_sql, result_summary, importance)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (session_id, max_idx + 1, user_query,
                 json.dumps(parsed_params, ensure_ascii=False) if parsed_params else None,
                 body.get("executed_sql"),
                 _safe_truncate(body.get("result_summary") or "") or None,
                 importance),
            )
            cur.execute(
                "UPDATE sessions SET updated_at = %s WHERE id = %s",
                (_now(), session_id),
            )
        conn.commit()

        # ---- Auto-summarize every 5 turns ----
        from memory.store import AgentMemory
        memory = AgentMemory()
        if memory.should_summarize(session_id):
            turns = memory.get_context(session_id, last_n=5)
            products = set()
            has_comparison = False
            for t in turns:
                params = t.get("parsed_params") or {}
                if isinstance(params, dict):
                    pt = params.get("product_type", "")
                    if pt:
                        products.add(pt)
                    if params.get("comparison"):
                        has_comparison = True
            memory.add_summary(session_id, "turn_group", {
                "turn_indices": [t["turn_index"] for t in turns],
                "queries": [t["user_query"] for t in turns],
                "products": list(products),
                "has_comparison": has_comparison,
                "total_turns": max_idx + 2,
            })
            logger.info("Auto-summarized session %s at turn %d (importance=%d)",
                        session_id, max_idx + 1, importance)

        return {"status": "ok", "turn_index": max_idx + 1, "importance": importance}
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
    cfg = load_dimension_config()
    TradeQueryBuilder.configure_dimensions(cfg.get("dimensions", {}))
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
    mode = body.get("mode", "")
    pre_parsed = body.get("params")
    context = body.get("context")
    session_id = body.get("session_id", "")

    # ---- mode=analyze: LLM tool-calling analysis pipeline ----
    if mode == "analyze":
        rule_parsed = rule_based_parse(text)
        confidence = _rule_confidence(text, rule_parsed)
        if confidence >= 0.8 or context:
            parsed = gatekeep(rule_parsed, text)
        else:
            system_prompt = build_system_prompt()
            llm_result = await asyncio.to_thread(llm_parse, text, system_prompt)
            if llm_result is not None:
                parsed = gatekeep(llm_result, text)
            else:
                parsed = gatekeep(rule_parsed, text)

        # Inherit params from context (follow-up queries like "分析下原因")
        if context:
            inherited = _inherit_params_from_context(context, parsed)
            if inherited:
                for k, v in inherited.items():
                    if k not in parsed or not parsed.get(k):
                        parsed[k] = v
                logger.info("Analyze inherited params from context: %s", {k: v for k, v in inherited.items() if v})
            # Also inherit date range (not in _INHERIT_PARAMS)
            dates = _inherit_dates_from_context(context)
            if dates:
                if not parsed.get("date_start"):
                    parsed["date_start"] = dates["date_start"]
                if not parsed.get("date_end"):
                    parsed["date_end"] = dates["date_end"]
                logger.info("Analyze inherited dates: %s ~ %s", parsed.get("date_start"), parsed.get("date_end"))

        from agent.orchestrator import run_analysis
        agent_result = run_analysis(
            user_query=text,
            session_id=session_id,
            gatekeep_params=parsed,
        )

        return {
            "summary": agent_result.get("summary", ""),
            "chartOption": _build_chart_option(parsed, [], [], None) if parsed else None,
            "insights": agent_result.get("insights", []),
            "comparison": None,
            "mode": "analyze",
            "analysis_data": agent_result.get("analysis_data"),
            "params": parsed,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "sql": "",
            "comparison_sql": None,
            "validation_warnings": [],
            "sql_validated": True,
        }

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
        "insights": _build_insights(parsed, rows, cols, comparison_data, text),
        "validation_warnings": [],
        "sql_validated": True,
    }


# ---- ResultCard builders ----


_AMOUNT_COL_NAMES = _dimension_config.get("amount_col_names", {"USDAMOUNT", "TOTAL_AMOUNT", "DERIVATIVE_AMOUNT"})
_LABEL_COL_NAMES = _dimension_config.get("label_col_names", {"DIPNAME", "BANKNAME", "银行", "客户经理", "CUSTMANAGERNAME"})


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

    # Dimension label mapping (from rules config, fallback to defaults)
    dim = parsed.get("dimension", "bank")
    dimensions_cfg = _dimension_config.get("dimensions", {})
    dim_info = dimensions_cfg.get(dim, {})
    dim_label = dim_info.get("display_label", "机构")
    count_unit = dim_info.get("count_unit", "家")

    parts = [f"{date_start} ~ {date_end}"]
    if bank_name:
        parts.append(f"{bank_name}")

    if parsed.get("aggregate"):
        # Aggregate query — each row is a group (institution / customer / manager)
        if not (bank_name and total_count == 1):
            # Skip "共1家机构" when user already specified a single bank
            parts.append(f"共{total_count}{count_unit}{dim_label}")
    else:
        # Detail query — each row is a trade record
        parts.append(f"共{total_count}笔交易")

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


def _build_insights(parsed: dict, rows: list, cols: list,
                     comparison: dict | None, user_query: str = "") -> list[dict]:
    """Build analysis insights from templates (deep analysis via /api/analyze)."""
    if not rows:
        return []

    amt_idx = _find_amount_col(cols)
    fallback = []

    if comparison:
        rate = comparison.get("change_rate")
        direction = "增长" if (comparison.get("change_amount") or 0) >= 0 else "下降"
        cmp_label = comparison.get("label", "对比")
        amt = abs(comparison.get("change_amount", 0) or 0) / 10000
        text = f"较{cmp_label}{direction}了{amt:,.2f}万美元"
        text += f"（{rate:+.2f}%）" if rate is not None else ""
        fallback.append({
            "type": "growth" if (comparison.get("change_amount") or 0) >= 0 else "risk",
            "title": f"{cmp_label}变化",
            "detail": text,
        })

    # Volume distribution
    bank_idx = _find_label_col(cols) if cols else None
    if bank_idx is not None and len(rows) > 1:
        vals = [(float(r[amt_idx]) if len(r) > amt_idx and r[amt_idx] is not None else 0) for r in rows]
        max_val = max(vals)
        max_row = rows[vals.index(max_val)]
        max_name = str(max_row[bank_idx]) if max_row and len(max_row) > bank_idx else ""
        if max_name and max_val > 0:
            fallback.append({
                "type": "quality",
                "title": "交易量分布",
                "detail": f"最高为 {max_name}（{max_val/10000:,.2f} 万美元）",
            })

    return fallback


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


def _fetch_breakdown_text(params: dict, date_start: str, date_end: str, label: str) -> str:
    """Fetch breakdown by product type for a given period, return formatted text."""
    lines = []
    bank_name = (params.get("bank_name") or "") or None
    appid = params.get("appid")

    for pt in ("spot", "fwd", "swap"):
        try:
            sql = TradeQueryBuilder.build_aggregate_query(
                product_type=pt,
                date_start=date_start or None,
                date_end=date_end or None,
                bank_name=bank_name,
                appid=appid,
            )
            cols, rows = _execute_oracle(sql)
            if rows and rows[0][0] is not None:
                amt = float(rows[0][0])
                cnt = int(rows[0][1])
                lines.append(f"  {pt}: 金额={amt:,.2f}, 笔数={cnt}")
            else:
                lines.append(f"  {pt}: 无数据")
        except Exception as exc:
            lines.append(f"  {pt}: 查询异常({exc})")
    return "\n".join(lines)


@app.post("/api/analyze")
async def analyze(body: dict):
    """Use LLM to analyze previous query results based on real data only."""
    text = body.get("text", "")
    previous_data = body.get("previous_data", {})

    comparison = previous_data.get("comparison", {})
    params = previous_data.get("params", {})

    if not params:
        return {"summary": "缺少查询参数，无法分析"}

    # Build real data context for the LLM
    data_parts = []

    # 1. Query context
    date_start = params.get("date_start", "")
    date_end = params.get("date_end", "")
    bank_name = params.get("bank_name", "") or ""
    dim = params.get("dimension", "bank")

    data_parts.append(f"查询期间: {date_start} ~ {date_end}")
    if bank_name:
        data_parts.append(f"机构: {bank_name}")
    data_parts.append(f"聚合维度: {dim}")

    # 2. Current period breakdown by product type
    data_parts.append("")
    data_parts.append("=== 当前期分产品类型 ===")
    try:
        current_breakdown = await asyncio.to_thread(
            _fetch_breakdown_text, params, date_start, date_end, "当前期"
        )
        data_parts.append(current_breakdown)
    except Exception as exc:
        logger.warning("Breakdown query failed: %s", exc)
        data_parts.append(f"  (分产品数据查询异常: {exc})")

    # 3. Comparison data
    if comparison:
        label = comparison.get("label", comparison.get("type", ""))
        change_amt = comparison.get("change_amount", 0)
        change_rate = comparison.get("change_rate", 0)
        cmp_amt = comparison.get("compare_amount", 0)
        cmp_start = comparison.get("cmp_start", "")
        cmp_end = comparison.get("cmp_end", "")

        data_parts.append("")
        data_parts.append(f"=== {label}对比 ===")
        data_parts.append(f"当前期: {date_start} ~ {date_end}")
        data_parts.append(f"对比期: {cmp_start} ~ {cmp_end}")
        data_parts.append(f"变化额: {change_amt:+,.2f}")
        data_parts.append(f"变化率: {change_rate:+.2f}%")

        # 4. Comparison period breakdown by product type
        data_parts.append("")
        data_parts.append("=== 对比期分产品类型 ===")
        try:
            cmp_breakdown = await asyncio.to_thread(
                _fetch_breakdown_text, params, cmp_start, cmp_end, "对比期"
            )
            data_parts.append(cmp_breakdown)
        except Exception as exc:
            logger.warning("Comparison breakdown query failed: %s", exc)
            data_parts.append(f"  (分产品数据查询异常: {exc})")

    real_data = "\n".join(data_parts)
    logger.info("Analyze data context:\n%s", real_data)

    system_prompt = (
        "你是一个严谨的外汇交易数据分析助手。\n\n"
        "规则：\n"
        "1. 只根据下面提供的真实数据进行分析，不要编造任何数字。\n"
        "2. 如果你无法从现有数据中确定变化原因，直接说明缺少什么数据导致无法分析。\n"
        "3. 分析要简洁专业，控制在 200 字以内。\n"
        "4. 如果数据表明某类产品变化显著，可以指出。\n\n"
        "真实数据:\n"
        f"{real_data}"
    )

    user_prompt = f"用户问题: {text}"

    try:
        result_text = await asyncio.to_thread(llm_chat, system_prompt, user_prompt)
    except Exception as exc:
        logger.warning("LLM chat failed: %s", exc)
        result_text = None

    if not result_text:
        return JSONResponse(status_code=503, content={"error": "分析服务暂不可用，请稍后重试"})

    return {"summary": result_text}


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/api/health")
def health():
    return {"status": "ok"}