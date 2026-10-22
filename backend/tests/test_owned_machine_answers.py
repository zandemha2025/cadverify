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


def test_post_processing_never_asked_is_unknown_not_missing():
    # M2 + W1: an unedited metal printer that fits, stress relief never declared.
    rep = _run("EOS M 400-4", "titanium", size=40.0)
    route = _route(rep, "dmls")
    assert route["verdict"] == "unknown"
    assert [(f["gate"], f["have"]) for f in route["failures"]] == [("secondary_op", None)]
    assert "not declared whether you do it in-house" in route["failures"][0]["human"]
    assert rep["verification"]["verdict"] == "unknown"  # not "outside only"
    # Declared: in-house with the op; declared unavailable: a real gap.
    done = _run("EOS M 400-4", "titanium", size=40.0, ops={"stress_relief": True})
    assert _route(done, "dmls")["verdict"] == "makeable_with_secondary_op"
    none = _run("EOS M 400-4", "titanium", size=40.0, ops={"stress_relief": False})
    assert _route(none, "dmls")["verdict"] == "makeable_not_on_owned"


def test_a_printer_with_no_materials_declared_is_cant_confirm_not_outside_only():
    # W1: Carbon M2 unedited (its resins have no registry equivalent).
    rep = _run("Carbon M2", "polymer", size=20.0)
    assert _route(rep, "dlp")["verdict"] == "unknown"
    assert rep["verification"]["verdict"] == "unknown"
