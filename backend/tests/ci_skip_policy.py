"""Protected CI requires every collected test to run, including native CAD tests."""

from __future__ import annotations

import os

import pytest


class _SkipPolicy:
    def __init__(self):
        self.skips: list[tuple[str, str]] = []

    def _record_skip(self, report):
        if report.skipped:
            finding = (report.nodeid, str(report.longrepr))
            if finding not in self.skips:
                self.skips.append(finding)

    def pytest_collectreport(self, report):
        self._record_skip(report)

    def pytest_runtest_logreport(self, report):
        self._record_skip(report)

    def pytest_sessionfinish(self, session, exitstatus):
        if not self.skips:
            return
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_sep("=", "UNEXPECTED SKIPS (protected CI policy)")
            for nodeid, reason in self.skips:
                reporter.write_line(f"{nodeid}: {reason}")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_configure(config):
    if os.getenv("CADVERIFY_ENFORCE_SKIP_POLICY") == "1":
        # A pytester child session must never clear its parent's findings.
        config.pluginmanager.register(_SkipPolicy(), "ci-no-skips")
