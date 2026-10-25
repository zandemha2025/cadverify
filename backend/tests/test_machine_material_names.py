"""Materials typed the way engineers and printer makers write them (feedback item 9).

The tester added a Bambu Lab X1C and saved "PLA, PETG, ABS, Nylon, TPU", the
materials Bambu Lab lists for it. The server refused the machine with a
paragraph of registry vocabulary for each of "Nylon" and "TPU". A machine's
materials now resolve per method: a filament printer's "Nylon" is the
registry's Nylon (PA6), its "TPU" is TPU 95A, and a maker's product names
("PLA Basic", "PETG HF") are the polymer they are. A name that matches
nothing, or more than one material on that method, is still refused, in one
short sentence naming the entry and the closest names.
"""
from __future__ import annotations

import pytest

from src.services import machine_inventory_service as svc


def _fdm(materials, **caps):
    return {"name": "Bambu Lab X1C", "process": "fdm", "materials": materials,
            "capabilities": {"x": 256, "y": 256, "z": 256, **caps}}


def _err(fields) -> str:
    with pytest.raises(ValueError) as exc:
        svc.validate_machine(fields)
    return str(exc.value)


@pytest.mark.parametrize("typed, stored", [
    (["PLA", "PETG", "ABS", "Nylon", "TPU"], ["PLA", "PETG", "ABS", "Nylon (PA6)", "TPU 95A"]),
    (["PLA Basic", "PETG HF", "PLA Matte", "PLA Silk"], ["PLA", "PETG"]),
    (["PA6-CF", "PAHT-CF", "PA-CF"], ["CF-Nylon"]),
    (["pa", "Pa6", "nylon 6"], ["Nylon (PA6)"]),
    (["TPU 95A HF", "TPU for AMS", "tpu95a"], ["TPU 95A"]),
    (["PC", "Ultem"], ["PC (Polycarbonate)", "ULTEM 9085"]),
    (["Nylon PA6", "polymer"], ["Nylon (PA6)", "polymer"]),
])
def test_a_filament_printer_takes_the_names_its_maker_uses(typed, stored):
    fields = _fdm(typed)
    svc.validate_machine(fields)  # no raise
    out = svc._normalize(fields)
    assert out["materials"] == stored


def test_the_same_word_means_the_registry_material_for_that_method():
    # Powder printers: PA12 and TPU are their own registry entries.
    sls = {"process": "sls", "materials": ["PA12", "TPU", "Nylon 12"]}
    svc.validate_machine(sls)
    assert svc._normalize(sls)["materials"] == ["PA12 (Nylon 12)", "TPU (SLS)"]
    mjf = {"process": "mjf", "materials": ["PA12", "PP"]}
    svc.validate_machine(mjf)
    assert svc._normalize(mjf)["materials"] == ["PA12 (Nylon 12)", "PP (MJF)"]
    # Resin printers: the catalog's short resin names.
    sla = {"process": "sla", "materials": ["Standard", "Tough"]}
    svc.validate_machine(sla)
    assert svc._normalize(sla)["materials"] == ["Standard Resin", "Tough Resin"]


def test_stocked_filament_resolves_the_same_way():
    fields = _fdm(["PLA"], stocked_materials=["PLA Basic", "PETG HF", "TPU"])
    svc.validate_machine(fields)
    assert svc._normalize(fields)["capabilities"]["stocked_materials"] == ["PLA", "PETG", "TPU 95A"]


def test_an_ambiguous_name_asks_which_one():
    msg = _err({"process": "sls", "materials": ["Nylon"]})
    assert msg.startswith("'Nylon' could be PA12 (Nylon 12) or PA11 on a powder printer")
    assert "accepted:" not in msg


def test_an_unknown_name_is_one_short_sentence_with_the_closest_names():
    msg = _err(_fdm(["PLA", "ASA", "Unobtainium"]))
    parts = msg.split("; ")
    assert len(parts) == 2
    assert parts[0].startswith("unknown material 'ASA'")
    assert "ABS" in parts[0]
    assert parts[1].startswith("unknown material 'Unobtainium'")
    # No wall of registry vocabulary: the filament list, not metals.
    assert "6061" not in msg and "SS316L" not in msg and "accepted:" not in msg
    assert len(parts[1]) < 260


def test_every_catalog_machine_saves_as_the_legacy_and_v4_forms_send_it():
    # Legacy form: name, process, count, envelope, materials joined/split by ", ", notes.
    for t in svc.catalog_options():
        cap = t["capabilities"]
        keys = ("swing_dia", "between_centers") if t["process"] == "cnc_turning" else ("x", "y", "z")
        legacy = {"name": t["name"], "process": t["process"], "count": 1,
                  "hourly_rate_usd": None, "max_workpiece_kg": t["max_workpiece_kg"],
                  "materials": [s.strip() for s in ", ".join(t["materials"] or []).split(",") if s.strip()] or None,
                  "capabilities": {k: cap[k] for k in keys if k in cap} or None,
                  "notes": t["notes"]}
        svc.validate_machine(legacy)
        svc.validate_machine(t)  # the v4 forms send the template as served


def test_the_raw_maker_names_from_the_live_catalog_now_save():
    # What the live catalog served for the X1C before its names were translated.
    svc.validate_machine(_fdm(["PLA", "PETG", "ABS", "Nylon", "TPU"]))
    svc.validate_machine({"process": "fdm", "materials": ["Nylon 12CF", "ABS-M30"]})
