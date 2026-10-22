"""Owned-machine answers for unedited catalog machines (engine audit W1, W4, W5, M1, M2).

Each case adds a catalog machine exactly as the forms save it (validate, store,
hydrate as load_org_inventory does) and checks the part against it on the real
cost path.
"""
from __future__ import annotations

import types

import pytest
import trimesh

from src.costing import EstimateOptions, estimate_decision, report_to_dict
from src.costing.makeability import MachineCap, ShopCaps, material_declared
from src.services import machine_inventory_service as mis

from tests.test_costing_model import _analyze


def _catalog_cap(name: str) -> MachineCap:
    payload = next(p for p in mis.catalog_options() if p["name"] == name)
    mis.validate_machine(payload)
    row = types.SimpleNamespace(**mis._normalize(payload))
    return MachineCap(process=row.process, name=row.name, count=row.count or 1,
                      max_workpiece_kg=row.max_workpiece_kg, hourly_rate_usd=row.hourly_rate_usd,
                      capital_frac=row.capital_frac, materials=tuple(row.materials or ()),
                      material_thickness_map=dict(row.material_thickness_map or {}),
                      capabilities=mis._engine_capabilities(row))


def _run(name: str, material_class: str, size=30.0, ops=None):
    result, mesh, feats = _analyze(trimesh.creation.box(extents=[size, size, size]))
    opts = EstimateOptions(quantities=[1, 10], material_class=material_class,
                           material_class_is_user=material_class != "polymer",
                           inventory=(_catalog_cap(name),), shop_caps=ShopCaps(ops=ops or {}))
    return report_to_dict(estimate_decision(result, mesh, feats, opts))


def _route(rep, proc):
    return rep["verification"]["per_route"][proc]


def test_one_material_under_two_registry_names_qualifies():
    # W4: the printing powder row and the bar row are the same alloy.
    assert material_declared("Ti-6Al-4V Grade 5", "titanium", ("Ti6Al4V",))
    assert material_declared("Ti6Al4V", "titanium", ("Ti-6Al-4V Grade 5",))
    assert material_declared("PP (Polypropylene)", "polymer", ("PP (MJF)",))
    assert material_declared("Delrin (POM)", "polymer", ("aluminum", "polymer"))
    assert not material_declared("PLA", "polymer", ("ABS", "ULTEM 9085"))
    assert not material_declared("Inconel 718", "nickel", ("Ti6Al4V",))


@pytest.mark.parametrize("name, cls, proc", [
    ("HP Jet Fusion 5200", "polymer", "mjf"),       # declared PA12, PA11, PP (MJF)
    ("Stratasys F900", "polymer", "fdm"),           # declared ULTEM 9085, CF-Nylon, ABS: no PLA
    ("Haas VF-2", "polymer", "cnc_3axis"),          # the default plastic on a mill (W5)
    ("Haas ST-20", "polymer", "cnc_turning"),
])
def test_an_unedited_catalog_machine_that_fits_makes_the_part_in_house(name, cls, proc):
    if proc == "cnc_turning":
        result, mesh, feats = _analyze(trimesh.creation.cylinder(radius=15, height=40, sections=64))
        opts = EstimateOptions(quantities=[1, 10], material_class=cls,
                               inventory=(_catalog_cap(name),), shop_caps=ShopCaps(ops={}))
        rep = report_to_dict(estimate_decision(result, mesh, feats, opts))
    else:
        rep = _run(name, cls)
    route = _route(rep, proc)
    assert route["verdict"] == "makeable_in_house", route
    assert route["best_machine"] == name
    est = [e for e in rep["estimates"] if e["process"] == proc]
    # Priced in a material the machine is declared for, and as owned (M1).
    cap = _catalog_cap(name)
    assert all(material_declared(e["material"], cls, cap.materials) for e in est)
    assert all(e.get("owned_in_house") is True for e in est)


def test_the_f900_route_is_priced_in_a_material_it_runs():
    rep = _run("Stratasys F900", "polymer")
    fdm = {e["material"] for e in rep["estimates"] if e["process"] == "fdm"}
    assert fdm == {"ABS"}  # its cheapest declared plastic, not PLA


def test_an_owned_machine_is_priced_owned_without_a_typed_rate():
    # M1: no $/h typed, no owned_processes passed: the inventory says it's yours.
    rep = _run("Haas VF-2", "aluminum")
    mill = [e for e in rep["estimates"] if e["process"] == "cnc_3axis"]
    assert mill and all(e.get("owned_in_house") is True for e in mill)
    assert any(d["name"] == "owned_in_house" for d in mill[0]["drivers"])
    # Routes you own nothing for stay at the outside rate.
    assert all(not e.get("owned_in_house") for e in rep["estimates"] if e["process"] != "cnc_3axis")


