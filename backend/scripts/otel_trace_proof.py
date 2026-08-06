"""Capture REAL OpenTelemetry spans from a REAL costed request.

Enables tracing on the live FastAPI app with an in-memory span exporter, drives
one genuine ``POST /api/v1/validate/cost/demo`` with the checked-in cube.step
asset through Starlette's TestClient, then prints every emitted span (name,
span/parent ids, duration, attributes) and a reconstructed parent/child tree.

Run:  cd backend && .venv/bin/python scripts/otel_trace_proof.py
The spans printed are the actual spans the app produced — nothing hand-written.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the backend package root importable regardless of cwd (mirrors pytest).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Deterministic, offline proof: no OTLP egress. We deliberately DO NOT set
# OTEL_TRACING_ENABLED before importing main, so the app imports with tracing
# OFF (single, byte-identical import path). We then activate tracing exactly
# once by passing an in-memory exporter to setup_tracing() below — this avoids
# double-instrumentation and keeps ALL spans (server + manual) in one provider.
os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
os.environ.pop("OTEL_TRACING_ENABLED", None)

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from starlette.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from src.obs import tracing  # noqa: E402


def _fmt_attrs(attrs) -> str:
    keep = {k: v for k, v in dict(attrs or {}).items() if k.startswith("cadverify.")}
    # Also surface the canonical http.* route attribute from auto-instrumentation.
    for k in ("http.method", "http.route", "http.status_code", "http.target"):
        if k in (attrs or {}):
            keep[k] = attrs[k]
    return ", ".join(f"{k}={v}" for k, v in keep.items())


def main_proof() -> str:
    exporter = InMemorySpanExporter()
    # Instrument the ALREADY-created app (imported with tracing off) + install the
    # in-memory exporter. force via span_exporter=.
    tracing.setup_tracing(main.app, span_exporter=exporter)
    assert tracing.is_active(), "tracing failed to activate"

    cube = Path(__file__).resolve().parent.parent / "tests" / "assets" / "cube.step"
    assert cube.exists(), f"missing asset {cube}"

    client = TestClient(main.app)
    with cube.open("rb") as fh:
        resp = client.post(
            "/api/v1/validate/cost/demo",
            files={"file": ("cube.step", fh, "application/octet-stream")},
            data={"qty": "50,5000", "material_class": "aluminum", "region": "US"},
            headers={"X-Request-ID": "otel-proof-0001"},
        )

    body = resp.json()
    spans = list(exporter.get_finished_spans())

    lines: list[str] = []
    lines.append("=== CADVerify OpenTelemetry trace proof ===")
    lines.append(
        "Real spans from a real POST /api/v1/validate/cost/demo (cube.step), "
        "in-memory exporter."
    )
    lines.append(f"Library: opentelemetry-sdk {_otel_version()} (real OTel, not a fallback)")
    lines.append(f"HTTP status: {resp.status_code}   decision status: {body.get('status')}")
    lines.append(f"Spans emitted: {len(spans)}")
    lines.append("")

    # Flat table (source of truth: the exporter's finished spans).
    lines.append("--- spans (flat) ---")
    for s in spans:
        ctx = s.get_span_context()
        parent = f"{s.parent.span_id:016x}" if s.parent else "(root)"
        dur_ms = (s.end_time - s.start_time) / 1e6
        lines.append(
            f"name={s.name!r} span={ctx.span_id:016x} parent={parent} "
            f"dur={dur_ms:.3f}ms"
        )
        a = _fmt_attrs(s.attributes)
        if a:
            lines.append(f"    attrs: {a}")
    lines.append("")

    # Reconstructed parent/child tree by span id.
    lines.append("--- trace tree (parent -> child, with durations) ---")
    by_parent: dict[int | None, list] = {}
    for s in spans:
        pid = s.parent.span_id if s.parent else None
        by_parent.setdefault(pid, []).append(s)

    def _walk(pid, depth):
        for s in sorted(by_parent.get(pid, []), key=lambda x: x.start_time):
            dur_ms = (s.end_time - s.start_time) / 1e6
            lines.append(f"{'  ' * depth}{s.name}  [{dur_ms:.3f}ms]")
            _walk(s.get_span_context().span_id, depth + 1)

    _walk(None, 0)

    tracing.shutdown_tracing()
    return "\n".join(lines) + "\n"


def _otel_version() -> str:
    try:
        from importlib.metadata import version

        return version("opentelemetry-sdk")
    except Exception:
        return "unknown"


if __name__ == "__main__":
    out = main_proof()
    print(out)
