"""Pure parts of the catalog run: parts lists, materials, quantities, board rows, CSV."""
from __future__ import annotations

import pytest

from src.services import catalog_run_service as cr


def test_parts_lists_as_boms_and_erp_exports_write_them():
    rows = cr.parse_parts_list(
        "﻿Part Number;Description;Qty;Material\n"
        "BRK-100;Bracket;1,200;6061-T6\n"
        "\n"
        "HSG-200;Housing;;PETG\n"
    )
    assert [(r["part_number"], r["quantity"], r["material_class"]) for r in rows] == [
        ("BRK-100", 1200, "aluminum"), ("HSG-200", None, "polymer"),
    ]
    assert rows[0]["description"] == "Bracket" and rows[0]["row"] == 2
    tabbed = cr.parse_parts_list("File\tQuantity\tMaterial\nparts/a.step\t5\tInconel 718\n")
    assert tabbed[0]["file"] == "parts/a.step" and tabbed[0]["material_class"] is None
    assert tabbed[0]["material_note"] == "Inconel 718 isn't priced in a catalog run yet"


@pytest.mark.parametrize("text, message", [
    ("Qty,Material\n1,PLA\n", "needs a column named filename"),
    ("filename,qty\na.stl,1.5\n", "Row 2: quantity '1.5' must be a whole number"),
    ("filename,qty\na.stl,lots\n", "Row 2: quantity 'lots' isn't a number"),
    ("filename,qty\n,3\n", "Row 2: no file name or part number"),
    ("", "The parts list is empty"),
])
def test_parts_list_errors_name_the_row(text, message):
    with pytest.raises(ValueError) as err:
        cr.parse_parts_list(text)
    assert message in str(err.value)


@pytest.mark.parametrize("text, cls", [
    ("6061-T6 Aluminum", "aluminum"), ("Al 7075", "aluminum"), ("aluminium", "aluminum"),
    ("304 SS", "stainless"), ("17-4 PH", "stainless"), ("316L", "stainless"), ("SS316L", "stainless"),
    ("AISI 4140", "steel"), ("A36", "steel"), ("mild steel", "steel"),
    ("Ti-6Al-4V", "titanium"), ("Titanium Gr 5", "titanium"),
    ("PLA", "polymer"), ("Delrin (POM)", "polymer"), ("PA12", "polymer"), ("PEEK", "polymer"),
    ("steel", "steel"), ("stainless", "stainless"),
])
def test_material_words_map_to_the_priced_classes(text, cls):
    assert cr.material_class_of(text) == (cls, None)


def test_unknown_or_unpriced_materials_say_so_instead_of_guessing():
    assert cr.material_class_of(None) == (None, None)
    assert cr.material_class_of("Brass C360")[0] is None
    assert cr.material_class_of("unobtainium") == (None, "unobtainium isn't a material ScaleCAD recognises")


def test_parts_list_rows_match_files_by_name_stem_or_part_number():
    rows = cr.parse_parts_list(
        "file,part number,qty\n"
        "Bracket.STEP,,2\n"
        "housing,,3\n"
        ",PIN-9,4\n"
        "missing.stl,,5\n"
        "bracket.step,,6\n"  # a second row for a file already matched
    )
    by_file, unmatched = cr.match_parts_list(rows, ["bracket.step", "housing.stl", "PIN-9.iges", "extra.stl"])
    assert {f: r["quantity"] for f, r in by_file.items()} == {"bracket.step": 2, "housing.stl": 3, "PIN-9.iges": 4}
    assert [r["quantity"] for r in unmatched] == [5, 6]


def test_quantity_ladder_matches_the_single_check():
    assert cr.quantity_ladder(None) == [1, 100, 1000, 2000, 5000, 10000]
    assert cr.quantity_ladder(1000) == [1, 100, 1000, 2000, 5000, 10000]
    assert cr.quantity_ladder(250) == [1, 250, 1000, 2000, 5000, 10000]
    assert cr.quantity_ladder(3000) == [1, 100, 1000, 3000, 5000, 10000]
    assert len(cr.quantity_ladder(7)) == 6


def _est(process, qty, unit, *, cycle=0.5, machine=10.0, material="6061-T6 Aluminum", ready=True, owned=False, blockers=()):
    drivers = [{"name": "cycle_time", "value": cycle, "unit": "hr"}, {"name": "machine_cost", "value": machine, "unit": "$"}]
    if owned:
        drivers.append({"name": "owned_in_house", "value": 0.65, "unit": "×"})
    return {"process": process, "quantity": qty, "unit_cost_usd": unit, "material": material, "dfm_ready": ready,
            "dfm_blockers": list(blockers), "drivers": drivers}


