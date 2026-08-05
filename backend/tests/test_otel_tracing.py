"""Tests for the opt-in OpenTelemetry tracing (src/obs/tracing.py).

These exercise the REAL tracer against the REAL costed path:

* When ENABLED with an in-memory exporter, a POST /api/v1/validate/cost/demo
  emits the server span plus the manual stage spans (parse -> compute ->
  dfm_analysis/should_cost -> serialize), correctly nested.
* When DISABLED (the default), the identical request works, raises nothing, and
  the tracer is inert (no provider, span() is the shared nullcontext, and
  importing the module has not activated anything).

A tiny procedurally-generated box STL keeps the cost engine fast/deterministic
so nothing binary is committed.
"""

from __future__ import annotations

import io

import pytest
import trimesh
from httpx import ASGITransport, AsyncClient

from main import app
from src.obs import tracing

try:
    import opentelemetry.sdk.trace  # noqa: F401

    _OTEL_AVAILABLE = True
except ImportError:  # OTel is an OPTIONAL dep (requirements-otel.txt)
    _OTEL_AVAILABLE = False

# The "enabled" tests need the optional OpenTelemetry SDK. When it is absent
# (default runtime / CI installs only requirements.txt) they skip cleanly — the
# disabled-path tests below still run and prove the zero-overhead default.
requires_otel = pytest.mark.skipif(
    not _OTEL_AVAILABLE,
    reason="opentelemetry-sdk not installed (optional; see requirements-otel.txt)",
)


def _tiny_stl_bytes() -> bytes:
    """A watertight ~12-triangle box STL (fast to parse + cost)."""
    mesh = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    return buf.getvalue()


async def _post_cost(client: AsyncClient):
    return await client.post(
        "/api/v1/validate/cost/demo",
        files={"file": ("box.stl", _tiny_stl_bytes(), "application/octet-stream")},
        data={"qty": "50,5000", "material_class": "aluminum", "region": "US"},
        headers={"X-Request-ID": "otel-test-req"},
    )


@pytest.fixture
def in_memory_tracing():
    """Activate tracing on the app with an in-memory exporter; tear down after."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    tracing.setup_tracing(app, span_exporter=exporter)
    try:
        yield exporter
    finally:
        tracing.shutdown_tracing()


@requires_otel
@pytest.mark.asyncio
async def test_spans_emitted_for_costed_path_when_enabled(in_memory_tracing):
    exporter = in_memory_tracing
    assert tracing.is_active()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post_cost(client)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "OK"

    spans = exporter.get_finished_spans()
    names = [s.name for s in spans]

    # The manual stage spans of the costed path are all present.
    for expected in (
        "cost.parse_mesh",
        "cost.compute",
        "cost.dfm_analysis",
        "cost.should_cost",
        "cost.serialize",
    ):
        assert expected in names, f"missing span {expected!r} in {names}"

    by_name = {s.name: s for s in spans}

    # Server span is the root and carries the request id (no new PII).
    server = next(s for s in spans if s.parent is None)
    assert server.attributes.get("cadverify.request_id") == "otel-test-req"

    # Nesting: parse/compute/serialize are children of the server span; the
    # executor-thread dfm/should_cost spans nest under cost.compute (proves the
    # cross-thread context propagation actually works).
    root_id = server.get_span_context().span_id
    assert by_name["cost.parse_mesh"].parent.span_id == root_id
    assert by_name["cost.compute"].parent.span_id == root_id
    assert by_name["cost.serialize"].parent.span_id == root_id
    compute_id = by_name["cost.compute"].get_span_context().span_id
    assert by_name["cost.dfm_analysis"].parent.span_id == compute_id
    assert by_name["cost.should_cost"].parent.span_id == compute_id

    # Real attributes captured off the real request.
    assert by_name["cost.parse_mesh"].attributes.get("cadverify.file.suffix") == ".stl"
    assert by_name["cost.should_cost"].attributes.get("cadverify.status") == "OK"

    # Durations are real, monotonic, and non-negative.
    for s in spans:
        assert s.end_time >= s.start_time


@pytest.mark.asyncio
async def test_no_spans_and_no_error_when_disabled():
    # Default module state: tracing never activated.
    assert tracing.is_active() is False
    # The off-path span() is the single shared nullcontext (zero allocation).
    assert tracing.span("anything") is tracing._NULL
    # Capture/attach are inert no-ops when off.
    assert tracing.capture_context() is None
    assert tracing.attach_context(object()) is None

    # The identical costed request still works with tracing off.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post_cost(client)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "OK"


def test_tracing_enabled_flag_reads_env(monkeypatch):
    monkeypatch.delenv("OTEL_TRACING_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert tracing.tracing_enabled() is False

    monkeypatch.setenv("OTEL_TRACING_ENABLED", "1")
    assert tracing.tracing_enabled() is True

    monkeypatch.setenv("OTEL_TRACING_ENABLED", "0")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    # Presence of an endpoint is itself an opt-in signal.
    assert tracing.tracing_enabled() is True


def test_setup_tracing_noop_when_unconfigured(monkeypatch):
    """Unconfigured setup_tracing() activates nothing and returns False."""
    monkeypatch.delenv("OTEL_TRACING_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert tracing.setup_tracing(None) is False
    assert tracing.is_active() is False
