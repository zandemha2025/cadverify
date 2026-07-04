"""/metrics endpoint + request-timing middleware (Prometheus text exposition).

Auth model (deliberate): /metrics is UNAUTHENTICATED at the app layer because
Prometheus scrapers do not carry API keys — putting it behind require_api_key
would make it unscrapable. In production it MUST be scraped over a private
network / behind an ingress allowlist and never exposed to the public internet.
Existence of the endpoint is gated by METRICS_ENABLED (default on); set
METRICS_ENABLED=0 to return 404. Because it is intentionally public, it is also
listed in scripts/ci/check_route_auth.py's public-route allowlist so the CI
auth-coverage guard treats it as legitimately unauthenticated.

The payload is machine metrics only (counters/histograms with method /
path_template / status / outcome labels) — no filenames, user ids, ULIDs, or
CAD content — so it cannot leak secrets.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.api.metrics_registry import (
    PROMETHEUS_AVAILABLE,
    observe_http_request,
    render_latest,
)

router = APIRouter()

_TRUTHY = {"1", "true", "yes", "on"}


def _metrics_enabled() -> bool:
    return os.getenv("METRICS_ENABLED", "1").strip().lower() in _TRUTHY


def _resolve_path_template(request: Request) -> str:
    """Return the matched route TEMPLATE (e.g. ``/api/v1/validate/cost``), never
    the raw path.

    The router stamps the matched route onto ``scope["route"]`` during handling,
    so after ``call_next`` we read its ``path_format`` — the pattern with
    ``{param}`` placeholders. Using the template is what keeps the
    ``path_template`` label cardinality bounded: raw paths embed ULIDs /
    filenames and would spawn an unbounded number of time series (and leak those
    identifiers into metrics). Unmatched requests (404s, bot probes) have no
    route on the scope and collapse to a single ``__unmatched__`` label for the
    same reason.
    """
    path_format = getattr(request.scope.get("route"), "path_format", None)
    if isinstance(path_format, str) and path_format:
        return path_format
    return "__unmatched__"


class MetricsMiddleware(BaseHTTPMiddleware):
    """Time each request and record the request counter + latency histogram,
    labelled by matched route template + status.

    Overhead is a perf_counter pair plus a route rematch and two label lookups —
    negligible. Labels carry no PII (method / path_template / status only). When
    prometheus-client is absent this is a straight pass-through.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not PROMETHEUS_AVAILABLE:
            return await call_next(request)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            template = _resolve_path_template(request)
            observe_http_request(request.method, template, status, duration)


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus text exposition of the core CADVerify metrics."""
    if not _metrics_enabled():
        return Response(status_code=404)
    payload, content_type = render_latest()
    if payload is None:
        # prometheus-client not installed — honest 503 rather than an empty body.
        return Response(
            content="metrics unavailable: prometheus-client not installed",
            status_code=503,
            media_type="text/plain",
        )
    return Response(content=payload, media_type=content_type)
