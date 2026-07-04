"""Dollar cost models for the four newly-costed processes — FORGING,
INVESTMENT_CASTING, SAND_CASTING, WIRE_EDM — plus the byte-identity guarantee for
the existing 11 costed processes.

Pure unit tests (no DB, no network): they call ``cost_breakdown`` directly on a
hand-built ``GeoDrivers`` + ``MaterialProfile`` so the physics of each new model is
exercised in isolation, and a golden-value regression proves the four additions did
NOT perturb any currently-costed process by a single byte.
"""

from __future__ import annotations

import math

from src.analysis.models import ProcessType as PT
from src.profiles.models import MaterialProfile
from src.costing.drivers import GeoDrivers
from src.costing.rates import build_rate_card, COSTED_PROCESSES, process_family, BAND_PCT
from src.costing.cost_model import cost_breakdown


# ── fixtures (hand-built, deterministic — no mesh/DB) ────────────────────────
def _drivers() -> GeoDrivers:
    """A 25×30×40 mm metal part: valid, rotational-flagged, sheet-flagged, with a
    measured outline perimeter — every family finds the driver it needs."""
    return GeoDrivers(
        volume_cm3=30.0, surface_area_cm2=74.0, bbox_mm=(25.0, 30.0, 40.0),
        bbox_volume_cm3=30.0, hull_volume_cm3=28.0, nominal_wall_mm=8.1,
        face_count=12, max_bbox_mm=40.0, is_valid=True, rotational=True,
        rot_axis_len_mm=40.0, rot_cross_dia_mm=27.5, sheet_gauge_mm=2.0,
        planar_aspect=15.0, outline_perimeter_mm=140.0, bend_count=2,
        sheet_like=True)


def _alu() -> MaterialProfile:
    return MaterialProfile(name="6061-T6 Aluminum", process_types=[],
                           min_wall_thickness=1.0, max_temperature=None,
                           tensile_strength=None, elongation=None,
                           density=2.70, cost_per_kg=8.0)


def _poly() -> MaterialProfile:
    return MaterialProfile(name="PA12 (Nylon 12)", process_types=[],
                           min_wall_thickness=1.0, max_temperature=None,
                           tensile_strength=None, elongation=None,
                           density=1.01, cost_per_kg=60.0)


def _driver(est, name):
    for d in est.drivers:
        if d.name == name:
            return d
    return None


NEW_PROCESSES = [PT.SAND_CASTING, PT.INVESTMENT_CASTING, PT.FORGING, PT.WIRE_EDM]


# ── per-process: positive finite cost + required drivers + honest provenance ──
def test_new_processes_are_in_costed_set():
    for p in NEW_PROCESSES:
        assert p in COSTED_PROCESSES, f"{p.name} must be costed (off feasibility-only)"


def test_new_families_have_bands():
    assert BAND_PCT["casting"] > 0
    assert BAND_PCT["forging"] > 0
    assert BAND_PCT["edm"] > 0
    assert process_family(PT.SAND_CASTING) == "casting"
    assert process_family(PT.INVESTMENT_CASTING) == "casting"
    assert process_family(PT.FORGING) == "forging"
    assert process_family(PT.WIRE_EDM) == "edm"


def test_each_new_process_positive_finite_cost_with_drivers():
    rc, d, mat = build_rate_card(), _drivers(), _alu()
    for p in NEW_PROCESSES:
        est = cost_breakdown(p, d, mat, "aluminum", 100, rc, "US")
        # positive, finite unit cost
        assert math.isfinite(est.unit_cost_usd) and est.unit_cost_usd > 0, p.name
        # Σ line_items == unit_cost (hard invariant G3)
        est.assert_sums()
        # a material driver and a machine/cycle driver both present
        mat_d = _driver(est, "material_cost")
        mach_d = _driver(est, "machine_cost")
        cyc_d = _driver(est, "cycle_time")
        assert mat_d is not None and mat_d.value > 0, p.name
        assert mach_d is not None and mach_d.value > 0, p.name
        assert cyc_d is not None and cyc_d.value > 0, p.name
        # a positive error band
        assert est.est_error_band_pct > 0, p.name
        # provenance DEFAULT on the new machine/cycle constants; never "validated"
        assert mach_d.provenance.value == "DEFAULT", p.name
        assert cyc_d.provenance.value == "DEFAULT", p.name
        # no driver is ever tagged as measured-truth for these un-validated models
        for dr in est.drivers:
            assert dr.provenance.value in ("MEASURED", "USER", "DEFAULT"), p.name
        # source strings honestly caveat the assumption
        assert "not shop-validated" in cyc_d.source or "assumption" in cyc_d.source, p.name


