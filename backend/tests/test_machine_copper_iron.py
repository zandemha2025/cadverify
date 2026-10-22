"""Brass, bronze and ductile iron on a job shop's machines (op-03).

Adding a Haas VF-2 with "Brass C360, bronze" was refused as an unknown material.
ScaleCAD prices no brass, bronze or copper part on a mill or lathe, so they stay
on the machine as typed and the save says "not priced yet"; ductile iron is read
as the steel a mill prices an iron part in, and says so. A run says "not priced
yet" once per material, with its parts, on the run page and in the pilot report.
"""
from __future__ import annotations

import types

import pytest

from src.services import catalog_run_service as cr
from src.services import machine_inventory_service as mis
from src.services import pilot_report_service as pr

HER_LIST = ["6061", "303", "Brass C360", "bronze", "ductile iron"]


def test_brass_bronze_and_ductile_iron_are_accepted_on_a_mill():
    mis.validate_machine({"process": "cnc_3axis", "materials": HER_LIST})
    assert [mis._canonical_material(m, "cnc_3axis") for m in HER_LIST] == [
        "6061-T6 Aluminum", "304 Stainless", "Brass C360", "bronze", "Mild Steel"]
    r = {x["typed"]: x for x in mis.material_readings(HER_LIST, "cnc_3axis")}
    assert r["Brass C360"] == {"typed": "Brass C360", "as": None, "note": (
        "ScaleCAD doesn't price brass yet: Brass C360 stays on the machine, and a brass part shows as not priced yet")}
    assert r["bronze"]["as"] is None and r["bronze"]["note"].startswith("ScaleCAD doesn't price bronze yet")
    assert r["ductile iron"] == {"typed": "ductile iron", "as": "Mild Steel", "note": (
        "ScaleCAD has no iron price on a 3-axis mill; ductile iron is read as Mild Steel, "
        "the steel it prices an iron part in there")}


@pytest.mark.parametrize("typed", ["C360", "C93200", "C932 bearing bronze", "copper", "C110", "Copper C110 (Sheet)"])
def test_copper_alloys_by_number_stay_as_typed_on_a_lathe(typed):
    assert mis._canonical_material(typed, "cnc_turning") == typed
    assert mis.materials_not_priced([typed], "cnc_turning") == [typed]


def test_where_scaleCAD_prices_the_material_itself_it_is_that_material():
    # A sheet-metal line prices C110 sheet; a sand mold prices Ductile Iron.
    assert mis._canonical_material("copper", "sheet_metal") == "Copper C110 (Sheet)"
    assert mis.material_readings(["Copper C110 (Sheet)"], "sheet_metal") == []
    assert mis._canonical_material("65-45-12", "sand_casting") == "Ductile Iron"
    assert mis.material_readings(["grey iron"], "sand_casting")[0]["note"] == (
        "grey iron is read as Ductile Iron, the iron ScaleCAD prices")
    # Hastelloy C276 is a nickel alloy, not a copper number; a bare C276 is still refused.
    assert mis._canonical_material("Hastelloy C276", "cnc_3axis") == "Hastelloy C276"
    with pytest.raises(ValueError, match="unknown material 'C276'"):
        mis.validate_machine({"process": "cnc_3axis", "materials": ["C276"]})
    # A printer of plastics takes none of them.
    with pytest.raises(ValueError, match="unknown material 'brass'"):
        mis.validate_machine({"process": "fdm", "materials": ["brass"]})


def test_the_machine_says_which_materials_are_not_priced_yet():
    row = types.SimpleNamespace(
        ulid="M1", name="Haas VF-2", process="cnc_3axis", count=1, max_workpiece_kg=1361.0, hourly_rate_usd=85.0,
        capital_frac=None, capabilities={}, materials=["6061-T6 Aluminum", "Brass C360", "bronze"],
        material_thickness_map=None, notes=None, schedule=None, created_at=None, updated_at=None)
    assert mis.machine_to_public(row)["materials_not_priced"] == ["Brass C360", "bronze"]


def _brass_row(part):
    return {"bucket": "not_sorted", "part_number": part, "reason": "x",
            "material": {"declared": "Brass C360", "class": None, "note": "Brass C360 isn't priced in ScaleCAD yet"}}


def test_a_run_says_not_priced_yet_once_with_the_parts():
    assert cr.read_material("Brass C360")["note"] == "Brass C360 isn't priced in ScaleCAD yet"
    rows = [_brass_row(p) for p in ("RFS-21047", "RFS-21048", "RFS-21052", "RFS-21055")] + [
        {"bucket": "not_sorted", "part_number": "RFS-21050",
         "material": {"declared": "bronze", "class": None, "note": "bronze isn't priced in ScaleCAD yet"}},
        {"bucket": "not_sorted", "part_number": "RFS-21051", "material": {"declared": None}},
        {"bucket": "not_sorted", "part_number": "RFS-21053",
         "material": {"declared": "unobtainium", "class": None, "note": "unobtainium isn't a material ScaleCAD recognises"}}]
    a = cr.make_or_buy_answer(rows)
    assert (a["not_sorted"], a["not_priced"]) == (7, 5)
    assert a["not_priced_materials"] == [
        {"material": "Brass C360", "count": 4, "parts": ["RFS-21047", "RFS-21048", "RFS-21052", "RFS-21055"]},
        {"material": "bronze", "count": 1, "parts": ["RFS-21050"]}]
    w = pr.answer_words(a, True)
    assert w["sub"] == "7 can’t be decided yet (5 not priced yet, 2 not sorted) · parts on your list, at their listed quantities"
    assert w["missing"] == ("Not priced yet: Brass C360 (4 parts: RFS-21047, RFS-21048, RFS-21052 and 1 more); "
                            "bronze (1 part: RFS-21050). Their shapes were checked; they aren’t priced as anything else.")
    # The report's list of parts checked without a verdict says each reason once.
    groups = pr.coverage(rows)["unsorted_groups"]
    assert groups[0] == {"reason": "x", "parts": ["RFS-21047", "RFS-21048", "RFS-21052", "RFS-21055"]}


def test_the_parts_list_check_says_it_before_the_run():
    rows = cr.parse_parts_list("Part Number,Qty,Material\nRFS-21047,200,Brass C360\nRFS-21048,50,brass c360\n"
                               "RFS-21039,500,316\nRFS-21050,40,Bronze\n")
    got = cr.list_unpriced_materials(rows)
    assert got["count"] == 3
    assert got["groups"] == [{"material": "Brass C360", "count": 2, "parts": ["RFS-21047", "RFS-21048"]},
                             {"material": "Bronze", "count": 1, "parts": ["RFS-21050"]}]
