"""工具执行监控 — 包装工具调用，记录指标"""
import time
import threading
import logging

logger = logging.getLogger(__name__)


class ToolMonitor:
    @staticmethod
    def wrap(tool_name: str, fn, *args, **kwargs):
        t0 = time.monotonic()
        try:
            result = fn(*args, **kwargs)
            duration_ms = (time.monotonic() - t0) * 1000
            _log_tool_call(tool_name, duration_ms, True)
            return result
        except Exception as e:
            duration_ms = (time.monotonic() - t0) * 1000
            _log_tool_call(tool_name, duration_ms, False, type(e).__name__)
            raise

    @staticmethod
    async def awrap(tool_name: str, fn, *args, **kwargs):
        t0 = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            duration_ms = (time.monotonic() - t0) * 1000
            _log_tool_call(tool_name, duration_ms, True)
            return result
        except Exception as e:
            duration_ms = (time.monotonic() - t0) * 1000
            _log_tool_call(tool_name, duration_ms, False, type(e).__name__)
            raise

    @staticmethod
    def get_stats(tool_name: str = None, window_minutes: int = 60) -> dict:
        try:
            from backend.db.mysql_store import get_conn
            conn = get_conn()
            try:
                where = "created_at >= NOW() - INTERVAL %s MINUTE"
                params = [window_minutes]
                if tool_name:
                    where += " AND tool_name = %s"
                    params.append(tool_name)
                sql = f"""SELECT tool_name, COUNT(*) AS calls,
                                 AVG(duration_ms) AS avg_ms,
                                 SUM(CASE WHEN success THEN 0 ELSE 1 END) / COUNT(*) AS error_rate
                          FROM tool_calls_log
                          WHERE {where}
                          GROUP BY tool_name"""
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    return {"window_minutes": window_minutes, "stats": [
                        dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()
                    ]}
            finally:
                conn.close()
        except Exception:
            return {"window_minutes": window_minutes, "stats": []}


def _log_tool_call(tool_name: str, duration_ms: float, success: bool,
                   error_type: str = ""):
    def _write():
        try:
            from backend.db.mysql_store import get_conn
            conn = get_conn()
            try:
                sql = """INSERT INTO tool_calls_log
                         (tool_name, duration_ms, success, error_type)
                         VALUES (%s, %s, %s, %s)"""
                with conn.cursor() as cur:
                    cur.execute(sql, (tool_name, duration_ms, success, error_type))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
    t = threading.Thread(target=_write)
    t.daemon = True
    t.start()
