"""Routing + sheet-metal cost regression (procedural — always runs in CI).

Locks in the Cost-Truth routing/physics fixes:
  * a thin constant-gauge flat plate routes to SHEET_METAL (not led by MJF),
    with the geometric reasoning surfaced;
  * a compact block does NOT (no over-eager sheet routing);
  * the sheet-metal cycle time is an explainable physics model (cut/bend/handle),
    not a magic constant, and Σ(line_items) == unit_cost holds for it;
  * check_bends no longer hard-fails a flat plate as a "sharp bend".
"""
from __future__ import annotations

import pytest
import numpy as np
import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult, ProcessType, Severity
from src.analysis.processes import base as pbase
from src.analysis.processes.base import get_analyzer
from src.analysis.processes.checks import check_bends
import src.analysis.processes  # noqa: F401  populate registry
from src.matcher.profile_matcher import rank_processes, score_process

from src.costing import estimate_decision, EstimateOptions


def _analyze(mesh):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="part.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=universal,
                            process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx, ctx.features


def _flat_plate():
    # 2 mm constant-gauge plate, 120 x 280 — the canonical sheet panel
    return trimesh.creation.box(extents=[280.0, 120.0, 2.0])


def _compact_block():
    return trimesh.creation.box(extents=[40.0, 30.0, 25.0])


def _est(report, process):
    return [e for e in report.estimates if e["process"] == process]


# ── the headline: a flat plate routes to sheet metal ────────────────────────
def test_flat_plate_routes_to_sheet_metal():
    result, mesh, _ctx, feats = _analyze(_flat_plate())
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100, 5000]))
    assert report.status == "OK"
    # geometric routing recognizes the sheet archetype + surfaces reasoning
    assert report.routing is not None
    assert report.routing["archetype"] == "sheet_panel"
    assert report.routing["recommended_process"] == "sheet_metal"
    assert report.routing["reasoning"].strip()
    # sheet metal is costed and is the cheapest make-now headline (not MJF)
    sheets = _est(report, "sheet_metal")
    assert sheets, "sheet metal must be costable for a flat plate"
    assert report.decision.make_now_process == "sheet_metal"
    # DFM-ready (the inverted bend check no longer hard-fails a flat plate)
    assert sheets[0]["dfm_verdict"] != "fail"


def test_sheet_cycle_is_explainable_and_sums():
    result, mesh, _ctx, feats = _analyze(_flat_plate())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    sheet = _est(report, "sheet_metal")[0]
    # Σ invariant (gate G3) holds for the new fabrication line
    assert abs(sheet["unit_cost_usd"] - round(sum(sheet["line_items"].values()), 2)) < 0.02
    # the cycle-time driver explains itself from cut/bend/handling (no magic const)
    cyc = next(d for d in sheet["drivers"] if d["name"] == "cycle_time")
    assert "cut" in cyc["source"] and "handling" in cyc["source"]
    # every driver still carries provenance + a non-empty source (gate G6)
    for d in sheet["drivers"]:
        assert d["source"].strip()
        assert d["provenance"] in ("MEASURED", "USER", "DEFAULT", "SHOP")


