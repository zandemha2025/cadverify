"""Analogy-to-quote k-NN activation via the LIVE contract (pure, always runs).

Exercises the EXACT records+geometry contract the ``/validate/cost`` path feeds
into ``ensemble_estimate`` — but with the real ``groundtruth.GroundTruthRecord``
dataclass, so it also proves the new nullable geometry columns ride through the
``geometry_features`` property the analogy member reads.

Invariants (orchestration-moat.md §4/§6; honesty rails):
  * REAL records carrying geometry (same process) => the analogy member fires:
    ``has_real_member`` True, the combined POINT shifts toward the neighbours
    (BLUE), and the combined variance is <= the physics-only variance.
  * Records lacking geometry, OR too few real neighbours, OR only stand-in
    records => the analogy ABSTAINS => the band dict is BYTE-IDENTICAL to the
    no-records band.
  * ``validated`` never flips from the analogy path (only the measured residual
    path can), and stand-in records never contribute.

No engine call is needed for the analogy math; one procedural mesh builds the
physics band the analogy combines with.
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

from src.costing import EstimateOptions
from src.costing.analogy_estimator import DEFAULT_MIN_REAL_NEIGHBORS
from src.costing.ensemble import ensemble_estimate
from src.costing.groundtruth import GroundTruthRecord

PROC = "cnc_3axis"
QTY = 100


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


def _physics_band():
    result, mesh, feats = _analyze(trimesh.creation.box(extents=[40.0, 30.0, 25.0]))
    opts = EstimateOptions(quantities=[QTY], material_class="aluminum")
    base = ensemble_estimate(result, mesh, feats, opts, n_members=16)
    return result, mesh, feats, opts, base


def _query_geo():
    return {"volume_cm3": 21.0, "surface_area_cm2": 55.0,
            "max_bbox_mm": 44.0, "face_count": 14}


def _real_records(center_cost, *, n=6, stand_in=False, with_geometry=True):
    """n records near ``center_cost`` with (optionally) geometry attached."""
    recs = []
    for i in range(n):
        f = 1.0 + 0.03 * (i - n // 2)
        kw = {}
        if with_geometry:
            kw = dict(volume_cm3=18.0 + i, surface_area_cm2=52.0 + i,
                      max_bbox_mm=40.0 + i, face_count=10 + i)
        recs.append(GroundTruthRecord(
            part_id=f"gt{i}", process=PROC, quantity=QTY,
            actual_unit_cost_usd=round(center_cost * f, 2),
            stand_in=stand_in, source="PO-real" if not stand_in else "",
            **kw))
    return recs


# ── the geometry_features property (the new column path) ─────────────────────
def test_record_geometry_features_property():
    r = GroundTruthRecord(part_id="p", process=PROC, quantity=QTY,
                          actual_unit_cost_usd=100.0, stand_in=False,
                          volume_cm3=10.0, surface_area_cm2=30.0,
                          max_bbox_mm=40.0, face_count=500)
    assert r.geometry_features == {"volume_cm3": 10.0, "surface_area_cm2": 30.0,
                                   "max_bbox_mm": 40.0, "face_count": 500}
    # a record without geometry -> None -> analogy skips it
    r2 = GroundTruthRecord(part_id="p2", process=PROC, quantity=QTY,
                           actual_unit_cost_usd=100.0, stand_in=False)
    assert r2.geometry_features is None
    # geometry is NOT a dataclass field -> never enters to_dict / dedup
    assert "geometry_features" not in r.to_dict()
    assert r.to_dict()["volume_cm3"] == 10.0


# ── activation: real geometry-bearing neighbours shift the point (BLUE) ──────
def test_real_records_activate_and_shift_point_and_tighten():
    result, mesh, feats, opts, base = _physics_band()
    b = base.band(PROC, QTY)
    assert b is not None and b.std_usd > 0.0
    pt = b.point_usd

    # Neighbours centred well ABOVE the physics point, tight spread -> the BLUE
    # combine must pull the combined point upward, toward the neighbours.
    recs = _real_records(center_cost=pt * 1.4, n=6)
    ens = ensemble_estimate(result, mesh, feats, opts, n_members=16,
                            records=recs, geometry=_query_geo())
    band = ens.band(PROC, QTY)
    assert band is not None
    assert band.has_real_member is True
    assert band.n_real_neighbors >= DEFAULT_MIN_REAL_NEIGHBORS
    # point shifted toward the (higher) neighbours, but stays between the members
    assert band.combined_usd is not None
    assert pt < band.combined_usd <= pt * 1.4 + 1e-6
    # BLUE: combined variance <= the physics-only (assumption-spread) variance
    assert band.combined_variance_usd2 is not None
    assert band.combined_variance_usd2 <= b.std_usd ** 2 + 1e-9
    # band width can only tighten
    assert (band.p90_usd - band.p10_usd) <= (b.p90_usd - b.p10_usd) + 1e-9
    # honesty: real member surfaced but NEVER validated by the analogy path
    assert band.validated is False and ens.validated is False
    assert "measured" not in band.method
    assert {m["name"] for m in band.members} == {"physics", "analogy"}


# ── abstain byte-identity: no records ────────────────────────────────────────
def test_byte_identical_when_no_records():
    result, mesh, feats, opts, base = _physics_band()
    withq = ensemble_estimate(result, mesh, feats, opts, n_members=16,
                              records=[], geometry=_query_geo())
    assert base.to_dict() == withq.to_dict()


# ── abstain byte-identity: real records but NO geometry ──────────────────────
def test_byte_identical_when_records_lack_geometry():
    result, mesh, feats, opts, base = _physics_band()
    recs = _real_records(center_cost=200.0, n=8, with_geometry=False)
    withq = ensemble_estimate(result, mesh, feats, opts, n_members=16,
                              records=recs, geometry=_query_geo())
    assert base.to_dict() == withq.to_dict()


# ── abstain byte-identity: too few real neighbours ───────────────────────────
def test_byte_identical_when_too_few_real():
    result, mesh, feats, opts, base = _physics_band()
    recs = _real_records(center_cost=200.0, n=DEFAULT_MIN_REAL_NEIGHBORS - 1)
    withq = ensemble_estimate(result, mesh, feats, opts, n_members=16,
                              records=recs, geometry=_query_geo())
    assert base.to_dict() == withq.to_dict()


# ── stand-in never contributes (even with geometry + plenty of them) ─────────
def test_stand_in_records_never_contribute():
    result, mesh, feats, opts, base = _physics_band()
    recs = _real_records(center_cost=200.0, n=10, stand_in=True)
    assert all(r.geometry_features is not None for r in recs)  # geometry present
    withq = ensemble_estimate(result, mesh, feats, opts, n_members=16,
                              records=recs, geometry=_query_geo())
    band = withq.band(PROC, QTY)
    assert band.has_real_member is False
    assert base.to_dict() == withq.to_dict()
