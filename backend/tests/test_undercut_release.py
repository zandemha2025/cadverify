"""Undercuts are faces a mold opening along Z cannot release, not "upward faces in the lower half"."""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import ProcessType
from src.analysis.processes import get_analyzer
from src.analysis.processes.checks import check_undercuts_molding

ASSETS = Path(__file__).parent / "assets"
MOLDS = (ProcessType.INJECTION_MOLDING, ProcessType.DIE_CASTING)


def _box(extents, center=(0.0, 0.0, 0.0)) -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=extents)
    box.apply_translation(center)
    return box


def _difference(*meshes) -> trimesh.Trimesh:
    try:
        return trimesh.boolean.difference(list(meshes), engine="manifold")
    except Exception as exc:  # pragma: no cover - CSG backend missing
        pytest.skip(f"boolean ops unavailable: {exc}")


def _union(*meshes) -> trimesh.Trimesh:
    try:
        return trimesh.boolean.union(list(meshes), engine="manifold")
    except Exception as exc:  # pragma: no cover - CSG backend missing
        pytest.skip(f"boolean ops unavailable: {exc}")


def _open_box() -> trimesh.Trimesh:
    """60 × 40 × 30 mm, 2 mm walls and floor, open at the top."""
    return _difference(_box([60, 40, 30], (0, 0, 15)), _box([56, 36, 40], (0, 0, 32)))


def _ctx(mesh: trimesh.Trimesh) -> GeometryContext:
    return GeometryContext.build(mesh, analyze_geometry(mesh))


def _undercut_faces(ctx: GeometryContext, process=ProcessType.INJECTION_MOLDING) -> np.ndarray:
    issues = [i for i in check_undercuts_molding(ctx, process, cite="Side actions add $5–15K tooling.")]
    assert all(i.code == "UNDERCUT_MOLDING" for i in issues)
    return np.asarray(issues[0].affected_faces if issues else [], dtype=int)


def _analyzer_codes(ctx: GeometryContext, process: ProcessType) -> set[str]:
    return {i.code for i in get_analyzer(process).analyze(ctx)}


def test_open_box_floor_is_reached_through_the_opening():
    ctx = _ctx(_open_box())
    assert len(_undercut_faces(ctx)) == 0
    for process in MOLDS:
        assert "UNDERCUT_MOLDING" not in _analyzer_codes(ctx, process)


@pytest.mark.skipif(importlib.util.find_spec("gmsh") is None, reason="gmsh is not installed")
@pytest.mark.parametrize("draft", [0.0, 1.5])
def test_design_studio_open_enclosure_has_no_undercuts(draft):
    from src.designs.generator import generate_design_artifacts

    plan = {"kind": "enclosure", "width_mm": 120.0, "depth_mm": 80.0, "height_mm": 40.0,
            "wall_thickness_mm": 1.0, "draft_angle_deg": draft}
    mesh = trimesh.load(io.BytesIO(generate_design_artifacts(plan, timeout_seconds=30.0).stl_bytes), file_type="stl")
    ctx = _ctx(mesh)
    # The old mid-height rule flagged the whole inside floor (~1,800 faces) here.
    floor = np.flatnonzero((np.abs(ctx.centroids[:, 2] - 1.0) < 1e-6) & (ctx.normals[:, 2] > 0.99))
    assert len(floor) > 1000
    assert len(_undercut_faces(ctx)) == 0
    for process in MOLDS:
        assert "UNDERCUT_MOLDING" not in _analyzer_codes(ctx, process)


def test_bored_block_has_no_undercuts():
    from src.api.routes import _parse_mesh

    path = ASSETS / "bored-block-mm.iges"
    mesh, _suffix = _parse_mesh(path.read_bytes(), path.name)
    assert len(_undercut_faces(_ctx(mesh))) == 0


