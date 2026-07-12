"""Operational observability helpers (opt-in tracing).

The ``src.obs`` package holds cross-cutting operational instrumentation that is
*additive* and *opt-in*: importing it must never pull heavy dependencies onto
the hot path, and it must be a byte-identical no-op unless explicitly enabled.
"""
