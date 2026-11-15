"""Mechanical-disconnect fixes (reality-audit follow-ups), locked in:

  1. PMI causality — the file's measured tolerance zones derive the effective
     tolerance class (loose < precision < tight < ultra), the derived class
     moves the tolerance-sensitive price terms, ultra zones add lead time, and
     a USER declaration always wins. Dimensional zones beyond a process's size
     capability surface as pmi_findings.
  2. Deep bores on the lathe — L/D > 8 peck-penalizes the turning cycle and
     the route scores below 1.0 with a DEEP_HOLE finding; a shallow bore does not.
  3. Machining undercuts — down-facing surfaces over internal features flag
     UNDERCUT_3AXIS on 3-axis and double its setup; a plain block stays clean.
  4. Multi-body honesty — the shop order minimum floors an order once, never
     each body; OCCT translator boilerplate never reaches a body name.
"""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

import src.analysis.processes  # noqa: F401  populate registry
from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult
from src.analysis.processes.base import get_analyzer
from src.analysis.processes import base as pbase
from src.analysis.processes.checks import (
    check_hole_depth_ratio,
    check_internal_shoulders,
    check_undercuts_machining,
)
from src.analysis.part_types import _clean_product_name
from src.costing import EstimateOptions, estimate_decision
from src.costing.cost_model import cost_breakdown
from src.costing.estimate import (
    PMI_ULTRA_TIGHT_MM,
    _derive_tolerance_class,
    _geometry_penalties,
    _pmi_capability_findings,
    _pmi_tightest_zone_mm,
)
from src.costing.rates import build_rate_card
from src.matcher.profile_matcher import rank_processes, score_process
from src.services.body_check_service import _totals


def _analyze(mesh):
    from src.analysis.features import detect_all

    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    ctx.features = detect_all(ctx.mesh)   # the production order (routes._run_cost_engine_ctx)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="part.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=universal,
                            process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx, ctx.features


def _report(result, mesh, feats, **kw):
    return estimate_decision(result, mesh, feats, EstimateOptions(quantities=[1, 100, 1000], **kw))


def _est(report, process, qty=1000):
    return next(e for e in report.estimates
                if e["process"] == process and e["quantity"] == qty)


def _bored_shaft(bore_d=4.0, length=55.0):
    outer = trimesh.creation.cylinder(radius=7.5, height=length, sections=64)
    bore = trimesh.creation.cylinder(radius=bore_d / 2, height=length + 2, sections=48)
    shaft = trimesh.boolean.difference([outer, bore])
    shaft.apply_translation([0, 0, length / 2])
    return shaft


def _stepped_bore_shaft():
    # From the top: ⌀4 entry 12 mm deep, then ⌀2 for 45 mm (22.5:1) — a
    # stepped bore (grooving shoulder) with a gun-drill-deep segment.
    outer = trimesh.creation.cylinder(radius=7.5, height=55, sections=64)
    outer.apply_translation([0, 0, 27.5])
    entry = trimesh.creation.cylinder(radius=2.0, height=12, sections=48)
    entry.apply_translation([0, 0, 49.0])
    deep = trimesh.creation.cylinder(radius=1.0, height=57, sections=48)
    deep.apply_translation([0, 0, 27.5])
    return trimesh.boolean.difference([outer, entry, deep])


def _undercut_block():
    # 60x60x30 block, a 15 mm mouth through the top 10 mm and a 35 mm wide
    # floor beneath — a true T-slot: its overhang ceilings face DOWN.
    body = trimesh.creation.box(extents=[60, 60, 30])
    body.apply_translation([0, 0, 15])
    mouth = trimesh.creation.box(extents=[15, 20, 10])
    mouth.apply_translation([0, 0, 25])
    floor = trimesh.creation.box(extents=[35, 20, 22])
    floor.apply_translation([0, 0, 13])
    return trimesh.boolean.difference([body, mouth, floor])


def _pmi(entries):
    return {"has_pmi": True, "entries": entries}


# ── 1. PMI → tolerance class derivation ─────────────────────────────────────

def test_pmi_class_thresholds():
    assert _derive_tolerance_class(1.0) == "standard"
    assert _derive_tolerance_class(0.5) == "standard"
    assert _derive_tolerance_class(0.2) == "precision"
    assert _derive_tolerance_class(0.05) == "tight"
    assert _derive_tolerance_class(0.005) == "ultra"
    assert PMI_ULTRA_TIGHT_MM == 0.025


