"""Routing + sheet-metal cost regression (procedural — always runs in CI).

Locks in the Cost-Truth routing/physics fixes:
  * a thin constant-gauge flat plate routes to SHEET_METAL (not led by MJF),
    with the geometric reasoning surfaced;
  * a compact block does NOT (no over-eager sheet routing);
  * the sheet-metal cycle time is an explainable physics model (cut/bend/handle),
    not a magic constant, and Σ(line_items) == unit_cost holds for it;
  * check_bends no longer hard-fails a flat plate as a "sharp bend".
"""
from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult, ProcessType, Severity
from src.analysis.processes import base as pbase
from src.analysis.processes.base import get_analyzer
from src.analysis.processes.checks import check_bends
import src.analysis.processes  # noqa: F401  populate registry
from src.matcher.profile_matcher import rank_processes, score_process

from src.costing import estimate_decision, EstimateOptions


def _analyze(mesh):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="part.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=universal,
                            process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx, ctx.features


def _flat_plate():
    # 2 mm constant-gauge plate, 120 x 280 — the canonical sheet panel
    return trimesh.creation.box(extents=[280.0, 120.0, 2.0])


def _compact_block():
    return trimesh.creation.box(extents=[40.0, 30.0, 25.0])


def _est(report, process):
    return [e for e in report.estimates if e["process"] == process]


# ── the headline: a flat plate routes to sheet metal ────────────────────────
def test_flat_plate_routes_to_sheet_metal():
    result, mesh, _ctx, feats = _analyze(_flat_plate())
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100, 5000]))
    assert report.status == "OK"
    # geometric routing recognizes the sheet archetype + surfaces reasoning
    assert report.routing is not None
    assert report.routing["archetype"] == "sheet_panel"
    assert report.routing["recommended_process"] == "sheet_metal"
    assert report.routing["reasoning"].strip()
    # sheet metal is costed and is the cheapest make-now headline (not MJF)
    sheets = _est(report, "sheet_metal")
    assert sheets, "sheet metal must be costable for a flat plate"
    assert report.decision.make_now_process == "sheet_metal"
    # DFM-ready (the inverted bend check no longer hard-fails a flat plate)
    assert sheets[0]["dfm_verdict"] != "fail"


def test_sheet_cycle_is_explainable_and_sums():
    result, mesh, _ctx, feats = _analyze(_flat_plate())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    sheet = _est(report, "sheet_metal")[0]
    # Σ invariant (gate G3) holds for the new fabrication line
    assert abs(sheet["unit_cost_usd"] - round(sum(sheet["line_items"].values()), 2)) < 0.02
    # the cycle-time driver explains itself from cut/bend/handling (no magic const)
    cyc = next(d for d in sheet["drivers"] if d["name"] == "cycle_time")
    assert "cut" in cyc["source"] and "handling" in cyc["source"]
    # every driver still carries provenance + a non-empty source (gate G6)
    for d in sheet["drivers"]:
        assert d["source"].strip()
        assert d["provenance"] in ("MEASURED", "USER", "DEFAULT", "SHOP")


# ── guard: a compact block must NOT route to sheet metal ────────────────────
def test_compact_block_not_sheet():
    result, mesh, _ctx, feats = _analyze(_compact_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    assert report.routing["archetype"] != "sheet_panel"
    assert not _est(report, "sheet_metal"), "a solid block is not a sheet part"


# ── the check_bends correctness fix ─────────────────────────────────────────
def test_check_bends_passes_flat_plate():
    """A flat plate has only flat (0°) and clean 90° edges — no knife-edge folds,
    so check_bends must return no SHARP_BEND error (the inverted-threshold bug)."""
    mesh = _flat_plate()
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    issues = check_bends(ctx, ProcessType.SHEET_METAL)
    assert not any(i.severity == Severity.ERROR for i in issues), (
        "flat plate must not be flagged as a sharp bend")
