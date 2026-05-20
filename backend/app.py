"""FastAPI application — FX trade query service."""

import platform
if platform.system() == "Windows":
    import ctypes
    ctypes.windll.kernel32.SetDllDirectoryW(r"D:\soft\instantclient\instantclient_19_19")

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

from llm_parser.parser import rule_based_parse, _rule_confidence
from llm_parser.llm_client import llm_parse, llm_chat
from llm_parser.rules_engine import gatekeep, reload_rules, load_dimension_config
from llm_parser.prompt_builder import build_system_prompt, invalidate_cache
from db.query_builder import TradeQueryBuilder
from db.mysql_store import init_db, get_conn, _auto_migrate
from admin_routes import router as admin_router
from backend.pricing.routes import router as pricing_router, init_pricing_service
from backend.event_bus import bus
from backend.wiki.routes import router as wiki_router
from services.query_service import build_sql, execute_query_sync, fetch_breakdown_text
from services.result_formatter import (
    build_summary, build_chart_option, build_insights,
    merge_comparison_into_rows,
)
from services.context_inherit import inherit_params_from_context, inherit_dates_from_context
from backend.middleware.error_handler import ErrorHandlerMiddleware
from backend.middleware.timing import TimingMiddleware
from backend.middleware.request_id import RequestIDMiddleware

logger = logging.getLogger(__name__)

# Initialize store on startup (MySQL unavailable → log and continue)
try:
    init_db()
    _auto_migrate()
except Exception as exc:
    logger.warning("MySQL init skipped: %s (rules/memory will use defaults)", exc)

# Load dimension config from rules DB and inject into query builder
_dimension_config = load_dimension_config()
TradeQueryBuilder.configure_dimensions(_dimension_config.get("dimensions", {}))
logger.info("Dimension config loaded (%d dimensions)", len(_dimension_config.get("dimensions", {})))

# 初始化询报价服务
with open("backend/knowledge_base/semantic_rules.json", "r", encoding="utf-8") as _f:
    _rules = json.load(_f)
_pricing_cfg = _rules.get("pricing", {})
init_pricing_service(
    engine_url=os.getenv("PRICING_ENGINE_URL", ""),
    scenarios=_pricing_cfg.get("scenarios", {}),
    validity_minutes=_pricing_cfg.get("quote_validity_minutes", 5),
)

from smartbi_mcp.server import create_http_app, get_session_manager
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

# Middleware stack: outermost → innermost
app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIDMiddleware)

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
app.include_router(pricing_router)
app.include_router(wiki_router)

# ── Helper functions ──────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_RESULT_MAX_CHARS = 50000


def _write_audit_log(session_id: str, raw_input: str, parsed: dict,
                     sql: str | None, row_count: int, summary: str | None) -> None:
    """Persist query execution to audit_log table (fire-and-forget)."""
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO audit_log (request_id, session_id, raw_input, resolved_params,
                       sql_executed, result_rows, response_to_user)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (str(uuid.uuid4())[:8], session_id, raw_input,
                     json.dumps(parsed, ensure_ascii=False) if parsed else None,
                     sql, row_count, _safe_truncate(summary or "", 2000)),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Audit log write failed: %s", exc)


def _safe_truncate(text: str, max_chars: int = _RESULT_MAX_CHARS) -> str:
    """Truncate at a JSON-safe boundary, never mid-string."""
    if not text or len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_brace = truncated.rfind("}")
    if last_brace > 0:
        return truncated[: last_brace + 1]
    return truncated


def _compute_importance(user_query: str, parsed_params: dict | None = None) -> int:
    """Score a turn's importance from 1 (routine) to 5 (critical)."""
    score = 1
    if not parsed_params:
        return min(score, 5)

    if parsed_params.get("comparison"):
        score += 1
    if parsed_params.get("aggregate") or parsed_params.get("top_n"):
        score += 1
    if parsed_params.get("hedge_ratio"):
        score += 1
    filters = sum(1 for k in ("bank_name", "cust_name", "appid",
                               "special_states", "amount_filter", "lifecycle_status")
                  if parsed_params.get(k))
    if filters >= 2:
        score += 1
    if len(user_query) > 15:
        score += 1

    return min(score, 5)


