"""Security response headers middleware (S6).

Pure-ASGI (not BaseHTTPMiddleware) so it injects headers into the
http.response.start message without buffering streaming bodies — the batch
CSV export streams, and BaseHTTPMiddleware would break that.

Off-switch: SECURITY_HEADERS_ENABLED=0 disables it (default on). The uvicorn
`server: uvicorn` banner is separately suppressed via --no-server-header in the
process command; here we also overwrite any Server header with a neutral value
so the tech stack is not advertised even when running under a bare ASGI server.
"""
from __future__ import annotations

import os

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Static, cheap to build once. HSTS is safe to always send: browsers ignore it
# over plain http, and every production origin is https (fly force_https).
SECURITY_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

_SERVER_VALUE = "CadVerify"


def security_headers_enabled() -> bool:
    return os.getenv("SECURITY_HEADERS_ENABLED", "1") != "0"


class SecurityHeadersMiddleware:
    """Attach a fixed set of hardening headers to every HTTP response."""

    def __init__(self, app: ASGIApp, enabled: bool | None = None) -> None:
        self.app = app
        self.enabled = security_headers_enabled() if enabled is None else enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in SECURITY_HEADERS.items():
                    headers[key] = value
                headers["Server"] = _SERVER_VALUE
            await send(message)

        await self.app(scope, receive, send_with_headers)
