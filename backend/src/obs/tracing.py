"""Opt-in OpenTelemetry tracing for CADVerify.

Design contract (the founder audits this):

* **OFF by default.** Tracing is a no-op unless explicitly enabled via
  ``OTEL_TRACING_ENABLED`` in {1,true,yes,on} OR the mere presence of an
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` (a configured collector implies intent).
* **Zero overhead + zero import cost when off.** Importing this module never
  imports ``opentelemetry``. While disabled, :func:`span` returns a single
  shared ``contextlib.nullcontext`` and every helper is an ``if not _ENABLED:
  return`` fast-path — no spans are created, no context is touched, and the
  costed request path is byte-identical to a build without this module.
* **Real spans when on.** :func:`setup_tracing` builds an OTel
  ``TracerProvider`` bound to our OWN provider reference (never mutating the
  global tracer provider), auto-instruments the FastAPI app for incoming
  request spans, and selects an exporter:
    - an OTLP/HTTP exporter when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, else
    - a console exporter (so "enabled" always emits somewhere for local proof).
  Tests inject an in-memory exporter directly via ``span_exporter=``.

No new PII is introduced: span attributes carry only the request id and org id
that are already available in the request context (both are opaque identifiers,
not user content), plus non-identifying geometry/size counters.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from typing import Any, Optional

_TRUTHY = {"1", "true", "yes", "on"}

# ── Module state, set by setup_tracing() ──────────────────────────────────
# _ENABLED gates every hot-path helper with a single bool check. While False
# (the default) opentelemetry is never imported and span() hands back _NULL.
_ENABLED: bool = False
_provider: Any = None  # our TracerProvider (not the global one)
_tracer: Any = None  # our Tracer, obtained from _provider
_instrumented_app: Any = None  # the FastAPI app we instrumented (for teardown)

# One shared no-op context manager reused for every disabled span() call so the
# off-path allocates nothing. nullcontext is reentrant + reusable.
_NULL = contextlib.nullcontext()
logger = logging.getLogger("cadverify.tracing")


def tracing_enabled() -> bool:
    """True when tracing should be active in this process.

    Opt-in signal: ``OTEL_TRACING_ENABLED`` truthy, or a non-empty
    ``OTEL_EXPORTER_OTLP_ENDPOINT``. Read from the environment each call so the
    decision is explicit and testable; the runtime hot path uses the cached
    ``_ENABLED`` bool instead (set once by :func:`setup_tracing`).
    """
    if os.getenv("OTEL_TRACING_ENABLED", "").strip().lower() in _TRUTHY:
        return True
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


def is_active() -> bool:
    """True once :func:`setup_tracing` has actually wired up a live tracer."""
    return _ENABLED and _tracer is not None


def setup_tracing(
    app: Any = None,
    *,
    span_exporter: Any = None,
    force: bool = False,
    service_name: Optional[str] = None,
) -> bool:
    """Enable tracing for ``app`` if configured. Returns True when activated.

    Called once at startup from ``main.py``. When neither the env opt-in is set
    nor ``force``/``span_exporter`` is supplied, this returns immediately having
    imported nothing and changed nothing — the guarantee that an unconfigured
    deploy pays zero cost.

    Args:
        app: FastAPI app to auto-instrument for incoming-request spans.
        span_exporter: explicit exporter (tests pass an in-memory exporter);
            when given, tracing is activated regardless of env.
        force: activate regardless of env (used by tests/proof drivers).
        service_name: overrides ``OTEL_SERVICE_NAME`` / the default resource.
    """
    global _ENABLED, _provider, _tracer, _instrumented_app

    if not (force or span_exporter is not None or tracing_enabled()):
        return False

    # Heavy imports happen ONLY on the enabled path.
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )

    resource = Resource.create(
        {
            "service.name": (
                service_name
                or os.getenv("OTEL_SERVICE_NAME", "cadverify-api")
            ),
            "service.version": os.getenv("RELEASE", "dev"),
        }
    )
    provider = TracerProvider(resource=resource)

    # Exporter selection: explicit test exporter > OTLP endpoint > console.
    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    else:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if endpoint:
            # OTLP/HTTP exporter, batched (production export path). Imported
            # lazily so the OTLP/proto/grpc deps are only needed when actually
            # exporting to a collector.
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            )
        else:
            # Enabled without an endpoint => console exporter so spans are
            # always observable somewhere (local proof / dev).
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    # Auto-instrument incoming FastAPI requests against OUR provider (never the
    # global one), so the server span parents our manual stage spans.
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        # Force Starlette to rebuild its middleware stack on the next request so
        # the instrumentation's patched builder actually takes effect even if the
        # stack was already built (e.g. a prior request in the same process).
        try:
            app.middleware_stack = None
        except Exception:
            pass
        _instrumented_app = app

    _provider = provider
    _tracer = provider.get_tracer("cadverify")
    _ENABLED = True
    return True


def shutdown_tracing(timeout_seconds: float | None = None) -> bool:
    """Tear down tracing with one bounded provider shutdown.

    The provider's ``shutdown`` already flushes processors, so calling
    ``force_flush`` first only doubles the wait. The potentially blocking SDK
    call runs on a daemon thread and is bounded; ``main.lifespan`` invokes this
    function off the event loop as well.
    """
    global _ENABLED, _provider, _tracer, _instrumented_app
    if _instrumented_app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.uninstrument_app(_instrumented_app)
            # Reset the cached stack so subsequent (uninstrumented) requests
            # rebuild without the OTel middleware — keeps test isolation clean.
            _instrumented_app.middleware_stack = None
        except Exception:
            pass
        _instrumented_app = None
    provider = _provider
    _ENABLED = False
    _provider = None
    _tracer = None
    if provider is None:
        return True

    if timeout_seconds is None:
        try:
            timeout_seconds = float(os.getenv("OTEL_SHUTDOWN_TIMEOUT_SEC", "5"))
        except ValueError:
            timeout_seconds = 5.0
    timeout_seconds = max(0.1, timeout_seconds)

    done = threading.Event()

    def _shutdown() -> None:
        try:
            provider.shutdown()
        except Exception:
            logger.exception("OpenTelemetry provider shutdown failed")
        finally:
            done.set()

    threading.Thread(
        target=_shutdown,
        name="otel-shutdown",
        daemon=True,
    ).start()
    completed = done.wait(timeout_seconds)
    if not completed:
        logger.error(
            "OpenTelemetry provider shutdown exceeded %.1fs", timeout_seconds
        )
    return completed


def span(name: str, **attributes: Any):
    """Context manager for a manual span.

    No-op (returns the shared nullcontext, imports nothing) unless tracing is
    active. When active, starts a child span of the current context and stamps
    the given non-None attributes.
    """
    if not _ENABLED or _tracer is None:
        return _NULL
    return _real_span(name, attributes)


@contextlib.contextmanager
def _real_span(name: str, attributes: dict):
    with _tracer.start_as_current_span(name) as sp:
        for key, value in attributes.items():
            if value is not None:
                sp.set_attribute(key, value)
        yield sp


def set_attr(sp: Any, key: str, value: Any) -> None:
    """Set an attribute on a span returned by :func:`span` (no-op if None)."""
    if sp is None or value is None:
        return
    try:
        sp.set_attribute(key, value)
    except Exception:
        pass


def set_current_attributes(**attributes: Any) -> None:
    """Stamp attributes onto the currently-active span (e.g. the server span)."""
    if not _ENABLED:
        return
    from opentelemetry import trace

    sp = trace.get_current_span()
    for key, value in attributes.items():
        if value is not None:
            try:
                sp.set_attribute(key, value)
            except Exception:
                pass


# ── Cross-thread context propagation ──────────────────────────────────────
# The costed compute runs in a thread executor; OTel context lives in
# contextvars which do NOT cross into executor threads automatically. Capture
# the context on the event loop, attach it inside the worker so the DFM /
# should-cost spans nest under the server/compute span.


def capture_context() -> Any:
    """Snapshot the current OTel context (None when disabled)."""
    if not _ENABLED:
        return None
    from opentelemetry import context as _context

    return _context.get_current()


def attach_context(ctx: Any) -> Any:
    """Attach a captured context; returns a detach token (None when disabled)."""
    if not _ENABLED or ctx is None:
        return None
    from opentelemetry import context as _context

    return _context.attach(ctx)


def detach_context(token: Any) -> None:
    """Detach a token from :func:`attach_context` (no-op when None)."""
    if token is None:
        return
    from opentelemetry import context as _context

    try:
        _context.detach(token)
    except Exception:
        pass
