from pathlib import Path

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_trapped_volumes

CORPUS = Path(__file__).parent / "trap-corpus"


def _context(name: str) -> GeometryContext:
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_all(ctx.mesh)
    return ctx


def test_undersized_drain_into_cavity_trips_fdm_gate():
    issues = check_trapped_volumes(
        _context("trap-hollow-drain-2mm-KNOWN-GAP.stl"),
        ProcessType.FDM,
        min_drain_mm=3.0,
    )

    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "TRAPPED_VOLUME"
    assert issue.measured_value == pytest.approx(2.0, abs=0.03)
    assert issue.required_value == 3.0
    assert issue.affected_faces


def test_compliant_drain_control_stays_clear():
    issues = check_trapped_volumes(
        _context("control-hollow-cup-drain-4mm.stl"),
        ProcessType.FDM,
        min_drain_mm=3.0,
    )

    assert issues == []


def test_small_blind_hole_does_not_claim_trapped_cavity():
    solid = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
    bore = trimesh.creation.cylinder(radius=1.0, height=4.0, sections=24)
    bore.apply_translation((0.0, 0.0, 8.0))
    mesh = trimesh.boolean.difference([solid, bore], engine="manifold")
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_all(ctx.mesh)

    assert check_trapped_volumes(ctx, ProcessType.FDM, min_drain_mm=3.0) == []