# ── guard: a compact block must NOT route to sheet metal ────────────────────
def test_compact_block_not_sheet():
    result, mesh, _ctx, feats = _analyze(_compact_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    assert report.routing["archetype"] != "sheet_panel"
    assert not _est(report, "sheet_metal"), "a solid block is not a sheet part"


# ── the check_bends correctness fix ─────────────────────────────────────────
def test_check_bends_passes_flat_plate():
    """A flat plate has only flat (0°) and clean 90° edges — no knife-edge folds,
    so check_bends must return no SHARP_BEND error (the inverted-threshold bug)."""
    mesh = _flat_plate()
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    issues = check_bends(ctx, ProcessType.SHEET_METAL)
    assert not any(i.severity == Severity.ERROR for i in issues), (
        "flat plate must not be flagged as a sharp bend")


@pytest.mark.parametrize("z_offset", [0., 511.8, 253.1])
@pytest.mark.parametrize("angle", [0., 0.71])
@pytest.mark.parametrize("thickness,code,limit", [
    (0.2, "TOO_THIN_SHEET", 0.5), (0.3, "TOO_THIN_SHEET", 0.5),
    (0.4, "TOO_THIN_SHEET", 0.5), (0.49999, "TOO_THIN_SHEET", 0.5),
    (0.5, None, None), (0.8, None, None), (5.99999, None, None), (6., None, None),
    (6.00001, "TOO_THICK_SHEET", 6.), (7., "TOO_THICK_SHEET", 6.),
    (8., "TOO_THICK_SHEET", 6.), (8.00001, "TOO_THICK_SHEET", 6.),
])
def test_sheet_stock_range_matches_its_disclosed_limits(thickness, code, limit, z_offset, angle):
    mesh = trimesh.creation.box(extents=[30., 20., thickness])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [1, 2, 3]))
    mesh.apply_translation([0., 0., z_offset])
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    issues = get_analyzer(ProcessType.SHEET_METAL).analyze(ctx)
    gauge_issues = [i for i in issues if i.code in {"TOO_THIN_SHEET", "TOO_THICK_SHEET"}]
    if code is None:
        assert not gauge_issues
        return
    assert len(gauge_issues) == 1
    issue = gauge_issues[0]
    assert issue.code == code
    assert issue.measured_value == pytest.approx(thickness)
    assert issue.required_value == limit
    assert issue.measurement_unit == "mm"
    assert "default" in issue.message.lower()
    assert f"{limit:g}mm" in issue.message
    assert issue.severity == (Severity.ERROR if code == "TOO_THIN_SHEET" else Severity.WARNING)


@pytest.mark.parametrize("outline", ["rectangle", "triangle", "cutout"])
def test_sheet_rotation_preserves_gauge_cut_stock_cost_and_machine_fit(outline):
    from shapely.geometry import Polygon
    from src.costing.drivers import extract_drivers
    from src.costing.makeability import part_req_from_drivers, MachineCap, fit_machine
    polygons = {
        "rectangle": Polygon([(0, 0), (30, 0), (30, 20), (0, 20)]),
        "triangle": Polygon([(0, 0), (30, 0), (0, 20)]),
        "cutout": Polygon([(0, 0), (30, 0), (30, 20), (0, 20)],
                          holes=[[(10, 5), (15, 5), (15, 10), (10, 10)]]),
    }
    polygon = polygons[outline]
    mesh = trimesh.creation.extrude_polygon(polygon, .5)
    estimates = []
    for angle in (0., .71, 1.4):
        part = mesh.copy()
        part.apply_transform(trimesh.transformations.rotation_matrix(angle, [1, 2, 3]))
        part.apply_translation([100, -200, 300])
        result, _, ctx, feats = _analyze(part)
        drivers = extract_drivers(result.geometry, part, feats)
        assert drivers.sheet_gauge_mm == pytest.approx(.5)
        assert drivers.outline_perimeter_mm == pytest.approx(polygon.length, abs=.005)
        assert drivers.sheet_like
        assert drivers.bend_count == 0
        # World-space bounds remain truthful for the existing non-sheet routes.
        assert drivers.bbox_mm == tuple(round(d, 2) for d in sorted(part.extents))
        req = part_req_from_drivers("sheet_metal", drivers, "Aluminum 6061", "standard")
        assert req.bbox_mm[0] == pytest.approx(.5)
        assert req.bbox_mm[1] * req.bbox_mm[2] == pytest.approx(600)
        assert req.bbox_mm == pytest.approx((.5, 20, 30))
        assert req.thickness_mm == pytest.approx(.5)
        machine = MachineCap(process="sheet_metal", name="Exact-fit bed",
                             capabilities={"bed_x": 30, "bed_y": 20},
                             material_thickness_map={"Aluminum 6061": .5})
        assert not any(f.gate in {"envelope", "thickness"} for f in fit_machine(req, machine).failures)
        report = estimate_decision(result, part, feats, EstimateOptions(quantities=[100]))
        assert report.routing["archetype"] == "sheet_panel"
        sheet = _est(report, "sheet_metal")[0]
        assert sheet["dfm_verdict"] == "pass"
        estimates.append(sheet["line_items"])
    assert estimates[0] == estimates[1] == estimates[2]


