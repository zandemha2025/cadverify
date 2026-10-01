"""PROD-021: a tessellated bore is curved, not thousands of sharp corners."""
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon

from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_fillet_requirements


def _check(mesh):
    context = SimpleNamespace(
        dihedral_angles_rad=np.asarray(mesh.face_adjacency_angles),
        concave_mask=~np.asarray(mesh.face_adjacency_convex),
    )
    return check_fillet_requirements(context, 1.0, ProcessType.DIE_CASTING)


@pytest.mark.parametrize("sections", [64, 256])
def test_smooth_cylindrical_bore_does_not_need_sharp_corner_fillets(sections):
    ring = trimesh.creation.annulus(r_min=3, r_max=10, height=10, sections=sections)
    assert _check(ring) == []


@pytest.mark.parametrize("subdivisions", [0, 3])
def test_real_reentrant_corner_is_reported_regardless_of_triangle_count(subdivisions):
    # The L has exactly one sharp concave vertical corner, even before refinement.
    part = trimesh.creation.extrude_polygon(
        Polygon([(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)]), height=10,
    )
    for _ in range(subdivisions):
        part = part.subdivide()
    assert [issue.code for issue in _check(part)] == ["MISSING_FILLETS"]
