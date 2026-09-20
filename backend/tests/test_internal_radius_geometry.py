from pathlib import Path

import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_internal_radii

CORPUS = Path(__file__).parent / "corpus-v3"


def _issues(name: str):
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_all(ctx.mesh)
    return check_internal_radii(ctx, 1.0, ProcessType.CNC_3AXIS)


def test_blind_drilled_hole_polygon_edges_are_not_pocket_corners():
    assert _issues("control-hole-8mmx16mm.stl") == []


def test_square_pocket_keeps_physical_internal_corner_finding():
    issues = _issues("trap-pocket-single-sharp-corner.stl")
    assert len(issues) == 1
    assert issues[0].code == "SHARP_INTERNAL_CORNERS"
