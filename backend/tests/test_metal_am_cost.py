"""Dollar cost models for the six metal-additive processes — DMLS, SLM, EBM
(metal powder-bed fusion), BINDER_JET (binder jetting), and DED / WAAM (directed-
energy / wire-arc) — plus the process_family() fix and a byte-identity guarantee
for the fifteen already-costed processes.

Pure unit tests (no DB, no network): they call ``cost_breakdown`` directly on a
hand-built ``GeoDrivers`` + ``MaterialProfile`` so each new physics model is
exercised in isolation, and a golden-value regression proves the six additions did
NOT perturb any currently-costed process by a single byte.

Physics recap (every constant is a DEFAULT assumption, un-validated):
  * metal_powder_bed {DMLS,SLM,EBM}: REUSES the build-job additive time model
    (full-build Z-sweep ÷ parts_per_build) with metal params, PLUS metal-only
    post-processing (build-plate cut-off + support removal + stress-relief furnace)
    that polymer AM never pays. Powder priced at the material-DB $/kg (no silent
    inflation); support structure ~20% extra printed volume.
  * binder_jet {BINDER_JET}: fast/cheap green PRINT + debind + SINTER furnace batch;
    the green is printed oversize by (1+shrinkage_linear)³ for sinter shrinkage.
  * ded {DED,WAAM}: deposition-RATE driven (deposited mass ÷ deposition_rate ×
    machine_rate) + near-net feedstock + a coarse finish-machining allowance. Widest
    band (highly geometry/shop-specific).
"""

from __future__ import annotations

import math

from src.analysis.models import ProcessType as PT
from src.profiles.models import MaterialProfile
from src.costing.drivers import GeoDrivers
from src.costing.rates import (
    build_rate_card, COSTED_PROCESSES, process_family, BAND_PCT,
    METAL_POWDER_BED, BINDER_JET_FAMILY, DED_FAMILY,
)
from src.costing.cost_model import cost_breakdown


# ── fixtures (hand-built, deterministic — no mesh/DB) ────────────────────────
def _drivers() -> GeoDrivers:
    """A 25×30×40 mm metal part: valid, with every field the families read."""
    return GeoDrivers(
        volume_cm3=30.0, surface_area_cm2=74.0, bbox_mm=(25.0, 30.0, 40.0),
        bbox_volume_cm3=30.0, hull_volume_cm3=28.0, nominal_wall_mm=8.1,
        face_count=12, max_bbox_mm=40.0, is_valid=True, rotational=True,
        rot_axis_len_mm=40.0, rot_cross_dia_mm=27.5, sheet_gauge_mm=2.0,
        planar_aspect=15.0, outline_perimeter_mm=140.0, bend_count=2,
        sheet_like=True)


def _small_drivers() -> GeoDrivers:
    """A 10×10×10 mm part — nests many more per powder-bed plate than _drivers()."""
    return GeoDrivers(
        volume_cm3=1.0, surface_area_cm2=6.0, bbox_mm=(10.0, 10.0, 10.0),
        bbox_volume_cm3=1.0, hull_volume_cm3=1.0, nominal_wall_mm=3.3,
        face_count=12, max_bbox_mm=10.0, is_valid=True, rotational=False,
        rot_axis_len_mm=10.0, rot_cross_dia_mm=10.0, sheet_gauge_mm=2.0,
        planar_aspect=5.0, outline_perimeter_mm=40.0, bend_count=0,
        sheet_like=False)


def _ti() -> MaterialProfile:
    return MaterialProfile(name="Ti6Al4V", process_types=[], min_wall_thickness=0.4,
                           max_temperature=None, tensile_strength=None, elongation=None,
                           density=4.43, cost_per_kg=350.0)


def _driver(est, name):
    for d in est.drivers:
        if d.name == name:
            return d
    return None


METAL_AM_PROCESSES = [PT.DMLS, PT.SLM, PT.EBM, PT.BINDER_JET, PT.DED, PT.WAAM]
POWDER_BED = [PT.DMLS, PT.SLM, PT.EBM]


