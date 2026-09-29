"""OVERHANG issues carry a truthful measured_value in the rule's own
convention, comparable to required_value.

From-vertical convention (FDM/EBM/DED/WAAM): measured_value is the
steepest offending overhang in degrees past vertical (worst face
angle_from_up minus 90). Above-horizontal convention (SLA, Formlabs):
measured_value is the lowest clearance above the build plate
(180 minus the shallowest offending angle_from_up). Values are raw
floats from mesh face normals - no rounding, no fabricated precision.
"""
from pathlib import Path

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.processes.additive.ebm import EBMAnalyzer
from src.analysis.processes.additive.fdm import FDMAnalyzer
from src.analysis.processes.additive.sla import SLAAnalyzer

CORPUS = Path(__file__).parent / "corpus-v3"


def _overhang(analyzer, name: str):
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_features(ctx.mesh)
    return next((i for i in analyzer.analyze(ctx) if i.code == "OVERHANG"), None)


def test_from_vertical_convention_measures_worst_angle():
    # Underside 30deg above horizontal = 60deg past vertical.
    issue = _overhang(EBMAnalyzer(), "trap-sla-overhang-30deg-from-horizontal.stl")
    assert issue.measured_value == pytest.approx(60.0, abs=1e-3)
    assert issue.required_value == 50.0
    assert issue.measured_value > issue.required_value  # trip is self-explaining


def test_from_vertical_steeper_fixture_measures_steeper():
    issue = _overhang(EBMAnalyzer(), "trap-sla-overhang-10deg-from-horizontal.stl")
    assert issue.measured_value == pytest.approx(80.0, abs=1e-3)


def test_above_horizontal_convention_measures_lowest_clearance():
    # Underside 10deg above horizontal vs Formlabs 19deg minimum.
    issue = _overhang(SLAAnalyzer(), "trap-sla-overhang-10deg-from-horizontal.stl")
    assert issue.measured_value == pytest.approx(10.0, abs=1e-3)
    assert issue.required_value == 19.0
    assert issue.measured_value < issue.required_value


def test_clearing_parts_emit_no_issue():
    assert _overhang(SLAAnalyzer(), "trap-sla-overhang-30deg-from-horizontal.stl") is None
    assert _overhang(FDMAnalyzer(), "control-overhang-44deg.stl") is None
    assert _overhang(EBMAnalyzer(), "control-cube-60mm.stl") is None
