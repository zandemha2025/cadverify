"""Unit round-trip for the W5 calibration bundle store (no DB, no engine).

Proves the persistence layer preserves the ground-truth loop's two honesty-
critical outputs across a save -> load cycle:

  * the tuned ``Calibration`` (per-process correction factors), and
  * the held-out residuals + their ``stand_in`` flags, so a REBUILT
    ``ResidualModel`` reports ``from_real`` / ``validated`` EXACTLY as the
    in-memory one did.

The store must not be able to launder a stand-in residual into a validated
claim: a stand-in-only bundle rebuilds to ``validated=False``; a real bundle to
``validated=True``.
"""
from __future__ import annotations

import os

from src.costing.calibration_store import (
    CalibrationBundle,
    bundle_path,
    delete_bundle,
    load_bundle,
    save_bundle,
)
from src.costing.confidence import confidence_interval
from src.costing.groundtruth import Calibration, Residual


def _res(process: str, se: float, stand_in: bool, i: int = 0) -> Residual:
    return Residual(
        part_id=f"p{i}", process=process, quantity=100, actual_usd=10.0,
        baseline_usd=10.0 * (1 + se), corrected_usd=10.0 * (1 + se),
        signed_err=se, abs_err=abs(se), stand_in=stand_in,
    )


def test_bundle_roundtrip_real_residuals_preserve_validated(tmp_path):
    store = str(tmp_path)
    cal = Calibration(
        process_factors={"sls": 1.62, "cnc_3axis": 0.88}, global_factor=1.2,
        n_by_process={"sls": 5, "cnc_3axis": 3}, fitted_on="unit",
    )
    residuals = [
        _res("sls", se, False, i)
        for i, se in enumerate([0.05, -0.1, 0.12, -0.03, 0.08])
    ]
    b = CalibrationBundle(
        org_id="ORG_R", calibration=cal, residuals=residuals, from_real=True,
        n_records=5, n_real=5, n_standin=0,
        heldout_metrics_real={"band_covers_80pct": 12.0, "n_parts": 5},
        claim="VALIDATED within +/-12%", fitted_on="unit",
    )
    path = save_bundle(b, store_dir=store)
    assert os.path.isfile(path)
    assert path == bundle_path("ORG_R", store)

    lb = load_bundle("ORG_R", store_dir=store)
    assert lb is not None
    # Calibration factors survive the round-trip (to_dict rounds to 4dp).
    assert lb.calibration.process_factors["sls"] == 1.62
    assert lb.calibration.factor_for("cnc_3axis") == 0.88
    assert lb.from_real is True
    assert lb.heldout_metrics_real == {"band_covers_80pct": 12.0, "n_parts": 5}

    # Rebuilt ResidualModel is MEASURED + validated (real, >= MIN_RESIDUALS).
    rm = lb.residual_model()
    assert rm.from_real is True
    ci = confidence_interval(
        10.0, assumption_band_pct=40.0, residual_provider=rm, process="sls"
    )
    assert ci.validated is True


def test_bundle_roundtrip_standin_never_validates(tmp_path):
    store = str(tmp_path)
    cal = Calibration(
        process_factors={"sls": 1.5}, global_factor=1.5,
        n_by_process={"sls": 4}, fitted_on="unit",
    )
    residuals = [
        _res("sls", se, True, i) for i, se in enumerate([0.05, -0.1, 0.12, -0.03])
    ]
    b = CalibrationBundle(
        org_id="ORG_S", calibration=cal, residuals=residuals, from_real=False,
        n_records=4, n_real=0, n_standin=4, claim="PENDING",
    )
    save_bundle(b, store_dir=store)

    lb = load_bundle("ORG_S", store_dir=store)
    assert lb.from_real is False
    rm = lb.residual_model()
    assert rm.from_real is False
    # A stand-in residual shapes the spread but NEVER validates the band.
    ci = confidence_interval(
        10.0, assumption_band_pct=40.0, residual_provider=rm, process="sls"
    )
    assert ci.validated is False


def test_missing_bundle_is_none_and_env_override(tmp_path, monkeypatch):
    assert load_bundle("NOPE", store_dir=str(tmp_path)) is None

    # No explicit store_dir -> resolved from CADVERIFY_CALIBRATION_DIR at call time.
    monkeypatch.setenv("CADVERIFY_CALIBRATION_DIR", str(tmp_path))
    cal = Calibration(global_factor=1.0, fitted_on="x")
    b = CalibrationBundle(
        org_id="ENVORG", calibration=cal, residuals=[], from_real=False
    )
    p = save_bundle(b)  # env-resolved dir
    assert str(tmp_path) in p
    assert load_bundle("ENVORG") is not None
    assert delete_bundle("ENVORG") is True
    assert load_bundle("ENVORG") is None
