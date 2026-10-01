"""Bar proportions guide routing; orientation must not hide costable routes."""
from __future__ import annotations

import trimesh
import numpy as np
import pytest

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
    assert PT_5AXIS in report.routing["alternatives"]
    assert report.routing["reasoning"].strip()


def test_long_bar_keeps_5axis_costed_as_an_alternative():
    result, mesh, _ctx, feats = _analyze(_long_bar())
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100],
                                               material_class="aluminum"))
    assert _est(report, "cnc_5axis"), "Shape alone cannot rule out multi-axis machining"
    # the make-now headline must not be 5-axis either
    assert report.decision.make_now_process != "cnc_5axis"


def test_long_bar_routing_holds_for_steel_too():
    result, mesh, _ctx, feats = _analyze(_long_bar())
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100],
                                               material_class="steel"))
    assert report.routing["archetype"] == "long_prismatic_bar"
    assert _est(report, "cnc_5axis")


# ── guard: a compact block does NOT get reclassified as a long bar ──────────
def test_compact_block_not_long_bar():
    result, mesh, _ctx, feats = _analyze(_compact_block())
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100],
                                               material_class="aluminum"))
    assert report.routing["archetype"] != "long_prismatic_bar"


@pytest.mark.parametrize("angle,axis", [(np.pi / 4, [0, 0, 1]), (.71, [1, 2, 3])])
@pytest.mark.parametrize("extents,archetype", [([80, 12, 12], "long_prismatic_bar"),
                                            ([80, 20, 12], "long_prismatic_bar"),
                                            ([240, 60, 12], "long_prismatic_bar"),
                                            ([40, 30, 25], "prismatic_block"),
                                            ([80, 30, 20], "prismatic_block")])
def test_shape_routing_survives_rotation(extents, archetype, angle, axis):
    from src.costing.drivers import extract_drivers
    from src.costing.routing import _classify_archetype, _routing_sane
    from src.analysis.models import ProcessType

    mesh = trimesh.creation.box(extents=extents)
    before = extract_drivers(analyze_geometry(mesh), mesh)
    mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, axis))
    mesh.apply_translation([100, -200, 300])
    after = extract_drivers(analyze_geometry(mesh), mesh)
    assert after.bbox_mm != before.bbox_mm  # source dimensions still describe the file
    for material in ["aluminum", "steel"]:
        old = _classify_archetype(before, material)
        new = _classify_archetype(after, material)
        assert old.archetype == new.archetype == archetype
        assert old.reasoning == new.reasoning
        assert _routing_sane(ProcessType.CNC_5AXIS, material, before) == _routing_sane(
            ProcessType.CNC_5AXIS, material, after)


def test_rotated_bar_report_keeps_the_same_costed_routes():
    reports = []
    for angle in [0, np.pi / 4]:
        mesh = trimesh.creation.box(extents=[80, 12, 12])
        mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [0, 0, 1]))
        result, mesh, _, features = _analyze(mesh)
        reports.append(estimate_decision(result, mesh, features,
            EstimateOptions(quantities=[1, 100], material_class="aluminum")))
    assert reports[0].routing == reports[1].routing
    assert [(e['process'], e['quantity']) for e in reports[0].estimates] == [
        (e['process'], e['quantity']) for e in reports[1].estimates]


def test_transverse_hole_bar_keeps_five_axis_when_three_axis_fails():
    solid = trimesh.creation.box(extents=[80, 12, 12])
    hole = trimesh.creation.cylinder(radius=2, height=14, sections=48)
    hole.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    mesh = trimesh.boolean.difference([solid, hole], engine="manifold")
    result, mesh, _, features = _analyze(mesh)
    report = estimate_decision(result, mesh, features,
        EstimateOptions(quantities=[1, 100], material_class="aluminum"))
    assert _est(report, "cnc_3axis")[0]["dfm_verdict"] == "fail"
    assert _est(report, "cnc_5axis")[0]["dfm_verdict"] != "fail"
    assert report.routing["archetype"] == "long_prismatic_bar"
    assert report.routing["recommended_process"] == "cnc_5axis"
    assert "not warranted" not in report.routing["reasoning"]


@pytest.mark.parametrize("extents,archetype", [
    ([79.99999, 20, 12], "bulk_solid"),
    ([240.00008, 60.00002, 12], "bulk_solid"),
    ([80.00001, 30, 20], "bulk_solid"),
])
def test_real_shape_threshold_overages_remain(extents, archetype):
    from src.costing.drivers import extract_drivers
    from src.costing.routing import _classify_archetype

    for angle in [0, np.pi / 4]:
        mesh = trimesh.creation.box(extents=extents)
        mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [0, 0, 1]))
        drivers = extract_drivers(analyze_geometry(mesh), mesh)
        assert _classify_archetype(drivers, "aluminum").archetype == archetype
