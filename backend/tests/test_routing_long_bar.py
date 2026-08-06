"""F4 regression: a slender prismatic bar / long rod must never headline
CNC 5-Axis. It should saw-to-length + turn (round bar) or 3-axis mill
(rectangular bar).

Root cause (see routing.py):
  1. `_classify_archetype` had no "long bar" branch, so a 200x20x10mm bar fell
     through prismatic_block (block_aspect ceiling 4.0 fails at 20:1) into
     bulk_solid, headlining CNC_3AXIS -> promoted-to-5-axis territory.
  2. `_routing_sane` returned True for CNC_5AXIS unconditionally, so once the
     bar's ordinary features tripped the 3-axis undercut DFM error and turning
     was gated out (not rotational), CNC_5AXIS was the cheapest surviving
     costed route.

Fix: `is_long_prismatic_bar` classifies the shape and (a) drives a new
"long_prismatic_bar" archetype headlining 3-axis/turning, never 5-axis, and
(b) gates CNC_5AXIS out of the costed shortlist for a bar in `_routing_sane`.
"""
from __future__ import annotations

import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult
from src.analysis.processes import base as pbase
from src.analysis.processes.base import get_analyzer
import src.analysis.processes  # noqa: F401  populate registry
from src.matcher.profile_matcher import rank_processes, score_process

from src.costing import estimate_decision, EstimateOptions

PT_5AXIS = "cnc_5axis"


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


def _long_bar():
    # 200 x 20 x 10 mm rectangular bar — the canonical F4 slender prismatic bar
    return trimesh.creation.box(extents=[200.0, 20.0, 10.0])


def _compact_block():
    return trimesh.creation.box(extents=[40.0, 30.0, 25.0])


def _est(report, process):
    return [e for e in report.estimates if e["process"] == process]


# ── the headline: a long bar routes to long_prismatic_bar, never 5-axis ─────
def test_long_bar_routes_to_prismatic_bar_not_5axis():
    result, mesh, _ctx, feats = _analyze(_long_bar())
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100],
                                               material_class="aluminum"))
    assert report.status == "OK"
    assert report.routing is not None
    assert report.routing["archetype"] == "long_prismatic_bar"
    assert report.routing["recommended_process"] != "cnc_5axis"
    assert PT_5AXIS not in report.routing["alternatives"]
    assert report.routing["reasoning"].strip()


def test_long_bar_5axis_not_in_costed_shortlist():
    result, mesh, _ctx, feats = _analyze(_long_bar())
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100],
                                               material_class="aluminum"))
    assert not _est(report, "cnc_5axis"), (
        "CNC 5-axis must be gated out of the costed shortlist for a slender bar")
    # the make-now headline must not be 5-axis either
    assert report.decision.make_now_process != "cnc_5axis"


def test_long_bar_routing_holds_for_steel_too():
    result, mesh, _ctx, feats = _analyze(_long_bar())
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100],
                                               material_class="steel"))
    assert report.routing["archetype"] == "long_prismatic_bar"
    assert not _est(report, "cnc_5axis")


# ── guard: a compact block does NOT get reclassified as a long bar ──────────
def test_compact_block_not_long_bar():
    result, mesh, _ctx, feats = _analyze(_compact_block())
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100],
                                               material_class="aluminum"))
    assert report.routing["archetype"] != "long_prismatic_bar"
