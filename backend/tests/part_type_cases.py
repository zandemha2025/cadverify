"""Generated multi-body cases for the part-type tests: each a binary STL, as exported.

Bodies are concatenated without being joined, so where members touch they may
share vertices and edges, the way CAD tools export a weldment as one STL.
"""
from __future__ import annotations

import io

import numpy as np
import trimesh
from shapely.geometry import Polygon


def box(lo, hi) -> trimesh.Trimesh:
    lo = np.asarray(lo, float)
    hi = np.asarray(hi, float)
    b = trimesh.creation.box(extents=hi - lo)
    b.apply_translation((lo + hi) / 2)
    return b


def tube_x(x0, x1, y0, z0, w=40.0, t=3.0) -> trimesh.Trimesh:
    """Square tube along X, outer w x w, wall t."""
    return box([x0, y0, z0], [x1, y0 + w, z0 + w]).difference(
        box([x0 - 1, y0 + t, z0 + t], [x1 + 1, y0 + w - t, z0 + w - t]))


def tube_y(y0, y1, x0, z0, w=40.0, t=3.0) -> trimesh.Trimesh:
    return box([x0, y0, z0], [x0 + w, y1, z0 + w]).difference(
        box([x0 + t, y0 - 1, z0 + t], [x0 + w - t, y1 + 1, z0 + w - t]))


def bent_l(thick=5.0, r_in=5.0, leg=60.0, width=100.0) -> trimesh.Trimesh:
    """One bent sheet: an L profile with an inside bend radius, extruded 100 mm."""
    ro = r_in + thick
    ang = np.linspace(np.pi, 1.5 * np.pi, 16)
    outer = [(ro + ro * np.cos(a), ro + ro * np.sin(a)) for a in ang]
    inner = [(ro + r_in * np.cos(a), ro + r_in * np.sin(a)) for a in ang[::-1]]
    pts = [(0.0, leg)] + outer + [(leg, 0.0), (leg, thick)] + inner + [(thick, leg)]
    m = trimesh.creation.extrude_polygon(Polygon(pts).buffer(0), width)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    return m


def stl(*bodies: trimesh.Trimesh) -> bytes:
    buf = io.BytesIO()
    trimesh.util.concatenate(list(bodies)).export(buf, file_type="stl")
    return buf.getvalue()


def two_cubes() -> bytes:
    return stl(box([0, 0, 0], [30, 30, 30]), box([50, 0, 0], [80, 30, 30]))


def cube_with_fixture() -> bytes:
    """A 40 mm cube seated in the pocket of a 120 x 80 x 20 fixture block (1 mm clearance)."""
    fixture = box([0, 0, 0], [120, 80, 20]).difference(box([39, 19, 10], [81, 61, 21]))
    return stl(fixture, box([40, 20, 10], [80, 60, 50]))


def welded_frame() -> bytes:
    """600 x 400 frame of 40 x 40 x 3 tube: two 600 mm rails, two 320 mm cross members butted between."""
    return stl(tube_x(0, 600, 0, 0), tube_x(0, 600, 360, 0), tube_y(40, 360, 0, 0), tube_y(40, 360, 560, 0))


def t_joint() -> bytes:
    """A 10 mm plate standing on its edge on another (200 mm long joint)."""
    return stl(box([0, 0, 0], [200, 100, 10]), box([0, 45, 10], [200, 55, 110]))


def l_bracket_welded() -> bytes:
    """Two 5 mm plates welded into an L (they share the corner edge)."""
    return stl(box([0, 0, 0], [100, 60, 5]), box([0, 0, 5], [100, 5, 60]))


def l_bracket_bent() -> bytes:
    return stl(bent_l())


def cube() -> bytes:
    return stl(box([0, 0, 0], [40, 40, 40]))


def cube_with_void() -> bytes:
    inner = box([10, 10, 10], [30, 30, 30])
    inner.invert()
    return stl(box([0, 0, 0], [40, 40, 40]), inner)
