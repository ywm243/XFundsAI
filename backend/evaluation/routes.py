"""评估 API — 质量指标查询"""
from fastapi import APIRouter, Query
from backend.db.mysql_store import get_conn, query_evaluation_metrics, query_token_usage

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/accuracy")
def get_accuracy(window: int = Query(24)):
    conn = get_conn()
    try:
        metrics = query_evaluation_metrics(window_hours=window)
        return {"window_hours": window, "metrics": metrics}
    finally:
        conn.close()


@router.get("/latency")
def get_latency(window: int = Query(24)):
    conn = get_conn()
    try:
        sql = """SELECT agent_type, AVG(total_duration_ms) AS avg_ms,
                        MAX(total_duration_ms) AS max_ms
                 FROM evaluation_records
                 WHERE created_at >= NOW() - INTERVAL %s HOUR
                 GROUP BY agent_type"""
        with conn.cursor() as cur:
            cur.execute(sql, (window,))
            rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        return {"window_hours": window, "latency": rows}
    finally:
        conn.close()


@router.get("/routing")
def get_routing(window: int = Query(24)):
    conn = get_conn()
    try:
        sql = """SELECT agent_type, COUNT(*) AS cnt
                 FROM evaluation_records
                 WHERE created_at >= NOW() - INTERVAL %s HOUR
                 GROUP BY agent_type"""
        with conn.cursor() as cur:
            cur.execute(sql, (window,))
            rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        return {"window_hours": window, "routing": rows}
    finally:
        conn.close()


@router.get("/token-usage")
def get_token_usage_route(window: int = Query(24)):
    conn = get_conn()
    try:
        rows = query_token_usage(window_hours=window)
        return {"window_hours": window, "usage": rows}
    finally:
        conn.close()


@router.get("/error-rate")
def get_error_rate(window: int = Query(24)):
    conn = get_conn()
    try:
        sql = """SELECT agent_type, COUNT(*) AS total,
                        SUM(CASE WHEN fatal_errors > 0 THEN 1 ELSE 0 END) AS errors
                 FROM evaluation_records
                 WHERE created_at >= NOW() - INTERVAL %s HOUR
                 GROUP BY agent_type"""
        with conn.cursor() as cur:
            cur.execute(sql, (window,))
            rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        return {"window_hours": window, "error_rate": rows}
    finally:
        conn.close()


@router.get("/wiki-impact")
def get_wiki_impact(window: int = Query(24)):
    conn = get_conn()
    try:
        sql = """SELECT wiki_hit, COUNT(*) AS cnt,
                        AVG(router_confidence) AS avg_router_conf,
                        AVG(parse_confidence) AS avg_parse_conf
                 FROM evaluation_records
                 WHERE created_at >= NOW() - INTERVAL %s HOUR
                 GROUP BY wiki_hit"""
        with conn.cursor() as cur:
            cur.execute(sql, (window,))
            rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        return {"window_hours": window, "wiki_impact": rows}
    finally:
        conn.close()
