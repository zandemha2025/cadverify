from pathlib import Path

import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.processes.additive.sla import SLAAnalyzer

CORPUS = Path(__file__).parent / "corpus-v3"


def _codes(name: str) -> set[str]:
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    return {issue.code for issue in SLAAnalyzer().analyze(ctx)}


def test_sealed_concave_ceiling_keeps_cupping_risk():
    assert "CUPPING_RISK" in _codes("trap-sealed-cavity-cupping.stl")


def test_flat_base_and_drained_open_cup_do_not_fake_cupping():
    assert "CUPPING_RISK" not in _codes("control-cube-10mm.stl")
    assert "CUPPING_RISK" not in _codes("control-hollow-cup-drain-4mm.stl")
