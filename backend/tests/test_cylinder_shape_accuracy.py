"""Known cross-sections must not acquire an invented constant hole diameter."""
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.features.base import FeatureKind, has_rotational_surface_evidence
from src.analysis.features.cylinders import detect_cylinders
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_rotational_symmetry
from src.costing.routing import is_rotational


@pytest.mark.parametrize("sections", [64, 256])
def test_round_elliptical_and_tapered_surfaces_remain_distinct(sections):
    transform = trimesh.transformations.rotation_matrix(0.73, [1, 2, 3])
    transform[:3, 3] = [125, -35, 41]
    round_part = trimesh.creation.annulus(r_min=3, r_max=10, height=10, sections=sections)
    ellipse = round_part.copy()
    ellipse.apply_scale([2, 1, 1])
    cone = trimesh.creation.revolve(np.array([[0, 0], [10, 0], [8, 20], [0, 20]]), sections=sections)
    for part in (round_part, ellipse, cone):
        part.apply_transform(transform)
    circular = detect_cylinders(round_part)
    assert sorted(f.kind.value for f in circular) == ["cylinder_boss", "cylinder_hole"]
    assert sorted(f.radius for f in circular) == pytest.approx([3, 10], abs=0.02)
    assert all(f.depth == pytest.approx(10, abs=0.02) for f in circular)
    oval = detect_cylinders(ellipse)
    assert not any(f.kind in (FeatureKind.CYLINDER_HOLE, FeatureKind.CYLINDER_BOSS) for f in oval)
    assert not has_rotational_surface_evidence(oval, ellipse.area)
    tapered = detect_cylinders(cone)
    assert not any(f.kind in (FeatureKind.CYLINDER_HOLE, FeatureKind.CYLINDER_BOSS) for f in tapered)
    assert has_rotational_surface_evidence(tapered, cone.area), "a circular taper remains valid turning evidence"


@pytest.mark.parametrize("subdivisions", [2, 3])
def test_spherical_turning_evidence_agrees_in_dfm_and_routing(subdivisions):
    sphere = trimesh.creation.icosphere(subdivisions=subdivisions, radius=10)
    ellipsoid = sphere.copy()
    ellipsoid.apply_scale([1, 1.1, 1.2])
    # A cube's vertices also lie on a sphere; its face interiors do not.
    cube = trimesh.creation.box(extents=[20, 20, 20])
    open_sphere = sphere.copy()
    open_sphere.update_faces(np.arange(len(open_sphere.faces) - 1))
    inverted = sphere.copy()
    inverted.invert()
    transform = trimesh.transformations.rotation_matrix(0.73, [1, 2, 3])
    transform[:3, 3] = [125, -35, 41]
    for mesh, expected in ((sphere, True), (ellipsoid, False), (cube, False),
                           (open_sphere, False), (inverted, False)):
        mesh.apply_transform(transform)
        info = analyze_geometry(mesh)
        assert bool(is_rotational(info, mesh, [])[0]) is expected
        if info.is_watertight and info.volume > 0:
            ctx = SimpleNamespace(mesh=mesh, info=info, features=[])
            issues = check_rotational_symmetry(ctx, ProcessType.CNC_TURNING, tolerance=0.15)
            assert (not any(i.code == "NOT_ROTATIONALLY_SYMMETRIC" for i in issues)) is expected
