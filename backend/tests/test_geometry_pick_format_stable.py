"""The geometry pick doesn't depend on the file format (M13).

The same part as STL and as STEP picked different processes on nine audit
parts (resin printing on the STL, wire EDM on the STEP): an STL-only
measurement caveat (``*_PRECISION``) cost a process 0.1 and made its verdict
"issues", and a triangle-count bonus favoured CNC on 12-triangle STLs only.
"""

from __future__ import annotations

import importlib.util

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.models import AnalysisResult, Issue, ProcessType, Severity
from src.matcher.profile_matcher import rank_processes, score_process

PT = ProcessType


def _caveat(code, process):
    return Issue(code=code, severity=Severity.WARNING, message="precision note", process=process)


def _result(geometry, issues_by_process):
    scores = [score_process(issues_by_process.get(p, []), geometry, p) for p in PT]
    return AnalysisResult(filename="x", file_type="stl", geometry=geometry, segments=[],
                          universal_issues=[], process_scores=scores, analysis_time_ms=0.0)


def test_measurement_caveats_cost_nothing_and_do_not_move_the_pick():
    geometry = analyze_geometry(trimesh.creation.box(extents=[30, 30, 30]))
    as_stl = _result(geometry, {PT.DLP: [_caveat("WALL_THICKNESS_PRECISION", PT.DLP)],
                                PT.WIRE_EDM: [_caveat("PRISMATIC_PROFILE_PRECISION", PT.WIRE_EDM)]})
    as_step = _result(geometry, {PT.DLP: [_caveat("WALL_THICKNESS_PRECISION", PT.DLP)]})
    stl_scores = {s.process: s for s in as_stl.process_scores}
    assert stl_scores[PT.WIRE_EDM].score == 1.0 and stl_scores[PT.WIRE_EDM].verdict == "issues"
    assert rank_processes(as_stl)[0].process == rank_processes(as_step)[0].process


def test_a_design_warning_still_costs_its_tenth():
    geometry = analyze_geometry(trimesh.creation.box(extents=[30, 30, 30]))
    warn = Issue(code="OVERHANG", severity=Severity.WARNING, message="overhang", process=PT.FDM)
    (fdm,) = [s for s in _result(geometry, {PT.FDM: [warn]}).process_scores if s.process == PT.FDM]
    assert fdm.score == pytest.approx(0.9)


def test_triangle_count_does_not_change_a_score():
    coarse = analyze_geometry(trimesh.creation.box(extents=[30, 30, 30]))
    fine = analyze_geometry(trimesh.creation.box(extents=[30, 30, 30]).subdivide().subdivide().subdivide())
    assert fine.face_count > 500 > coarse.face_count
    for p in (PT.CNC_3AXIS, PT.INJECTION_MOLDING):
        warn = [Issue(code="UNDERCUT", severity=Severity.WARNING, message="undercut", process=p)]
        assert score_process(warn, coarse, p).score == score_process(warn, fine, p).score == pytest.approx(0.9)


@pytest.mark.skipif(importlib.util.find_spec("gmsh") is None, reason="gmsh is not installed")
def test_design_studio_plate_picks_the_same_process_from_stl_and_step():
    from src.analysis.context import GeometryContext
    from src.analysis.features import detect_all
    from src.analysis.processes import get_analyzer
    from src.api import routes
    from src.designs.generator import generate_design_artifacts

    art = generate_design_artifacts({"kind": "plate", "width_mm": 100.0, "depth_mm": 60.0, "thickness_mm": 3.0},
                                    timeout_seconds=60.0)
    picks = {}
    for name, data in (("plate.stl", art.stl_bytes), ("plate.step", art.step_bytes)):
        mesh, _ = routes._parse_mesh(data, name)
        geometry = analyze_geometry(mesh)
        ctx = GeometryContext.build(mesh, geometry)
        ctx.features = detect_all(ctx.mesh)
        scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p) for p in PT]
        result = AnalysisResult(filename=name, file_type=name.rsplit(".", 1)[1], geometry=geometry,
                                segments=[], universal_issues=[], process_scores=scores, analysis_time_ms=0.0)
        picks[name] = rank_processes(result)[0].process
    assert picks["plate.stl"] == picks["plate.step"], picks