# ── Parse + context helpers ─────────────────────────────────────────────────


async def _resolve_params(text: str, context: dict | None = None) -> dict:
    """Rule → LLM fallback → gatekeep pipeline, returns parsed params."""
    rule_parsed = rule_based_parse(text)
    confidence = _rule_confidence(text, rule_parsed)

    if confidence >= 0.8 or context:
        parsed = gatekeep(rule_parsed, text)
    else:
        system_prompt = build_system_prompt(context)
        llm_result = await asyncio.to_thread(llm_parse, text, system_prompt)
        if llm_result is not None:
            parsed = gatekeep(llm_result, text)
        else:
            parsed = gatekeep(rule_parsed, text)

    if context:
        inherited = inherit_params_from_context(context, parsed, user_text=text)
        if inherited:
            for k, v in inherited.items():
                if k not in parsed or not parsed.get(k):
                    parsed[k] = v
            logger.info("Inherited params: %s", {k: v for k, v in inherited.items() if v})

        dates = inherit_dates_from_context(context)
        if dates:
            if not parsed.get("date_start"):
                parsed["date_start"] = dates["date_start"]
            if not parsed.get("date_end"):
                parsed["date_end"] = dates["date_end"]

    logger.info("Parsed params: lifecycle_status=%s", parsed.get("lifecycle_status"))
    return parsed