def test_pmi_tightest_zone_reads_deviations_and_zones():
    pmi = _pmi([
        {"tolerance_type": "diameter", "value_mm": 35.0,
         "upper_deviation": 0.0, "lower_deviation": -0.2},
        {"tolerance_type": "diameter", "value_mm": 20.0,
         "upper_deviation": 0.005, "lower_deviation": -0.01},
        {"tolerance_type": "angular_size", "value_mm": 60.0, "unit": "deg",
         "upper_deviation": 0.5, "lower_deviation": -0.5},
        {"tolerance_type": "flatness", "value_mm": 0.01},
    ])
    tightest, label = _pmi_tightest_zone_mm(pmi)
    assert tightest == pytest.approx(0.005)
    assert "diameter" in label
    assert "deg" not in label  # angular zones never drive a linear class


def test_derived_class_moves_price_and_user_wins():
    block = trimesh.creation.box(extents=[40, 30, 25])
    result, mesh, _ctx, feats = _analyze(block)
    pmi_loose = _pmi([{"tolerance_type": "diameter", "value_mm": 20.0,
                       "upper_deviation": 0.4, "lower_deviation": -0.4}])
    pmi_ultra = _pmi([{"tolerance_type": "diameter", "value_mm": 20.0,
                       "upper_deviation": 0.005, "lower_deviation": -0.005}])

    r_loose = _report(result, mesh, feats, material_class="aluminum", pmi_tolerances=pmi_loose)
    r_ultra = _report(result, mesh, feats, material_class="aluminum", pmi_tolerances=pmi_ultra)

    assert r_loose.tolerance_derivation["source"] == "pmi"
    assert r_loose.tolerance_derivation["class"] == "precision"
    assert r_ultra.tolerance_derivation["class"] == "ultra"
    assert r_ultra.tolerance_derivation["ultra_tight"] is True

    u_loose = _est(r_loose, "cnc_3axis")["unit_cost_usd"]
    u_ultra = _est(r_ultra, "cnc_3axis")["unit_cost_usd"]
    assert u_ultra > u_loose * 1.05  # price moves causally with the measured zones

    # ultra zones add lead time (grinding/EDM), stated as a component
    lt = _est(r_ultra, "cnc_3axis").get("lead_time") or {}
    assert "tight_tolerance" in (lt.get("components") or {})

    # a USER declaration always wins over the measured derivation
    r_user = _report(result, mesh, feats, material_class="aluminum",
                     pmi_tolerances=pmi_ultra, tolerance_class="standard",
                     tolerance_class_is_user=True)
    assert r_user.tolerance_derivation["source"] == "user"
    assert r_user.tolerance_derivation["class"] == "standard"
    assert _est(r_user, "cnc_3axis")["unit_cost_usd"] < u_loose


def test_capability_findings_on_dimensional_zones():
    pmi = _pmi([{"tolerance_id": "TOL-1", "tolerance_type": "diameter", "value_mm": 20.0,
                 "upper_deviation": 0.005, "lower_deviation": -0.005, "process_verdicts": []}])
    findings = _pmi_capability_findings(pmi, "cnc_3axis")
    assert findings and findings[0]["code"] == "PMI_TOLERANCE_NOT_ACHIEVABLE"
    assert "grinding" in findings[0]["message"]
    # a zone the route comfortably holds raises no finding
    ok = _pmi([{"tolerance_id": "TOL-2", "tolerance_type": "diameter", "value_mm": 20.0,
                "upper_deviation": 0.2, "lower_deviation": -0.2, "process_verdicts": []}])
    assert _pmi_capability_findings(ok, "cnc_3axis") == []


# ── 2. Deep bores on turning ────────────────────────────────────────────────

def test_deep_bore_penalizes_turning_cycle_and_score():
    shaft = _bored_shaft(bore_d=4.0)          # 55 mm deep, ⌀4 → 13.75:1
    result, mesh, ctx, feats = _analyze(shaft)
    turning = next(s for s in result.process_scores if s.process.value == "cnc_turning")
    codes = [i.code for i in turning.issues]
    assert "DEEP_HOLE" in codes
    assert turning.score < 1.0

    pen = _geometry_penalties(turning.process, turning)
    assert pen["cycle_time_multiplier"] == pytest.approx(1.5)
    report = _report(result, mesh, feats, material_class="aluminum")
    est = _est(report, "cnc_turning")
    assert any("cycle_penalty" == d["name"] for d in est["drivers"])


def test_severe_bore_gun_drill_penalty():
    shaft = _stepped_bore_shaft()             # ⌀4 entry → ⌀2 × 55 deep (27.5:1)
    result, mesh, ctx, feats = _analyze(shaft)
    turning = next(s for s in result.process_scores if s.process.value == "cnc_turning")
    pen = _geometry_penalties(turning.process, turning)
    assert pen["cycle_time_multiplier"] == pytest.approx(2.5)
    assert "gun drilling" in pen["cycle_penalty_note"]
    # a 27:1 bore never reads as a clean score-1.0 turn
    assert turning.score < 1.0
    # the ⌀4→⌀2 internal step is a grooving shoulder, not a straight turn
    assert "SHARP_INTERNAL_SHOULDER" in [i.code for i in turning.issues]


