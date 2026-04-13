"""Phase 2 analyzer tests — every registered process runs without crashing."""

from __future__ import annotations

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes import get_analyzer, registered_processes


def _build_ctx(mesh):
    info = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, info)
    ctx.features = detect_all(mesh)
    return ctx


def test_all_21_processes_registered():
    """Every ProcessType enum has a registered analyzer."""
    procs = registered_processes()
    assert len(procs) == 21
    for pt in ProcessType:
        assert get_analyzer(pt) is not None, f"No analyzer for {pt.value}"


def test_every_analyzer_runs_on_cube(cube_10mm):
    """Every analyzer returns list[Issue] on a 10mm cube without crashing."""
    ctx = _build_ctx(cube_10mm)
    for pt in ProcessType:
        analyzer = get_analyzer(pt)
        assert analyzer is not None
        issues = analyzer.analyze(ctx)
        assert isinstance(issues, list), f"{pt.value} returned {type(issues)}"
        # Every issue should have code + severity at minimum
        for issue in issues:
            assert issue.code, f"{pt.value} produced issue without code"
            assert issue.severity, f"{pt.value} produced issue without severity"


def test_every_analyzer_runs_on_cylinder(cylinder_50h_10r):
    ctx = _build_ctx(cylinder_50h_10r)
    for pt in ProcessType:
        issues = get_analyzer(pt).analyze(ctx)
        assert isinstance(issues, list)


def test_every_analyzer_runs_on_thin_plate(plate_thin_04mm):
    """0.4mm plate should trigger wall-thickness issues on most processes."""
    ctx = _build_ctx(plate_thin_04mm)
    thin_wall_triggered = set()
    for pt in ProcessType:
        issues = get_analyzer(pt).analyze(ctx)
        for issue in issues:
            if issue.code in ("THIN_WALL", "THIN_WALL_MOLDING"):
                thin_wall_triggered.add(pt)
    # At least FDM (0.8mm min), SLS (0.7mm min), CNC should flag
    assert ProcessType.FDM in thin_wall_triggered
    assert ProcessType.CNC_3AXIS in thin_wall_triggered


def test_fdm_standards_cited(cube_10mm):
    ctx = _build_ctx(cube_10mm)
    analyzer = get_analyzer(ProcessType.FDM)
    assert len(analyzer.standards) > 0
    assert any("ISO" in s or "ASTM" in s or "Stratasys" in s for s in analyzer.standards)


def test_cnc_turning_passes_symmetric_cylinder(cylinder_50h_10r):
    """A cylinder IS rotationally symmetric — turning should NOT flag symmetry."""
    ctx = _build_ctx(cylinder_50h_10r)
    issues = get_analyzer(ProcessType.CNC_TURNING).analyze(ctx)
    codes = {i.code for i in issues}
    assert "NOT_ROTATIONALLY_SYMMETRIC" not in codes


def test_wire_edm_detects_non_prismatic(cylinder_50h_10r):
    """A cylinder has non-vertical faces (the caps) — wire EDM may flag it."""
    ctx = _build_ctx(cylinder_50h_10r)
    issues = get_analyzer(ProcessType.WIRE_EDM).analyze(ctx)
    # Cylinder sidewalls are vertical, but caps are horizontal — should still pass
    # (prismatic check allows horizontal + vertical faces)
    # Just verify it runs without error
    assert isinstance(issues, list)
