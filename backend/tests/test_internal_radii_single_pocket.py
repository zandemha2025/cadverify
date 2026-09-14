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
    return check_internal_radii(ctx, 0.5, ProcessType.CNC_3AXIS)


def test_one_square_pocket_is_enough_to_report_uncuttable_internal_corners():
    issues = _issues("trap-pocket-single-sharp-corner.stl")
    assert len(issues) == 1
    assert issues[0].code == "SHARP_INTERNAL_CORNERS"
    assert issues[0].required_value == 0.5


def test_many_square_pockets_remain_reported():
    assert _issues("trap-pocket-grid-16-sharp-corners.stl")[0].code == "SHARP_INTERNAL_CORNERS"
