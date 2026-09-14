from pathlib import Path

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_sheet_gauge

CORPUS = Path(__file__).parent / "corpus-v3"


def _gauge(name: str):
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    return check_sheet_gauge(ctx, ProcessType.SHEET_METAL)


def test_formed_channel_uses_wall_gauge_not_bounding_box():
    assert _gauge("trap-uchannel-2mm-formed.stl") == []


def test_flat_sheet_controls_keep_measured_gauge_behavior():
    assert _gauge("control-plate-2mm-flat.stl") == []
    issues = _gauge("trap-plate-0p2mm-foil.stl")
    assert len(issues) == 1
    assert issues[0].code == "TOO_THIN_SHEET"
    assert issues[0].measured_value == pytest.approx(0.193, abs=0.001)
