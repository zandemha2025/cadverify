"""Issues carry the measured and required numbers the engine already compared."""
from __future__ import annotations

import math

import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.features.base import Feature, FeatureKind
from src.analysis.models import ProcessType
from src.analysis.processes import get_analyzer
from src.analysis.processes.checks import (
    check_bends,
    check_core_feasibility,
    check_fixture_surfaces,
    check_overhangs,
    check_residual_stress,
    check_shrinkage_risk,
    check_trapped_volumes,
)
from src.analysis.serialization import serialize_issue


def _ctx(mesh: trimesh.Trimesh, *, features: bool = False) -> GeometryContext:
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    if features:
        ctx.features = detect_all(ctx.mesh)
    return ctx


def _one(issues, code):
    (issue,) = [i for i in issues if i.code == code]
    return issue


def _difference(outer, inner):
    try:
        return trimesh.boolean.difference([outer, inner], engine="manifold")
    except Exception as exc:  # pragma: no cover - CSG backend missing
        pytest.skip(f"boolean ops unavailable: {exc}")


def test_overhang_reports_steepest_face_past_vertical_and_the_limit():
    column = trimesh.creation.box(extents=[10.0, 10.0, 20.0])
    column.apply_translation([0, 0, 10.0])
    slab = trimesh.creation.box(extents=[40.0, 40.0, 5.0])
    slab.apply_translation([0, 0, 22.5])
    issue = _one(check_overhangs(_ctx(trimesh.util.concatenate([column, slab])), 45.0, ProcessType.FDM), "OVERHANG")
    assert issue.measured_value == pytest.approx(90.0)  # the slab's flat underside
    assert issue.required_value == 45.0 and issue.measurement_unit == "deg"
    assert "exceed 45.0° overhang threshold" in issue.message  # read by the fix screens


def test_sealed_cavity_states_the_drain_it_needs():
    mesh = _difference(trimesh.creation.box(extents=[30.0] * 3), trimesh.creation.box(extents=[10.0] * 3))
    issue = _one(check_trapped_volumes(_ctx(mesh), ProcessType.SLA, min_drain_mm=3.5), "TRAPPED_VOLUME")
    assert issue.measured_value is None and issue.required_value == 3.5
    out = serialize_issue(issue)
    assert out["required_value"] == 3.5 and out["measurement_unit"] == "mm" and "measured_value" not in out
    assert "Needs >= 3.5mm drain holes" in issue.message


def test_fixture_flat_area_is_a_percent_against_its_minimum():
    mesh = trimesh.creation.cylinder(radius=5.0, height=100.0, sections=96)
    ctx = _ctx(mesh)
    # Keep only the two end caps as flat groups (the side strips are coplanar pairs).
    ctx.facet_groups = [g for g in ctx.facet_groups if abs(ctx.normals[g[0], 2]) > 0.99]
    assert len(ctx.facet_groups) == 2
    issue = _one(check_fixture_surfaces(ctx, 15.0, ProcessType.CNC_3AXIS), "NO_FIXTURE_SURFACES")
    flat = sum(float(ctx.face_areas[g].sum()) for g in ctx.facet_groups) / ctx.info.surface_area * 100
    assert issue.measured_value == pytest.approx(flat) and issue.measured_value < 15.0
    assert issue.required_value == 15.0 and issue.measurement_unit == "percent"


def test_shrinkage_states_its_volume_to_area_limit():
    issue = _one(check_shrinkage_risk(_ctx(trimesh.creation.box(extents=[120.0] * 3)), ProcessType.SAND_CASTING,
                                      max_compactness=12.0), "SHRINKAGE_RISK")
    assert issue.measured_value == pytest.approx(20.0) and issue.required_value == 12.0


def test_residual_stress_reports_the_flat_share():
    issue = _one(check_residual_stress(_ctx(trimesh.creation.box(extents=[50.0, 50.0, 2.0])), ProcessType.DMLS),
                 "RESIDUAL_STRESS_RISK")
    assert issue.measured_value == pytest.approx(2500.0 / 5400.0 * 100)
    assert issue.required_value == 15.0 and issue.measurement_unit == "percent"


def test_knife_edge_bend_states_its_divergence_limit():
    depth, length, included = 20.0, 50.0, 20.0
    tip = length * math.tan(math.radians(included))
    points = [(x, y, z) for y in (0.0, depth) for x, z in ((0.0, 0.0), (length, 0.0), (length, tip))]
    issue = _one(check_bends(_ctx(trimesh.convex.convex_hull(np.array(points))), ProcessType.SHEET_METAL), "SHARP_BEND")
    assert issue.measured_value == pytest.approx(180.0 - included)
    assert issue.required_value == 150.0


def test_fragile_core_reports_its_aspect_ratio_only():
    mesh = _difference(trimesh.creation.box(extents=[60.0, 20.0, 20.0]),
                       trimesh.creation.box(extents=[50.0, 4.0, 4.0]))
    issue = _one(check_core_feasibility(_ctx(mesh), ProcessType.SAND_CASTING), "FRAGILE_CORE")
    assert issue.measured_value == pytest.approx(12.5) and issue.measurement_unit == "ratio"
    # Flagged above 6:1 while the advice targets 4:1, so no single limit is claimed.
    assert issue.required_value is None


def test_sheet_hole_reports_diameter_against_the_gauge():
    mesh = trimesh.creation.box(extents=[30.0, 20.0, 2.0])
    ctx = _ctx(mesh)
    ctx.features = [Feature(kind=FeatureKind.CYLINDER_HOLE, face_indices=[], centroid=(0.0, 0.0, 0.0), radius=0.5)]
    issue = _one(get_analyzer(ProcessType.SHEET_METAL).analyze(ctx), "SMALL_HOLE_SHEET")
    assert issue.measured_value == pytest.approx(1.0)
    assert issue.required_value == pytest.approx(2.0) and issue.measurement_unit == "mm"


def test_resin_cupping_reports_the_downward_share():
    issue = _one(get_analyzer(ProcessType.SLA).analyze(_ctx(trimesh.creation.box(extents=[10.0] * 3))), "CUPPING_RISK")
    assert issue.measured_value == pytest.approx(100.0 / 6.0)
    assert issue.required_value == 10.0 and issue.measurement_unit == "percent"


def test_thin_boss_reports_its_outside_diameter_only():
    ctx = _ctx(trimesh.creation.box(extents=[20.0] * 3))
    ctx.features = [Feature(kind=FeatureKind.CYLINDER_BOSS, face_indices=[], centroid=(0.0, 0.0, 10.0), radius=1.0)]
    issue = _one(get_analyzer(ProcessType.INJECTION_MOLDING).analyze(ctx), "THIN_BOSS")
    assert issue.measured_value == pytest.approx(2.0) and issue.measurement_unit == "mm"
    # The advice is "OD >= 2x ID", which the engine does not measure.
    assert issue.required_value is None
