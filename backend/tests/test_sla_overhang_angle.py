import json
from pathlib import Path

import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes import get_analyzer

CORPUS = Path(__file__).parent / "corpus-v3"


def _codes(name: str, process: ProcessType) -> set[str]:
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_all(ctx.mesh)
    return {issue.code for issue in get_analyzer(process).analyze(ctx)}


def test_sla_uses_19_degrees_above_horizontal_not_from_vertical():
    assert "OVERHANG" not in _codes("trap-sla-overhang-30deg-from-horizontal.stl", ProcessType.SLA)
    assert "OVERHANG" in _codes("trap-sla-overhang-10deg-from-horizontal.stl", ProcessType.SLA)


def test_shared_geometry_keeps_dlp_vertical_angle_semantics():
    assert "OVERHANG" in _codes("control-overhang-44deg.stl", ProcessType.DLP)
    assert "OVERHANG" not in _codes("control-overhang-44deg.stl", ProcessType.SLA)
