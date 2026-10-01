"""Phase 2 analyzer tests — every registered process runs without crashing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes import get_analyzer, registered_processes
from src.analysis.processes.checks import check_prismatic, check_setup_access


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


def test_wire_edm_accepts_cylinder_profile(cylinder_50h_10r):
    """A cylinder is a straight extrusion of its circular cross section."""
    ctx = _build_ctx(cylinder_50h_10r)
    issues = get_analyzer(ProcessType.WIRE_EDM).analyze(ctx)
    assert not any("PRISMATIC" in issue.code for issue in issues)


def test_straight_profile_check_is_orientation_independent_and_keeps_small_caps():
    for source in [trimesh.creation.box(extents=[80, 12, 12]),
                   trimesh.creation.cylinder(radius=1, height=1000, sections=128),
                   trimesh.creation.annulus(r_min=2, r_max=3, height=20, sections=32)]:
        for angle in [0., .5, 1.3]:
            mesh = source.copy()
            mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [1, 1, .3]))
            mesh.apply_translation([200, -300, 100])
            before = mesh.vertices.copy()
            assert check_prismatic(_build_ctx(mesh), ProcessType.WIRE_EDM) == []
            np.testing.assert_array_equal(mesh.vertices, before)


def test_unproved_step_profiles_request_wire_path_review():
    from src.parsers.step_mesher import step_to_trimesh_from_bytes

    controls = Path(__file__).resolve().parents[2] / "outputs/production-audit-20260929/shape-controls"
    # The boss changes section despite all normals being axis aligned. The
    # curved hole's adaptive triangles are not an exact extrusion, and the
    # parser supplies no tessellation-error bound to certify its nominal CAD.
    for filename in ["156-plate-with-boss.step", "166-transverse-hole-bar.step"]:
        source = controls / filename
        mesh = step_to_trimesh_from_bytes(source.read_bytes(), source.name)
        issues = check_prismatic(_build_ctx(mesh), ProcessType.WIRE_EDM)
        assert [i.code for i in issues] == ["PRISMATIC_PROFILE_UNVERIFIED"]
        assert issues[0].severity.value == "warning"
        assert "multi-axis" in issues[0].message


def test_profile_check_discloses_rounding_decimation_and_nonextrusions():
    from src.parsers.stl_parser import parse_stl_from_bytes

    mesh = trimesh.creation.box(extents=[80, 12, 12])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(.5, [1, 1, .3]))
    mesh.apply_translation([200, -300, 100])
    rounded = parse_stl_from_bytes(mesh.export(file_type="stl"))
    issues = check_prismatic(_build_ctx(rounded), ProcessType.WIRE_EDM)
    assert [i.code for i in issues] == ["PRISMATIC_PROFILE_PRECISION"]
    assert issues[0].severity.value == "warning"

    ctx = _build_ctx(mesh)
    ctx.metadata["decimation"] = {"succeeded": True}
    assert check_prismatic(ctx, ProcessType.WIRE_EDM)[0].code == "PRISMATIC_PROFILE_UNVERIFIED"

    opened = mesh.copy(); opened.update_faces(np.arange(len(mesh.faces) - 1))
    other = mesh.copy(); other.apply_translation([200, 0, 0])
    for source in [opened, mesh + other, trimesh.creation.cone(radius=5, height=10),
                   trimesh.creation.icosphere(subdivisions=1, radius=5)]:
        issues = check_prismatic(_build_ctx(source), ProcessType.WIRE_EDM)
        assert [i.code for i in issues] == ["PRISMATIC_PROFILE_UNVERIFIED"]
        assert issues[0].severity.value == "warning"


def test_reorienting_convex_parts_does_not_invent_machining_undercuts():
    for source in [trimesh.creation.box(extents=[80, 12, 12]),
                   trimesh.creation.icosphere(subdivisions=1, radius=5)]:
        for angle in [0., .5, 1.3]:
            mesh = source.copy()
            mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [1, 1, .3]))
            mesh.apply_translation([200, -300, 100])
            before = mesh.vertices.copy()
            ctx = _build_ctx(mesh)
            for process in [ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS, ProcessType.FORGING]:
                assert check_setup_access(ctx, process) == []
            np.testing.assert_array_equal(mesh.vertices, before)


def test_access_check_does_not_ignore_a_cavity_in_the_bottom_five_percent():
    outer = trimesh.creation.box(extents=[20, 20, 20])
    cavity = trimesh.creation.box(extents=[1, 1, .2])
    cavity.apply_translation([0, 0, -9.8]); cavity.invert()
    mesh = outer + cavity
    assert mesh.is_volume
    issues = check_setup_access(_build_ctx(mesh), ProcessType.CNC_3AXIS)
    assert [i.code for i in issues] == ["SETUP_ACCESS_UNVERIFIED"]
    assert issues[0].severity.value == "warning"
    assert issues[0].affected_faces
    assert min(issues[0].affected_faces) >= len(outer.faces)


def test_setup_search_accepts_rotated_boss_and_retains_uncertain_geometry():
    from src.parsers.step_mesher import step_to_trimesh_from_bytes
    from src.parsers.stl_parser import parse_stl_from_bytes

    source = Path(__file__).resolve().parents[2] / "outputs/production-audit-20260929/shape-controls/156-plate-with-boss.step"
    boss = step_to_trimesh_from_bytes(source.read_bytes(), source.name)
    for angle in [0., .5]:
        mesh = boss.copy()
        mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [1, 1, .3]))
        assert check_setup_access(_build_ctx(mesh), ProcessType.CNC_3AXIS) == []

    mesh = trimesh.creation.box(extents=[80, 12, 12])
    rounded = parse_stl_from_bytes(mesh.export(file_type="stl"))
    assert check_setup_access(_build_ctx(rounded), ProcessType.CNC_3AXIS)[0].code == "SETUP_ACCESS_UNVERIFIED"
    ctx = _build_ctx(mesh); ctx.metadata["decimation"] = {"succeeded": True}
    issue = check_setup_access(ctx, ProcessType.CNC_3AXIS)[0]
    assert issue.code == "SETUP_ACCESS_UNVERIFIED" and not issue.affected_faces
    torus = trimesh.creation.torus(major_radius=5, minor_radius=1, major_sections=24, minor_sections=12)
    assert check_setup_access(_build_ctx(torus), ProcessType.CNC_3AXIS)[0].code == "SETUP_ACCESS_UNVERIFIED"


def test_skinny_triangulation_cannot_hide_a_reentrant_chamber():
    from src.analysis.context import wall_thickness_tolerance

    outer = trimesh.creation.box(extents=[20, 20, 20])
    chamber = trimesh.creation.box(extents=[10, 10, 10])
    neck = trimesh.creation.box(extents=[4, 4, 12]); neck.apply_translation([0, 0, 6])
    mesh = trimesh.boolean.difference([outer, chamber, neck])
    # Inset each triangle without changing its surface. Thin coplanar edge
    # strips shrink local adjacency projections at every concave edge.
    inner = mesh.triangles * (1 - 1e-10) + mesh.triangles_center[:, None, :] * 1e-10
    faces = []
    for index, (a, b, c) in enumerate(mesh.faces):
        x, y, z = len(mesh.vertices) + 3 * index + np.arange(3)
        faces.extend([[a, b, y], [a, y, x], [b, c, z], [b, z, y],
                      [c, a, x], [c, x, z], [x, y, z]])
    refined = trimesh.Trimesh(np.vstack([mesh.vertices, inner.reshape(-1, 3)]), faces, process=False)
    assert refined.is_volume and refined.body_count == 1
    np.testing.assert_allclose(refined.volume, mesh.volume, rtol=1e-12)
    ctx = _build_ctx(refined)
    assert refined.face_adjacency_projections.max() <= wall_thickness_tolerance(refined, ctx.scale_eps)
    for process in [ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS, ProcessType.FORGING]:
        assert check_setup_access(ctx, process)[0].code == "SETUP_ACCESS_UNVERIFIED"