# ── wiring: costed set + families (the process_family regression) ────────────
def test_metal_am_processes_are_costed():
    for p in METAL_AM_PROCESSES:
        assert p in COSTED_PROCESSES, f"{p.name} must be costed (off feasibility-only)"


def test_process_family_no_longer_formative():
    """Regression: these six matched NO family set and mis-returned 'formative'.
    They must now return their real metal-AM family."""
    for p in METAL_POWDER_BED:
        assert process_family(p) == "metal_powder_bed", p.name
    for p in BINDER_JET_FAMILY:
        assert process_family(p) == "binder_jet", p.name
    for p in DED_FAMILY:
        assert process_family(p) == "ded", p.name
    # not one of them is 'formative' any more
    for p in METAL_AM_PROCESSES:
        assert process_family(p) != "formative", p.name


def test_new_families_have_positive_bands():
    assert BAND_PCT["metal_powder_bed"] > 0
    assert BAND_PCT["binder_jet"] > 0
    assert BAND_PCT["ded"] > 0


# ── per-process: positive finite cost + required drivers + honest provenance ──
def test_each_metal_am_process_positive_finite_cost_with_drivers():
    rc, d, mat = build_rate_card(), _drivers(), _ti()
    for p in METAL_AM_PROCESSES:
        est = cost_breakdown(p, d, mat, "titanium", 100, rc, "US")
        # positive, finite unit cost
        assert math.isfinite(est.unit_cost_usd) and est.unit_cost_usd > 0, p.name
        # Σ line_items == unit_cost (hard invariant G3)
        est.assert_sums()
        # a material driver and a machine/cycle driver both present + positive
        mat_d = _driver(est, "material_cost")
        mach_d = _driver(est, "machine_cost")
        cyc_d = _driver(est, "cycle_time")
        assert mat_d is not None and mat_d.value > 0, p.name
        assert mach_d is not None and mach_d.value > 0, p.name
        assert cyc_d is not None and cyc_d.value > 0, p.name
        # a positive error band
        assert est.est_error_band_pct > 0, p.name
        # provenance DEFAULT on the new machine/cycle constants; NEVER measured-truth
        assert mach_d.provenance.value == "DEFAULT", p.name
        assert cyc_d.provenance.value == "DEFAULT", p.name
        for dr in est.drivers:
            assert dr.provenance.value in ("MEASURED", "USER", "DEFAULT"), p.name
        # no un-validated model is ever presented as validated truth
        assert getattr(est, "validated", False) is not True, p.name
        assert est.dfm_verdict != "validated", p.name
        # the estimate honestly caveats its un-validated assumptions somewhere
        all_src = " ".join(dr.source for dr in est.drivers)
        assert "not shop-validated" in all_src or "assumption" in all_src, p.name


def test_powder_bed_has_metal_only_post_processing():
    """DMLS/SLM/EBM must carry the metal-only post costs polymer AM never pays:
    build-plate removal, support removal, and a stress-relief furnace — each its own
    inspectable driver + line item — plus a support-material adder."""
    rc, d, mat = build_rate_card(), _drivers(), _ti()
    for p in POWDER_BED:
        est = cost_breakdown(p, d, mat, "titanium", 100, rc, "US")
        for name in ("plate_removal_cost", "support_removal_cost", "stress_relief_cost"):
            drv = _driver(est, name)
            assert drv is not None and drv.value > 0, f"{p.name} missing {name}"
            assert drv.provenance.value == "DEFAULT", f"{p.name} {name} prov"
        for li in ("plate_removal", "support_removal", "stress_relief"):
            assert li in est.line_items and est.line_items[li] > 0, f"{p.name} li {li}"
        # support-structure powder surfaced as an inspectable adder
        sup = _driver(est, "support_material")
        assert sup is not None and sup.value > 0, p.name
        # the un-bundled part-specific ops are honestly caveated
        sr = _driver(est, "stress_relief_cost")
        assert "NOT bundled" in sr.source and "HIP" in sr.source, p.name


