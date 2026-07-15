"""Regression coverage for non-fatal structured-log output."""

from __future__ import annotations

import errno
import io
import json

import structlog

from src.obs.safe_logger import SafePrintLoggerFactory


class _RevokedStream(io.StringIO):
    """Model the EBADF write produced by a detached terminal descriptor."""

    def write(self, value: str) -> int:
        raise OSError(errno.EBADF, "Bad file descriptor")


def test_safe_print_logger_preserves_normal_output() -> None:
    stream = io.StringIO()
    logger = structlog.wrap_logger(
        SafePrintLoggerFactory(stream)(),
        processors=[structlog.processors.JSONRenderer()],
    )

    logger.info("cost_estimate", status="OK")

    assert json.loads(stream.getvalue()) == {
        "event": "cost_estimate",
        "status": "OK",
    }


def test_safe_print_logger_does_not_propagate_revoked_sink_error() -> None:
    logger = SafePrintLoggerFactory(_RevokedStream())()

    # A log sink is observability only: losing it must not turn a successful
    # should-cost calculation into an HTTP 500.
    assert logger.info('{"event":"cost_estimate","status":"OK"}') is None


def test_safe_print_logger_does_not_propagate_closed_sink_error() -> None:
    stream = io.StringIO()
    stream.close()
    logger = SafePrintLoggerFactory(stream)()

    assert logger.warning('{"event":"cost_timeout"}') is None
