"""Per-check limits for a big file checked on the worker.

A web request's check runs under the process-wide limits: ``ANALYSIS_TIMEOUT_SEC``
(60 s), ``MAX_TRIANGLES`` (2 M) and ``MAX_UPLOAD_MB`` (100). A big file checked
on the worker from its stored upload (``src.jobs.stored_check_tasks``) needs a
budget sized to the file instead, without changing the limits of anything else
the same worker runs at the same time (batch items, catalog parts).

``larger_limits(...)`` sets them for the current task only (a ContextVar, so it
follows ``await`` and ``asyncio.to_thread`` and nothing else). The readers in
``src.api.routes``, ``src.api.upload_validation`` and ``src.parsers.parse_pool``
consult :func:`current` first; with nothing set they behave exactly as before.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class CheckLimits:
    budget_sec: float
    max_triangles: int
    max_bytes: int


_CURRENT: ContextVar[Optional[CheckLimits]] = ContextVar("cadverify_check_limits", default=None)


def current() -> Optional[CheckLimits]:
    return _CURRENT.get()


@contextmanager
def larger_limits(*, budget_sec: float, max_triangles: int, max_bytes: int) -> Iterator[CheckLimits]:
    limits = CheckLimits(float(budget_sec), int(max_triangles), int(max_bytes))
    token = _CURRENT.set(limits)
    try:
        yield limits
    finally:
        _CURRENT.reset(token)
