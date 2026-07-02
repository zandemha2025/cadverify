"""Unit tests for scripts/ci/check_pyright_baseline.py.

The pyright typecheck CI step is a regression ratchet (see that script's
docstring for why): it must fail when the error count exceeds the checked-in
baseline, pass (with a note) when the count improves, and pass silently when
unchanged. These tests exercise `main()` directly against synthetic
`pyright --outputjson`-shaped reports so the ratchet logic is covered without
needing pyright installed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).parent.parent / "scripts" / "ci" / "check_pyright_baseline.py"
)


def _load_module():
    assert _SCRIPT_PATH.exists(), f"script not found: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("check_pyright_baseline", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load_module()


def _write_report(tmp_path: Path, error_count: int) -> Path:
    report = tmp_path / "pyright-report.json"
    report.write_text(
        json.dumps(
            {
                "summary": {
                    "filesAnalyzed": 167,
                    "errorCount": error_count,
                    "warningCount": 3,
                    "informationCount": 0,
                    "timeInSec": 1.0,
                }
            }
        ),
        encoding="utf-8",
    )
    return report


def test_load_baseline_reads_real_baseline_file(mod):
    # The checked-in baseline must parse as a plain int (no trailing prose).
    baseline = mod.load_baseline()
    assert isinstance(baseline, int)
    assert baseline >= 0


def test_pass_when_count_equals_baseline(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "load_baseline", lambda: 127)
    report = _write_report(tmp_path, 127)
    assert mod.main(["check_pyright_baseline.py", str(report)]) == 0


def test_pass_when_count_improves(mod, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_baseline", lambda: 127)
    report = _write_report(tmp_path, 100)
    rc = mod.main(["check_pyright_baseline.py", str(report)])
    assert rc == 0
    assert "improved" in capsys.readouterr().out


def test_fail_when_count_regresses(mod, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_baseline", lambda: 127)
    report = _write_report(tmp_path, 128)
    rc = mod.main(["check_pyright_baseline.py", str(report)])
    assert rc == 1
    assert "regressed" in capsys.readouterr().out


def test_usage_error_on_missing_arg(mod):
    assert mod.main(["check_pyright_baseline.py"]) == 2