@pytest.mark.parametrize("name, cls, proc, op, words", [
    ("EOS M 400-4", "titanium", "dmls", "stress_relief", "stress relief"),
    ("SLM 500", "titanium", "slm", "stress_relief", "stress relief"),
    ("Arcam Q20plus", "titanium", "ebm", "stress_relief", "stress relief"),
    ("Desktop Metal Shop System", "stainless", "binder_jetting", "sinter", "sintering"),
])
def test_the_machines_own_post_processing_is_assumed_in_house_and_said(name, cls, proc, op, words):
    # Round 7 (owner's call): an unedited metal printer or binder jetter that fits
    # makes the part in-house; its own stress relief or sintering is assumed done
    # by the shop that owns it, in one line, until Your shop says it's sent out.
    rep = _run(name, cls, size=40.0)
    route = _route(rep, proc)
    assert route["verdict"] == "makeable_with_secondary_op", route
    assert route["best_machine"] == name and route["failures"] == []
    assert route["assumed_in_house"] == [op]
    assert f"Assumes your shop does its own {words}; change this in Your shop" in route["notes"]
    assert rep["verification"]["verdict"] == "makeable_with_secondary_op"
    # Declared in-house: no assumption to state. Declared sent out: still made on
    # the machine, the step bought outside.
    done = _route(_run(name, cls, size=40.0, ops={op: True}), proc)
    assert done["verdict"] == "makeable_with_secondary_op" and "assumed_in_house" not in done
    out = _route(_run(name, cls, size=40.0, ops={op: False}), proc)
    assert out["verdict"] == "makeable_with_secondary_op" and out["sent_out"] == [op]


def test_a_catalog_carbon_m2_carries_its_materials_and_makes_a_plastic_part():
    # Round 7: Carbon's resins have no price in ScaleCAD; the catalog entry
    # declares their class (plastic) instead of nothing, and says which resins.
    payload = next(p for p in mis.catalog_options() if p["name"] == "Carbon M2")
    assert payload["materials"] == ["polymer"]
    assert "RPU 70, EPU 41 and CE 221" in payload["spec"]["materials_note"]
    assert payload["field_provenance"]["materials"]["source"] == "maker_described"
    rep = _run("Carbon M2", "polymer", size=20.0)
    route = _route(rep, "dlp")
    assert route["verdict"] == "makeable_in_house" and route["best_machine"] == "Carbon M2"
    assert rep["verification"]["verdict"] == "makeable_in_house"
    dlp = [e for e in rep["estimates"] if e["process"] == "dlp"]
    assert dlp and all(e.get("owned_in_house") is True for e in dlp)


def test_a_sand_printer_says_it_prints_molds_not_metal_parts():
    # The ExOne S-Max Pro prints sand molds and cores. Unedited, it says so for a
    # stainless part, rather than "no qualified materials declared".
    payload = next(p for p in mis.catalog_options() if p["name"] == "ExOne S-Max Pro")
    assert payload["materials"] == ["sand"]
    rep = _run("ExOne S-Max Pro", "stainless", size=40.0)
    route = _route(rep, "binder_jetting")
    assert route["verdict"] == "makeable_not_on_owned", route
    mat = [f for f in route["failures"] if f["gate"] == "material"]
    assert mat and mat[0]["human"].startswith("prints sand molds and cores, not ")
    assert mat[0]["human"].endswith(" parts")


def _cup(wall):
    outer = trimesh.creation.box(extents=[60, 40, 30])
    outer.apply_translation([0, 0, 15])
    inner = trimesh.creation.box(extents=[60 - 2 * wall, 40 - 2 * wall, 30])
    inner.apply_translation([0, 0, 15 + wall])
    return trimesh.boolean.difference([outer, inner], engine="manifold")


@pytest.mark.parametrize("wall, verdict", [(0.5, "fail"), (0.6, "issues"), (1.0, "pass")])
def test_the_fdm_wall_floor_follows_a_standard_nozzle(wall, verdict):
    # W2: a 0.4 mm nozzle lays a 0.6 mm wall; below two perimeters it's weak, not unmakeable.
    result, mesh, feats = _analyze(_cup(wall))
    fdm = next(p for p in result.process_scores if p.process.value == "fdm")
    assert fdm.verdict == verdict
    opts = EstimateOptions(quantities=[1, 10], inventory=(_catalog_cap("Bambu Lab X1C"),),
                           shop_caps=ShopCaps(ops={}))
    rep = report_to_dict(estimate_decision(result, mesh, feats, opts))
    route = _route(rep, "fdm")
    if verdict == "fail":
        assert route["verdict"] == "not_makeable"
    else:
        assert route["verdict"] == "makeable_in_house"
        assert rep["verification"]["verdict"] == "makeable_in_house"


