"""Regression tests for the outer real-CAD evidence oracle."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prehuman" / "real_cad_corpus.py"
SPEC = importlib.util.spec_from_file_location("real_cad_corpus", SCRIPT)
assert SPEC and SPEC.loader
corpus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corpus)


def _case(case_id: str, bbox: list[float], volume: float) -> dict:
    return {
        "id": case_id,
        "status": "PASS",
        "geometry": {"bbox_mm": bbox, "volume_cm3": volume},
    }


def test_worker_pass_cannot_override_failed_outer_expectation():
    case = {
        "id": "mismatch",
        "source": "nist_mtc_assembly",
        "inner_path": "fixture.SLDASM",
        "family": "MTC",
        "schema": "native_solidworks",
        "cad_category": "native_assembly_control",
        "expected_outcome": "UNSUPPORTED_SUFFIX",
    }
    source = {"zip_sha256": "a" * 64}
    worker_result = {
        "status": "PASS",
        "outcome": "OK",
        "network_egress_blocked": True,
        "runtime_warnings": [],
    }

    result = corpus.finalize_case_result(case, source, b"cad", worker_result)

    assert result["worker_status"] == "PASS"
    assert result["status"] == "FAIL"
    assert "expected UNSUPPORTED_SUFFIX, got OK" in result["failures"]


def test_cross_representation_oracle_accepts_equivalent_geometry():
    members = [
        _case("a", [311.6, 222.7, 48.3], 503.52),
        _case("b", [311.6, 222.7, 48.3], 503.57),
        _case("c", [311.6, 222.7, 48.3], 503.28),
    ]
    result = corpus.geometry_equivalence(members, ["a", "b", "c"])
    assert result["status"] == "PASS"
    assert result["observed_max_relative_volume_delta"] < 0.002


def test_cross_representation_oracle_rejects_wrong_scale():
    members = [
        _case("a", [10.0, 20.0, 30.0], 100.0),
        _case("b", [254.0, 508.0, 762.0], 1_638_706.4),
    ]
    result = corpus.geometry_equivalence(members, ["a", "b"])
    assert result["status"] == "FAIL"
    assert any("bounding-box delta" in failure for failure in result["failures"])


def test_worker_timeout_preserves_bounded_diagnostic_output(monkeypatch):
    def timeout(*args, **kwargs):
        raise corpus.subprocess.TimeoutExpired(
            args[0], 90, output=b"partial result", stderr=b"x" * 20000 + b"blocked stack"
        )

    monkeypatch.setattr(corpus.subprocess, "run", timeout)
    result = corpus.run_worker(
        {"zip_path": "fixture.zip"},
        {"inner_path": "part.stp", "expected_outcome": "OK"},
    )
    assert result["outcome"] == "TIMEOUT"
    assert result["status"] == "FAIL"
    assert result["stdout_tail"] == "partial result"
    assert result["stderr_tail"].endswith("blocked stack")
    assert len(result["stderr_tail"]) <= 12000


def test_worker_stack_diagnostics_survive_result_and_interpreter_exit(tmp_path):
    archive = tmp_path / "control.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("control.SLDASM", b"unsupported native CAD control")
    # Preload the backend before starting the short diagnostic clock. A live
    # non-daemon thread then makes the real interpreter wait after the result.
    program = """
import importlib.util, sys, threading, time
from argparse import Namespace
from src.api import routes
from src import costing
spec = importlib.util.spec_from_file_location("corpus", sys.argv[1])
corpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus)
corpus.PER_CASE_TIMEOUT_SEC = 5.1
threading.Thread(target=time.sleep, args=(1.0,)).start()
raise SystemExit(corpus.run_worker_mode(Namespace(
    zip=sys.argv[2], inner="control.SLDASM", expected="UNSUPPORTED_SUFFIX"
)))
"""
    run = subprocess.run(
        [sys.executable, "-c", program, str(SCRIPT), str(archive)],
        cwd=SCRIPT.parents[2] / "backend",
        capture_output=True, text=True, timeout=15,
    )
    assert run.returncode == 0, run.stderr
    assert '"outcome": "UNSUPPORTED_SUFFIX"' in run.stdout
    assert "_shutdown" in run.stderr, "the diagnostic was disarmed before interpreter exit"
