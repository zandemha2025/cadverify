"""Request-ID middleware for correlation across logs, Sentry, and responses."""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate or propagate X-Request-ID, bind to structlog + Sentry."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Bind to structlog context vars (picked up by merge_contextvars processor)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Tag Sentry scope if available
        if sentry_sdk is not None:
            sentry_sdk.set_tag("request_id", request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        # Clear contextvars after request completes
        structlog.contextvars.unbind_contextvars("request_id")
        return response
