"""A press brake is fitted as a press brake (me-02).

A job shop declared its Amada HG-1003 press brake with the same work area X/Y/Z
box a mill gets, and its real limits (100 t, 10 ft bed, 3/16 in in stainless) in
Notes, which the checker can't read. Her 0.197 in (5.0 mm) stainless bracket
then "cleared every check" on the brake, and "Bend and cut" was priced in-house
in a shop with no laser or punch to cut the blank.

A sheet-metal machine now says what it is (``sheet_kind``). A press brake is
fitted on its bend length, its press force against the force to air-bend the
part, and the thickest sheet it bends per material; a cutter on its bed and the
thickest sheet it cuts. A brake's bent part needs a blank: cut on a cutter of
yours that fits it, else bought outside, and the fit says which.
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh
from shapely.geometry import LineString

from src.analysis.base_analyzer import analyze_geometry
from src.costing.drivers import extract_drivers
from src.costing.makeability import (
    MachineCap,
    bend_force_t,
    fit_machine,
    part_req_from_drivers,
    verify_part,
)
from src.profiles.database import get_material_by_name


def _strip(points, t=5.0, width=40.0):
    """A sheet of thickness t bent along ``points``, extruded ``width`` (the bend length)."""
    poly = LineString([np.asarray(p, float) for p in points]).buffer(t / 2, cap_style=2, join_style=2)
    return trimesh.creation.extrude_polygon(poly, width)


def _req(mesh, material="SS316L"):
    g = analyze_geometry(mesh)
    d = extract_drivers(g, mesh)
    mat = get_material_by_name(material)
    return part_req_from_drivers("sheet_metal", d, mat, None)


def _amada(**over):
    """Her Amada HG-1003 as the new form declares it: 100 t, 10 ft (3048 mm) bend
    length, 1/4 in in mild steel and 3/16 in (4.7625 mm) in stainless."""
    caps = {"sheet_kind": "press_brake", "max_bend_length_mm": 3048.0, "tonnage_t": 100.0}
    caps.update(over.pop("caps", {}))
    kw = dict(process="sheet_metal", name="Amada HG-1003 press brake", max_workpiece_kg=23.0,
              hourly_rate_usd=70.0, materials=("steel", "stainless", "aluminum"),
              material_thickness_map={"steel": 6.35, "stainless": 4.7625}, capabilities=caps)
    kw.update(over)
    return MachineCap(**kw)


BRACKET = [(0, 57.5), (0, 0), (37.5, 0)]  # an L: 5 mm sheet, one bend, 40 mm bend lines


def test_bend_force_is_the_air_bending_rule():
    # F = 1.42 × Rm × s² × L ÷ V, V = 8 s: 1.42 × 550 MPa × 5² mm² × 0.040 m ÷ 40 mm = 19.525 kN
    # = 19.525 ÷ 9.80665 = 1.9910 t.
    assert bend_force_t(550, 5.0, 40.0) == pytest.approx(19.525 / 9.80665, rel=1e-9)
    assert bend_force_t(None, 5.0, 40.0) is None
    assert bend_force_t(550, 0.0, 40.0) is None


def test_the_bracket_is_measured_as_a_bent_sheet_with_its_bend_length():
    req = _req(_strip(BRACKET))
    assert req.bend_count == 1
    assert req.bend_length_mm == pytest.approx(40.0, abs=1e-6)
    assert req.thickness_mm == pytest.approx(5.0, abs=1e-6)
    # SS316L's tensile strength in the registry is 550 MPa.
    assert req.bend_force_t == pytest.approx(19.525 / 9.80665, rel=1e-6)


def test_her_0197_in_stainless_doesnt_clear_a_3_16_in_limit():
    fit = fit_machine(_req(_strip(BRACKET)), _amada())
    assert not fit.passes
    [f] = fit.failures
    assert (f.gate, f.need, f.have) == ("thickness", 5.0, 4.76)
    assert f.human == "thickness 5.00mm > machine max 4.7625mm for SS316L"
    # In 1/4 in mild steel it clears every brake check: bend length, force and thickness.
    fit = fit_machine(_req(_strip(BRACKET), material="Mild Steel"), _amada())
    assert fit.passes, fit.failures


def test_bend_length_and_press_force_are_checked_against_the_brake():
    req = _req(_strip(BRACKET), material="Mild Steel")
    short = fit_machine(req, _amada(caps={"max_bend_length_mm": 30.0}))
    [f] = short.failures
    assert (f.gate, f.axis, f.need, f.have) == ("envelope", "max_bend_length_mm", 40.0, 30.0)
    assert f.human == "too big for your Amada HG-1003 press brake: needs 40 mm, has 30 mm (bend length)"
    weak = fit_machine(req, _amada(caps={"tonnage_t": 0.5}))
    [f] = weak.failures
    # Mild Steel's tensile strength is 400 MPa: 1.42 × 400 × 5² × 0.040 ÷ 40 = 14.2 kN = 1.448 t.
    assert f.gate == "force" and f.have == 0.5 and f.need == pytest.approx(14.2 / 9.80665, abs=0.005)
    assert f.human == "needs 1.45 t to air-bend 40mm of 5.00mm Mild Steel; machine 0.5 t"
    # Not declared: unknown (have None), never a pass.
    bare = MachineCap(process="sheet_metal", name="Brake", max_workpiece_kg=23.0, materials=("steel",),
                      capabilities={"sheet_kind": "press_brake"})
    fit = fit_machine(req, bare)
    assert not fit.passes
    assert {(f.axis, f.have) for f in fit.failures} == {("max_bend_length_mm", None), ("tonnage_t", None)}


def test_a_flat_blank_is_cut_not_bent_and_a_cutter_doesnt_bend():
    flat = _req(trimesh.creation.box(extents=[120.0, 80.0, 3.0]), material="Mild Steel")
    assert flat.bend_count == 0 and flat.bend_length_mm is None
    fit = fit_machine(flat, _amada())
    assert not fit.passes and fit.failures[0].axis == "bend_count" and fit.failures[0].have == 0
    laser = MachineCap(process="sheet_metal", name="Trumpf TruLaser 3030", max_workpiece_kg=900.0, hourly_rate_usd=120.0,
                       materials=("steel", "stainless", "aluminum"), material_thickness_map={"steel": 20.0},
                       capabilities={"sheet_kind": "laser", "bed_x": 3000.0, "bed_y": 1500.0})
    assert fit_machine(flat, laser).passes
    bent = fit_machine(_req(_strip(BRACKET), material="Mild Steel"), laser)
    assert not bent.passes
    assert bent.failures[0].human == "cuts the blank; its 1 bend need a press brake"


def test_bend_and_cut_in_house_needs_a_cutter_otherwise_the_blank_is_bought_outside():
    req = _req(_strip(BRACKET), material="Mild Steel")
    v = verify_part({"sheet_metal": req}, [_amada()])
    res = v.per_route["sheet_metal"]["resource"]
    assert v.per_route["sheet_metal"]["best_machine"] == "Amada HG-1003 press brake"
    assert res["blank_outside"] is True
    assert "blank cut outside: no laser, punch, plasma or waterjet in Your shop" in res["notes"]
    laser = MachineCap(process="sheet_metal", name="Trumpf TruLaser 3030", max_workpiece_kg=900.0, hourly_rate_usd=120.0,
                       materials=("steel",), material_thickness_map={"steel": 20.0},
                       capabilities={"sheet_kind": "laser", "bed_x": 3000.0, "bed_y": 1500.0})
    v = verify_part({"sheet_metal": req}, [_amada(), laser])
    res = v.per_route["sheet_metal"]["resource"]
    assert v.per_route["sheet_metal"]["best_machine"] == "Amada HG-1003 press brake"
    assert res.get("blank_outside") is None and res["blank_on"] == "Trumpf TruLaser 3030"
    assert "blank cut on your Trumpf TruLaser 3030" in res["notes"]
    # A cutter too small for the blank: still outside, and the note says why.
    small = MachineCap(**{**laser.__dict__, "capabilities": {"sheet_kind": "laser", "bed_x": 50.0, "bed_y": 50.0}})
    res = verify_part({"sheet_metal": req}, [_amada(), small]).per_route["sheet_metal"]["resource"]
    assert res["blank_outside"] is True
    assert res["blank_note"].startswith("your Trumpf TruLaser 3030 can't cut it (")


def test_a_sheet_machine_with_no_kind_keeps_the_work_area_check():
    legacy = MachineCap(process="sheet_metal", name="Amada", max_workpiece_kg=23.0, materials=("steel",),
                        capabilities={"x": 3048.0, "y": 1219.2, "z": 304.8})
    fit = fit_machine(_req(_strip(BRACKET), material="Mild Steel"), legacy)
    assert fit.passes and "blank_outside" not in fit.resource_hint


def test_sheet_kind_is_validated_on_sheet_metal_machines_only():
    from src.services.machine_inventory_service import validate_machine

    validate_machine({"process": "sheet_metal", "capabilities": {"sheet_kind": "press_brake", "tonnage_t": 100,
                                                                 "max_bend_length_mm": 3048}})
    with pytest.raises(ValueError, match="sheet_kind must be one of"):
        validate_machine({"process": "sheet_metal", "capabilities": {"sheet_kind": "brake"}})
    with pytest.raises(ValueError, match="applies to sheet_metal machines only"):
        validate_machine({"process": "cnc_3axis", "capabilities": {"sheet_kind": "laser"}})


def test_a_brake_only_shop_prices_the_bracket_with_its_blank_cut_outside():
    """End to end, file to price: on her brake in mild steel the bracket is in-house,
    the bends at the brake's $70/h and the blank on its own "Blank cut outside" line."""
    from src.analysis.context import GeometryContext
    from src.analysis.features import detect_all
    from src.analysis.models import AnalysisResult, ProcessType
    from src.analysis.processes import get_analyzer
    from src.costing import EstimateOptions, estimate_decision
    from src.matcher.profile_matcher import score_process

    mesh = _strip(BRACKET)
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    ctx.features = detect_all(ctx.mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p) for p in ProcessType]
    result = AnalysisResult(filename="bracket.stl", file_type="stl", geometry=geometry, segments=[],
                            universal_issues=[], process_scores=scores, analysis_time_ms=0.0)
    brake = _amada(materials=("steel", "Mild Steel"))
    report = estimate_decision(result, mesh, ctx.features, EstimateOptions(
        quantities=[100], material_class="steel", material_class_is_user=True,
        inventory=(brake,), owned_processes=frozenset({ProcessType.SHEET_METAL})))
    fit = report.verification["per_route"]["sheet_metal"]
    assert fit["verdict"] == "makeable_in_house" and fit["best_machine"] == "Amada HG-1003 press brake"
    assert "blank cut outside: no laser, punch, plasma or waterjet in Your shop" in fit["notes"]
    est = next(e for e in report.estimates if e["process"] == "sheet_metal" and e["quantity"] == 100)
    assert est["line_items"].get("blank_outside", 0) > 0
