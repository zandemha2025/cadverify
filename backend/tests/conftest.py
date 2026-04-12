"""Shared pytest fixtures for CADVerify.

All fixtures generate meshes *procedurally* via trimesh.creation so nothing
binary has to be checked into git. Any fixture whose construction needs
boolean operations (difference / union) is skipped gracefully if the
underlying CSG backend (manifold3d) is missing — the rest of the suite
still runs.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
import trimesh


def _try_csg(op):
    """Run a boolean-op closure, skip the test if the backend is missing."""
    try:
        return op()
    except Exception as e:
        pytest.skip(f"boolean ops unavailable: {e}")


# ──────────────────────────────────────────────────────────────
# Primitive meshes
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def cube_10mm() -> trimesh.Trimesh:
    """Watertight 10mm cube — the universal 'it should just pass' fixture."""
    return trimesh.creation.box(extents=[10.0, 10.0, 10.0])


@pytest.fixture
def plate_thin_2mm() -> trimesh.Trimesh:
    """30×30×2 mm plate — exercises wall-thickness detection at the low end."""
    return trimesh.creation.box(extents=[30.0, 30.0, 2.0])


@pytest.fixture
def plate_thin_04mm() -> trimesh.Trimesh:
    """30×30×0.4 mm plate — sub-mm wall, should fail FDM (0.8mm min)."""
    return trimesh.creation.box(extents=[30.0, 30.0, 0.4])


@pytest.fixture
def cylinder_50h_10r() -> trimesh.Trimesh:
    """Solid cylinder, 20mm diameter × 50mm tall."""
    return trimesh.creation.cylinder(radius=10.0, height=50.0, sections=64)


@pytest.fixture
def plate_with_hole(cube_10mm) -> trimesh.Trimesh:
    """50×50×10 plate with a 5mm-radius hole through it."""
    def build():
        plate = trimesh.creation.box(extents=[50.0, 50.0, 10.0])
        drill = trimesh.creation.cylinder(radius=5.0, height=12.0, sections=64)
        return plate.difference(drill)
    return _try_csg(build)


@pytest.fixture
def hollow_box_02mm_wall() -> trimesh.Trimesh:
    """20mm cube with 19.6mm inner cavity → 0.2mm walls."""
    def build():
        outer = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
        inner = trimesh.creation.box(extents=[19.6, 19.6, 19.6])
        return outer.difference(inner)
    return _try_csg(build)


@pytest.fixture
def non_watertight_box() -> trimesh.Trimesh:
    """10mm cube with one face torn off so universal checks fail."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    return trimesh.Trimesh(
        vertices=mesh.vertices,
        faces=mesh.faces[:-2],
        process=False,
    )


# ──────────────────────────────────────────────────────────────
# Serialization helpers
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def stl_bytes_of():
    """Return a callable that serializes a mesh to binary STL bytes."""
    def _serialize(mesh: trimesh.Trimesh) -> bytes:
        buf = io.BytesIO()
        mesh.export(buf, file_type="stl")
        return buf.getvalue()
    return _serialize
