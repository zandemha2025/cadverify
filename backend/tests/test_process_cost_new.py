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

import pytest

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
        assert "not confirmed by a shop" in cyc_d.source, p.name


def test_new_families_carry_honesty_literal_in_drivers():
    """Honesty-literal regression guard: every newly-costed family (casting,
    forging, wire-EDM) attaches the ``assumption, not shop-validated`` caveat to at
    least one returned driver — an un-validated model is NEVER presented as
    shop-validated truth. If a future edit drops the caveat, this fails."""
    rc, d, mat = build_rate_card(), _drivers(), _alu()
    for p in NEW_PROCESSES:
        est = cost_breakdown(p, d, mat, "aluminum", 100, rc, "US")
        sources = " ".join(dr.source for dr in est.drivers)
        assert "typical value, not confirmed by a shop" in sources, (
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
    """Wire-EDM: no hard tooling (its one-time cost is just the order's first
    setup), and the SLOW cut dominates the unit cost (machine is the largest line
    item), with a wire consumable present."""
    rc, d, mat = build_rate_card(), _drivers(), _alu()
    est = cost_breakdown(PT.WIRE_EDM, d, mat, "aluminum", 100, rc, "US")
    assert _driver(est, "tooling_cost") is None
    assert 0 < est.fixed_cost_usd < est.unit_cost_usd * 100, "only the first setup is one-time"
    assert est.fixed_cost_usd / 100 + est.variable_cost_usd == pytest.approx(est.unit_cost_usd, abs=2e-4)
    li = est.line_items
    assert li["machine"] == max(li.values()), f"slow EDM cut should dominate: {li}"
    assert "consumables" in li and li["consumables"] > 0, "wire consumable must appear"
    # the cut-path proxy is honestly flagged
    cyc = _driver(est, "cycle_time")
    assert "cut path estimated" in cyc.source and "not a measured 3D path" in cyc.source


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
    # FDM updated for the shared 300 x 300 x 350 mm build size (src/profiles/envelopes.py):
    # the plate holds more parts, so per-build setup and the Z climb spread further.
    # 100 parts at 30 a plate pay 100/30 setups, not 4 (M14: no partial-plate step)
    PT.FDM: (_POLY, "polymer", 24.6749,
             {"amortized_fixed": 0.2917, "material": 1.9998, "machine": 15.2667, "labor": 7.1167}),
    PT.SLA: (_POLY, "polymer", 56.8927,
             {"amortized_fixed": 1.5, "material": 1.9998, "machine": 47.1429, "labor": 6.25}),
    PT.DLP: (_POLY, "polymer", 14.0439,
             {"amortized_fixed": 0.6176, "material": 1.9998, "machine": 5.7647, "labor": 5.6618}),
    PT.SLS: (_POLY, "polymer", 9.2043,
             {"amortized_fixed": 0.175, "material": 1.9998, "machine": 4.1096, "labor": 2.9199}),
    PT.MJF: (_POLY, "polymer", 9.0952,
             {"amortized_fixed": 0.2035, "material": 1.9998, "machine": 3.8884, "labor": 3.0035}),
    PT.CNC_3AXIS: (_ALU, "aluminum", 30.2797,
                   {"amortized_fixed": 0.2625, "material": 0.7484, "machine": 9.375,
                    "labor": 17.5, "nre": 0.7, "inspection": 1.225, "consumables": 0.4688}),
    PT.CNC_5AXIS: (_ALU, "aluminum", 38.9474,
                   {"amortized_fixed": 0.35, "material": 0.7484, "machine": 16.4633,
                    "labor": 17.5, "nre": 1.05, "inspection": 2.0125, "consumables": 0.8232}),
    # Turning updated for the shared round-stock calculation; other goldens unchanged.
    PT.CNC_TURNING: (_ALU, "aluminum", 18.9458,
                     {"amortized_fixed": 0.175, "material": 0.5927, "machine": 6.0125,
                      "labor": 10.5, "nre": 0.35, "inspection": 1.015, "consumables": 0.3006}),
    PT.INJECTION_MOLDING: (_POLY, "polymer", 65.3252,
                           {"amortized_fixed": 0.0, "material": 1.8725, "machine": 1.7027,
                            "labor": 1.75, "tooling": 60.0}),
    PT.DIE_CASTING: (_ALU, "aluminum", 97.5729,
                     {"amortized_fixed": 0.0, "material": 0.6674, "machine": 3.4055,
                      "labor": 3.5, "tooling": 90.0}),
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


# ── Round 14: a mould or tree is shared; fettling follows the casting's size ──
@pytest.mark.parametrize("process, per_mould", [(PT.SAND_CASTING, 42), (PT.INVESTMENT_CASTING, 8)])
def test_a_mould_or_tree_is_shared_by_the_castings_it_holds(process, per_mould):
    """25 x 30 x 40 mm: 42 to a 500 x 400 mm sand mould, 8 to a 300 x 200 mm tree
    (25 / 30 mm of sand or gating around each). The mould's time is shared."""
    from src.costing.cost_model import castings_per_mould

    rc, d = build_rate_card(), _drivers()
    n, share, words = castings_per_mould(process, d, rc)
    assert (n, share) == (per_mould, pytest.approx(1 / per_mould))
    est = cost_breakdown(process, d, _alu(), "aluminum", 100, rc, "US")
    cycle = _driver(est, "cycle_time")
    assert f"÷ {per_mould}" in cycle.source and f"{per_mould} castings a " in cycle.source


def test_a_casting_too_big_for_the_mould_takes_a_bigger_one():
    from src.costing.cost_model import castings_per_mould

    big = GeoDrivers(volume_cm3=64000.0, surface_area_cm2=9600.0, bbox_mm=(400.0, 400.0, 400.0),
                     bbox_volume_cm3=64000.0, hull_volume_cm3=64000.0, nominal_wall_mm=200.0,
                     face_count=12, max_bbox_mm=400.0, is_valid=True, rotational=False,
                     rot_axis_len_mm=400.0, rot_cross_dia_mm=565.0)
    n, share, words = castings_per_mould(PT.SAND_CASTING, big, build_rate_card())
    assert n == 1 and share == pytest.approx(450 * 450 / (500 * 400))
    assert "takes a mould 1.01× the 500 × 400 mm one" in words


def test_fettling_follows_the_casting_surface_unless_the_hours_are_set():
    rc, d = build_rate_card(), _drivers()
    kg = d.mass_kg(_alu().density)
    est = cost_breakdown(PT.SAND_CASTING, d, _alu(), "aluminum", 100, rc, "US")
    expected_hr = 0.01 + 0.04 * kg ** (2 / 3)
    assert est.line_items["labor"] == pytest.approx(expected_hr * 35.0, abs=1e-3)
    assert "mass to the 2/3 power" in _driver(est, "labor_cost").source
    # A shop's or user's own hand-work hours are the whole of it, at any size.
    set_hours = build_rate_card({"post_hr_part.SAND_CASTING": 0.3})
    est = cost_breakdown(PT.SAND_CASTING, d, _alu(), "aluminum", 100, set_hours, "US")
    assert est.line_items["labor"] == pytest.approx(0.3 * 35.0)
    assert "your figure for cutting off, fettling and cleaning" in _driver(est, "labor_cost").source


def test_a_rate_table_published_before_the_mould_keys_prices_as_it_did():
    """An org's governed card copied from the earlier table has no mould or fettling
    keys: one casting a mould and its own flat hand work, as when it was published."""
    import copy

    from src.costing.rates import RATE_CARD_V0

    table = copy.deepcopy(RATE_CARD_V0)
    for key in ("mould_w_mm", "mould_l_mm", "mould_gap_mm", "fettle_hr_kg"):
        table["process"][PT.SAND_CASTING].pop(key)
    table["process"][PT.SAND_CASTING]["post_hr_part"] = 0.60
    rc = build_rate_card(base_rate_table=table)
    est = cost_breakdown(PT.SAND_CASTING, _drivers(), _alu(), "aluminum", 100, rc, "US")
    assert est.line_items["labor"] == pytest.approx(21.0)
    assert est.line_items["machine"] == pytest.approx(3.2972, abs=1e-4)


# ── Forging: the press a forging needs follows its load ──────────────────────
def _steel() -> MaterialProfile:
    return MaterialProfile(name="AISI 4140", process_types=[], min_wall_thickness=1.0,
                           max_temperature=None, tensile_strength=None, elongation=None,
                           density=7.85, cost_per_kg=2.2)


def _forging_drivers(dims) -> GeoDrivers:
    """A solid box forging, its enclosing box ``dims`` (ascending, mm)."""
    vol = dims[0] * dims[1] * dims[2] / 1000.0
    return GeoDrivers(volume_cm3=vol, surface_area_cm2=2 * (dims[0] * dims[1] + dims[0] * dims[2]
                                                             + dims[1] * dims[2]) / 100.0,
                      bbox_mm=dims, bbox_volume_cm3=vol, hull_volume_cm3=vol, nominal_wall_mm=dims[0] / 2,
                      face_count=12, max_bbox_mm=dims[2], is_valid=True, rotational=False,
                      rot_axis_len_mm=dims[2], rot_cross_dia_mm=dims[1],
                      billet_bbox_mm=dims, billet_basis="oriented candidate")


# The keys a rate table published before press classes doesn't have.
_PRESS_KEYS = r"press\d+_(t|rate)|flow_mpa_\w+|flash_land_mm|press_shape_factor"


def _heat_hr(d, density=7.85):
    return d.mass_kg(density) * 1.25 * 2.5 / 60.0     # billet × 2.5 min/kg


@pytest.mark.parametrize("dims, press_t, rate", [
    ((25.0, 30.0, 40.0), 500, 80.0),        # small: 52 × 42 mm with the flash land, 214 t
    ((40.0, 100.0, 100.0), 2500, 220.0),    # medium: 112 × 112 mm, 1,228 t
    ((60.0, 300.0, 300.0), 16000, 730.0),   # large: 312 × 312 mm, 9,529 t
])
def test_a_forging_is_priced_on_the_press_its_load_needs(dims, press_t, rate):
    """Load = plan area (two longest sides + 6 mm flash land each side) × 120 MPa
    steel flow stress × shape factor 8; the smallest press class rated for it prices
    the 40 s of forging and trim, heating stays at the forging cell's $120/h."""
    from src.costing.cost_model import forging_press

    rc, d = build_rate_card(), _forging_drivers(dims)
    press = forging_press(PT.FORGING, d, "steel", rc)
    assert press is not None
    assert press.load_t == pytest.approx((dims[2] + 12) * (dims[1] + 12) * 120 * 8 / 9806.65)
    assert (press.capacity_t, press.rate) == (press_t, rate)
    est = cost_breakdown(PT.FORGING, d, _steel(), "steel", 10000, rc, "US")
    est.assert_sums()
    assert est.line_items["machine"] == pytest.approx(_heat_hr(d) * 120 + 40 / 3600 * rate, abs=1e-4)
    mach = _driver(est, "machine_cost")
    assert f"on the {press_t:,} t press at ${rate:g}/hr" in mach.source
    assert mach.provenance.value == "DEFAULT"
    cycle = _driver(est, "cycle_time").source
    assert f"the {press_t:,} t press, ${rate:g}/hr" in cycle
    assert "forging and trim 40s a piece (Boothroyd Dewhurst: 20–120 s" in cycle
    assert "typical value, not confirmed by a shop" in cycle


def test_the_same_metal_spread_wider_needs_a_bigger_press():
    """240 cm³ of steel as a 40 × 60 × 100 mm block (789 t: 1,000 t press) or a 16 ×
    100 × 150 mm plate (1,776 t: 2,500 t press): the same billet and heating, and the
    plate's forging and trim cost the bigger press's rate."""
    rc = build_rate_card()
    block, plate = _forging_drivers((40.0, 60.0, 100.0)), _forging_drivers((16.0, 100.0, 150.0))
    assert block.volume_cm3 == plate.volume_cm3
    est = {k: cost_breakdown(PT.FORGING, d, _steel(), "steel", 10000, rc, "US")
           for k, d in (("block", block), ("plate", plate))}
    assert est["block"].line_items["material"] == est["plate"].line_items["material"]
    assert (est["plate"].line_items["machine"] - est["block"].line_items["machine"]
            == pytest.approx((220 - 120) * 40 / 3600, abs=2e-4))
    assert "on the 1,000 t press" in _driver(est["block"], "machine_cost").source
    assert "on the 2,500 t press" in _driver(est["plate"], "machine_cost").source


def test_a_forging_past_the_largest_press_scales_its_rate_with_the_load():
    from src.costing.cost_model import forging_press

    rc, d = build_rate_card(), _forging_drivers((100.0, 700.0, 700.0))
    press = forging_press(PT.FORGING, d, "steel", rc)
    assert press is not None and press.capacity_t == 40000 and press.load_t > 40000
    assert press.rate == pytest.approx(1300 * press.load_t / 40000)
    assert "more than the largest press class, 40,000 t" in press.words
    est = cost_breakdown(PT.FORGING, d, _steel(), "steel", 100, rc, "US")
    assert "on a press past the 40,000 t class" in _driver(est, "machine_cost").source


def test_a_rate_table_published_before_the_press_keys_prices_as_it_did():
    """An org's governed card copied from the earlier table has no press classes and
    its own 0.05 h press + 0.03 h trim: every forging on the one $120/h press, small or
    large, as when it was published."""
    import copy
    import json
    import re

    from src.costing.rates import RATE_CARD_V0

    table = copy.deepcopy(RATE_CARD_V0)
    forging = table["process"][PT.FORGING]
    for key in [k for k in forging if re.fullmatch(_PRESS_KEYS, k)]:
        forging.pop(key)
    forging.update(press_hr=0.05, trim_hr=0.03)
    rc = build_rate_card(base_rate_table=json.loads(json.dumps(table)))   # as stored
    est = cost_breakdown(PT.FORGING, _drivers(), _alu(), "aluminum", 100, rc, "US")
    assert est.unit_cost_usd == 139.0068                    # the golden before press classes
    assert est.line_items["machine"] == 10.1063
    assert "press 0.05hr + trim 0.03hr" in _driver(est, "cycle_time").source
    for dims in ((25.0, 30.0, 40.0), (60.0, 300.0, 300.0)):
        d = _forging_drivers(dims)
        est = cost_breakdown(PT.FORGING, d, _steel(), "steel", 10000, rc, "US")
        assert est.line_items["machine"] == pytest.approx((_heat_hr(d) + 0.08) * 120, abs=1e-4)
        assert " t press" not in _driver(est, "machine_cost").source


def test_a_shops_own_forging_rate_is_their_cell_as_given():
    """A shop's (or user's) machine rate is their forging cell, for all of its time;
    the source still names the press the part needs. A press class's rate set for the
    quote is the user's."""
    d = _forging_drivers((40.0, 100.0, 100.0))
    shop = build_rate_card(shop_overrides={"machine_rate.FORGING": 150.0}, shop_name="Forge Co")
    est = cost_breakdown(PT.FORGING, d, _steel(), "steel", 100, shop, "US")
    mach = _driver(est, "machine_cost")
    assert est.line_items["machine"] == pytest.approx((_heat_hr(d) + 40 / 3600) * 150, abs=1e-4)
    assert mach.provenance.value == "SHOP"
    assert "your forging cell's rate, as given, for all of it; the part needs the 2,500 t press" in mach.source
    user = build_rate_card({"press3_rate.FORGING": 260.0})
    mach = _driver(cost_breakdown(PT.FORGING, d, _steel(), "steel", 100, user, "US"), "machine_cost")
    assert mach.provenance.value == "USER"
    assert "on the 2,500 t press at $260/hr" in mach.source
