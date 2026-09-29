"""PROD-026: a recognized cylindrical surface is not also many flat features."""
import pytest
import trimesh

from src.analysis.features import detect_all
from src.analysis.features.base import FeatureKind


@pytest.mark.parametrize("sections", [64, 256])
def test_bore_and_outer_cylinder_have_only_two_planar_caps(sections):
    part = trimesh.creation.annulus(r_min=3, r_max=10, height=10, sections=sections)
    flats = [feature for feature in detect_all(part) if feature.kind == FeatureKind.FLAT]
    assert len(flats) == 2
    assert all(abs(feature.axis[2]) > 0.999 for feature in flats)


def test_real_polygonal_sides_remain_flat():
    part = trimesh.creation.cylinder(radius=5, height=10, sections=6)
    flats = [feature for feature in detect_all(part) if feature.kind == FeatureKind.FLAT]
    assert len(flats) == 8  # six actual planar sides and two caps
