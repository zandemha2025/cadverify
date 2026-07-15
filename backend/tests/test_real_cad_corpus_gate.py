"""Regression tests for the outer real-CAD evidence oracle."""
from __future__ import annotations

import importlib.util
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
