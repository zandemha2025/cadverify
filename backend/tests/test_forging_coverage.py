"""Forging analyzer behavior on the v3 forging coverage fixtures.

Thresholds from formative/forging.py, citing the Forging Industry
Association Design Guide: 5deg external draft, 3mm min corner radius,
no undercuts (die opening), 3mm min web, 6:1 max rib height:width.
"""
from pathlib import Path

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.processes.formative.forging import ForgingAnalyzer

CORPUS = Path(__file__).parent / "corpus-v3"


def _codes(name: str):
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_features(ctx.mesh)
    return {i.code: i for i in ForgingAnalyzer().analyze(ctx)}


def test_7deg_drafted_frustum_is_clean_control():
    assert _codes("control-draft-7deg.stl") == {}


def test_half_and_1p5_deg_draft_trip():
    assert "INSUFFICIENT_DRAFT" in _codes("trap-draft-0p5deg.stl")
    assert "INSUFFICIENT_DRAFT" in _codes("control-draft-1p5deg.stl")


def test_tshape_undercut_trips():
    assert "UNDERCUT" in _codes("trap-tshape-undercut.stl")
    assert "UNDERCUT" not in _codes("control-stepped-shaft-noundercut.stl")


def test_sharp_pocket_corner_trips_fillet_rule():
    assert "MISSING_FILLETS" in _codes("trap-pocket-single-sharp-corner.stl")


def test_2p99mm_wall_trips_3mm_web_minimum():
    issues = _codes("control-hollow-box-uniform-3mm-wall.stl")
    assert issues["THIN_WALL"].measured_value == pytest.approx(2.99, abs=0.01)


def test_12to1_bbox_trips_rib_ratio():
    issues = _codes("trap-mjf-rod-12to1.stl")
    assert issues["HIGH_RIB_RATIO"].measured_value == pytest.approx(12.0)
