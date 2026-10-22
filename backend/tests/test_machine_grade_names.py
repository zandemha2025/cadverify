"""A job shop's grades are taken as it writes them (me-01).

Adding a Haas VF-2 with "6061, 7075, 303, 304, 316, 17-4, 4140, Delrin" was
refused: "unknown material '303' ... '316' (closest: SS316L) ... '17-4'", in an
error below the dialog's fold. Each grade now reads as the registry material it
is priced as, and the ones ScaleCAD has no price of their own for say so.
"""

from __future__ import annotations

import pytest

from src.services.machine_inventory_service import _canonical_material, material_readings, validate_machine

HER_LIST = ["6061", "7075", "303", "304", "316", "17-4", "4140", "Delrin"]


def test_her_vf2_materials_are_accepted():
    validate_machine({"process": "cnc_3axis", "materials": HER_LIST})
    assert [_canonical_material(m, "cnc_3axis") for m in HER_LIST] == [
        "6061-T6 Aluminum", "7075-T6 Aluminum", "304 Stainless", "304 Stainless", "SS316L", "17-4 PH SS", "AISI 4140", "Delrin (POM)",
    ]


@pytest.mark.parametrize("typed,as_", [
    ("6061-T6", "6061-T6 Aluminum"), ("6061-T651", "6061-T6 Aluminum"), ("7075-T6", "7075-T6 Aluminum"),
    ("316", "SS316L"), ("316 SS", "SS316L"), ("17-4 PH", "17-4 PH SS"), ("17-4PH", "17-4 PH SS"),
    ("303 stainless", "304 Stainless"), ("1018", "Mild Steel"), ("A36", "Mild Steel"),
])
def test_common_grades_map_to_what_they_are_priced_as(typed, as_):
    assert _canonical_material(typed, "cnc_turning") == as_


def test_what_each_grade_was_read_as_is_said():
    r = {x["typed"]: x for x in material_readings(HER_LIST, "cnc_3axis")}
    assert r["303"]["as"] == "304 Stainless"
    assert r["303"]["note"] == "ScaleCAD has no 303 price; read as 304 Stainless, the closest stainless it prices"
    assert r["316"]["note"] == "316 is read as 316L (SS316L), the 316 stainless ScaleCAD prices"
    assert r["17-4"]["note"].startswith("ScaleCAD prices 17-4 PH for binder jetting and investment casting")
    # A plain spelling of a priced material reads as it, with no note.
    assert r["6061"] == {"typed": "6061", "as": "6061-T6 Aluminum", "note": None}
    # On a binder-jet printer 17-4 PH is priced as itself: no note.
    assert material_readings(["17-4 PH"], "binder_jetting") == [{"typed": "17-4 PH", "as": "17-4 PH SS", "note": None}]
    # A material stored as typed isn't listed; an unknown one is refused, never read as something.
    assert material_readings(["SS316L"], "cnc_3axis") == []
    with pytest.raises(ValueError, match="unknown material 'Inconel 9999'"):
        validate_machine({"process": "cnc_3axis", "materials": ["Inconel 9999"]})
