"""Ground-truth loop tests — the honesty rails are the moat, so they are asserted.

Two layers:
  * PURE (no engine, fast) — record store, split/no-leakage, tuner independence
    from held-out, stand-in exclusion from claimed-real metrics, the confidence
    interval fallback + stand-in-never-validates guarantee, zero network.
  * ENGINE-BACKED (skipped when the real STL batch is absent) — every estimate
    carries a CI, the CI narrows under a residual model, the unit_cost == Σ
    line-items invariant still holds, and the full stand-in loop RUNS and stays
    honest (PENDING, non-zero held-out error => no overfitting).
"""

from __future__ import annotations

import os
import socket

import pytest

from src.costing import confidence as conf
from src.costing import groundtruth as gt
from src.costing.groundtruth import (
    GroundTruthRecord, Prediction, IDENTITY_CALIBRATION,
    split_records, tune, evaluate, ResidualModel, make_standin_record,
)

PARTS_DIR = os.environ.get("CADVERIFY_PARTS_DIR")
if not PARTS_DIR:
    from src.costing.harness import ensure_fixture_parts_dir
    PARTS_DIR = ensure_fixture_parts_dir()
from src.costing.harness import has_sample_parts

requires_parts = pytest.mark.skipif(
    not has_sample_parts(PARTS_DIR),
    reason=f"real parts fixture batch not present: {PARTS_DIR}",
)


# ── helpers ─────────────────────────────────────────────────────────────────
def _mock_records(n_parts=10, processes=("sls", "cnc_3axis"), stand_in=True):
    recs = []
    for i in range(n_parts):
        for proc in processes:
            recs.append(make_standin_record(f"part_{i}.stl", proc, 100,
                                            baseline_usd=10.0 + i, shop=None))
            recs[-1].stand_in = stand_in
    return recs


def _mock_preds(records):
    """Reconstruct the baseline each stand-in record was built from (10 + part index)."""
    out = []
    for r in records:
        i = int(r.part_id.split("_")[1].split(".")[0])
        out.append(Prediction(r, baseline_usd=10.0 + i, ok=True))
    return out


# ── record store + stand-in defaults ────────────────────────────────────────
def test_standin_defaults_true_and_self_tags():
    r = GroundTruthRecord("p.stl", "sls", 100, 42.0)
    assert r.stand_in is True                      # fail-safe: synthetic until proven real
    assert "STAND-IN" in r.source.upper()          # self-documenting origin


def test_real_record_is_not_forced_to_standin_tag():
    r = GroundTruthRecord("p.stl", "sls", 100, 42.0, stand_in=False, source="PO #123")
    assert r.stand_in is False
    assert "STAND-IN" not in r.source.upper()


def test_record_store_roundtrip_and_dedup(tmp_path):
    p = str(tmp_path / "records.jsonl")
    gt.add_record(GroundTruthRecord("a.stl", "sls", 100, 10.0), p)
    gt.add_record(GroundTruthRecord("a.stl", "sls", 100, 99.0), p)   # same key -> replace
    gt.add_record(GroundTruthRecord("a.stl", "cnc_3axis", 100, 20.0), p)
    recs = gt.load_records(p)
    assert len(recs) == 2
    sls = next(r for r in recs if r.process == "sls")
    assert sls.actual_unit_cost_usd == 99.0        # last write wins


def test_bad_actual_cost_rejected():
    with pytest.raises(ValueError):
        GroundTruthRecord("p.stl", "sls", 100, 0.0)


# ── split: deterministic, disjoint by part, order-independent (NO LEAKAGE) ───
def test_split_disjoint_by_part_identity():
    recs = _mock_records(12)
    sp = split_records(recs, test_fraction=0.30, seed=1337)
    assert sp.tuning_part_ids.isdisjoint(sp.test_part_ids), "a part leaked across splits"
    assert sp.tuning and sp.test, "split degenerated"


def test_split_is_order_independent_and_deterministic():
    recs = _mock_records(12)
    a = split_records(recs, seed=1337)
    b = split_records(list(reversed(recs)), seed=1337)
    assert a.test_part_ids == b.test_part_ids
    assert a.tuning_part_ids == b.tuning_part_ids


def test_split_all_records_of_a_part_stay_together():
    recs = _mock_records(12, processes=("sls", "mjf", "cnc_3axis"))
    sp = split_records(recs)
    for pid in {r.part_id for r in recs}:
        sides = {("test" if r in sp.test else "tuning") for r in recs if r.part_id == pid}
        assert len(sides) == 1, f"{pid} straddled the split"


# ── the headline guarantee: tuning NEVER touches the held-out set ────────────
def test_tuning_never_touches_heldout():
    recs = _mock_records(14)
    sp = split_records(recs)
    tuning_preds = _mock_preds(sp.tuning)
    calib_before = tune(tuning_preds)

    # Corrupt every HELD-OUT record's actual cost by 10x and re-tune on the SAME
    # tuning split: the calibration must be byte-for-byte identical.
    for r in sp.test:
        r.actual_unit_cost_usd *= 10.0
    calib_after = tune(_mock_preds(sp.tuning))
    assert calib_before.to_dict() == calib_after.to_dict(), \
        "held-out data influenced the tuned parameters — leakage!"

    # And no held-out part id is among the parts the tuner fitted on.
    fitted_parts = {p.record.part_id for p in tuning_preds}
    assert fitted_parts.isdisjoint(sp.test_part_ids)