def test_binder_jet_has_sinter_and_ded_has_finish_machining():
    rc, d, mat = build_rate_card(), _drivers(), _ti()
    bj = cost_breakdown(PT.BINDER_JET, d, mat, "titanium", 100, rc, "US")
    assert _driver(bj, "sinter_cost") is not None and bj.line_items["sinter"] > 0
    for p in DED_FAMILY:
        est = cost_breakdown(p, d, mat, "titanium", 100, rc, "US")
        assert _driver(est, "finish_machining") is not None, p.name
        assert est.line_items["finish_machining"] > 0, p.name


# ── economic sanity (>=1 per family) ─────────────────────────────────────────
def test_powder_bed_machine_drops_with_more_parts_per_build():
    """Build-job amortization: more parts nested per build ⇒ lower per-part machine
    cost (the beam sweeps the same full-build Z regardless of part count)."""
    d, mat = _drivers(), _ti()
    base = build_rate_card()
    dense = build_rate_card(overrides={"packing_density.DMLS": 0.20})
    e_base = cost_breakdown(PT.DMLS, d, mat, "titanium", 100, base, "US")
    e_dense = cost_breakdown(PT.DMLS, d, mat, "titanium", 100, dense, "US")
    n_base = _driver(e_base, "parts_per_build").value
    n_dense = _driver(e_dense, "parts_per_build").value
    assert n_dense > n_base, f"denser packing should nest more: {n_base} -> {n_dense}"
    assert e_dense.line_items["machine"] < e_base.line_items["machine"], (
        "per-part machine cost must fall as more parts amortize the build job")


def test_ebm_cheaper_machine_time_than_dmls_same_part():
    """EBM's higher vertical build rate (9 vs 6 mm/hr) ⇒ cheaper machine time for
    the same part than DMLS."""
    rc, d, mat = build_rate_card(), _drivers(), _ti()
    dmls = cost_breakdown(PT.DMLS, d, mat, "titanium", 100, rc, "US")
    ebm = cost_breakdown(PT.EBM, d, mat, "titanium", 100, rc, "US")
    assert ebm.line_items["machine"] < dmls.line_items["machine"]


def test_binder_jet_material_reflects_green_oversize_cube():
    """Binder-jet material = net × (1+shrinkage_linear)³ green oversize (net volume
    grows by the cube of the linear shrink factor)."""
    rc, d, mat = build_rate_card(), _drivers(), _ti()
    est = cost_breakdown(PT.BINDER_JET, d, mat, "titanium", 100, rc, "US")
    md = _driver(est, "material_cost")
    assert "sinter-shrink oversize" in md.source
    # numeric: material line = net_kg × (1+0.18)^3 × $/kg × (1+scrap) × region(1.0)
    net_kg = d.mass_kg(mat.density)
    scrap = rc.p(PT.BINDER_JET, "scrap")
    shr = rc.p(PT.BINDER_JET, "shrinkage_linear")
    expected = net_kg * (1.0 + shr) ** 3 * mat.cost_per_kg * (1.0 + scrap)
    assert abs(est.line_items["material"] - round(expected, 4)) < 0.02
    # and the green is strictly heavier than the net part
    net_mat = net_kg * mat.cost_per_kg * (1.0 + scrap)
    assert est.line_items["material"] > net_mat


def test_ded_machine_scales_with_deposited_mass_over_rate():
    """DED/WAAM cycle time = deposited mass ÷ deposition_rate. WAAM deposits 3× faster
    than DED (3.0 vs 1.0 kg/hr) for identical feedstock ⇒ WAAM cycle = DED cycle ÷ 3."""
    rc, d, mat = build_rate_card(), _drivers(), _ti()
    ded = cost_breakdown(PT.DED, d, mat, "titanium", 100, rc, "US")
    waam = cost_breakdown(PT.WAAM, d, mat, "titanium", 100, rc, "US")
    cyc_ded = _driver(ded, "cycle_time").value
    cyc_waam = _driver(waam, "cycle_time").value
    assert cyc_ded > cyc_waam
    # rate ratio 3.0/1.0 => DED cycle ~ 3× WAAM cycle (same feedstock_mult)
    assert abs(cyc_ded / cyc_waam - 3.0) < 0.05


