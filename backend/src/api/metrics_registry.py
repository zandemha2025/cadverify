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
    from prometheus_client import Counter, Gauge, Histogram, generate_latest

    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover
    Counter = Gauge = Histogram = None  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]
    PROMETHEUS_AVAILABLE = False


# Outcomes accepted by record_cost_decision(); anything else is coerced to
# "error" so a typo can never mint a new (unbounded) label value.
_VALID_COST_OUTCOMES = {"ok", "geometry_invalid", "error"}
_JOB_STATUSES = ("queued", "running", "done", "partial", "failed", "other")
_BATCH_STATUSES = ("pending", "processing", "completed", "failed", "cancelled", "other")
_BATCH_ITEM_STATUSES = ("pending", "queued", "processing", "completed", "failed", "skipped", "cancelled", "other")
_WEBHOOK_STATUSES = ("pending", "delivered", "failed", "other")


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
    JOBS_CURRENT = Gauge(
        "cadverify_jobs_current",
        "Current async jobs by bounded status bucket.",
        ["status"],
    )
    BATCHES_CURRENT = Gauge(
        "cadverify_batches_current",
        "Current batches by bounded status bucket.",
        ["status"],
    )
    BATCH_ITEMS_CURRENT = Gauge(
        "cadverify_batch_items_current",
        "Current batch items by bounded status bucket.",
        ["status"],
    )
    WEBHOOK_DELIVERIES_CURRENT = Gauge(
        "cadverify_webhook_deliveries_current",
        "Current webhook deliveries by bounded status bucket.",
        ["status"],
    )
    ASYNC_WORKER_UP = Gauge(
        "cadverify_async_worker_up",
        "1 when Redis heartbeat confirms an arq worker is alive, otherwise 0.",
    )
    BATCHES_STALE_HEARTBEAT_CURRENT = Gauge(
        "cadverify_batches_stale_heartbeat_current",
        "Active batches whose heartbeat is beyond the configured stale threshold.",
    )
    WEBHOOK_RETRIES_DUE_CURRENT = Gauge(
        "cadverify_webhook_retries_due_current",
        "Webhook deliveries whose scheduled retry time is due.",
    )
    ORPHAN_SWEEPS_TOTAL = Counter(
        "cadverify_orphan_sweeps_total",
        "Total batches reaped by the orphan sweeper.",
    )
else:  # pragma: no cover - only when prometheus-client is absent
    HTTP_REQUESTS_TOTAL = None
    HTTP_REQUEST_DURATION_SECONDS = None
    COST_DECISIONS_TOTAL = None
    ANALYSIS_DURATION_SECONDS = None
    JOBS_CURRENT = None
    BATCHES_CURRENT = None
    BATCH_ITEMS_CURRENT = None
    WEBHOOK_DELIVERIES_CURRENT = None
    ASYNC_WORKER_UP = None
    BATCHES_STALE_HEARTBEAT_CURRENT = None
    WEBHOOK_RETRIES_DUE_CURRENT = None
    ORPHAN_SWEEPS_TOTAL = None


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


def _bounded_status_counts(counts: dict, allowed: tuple[str, ...]) -> dict[str, int]:
    allowed_set = set(allowed)
    out = {status: 0 for status in allowed}
    for raw_status, raw_count in (counts or {}).items():
        status = str(raw_status)
        bucket = status if status in allowed_set else "other"
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            count = 0
        out[bucket] = out.get(bucket, 0) + max(0, count)
    return out


def _set_status_gauge(gauge, counts: dict, allowed: tuple[str, ...]) -> None:
    for status, count in _bounded_status_counts(counts, allowed).items():
        gauge.labels(status=status).set(count)


def update_queue_metrics(summary: dict) -> None:
    """Refresh queue/worker gauges from a PII-free ops summary."""
    if not PROMETHEUS_AVAILABLE:
        return

    _set_status_gauge(
        JOBS_CURRENT,
        summary.get("jobs", {}).get("status_counts", {}),
        _JOB_STATUSES,
    )
    _set_status_gauge(
        BATCHES_CURRENT,
        summary.get("batches", {}).get("status_counts", {}),
        _BATCH_STATUSES,
    )
    _set_status_gauge(
        BATCH_ITEMS_CURRENT,
        summary.get("batch_items", {}).get("status_counts", {}),
        _BATCH_ITEM_STATUSES,
    )
    _set_status_gauge(
        WEBHOOK_DELIVERIES_CURRENT,
        summary.get("webhooks", {}).get("status_counts", {}),
        _WEBHOOK_STATUSES,
    )
    ASYNC_WORKER_UP.set(1 if summary.get("async", {}).get("worker") == "ok" else 0)
    BATCHES_STALE_HEARTBEAT_CURRENT.set(
        int(summary.get("batches", {}).get("stale_heartbeat_count") or 0)
    )
    WEBHOOK_RETRIES_DUE_CURRENT.set(
        int(summary.get("webhooks", {}).get("retry_due_count") or 0)
    )


def record_orphan_sweep(reaped_count: int) -> None:
    """Increment orphan-sweep counter by the number of batches reaped."""
    if not PROMETHEUS_AVAILABLE or reaped_count <= 0:
        return
    ORPHAN_SWEEPS_TOTAL.inc(reaped_count)


def render_latest() -> tuple[bytes | None, str | None]:
    """Return (payload_bytes, content_type) for the text exposition, or
    (None, None) when prometheus-client is not installed."""
    if not PROMETHEUS_AVAILABLE:
        return None, None
    return generate_latest(), CONTENT_TYPE