# ── stand-in is EXCLUDED from any claimed-real metric ────────────────────────
def test_standin_excluded_from_claimed_real_metric():
    recs = _mock_records(10, stand_in=True)
    sp = split_records(recs)
    calib = tune(_mock_preds(sp.tuning))
    ev = evaluate(_mock_preds(sp.test), calib, "held-out")
    assert ev.metrics_real is None, "stand-in records produced a claimed-real number"
    assert ev.metrics_all is not None, "stand-in should still be measurable (labelled)"
    assert "PENDING" in ev.claim and "STAND-IN" in ev.claim


def test_real_metric_counts_only_real_records():
    recs = _mock_records(10, stand_in=True)
    sp = split_records(recs)
    # mark exactly the records of two held-out parts as real
    real_parts = sorted(sp.test_part_ids)[:2]
    n_real_records = 0
    for r in sp.test:
        if r.part_id in real_parts:
            r.stand_in = False
            n_real_records += 1
    calib = tune(_mock_preds(sp.tuning))
    ev = evaluate(_mock_preds(sp.test), calib, "held-out")
    assert ev.metrics_real is not None
    assert ev.n_real == n_real_records
    assert ev.metrics_real["n_parts"] == len(real_parts)
    assert "VALIDATED" in ev.claim


# ── tuning actually improves held-out accuracy (and not to zero) ─────────────
def test_tuning_uplift_on_heldout_without_overfitting():
    recs = _mock_records(16, stand_in=True)
    sp = split_records(recs)
    calib = tune(_mock_preds(sp.tuning))
    tuned = evaluate(_mock_preds(sp.test), calib, "held-out")
    untuned = evaluate(_mock_preds(sp.test), IDENTITY_CALIBRATION, "held-out raw")
    assert tuned.metrics_all["mean_abs_pct"] < untuned.metrics_all["mean_abs_pct"], \
        "calibration did not reduce held-out error"
    assert tuned.metrics_all["mean_abs_pct"] > 0.5, \
        "held-out error collapsed to ~0 — that would smell of overfitting/leakage"


# ── ResidualModel: stand-in shapes spread but NEVER validates ────────────────
def test_residual_model_standin_never_validates():
    recs = _mock_records(10, stand_in=True)
    sp = split_records(recs)
    calib = tune(_mock_preds(sp.tuning))
    ev = evaluate(_mock_preds(sp.test), calib, "held-out")
    rm = ResidualModel(ev.residuals)
    assert rm.from_real is False
    ci = rm.interval(50.0, process="sls")
    assert ci.validated is False
    assert "STAND-IN" in ci.label.upper()


def test_residual_model_real_data_validates():
    recs = _mock_records(12, stand_in=True)
    sp = split_records(recs)
    for r in sp.test:
        r.stand_in = False                          # all held-out now real
    calib = tune(_mock_preds(sp.tuning))
    ev = evaluate(_mock_preds(sp.test), calib, "held-out")
    rm = ResidualModel(ev.residuals)
    assert rm.from_real is True
    ci = rm.interval(50.0, process="sls")
    assert ci.method == "measured-residual"
    assert ci.validated is True
    assert ci.low_usd < ci.point_usd < ci.high_usd


# ── confidence interval fallback behaviour ──────────────────────────────────
def test_ci_assumption_band_fallback_when_no_data():
    ci = conf.confidence_interval(100.0, assumption_band_pct=40.0)
    assert ci.method == "assumption-band"
    assert ci.validated is False
    assert ci.label == "assumption-based, not yet validated"
    assert ci.low_usd == 60.0 and ci.high_usd == 140.0


def test_ci_falls_back_below_min_residuals():
    prov = lambda p: ([0.5, 0.4], False, 2)         # n=2 < MIN_RESIDUALS
    ci = conf.confidence_interval(100.0, assumption_band_pct=40.0,
                                  residual_provider=prov, process="sls")
    assert ci.method == "assumption-band"


def test_ci_measured_interval_is_bias_corrected():
    # engine over-predicts ~60%; corrected centre should land near point/1.6
    prov = lambda p: ([0.6, 0.55, 0.62, 0.58], True, 4)
    ci = conf.confidence_interval(160.0, assumption_band_pct=40.0,
                                  residual_provider=prov, process="sls")
    assert ci.method == "measured-residual" and ci.validated is True
    assert abs(ci.point_usd - 100.0) < 6.0


def test_ci_basis_never_empty():
    with pytest.raises(ValueError):
        conf.ConfidenceInterval(1, 2, 1.5, 0.8, "x", False, 0, basis="  ", label="")


