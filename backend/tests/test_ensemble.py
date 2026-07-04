"""Unit tests for the assumption-ensemble uncertainty estimator (Moat P0).

Procedural meshes only (like test_costing_model.py) so they always run in CI.
Asserts the honesty + math invariants:
  * member 0 (unperturbed) == baseline estimate_decision unit cost (byte-identical)
  * band is ordered (p10<=p50<=p90), std>=0, and brackets the point when spread
  * inverse-variance combine: var <= min(v1,v2); equal-variance => mean
  * disagreement CoV increases when coefficient ranges widen
  * validated stays False and the band carries the assumption label (no "measured")
  * deterministic: two runs give identical output
"""

from __future__ import annotations

import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult
from src.analysis.processes.base import get_analyzer
from src.analysis.processes import base as pbase
from src.matcher.profile_matcher import rank_processes, score_process
import src.analysis.processes  # noqa: F401  populate registry

from src.costing import estimate_decision, EstimateOptions
from src.costing.ensemble import (
    ensemble_estimate, combine_inverse_variance, scale_ranges,
    UNCERTAIN_COEFFICIENTS, ASSUMPTION_LABEL, ensemble_enabled, COST_ENSEMBLE_ENABLED,
)


def _analyze(mesh):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="cube.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=universal,
                            process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx.features


def _bulky_block():
    return trimesh.creation.box(extents=[40.0, 30.0, 25.0])


# ──────────────────────────────────────────────────────────────────────────
def test_flag_default_off():
    """COST_ENSEMBLE_ENABLED defaults OFF: existing path is opt-in only."""
    import os
    assert COST_ENSEMBLE_ENABLED == "COST_ENSEMBLE_ENABLED"
    prev = os.environ.pop(COST_ENSEMBLE_ENABLED, None)
    try:
        assert ensemble_enabled() is False
        os.environ[COST_ENSEMBLE_ENABLED] = "1"
        assert ensemble_enabled() is True
    finally:
        os.environ.pop(COST_ENSEMBLE_ENABLED, None)
        if prev is not None:
            os.environ[COST_ENSEMBLE_ENABLED] = prev


def test_member0_byte_identical_to_baseline():
    """Point estimate == single-estimator baseline, byte-for-byte."""
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=[100])
    baseline = estimate_decision(result, mesh, feats, opts)
    ens = ensemble_estimate(result, mesh, feats, opts, n_members=16)
    base_by = {(e["process"], e["quantity"]): e["unit_cost_usd"]
               for e in baseline.estimates}
    assert ens.bands, "ensemble produced no bands"
    for b in ens.bands:
        assert b.point_usd == base_by[(b.process, b.quantity)], (
            f"{b.process}: point {b.point_usd} != baseline {base_by[(b.process, b.quantity)]}")


def test_band_ordered_and_brackets_point():
    """p10<=p50<=p90, std>=0, and the band brackets the point for a spread process."""
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=[100], material_class="aluminum")
    ens = ensemble_estimate(result, mesh, feats, opts, n_members=16)
    for b in ens.bands:
        assert b.p10_usd <= b.p50_usd <= b.p90_usd, f"{b.process} band mis-ordered"
        assert b.std_usd >= 0.0
        assert b.p10_usd <= b.point_usd <= b.p90_usd, f"{b.process} point not bracketed"
    # a rate-sensitive process must actually show spread (std > 0)
    cnc = ens.band("cnc_3axis", 100)
    assert cnc is not None
    assert cnc.std_usd > 0.0 and cnc.disagreement_cov > 0.0


def test_combine_inverse_variance():
    """var <= min(v1,v2); equal-variance combine == mean."""
    c = combine_inverse_variance([(10.0, 4.0), (12.0, 9.0)])
    assert c.variance <= min(4.0, 9.0) + 1e-12
    # closed form: v = 1/(1/4+1/9) = 36/13
    assert abs(c.variance - 36.0 / 13.0) < 1e-9
    assert 10.0 < c.value < 12.0
    # equal variance -> plain mean, variance halved
    eq = combine_inverse_variance([(10.0, 5.0), (20.0, 5.0)])
    assert abs(eq.value - 15.0) < 1e-9
    assert abs(eq.variance - 2.5) < 1e-9
    # three members -> variance strictly below the best single
    tri = combine_inverse_variance([(1.0, 2.0), (2.0, 2.0), (3.0, 2.0)])
    assert tri.variance < 2.0


def test_disagreement_widens_with_ranges():
    """Widening the coefficient ranges raises the disagreement metric."""
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=[100], material_class="aluminum")
    narrow = ensemble_estimate(result, mesh, feats, opts, n_members=16,
                               coefficients=UNCERTAIN_COEFFICIENTS)
    wide = ensemble_estimate(result, mesh, feats, opts, n_members=16,
                             coefficients=scale_ranges(UNCERTAIN_COEFFICIENTS, 2.0))
    n = narrow.band("cnc_3axis", 100)
    w = wide.band("cnc_3axis", 100)
    assert n is not None and w is not None
    assert w.disagreement_cov > n.disagreement_cov, (
        f"widening ranges must raise CoV: {n.disagreement_cov} -> {w.disagreement_cov}")


def test_validated_false_and_assumption_label():
    """No fabricated 'measured' claim: validated False, assumption label present."""
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=[100])
    ens = ensemble_estimate(result, mesh, feats, opts, n_members=16)
    assert ens.validated is False
    assert ens.method == "assumption-ensemble"
    assert ens.label == ASSUMPTION_LABEL
    for b in ens.bands:
        assert b.validated is False
        assert b.label == ASSUMPTION_LABEL
        assert "measured" not in b.method
        assert "not shop-validated" in b.label
        assert b.basis.strip()


def test_deterministic_reproducible():
    """Two runs give identical output (no wall-clock/global randomness)."""
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=[100, 1000])
    a = ensemble_estimate(result, mesh, feats, opts, n_members=16)
    b = ensemble_estimate(result, mesh, feats, opts, n_members=16)
    assert a.to_dict() == b.to_dict()


def test_options_not_mutated():
    """Ensemble must not mutate the caller's options.rate_overrides."""
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=[100])
    before = dict(opts.rate_overrides)
    ensemble_estimate(result, mesh, feats, opts, n_members=8)
    assert opts.rate_overrides == before


def test_backtest_gating_refuses_without_ground_truth():
    """Backtest REFUSES accuracy below the real-record gate; reports spread only."""
    from src.eval.backtest_ensemble import (
        backtest, decide_mode, MIN_BACKTEST_REAL, SPREAD_MODE, ACCURACY_MODE,
    )
    from src.costing.groundtruth import make_standin_record

    assert decide_mode(0) == SPREAD_MODE
    assert decide_mode(MIN_BACKTEST_REAL) == ACCURACY_MODE

    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=[100])
    bands = ensemble_estimate(result, mesh, feats, opts, n_members=8).bands

    # a few STAND-IN records (never count as real) => must refuse accuracy
    recs = [make_standin_record("cube.stl", "cnc_3axis", 100, 12.0)]
    res = backtest(recs, ensemble_bands_provider=lambda _r: bands)
    assert res.mode == SPREAD_MODE
    assert res.accuracy is None
    assert res.spread is not None and res.spread["n_bands"] == len(bands)
    assert "NOT a validated accuracy claim" in res.spread["label"]
