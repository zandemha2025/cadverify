"""INSUFFICIENT_DRAFT and UNDERCUT issues carry truthful measured evidence.

INSUFFICIENT_DRAFT: measured_value is the least-drafted offending
sidewall in draft degrees, comparable to required_value (the minimum).
UNDERCUT: measured_value is the total undercut surface area in mm^2
(the rule is binary; required_value is 0). Raw floats from mesh
geometry - no rounding, no fabricated precision.
"""
from pathlib import Path

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.processes.formative.forging import ForgingAnalyzer

CORPUS = Path(__file__).parent / "corpus-v3"


def _issues(name: str):
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_features(ctx.mesh)
    return {i.code: i for i in ForgingAnalyzer().analyze(ctx)}


def test_draft_measured_matches_fixture_nominal():
    assert _issues("trap-draft-0p5deg.stl")["INSUFFICIENT_DRAFT"].measured_value == pytest.approx(0.5, abs=1e-3)
    assert _issues("control-draft-1p5deg.stl")["INSUFFICIENT_DRAFT"].measured_value == pytest.approx(1.5, abs=1e-3)
    assert _issues("control-cube-60mm.stl")["INSUFFICIENT_DRAFT"].measured_value == pytest.approx(0.0, abs=1e-6)


def test_draft_required_value_is_threshold():
    assert _issues("trap-draft-0p5deg.stl")["INSUFFICIENT_DRAFT"].required_value == 5.0


def test_sufficient_draft_emits_nothing():
    assert "INSUFFICIENT_DRAFT" not in _issues("control-draft-7deg.stl")


def test_undercut_measured_is_area_mm2():
    issue = _issues("trap-tshape-undercut.stl")["UNDERCUT"]
    assert issue.measured_value == pytest.approx(3200.0, abs=1.0)  # two 40x40 undersides
    assert issue.required_value == 0.0


def test_no_undercut_emits_nothing():
    assert "UNDERCUT" not in _issues("control-stepped-shaft-noundercut.stl")
