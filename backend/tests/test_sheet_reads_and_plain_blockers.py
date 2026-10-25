"""Sheet reads that hold on real tessellations, and blockers in plain words.

M9 (flat half): a 3 mm plate with round holes, from Design Studio's STL or
its STEP, was not read as a flat sheet: the tessellated hole walls lean a few
degrees off square, and the flat-sheet test demanded exactly square walls. It
now gets a sheet-metal price.
M21: a tube's 80 mm length read as the "gauge", so its bore was reported as
"Hole Ø30mm < gauge 80mm".
C7 / C8: the turning and work-area blockers spoke in eigenvalue ratios and
"necessary bound is not a machine specification".
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext, envelope_nonfit_bound, flat_sheet_geometry
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes import get_analyzer

needs_gmsh = pytest.mark.skipif(importlib.util.find_spec("gmsh") is None, reason="gmsh is not installed")

_PLATE = {"kind": "plate", "width_mm": 100.0, "depth_mm": 60.0, "thickness_mm": 3.0,
          "holes": [{"x_mm": -35.0, "y_mm": 0.0, "diameter_mm": 6.0},
                    {"x_mm": 35.0, "y_mm": 0.0, "diameter_mm": 6.0}]}


def _ctx(mesh):
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_all(ctx.mesh)
    return ctx


def _issues(mesh, process):
    return get_analyzer(process).analyze(_ctx(mesh))


@pytest.fixture(scope="module")
def studio_plate():
    from src.designs.generator import generate_design_artifacts

    return generate_design_artifacts(_PLATE, timeout_seconds=60.0)


@needs_gmsh
@pytest.mark.parametrize("name", ["preview.stl", "model.step"])
def test_plate_with_holes_reads_as_a_3mm_flat_sheet(studio_plate, name):
    from src.api import routes

    data = studio_plate.stl_bytes if name.endswith(".stl") else studio_plate.step_bytes
    mesh, _ = routes._parse_mesh(data, name)
    measured = flat_sheet_geometry(mesh)
    assert measured is not None, name
    gauge, short, long = measured[0]
    assert gauge == pytest.approx(3.0, abs=1e-3)
    assert (short, long) == (pytest.approx(60.0, abs=1e-2), pytest.approx(100.0, abs=1e-2))
    codes = {i.code for i in _issues(mesh, ProcessType.SHEET_METAL)}
    assert "SHEET_GAUGE_UNVERIFIED" not in codes and "NOT_SHEET_STOCK" not in codes


@needs_gmsh
def test_plate_with_holes_gets_a_sheet_metal_price(studio_plate):
    from src.api import routes
    from src.costing import EstimateOptions, estimate_decision

    mesh, _ = routes._parse_mesh(studio_plate.stl_bytes, "preview.stl")
    result, mesh, ctx = routes._run_cost_engine_ctx(mesh, "preview.stl")
    report = estimate_decision(result, mesh, ctx.features,
                               EstimateOptions(quantities=[1, 100], material_class="aluminum"))
    sheet = [e for e in report.estimates if e["process"] == "sheet_metal"]
    assert sheet and all(e["unit_cost_usd"] > 0 for e in sheet)
    assert report.routing["archetype"] == "sheet_panel"


@needs_gmsh
def test_a_drafted_plate_is_still_not_a_flat_sheet():
    from src.api import routes
    from src.designs.generator import generate_design_artifacts

    drafted = generate_design_artifacts({"kind": "plate", "width_mm": 80.0, "depth_mm": 50.0,
                                         "thickness_mm": 6.0, "draft_angle_deg": 2.0}, timeout_seconds=60.0)
    mesh, _ = routes._parse_mesh(drafted.stl_bytes, "preview.stl")
    assert flat_sheet_geometry(mesh) is None


def _tube():
    return trimesh.creation.annulus(r_min=15.0, r_max=20.0, height=80.0, sections=128)


def test_tube_bore_is_not_compared_with_its_length():
    issues = _issues(_tube(), ProcessType.SHEET_METAL)
    codes = {i.code for i in issues}
    assert "SMALL_HOLE_SHEET" not in codes
    assert not any("gauge 80" in i.message for i in issues)
    # It is still not sheet: thicker than any sheet gauge, an error.
    assert any(i.code in {"TOO_THICK_SHEET", "NOT_SHEET_STOCK"} and i.severity.value == "error" for i in issues)


@pytest.mark.parametrize("mesh", [trimesh.creation.box(extents=[30, 30, 30]),
                                  trimesh.creation.box(extents=[120, 12, 12])])
def test_a_block_or_bar_still_cant_be_sheet_metal(mesh):
    issues = _issues(mesh, ProcessType.SHEET_METAL)
    assert any(i.severity.value == "error" for i in issues)


def test_turning_blocker_says_why_in_plain_words():
    (issue,) = [i for i in _issues(trimesh.creation.box(extents=[30, 30, 30]), ProcessType.CNC_TURNING)
                if i.code == "NOT_ROTATIONALLY_SYMMETRIC"]
    assert "eigenvalue" not in issue.message and "cnc_turning" not in issue.message
    assert issue.message == "A lathe can't make this part as drawn: no round outer surface was found to turn."
    (flat,) = [i for i in _issues(trimesh.creation.box(extents=[60, 40, 20]), ProcessType.CNC_TURNING)
               if i.code == "NOT_ROTATIONALLY_SYMMETRIC"]
    assert flat.message == "A lathe can't make this part as drawn: it isn't round about any axis."


def test_work_area_bound_in_plain_words():
    axis, need, have, human = envelope_nonfit_bound((1100.0, 1200.0, 2000.0), (406.0, 762.0, 508.0),
                                                    minimum_width=1099.99963)
    assert axis == "minimum_width_mm" and need == pytest.approx(1099.99963) and have == 406.0
    assert human == ("Part is at least 1099.9mm wide at its narrowest > the 406mm shortest side of "
                     "the work area, so it fits in no orientation.")
    assert "necessary bound" not in human and "specification" not in human
    axis, need, have, human = envelope_nonfit_bound((10.0, 10.0, 2000.0), (406.0, 762.0, 508.0))
    assert axis == "diameter_mm" and need > have
    assert human.startswith("Part is at least 2000mm corner to corner > the ")
    assert np.isclose(have, np.linalg.norm([406.0, 762.0, 508.0]))
