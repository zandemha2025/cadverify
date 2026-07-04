"""Tests for the Prometheus /metrics endpoint + core instrumentation.

Metrics are real counters/timings — these tests exercise the actual middleware
and helper hooks, then read the exposition back. They also assert the enterprise
guardrails: labels are the route TEMPLATE (never a raw path with a ULID), and the
/metrics payload carries no secret/PII substrings.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from main import app
from src.api.metrics_registry import PROMETHEUS_AVAILABLE, record_cost_decision

requires_prom = pytest.mark.skipif(
    not PROMETHEUS_AVAILABLE, reason="prometheus-client not installed"
)

# A ULID-shaped token we deliberately push through a request path to prove it
# never leaks into a metric label (cardinality/PII guard).
_FAKE_ULID = "01JZZZZZZZZZZZZZZZZZZZZZZZZ"


async def _get(path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def _sample(name: str, labels: dict) -> float | None:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value(name, labels)


@pytest.mark.asyncio
@requires_prom
async def test_metrics_endpoint_returns_prometheus_text():
    """GET /metrics -> 200 text/plain (version 0.0.4) with the core metric names."""
    resp = await _get("/metrics")
    assert resp.status_code == 200
    ctype = resp.headers["content-type"]
    assert "text/plain" in ctype
    assert "version=0.0.4" in ctype
    body = resp.text
    for name in (
        "cadverify_http_requests_total",
        "cadverify_http_request_duration_seconds",
        "cadverify_cost_decisions_total",
        "cadverify_analysis_duration_seconds",
    ):
        assert name in body


@pytest.mark.asyncio
@requires_prom
async def test_http_requests_counter_increments_with_template_label():
    """A request bumps cadverify_http_requests_total under the route TEMPLATE."""
    labels = {"method": "GET", "path_template": "/metrics", "status": "200"}
    before = _sample("cadverify_http_requests_total", labels) or 0.0
    await _get("/metrics")  # this scrape is itself a GET /metrics -> 200
    after = _sample("cadverify_http_requests_total", labels) or 0.0
    assert after >= before + 1.0


@pytest.mark.asyncio
@requires_prom
async def test_raw_ulid_path_never_becomes_a_label():
    """An unmatched ULID path must collapse to '__unmatched__', never leak the raw
    identifier into a label (cardinality + PII guard)."""
    await _get(f"/api/v1/does-not-exist/{_FAKE_ULID}")
    body = (await _get("/metrics")).text
    # The raw ULID must not appear anywhere in the exposition.
    assert _FAKE_ULID not in body
    # Unmatched requests are bucketed under a single fixed template.
    assert 'path_template="__unmatched__"' in body


@pytest.mark.asyncio
@requires_prom
async def test_cost_decision_counter_increments_with_outcome():
    """The cost-decision hook increments cadverify_cost_decisions_total{outcome}."""
    for outcome in ("ok", "geometry_invalid", "error"):
        labels = {"outcome": outcome}
        before = _sample("cadverify_cost_decisions_total", labels) or 0.0
        record_cost_decision(outcome)
        after = _sample("cadverify_cost_decisions_total", labels) or 0.0
        assert after == before + 1.0

    # An unknown outcome is clamped to "error" (fixed, PII-free label space).
    before = _sample("cadverify_cost_decisions_total", {"outcome": "error"}) or 0.0
    record_cost_decision("something-weird")
    after = _sample("cadverify_cost_decisions_total", {"outcome": "error"}) or 0.0
    assert after == before + 1.0


@pytest.mark.asyncio
@requires_prom
async def test_metrics_payload_has_no_secret_or_pii():
    """The /metrics output must not leak secrets or PII."""
    # Exercise several paths first so real samples exist.
    await _get("/health")
    await _get(f"/api/v1/cost-decisions/{_FAKE_ULID}")
    body = (await _get("/metrics")).text
    for needle in (
        "cv_live_",          # API key prefix
        "Authorization",     # auth header
        "SESSION_SECRET",    # secret env name
        "password",
        _FAKE_ULID,          # ULID / id
        ".stl",              # filename fragment
        ".step",
    ):
        assert needle not in body


@pytest.mark.asyncio
async def test_metrics_disabled_returns_404(monkeypatch):
    """METRICS_ENABLED=0 makes the endpoint 404 (documented off-switch)."""
    monkeypatch.setenv("METRICS_ENABLED", "0")
    resp = await _get("/metrics")
    assert resp.status_code == 404


def test_route_auth_guard_passes():
    """The CI route-auth guard still passes with /metrics on the public allowlist."""
    root = Path(__file__).resolve().parents[2]
    guard = root / "scripts" / "ci" / "check_route_auth.py"
    result = subprocess.run(
        [sys.executable, str(guard)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
