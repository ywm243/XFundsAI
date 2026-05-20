"""Global error-handler middleware — unified JSON error responses + error_log persistence."""

import traceback
import threading

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Catch unhandled exceptions and return a consistent JSON envelope."""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            rid = getattr(request.state, "request_id", "")
            err_type = type(exc).__name__
            err_msg = str(exc)[:500]
            tb = traceback.format_exc()[:2000]

            def _log_error() -> None:
                try:
                    from backend.db.mysql_store import insert_error_log

                    insert_error_log(
                        rid, request.method, request.url.path,
                        err_type, err_msg, tb,
                    )
                except Exception:
                    pass

            t = threading.Thread(target=_log_error)
            t.daemon = True
            t.start()

            return JSONResponse(
                status_code=500,
                content={
                    "error": err_type,
                    "message": err_msg,
                    "request_id": rid,
                },
            )