def test_side_hole_is_an_undercut():
    hole = trimesh.creation.cylinder(radius=3.0, height=60.0, sections=48)
    hole.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    hole.apply_translation([0, 0, 10])
    ctx = _ctx(_difference(_box([40, 30, 20], (0, 0, 10)), hole))
    faces = _undercut_faces(ctx)
    assert len(faces) > 0
    # Only the hole's own surface, top and bottom of the bore, is shadowed.
    assert np.all(np.abs(ctx.centroids[faces, 2] - 10.0) <= 3.0 + 1e-6)
    assert np.all(np.abs(ctx.normals[faces, 2]) >= np.cos(np.radians(80.0)) - 1e-9)
    for process in MOLDS:
        assert "UNDERCUT_MOLDING" in _analyzer_codes(ctx, process)


def test_inward_lip_is_an_undercut():
    lip = _difference(_box([60, 40, 2], (0, 0, 29)), _box([48, 28, 4], (0, 0, 29)))
    ctx = _ctx(_union(_open_box(), lip))
    faces = _undercut_faces(ctx)
    assert len(faces) > 0
    # The lip's underside hangs over the cavity and cannot drop out along -Z.
    assert np.allclose(ctx.centroids[faces, 2], 28.0)
    assert np.all(ctx.normals[faces, 2] < -0.99)


def test_groove_in_an_inside_wall_is_an_undercut():
    ctx = _ctx(_difference(_open_box(), _box([4, 20, 3], (-28, 0, 15))))
    faces = _undercut_faces(ctx)
    z = np.round(ctx.centroids[faces, 2], 6)
    assert set(z) == {13.5, 16.5}  # the groove's floor and ceiling


def test_sealed_cavity_is_an_undercut():
    ctx = _ctx(_difference(_box([30] * 3, (0, 0, 15)), _box([10] * 3, (0, 0, 15))))
    faces = _undercut_faces(ctx)
    assert set(np.round(ctx.centroids[faces, 2], 6)) == {10.0, 20.0}


@pytest.mark.parametrize("name", ["cap on a stem", "blind vertical bore", "plain box"])
def test_shapes_that_release_along_z_are_not_flagged(name):
    """The old rule flagged the cap's underside and the bore's floor by height alone."""
    bore = trimesh.creation.cylinder(radius=4.0, height=20.0, sections=48)
    bore.apply_translation([0, 0, 20])
    mesh = {
        "cap on a stem": lambda: _union(_box([10, 10, 20], (0, 0, 10)), _box([40, 40, 5], (0, 0, 22.5))),
        "blind vertical bore": lambda: _difference(_box([30, 30, 20], (0, 0, 10)), bore),
        "plain box": lambda: _box([40, 30, 25]),
    }[name]()
    assert len(_undercut_faces(_ctx(mesh))) == 0


def test_without_embree_small_meshes_get_the_same_answer_and_large_ones_say_unknown(monkeypatch):
    from trimesh.ray.ray_triangle import RayMeshIntersector

    def python_rays(ctx):
        ctx.mesh.ray = RayMeshIntersector(ctx.mesh)
        return ctx

    hole = trimesh.creation.cylinder(radius=3.0, height=60.0, sections=96)
    hole.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    hole.apply_translation([0, 0, 10])
    side_mesh = _difference(_box([40, 30, 20], (0, 0, 10)), hole)
    with_embree = _undercut_faces(_ctx(side_mesh.copy()))
    side = python_rays(_ctx(side_mesh))
    assert "embree" not in type(side.mesh.ray).__module__
    assert np.array_equal(_undercut_faces(side), with_embree)
    assert len(_undercut_faces(python_rays(_ctx(_open_box())))) == 0

    # Too many rays for the slow backend: report unknown instead of guessing.
    monkeypatch.setenv("RAYCAST_SAMPLE_THRESHOLD", "10")
    (issue,) = check_undercuts_molding(python_rays(_ctx(side_mesh.copy())), ProcessType.INJECTION_MOLDING)
    assert issue.code == "ANALYSIS_PARTIAL"


def test_a_failed_ray_cast_is_reported_not_passed():
    class Broken:
        def intersects_any(self, *_args, **_kwargs):
            raise RuntimeError("ray backend down")

    ctx = _ctx(_open_box())
    ctx.mesh.ray = Broken()
    (issue,) = check_undercuts_molding(ctx, ProcessType.DIE_CASTING)
    assert issue.code == "ANALYSIS_PARTIAL" and "Undercut check incomplete" in issue.message