def test_ded_waam_carry_the_widest_band():
    """DED/WAAM are the most geometry/shop-specific ⇒ the widest error band of the six."""
    rc, d, mat = build_rate_card(), _drivers(), _ti()
    bands = {p: cost_breakdown(p, d, mat, "titanium", 100, rc, "US").est_error_band_pct
             for p in METAL_AM_PROCESSES}
    ded_band = bands[PT.DED]
    assert bands[PT.WAAM] == ded_band
    for p in (PT.DMLS, PT.SLM, PT.EBM, PT.BINDER_JET):
        assert ded_band >= bands[p], f"DED band {ded_band} should be widest vs {p.name}"
    assert ded_band > bands[PT.DMLS]


def test_powder_price_not_silently_inflated():
    """Honesty guard: the metal-AM powder multiplier defaults to 1.0, so powder-bed
    material uses the material-DB $/kg as-is (documented refinement, no hidden markup)."""
    assert build_rate_card().p(PT.DMLS, "metal_am_powder_mult") == 1.0
    rc, d, mat = build_rate_card(), _drivers(), _ti()
    est = cost_breakdown(PT.DMLS, d, mat, "titanium", 100, rc, "US")
    md = _driver(est, "material_cost")
    # material = net×(1+support)×$/kg×(1+scrap): the $/kg is exactly the DB value
    assert f"${mat.cost_per_kg:g}/kg" in md.source
    assert "not silently inflated" in md.source


# ── BYTE-IDENTITY REGRESSION of the existing 15 costed processes ─────────────
# Golden values captured from the code BEFORE the six metal-AM processes were added,
# on this exact fixed part (_drivers) + qty 100. If any existing family's cost path
# is perturbed by a single cent, one of these fails.
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
    PT.FORGING: (_ALU, "aluminum", 139.0068,
                 {"amortized_fixed": 121.05, "material": 0.8505, "machine": 10.1063, "labor": 7.0}),
    PT.INVESTMENT_CASTING: (_ALU, "aluminum", 74.4835,
                            {"amortized_fixed": 54.525, "material": 0.9526, "machine": 6.7559,
                             "labor": 12.25}),
    PT.SAND_CASTING: (_ALU, "aluminum", 46.6775,
                      {"amortized_fixed": 21.35, "material": 1.0303, "machine": 3.2972, "labor": 21.0}),
    PT.WIRE_EDM: (_ALU, "aluminum", 23.258,
                  {"amortized_fixed": 0.525, "material": 0.7413, "machine": 16.45, "labor": 3.5,
                   "consumables": 2.0417}),
}


def test_existing_fifteen_byte_identical():
    """The six new metal-AM processes/families must not change the cost output of ANY
    of the 15 currently-costed processes. Golden values were captured on this exact
    fixed part+qty from the code BEFORE the change — any drift is a regression."""
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


def test_existing_families_unchanged_by_process_family():
    """process_family() for every pre-existing family is untouched — only the six
    metal-AM processes moved off the 'formative' fallback."""
    assert process_family(PT.FDM) == "additive"
    assert process_family(PT.SLS) == "additive"
    assert process_family(PT.CNC_3AXIS) == "subtractive"
    assert process_family(PT.SHEET_METAL) == "fabrication"
    assert process_family(PT.SAND_CASTING) == "casting"
    assert process_family(PT.FORGING) == "forging"
    assert process_family(PT.WIRE_EDM) == "edm"
    # the genuinely-formative processes stay formative
    assert process_family(PT.INJECTION_MOLDING) == "formative"
    assert process_family(PT.DIE_CASTING) == "formative"
