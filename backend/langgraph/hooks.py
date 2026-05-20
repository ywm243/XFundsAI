"""LangGraph 节点级钩子 — 执行前/后/错误记录"""
import time
import threading
import logging

logger = logging.getLogger(__name__)


class NodeHooks:
    @staticmethod
    def before_node(node_name: str, state: dict) -> dict:
        state["_node_start_time"] = time.monotonic()
        logger.debug(f"Node '{node_name}' started")
        return state

    @staticmethod
    def after_node(node_name: str, state: dict, result: dict) -> dict:
        duration_ms = (time.monotonic() - state.get("_node_start_time", time.monotonic())) * 1000
        logger.debug(f"Node '{node_name}' completed in {duration_ms:.0f}ms")

        def _log():
            try:
                from backend.db.mysql_store import get_conn
                conn = get_conn()
                sql = """INSERT INTO tool_calls_log (tool_name, duration_ms, success)
                         VALUES (%s, %s, TRUE)"""
                try:
                    with conn.cursor() as cur:
                        cur.execute(sql, (f"node:{node_name}", duration_ms))
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass
        t = threading.Thread(target=_log)
        t.daemon = True
        t.start()
        return result

    @staticmethod
    def on_error(node_name: str, state: dict, error: Exception) -> dict:
        errors = state.get("errors", [])
        errors.append({
            "node": node_name,
            "code": type(error).__name__,
            "message": str(error),
            "severity": "fatal" if isinstance(error, (ConnectionError, TimeoutError)) else "warning",
            "timestamp": time.time(),
        })
        state["errors"] = errors
        logger.error(f"Node '{node_name}' failed: {error}")
        return state