def _decision(verdict, *, estimates, make_now="cnc_3axis", rec=None, **verification):
    return {
        "ulid": "D1", "mesh_hash": "m" * 64,
        "result_json": {
            "status": "OK",
            "geometry": {"volume_cm3": 100.0},
            "estimates": estimates,
            "decision": {"make_now_process": make_now, "recommendation": rec or {}},
            "verification": {"verdict": verdict, "inventory_declared": True, **verification},
        },
    }


ITEM = {"ulid": "I1", "filename": "bracket.step", "status": "completed", "error_message": None, "duration_ms": 900.0}
MACHINES = [{"name": "Haas VF-2", "process": "cnc_3axis"}, {"name": "Bambu Lab X1C", "process": "fdm"}]


def _row(decision, meta=None, item=ITEM, analysis=None):
    return cr.derive_part_row(item=item, analysis=analysis, decision=decision, meta=meta, machines=MACHINES, default_quantity=10)


def test_in_house_leads_with_hours_material_and_the_marginal_cost():
    d = _decision(
        "makeable_in_house",
        estimates=[_est("cnc_3axis", 1, 90.0, owned=True), _est("cnc_3axis", 10, 30.0, cycle=0.25, machine=12.19, owned=True)],
        resource={"machine": "Haas VF-2", "process": "cnc_3axis"},
    )
    r = _row(d)
    assert (r["bucket"], r["reason"]) == ("in_house", "On your Haas VF-2 · 6061-T6 Aluminum")
    assert r["route"] == {"process": "cnc_3axis", "machine": "Haas VF-2", "owned": True}
    assert (r["hours_each"], r["hours_total"], r["machine_rate_usd"], r["marginal"]) == (0.25, 2.5, 48.76, True)
    assert r["material"]["mass_kg_each"] == pytest.approx(0.27)  # 100 cm³ × 2.7 g/cm³
    assert r["material"]["mass_basis"].startswith("measured volume 100 cm³")
    assert (r["unit_cost_usd"], r["total_cost_usd"], r["quantity"], r["quantity_source"]) == (30.0, 300.0, 10, "run")
    assert r["part_key"] == "m" * 64 and r["cost_decision_id"] == "D1"


def test_in_house_says_when_a_route_outside_is_cheaper():
    d = _decision(
        "makeable_in_house",
        estimates=[_est("cnc_3axis", 25, 31.38, owned=True), _est("ded", 25, 30.0)],
        make_now="ded",
        rec={"25": {"process": "ded", "unit_cost_usd": 30.0, "dfm_ready": True}},
        resource={"machine": "Haas VF-2", "process": "cnc_3axis"},
    )
    r = _row(d, meta={"quantity": 25})
    assert r["unit_cost_usd"] == 31.38 and r["cheaper_outside"] == {"process": "ded", "unit_cost_usd": 30.0}
    assert r["quantity_source"] == "list"


def test_buy_outside_names_the_process_none_of_your_machines_do():
    d = _decision("makeable_outsource_only", estimates=[_est("sls", 10, 12.5, material="PA12 (Nylon 12)")], make_now="sls")
    r = _row(d)
    assert r["bucket"] == "outside" and r["route"]["owned"] is False
    assert r["reason"].startswith("No machine of yours does ")
    assert r["unit_cost_usd"] == 12.5 and r["marginal"] is False


def test_needs_a_new_machine_names_the_missing_capability():
    fail = {"gate": "material", "axis": "material", "need": "304 Stainless", "have": ["aluminum", "steel"],
            "human": "not qualified for 304 Stainless"}
    d = _decision(
        "makeable_not_on_owned",
        estimates=[_est("cnc_3axis", 10, 40.0, material="304 Stainless")],
        make_now="wire_edm",
        per_route={"cnc_3axis": {"verdict": "makeable_not_on_owned", "failures": [fail]}},
    )
    r = _row(d)
    assert (r["bucket"], r["reason"]) == ("new_machine", "Haas VF-2: not qualified for 304 Stainless")
    assert r["capability"]["gate"] == "material" and r["capability"]["need"] == "304 Stainless"
    assert r["hours_each"] == 0.5


def test_cant_be_made_as_drawn_gives_the_engines_reason():
    d = _decision("not_makeable", estimates=[],
                  gap=[{"gate": "dfm", "human": "All walls 0.5 mm. No method makes them as drawn."}])
    r = _row(d)
    assert (r["bucket"], r["reason"]) == ("cant_make", "All walls 0.5 mm")
    assert r["hours_each"] is None and r["unit_cost_usd"] is None
    env = _decision("environment_excluded", estimates=[],
                    env_exclusions=[{"human": "Aluminum is not NACE MR0175 qualified for sour service."}])
    assert _row(env)["reason"] == "Aluminum is not NACE MR0175 qualified for sour service"


