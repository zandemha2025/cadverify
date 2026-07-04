"""Prometheus metric registry + instrumentation helpers (enterprise observability).

Real counters/timings only — every value here is a genuine measurement, never a
fabricated or placeholder number. Labels are deliberately low-cardinality and
PII-free: only ``method``, ``path_template`` (the matched route *pattern*, e.g.
``/api/v1/validate/cost`` — NEVER the raw request path), ``status`` and cost
``outcome``. Raw paths carry ULIDs / filenames; using them as labels would
create an unbounded number of time series (cardinality blow-up) AND leak
identifiers into the metrics surface. Because no filename, user id, ULID, or
CAD content ever becomes a label, the /metrics payload cannot leak secrets.

Import-guarded: if ``prometheus-client`` is not installed, ``PROMETHEUS_AVAILABLE``
is False and every helper below is a no-op, so the app still imports and serves
normally (the /metrics endpoint then returns 503 "metrics unavailable"). The
dependency is declared in backend/requirements.txt for production.
"""

from __future__ import annotations

# Classic Prometheus text exposition content type. Pinned explicitly (rather than
# using prometheus_client.CONTENT_TYPE_LATEST, which newer client releases bumped
# to version=1.0.0) so the endpoint advertises the widely-scraped 0.0.4 format.
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

try:  # pragma: no cover - import guard exercised only when the lib is absent
    from prometheus_client import Counter, Histogram, generate_latest

    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover
    Counter = Histogram = None  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]
    PROMETHEUS_AVAILABLE = False


# Outcomes accepted by record_cost_decision(); anything else is coerced to
# "error" so a typo can never mint a new (unbounded) label value.
_VALID_COST_OUTCOMES = {"ok", "geometry_invalid", "error"}


if PROMETHEUS_AVAILABLE:
    HTTP_REQUESTS_TOTAL = Counter(
        "cadverify_http_requests_total",
        "Total HTTP requests, labelled by method, matched route template, and status.",
        ["method", "path_template", "status"],
    )
    HTTP_REQUEST_DURATION_SECONDS = Histogram(
        "cadverify_http_request_duration_seconds",
        "HTTP request latency in seconds, labelled by method and matched route template.",
        ["method", "path_template"],
    )
    COST_DECISIONS_TOTAL = Counter(
        "cadverify_cost_decisions_total",
        "Should-cost / make-vs-buy decisions by outcome (ok|geometry_invalid|error).",
        ["outcome"],
    )
    ANALYSIS_DURATION_SECONDS = Histogram(
        "cadverify_analysis_duration_seconds",
        "Cost-decision compute duration in seconds (mesh parse + cost engine).",
    )
else:  # pragma: no cover - only when prometheus-client is absent
    HTTP_REQUESTS_TOTAL = None
    HTTP_REQUEST_DURATION_SECONDS = None
    COST_DECISIONS_TOTAL = None
    ANALYSIS_DURATION_SECONDS = None


def observe_http_request(
    method: str, path_template: str, status: int, duration_seconds: float
) -> None:
    """Increment the request counter + latency histogram for one request.

    ``path_template`` MUST be a route pattern (bounded set), never a raw path.
    No-op when prometheus-client is unavailable.
    """
    if not PROMETHEUS_AVAILABLE:
        return
    status_label = str(status)
    HTTP_REQUESTS_TOTAL.labels(
        method=method, path_template=path_template, status=status_label
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(
        method=method, path_template=path_template
    ).observe(duration_seconds)


def record_cost_decision(outcome: str) -> None:
    """Increment cadverify_cost_decisions_total{outcome}. No-op if lib absent.

    ``outcome`` is clamped to {ok, geometry_invalid, error} so the label space
    stays fixed and PII-free.
    """
    if not PROMETHEUS_AVAILABLE:
        return
    label = outcome if outcome in _VALID_COST_OUTCOMES else "error"
    COST_DECISIONS_TOTAL.labels(outcome=label).inc()


def observe_analysis_duration(duration_seconds: float) -> None:
    """Observe one cost-decision compute duration. No-op if lib absent."""
    if not PROMETHEUS_AVAILABLE:
        return
    ANALYSIS_DURATION_SECONDS.observe(duration_seconds)


def render_latest() -> tuple[bytes | None, str | None]:
    """Return (payload_bytes, content_type) for the text exposition, or
    (None, None) when prometheus-client is not installed."""
    if not PROMETHEUS_AVAILABLE:
        return None, None
    return generate_latest(), CONTENT_TYPE
