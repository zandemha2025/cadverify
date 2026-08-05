"""Protected-CI policy: only three exact optional skips are permitted."""

from __future__ import annotations

import os

import pytest


EXPECTED_CI_SKIPS = {
    "tests/test_eval_harness.py::test_smoke_seed_is_one_part_per_key_in_real_corpus": (
        "real corpus manifest not present"
    ),
    "tests/test_step_ap242_parser.py::test_ap242_document_has_pmi_flag": (
        "OCP XDE not available"
    ),
    "tests/test_step_ap242_parser.py::test_ap214_fallback_no_pmi": (
        "OCP XDE not available"
    ),
}
_UNEXPECTED_CI_SKIPS: list[tuple[str, str]] = []


def is_expected_ci_skip(nodeid: str, reason: str) -> bool:
    expected_reason = EXPECTED_CI_SKIPS.get(nodeid)
    return expected_reason is not None and expected_reason in reason


def _record_skip(report) -> None:
    if os.getenv("CADVERIFY_ENFORCE_SKIP_POLICY") != "1" or not report.skipped:
        return
    reason = str(report.longrepr)
    if not is_expected_ci_skip(report.nodeid, reason):
        finding = (report.nodeid, reason)
        if finding not in _UNEXPECTED_CI_SKIPS:
            _UNEXPECTED_CI_SKIPS.append(finding)


def pytest_sessionstart(session):
    del session
    _UNEXPECTED_CI_SKIPS.clear()


def pytest_collectreport(report):
    """Catch module/import-time skips that never produce a runtest report."""
    _record_skip(report)


def pytest_runtest_logreport(report):
    """Catch setup/call-time skips for collected test items."""
    _record_skip(report)


def pytest_sessionfinish(session, exitstatus):
    del exitstatus
    if not _UNEXPECTED_CI_SKIPS:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", "UNEXPECTED SKIPS (protected CI policy)")
        for nodeid, reason in _UNEXPECTED_CI_SKIPS:
            reporter.write_line(f"{nodeid}: {reason}")
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    # pytester can run a nested session in-process; do not leak that session's
    # findings into its parent plugin manager.
    _UNEXPECTED_CI_SKIPS.clear()