# ── zero network egress in the measurement path ─────────────────────────────
def test_zero_network_in_measurement_path():
    recs = _mock_records(10)
    sp = split_records(recs)
    real = socket.socket

    def _boom(*a, **k):
        raise AssertionError("network access attempted during ground-truth measurement")

    socket.socket = _boom
    try:
        calib = tune(_mock_preds(sp.tuning))
        ev = evaluate(_mock_preds(sp.test), calib, "held-out")
        rm = ResidualModel(ev.residuals)
        _ = rm.interval(20.0, process="sls")
    finally:
        socket.socket = real
    assert ev.metrics_all is not None


# ════════════════════════════════════════════════════════════════════════════
# ENGINE-BACKED (skipped without the real STL batch)
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def engine_part():
    from src.costing.cli import _run_engine
    from src.costing.harness import SAMPLE_PARTS
    for fname, _m in SAMPLE_PARTS:
        path = os.path.join(PARTS_DIR, fname)
        if os.path.isfile(path):
            return _run_engine(path)
    pytest.skip("no sample part available")


@requires_parts
def test_every_estimate_carries_a_confidence_interval(engine_part):
    from src.costing import estimate_decision, EstimateOptions
    result, mesh, feats = engine_part
    rep = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100, 1000]))
    assert rep.status == "OK" and rep.estimates
    for e in rep.estimates:
        ci = e.get("confidence")
        assert ci is not None, f"{e['process']} estimate has no confidence interval"
        for key in ("low_usd", "high_usd", "point_usd", "level", "method",
                    "validated", "n_samples", "basis", "label"):
            assert key in ci, f"CI missing {key}"
        # no ground truth bound -> assumption-band, explicitly NOT validated
        assert ci["method"] == "assumption-band"
        assert ci["validated"] is False
        assert ci["label"] == "assumption-based, not yet validated"
        assert ci["low_usd"] <= e["unit_cost_usd"] <= ci["high_usd"]


@requires_parts
def test_unit_cost_equals_sum_line_items_with_ci(engine_part):
    """Regression: adding the CI must not disturb unit_cost == Σ line_items (G3)."""
    from src.costing import estimate_decision, EstimateOptions
    result, mesh, feats = engine_part
    rep = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100, 1000]))
    for e in rep.estimates:
        assert abs(e["unit_cost_usd"] - round(sum(e["line_items"].values()), 2)) < 0.02


@requires_parts
def test_ci_narrows_to_measured_when_residual_model_bound(engine_part):
    """Binding a residual model flips the CI from assumption-band to measured."""
    from src.costing import estimate_decision, EstimateOptions
    result, mesh, feats = engine_part

    base = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    proc = base.estimates[0]["process"]

    # a residual model that says the engine over-predicts this process by ~50%
    class _RM:
        from_real = True

        def __call__(self, p):
            if p == proc:
                return [0.5, 0.45, 0.55, 0.5], True, 4
            return [0.5, 0.45, 0.55, 0.5], True, 4

    rep = estimate_decision(result, mesh, feats,
                            EstimateOptions(quantities=[100], residual_model=_RM()))
    ci = next(e["confidence"] for e in rep.estimates if e["process"] == proc)
    assert ci["method"] == "measured-residual"
    assert ci["validated"] is True
    assert ci["n_samples"] == 4
    # bias-corrected centre is pulled below the raw point estimate
    raw = next(e["unit_cost_usd"] for e in base.estimates if e["process"] == proc)
    assert ci["point_usd"] < raw


@requires_parts
def test_full_standin_loop_runs_and_stays_pending():
    """The whole loop runs on real geometry with STAND-IN data and is HONEST:
    measured held-out error is produced, but the claimed-real number is PENDING
    and the held-out error is non-zero (no overfitting / no fabrication)."""
    from src.costing.harness import SAMPLE_PARTS
    from src.costing.groundtruth import EngineCostCache, run_loop

    cache = EngineCostCache(PARTS_DIR)
    records = []
    used = 0
    for fname, _m in SAMPLE_PARTS:
        path = os.path.join(PARTS_DIR, fname)
        if not os.path.isfile(path):
            continue
        rep = cache._report(path, 100, None, "polymer", None)
        if rep.status != "OK":
            continue
        for proc in ("sls", "mjf", "fdm", "cnc_3axis"):
            ests = [e for e in rep.estimates if e["process"] == proc
                    and int(e["quantity"]) == 100]
            if ests:
                records.append(make_standin_record(fname, proc, 100,
                                                   ests[0]["unit_cost_usd"]))
        used += 1
        if used >= 6:
            break
    if len(records) < 6:
        pytest.skip("not enough costable sample parts for a loop")

    loop = run_loop(records, parts_dir=PARTS_DIR, cache=cache)
    # split is clean
    assert loop.split.tuning_part_ids.isdisjoint(loop.split.test_part_ids)
    # measured, not asserted, and PENDING because everything is stand-in
    assert loop.heldout_eval.metrics_real is None
    assert "PENDING" in loop.heldout_eval.claim
    if loop.heldout_eval.metrics_all is not None:
        assert loop.heldout_eval.metrics_all["mean_abs_pct"] > 0.5      # not fabricated to 0
    # report renders and flags the stand-in status
    md = gt.build_report(loop)
    assert "PENDING" in md and "STAND-IN" in md