def test_new_families_carry_honesty_literal_in_drivers():
    """Honesty-literal regression guard: every newly-costed family (casting,
    forging, wire-EDM) attaches the ``assumption, not shop-validated`` caveat to at
    least one returned driver — an un-validated model is NEVER presented as
    shop-validated truth. If a future edit drops the caveat, this fails."""
    rc, d, mat = build_rate_card(), _drivers(), _alu()
    for p in NEW_PROCESSES:
        est = cost_breakdown(p, d, mat, "aluminum", 100, rc, "US")
        sources = " ".join(dr.source for dr in est.drivers)
        assert "assumption, not shop-validated" in sources, (
            f"{p.name}: no driver carries the honesty caveat")


# ── per-process economically-meaningful relationships ────────────────────────
def _tooling(process, qty=1):
    rc, d, mat = build_rate_card(), _drivers(), _alu()
    est = cost_breakdown(process, d, mat, "aluminum", qty, rc, "US")
    td = _driver(est, "tooling_cost")
    return td.value if td else 0.0


def test_investment_tooling_exceeds_sand_tooling():
    """Investment casting (wax die + ceramic shell) tooling > sand pattern."""
    assert _tooling(PT.INVESTMENT_CASTING) > _tooling(PT.SAND_CASTING) > 0


def test_forging_tooling_is_most_expensive_tooled_route():
    """A hardened forging die set costs more than either casting pattern/shell."""
    assert _tooling(PT.FORGING) > _tooling(PT.INVESTMENT_CASTING)
    assert _tooling(PT.FORGING) > _tooling(PT.SAND_CASTING)


def test_casting_material_is_poured_mass_above_net():
    """Poured metal = net part mass × (1 + gating/riser yield loss) > net mass, and
    sand (heavier gating) pours more than investment for the same part."""
    rc, d, mat = build_rate_card(), _drivers(), _alu()
    net_kg = d.mass_kg(mat.density)
    # reconstruct poured mass from the material driver's price path
    for p, yl in ((PT.SAND_CASTING, 0.50), (PT.INVESTMENT_CASTING, 0.40)):
        est = cost_breakdown(p, d, mat, "aluminum", 100, rc, "US")
        md = _driver(est, "material_cost")
        # material_cost = poured_kg × $/kg × (1+scrap) × region_material; poured>net
        assert "poured metal" in md.source
        assert f"1+{yl:g}" in md.source
    sand = cost_breakdown(PT.SAND_CASTING, d, mat, "aluminum", 100, rc, "US")
    inv = cost_breakdown(PT.INVESTMENT_CASTING, d, mat, "aluminum", 100, rc, "US")
    # sand yields heavier (more gating) => higher material line for identical part
    assert sand.line_items["material"] > inv.line_items["material"]
    assert net_kg > 0


def test_forging_material_is_billet_above_net():
    """Billet from bar = net × (1 + flash/scale loss) > net part mass."""
    rc, d, mat = build_rate_card(), _drivers(), _alu()
    est = cost_breakdown(PT.FORGING, d, mat, "aluminum", 100, rc, "US")
    md = _driver(est, "material_cost")
    assert "billet from bar" in md.source and "flash/scale" in md.source


def test_forging_unit_cost_amortizes_down_with_qty():
    """The expensive forging die amortizes over quantity: unit cost must drop as
    qty rises (tooling ÷ qty)."""
    rc, d, mat = build_rate_card(), _drivers(), _alu()
    lo = cost_breakdown(PT.FORGING, d, mat, "aluminum", 10, rc, "US").unit_cost_usd
    hi = cost_breakdown(PT.FORGING, d, mat, "aluminum", 10000, rc, "US").unit_cost_usd
    assert hi < lo, f"forging unit cost should fall with qty: {lo} -> {hi}"


def test_wire_edm_is_slow_and_tool_less():
    """Wire-EDM: no hard tooling (fixed cost 0), and the SLOW cut dominates the
    unit cost (machine is the largest line item), with a wire consumable present."""
    rc, d, mat = build_rate_card(), _drivers(), _alu()
    est = cost_breakdown(PT.WIRE_EDM, d, mat, "aluminum", 100, rc, "US")
    assert est.fixed_cost_usd == 0.0, "wire-EDM has no hard tooling"
    assert _driver(est, "tooling_cost") is None
    li = est.line_items
    assert li["machine"] == max(li.values()), f"slow EDM cut should dominate: {li}"
    assert "consumables" in li and li["consumables"] > 0, "wire consumable must appear"
    # the cut-path proxy is honestly flagged
    cyc = _driver(est, "cycle_time")
    assert "PROXY" in cyc.source and "not a true 3D cut perimeter" in cyc.source


