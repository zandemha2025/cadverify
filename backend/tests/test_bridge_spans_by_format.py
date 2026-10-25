"""Filament printing's bridge rule gives a STEP the same answer as its STL.

A flat span counts as a bridge when both of its ends rest on the part below.
"Rests on" was read from the face across the span's edge: its centre had to sit
0.1 mm or more below the edge. A STEP's wall is meshed in triangles a fraction
of a millimetre tall along that edge, so no wall under a STEP's span ever
qualified: an 8 mm span printed as a bridge from the STL but needed support
from the STEP, and a 20 mm span lost the sentence saying why it is counted
(longer than the 10 mm a desktop printer bridges). The wall's direction now
decides, the same for any mesh.
"""
from pathlib import Path

import pytest
import trimesh

gmsh = pytest.importorskip("gmsh")


def _frame_step(tmp_path: Path, span: float) -> bytes:
    path = tmp_path / f"frame-{span:g}.step"
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("frame")
        occ = gmsh.model.occ
        left = occ.addBox(0, 0, 0, 5, 20, 20)
        right = occ.addBox(5 + span, 0, 0, 5, 20, 20)
        top = occ.addBox(0, 0, 20, 10 + span, 20, 5)
        occ.fuse([(3, top)], [(3, left), (3, right)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path.read_bytes()


def _frame_stl(span: float) -> bytes:
    def box(ext, at):
        m = trimesh.creation.box(extents=ext)
        m.apply_translation([a + e / 2 for a, e in zip(at, ext)])
        return m

    parts = [box((5, 20, 20), (0, 0, 0)), box((5, 20, 20), (5 + span, 0, 0)), box((10 + span, 20, 5), (0, 0, 20))]
    return trimesh.boolean.union(parts, engine="manifold").export(file_type="stl")


def _fdm_overhang(data: bytes, filename: str):
    from src.api.routes import _parse_mesh, _run_cost_engine_ctx

    mesh, _ = _parse_mesh(data, filename)
    result, _m, _ctx = _run_cost_engine_ctx(mesh, filename)
    fdm = next(s for s in result.process_scores if s.process.value == "fdm")
    return next((i for i in fdm.issues if i.code == "OVERHANG"), None)


def test_a_short_span_is_a_bridge_from_either_file(tmp_path):
    assert _fdm_overhang(_frame_stl(8.0), "frame-8.stl") is None
    assert _fdm_overhang(_frame_step(tmp_path, 8.0), "frame-8.step") is None


def test_a_long_span_says_why_it_needs_support_from_either_file(tmp_path):
    why = "A flat span between walls is 20 mm across, longer than the 10 mm a desktop printer bridges"
    for data, name in ((_frame_stl(20.0), "frame-20.stl"), (_frame_step(tmp_path, 20.0), "frame-20.step")):
        issue = _fdm_overhang(data, name)
        assert issue is not None and "Supports required." in issue.message
        assert why in issue.message, name
