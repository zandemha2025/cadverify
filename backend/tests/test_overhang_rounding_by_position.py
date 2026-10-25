"""Moving a part changes no overhang finding, even for a face drawn at the limit.

trap-multi-lbracket-thin-steep-small has faces at exactly 50 degrees past
vertical, electron-beam printing's limit. A binary STL rounds coordinates to
float32, and 1.2 m from the origin that rounding is ~100x coarser: the same
faces read 139.9999995 degrees from up in place and 140.000245 moved, so the
moved file gained an EBM "Supports required". A face past the limit only by its
rounding now doesn't exceed it, in place or moved.
"""
from pathlib import Path

import numpy as np

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import ProcessType
from src.analysis.processes.base import get_analyzer
from src.parsers.stl_parser import parse_stl_from_bytes

TRAP = Path(__file__).parent / "trap-corpus" / "trap-multi-lbracket-thin-steep-small.stl"


def _codes(mesh, process):
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    return sorted(i.code for i in get_analyzer(process).analyze(ctx))


def test_moving_the_part_adds_no_overhang_at_the_limit():
    base = parse_stl_from_bytes(TRAP.read_bytes(), TRAP.name)
    moved = base.copy()
    moved.apply_translation((1234.5, -567.8, 250.0))
    moved = parse_stl_from_bytes(moved.export(file_type="stl"), "moved.stl")
    assert _codes(moved, ProcessType.EBM) == _codes(base, ProcessType.EBM)
    from src.analysis.context import rounding_angle_error_deg

    # The faces at the limit, each within its own rounding of exactly 140 degrees.
    for mesh in (base, moved):
        angles = np.degrees(np.arccos(np.clip(mesh.face_normals[:, 2], -1.0, 1.0)))
        at_limit = np.flatnonzero(np.abs(angles - 140.0) < 0.01)
        assert len(at_limit) == 2
        assert np.all(np.abs(angles[at_limit] - 140.0) <= rounding_angle_error_deg(mesh)[at_limit])
    assert "OVERHANG" not in _codes(base, ProcessType.EBM)


def test_a_real_overhang_past_the_limit_still_counts():
    # The same part's 45-degree printers (DMLS) still flag those faces.
    base = parse_stl_from_bytes(TRAP.read_bytes(), TRAP.name)
    assert "OVERHANG" in _codes(base, ProcessType.DMLS)
