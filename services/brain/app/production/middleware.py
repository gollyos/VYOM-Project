from __future__ import annotations

import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..observability import correlation
from ..security.rate_limits import RateLimiter


class ProductionMiddleware(BaseHTTPMiddleware):
    """Correlation IDs on every request, remote-endpoint rate limiting,
    and body-size limits — the local API hardening layer."""

    def __init__(self, app, *, rate_limiter: RateLimiter | None = None, max_body_bytes: int = 1_000_000):
        super().__init__(app)
        self.rate_limiter = rate_limiter
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex[:16]}"
        trace_id = request.headers.get("x-trace-id") or f"trace_{uuid4().hex[:16]}"
        correlation.bind_request(request_id=request_id, trace_id=trace_id)
        request.state.request_id = request_id

        if self.rate_limiter is not None and request.url.path.startswith("/api/remote"):
            client = request.client.host if request.client else "unknown"
            allowed, retry_after = self.rate_limiter.check("remote_device", client)
            if not allowed:
                return JSONResponse(
                    {"detail": "Rate limit exceeded", "retry_after_seconds": round(retry_after, 1)},
                    status_code=429,
                    headers={"retry-after": str(int(retry_after) + 1), "x-request-id": request_id},
                )

        if request.method in ("POST", "PUT", "PATCH"):
            length_header = request.headers.get("content-length")
            if length_header and int(length_header) > self.max_body_bytes:
                return JSONResponse(
                    {"detail": f"Payload too large (>{self.max_body_bytes} bytes)"},
                    status_code=413, headers={"x-request-id": request_id},
                )

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            raise
        response.headers["x-request-id"] = request_id
        response.headers["x-trace-id"] = trace_id
        response.headers["x-response-time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response
