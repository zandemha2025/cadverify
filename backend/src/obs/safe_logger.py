"""Structured logging primitives whose output failures are non-fatal.

Application work must not fail because its observability sink disappeared.  A
local service can outlive the terminal that launched it, leaving stdout with a
revoked descriptor.  ``structlog.PrintLogger`` propagates that write error, so
wrap only the final sink operation while preserving the existing JSON output.
"""

from __future__ import annotations

from typing import Any, TextIO

import structlog


class SafePrintLogger(structlog.PrintLogger):
    """A ``PrintLogger`` that treats sink I/O failures as dropped log events."""

    def msg(self, message: str) -> None:
        try:
            super().msg(message)
        except (OSError, ValueError):
            # OSError covers revoked/broken descriptors; ValueError covers a
            # stream that was explicitly closed.  Logging is best-effort and
            # must never change a manufacturing decision into an HTTP 500.
            return None

    log = debug = info = warn = warning = msg
    fatal = failure = err = error = critical = exception = msg


class SafePrintLoggerFactory:
    """Produce :class:`SafePrintLogger` instances for ``structlog``."""

    def __init__(self, file: TextIO | None = None):
        self._file = file

    def __call__(self, *args: Any) -> SafePrintLogger:
        return SafePrintLogger(self._file)
