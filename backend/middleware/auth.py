"""API Key 认证中间件"""
import os
import hashlib
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    WHITELIST = ["/api/health", "/docs", "/openapi.json", "/redoc"]

    async def dispatch(self, request: Request, call_next):
        if os.getenv("ENABLE_AUTH", "").lower() != "true":
            return await call_next(request)
        if request.url.path in self.WHITELIST:
            return await call_next(request)
        api_key = request.headers.get("X-API-Key") or \
                  request.query_params.get("api_key", "")
        if not api_key or not self._validate_key(api_key):
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing API key"},
            )
        request.state.api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return await call_next(request)

    def _validate_key(self, api_key: str) -> bool:
        try:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            from db.mysql_store import get_conn
            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT 1 FROM api_keys
                           WHERE key_hash = %s AND is_active = TRUE
                           AND (expires_at IS NULL OR expires_at > NOW())""",
                        (key_hash,)
                    )
                    result = cur.fetchone()
                return result is not None
            finally:
                conn.close()
        except Exception:
            return False
