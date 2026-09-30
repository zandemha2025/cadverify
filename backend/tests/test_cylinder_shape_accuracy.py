"""Known cross-sections must not acquire an invented constant hole diameter."""
import numpy as np
import pytest
import trimesh

from src.analysis.features.base import FeatureKind, has_rotational_surface_evidence
from src.analysis.features.cylinders import detect_cylinders


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
