from pathlib import Path

import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_wall_uniformity

CORPUS = Path(__file__).parent / "corpus-v3"


def _codes(name: str, max_wall: float):
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_all(ctx.mesh)
    return {i.code for i in check_wall_uniformity(ctx, 0.5, max_wall, 2.5, ProcessType.INJECTION_MOLDING)}


def test_uniform_hollow_box_drain_rays_do_not_inflate_wall_stock():
    assert not (_codes("control-hollow-box-uniform-3mm-wall.stl", 6.0) & {"THICK_WALL", "NON_UNIFORM_WALLS"})


def test_uniform_plate_hole_and_span_rays_do_not_inflate_wall_stock():
    assert not (_codes("trap-plate-5mm-through-hole-2mm.stl", 6.0) & {"THICK_WALL", "NON_UNIFORM_WALLS"})
