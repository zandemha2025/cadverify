"""Known cross-sections must not acquire an invented constant hole diameter."""
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.features.base import FeatureKind, has_rotational_surface_evidence
from src.analysis.features.cylinders import detect_cylinders
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_build_volume, check_length_diameter_ratio, check_rotational_symmetry
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


@pytest.mark.parametrize("radius,height", [(5, 40), (10, 6), (10, np.sqrt(3) * 10)])
def test_turning_dimensions_follow_the_part_axis_after_rigid_rotation(radius, height):
    cylinder = trimesh.creation.cylinder(radius=radius, height=height, sections=96)
    for angle in (0, 0.4, 0.73, 1.2):
        mesh = cylinder.copy()
        transform = trimesh.transformations.rotation_matrix(angle, [1, 2, 3])
        transform[:3, 3] = [125, -35, 41]
        mesh.apply_transform(transform)
        geometry = analyze_geometry(mesh)
        features = detect_cylinders(mesh)
        rotational, length, diameter = is_rotational(geometry, mesh, features)
        assert rotational, "changing a CAD part's orientation must not remove turning eligibility"
        assert length == pytest.approx(height, abs=1e-6)
        assert diameter == pytest.approx(2 * radius, abs=1e-6)


def test_turning_envelope_and_slenderness_use_the_same_physical_axis():
    for radius, height, too_large, slender in [(10, 500, False, True), (10, 600, True, True), (140, 30, True, False)]:
        for angle in (0, 0.73, 1.2):
            mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=96)
            mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [1, 2, 3]))
            ctx = SimpleNamespace(mesh=mesh, info=analyze_geometry(mesh), features=detect_cylinders(mesh))
            envelope = check_build_volume(ctx, (254, 254, 533), ProcessType.CNC_TURNING)
            assert bool(envelope) is too_large
            issues = check_length_diameter_ratio(ctx, 10.0, ProcessType.CNC_TURNING)
            assert bool(issues) is slender
            if issues:
                assert issues[0].measured_value == pytest.approx(height / (2 * radius), abs=1e-6)


@pytest.mark.parametrize("shape", ["prolate", "oblate", "torus", "profile"])
def test_curved_revolved_profiles_agree_in_routing_and_dfm(shape):
    if shape == "torus":
        original = trimesh.creation.torus(major_radius=15, minor_radius=6, major_sections=96, minor_sections=48)
        length, diameter = 12, 42
    elif shape == "profile":
        original = trimesh.creation.revolve(np.array([[0, -20], [5, -18], [10, -10], [13, 0], [8, 10], [3, 18], [0, 20]]), sections=96)
        length, diameter = 40, 26
    else:
        original = trimesh.creation.icosphere(subdivisions=4, radius=10)
        original.apply_scale([1, 1, 2] if shape == "prolate" else [2, 2, 1])
        length, diameter = (40, 20) if shape == "prolate" else (20, 40)
    for angle in (0, 0.73):
        mesh = original.copy()
        transform = trimesh.transformations.rotation_matrix(angle, [1, 2, 3])
        transform[:3, 3] = [125, -35, 41]
        mesh.apply_transform(transform)
        geometry = analyze_geometry(mesh)
        # Exercise curved-profile evidence independently of cylinder detection.
        rotational, measured_length, measured_diameter = is_rotational(geometry, mesh, [])
        assert rotational, shape
        assert measured_length == pytest.approx(length, abs=0.01)
        assert measured_diameter == pytest.approx(diameter, abs=0.01)
        ctx = SimpleNamespace(mesh=mesh, info=geometry, features=[])
        assert not check_rotational_symmetry(ctx, ProcessType.CNC_TURNING, tolerance=0.15)


def test_matching_inertia_is_insufficient_for_curved_profile_evidence():
    lobe = trimesh.creation.icosphere(subdivisions=3, radius=10)
    vertices = lobe.vertices.copy()
    theta = np.arctan2(vertices[:, 1], vertices[:, 0])
    vertices[:, :2] *= (1 + 0.12 * np.cos(4 * theta))[:, None]
    vertices[:, 2] *= 2
    lobe.vertices = vertices
    ellipsoid = trimesh.creation.icosphere(subdivisions=3, radius=10)
    ellipsoid.apply_scale([1, 1.1, 1.2])
    for mesh in [lobe, ellipsoid, trimesh.creation.box(extents=[20, 20, 40]), trimesh.creation.icosahedron()]:
        assert not has_rotational_surface_evidence([], mesh.area, mesh=mesh)
