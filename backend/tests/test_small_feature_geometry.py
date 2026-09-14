from pathlib import Path

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_small_features

CORPUS = Path(__file__).parent / "corpus-v3"


def _issues(name: str):
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_all(ctx.mesh)
    return check_small_features(ctx, 0.4, ProcessType.FDM)


def test_printable_hole_chords_are_not_physical_small_features():
    assert _issues("trap-plate-5mm-through-hole-2mm.stl") == []
    assert _issues("control-hole-8mmx16mm.stl") == []


def test_single_real_undersized_rib_is_not_hidden_by_percentage_floor():
    issues = _issues("trap-single-0p3mm-rib-among-many.stl")
    assert len(issues) == 1
    assert issues[0].code == "SMALL_FEATURES"
    assert issues[0].measured_value == pytest.approx(0.3)
    assert issues[0].required_value == 0.4
