"""Analogy-to-quote k-NN as a REAL 2nd ensemble member + applied BLUE combine.

Pure/procedural (no engine, no I/O) for the analogy math, plus one procedural-mesh
test that the ensemble's physics-only path stays byte-identical when the analogy
member abstains and tightens when real quotes are supplied.

Invariants asserted (Moat P1, orchestration-moat.md §4/§6):
  * analogy_estimate ABSTAINS (None) below min_real real neighbours and when only
    stand-in records exist — it never fabricates from synthetic data.
  * with enough real neighbours: a value near the neighbour costs, finite variance,
    deterministic across runs.
  * inverse-variance combine: combined var <= min(member vars); value between them.
  * ensemble_estimate WITHOUT records (or abstaining analogy) == today's
    physics-only band, byte-for-byte (band dict equality).
  * ensemble_estimate WITH sufficient real records: members list len 2, tightened
    (<=) band width, has_real_member True, validated STILL False (no residual model).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult
from src.analysis.processes.base import get_analyzer
from src.analysis.processes import base as pbase
from src.matcher.profile_matcher import rank_processes, score_process
import src.analysis.processes  # noqa: F401  populate registry

from src.costing import EstimateOptions
from src.costing.analogy_estimator import (
    analogy_estimate, AnalogyEstimate, FEATURE_KEYS, DEFAULT_MIN_REAL_NEIGHBORS,
)
from src.costing.ensemble import ensemble_estimate, combine_inverse_variance


# ──────────────────────────────────────────────────────────────────────────
# In-memory record double: minimal fields analogy_estimate reads + attached geo.
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Rec:
    part_id: str
    process: str
    quantity: int
    actual_unit_cost_usd: float
    stand_in: bool = False
    geometry_features: Optional[dict] = None


def _geo(vol, area, bbox, faces):
    return {"volume_cm3": vol, "surface_area_cm2": area,
            "max_bbox_mm": bbox, "face_count": faces}


def _quotes(process="cnc_3axis", n=6, cost=100.0, standin=False):
    """n real (or stand-in) quotes spread over a geometric range."""
    out = []
    for i in range(n):
        f = 1.0 + 0.15 * i
        out.append(Rec(part_id=f"p{i}", process=process, quantity=100,
                       actual_unit_cost_usd=cost * f, stand_in=standin,
                       geometry_features=_geo(10 * f, 30 * f, 40 * f, 500 + 50 * i)))
    return out


# ── abstention ─────────────────────────────────────────────────────────────
def test_abstains_below_min_real():
    recs = _quotes(n=DEFAULT_MIN_REAL_NEIGHBORS - 1)
    q = _geo(12, 34, 44, 520)
    assert analogy_estimate("cnc_3axis", 100, q, recs) is None


def test_abstains_when_only_standin():
    recs = _quotes(n=8, standin=True)          # plenty, but all synthetic
    q = _geo(12, 34, 44, 520)
    assert analogy_estimate("cnc_3axis", 100, q, recs) is None


def test_abstains_without_query_geometry():
    recs = _quotes(n=8)
    assert analogy_estimate("cnc_3axis", 100, None, recs) is None


def test_abstains_wrong_process():
    recs = _quotes(process="sls", n=8)
    q = _geo(12, 34, 44, 520)
    assert analogy_estimate("cnc_3axis", 100, q, recs) is None


# ── genuine estimate ────────────────────────────────────────────────────────
def test_estimate_near_neighbours_and_finite_variance():
    recs = _quotes(n=8, cost=100.0)
    q = _geo(11, 33, 44, 520)                   # near the small end of the range
    est = analogy_estimate("cnc_3axis", 100, q, recs, k=5)
    assert isinstance(est, AnalogyEstimate)
    costs = [r.actual_unit_cost_usd for r in recs]
    assert min(costs) <= est.value_usd <= max(costs)
    assert est.variance_usd2 > 0.0 and est.variance_usd2 < float("inf")
    assert 1 <= est.n_used <= 8


def test_deterministic_across_runs():
    recs = _quotes(n=8)
    q = _geo(12, 34, 44, 520)
    a = analogy_estimate("cnc_3axis", 100, q, recs, k=5)
    b = analogy_estimate("cnc_3axis", 100, q, recs, k=5)
    assert a == b


def test_features_by_part_map_used():
    """Geometry can be supplied out-of-band via features_by_part."""
    recs = [Rec(f"p{i}", "cnc_3axis", 100, 100.0 + 5 * i) for i in range(8)]
    fmap = {f"p{i}": _geo(10 + i, 30 + i, 40 + i, 500 + i) for i in range(8)}
    q = _geo(12, 32, 42, 502)
    est = analogy_estimate("cnc_3axis", 100, q, recs, features_by_part=fmap)
    assert est is not None and est.value_usd > 0.0


# ── inverse-variance combine (the BLUE spine) ───────────────────────────────
def test_combine_variance_le_min_and_value_between():
    physics = (120.0, 900.0)      # (value, variance)
    recs = _quotes(n=8, cost=100.0)
    q = _geo(11, 33, 44, 520)
    est = analogy_estimate("cnc_3axis", 100, q, recs, k=5)
    assert est is not None
    blue = combine_inverse_variance([physics, (est.value_usd, est.variance_usd2)])
    assert blue.variance <= min(physics[1], est.variance_usd2) + 1e-9
    lo, hi = sorted([physics[0], est.value_usd])
    assert lo - 1e-9 <= blue.value <= hi + 1e-9


# ──────────────────────────────────────────────────────────────────────────
# ensemble_estimate wiring (procedural mesh, always runs in CI)
# ──────────────────────────────────────────────────────────────────────────
def _analyze(mesh):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="block.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=universal,
                            process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx.features


def _bulky_block():
    return trimesh.creation.box(extents=[40.0, 30.0, 25.0])


def _query_geo_for(band):
    """A plausible query feature vector; values only need to be positive & finite."""
    return _geo(20.0, 55.0, 40.0, 12)


def test_byte_identical_when_no_records():
    """No records -> analogy cannot fire -> band dict identical to physics-only."""
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=[100], material_class="aluminum")
    base = ensemble_estimate(result, mesh, feats, opts, n_members=16)
    withq = ensemble_estimate(result, mesh, feats, opts, n_members=16,
                              records=[], geometry=_geo(20, 55, 40, 12))
    assert base.to_dict() == withq.to_dict()


def test_byte_identical_when_analogy_abstains():
    """Real records exist but too few for the process -> abstain -> identical band."""
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=[100], material_class="aluminum")
    base = ensemble_estimate(result, mesh, feats, opts, n_members=16)
    too_few = _quotes(process="cnc_3axis", n=DEFAULT_MIN_REAL_NEIGHBORS - 1)
    withq = ensemble_estimate(result, mesh, feats, opts, n_members=16,
                              records=too_few, geometry=_geo(20, 55, 40, 12))
    assert base.to_dict() == withq.to_dict()


def test_tightens_and_surfaces_real_member_when_sufficient():
    result, mesh, feats = _analyze(_bulky_block())
    opts = EstimateOptions(quantities=[100], material_class="aluminum")
    base = ensemble_estimate(result, mesh, feats, opts, n_members=16)
    b_cnc = base.band("cnc_3axis", 100)
    assert b_cnc is not None and b_cnc.std_usd > 0.0

    # Build enough REAL cnc_3axis quotes near the engine's own point so the k-NN
    # can contribute (costs centred on the physics point, small spread).
    pt = b_cnc.point_usd
    recs = []
    for i in range(8):
        f = 1.0 + 0.05 * (i - 4)
        recs.append(Rec(part_id=f"cnc{i}", process="cnc_3axis", quantity=100,
                        actual_unit_cost_usd=pt * f, stand_in=False,
                        geometry_features=_geo(18 + i, 52 + i, 40 + i, 10 + i)))
    ens = ensemble_estimate(result, mesh, feats, opts, n_members=16,
                            records=recs, geometry=_geo(21, 55, 44, 14))
    band = ens.band("cnc_3axis", 100)
    assert band is not None
    # 1) two named members
    assert len(band.members) == 2
    assert {m["name"] for m in band.members} == {"physics", "analogy"}
    # 2) real-data member surfaced, but NOT validated (no residual model)
    assert band.has_real_member is True
    assert band.n_real_neighbors >= DEFAULT_MIN_REAL_NEIGHBORS
    assert band.validated is False
    assert ens.validated is False
    # 3) tightened band width (<=) vs physics-only
    base_w = b_cnc.p90_usd - b_cnc.p10_usd
    new_w = band.p90_usd - band.p10_usd
    assert new_w <= base_w + 1e-9
    assert new_w < base_w                       # strictly tighter with a 2nd member
    # 4) combined variance <= physics assumption-spread variance
    assert band.combined_variance_usd2 is not None
    assert band.combined_variance_usd2 <= b_cnc.std_usd ** 2 + 1e-9
    # 5) honest labels: no fabricated "measured"/"validated"
    assert "measured" not in band.method
    d = band.to_dict()
    assert d["has_real_member"] is True and d["validated"] is False
    assert len(d["members"]) == 2
