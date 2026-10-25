"""A drafted cover drawn lying on its side is a molded part drawn turned.

The draft check reads the file's +Z as the direction the tool opens (a turned
re-check reads the chosen up). The Design Studio enclosure with 3-degree draft,
saved rotated 90 degrees about X or Y, read as undrafted: injection molding
"can't make it as drawn", and the routing for the same shape moved from
injection molding to nylon powder printing. The finding still says the tool
opens along +Z, now with which file axis the walls are drafted along, as a
warning to check it turned; the routing stays injection molding.
"""
import importlib.util

import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import AnalysisResult, ProcessType, Severity
from src.analysis.processes.base import get_analyzer
from src.costing import EstimateOptions, estimate_decision
from src.matcher.profile_matcher import score_process

pytestmark = pytest.mark.skipif(importlib.util.find_spec("gmsh") is None, reason="gmsh is not installed")

PLAN = {"kind": "enclosure", "width_mm": 80.0, "depth_mm": 60.0, "height_mm": 40.0,
        "wall_thickness_mm": 2.5, "draft_angle_deg": 3.0}


@pytest.fixture(scope="module")
def enclosure():
    from src.api import routes
    from src.designs.generator import generate_design_artifacts

    art = generate_design_artifacts(PLAN, timeout_seconds=60.0)
    mesh, _ = routes._parse_mesh(art.stl_bytes, "enclosure.stl")
    return mesh


def _turned(mesh, axis):
    from src.api import routes

    m = mesh.copy()
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, axis))
    out, _ = routes._parse_mesh(m.export(file_type="stl"), "turned.stl")
    return out


def _check(mesh):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    ctx.features = detect_all(ctx.mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p) for p in ProcessType]
    result = AnalysisResult(filename="enclosure.stl", file_type="stl", geometry=geometry, segments=[],
                            universal_issues=[], process_scores=scores, analysis_time_ms=0.0)
    report = estimate_decision(result, mesh, ctx.features, EstimateOptions(quantities=[1, 1000]))
    return {s.process: s for s in scores}, report.routing


@pytest.mark.parametrize("axis, drafted_along", [((1, 0, 0), "+Y"), ((0, 1, 0), "+X")])
def test_a_turned_drafted_enclosure_is_molded_and_says_which_way(enclosure, axis, drafted_along):
    base_scores, base_route = _check(enclosure)
    scores, route = _check(_turned(enclosure, axis))
    assert base_route["recommended_process"] == route["recommended_process"] == "injection_molding"
    im = scores[ProcessType.INJECTION_MOLDING]
    assert im.verdict != "fail"
    draft = next(i for i in im.issues if i.code == "INSUFFICIENT_DRAFT")
    assert draft.severity == Severity.WARNING
    assert "The tool opens along the file's +Z" in draft.message
    assert f"the walls are drafted along the file's {drafted_along} (at least 3.0°)" in draft.message
    # Forging needs 5 degrees: not drafted enough along any axis, still an error.
    forging = next(i for i in scores[ProcessType.FORGING].issues if i.code == "INSUFFICIENT_DRAFT")
    assert forging.severity == Severity.ERROR


def test_an_undrafted_box_still_cant_be_molded():
    box = trimesh.creation.box(extents=(40, 30, 20))
    scores, _route = _check(box)
    draft = next(i for i in scores[ProcessType.INJECTION_MOLDING].issues if i.code == "INSUFFICIENT_DRAFT")
    assert draft.severity == Severity.ERROR and "drawn turned" not in draft.message