# ── W3 / M3 / W13: size is a machine's question, one envelope per process ─────
def test_one_build_envelope_per_process_for_dfm_and_price():
    from src.analysis.models import ProcessType as PT
    from src.costing.rates import build_rate_card
    from src.profiles.envelopes import common_envelope

    rates = build_rate_card()
    for p in (PT.FDM, PT.SLA, PT.DLP, PT.SLS, PT.MJF, PT.DMLS, PT.SLM, PT.EBM, PT.BINDER_JET):
        assert rates.build_env(p) == common_envelope(p), p


def test_bigger_than_the_common_size_is_a_warning_and_bigger_than_every_machine_an_error():
    def fdm(size):
        result, _mesh, _f = _analyze(trimesh.creation.box(extents=list(size)))
        return next(p for p in result.process_scores if p.process.value == "fdm")

    big = fdm((400, 400, 400))
    issue = next(i for i in big.issues if i.code == "EXCEEDS_BUILD_VOLUME")
    assert big.verdict != "fail" and issue.severity.value == "warning"
    assert "300 x 300 x 350mm build size" in issue.message
    assert "Stratasys F900" in issue.message or "BigRep ONE" in issue.message
    huge = fdm((2000, 1200, 1100))
    assert huge.verdict == "fail"
    assert any(i.code == "EXCEEDS_BUILD_VOLUME" and i.severity.value == "error"
               and "Larger than any filament printing (FDM/FFF) machine ScaleCAD knows" in i.message for i in huge.issues)


@pytest.mark.parametrize("name, size, cls, verdict, needs", [
    ("BigRep ONE", 854, "polymer", "makeable_in_house", None),
    ("DMG MORI DMU 50", 450, "aluminum", "makeable_in_house", None),
    ("Bambu Lab X1C", 333, "polymer", "makeable_not_on_owned", "too big for your Bambu Lab X1C: needs 333 mm, has 256 mm"),
    ("BigRep ONE", 1306, "polymer", "makeable_not_on_owned", "too big for your BigRep ONE: needs 1306 mm, has 1005 mm"),
])
def test_size_against_the_shops_own_machine(name, size, cls, verdict, needs):
    rep = _run(name, cls, size=size)
    proc = _catalog_cap(name).process
    route = _route(rep, proc)
    assert route["verdict"] == verdict, route
    if needs:
        assert any(f["human"].startswith(needs) for f in route["failures"])
    else:
        # priced on the owned machine's own work area
        assert any(e["process"] == proc for e in rep["estimates"])


def test_a_binder_jet_size_miss_says_the_green_part_is_printed_oversize():
    # Round 7: a part at 85% of the Shop System's work area misses because the
    # green part is printed 18% oversize (it shrinks to size when sintered): the
    # engine is right, and the message says why.
    result, mesh, feats = _analyze(trimesh.creation.box(extents=[170.0, 187.0, 297.5]))
    opts = EstimateOptions(quantities=[1, 10], material_class="stainless", material_class_is_user=True,
                           inventory=(_catalog_cap("Desktop Metal Shop System"),), shop_caps=ShopCaps(ops={}))
    rep = report_to_dict(estimate_decision(result, mesh, feats, opts))
    route = _route(rep, "binder_jetting")
    assert route["verdict"] == "makeable_not_on_owned", route
    env = [f for f in route["failures"] if f["gate"] == "envelope"]
    assert env and env[0]["need"] == pytest.approx(170.0 * 1.18, abs=0.5) and env[0]["have"] == pytest.approx(200.0)
    assert env[0]["human"] == (
        "too big for your Desktop Metal Shop System: needs 201 mm, has 200 mm (its narrowest width "
        "against the work area's smallest side; printed 18% oversize so it shrinks to size when sintered)")
    # A route printed at size says nothing about oversize.
    assert not any("oversize" in f["human"] for r in rep["verification"]["per_route"].values()
                   for f in r["failures"] if r is not route)


def test_a_lathe_size_miss_reads_in_whole_millimetres():
    # Round 7 item 8: the turning envelope sentence rounds like every other size.
    result, mesh, feats = _analyze(trimesh.creation.cylinder(radius=134.4071, height=120.0, sections=96))
    opts = EstimateOptions(quantities=[1, 10], material_class="aluminum", material_class_is_user=True,
                           inventory=(_catalog_cap("Haas ST-20"),), shop_caps=ShopCaps(ops={}))
    rep = report_to_dict(estimate_decision(result, mesh, feats, opts))
    route = _route(rep, "cnc_turning")
    env = [f for f in route["failures"] if f["gate"] == "envelope"]
    assert env, route
    assert env[0]["human"] == "too big for your Haas ST-20: needs 269 mm, has 254 mm (swing diameter)"
