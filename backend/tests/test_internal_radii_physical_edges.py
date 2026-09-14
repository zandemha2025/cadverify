from types import SimpleNamespace

import numpy as np

from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_internal_radii


def _ctx(lengths: list[float]):
    # Independent two-vertex edges keep this focused on the check\x27s physical
    # edge filter rather than trimesh boolean/tessellation implementation.
    vertices = []
    edges = []
    for length in lengths:
        base = len(vertices)
        vertices.extend(((0.0, 0.0, 0.0), (length, 0.0, 0.0)))
        edges.append((base, base + 1))
    mesh = SimpleNamespace(
        vertices=np.asarray(vertices, dtype=float),
        face_adjacency_edges=np.asarray(edges, dtype=int),
    )
    return SimpleNamespace(
        mesh=mesh,
        concave_mask=np.ones(len(edges), dtype=bool),
        dihedral_angles_rad=np.full(len(edges), np.radians(90.0)),
    )


def test_single_physical_internal_corner_is_not_hidden_by_edge_count_floor():
    issues = check_internal_radii(_ctx([12.0]), 0.5, ProcessType.CNC_3AXIS)
    assert [issue.code for issue in issues] == ["SHARP_INTERNAL_CORNERS"]


def test_sub_tool_radius_tessellation_chords_do_not_fake_internal_corners():
    # A segmented round hole may carry dozens of short concave mesh chords.
    assert check_internal_radii(_ctx([0.393] * 64), 0.5, ProcessType.CNC_3AXIS) == []
