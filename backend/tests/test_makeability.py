"""Exhaustive, PURE unit tests for the capability-matching + gap engine + env
gate (spec §9). No DB, no I/O. Every gate, every §0 verdict, the honesty
invariants (§2), gap-analysis ordering, and the environment gate are covered.
"""

from __future__ import annotations

import pytest

from src.costing.makeability import (
    MachineCap,
    ShopCaps,
    PartReq,
    FitFailure,
    fit_machine,
    verify_part,
    gap_analysis,
    environment_gate,
    part_req_from_drivers,
    TOLERANCE_IT_MAP,
    STANDARD_IT,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fakes / builders
# ─────────────────────────────────────────────────────────────────────────────


class FakeDrivers:
    """Duck-typed GeoDrivers stand-in (only the fields part_req_from_drivers reads)."""

    def __init__(self, bbox_mm, volume_cm3=10.0, rotational=False,
                 rot_cross_dia_mm=0.0, rot_axis_len_mm=0.0, nominal_wall_mm=3.0,
                 sheet_gauge_mm=0.0, sheet_like=False):
        self.bbox_mm = tuple(sorted(bbox_mm))
        self.volume_cm3 = volume_cm3
        self.rotational = rotational
        self.rot_cross_dia_mm = rot_cross_dia_mm
        self.rot_axis_len_mm = rot_axis_len_mm
        self.nominal_wall_mm = nominal_wall_mm
        self.sheet_gauge_mm = sheet_gauge_mm
        self.sheet_like = sheet_like

    def mass_kg(self, density_g_cm3):
        return self.volume_cm3 * density_g_cm3 / 1000.0


class FakeMaterial:
    def __init__(self, name, density):
        self.name = name
        self.density = density


def mill(name="Haas VF-2", x=762, y=406, z=508, axes=3, motion_mode=None,
         materials=("6061-T6 Aluminum", "aluminum"), max_kg=200.0,
         rate=75.0, it=None, min_feature=None, process="cnc_3axis"):
    cap = {"x": x, "y": y, "z": z, "axes": axes}
    if motion_mode is not None:
        cap["motion_mode"] = motion_mode
    if it is not None:
        cap["achievable_it_grade"] = it
    if min_feature is not None:
        cap["min_feature_mm"] = min_feature
    return MachineCap(process=process, name=name, count=1, max_workpiece_kg=max_kg,
                      hourly_rate_usd=rate, capital_frac=0.35,
                      materials=materials, capabilities=cap)


def part(process="cnc_3axis", bbox=(100, 200, 300), mass=5.0,
         material_name="6061-T6 Aluminum", material_class="aluminum",
         it=STANDARD_IT, min_feature=2.0, props=None, sec=(), thickness=None,
         sheet_like=False, rotational=False, dia=0.0, length=0.0):
    return PartReq(
        process=process, bbox_mm=tuple(sorted(bbox)), rotational=rotational,
        rot_cross_dia_mm=dia, rot_axis_len_mm=length, mass_kg=mass,
        material_name=material_name, material_class=material_class,
        material_props=props or {}, tolerance_it=it, min_feature_mm=min_feature,
        required_secondary_ops=sec, thickness_mm=thickness, sheet_like=sheet_like)


# ─────────────────────────────────────────────────────────────────────────────
# ENVELOPE gate
# ─────────────────────────────────────────────────────────────────────────────


def test_envelope_fits_exactly():
    m = mill(x=300, y=200, z=100)
    fr = fit_machine(part(bbox=(100, 200, 300)), m)
    assert fr.passes, fr.failures


def test_envelope_orientation_permutation_passes():
    # part 300 long fits the machine's 305 axis only after a rotation
    m = mill(x=305, y=205, z=105)
    fr = fit_machine(part(bbox=(105, 205, 300)), m)
    assert fr.passes


def test_envelope_exceeds_longest_axis():
    m = mill(x=305, y=305, z=305)
    fr = fit_machine(part(bbox=(100, 200, 380)), m)
    assert not fr.passes
    env = [f for f in fr.failures if f.gate == "envelope"]
    assert env and env[0].need == 380 and env[0].have == 305
    assert "380mm > machine 305mm" in env[0].human


def test_envelope_exceeds_each_axis_reported():
    # every axis too big: still one binding envelope failure (worst axis)
    m = mill(x=100, y=100, z=100)
    fr = fit_machine(part(bbox=(150, 250, 400)), m)
    env = [f for f in fr.failures if f.gate == "envelope"]
    assert env and env[0].need == 400  # worst axis is the binding one


def test_envelope_turning_swing_and_length():
    lathe = MachineCap(process="cnc_turning", name="Haas ST-20",
                       max_workpiece_kg=100, hourly_rate_usd=65, materials=("304 Stainless", "stainless"),
                       capabilities={"swing_dia": 254, "between_centers": 533})
    ok = fit_machine(part(process="cnc_turning", material_name="304 Stainless",
                          material_class="stainless", rotational=True, dia=200,
                          length=500, bbox=(200, 200, 500)), lathe)
    assert ok.passes, ok.failures
    over_swing = fit_machine(part(process="cnc_turning", material_name="304 Stainless",
                                  material_class="stainless", rotational=True, dia=300,
                                  length=500, bbox=(300, 300, 500)), lathe)
    fails = {f.axis for f in over_swing.failures}
    assert "swing_dia" in fails
    over_len = fit_machine(part(process="cnc_turning", material_name="304 Stainless",
                                material_class="stainless", rotational=True, dia=100,
                                length=900, bbox=(100, 100, 900)), lathe)
    assert "between_centers" in {f.axis for f in over_len.failures}


def test_envelope_sheet_footprint():
    m = MachineCap(process="sheet_metal", name="Laser", max_workpiece_kg=50,
                   hourly_rate_usd=45, materials=("Mild Steel", "steel"),
                   capabilities={"bed_x": 1500, "bed_y": 3000})
    ok = fit_machine(part(process="sheet_metal", material_name="Mild Steel",
                          material_class="steel", bbox=(2, 1000, 2500),
                          sheet_like=True, thickness=2.0), m)
    assert ok.passes, ok.failures
    over = fit_machine(part(process="sheet_metal", material_name="Mild Steel",
                            material_class="steel", bbox=(2, 1600, 2500),
                            sheet_like=True, thickness=2.0), m)
    assert not over.passes


def test_envelope_undeclared_is_unknown():
    m = MachineCap(process="cnc_3axis", name="mystery", max_workpiece_kg=100,
                   hourly_rate_usd=75, materials=("aluminum",), capabilities={})
    fr = fit_machine(part(), m)
    env = [f for f in fr.failures if f.gate == "envelope"]
    assert env and env[0].have is None  # unknown, not a hard fail


# ─────────────────────────────────────────────────────────────────────────────
# MASS gate
# ─────────────────────────────────────────────────────────────────────────────


def test_mass_under_at_over():
    m = mill(max_kg=10.0)
    assert fit_machine(part(mass=5.0), m).passes            # under
    assert fit_machine(part(mass=10.0), m).passes           # at (<=)
    over = fit_machine(part(mass=12.0), m)
    assert not over.passes
    mf = [f for f in over.failures if f.gate == "mass"][0]
    assert mf.need == 12.0 and mf.have == 10.0


def test_mass_undeclared_machine_is_unknown():
    m = mill()
    m = MachineCap(process="cnc_3axis", name="n", max_workpiece_kg=None,
                   hourly_rate_usd=75, materials=("aluminum",),
                   capabilities={"x": 500, "y": 500, "z": 500, "axes": 3})
    fr = fit_machine(part(mass=5.0), m)
    mf = [f for f in fr.failures if f.gate == "mass"][0]
    assert mf.have is None


def test_mass_unknown_when_part_mass_none():
    m = mill(max_kg=10.0)
    fr = fit_machine(part(mass=None), m)
    mf = [f for f in fr.failures if f.gate == "mass"][0]
    assert mf.have is None


# ─────────────────────────────────────────────────────────────────────────────
# MATERIAL qualification gate
# ─────────────────────────────────────────────────────────────────────────────


def test_material_qualified_by_name():
    m = mill(materials=("6061-T6 Aluminum",))
    assert fit_machine(part(material_name="6061-T6 Aluminum",
                            material_class="aluminum"), m).passes


def test_material_qualified_by_class():
    m = mill(materials=("aluminum",))
    assert fit_machine(part(material_name="7075-T6 Aluminum",
                            material_class="aluminum"), m).passes


def test_material_class_sentinel_at():
    m = mill(materials=("@aluminum",))
    assert fit_machine(part(material_class="aluminum"), m).passes


def test_material_not_qualified():
    m = mill(materials=("aluminum", "steel"))
    fr = fit_machine(part(material_name="Inconel 718", material_class="nickel"), m)
    mf = [f for f in fr.failures if f.gate == "material"][0]
    assert not fr.passes and "not qualified for Inconel 718" in mf.human
    assert mf.have is not None  # hard fail


def test_material_undeclared_is_unknown():
    m = mill(materials=())
    fr = fit_machine(part(), m)
    mf = [f for f in fr.failures if f.gate == "material"][0]
    assert mf.have is None


# ─────────────────────────────────────────────────────────────────────────────
# TOLERANCE gate (with/without shop grinding, full ladder)
# ─────────────────────────────────────────────────────────────────────────────


def test_tolerance_standard_is_noop():
    m = mill(it=None)  # machine doesn't even declare IT
    assert fit_machine(part(it=STANDARD_IT), m).passes  # standard never engages


def test_tolerance_machine_holds_grade():
    m = mill(it=6)
    assert fit_machine(part(it=6), m).passes
    assert fit_machine(part(it=8), m).passes  # machine tighter than needed


def test_tolerance_too_tight_no_grinding_hard_fail():
    m = mill(it=9)
    fr = fit_machine(part(it=6), m)  # need IT6, machine holds IT9
    tf = [f for f in fr.failures if f.gate == "tolerance"][0]
    assert not fr.passes and tf.need == 6 and tf.have == 9
    assert "IT6" in tf.human and "IT9" in tf.human


def test_tolerance_too_tight_with_shop_grinding_soft_pass():
    m = mill(it=9)
    shop = ShopCaps(ops={"grinding": True})
    fr = fit_machine(part(it=6), m, shop)
    assert fr.passes
    assert "grinding" in fr.resource_hint["secondary_ops"]


def test_tolerance_undeclared_machine_is_unknown():
    m = mill(it=None)
    fr = fit_machine(part(it=6), m)  # tight part, machine IT undeclared
    tf = [f for f in fr.failures if f.gate == "tolerance"][0]
    assert tf.have is None


# ─────────────────────────────────────────────────────────────────────────────
# AXES / reachability gate
# ─────────────────────────────────────────────────────────────────────────────


def test_3axis_part_on_3axis_machine_passes():
    m = mill(process="cnc_3axis", axes=3)
    assert fit_machine(part(process="cnc_3axis"), m).passes


def test_5axis_part_on_3axis_machine_fails():
    m = mill(process="cnc_5axis", axes=3, materials=("aluminum",))
    fr = fit_machine(part(process="cnc_5axis"), m)
    af = [f for f in fr.failures if f.gate == "axes"][0]
    assert not fr.passes and af.need == 5 and af.have == 3
    assert "needs 5-axis" in af.human and "3-axis" in af.human


def test_5axis_part_on_5axis_machine_passes():
    m = mill(process="cnc_5axis", axes=5, motion_mode="simultaneous_5",
             materials=("aluminum",))
    assert fit_machine(part(process="cnc_5axis"), m).passes


def test_5axis_part_positional_only_fails_motion_mode():
    m = mill(process="cnc_5axis", axes=5, motion_mode="positional_3plus2",
             materials=("aluminum",))
    fr = fit_machine(part(process="cnc_5axis"), m)
    assert "motion_mode" in {f.axis for f in fr.failures}


def test_3axis_part_on_5axis_machine_passes():
    m = mill(process="cnc_5axis", axes=5, materials=("aluminum",))
    # a 3-axis-routed part on a 5-axis machine (over-capable) — but process must match
    assert fit_machine(part(process="cnc_5axis", it=STANDARD_IT), m).passes


# ─────────────────────────────────────────────────────────────────────────────
# FORCE / THICKNESS / POWER / min-feature edges
# ─────────────────────────────────────────────────────────────────────────────


def test_laser_thickness_by_material():
    m = MachineCap(process="sheet_metal", name="Laser 6kW", max_workpiece_kg=50,
                   hourly_rate_usd=45, materials=("Mild Steel", "steel"),
                   material_thickness_map={"Mild Steel": 20.0, "steel": 20.0},
                   capabilities={"bed_x": 1500, "bed_y": 3000})
    ok = fit_machine(part(process="sheet_metal", material_name="Mild Steel",
                          material_class="steel", bbox=(10, 500, 800),
                          thickness=10.0, sheet_like=False), m)
    assert ok.passes, ok.failures
    over = fit_machine(part(process="sheet_metal", material_name="Mild Steel",
                            material_class="steel", bbox=(25, 500, 800),
                            thickness=25.0, sheet_like=False), m)
    tf = [f for f in over.failures if f.gate == "thickness"][0]
    assert tf.need == 25.0 and tf.have == 20.0


def test_edm_conductive_required():
    m = MachineCap(process="wire_edm", name="Sodick", max_workpiece_kg=100,
                   hourly_rate_usd=42, materials=("polymer", "steel"),
                   capabilities={"x": 600, "y": 400, "z": 350,
                                 "conductive_required": True})
    non_cond = fit_machine(part(process="wire_edm", material_name="PEEK",
                                material_class="polymer", bbox=(10, 100, 100),
                                props={"conductive": False}), m)
    cf = [f for f in non_cond.failures if f.axis == "conductive"][0]
    assert not non_cond.passes and "conductive" in cf.human
    cond = fit_machine(part(process="wire_edm", material_name="Mild Steel",
                            material_class="steel", bbox=(10, 100, 100),
                            props={"conductive": True}), m)
    assert cond.passes, cond.failures


def test_edm_taper_limit():
    m = MachineCap(process="wire_edm", name="Sodick", max_workpiece_kg=100,
                   hourly_rate_usd=42, materials=("steel",),
                   capabilities={"x": 600, "y": 400, "z": 350,
                                 "conductive_required": True, "max_taper_deg": 15.0})
    over = fit_machine(part(process="wire_edm", material_name="Mild Steel",
                            material_class="steel", bbox=(10, 100, 100),
                            props={"conductive": True, "taper_deg": 30.0}), m)
    assert "taper_deg" in {f.axis for f in over.failures}


def test_forge_tonnage():
    forge = MachineCap(process="forging", name="Press", max_workpiece_kg=500,
                       hourly_rate_usd=120, materials=("steel",),
                       capabilities={"x": 500, "y": 500, "z": 500,
                                     "press_tonnage_t": 1000})
    over = fit_machine(part(process="forging", material_name="AISI 4140",
                            material_class="steel", bbox=(100, 100, 100),
                            props={"required_tonnage_t": 1500}), forge)
    tf = [f for f in over.failures if f.axis == "tonnage_t"][0]
    assert tf.need == 1500 and tf.have == 1000
    ok = fit_machine(part(process="forging", material_name="AISI 4140",
                          material_class="steel", bbox=(100, 100, 100),
                          props={"required_tonnage_t": 800}), forge)
    assert ok.passes, ok.failures


def test_min_feature_edge():
    m = mill(min_feature=2.0)
    ok = fit_machine(part(min_feature=3.0), m)  # feature >= machine min
    assert ok.passes
    too_fine = fit_machine(part(min_feature=0.5), m)  # finer than machine can hold
    mf = [f for f in too_fine.failures if f.gate == "min_feature"][0]
    assert mf.need == 0.5 and mf.have == 2.0


def test_min_feature_undeclared_is_noop():
    m = mill(min_feature=None)
    assert fit_machine(part(min_feature=0.1), m).passes  # no constraint declared


# ─────────────────────────────────────────────────────────────────────────────
# SECONDARY OPS gate (present / absent / size-limited)
# ─────────────────────────────────────────────────────────────────────────────


def test_secondary_op_required_present_soft_pass():
    m = mill(process="dmls", materials=("Ti6Al4V", "titanium"))
    m = MachineCap(process="dmls", name="EOS", max_workpiece_kg=50,
                   hourly_rate_usd=180, materials=("Ti6Al4V", "titanium"),
                   capabilities={"x": 400, "y": 400, "z": 400})
    shop = ShopCaps(ops={"stress_relief": True})
    fr = fit_machine(part(process="dmls", material_name="Ti6Al4V",
                          material_class="titanium", bbox=(50, 100, 200),
                          sec=("stress_relief",)), m, shop)
    assert fr.passes
    assert "stress_relief" in fr.resource_hint["secondary_ops"]


def test_secondary_op_required_absent_hard_fail():
    m = MachineCap(process="dmls", name="EOS", max_workpiece_kg=50,
                   hourly_rate_usd=180, materials=("Ti6Al4V", "titanium"),
                   capabilities={"x": 400, "y": 400, "z": 400})
    fr = fit_machine(part(process="dmls", material_name="Ti6Al4V",
                          material_class="titanium", bbox=(50, 100, 200),
                          sec=("stress_relief",)), m, ShopCaps(ops={}))
    sf = [f for f in fr.failures if f.gate == "secondary_op"][0]
    assert not fr.passes and "stress_relief" in sf.human and sf.have is not None


def test_secondary_op_hip_size_limited():
    m = MachineCap(process="investment_casting", name="Foundry",
                   max_workpiece_kg=100, hourly_rate_usd=55,
                   materials=("17-4 PH (Cast)", "stainless"),
                   capabilities={"flask_x": 500, "flask_y": 500, "flask_z": 500})
    # HIP vessel dia 300 x height 600
    shop_ok = ShopCaps(ops={"hip": {"dia_mm": 300, "height_mm": 600}})
    small = part(process="investment_casting", material_name="17-4 PH (Cast)",
                 material_class="stainless", bbox=(100, 100, 400), sec=("hip",))
    assert fit_machine(small, m, shop_ok).passes
    big = part(process="investment_casting", material_name="17-4 PH (Cast)",
               material_class="stainless", bbox=(400, 400, 400), sec=("hip",))
    over = fit_machine(big, m, shop_ok)
    assert not over.passes
    assert "exceeds hip envelope" in [f.human for f in over.failures
                                      if f.gate == "secondary_op"][0]


# ─────────────────────────────────────────────────────────────────────────────
# part_req_from_drivers — extraction + tolerance map + secondary-op derivation
# ─────────────────────────────────────────────────────────────────────────────


def test_part_req_tolerance_map():
    assert TOLERANCE_IT_MAP == {"standard": 11, "precision": 8, "tight": 6}
    d = FakeDrivers(bbox_mm=(10, 20, 30), volume_cm3=100.0)
    mat = FakeMaterial("6061-T6 Aluminum", 2.7)
    for tc, it in (("standard", 11), ("precision", 8), ("tight", 6)):
        pr = part_req_from_drivers("cnc_3axis", d, mat, tc)
        assert pr.tolerance_it == it


def test_part_req_mass_and_class():
    d = FakeDrivers(bbox_mm=(10, 20, 30), volume_cm3=100.0)
    mat = FakeMaterial("6061-T6 Aluminum", 2.7)
    pr = part_req_from_drivers("cnc_3axis", d, mat, "standard")
    assert pr.mass_kg == pytest.approx(100.0 * 2.7 / 1000.0)
    assert pr.material_class == "aluminum"
    assert pr.bbox_mm == (10, 20, 30)


def test_part_req_mass_none_without_density():
    d = FakeDrivers(bbox_mm=(10, 20, 30))
    pr = part_req_from_drivers("cnc_3axis", d, "MysteryAlloy", "standard")
    assert pr.mass_kg is None  # honesty: no density → no fabricated mass


def test_part_req_secondary_ops_metal_am_stress_relief():
    d = FakeDrivers(bbox_mm=(10, 20, 30), volume_cm3=100.0)
    mat = FakeMaterial("Ti6Al4V", 4.43)
    pr = part_req_from_drivers("dmls", d, mat, "standard")
    assert "stress_relief" in pr.required_secondary_ops


def test_part_req_secondary_ops_binder_jet_sinter():
    d = FakeDrivers(bbox_mm=(10, 20, 30), volume_cm3=100.0)
    mat = FakeMaterial("17-4 PH SS", 7.78)
    pr = part_req_from_drivers("binder_jetting", d, mat, "standard")
    assert "sinter" in pr.required_secondary_ops


def test_part_req_secondary_ops_hip_from_env():
    d = FakeDrivers(bbox_mm=(10, 20, 30), volume_cm3=100.0)
    mat = FakeMaterial("17-4 PH (Cast)", 7.78)
    pr = part_req_from_drivers("investment_casting", d, mat, "standard",
                               env={"pressure_bar": 150})
    assert "hip" in pr.required_secondary_ops


def test_part_req_secondary_ops_grinding_from_tight_tolerance():
    d = FakeDrivers(bbox_mm=(10, 20, 30), volume_cm3=100.0)
    mat = FakeMaterial("6061-T6 Aluminum", 2.7)
    pr = part_req_from_drivers("cnc_3axis", d, mat, "tight")  # IT6 < base IT9
    assert "grinding" in pr.required_secondary_ops


# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT gate (spec §6)
# ─────────────────────────────────────────────────────────────────────────────


def test_env_no_env_is_noop():
    valid, exclusions = environment_gate(
        ["cnc_3axis"], ["6061-T6 Aluminum"], None, {})
    assert exclusions == ()
    assert valid["routes"] == ["cnc_3axis"]
    assert valid["materials"] == ["6061-T6 Aluminum"]


def test_env_sour_excludes_aluminium_cites_nace():
    props = {"6061-T6 Aluminum": {"class": "aluminum", "nace_mr0175": False,
                                  "sour_service": False}}
    valid, exclusions = environment_gate(
        ["cnc_3axis"], ["6061-T6 Aluminum"], {"sour_service": True}, props)
    assert "6061-T6 Aluminum" in valid["excluded_materials"]
    assert len(exclusions) == 1
    ex = exclusions[0]
    assert "NACE MR0175" in ex.human and ex.need == "NACE MR0175 sour-service qualified"


def test_env_sour_allows_nace_material():
    props = {"AISI 4130": {"class": "steel", "nace_mr0175": True,
                           "sour_service": True}}
    valid, exclusions = environment_gate(
        ["forging"], ["AISI 4130"], {"sour_service": True}, props)
    assert exclusions == () and valid["materials"] == ["AISI 4130"]


def test_env_over_temp_excludes_polymer_cites_max_temp():
    props = {"PEEK": {"class": "polymer", "max_temperature_c": 260}}
    valid, exclusions = environment_gate(
        ["cnc_3axis"], ["PEEK"], {"max_temp_c": 400}, props)
    assert "PEEK" in valid["excluded_materials"]
    assert "max service temperature" in exclusions[0].human


def test_env_corrosive_excludes_carbon_steel():
    props = {"Mild Steel": {"class": "steel", "nace_mr0175": False}}
    valid, exclusions = environment_gate(
        ["sheet_metal"], ["Mild Steel"], {"corrosive": True}, props)
    assert "Mild Steel" in valid["excluded_materials"]
    assert "CRA" in exclusions[0].human


def test_env_excluded_processes():
    valid, exclusions = environment_gate(
        ["dmls", "forging"], ["Ti6Al4V"], {"excluded_processes": ["dmls"]},
        {"Ti6Al4V": {"class": "titanium"}})
    assert "dmls" in valid["excluded_routes"]
    assert "forging" in valid["routes"] and "dmls" not in valid["routes"]


# ── integration: the gate on REAL loaded MaterialProfiles (defect D) ─────────
# NOT hand-crafted flat dicts. The actual loader produces MaterialProfiles whose
# compliance flags live NESTED under MaterialProfile.compliance — exactly the
# shape the future Phase-C wiring feeds. This proves the gate reads that nested
# shape (previously it read flat only and silently saw NO qualification, wrongly
# excluding every NACE/sour-qualified alloy).
def _real_material_props(names: list[str]) -> dict:
    from dataclasses import asdict

    from src.profiles.loader import load_yaml_materials

    by_name = {m.name: m for m in load_yaml_materials()}
    return {n: asdict(by_name[n]) for n in names}


def test_env_gate_on_real_loaded_profiles_flips_sour_exclusion():
    props = _real_material_props(["API 13Cr", "ASTM A105"])
    # sanity: the flags really ARE nested under 'compliance' (the shape that used
    # to defeat the flat read), not flattened onto the top level.
    assert "nace_mr0175" not in props["API 13Cr"]
    assert props["API 13Cr"]["compliance"]["sour_service"] is True
    assert props["ASTM A105"]["compliance"]["nace_mr0175"] is False

    valid, exclusions = environment_gate(
        ["forging", "cnc_3axis"],
        ["API 13Cr", "ASTM A105"],
        {"sour_service": True},
        props,
    )
    # API 13Cr is NACE MR0175 / sour-qualified → allowed; A105 is not → excluded.
    assert "API 13Cr" not in valid["excluded_materials"]
    assert "API 13Cr" in valid["materials"]
    assert "ASTM A105" in valid["excluded_materials"]
    # the exclusion cites the standard on the offending (nested-flag) material
    a105 = [e for e in exclusions if e.axis == "ASTM A105"]
    assert a105 and "NACE MR0175" in a105[0].human


# ─────────────────────────────────────────────────────────────────────────────
# GAP analysis — minimal delta, binding-constraint-first, multi-failure collapse
# ─────────────────────────────────────────────────────────────────────────────


def test_gap_single_failure():
    m = mill(x=305, y=305, z=305, materials=("aluminum",))
    fr = fit_machine(part(bbox=(100, 200, 380)), m)
    gap = gap_analysis([fr])
    assert len(gap) == 1 and gap[0].gate == "envelope" and gap[0].need == 380


def test_gap_minimal_delta_across_machines():
    # two machines both too small on Z; closest is 305 → gap cites the 305, not 250
    m1 = mill(name="small", x=305, y=305, z=250, materials=("aluminum",))
    m2 = mill(name="bigger", x=305, y=305, z=305, materials=("aluminum",))
    p = part(bbox=(100, 200, 380))
    fits = [fit_machine(p, m1), fit_machine(p, m2)]
    gap = gap_analysis(fits)
    env = [g for g in gap if g.gate == "envelope"][0]
    assert env.have == 305  # smallest delta = closest machine


def test_gap_binding_constraint_first():
    # machine fails BOTH material (categorical) and envelope; envelope leads
    m = mill(x=100, y=100, z=100, materials=("steel",))
    fr = fit_machine(part(bbox=(150, 150, 150), material_name="Inconel 718",
                          material_class="nickel"), m)
    gap = gap_analysis([fr])
    gates = [g.gate for g in gap]
    assert gates[0] == "envelope"  # envelope defines the machine class → binding first
    assert "material" in gates


def test_gap_excludes_unknowns():
    # unknown (undeclared) failures must not appear as a concrete gap
    m = MachineCap(process="cnc_3axis", name="n", max_workpiece_kg=None,
                   hourly_rate_usd=75, materials=("steel",),
                   capabilities={"x": 100, "y": 100, "z": 100, "axes": 3})
    fr = fit_machine(part(bbox=(150, 150, 150), material_name="Inconel 718",
                          material_class="nickel"), m)
    gap = gap_analysis([fr])
    assert all(g.have is not None for g in gap)  # no unknowns in the gap
    assert "mass" not in {g.gate for g in gap}   # the undeclared-mass unknown dropped


def test_gap_accepts_bare_failures():
    fs = [FitFailure("envelope", "envelope", 380, 305, "z"),
          FitFailure("material", "material", "Inconel 718", ("steel",), "mat")]
    gap = gap_analysis(fs)
    assert gap[0].gate == "envelope"


# ─────────────────────────────────────────────────────────────────────────────
# VERDICT LATTICE (§0) — every outcome via a crafted case
# ─────────────────────────────────────────────────────────────────────────────


def test_verdict_makeable_in_house():
    inv = [mill()]
    v = verify_part({"cnc_3axis": part()}, inv)
    assert v.verdict == "makeable_in_house"
    assert v.best_machine == "Haas VF-2"
    assert v.resource["hourly_rate_usd"] == 75


def test_verdict_makeable_with_secondary_op():
    inv = [mill(it=9)]
    shop = ShopCaps(ops={"grinding": True})
    v = verify_part({"cnc_3axis": part(it=6)}, inv, shop)
    assert v.verdict == "makeable_with_secondary_op"
    assert "grinding" in v.resource["secondary_ops"]


def test_verdict_makeable_not_on_owned_with_gap():
    inv = [mill(x=305, y=305, z=305, materials=("aluminum",))]
    v = verify_part({"cnc_3axis": part(bbox=(100, 200, 380))}, inv)
    assert v.verdict == "makeable_not_on_owned"
    assert v.gap and v.gap[0].gate == "envelope" and v.gap[0].need == 380


def test_verdict_not_on_owned_when_required_op_absent():
    # owns the DMLS machine, but the mandated stress-relief op is not in-house
    m = MachineCap(process="dmls", name="EOS", max_workpiece_kg=50,
                   hourly_rate_usd=180, materials=("Ti6Al4V", "titanium"),
                   capabilities={"x": 400, "y": 400, "z": 400})
    p = part(process="dmls", material_name="Ti6Al4V", material_class="titanium",
             bbox=(50, 100, 200), sec=("stress_relief",), it=STANDARD_IT)
    v = verify_part({"dmls": p}, [m], ShopCaps(ops={}))
    assert v.verdict == "makeable_not_on_owned"
    assert any(g.gate == "secondary_op" for g in v.gap)


def test_verdict_makeable_outsource_only():
    # owns a mill, but the route is turning → owns nothing of that family
    inv = [mill(process="cnc_3axis")]
    v = verify_part({"cnc_turning": part(process="cnc_turning",
                                         material_name="304 Stainless",
                                         material_class="stainless",
                                         rotational=True, dia=50, length=100)}, inv)
    assert v.verdict == "makeable_outsource_only"


def test_verdict_environment_excluded():
    inv = [mill(materials=("aluminum",))]
    props = {"6061-T6 Aluminum": {"class": "aluminum", "nace_mr0175": False,
                                  "sour_service": False}}
    v = verify_part({"cnc_3axis": part()}, inv, env={"sour_service": True},
                    material_props=props)
    assert v.verdict == "environment_excluded"
    assert v.env_exclusions and "NACE" in v.env_exclusions[0].human


def test_verdict_unknown_no_inventory():
    v = verify_part({"cnc_3axis": part()}, [])
    assert v.verdict == "unknown"
    assert v.gap == () and v.env_exclusions == () and v.resource is None


def test_verdict_unknown_missing_capability_not_fabricated_pass():
    # machine owns family but a required capability is UNDECLARED → unknown,
    # never a fabricated makeable
    m = MachineCap(process="cnc_3axis", name="mystery", max_workpiece_kg=None,
                   hourly_rate_usd=75, materials=("aluminum",),
                   capabilities={"axes": 3})  # no envelope, no mass
    v = verify_part({"cnc_3axis": part()}, [m])
    assert v.verdict == "unknown"


def test_verdict_not_makeable_empty_routes():
    v = verify_part({}, [mill()])
    assert v.verdict == "not_makeable"


def test_verdict_prefers_in_house_over_secondary():
    # one machine passes clean, another needs grinding → in_house wins
    clean = mill(name="precise", it=6)
    coarse = mill(name="coarse", it=9)
    shop = ShopCaps(ops={"grinding": True})
    v = verify_part({"cnc_3axis": part(it=6)}, [coarse, clean], shop)
    assert v.verdict == "makeable_in_house" and v.best_machine == "precise"


def test_verdict_picks_cheapest_passing_machine():
    cheap = mill(name="cheap", rate=50)
    pricey = mill(name="pricey", rate=200)
    v = verify_part({"cnc_3axis": part()}, [pricey, cheap])
    assert v.best_machine == "cheap"


# ─────────────────────────────────────────────────────────────────────────────
# HONESTY INVARIANTS (spec §2)
# ─────────────────────────────────────────────────────────────────────────────


def test_honesty_empty_inventory_byte_identical_unknown():
    # empty inventory + no env → identical unknown regardless of routes
    v1 = verify_part({"cnc_3axis": part()}, [], None, None, {})
    v2 = verify_part({"dmls": part(process="dmls")}, [], None, None, {})
    assert v1 == v2 == verify_part({}, [], None, None, {})  # all bare unknown
    assert v1.verdict == "unknown"


def test_honesty_no_env_gate_is_noop():
    valid, exclusions = environment_gate(["cnc_3axis"], ["Anything"], None)
    assert (valid["routes"], valid["materials"], exclusions) == (
        ["cnc_3axis"], ["Anything"], ())


def test_honesty_never_pass_on_missing_field():
    # every gate that lacks its datum contributes an unknown; none is a pass
    m = MachineCap(process="cnc_3axis", name="bare", max_workpiece_kg=None,
                   hourly_rate_usd=None, materials=(), capabilities={})
    fr = fit_machine(part(it=6), m)
    assert not fr.passes
    # unknowns present for envelope, mass, material, tolerance
    unknown_gates = {f.gate for f in fr.failures if f.have is None}
    assert {"envelope", "mass", "material", "tolerance"} <= unknown_gates


def test_honesty_gap_is_quantified():
    m = mill(x=305, y=305, z=305, materials=("aluminum",))
    v = verify_part({"cnc_3axis": part(bbox=(100, 200, 380))}, [m])
    g = v.gap[0]
    assert g.need == 380 and g.have == 305  # concrete measured-vs-declared delta


def test_env_exclusion_cites_property():
    props = {"6061-T6 Aluminum": {"class": "aluminum"}}
    _, exclusions = environment_gate(["cnc_3axis"], ["6061-T6 Aluminum"],
                                     {"sour_service": True}, props)
    # exclusion must carry the standard + the offending property, not a naked drop
    assert exclusions[0].gate == "environment"
    assert "nace_mr0175" in exclusions[0].have
