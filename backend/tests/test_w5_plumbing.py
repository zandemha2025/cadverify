"""W5 flywheel plumbing — the loop from real quotes to the served cost path.

Pure / mocked (no DB, no engine, no network). Proves the four plumbing guarantees
the served moat depends on:

  1. **Honest gate.** ``recalibrate`` REFUSES — before the engine ever runs — when
     there are fewer than ``MIN_REAL_RECORDS`` real (non-stand-in) records. A
     calibration is emitted ONLY from sufficient REAL data.
  2. **Stand-in never counts.** A pile of stand-in records can NEVER satisfy the
     floor; only ``stand_in=False`` records do.
  3. **Ingest stores real.** ``ingest_record`` persists a real quote with
     ``stand_in=False`` (and honours an explicit stand-in flag) — no fabrication,
     no auto-labelling.
  4. **Durable round-trip.** A persisted bundle flows back through
     ``load_served_calibration`` after a (simulated) restart: a REAL bundle yields
     a MEASURED ``ResidualModel`` + a live ``Calibration``; a stand-in-only bundle
     yields an un-validated model and NO calibration; an uncalibrated org yields
     ``(None, None)``. Cross-tenant: org B never sees org A's calibration.

The served cost path (``routes.py`` /validate/cost, ``batch_tasks.py``) already
consumes ``load_served_calibration`` and binds ``options.residual_model`` from it
(that seam is asserted end-to-end in ``test_groundtruth_api.py`` on live PG); here
we prove the LOAD CONTRACT those consumers rely on.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.costing import calibration_store as cstore
from src.costing.confidence import confidence_interval
from src.costing.groundtruth import Calibration, GroundTruthRecord, Residual
from src.services import groundtruth_service as svc


# ── record + bundle builders ────────────────────────────────────────────────
def _rec(i: int, *, stand_in: bool, process: str = "sls") -> GroundTruthRecord:
    return GroundTruthRecord(
        part_id=f"part-{i:02d}.stl", process=process, quantity=100,
        actual_unit_cost_usd=30.0 + i, stand_in=stand_in,
        source=("real PO" if not stand_in else ""),
    )


def _real_bundle(org_id: str, process: str = "sls") -> cstore.CalibrationBundle:
    cal = Calibration(
        process_factors={process: 1.62}, global_factor=1.5,
        n_by_process={process: 6}, fitted_on="unit",
    )
    residuals = [
        Residual(part_id=f"p{i}", process=process, quantity=100, actual_usd=10.0,
                 baseline_usd=10.0 * (1 + se), corrected_usd=10.0 * (1 + se),
                 signed_err=se, abs_err=abs(se), stand_in=False)
        for i, se in enumerate([0.05, -0.1, 0.12, -0.03, 0.08])
    ]
    return cstore.CalibrationBundle(
        org_id=org_id, calibration=cal, residuals=residuals, from_real=True,
        n_records=5, n_real=5, n_standin=0, claim="VALIDATED within +/-12%",
    )


def _standin_bundle(org_id: str, process: str = "sls") -> cstore.CalibrationBundle:
    cal = Calibration(process_factors={process: 1.5}, global_factor=1.5,
                      n_by_process={process: 4}, fitted_on="unit")
    residuals = [
        Residual(part_id=f"s{i}", process=process, quantity=100, actual_usd=10.0,
                 baseline_usd=10.0 * (1 + se), corrected_usd=10.0 * (1 + se),
                 signed_err=se, abs_err=abs(se), stand_in=True)
        for i, se in enumerate([0.05, -0.1, 0.12, -0.03])
    ]
    return cstore.CalibrationBundle(
        org_id=org_id, calibration=cal, residuals=residuals, from_real=False,
        n_records=4, n_real=0, n_standin=4, claim="PENDING",
    )


# ── 1 + 2. recalibrate is honestly gated; stand-in never counts ─────────────
def test_recalibrate_refuses_below_min_real_records():
    """Below the floor => InsufficientGroundTruth, raised BEFORE any engine work
    (no parts_dir / cache touched), so the refusal is pure."""
    records = [_rec(i, stand_in=False) for i in range(svc.MIN_REAL_RECORDS - 1)]
    with pytest.raises(svc.InsufficientGroundTruth) as ei:
        svc.recalibrate_from_records("ORG_LOW", records)
    exc = ei.value
    assert exc.n_real == svc.MIN_REAL_RECORDS - 1
    assert exc.min_real == svc.MIN_REAL_RECORDS
    assert "refused" in str(exc).lower()


def test_standin_records_never_satisfy_the_floor():
    """A large stand-in pile plus too-few real records still REFUSES — synthetic
    data can shape a spread but can never earn a served calibration."""
    records = (
        [_rec(i, stand_in=True) for i in range(50)]                       # noise
        + [_rec(100 + i, stand_in=False) for i in range(svc.MIN_REAL_RECORDS - 1)]
    )
    with pytest.raises(svc.InsufficientGroundTruth) as ei:
        svc.recalibrate_from_records("ORG_MIX", records)
    # Only the REAL records are counted, never the 50 stand-ins.
    assert ei.value.n_real == svc.MIN_REAL_RECORDS - 1
    assert ei.value.n_records == 50 + svc.MIN_REAL_RECORDS - 1


def test_recalibrate_passes_gate_at_min_and_persists(monkeypatch):
    """At exactly MIN_REAL_RECORDS the gate opens: the loop runs and the bundle is
    persisted. run_loop + save_bundle are stubbed so this stays engine-free."""
    saved: dict = {}

    def _fake_run_loop(records, **kw):
        cal = Calibration(process_factors={"sls": 1.62}, global_factor=1.5,
                          n_by_process={"sls": 4}, fitted_on="stub")
        residuals = [
            Residual(part_id=f"p{i}", process="sls", quantity=100, actual_usd=10.0,
                     baseline_usd=10.0, corrected_usd=10.0,
                     signed_err=0.05, abs_err=0.05, stand_in=False)
            for i in range(5)
        ]
        he = SimpleNamespace(
            residuals=residuals, n_real=5, n_standin=0,
            metrics_real={"band_covers_80pct": 10.0, "n_parts": 5},
            claim="VALIDATED within +/-10%",
        )
        return SimpleNamespace(
            n_records=len(records), calibration=cal, heldout_eval=he,
            residual_model=SimpleNamespace(from_real=True), skipped=[],
        )

    monkeypatch.setattr(svc, "run_loop", _fake_run_loop)
    monkeypatch.setattr(svc.cstore, "save_bundle",
                        lambda b, store_dir=None: saved.setdefault("b", b) or "/tmp/x.json")

    records = [_rec(i, stand_in=False) for i in range(svc.MIN_REAL_RECORDS)]
    summary = svc.recalibrate_from_records("ORG_OK", records)

    assert summary["from_real"] is True
    assert summary["validated"] is True
    assert summary["n_real"] == 5
    assert saved["b"].org_id == "ORG_OK"       # the persisted bundle is org-stamped


# ── 3. ingest stores real (stand_in=False) without fabrication ──────────────
def _mock_session() -> MagicMock:
    s = MagicMock()
    s.execute = AsyncMock()
    s.flush = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_ingest_stores_real_record_stand_in_false():
    s = _mock_session()
    row = await svc.ingest_record(
        s, "ORG_A", 7,
        {"part_id": "widget.stl", "process": "sls", "quantity": 100,
         "actual_unit_cost_usd": 42.5, "source": "PO-1001"},
    )
    assert row.stand_in is False           # real by default — never auto-labelled
    assert row.org_id == "ORG_A"
    assert row.user_id == 7
    assert row.actual_unit_cost_usd == 42.5
    s.add.assert_called_once_with(row)
    s.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_honours_explicit_standin_flag():
    s = _mock_session()
    row = await svc.ingest_record(
        s, "ORG_A", None,
        {"part_id": "widget.stl", "process": "sls", "quantity": 100,
         "actual_unit_cost_usd": 42.5, "stand_in": True},
    )
    assert row.stand_in is True            # honoured exactly as declared


@pytest.mark.asyncio
async def test_ingest_rejects_non_positive_cost():
    s = _mock_session()
    with pytest.raises(ValueError):
        await svc.ingest_record(
            s, "ORG_A", 1,
            {"part_id": "bad.stl", "process": "sls", "quantity": 1,
             "actual_unit_cost_usd": 0},
        )
    s.add.assert_not_called()


# ── 4. durable round-trip through load_served_calibration ───────────────────
def test_real_bundle_round_trips_to_measured_served_calibration(tmp_path):
    """A persisted REAL bundle survives 'restart' and load_served_calibration
    returns a MEASURED ResidualModel + a live Calibration -> the served path would
    report a validated band."""
    store = str(tmp_path)
    cstore.save_bundle(_real_bundle("ORG_REAL"), store_dir=store)

    model, calibration = svc.load_served_calibration("ORG_REAL", store_dir=store)
    assert model is not None and model.from_real is True
    assert calibration is not None                     # real => point gets corrected
    assert calibration.factor_for("sls") == 1.62
    # the seam the ensemble/served path consumes: a validated empirical band.
    ci = confidence_interval(10.0, assumption_band_pct=40.0,
                             residual_provider=model, process="sls")
    assert ci.validated is True
    assert ci.method == "measured-residual"


def test_standin_bundle_serves_no_calibration_and_never_validates(tmp_path):
    store = str(tmp_path)
    cstore.save_bundle(_standin_bundle("ORG_STANDIN"), store_dir=store)

    model, calibration = svc.load_served_calibration("ORG_STANDIN", store_dir=store)
    assert model is not None and model.from_real is False
    assert calibration is None                          # stand-in => point uncorrected
    ci = confidence_interval(10.0, assumption_band_pct=40.0,
                             residual_provider=model, process="sls")
    assert ci.validated is False


def test_uncalibrated_org_serves_none_none(tmp_path):
    model, calibration = svc.load_served_calibration("NEVER", store_dir=str(tmp_path))
    assert model is None and calibration is None


def test_cross_tenant_calibration_is_never_served_to_another_org(tmp_path):
    """Org A calibrates; org B (no bundle of its own) must get (None, None) — A's
    real calibration never leaks across the tenant boundary."""
    store = str(tmp_path)
    cstore.save_bundle(_real_bundle("ORG_A"), store_dir=store)
    # B has its own stand-in bundle; it must not borrow A's real one.
    cstore.save_bundle(_standin_bundle("ORG_B"), store_dir=store)

    a_model, a_cal = svc.load_served_calibration("ORG_A", store_dir=store)
    assert a_model.from_real is True and a_cal is not None

    b_model, b_cal = svc.load_served_calibration("ORG_B", store_dir=store)
    assert b_model.from_real is False and b_cal is None   # B stays un-validated

    c_model, c_cal = svc.load_served_calibration("ORG_C", store_dir=store)
    assert c_model is None and c_cal is None              # a third org: nothing