def test_invalid_geometry_is_a_result_not_a_failure():
    item = {**ITEM, "error_message": cr.GEOMETRY_INVALID_PREFIX + "Mesh is not watertight (12 open edges). Repair it."}
    r = _row(None, item=item, analysis={"ulid": "A1", "mesh_hash": "h" * 64})
    assert (r["bucket"], r["verdict"]) == ("cant_make", "geometry_invalid")
    assert r["reason"] == "Not a valid solid: Mesh is not watertight (12 open edges)"
    assert r["part_key"] == "h" * 64


def test_a_withheld_price_is_never_invented():
    d = _decision("makeable_in_house", estimates=[_est("cnc_3axis", 10, 55.0, ready=False, blockers=["Walls under 0.8 mm. Thicken them."])],
                  resource={"machine": "Haas VF-2", "process": "cnc_3axis"})
    r = _row(d)
    assert r["unit_cost_usd"] is None and r["total_cost_usd"] is None
    assert r["price_withheld"] == "Walls under 0.8 mm"
    assert r["hours_each"] == 0.5  # the machine time is still the engine's


def test_no_machines_declared_reads_not_sorted():
    d = _decision(None, estimates=[_est("cnc_3axis", 10, 30.0)])
    d["result_json"]["verification"]["inventory_declared"] = False
    r = _row(d)
    assert r["bucket"] == "not_sorted" and "add your machines" in r["reason"]


def test_failed_skipped_and_running_items():
    assert _row(None, item={**ITEM, "status": "processing"})["bucket"] == "checking"
    failed = _row(None, item={**ITEM, "status": "failed", "error_message": "Could not read the file. It may be corrupt."})
    assert (failed["bucket"], failed["reason"]) == ("not_checked", "The file couldn't be read as STEP, STL or IGES")
    assert failed["error"] == "Could not read the file. It may be corrupt."
    mesh = _row(None, item={**ITEM, "status": "failed", "error_message": "400: Could not tessellate this part: gmsh could not mesh the geometry [rung 2 exceeded 15s cap] (all 3 mesh strategies failed)."})
    assert mesh["reason"].startswith("The CAD kernel couldn't make a solid")
    slow = _row(None, item={**ITEM, "status": "failed", "error_message": "504: File parsing exceeded 60s timeout."})
    assert slow["reason"] == "Reading the file ran past the time limit; check it on its own"
    other = _row(None, item={**ITEM, "status": "failed", "error_message": "500: Something new. More detail."})
    assert other["reason"] == "Something new"
    assert _row(None, item={**ITEM, "status": "skipped", "error_message": None})["reason"] == "Skipped"


def test_totals_sum_real_figures_and_say_how_many_they_cover():
    rows = [
        {"bucket": "in_house", "quantity": 10, "hours_total": 2.5, "mass_kg_total": 1.0, "total_cost_usd": 300.0},
        {"bucket": "in_house", "quantity": 5, "hours_total": None, "mass_kg_total": None, "total_cost_usd": None},
        {"bucket": "cant_make", "quantity": 1},
    ]
    t = cr.bucket_totals(rows)
    assert t["in_house"] == {"parts": 2, "quantity": 15, "hours": 2.5, "hours_parts": 1, "mass_kg": 1.0,
                             "mass_parts": 1, "cost_usd": 300.0, "cost_parts": 1}
    assert t["cant_make"]["parts"] == 1 and t["cant_make"]["hours"] is None
    assert t["outside"]["parts"] == 0


def test_csv_neutralises_formulas_and_quotes_commas():
    board = {"rows": [{
        "filename": "=HYPERLINK(\"x\").stl", "part_number": "A,1", "bucket": "in_house", "reason": "On your Haas VF-2",
        "route": {"process": "cnc_3axis", "machine": "Haas VF-2", "owned": True},
        "material": {"name": "6061-T6 Aluminum", "declared": "6061"}, "quantity": 10, "hours_each": 0.25,
        "hours_total": 2.5, "mass_kg_total": 2.7, "unit_cost_usd": 30.0, "total_cost_usd": 300.0,
        "marginal": True, "status": "completed",
    }]}
    lines = list(cr.board_csv_rows(board))
    assert lines[0] == cr.CSV_HEADER
    row = lines[1]
    assert row.startswith("\"'=HYPERLINK(\"\"x\"\").stl\",\"A,1\",Make in-house,On your Haas VF-2,")
    assert ",yes,6061-T6 Aluminum,6061,10,0.25,2.5,," in row
    assert "your machine at marginal rate" in row