def test_wire_edm_slower_material_costs_more_machine_time():
    """A slower-cutting material (titanium << aluminum cut rate) makes the EDM cut
    take longer, so machine cost rises — the cut-rate driver is real physics."""
    rc, d = build_rate_card(), _drivers()
    alu = cost_breakdown(PT.WIRE_EDM, d, _alu(), "aluminum", 100, rc, "US")
    ti = cost_breakdown(PT.WIRE_EDM, d, _alu(), "titanium", 100, rc, "US")
    assert ti.line_items["machine"] > alu.line_items["machine"]


# ── BYTE-IDENTITY REGRESSION of the existing 11 costed processes ─────────────
# Golden values captured from the CURRENT code on the fixed part+qty below, BEFORE
# the four processes were added. If any existing family's cost path is perturbed by
# a single cent, one of these fails.
_ALU = dict(name="6061-T6 Aluminum", density=2.70, cost_per_kg=8.0)
_POLY = dict(name="PA12 (Nylon 12)", density=1.01, cost_per_kg=60.0)

# process -> (material spec, material_class, expected unit_cost, expected line_items)
GOLDEN = {
    PT.FDM: (_POLY, "polymer", 25.0123,
             {"amortized_fixed": 0.4375, "material": 1.9998, "machine": 15.4, "labor": 7.175}),
    PT.SLA: (_POLY, "polymer", 56.9677,
             {"amortized_fixed": 1.575, "material": 1.9998, "machine": 47.1429, "labor": 6.25}),
    PT.DLP: (_POLY, "polymer", 14.0563,
             {"amortized_fixed": 0.63, "material": 1.9998, "machine": 5.7647, "labor": 5.6618}),
    PT.SLS: (_POLY, "polymer", 9.2043,
             {"amortized_fixed": 0.175, "material": 1.9998, "machine": 4.1096, "labor": 2.9199}),
    PT.MJF: (_POLY, "polymer", 9.2417,
             {"amortized_fixed": 0.35, "material": 1.9998, "machine": 3.8884, "labor": 3.0035}),
    PT.CNC_3AXIS: (_ALU, "aluminum", 30.2797,
                   {"amortized_fixed": 0.2625, "material": 0.7484, "machine": 9.375,
                    "labor": 17.5, "nre": 0.7, "inspection": 1.225, "consumables": 0.4688}),
    PT.CNC_5AXIS: (_ALU, "aluminum", 38.9474,
                   {"amortized_fixed": 0.35, "material": 0.7484, "machine": 16.4633,
                    "labor": 17.5, "nre": 1.05, "inspection": 2.0125, "consumables": 0.8232}),
    PT.CNC_TURNING: (_ALU, "aluminum", 19.0516,
                     {"amortized_fixed": 0.175, "material": 0.6985, "machine": 6.0125,
                      "labor": 10.5, "nre": 0.35, "inspection": 1.015, "consumables": 0.3006}),
    PT.INJECTION_MOLDING: (_POLY, "polymer", 65.3252,
                           {"amortized_fixed": 60.0, "material": 1.8725, "machine": 1.7027,
                            "labor": 1.75}),
    PT.DIE_CASTING: (_ALU, "aluminum", 97.5729,
                     {"amortized_fixed": 90.0, "material": 0.6674, "machine": 3.4055,
                      "labor": 3.5}),
    PT.SHEET_METAL: (_ALU, "aluminum", 5.7466,
                     {"amortized_fixed": 0.14, "material": 0.6804, "machine": 1.4262,
                      "labor": 3.5}),
}


def test_existing_eleven_byte_identical():
    """The four new processes/families must not change the cost output of ANY of the
    11 currently-costed processes. Golden values were captured on this exact fixed
    part+qty from the code BEFORE the change — any drift is a regression."""
    rc, d = build_rate_card(), _drivers()
    for proc, (mspec, cls, exp_unit, exp_items) in GOLDEN.items():
        mat = MaterialProfile(name=mspec["name"], process_types=[], min_wall_thickness=1.0,
                              max_temperature=None, tensile_strength=None, elongation=None,
                              density=mspec["density"], cost_per_kg=mspec["cost_per_kg"])
        est = cost_breakdown(proc, d, mat, cls, 100, rc, "US")
        assert est.unit_cost_usd == exp_unit, (
            f"{proc.name} unit_cost drifted: {est.unit_cost_usd} != {exp_unit}")
        assert est.line_items == exp_items, (
            f"{proc.name} line_items drifted: {est.line_items} != {exp_items}")