def _ensure_dates_for_comparison(parsed: dict, context: dict | None) -> dict | None:
    """Fill in date_start/date_end for comparison queries. Returns None if dates unavailable."""
    if not parsed.get("comparison"):
        return parsed
    if parsed.get("date_start") and parsed.get("date_end"):
        return parsed

    if context:
        dates = inherit_dates_from_context(context)
        if dates:
            parsed["date_start"] = dates["date_start"]
            parsed["date_end"] = dates["date_end"]
            return parsed

    now = datetime.now()
    parsed["date_start"] = f"{now.year}-01-01"
    parsed["date_end"] = now.strftime("%Y-%m-%d")
    return parsed


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
            cur.execute("""
                SELECT s.id, s.agent_type, s.created_at, s.updated_at,
                       (SELECT t.user_query FROM turns t WHERE t.session_id = s.id ORDER BY t.turn_index ASC LIMIT 1) AS first_query,
                       (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id) AS turn_count
                FROM sessions s
                WHERE s.is_active = 1
                ORDER BY s.updated_at DESC LIMIT 50
            """)
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
    """解析自然语言为结构化参数（不执行 SQL）。"""
    body = await request.json()
    text = body.get("text", "")
    context = body.get("context")

    try:
        parsed = await _resolve_params(text, context)
        rule_parsed = rule_based_parse(text)
        confidence = _rule_confidence(text, rule_parsed)
        return {"params": parsed, "confidence": confidence}
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
        parsed = await _resolve_params(text, context)

        from agent.orchestrator import run_analysis
        agent_result = run_analysis(
            user_query=text,
            session_id=session_id,
            gatekeep_params=parsed,
        )

        return {
            "summary": agent_result.get("summary", ""),
            "chartOption": build_chart_option(parsed, [], [], None) if parsed else None,
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
            # Still inherit missing params from context (e.g. profit_type from previous turn)
            if context:
                inherited = inherit_params_from_context(context, parsed, user_text=text)
                if inherited:
                    for k, v in inherited.items():
                        if k not in parsed or not parsed.get(k):
                            parsed[k] = v
                dates = inherit_dates_from_context(context)
                if dates:
                    if not parsed.get("date_start"):
                        parsed["date_start"] = dates["date_start"]
                    if not parsed.get("date_end"):
                        parsed["date_end"] = dates["date_end"]
        else:
            parsed = await _resolve_params(text, context)

        parsed = _ensure_dates_for_comparison(parsed, context) or parsed

        if parsed.get("comparison") and not (parsed.get("date_start") and parsed.get("date_end")):
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

        sql = build_sql(parsed, date_start=parsed.get("date_start") or None, date_end=parsed.get("date_end") or None)

        cols, rows, comparison_data, cmp_rows, comparison_sql = await asyncio.to_thread(
            execute_query_sync, sql, parsed
        )

        if comparison_data and cmp_rows:
            cmp_label = comparison_data.get("label", "对比")
            cols, rows = merge_comparison_into_rows(rows, cmp_rows, cols, cmp_label)

    except Exception as exc:
        logger.exception("查询执行失败: %s", text)
        return JSONResponse(status_code=500, content={
            "sql": sql, "params": parsed,
            "columns": [], "rows": [], "row_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        })

    result = {
        "sql": sql,
        "comparison_sql": comparison_sql,
        "params": parsed,
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
        "comparison": comparison_data,
        "summary": build_summary(parsed, rows, cols, comparison_data),
        "chartOption": build_chart_option(parsed, rows, cols, comparison_data),
        "insights": build_insights(parsed, rows, cols, comparison_data, text),
        "validation_warnings": [],
        "sql_validated": True,
    }
    _write_audit_log(session_id, text, parsed, sql, len(rows), result.get("summary"))
    return result


# ── LangGraph orchestration endpoint ──────────────────────────────────────────

from langgraph.pipeline import build_main_graph
from backend.langgraph.checkpointer import MySqlCheckpointer
_langgraph_app = build_main_graph(checkpointer=MySqlCheckpointer())


@app.post("/api/chat")
async def api_chat(request: Request):
    """Run the LangGraph orchestration pipeline."""
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
    """Use LLM to analyze previous query results based on real data only."""
    text = body.get("text", "")
    previous_data = body.get("previous_data", {})

    comparison = previous_data.get("comparison", {})
    params = previous_data.get("params", {})

    if not params:
        return {"summary": "缺少查询参数，无法分析"}

    data_parts = []

    date_start = params.get("date_start", "")
    date_end = params.get("date_end", "")
    bank_name = params.get("bank_name", "") or ""
    dim = params.get("dimension", "bank")

    data_parts.append(f"查询期间: {date_start} ~ {date_end}")
    if bank_name:
        data_parts.append(f"机构: {bank_name}")
    data_parts.append(f"聚合维度: {dim}")

    data_parts.append("")
    data_parts.append("=== 当前期分产品类型 ===")
    try:
        current_breakdown = await asyncio.to_thread(
            fetch_breakdown_text, params, date_start, date_end, "当前期"
        )
        data_parts.append(current_breakdown)
    except Exception as exc:
        logger.warning("Breakdown query failed: %s", exc)
        data_parts.append(f"  (分产品数据查询异常: {exc})")

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

        data_parts.append("")
        data_parts.append("=== 对比期分产品类型 ===")
        try:
            cmp_breakdown = await asyncio.to_thread(
                fetch_breakdown_text, params, cmp_start, cmp_end, "对比期"
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


# ── Audit Log ─────────────────────────────────────────────────────────────────


@app.get("/api/audit-log")
def get_audit_log(session_id: str = "", limit: int = 50):
    """Return recent audit log entries, optionally filtered by session_id."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if session_id:
                cur.execute(
                    """SELECT id, request_id, session_id, raw_input, resolved_params,
                       sql_executed, result_rows, created_at
                       FROM audit_log WHERE session_id=%s
                       ORDER BY created_at DESC LIMIT %s""",
                    (session_id, limit),
                )
            else:
                cur.execute(
                    """SELECT id, request_id, session_id, raw_input, resolved_params,
                       sql_executed, result_rows, created_at
                       FROM audit_log ORDER BY created_at DESC LIMIT %s""",
                    (limit,),
                )
            rows = cur.fetchall()
            for r in rows:
                if isinstance(r.get("resolved_params"), str):
                    try:
                        r["resolved_params"] = json.loads(r["resolved_params"])
                    except (json.JSONDecodeError, TypeError):
                        pass
            return rows
    finally:
        conn.close()


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/api/health")
def health():
    return {"status": "ok"}