def test_nonuniform_plate_does_not_claim_its_envelope_is_sheet_gauge():
    # A shallow stepped part used to look like a flat sheet by its 2V/A proxy.
    profile = np.array([[0, 0], [30, 0], [30, .5], [20, .5],
                        [20, 2], [10, 2], [10, .5], [0, .5]])
    from shapely.geometry import Polygon
    from src.costing.drivers import extract_drivers
    mesh = trimesh.creation.extrude_polygon(Polygon(profile), 20)
    result, _, ctx, feats = _analyze(mesh)
    issues = get_analyzer(ProcessType.SHEET_METAL).analyze(ctx)
    assert any(i.code == "SHEET_GAUGE_UNVERIFIED" for i in issues)
    assert not any(i.code in {"TOO_THIN_SHEET", "TOO_THICK_SHEET"} for i in issues)
    assert not extract_drivers(result.geometry, mesh, feats).sheet_like


@pytest.mark.parametrize("diameter", [.4, .5, .6])
def test_sheet_hole_limit_uses_gauge_in_any_orientation(diameter):
    from src.analysis.features.base import Feature, FeatureKind
    for angle in (0., .71):
        mesh = trimesh.creation.box(extents=[30., 20., .5])
        mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [1, 2, 3]))
        mesh.apply_translation([100, -200, 511.8])
        ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
        ctx.features = [Feature(kind=FeatureKind.CYLINDER_HOLE, face_indices=[],
                                centroid=(100, -200, 511.8), radius=diameter / 2)]
        issues = get_analyzer(ProcessType.SHEET_METAL).analyze(ctx)
        assert any(i.code == "SMALL_HOLE_SHEET" for i in issues) == (diameter < .5)


@pytest.mark.parametrize("thickness", [4.5, 5.0, 5.00001])
def test_sheet_classification_boundary_survives_rotation(thickness):
    from src.costing.drivers import extract_drivers
    for angle in (0., .1, .71):
        mesh = trimesh.creation.box(extents=[30., 20., thickness])
        mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [1, 2, 3]))
        drivers = extract_drivers(analyze_geometry(mesh), mesh)
        assert drivers.sheet_like == (thickness <= 5.)


def test_sheet_machine_numeric_tolerance_does_not_allow_real_overage():
    from src.costing.drivers import extract_drivers
    from src.costing.makeability import part_req_from_drivers, MachineCap, fit_machine
    mesh = trimesh.creation.box(extents=[30.00001, 20., .50001])
    drivers = extract_drivers(analyze_geometry(mesh), mesh)
    req = part_req_from_drivers("sheet_metal", drivers, "Aluminum 6061", "standard")
    machine = MachineCap(process="sheet_metal", name="Too small",
                         capabilities={"bed_x": 30, "bed_y": 20},
                         material_thickness_map={"Aluminum 6061": .5})
    assert {f.gate for f in fit_machine(req, machine).failures} >= {"envelope", "thickness"}


@pytest.mark.parametrize("outline,bed,fits", [
    ([(0, 0), (30, 0), (0, 20)], (31, 21), True),
    ([(0, 0), (30, 0), (0, 20)], (37, 18), True),
    ([(0, 0), (30, 0), (0, 20)], (30, 15), False),
    ([(0, 0), (60, 0), (60, 5), (0, 5)], (46, 46), True),
    ([(0, 0), (60, 0), (60, 5), (0, 5)], (45, 45), False),
])
def test_sheet_machine_considers_all_in_plane_orientations(outline, bed, fits):
    from shapely.geometry import Polygon
    from src.costing.drivers import extract_drivers
    from src.costing.makeability import part_req_from_drivers, MachineCap, fit_machine
    for angle in (0., .1, .71):
        mesh = trimesh.creation.extrude_polygon(Polygon(outline), .5)
        mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [1, 2, 3]))
        drivers = extract_drivers(analyze_geometry(mesh), mesh)
        req = part_req_from_drivers("sheet_metal", drivers, "Aluminum 6061", "standard")
        machine = MachineCap(process="sheet_metal", name="Bed", capabilities={"bed_x": bed[0], "bed_y": bed[1]})
        assert (not any(f.gate == "envelope" for f in fit_machine(req, machine).failures)) == fits
