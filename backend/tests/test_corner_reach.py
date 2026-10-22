"""Milling's inside corners: the radius follows the depth, deep small radii need reach, and the
corner fix rounds only the corners the finding names (de-14, de-15)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

import src.analysis.processes  # noqa: F401  (registers the analyzers)
from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes.base import get_analyzer
from src.analysis.processes.checks import reach_radius_mm
from src.parsers import step_mesher as sm


def _pocket_step(path: Path, depth: float, corner_radius: float = 0.0) -> Path:
    """An 80 × 60 × 30 mm block with a 60 × 40 mm pocket ``depth`` deep, its vertical corners
    sharp or rounded ``corner_radius`` (the floor edges stay sharp)."""
    import gmsh

    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("pocket")
        occ = gmsh.model.occ
        block = occ.addBox(0, 0, 0, 80, 60, 30)
        tool = occ.addBox(10, 10, 30 - depth, 60, 40, depth + 5)
        occ.synchronize()
        if corner_radius > 0:
            surfaces = gmsh.model.getBoundary([(3, tool)], oriented=False)
            edges = sorted({abs(t) for d, t in gmsh.model.getBoundary(surfaces, combined=False, oriented=False) if d == 1})
            vertical = []
            for e in edges:
                x0, y0, _z0, x1, y1, _z1 = gmsh.model.getBoundingBox(1, e)
                if abs(x1 - x0) < 1e-6 and abs(y1 - y0) < 1e-6:
                    vertical.append(e)
            occ.cut([(3, block)], occ.fillet([tool], vertical, [corner_radius]))
        else:
            occ.cut([(3, block)], [(3, tool)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path


def _milling(path: Path) -> dict:
    """3-axis milling's findings on the part, meshed the way the mesher does (coarser, for speed)."""
    cad: dict = {}
    verts, faces = sm._tessellate_once(str(path), None, sm._CURVATURE_PTS, False, target_diag_segments=80, cad=cad)
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    assert cad and len(cad[sm.CAD_FACES_KEY]) == len(mesh.faces)
    mesh.metadata.update(cad)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_all(ctx.mesh)
    return {i.code: i for i in get_analyzer(ProcessType.CNC_3AXIS).analyze(ctx)}


def test_reach_radius_follows_depth():
    # A standard end mill cuts about 3x its diameter: 20 mm deep needs Ø6.7, R3.4 rounded up.
    assert reach_radius_mm(20.0, 0.5) == 3.4
    assert reach_radius_mm(2.0, 0.5) == 0.5  # shallow: the smallest end mill's radius still rules
    assert reach_radius_mm(6.0, 0.5) == 1.0


def test_deep_sharp_corners_need_the_radius_a_cutter_reaches(tmp_path):
    """de-14: the 20 mm deep pocket asked R0.5 (a Ø1 cutter at 20× its diameter)."""
    issue = _milling(_pocket_step(tmp_path / "deep.step", 20.0))["SHARP_INTERNAL_CORNERS"]
    assert issue.required_value == 3.4
    assert issue.message.startswith("4 sharp concave corners between walls (80 mm of edge, the deepest runs 20 mm deep)")
    assert "at least R3.4" in issue.message
    assert "R6.7 (a third of the depth)" in issue.fix_suggestion
    assert issue.citation is not None and "Protolabs Network" in (issue.citation.standard or issue.citation.text or "")


def test_shallow_sharp_corners_keep_the_smallest_cutter(tmp_path):
    issue = _milling(_pocket_step(tmp_path / "shallow.step", 2.0))["SHARP_INTERNAL_CORNERS"]
    assert issue.required_value == 0.5
    assert "0.5mm radius" in issue.message


def test_small_radius_deep_corners_get_a_tool_reach_finding(tmp_path):
    found = _milling(_pocket_step(tmp_path / "r05.step", 20.0, corner_radius=0.5))
    assert "SHARP_INTERNAL_CORNERS" not in found
    reach = found["TOOL_REACH"]
    assert reach.measured_value == pytest.approx(0.5, abs=1e-6) and reach.required_value == 3.4
    assert "R0.5 runs 20 mm deep" in reach.message and "20× its diameter" in reach.message
    assert reach.cad_face_count == 4  # the four rounded corners, as the CAD tool shows them
    # Rounded enough for its depth: nothing to say.
    assert "TOOL_REACH" not in _milling(_pocket_step(tmp_path / "r6.step", 20.0, corner_radius=6.0))


def test_corner_fix_rounds_the_flagged_corners_not_the_floor(tmp_path):
    """de-15: R6 on the 20 mm pocket adds 4 × (36 − 9π) × 20 ≈ 618 mm³, not the floor's fillets too."""
    from src.fixes import brep_fixes as bf
    from src.services import cad_fix_service as svc

    raw = _pocket_step(tmp_path / "fix.step", 20.0).read_bytes()
    result = {"process_scores": [{"process": "cnc_3axis", "issues": [
        {"code": "SHARP_INTERNAL_CORNERS", "required_value": 3.4, "severity": "warning"}]},
        {"process": "die_casting", "issues": [{"code": "MISSING_FILLETS", "required_value": 1.0}]}]}
    params = svc.resolve_params(svc.FIXES["fillet_inside_corners"], None, result, ".step")
    assert params == {"radius_mm": 3.4, "edges": "corners"}
    params["radius_mm"] = 6.0
    out = bf.run_fix("fillet_inside_corners", raw, ".step", params)
    assert out.applied, out.reason
    assert out.details["edges_rounded"] == 4 and out.details["edges"] == "corners"
    added = out.details["brep_volume_after_mm3"] - out.details["brep_volume_before_mm3"]
    assert added == pytest.approx(4 * (36 - 9 * np.pi) * 20, rel=0.01)
    # Casting's fillets (no milling finding): every sharp inside edge, the floor's too.
    only_casting = {"process_scores": [{"process": "die_casting", "issues": [{"code": "MISSING_FILLETS", "required_value": 1.0}]}]}
    assert svc.resolve_params(svc.FIXES["fillet_inside_corners"], None, only_casting, ".step")["edges"] == "all"
    everything = bf.run_fix("fillet_inside_corners", raw, ".step", {"radius_mm": 6.0, "edges": "all"})
    assert everything.applied and everything.details["edges_rounded"] == 8
    with pytest.raises(svc.FixRequestError):
        svc.resolve_params(svc.FIXES["fillet_inside_corners"], None, result, ".step", "floor")
