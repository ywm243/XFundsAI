"""Timing middleware — log request duration to request_log table."""

import time
import threading

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class TimingMiddleware(BaseHTTPMiddleware):
    """Record elapsed time per request and persist asynchronously."""

    async def dispatch(self, request: Request, call_next):
        t0 = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - t0) * 1000
        rid = getattr(request.state, "request_id", "")

        t = threading.Thread(
            target=_write_request_log,
            args=(rid, request.method, request.url.path, response.status_code, duration_ms),
        )
        t.daemon = True
        t.start()
        return response


def _write_request_log(
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
) -> None:
    """Fire-and-forget insert into request_log."""
    try:
        from backend.db.mysql_store import insert_request_log

        insert_request_log(request_id, method, path, status_code, duration_ms)
    except Exception:
        pass
