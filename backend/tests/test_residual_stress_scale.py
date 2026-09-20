from pathlib import Path

import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_residual_stress

CORPUS = Path(__file__).parent / "corpus-v3"


def _ctx(mesh):
    return GeometryContext.build(mesh, analyze_geometry(mesh))


def test_tiny_control_cube_does_not_fake_large_flat_section():
    mesh = trimesh.load_mesh(CORPUS / "control-cube-10mm.stl")
    assert check_residual_stress(_ctx(mesh), ProcessType.DMLS) == []
    assert check_residual_stress(_ctx(mesh), ProcessType.SLM) == []


def test_physically_large_horizontal_patch_keeps_residual_stress_warning():
    mesh = trimesh.creation.box(extents=(60.0, 60.0, 10.0))
    issues = check_residual_stress(_ctx(mesh), ProcessType.DMLS)
    assert [issue.code for issue in issues] == ["RESIDUAL_STRESS_RISK"]
