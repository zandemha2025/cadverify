"""Request-ID middleware for correlation across logs, Sentry, and responses."""

from __future__ import annotations

import re
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]


# A client's X-Request-ID goes into the response header, structured logs and the
# Sentry scope, so only a short plain token is kept; anything else is replaced.
_CLIENT_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def request_id_for(supplied: str | None) -> str:
    """The client's id when it is at most 128 of ``A-Z a-z 0-9 . _ : -``, else a new UUID."""
    if supplied and _CLIENT_REQUEST_ID.fullmatch(supplied):
        return supplied
    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate or propagate X-Request-ID, bind to structlog + Sentry."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request_id_for(request.headers.get("X-Request-ID"))

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
