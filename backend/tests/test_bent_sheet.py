"""Bent sheet parts read as sheet metal and get a sheet price (M9).

An L bracket (3 mm, one bend) passed the sheet DFM check but was read as a
"thin-wall hollow shell" and routed to metal printing, with no sheet-metal
price: only flat blanks were ever sheet-costable.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest
import trimesh
from shapely.geometry import LineString

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext, bent_sheet_geometry
from src.analysis.features import detect_all
from src.analysis.models import AnalysisResult, ProcessType
from src.analysis.processes import get_analyzer
from src.costing import EstimateOptions, estimate_decision
from src.matcher.profile_matcher import score_process


def _strip(points, t=3.0, width=30.0, fillet=0.0):
    """A strip of thickness t along ``points``, extruded ``width``; optional inside radius."""
    pts = [np.asarray(p, float) for p in points]
    line = pts
    if fillet:
        out, r_mid = [pts[0]], fillet + t / 2
        for a, b, c in zip(pts, pts[1:], pts[2:]):
            u = (a - b) / np.linalg.norm(a - b)
            v = (c - b) / np.linalg.norm(c - b)
            half = np.arccos(np.clip(u @ v, -1, 1)) / 2
            centre = b + (u + v) / np.linalg.norm(u + v) * r_mid / np.sin(half)
            p1, p2 = b + u * r_mid / np.tan(half), b + v * r_mid / np.tan(half)
            a1, a2 = (np.arctan2(*(p - centre)[::-1]) for p in (p1, p2))
            if a2 - a1 > np.pi:
                a2 -= 2 * np.pi
            if a1 - a2 > np.pi:
                a2 += 2 * np.pi
            out += [centre + r_mid * np.array([np.cos(x), np.sin(x)]) for x in np.linspace(a1, a2, 16)]
        line = [*out, pts[-1]]
    poly = LineString(line).buffer(t / 2, cap_style=2, join_style=2 if not fillet else 1)
    return trimesh.creation.extrude_polygon(poly, width)


def test_l_u_and_z_profiles_read_with_their_bends():
    l_sharp = bent_sheet_geometry(_strip([(0, 40), (0, 0), (40, 0)]))
    assert l_sharp is not None and l_sharp.bends == 1
    assert (l_sharp.gauge_mm, l_sharp.width_mm, l_sharp.developed_mm) == pytest.approx((3.0, 30.0, 80.0), abs=1e-6)
    assert l_sharp.min_inside_radius_mm == 0.0
    assert bent_sheet_geometry(_strip([(0, 30), (0, 0), (50, 0), (50, 30)])).bends == 2
    assert bent_sheet_geometry(_strip([(0, 20), (0, 0), (30, 0), (30, -20)])).bends == 2
    radiused = bent_sheet_geometry(_strip([(0, 40), (0, 0), (40, 0)], fillet=3.0))
    assert radiused is not None and radiused.bends == 1 and radiused.min_inside_radius_mm >= 3.0


@pytest.mark.parametrize("mesh", [trimesh.creation.box(extents=[30, 30, 30]),
                                  trimesh.creation.box(extents=[100, 60, 3]),
                                  trimesh.creation.annulus(r_min=15, r_max=20, height=80),
                                  trimesh.creation.cylinder(radius=10, height=60)])
def test_blocks_plates_and_tubes_are_not_bent_sheets(mesh):
    assert bent_sheet_geometry(mesh) is None


def _report(mesh, material_class="aluminum"):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    ctx.features = detect_all(ctx.mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p) for p in ProcessType]
    result = AnalysisResult(filename="bracket.stl", file_type="stl", geometry=geometry, segments=[],
                            universal_issues=[], process_scores=scores, analysis_time_ms=0.0)
    report = estimate_decision(result, mesh, ctx.features,
                               EstimateOptions(quantities=[1, 100], material_class=material_class,
                                               material_class_is_user=True))
    return report, {s.process: s for s in scores}


@pytest.mark.skipif(importlib.util.find_spec("gmsh") is None, reason="gmsh is not installed")
def test_design_studio_bracket_gets_a_sheet_metal_price_and_route():
    from src.api import routes
    from src.designs.generator import generate_design_artifacts

    art = generate_design_artifacts({"kind": "bracket", "width_mm": 40.0, "depth_mm": 30.0,
                                     "height_mm": 40.0, "thickness_mm": 3.0}, timeout_seconds=60.0)
    mesh, _ = routes._parse_mesh(art.stl_bytes, "bracket.stl")
    report, scores = _report(mesh)
    sheet = [e for e in report.estimates if e["process"] == "sheet_metal"]
    assert sheet and all(e["unit_cost_usd"] > 0 for e in sheet)
    assert report.routing["archetype"] == "sheet_panel"
    assert "bent once" in report.routing["reasoning"]
    bends = next(d for d in sheet[0]["drivers"] if d["name"] == "cycle_time")["source"]
    assert "bends 1×" in bends
    codes = {i.code for i in scores[ProcessType.SHEET_METAL].issues}
    assert "SHEET_GAUGE_UNVERIFIED" not in codes and "BEND_RADIUS_UNDER_GAUGE" in codes
    assert scores[ProcessType.SHEET_METAL].verdict != "fail"


def test_a_radiused_bracket_has_no_bend_radius_warning():
    mesh = _strip([(0, 40), (0, 0), (40, 0)], fillet=3.0)
    _report_, scores = _report(mesh)
    assert "BEND_RADIUS_UNDER_GAUGE" not in {i.code for i in scores[ProcessType.SHEET_METAL].issues}