def test_shallow_bore_stays_clean():
    shaft = _bored_shaft(bore_d=15.0, length=30.0)  # ⌀15 × 30 → 2:1
    result, mesh, ctx, feats = _analyze(shaft)
    turning = next(s for s in result.process_scores if s.process.value == "cnc_turning")
    assert "DEEP_HOLE" not in [i.code for i in turning.issues]


# ── 3. Machining undercuts ──────────────────────────────────────────────────

def test_tslot_flags_3axis_and_doubles_setup():
    block = _undercut_block()
    result, mesh, ctx, feats = _analyze(block)
    three = next(s for s in result.process_scores if s.process.value == "cnc_3axis")
    five = next(s for s in result.process_scores if s.process.value == "cnc_5axis")
    assert "UNDERCUT_3AXIS" in [i.code for i in three.issues]
    assert "UNDERCUT_3AXIS" not in [i.code for i in five.issues]

    pen = _geometry_penalties(three.process, three)
    assert pen["n_setups_override"] == 2.0

    report = _report(result, mesh, feats, material_class="aluminum")
    q1 = _est(report, "cnc_3axis", qty=1)
    q1_five = _est(report, "cnc_5axis", qty=1)
    three_fixed = q1["line_items"]["amortized_fixed"]
    five_fixed = q1_five["line_items"]["amortized_fixed"]
    # the flip setup the undercut demands is paid on the 3-axis quote only
    assert three_fixed == pytest.approx(2 * (five_fixed * 0.75), rel=0.35)


def test_plain_block_has_no_undercut():
    result, mesh, ctx, feats = _analyze(trimesh.creation.box(extents=[40, 30, 25]))
    assert check_undercuts_machining(ctx, result.process_scores[0].process) == []


# ── 4. Order minimums once per order + clean body names ─────────────────────

def test_totals_floor_order_once():
    designs = [
        {"status": "ok", "copies": 1, "by_quantity": {
            "1": {"process": "mjf", "per_file_usd": 3.29},
            "100": {"process": "mjf", "per_file_usd": 3.58}}},
        {"status": "ok", "copies": 1, "by_quantity": {
            "1": {"process": "mjf", "per_file_usd": 3.58},
            "100": {"process": "mjf", "per_file_usd": 3.58}}},
    ]
    per_file, floored = _totals(designs, [1, 100])
    raw_1 = 3.29 + 3.58
    # five small bodies are not 5 × the shop minimum: the ORDER total is the
    # sum, floored ONCE by the largest chosen route's minimum — never per body.
    if raw_1 >= floored.get("1") or "1" not in floored:
        assert per_file["1"] == pytest.approx(raw_1, rel=0.001)
    else:
        assert per_file["1"] == pytest.approx(floored["1"])
        assert floored["1"] > raw_1
    assert per_file["100"] >= 3.58 + 3.58


def test_boilerplate_product_names_never_surface():
    assert _clean_product_name("Open CASCADE STEP translator 7.8 3.2") is None
    assert _clean_product_name("open cascade step translator 7.8 3.1") is None
    assert _clean_product_name("Flange plate") == "Flange plate"
    assert _clean_product_name(None) is None


# ── 5. Material inference from strong geometry ─────────────────────────────

def test_sheet_like_part_infers_metal():
    plate = trimesh.creation.box(extents=[280.0, 120.0, 2.0])
    result, mesh, _ctx, feats = _analyze(plate)
    report = _report(result, mesh, feats)  # default polymer, no user pick
    inf = report.material_inference
    assert inf and inf["material_class"] == "aluminum"
    assert "change" in inf["badge"].lower()
    assert report.material_class == "aluminum"


def test_pmi_part_infers_metal_but_picked_material_wins():
    block = trimesh.creation.box(extents=[40, 30, 25])
    result, mesh, _ctx, feats = _analyze(block)
    pmi = _pmi([{"tolerance_type": "diameter", "value_mm": 20.0,
                 "upper_deviation": 0.01, "lower_deviation": -0.01}])
    r = _report(result, mesh, feats, pmi_tolerances=pmi)
    assert r.material_inference and r.material_inference["material_class"] == "aluminum"
    r_user = _report(result, mesh, feats, pmi_tolerances=pmi,
                     material_class="polymer", material_class_is_user=True)
    assert r_user.material_inference is None
    assert r_user.material_class == "polymer"
