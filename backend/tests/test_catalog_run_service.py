"""Pure parts of the catalog run: parts lists, materials, quantities, board rows, CSV."""
from __future__ import annotations

import csv
import io

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
    # A nickel alloy is priced as itself now (oo-08), never in the run's plastic.
    assert tabbed[0]["file"] == "parts/a.step" and tabbed[0]["material_class"] == "nickel"
    assert tabbed[0]["material_grade"] == "inconel_718" and tabbed[0]["material_note"] is None


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
    dlp = _row(_decision("makeable_outsource_only", estimates=[_est("dlp", 10, 5.0)], make_now="dlp"))
    assert "DLP" in dlp["reason"] or "resin" in dlp["reason"].lower()
    assert cr._lower("DLP 3D printing") == "DLP 3D printing" and cr._lower("Filament printing") == "filament printing"
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


def test_a_size_an_older_record_wrote_unrounded_reads_rounded():
    # Round 7 item 8: records from before the engine rounded its sentences carry
    # "268.814272mm"; the board and the pilot report show it like the rest.
    fail = {"gate": "envelope", "axis": "minimum_width_mm", "need": 268.8142723042861, "have": 254.00000009071616,
            "human": "Part minimum width is at least 268.814272mm > smallest chamber span 254.000000mm. "
                     "This necessary bound is not a machine specification."}
    d = _decision(
        "makeable_not_on_owned",
        estimates=[_est("cnc_turning", 10, 40.0)],
        make_now="cnc_turning",
        per_route={"cnc_turning": {"verdict": "makeable_not_on_owned", "failures": [fail]}},
    )
    r = _row(d)
    assert r["capability"]["human"].startswith("Part minimum width is at least 268.8mm > smallest chamber span 254mm.")
    assert r["capability"]["all"] == [r["capability"]["human"]]
    assert r["reason"].endswith("Part minimum width is at least 268.8mm > smallest chamber span 254mm")
    assert cr._tidy_mm("needs 201 mm, has 200 mm; 0.6mm wall; 12.75 mm") == "needs 201 mm, has 200 mm; 0.6mm wall; 12.75 mm"


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
    capped = _row(None, item={**ITEM, "status": "failed", "error_message": "400: Could not tessellate this part: gmsh could not mesh the geometry [rung 2 exceeded 15s cap] (all 3 mesh strategies failed)."})
    assert capped["reason"] == cr.TIMED_OUT_WORDS
    mesh = _row(None, item={**ITEM, "status": "failed", "error_message": "400: Could not tessellate this part: gmsh could not mesh the geometry (all 3 mesh strategies failed)."})
    assert mesh["reason"].startswith("The CAD kernel couldn't make a solid")
    slow = _row(None, item={**ITEM, "status": "failed", "error_message": "504: File parsing exceeded 60s timeout."})
    assert slow["reason"] == cr.TIMED_OUT_WORDS
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
                             "mass_parts": 1, "used_kg": None, "used_parts": 0, "cost_usd": 300.0, "cost_parts": 1}
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


# ── resources first: the material the engine charges for, and each bucket's breakdown ──
MILL_SRC = ("bounding-box billet 6.00 cm³ (oriented candidate 10×20×30 mm; minimum not certified) × 1.10 stock "
            "allowance × Mild Steel density 7.85 g/cm³ = 0.0518 kg × $1.5/kg (material-DB unit price) × (1+0.05 scrap)")
FORGE_SRC = ("billet from bar = net 0.0471 kg (CAD volume 6.00 cm³ × Mild Steel density 7.85 g/cm³) × (1+0.25 "
             "flash/scale loss) = 0.0589 kg × $1.5/kg (material-DB unit price) × (1+0.05 scrap)")


def test_material_used_is_the_mass_the_engine_charges_for():
    assert cr.material_used_kg({"drivers": [{"name": "material_cost", "source": MILL_SRC}]}) == 0.0518
    # The net mass named first isn't the one charged.
    assert cr.material_used_kg({"drivers": [{"name": "material_cost", "source": FORGE_SRC}]}) == 0.0589
    # The board's SQL slice keeps only the clause; it reads the same.
    assert cr.material_used_kg({"drivers": [{"name": "material_cost", "source": "= 0.0518 kg × $"}]}) == 0.0518
    assert cr.material_used_kg({"drivers": [{"name": "material_cost", "source": None}]}) is None
    assert cr.material_used_kg({"drivers": []}) is None
    assert cr.material_used_kg(None) is None


def test_the_structured_material_mass_is_read_before_the_derivation_text():
    # Round 7 item 7: estimates carry material_mass; the text is read only for
    # older records. A tiny part keeps its grams instead of rounding to 0.
    est = {"material_mass": {"part_kg": 0.0000124, "used_kg": 0.0000412, "density_g_cm3": 1.24, "usd_per_kg": 25.0},
           "drivers": [{"name": "material_cost", "source": "filament ... = 0.0000 kg × $25/kg"}]}
    assert cr.material_used_kg(est) == 0.0000412
    est = _est("fdm", 10, 3.0, material="PLA")
    est["material_mass"] = {"part_kg": 0.0000124, "used_kg": 0.0000412, "density_g_cm3": 1.24, "usd_per_kg": 25.0}
    est["drivers"].append({"name": "material_cost", "value": 0.001, "unit": "$", "source": "= 0.0000 kg × $25/kg"})
    r = _row(_decision("makeable_outsource_only", estimates=[est], make_now="fdm"))
    assert r["material"]["used_kg_each"] == 0.0000412 and r["used_kg_total"] == pytest.approx(0.000412)
    assert r["material"]["mass_kg_each"] == 0.0000124 and r["mass_kg_total"] == pytest.approx(0.000124)
    # The board's SQL slice keeps the field.
    assert "material_mass" in cr._BOARD_ESTIMATE_KEYS


def test_a_row_carries_the_material_used_next_to_the_part_mass():
    est = _est("cnc_3axis", 10, 30.0, cycle=0.25, owned=True, material="Mild Steel")
    est["drivers"].append({"name": "material_cost", "value": 0.08, "unit": "$", "source": MILL_SRC})
    d = _decision("makeable_in_house", estimates=[est], resource={"machine": "Haas VF-2", "process": "cnc_3axis"})
    r = _row(d)
    assert r["material"]["used_kg_each"] == 0.0518 and r["used_kg_total"] == pytest.approx(0.518)
    assert r["material"]["mass_kg_each"] == pytest.approx(0.785)  # 100 cm³ × 7.85 g/cm³, the part itself
    line = list(cr.board_csv_rows({"rows": [r]}))[1]
    head = cr.CSV_HEADER.rstrip("\n").split(",")
    cells = next(csv.reader(io.StringIO(line)))
    assert cells[head.index("material_used_kg_each")] == "0.0518"
    assert cells[head.index("material_used_kg_total")] == "0.518"


def _brow(bucket, *, machine=None, process=None, owned=False, hours=None, material=None, used=None, part=None, cap=None):
    return {"bucket": bucket, "route": {"process": process, "machine": machine, "owned": owned} if process else None,
            "hours_total": hours, "material": {"name": material}, "used_kg_total": used, "mass_kg_total": part,
            "capability": cap, "quantity": 10}


def test_breakdown_sums_hours_by_machine_material_by_grade_and_what_is_missing():
    rows = [
        _brow("in_house", machine="Haas VF-2", process="cnc_3axis", owned=True, hours=2.5, material="6061-T6 Aluminum", used=1.2, part=0.9),
        _brow("in_house", machine="Haas VF-2", process="cnc_3axis", owned=True, hours=None, material="6061-T6 Aluminum", used=None, part=0.3),
        _brow("in_house", machine="HP Jet Fusion 5200", process="mjf", owned=True, hours=7.0, material="PA12 (Nylon 12)", used=0.4, part=0.4),
        _brow("outside", process="fdm", hours=5.0, material="PLA", used=0.1, part=0.2),
        _brow("outside", process="fdm", hours=1.0, material="PLA", used=0.05, part=0.1),
        _brow("new_machine", process="cnc_3axis", hours=3.0, material="Delrin (POM)",
              cap={"process": "cnc_3axis", "gate": "material", "need": "Delrin (POM)", "human": "not qualified for Delrin (POM)"}),
        _brow("new_machine", process="cnc_3axis", hours=None, material="Delrin (POM)",
              cap={"process": "cnc_3axis", "gate": "material", "need": "Delrin (POM)", "human": "not qualified for Delrin (POM)"}),
        _brow("new_machine", process="cnc_turning", material="6061-T6 Aluminum",
              cap={"process": "cnc_turning", "gate": "envelope", "need": [300, 300], "human": "too long for the work area"}),
        {"bucket": "cant_make", "route": None, "material": {"name": None}, "capability": None},
    ]
    b = cr.bucket_breakdown(rows)
    ih = b["in_house"]
    assert [(m["machine"], m["parts"], m["hours"], m["hours_parts"]) for m in ih["machines"]] == [
        ("HP Jet Fusion 5200", 1, 7.0, 1), ("Haas VF-2", 2, 2.5, 1)]
    assert [(g["material"], g["parts"], g["used_kg"], g["used_parts"], g["part_kg"]) for g in ih["materials"]] == [
        ("6061-T6 Aluminum", 2, 1.2, 1, 1.2), ("PA12 (Nylon 12)", 1, 0.4, 1, 0.4)]
    # Outside, hours sit with the process: no machine of yours is named.
    assert [(m["machine"], m["process"], m["owned"], m["hours"]) for m in b["outside"]["machines"]] == [(None, "fdm", False, 6.0)]
    miss = b["new_machine"]["missing"]
    assert [(g["process"], g["gate"], g["need"], g["parts"], g["hours"]) for g in miss] == [
        ("cnc_3axis", "material", "Delrin (POM)", 2, 3.0), ("cnc_turning", "envelope", None, 1, None)]
    assert b["cant_make"] == {"machines": [], "materials": [], "missing": []}
    assert b["checking"] == {"machines": [], "materials": [], "missing": []}


# ── part specs and the sign-off on the board ──────────────────────────────────
def test_a_row_carries_the_specs_the_run_priced_with():
    d = _decision("makeable_outsource_only", estimates=[_est("cnc_3axis", 10, 30.0)])
    d["result_json"]["specs"] = {"summary": ["Finish: Anodize, Type II", "Inspection: Standard inspection",
                                             "Supplier must hold: AS9100"],
                                 "certifications": [{"key": "as9100", "label": "AS9100", "shop_op": "as9100"}],
                                 "excluded_processes": ["fdm"]}
    r = _row(d)
    assert r["specs"] == {"summary": ["Finish: Anodize, Type II", "Inspection: Standard inspection",
                                      "Supplier must hold: AS9100"],
                          "supplier_must_hold": ["AS9100"], "excluded_processes": ["fdm"]}
    # Not yet priced: the parts list's declaration shows.
    r = _row(None, meta={"part_specs": {"heat_treatments": ["hip"], "certifications": ["itar"]}},
             item={**ITEM, "status": "pending"})
    assert r["specs"]["supplier_must_hold"] == ["ITAR registration"]
    assert r["specs"]["summary"][0] == "Heat treatment: HIP (hot isostatic pressing)"
    assert _row(d, meta={})["specs"] is not None and _row(_decision("makeable_outsource_only", estimates=[]))["specs"] is None


def test_csv_adds_specs_outcome_and_signoff_columns():
    row = {"filename": "a.stl", "bucket": "outside", "quantity": 10, "material": {},
           "specs": {"summary": ["Finish: Anodize, Type II", "Inspection: Standard inspection"],
                     "supplier_must_hold": ["AS9100", "ITAR registration"]},
           "outcome": "outside",
           "signoff": {"by": "Ada Admin", "at": "2026-10-22T10:00:00+00:00", "stale": True}}
    head = cr.CSV_HEADER.rstrip("\n").split(",")
    assert head[-6:] == ["specs", "supplier_must_hold", "outcome", "signed_off_by", "signed_off_at",
                         "signoff_out_of_date"]
    cells = next(csv.reader(io.StringIO(list(cr.board_csv_rows({"rows": [row]}))[1])))
    got = dict(zip(head, cells))
    assert got["specs"] == "Finish: Anodize, Type II; Inspection: Standard inspection"
    assert got["supplier_must_hold"] == "AS9100; ITAR registration"
    assert (got["outcome"], got["signed_off_by"], got["signoff_out_of_date"]) == ("Make outside", "Ada Admin", "yes")
    bare = dict(zip(head, next(csv.reader(io.StringIO(list(cr.board_csv_rows({"rows": [{**row, "specs": None,
                                                                                         "outcome": None, "signoff": None}]}))[1])))))
    assert (bare["specs"], bare["outcome"], bare["signed_off_by"], bare["signoff_out_of_date"]) == ("", "", "", "")


def test_a_row_carries_the_outcome_and_a_signoff_that_went_out_of_date():
    d = _decision("makeable_outsource_only", estimates=[_est("cnc_3axis", 10, 30.0)])
    gov = {"user_disposition": "outside", "approval_status": "approved", "approved_by_user_id": 7,
           "approved_at": "2026-10-22T10:00:00+00:00", "approval_note": None, "is_stale": True,
           "stale_reason": "rate_library_published:v3", "stale_at": "2026-10-22T11:00:00+00:00", "signers": {7: "Ada"}}
    r = cr.derive_part_row(item=ITEM, analysis=None, decision=d, meta=None, machines=MACHINES,
                           default_quantity=10, governance=gov)
    assert r["outcome"] == "outside" and r["record_out_of_date"] is True
    assert r["signoff"]["by"] == "Ada" and r["signoff"]["stale"] is True
    assert r["signoff"]["stale_reason"] == "rate_library_published:v3"
    plain = _row(d)
    assert (plain["outcome"], plain["signoff"], plain["record_out_of_date"]) == (None, None, False)


def test_the_pilot_report_writes_a_tiny_parts_mass_in_grams():
    from src.services.pilot_report_service import _kg

    assert [_kg(0.0000412), _kg(0.0041), _kg(0.27), _kg(312.4), _kg(None)] == ["<1 g", "4.1 g", "0.27 kg", "312 kg", "—"]


# ── round 9: the ops owner's make-or-buy answer ─────────────────────────────

def test_listed_materials_keep_their_grade_and_unpriced_ones_say_so():
    assert cr.read_material("4140") == {"class": "steel", "grade": "4140", "note": None}
    assert cr.read_material("Delrin")["grade"] == "pom"
    assert cr.read_material("Inconel 718") == {"class": "nickel", "grade": "inconel_718", "note": None}
    # Never priced as something else: no class, and a reason.
    assert cr.read_material("Nylon 6/6") == {"class": None, "grade": "pa66", "note": "Nylon 6/6 isn't a plastic ScaleCAD prices yet"}
    assert cr.read_material("CoCr")["class"] is None
    assert cr.read_material("Brass C360")["note"] == "Brass C360 isn't priced in ScaleCAD yet"


def test_a_current_price_column_is_read_per_part_in_dollars():
    rows = cr.parse_parts_list('file,qty,current price,per\na.step,10,"$1,250.00",100\nb.step,5,12.4 / 10,\nc.step,1,$3,\nd.step,1,,\n')
    assert [(r["current_price_usd"], r["current_price"]) for r in rows] == [
        (12.5, "$1,250.00 per 100"), (1.24, "$12.40 per 10"), (3.0, "$3.00 each"), (None, None)]
    with pytest.raises(ValueError, match="Row 2: current price 'abc' isn't a number"):
        cr.parse_parts_list("file,price\na.step,abc\n")
    with pytest.raises(ValueError, match="Row 2: 'per' 'dozen' must be each or a number"):
        cr.parse_parts_list("file,price,per\na.step,3,dozen\n")


def _opt(make, low, buy, *, pick="in_house", basis="in_house_cheapest", out_proc="sheet_metal", same=False):
    return {"in_house": {"process": "cnc_3axis", "machine": "Haas VF-2", "material": "6061-T6 Aluminum",
                         "unit_cost_usd": make, "low_usd": low, "high_usd": make * 1.3},
            "outside": {"process": out_proc, "unit_cost_usd": buy, "same_process": same}, "pick": pick, "basis": basis}


def _in_house_decision(opt, qty=10):
    d = _decision("makeable_in_house", estimates=[_est("cnc_3axis", qty, opt["in_house"]["unit_cost_usd"], owned=True),
                                                  _est("sheet_metal", qty, 5.13, material="5052 Aluminum (Sheet)")],
                  resource={"machine": "Haas VF-2", "process": "cnc_3axis"})
    d["result_json"]["decision"]["options"] = {str(qty): opt}
    return d


def test_make_in_house_means_cheaper_to_make_not_just_able_to():
    # oo-09: the engine's own comparison put buying first: the part is "Buy", and says what making costs.
    r = _row(_in_house_decision(_opt(38.71, 30.0, 5.13, pick="outside", basis="outside_cheaper")))
    assert r["bucket"] == "outside"
    assert r["could_make"] == {"process": "cnc_3axis", "machine": "Haas VF-2", "unit_cost_usd": 38.71, "times": 7.5}
    assert r["reason"] == "Could make in-house at $38.71 on your Haas VF-2 (7.5× the buy price)"
    assert (r["unit_cost_usd"], r["total_cost_usd"], r["marginal"]) == (5.13, 51.3, False)
    assert r["buy"]["source"] == "model" and r["buy"]["process"] == "sheet_metal"
    # Cheaper on your machine: in-house, with both sides on the row.
    ok = _row(_in_house_decision(_opt(20.0, 16.0, 30.0)))
    assert ok["bucket"] == "in_house" and ok["make"]["unit_cost_usd"] == 20.0 and ok["buy"]["unit_cost_usd"] == 30.0
    assert ok["saving"] is None  # no current price: no saving claimed against a model price


def test_a_current_price_decides_and_gives_the_saving_the_typed_one_wins():
    d = _in_house_decision(_opt(20.0, 16.0, 5.0, pick="outside", basis="outside_cheaper"))
    listed = _row(d, meta={"row": 2, "quantity": 10, "current_price_usd": 50.0, "current_price": "$50.00 each"})
    assert listed["bucket"] == "in_house" and listed["current_price"]["source"] == "parts_list"
    assert listed["saving"] == {"each": 30.0, "total": 300.0, "vs": "parts_list"}
    typed = cr.derive_part_row(item=ITEM, analysis=None, decision=d, machines=MACHINES, default_quantity=10,
                               meta={"row": 2, "quantity": 10, "current_price_usd": 50.0},
                               buy_price={"usd_each": 4.0, "per": 1, "price_usd": 4.0, "source": "you"})
    assert typed["current_price"] == {"usd_each": 4.0, "source": "you", "text": "$4.00 each"}
    assert typed["bucket"] == "outside" and typed["could_make"]["times"] == 5.0


def test_a_metal_route_priced_in_another_grade_says_so():
    d = _decision("makeable_in_house", estimates=[_est("cnc_turning", 10, 30.0, material="304 Stainless", owned=True)],
                  resource={"machine": "Haas ST-20", "process": "cnc_turning"})
    r = _row(d, meta={"row": 3, "quantity": 10, "material": "17-4 PH", "material_class": "stainless",
                      "material_grade": "17-4ph"})
    assert r["material"]["note"] == "17-4 PH isn't priced for turning in ScaleCAD; priced as 304 Stainless, confirm"


def test_an_unpriced_material_is_checked_not_priced():
    item = {**ITEM, "status": "completed"}
    r = _row(None, item=item, analysis={"ulid": "A1", "mesh_hash": "h" * 64},
             meta={"row": 4, "material": "Brass C360", "material_class": None,
                   "material_note": "Brass C360 isn't priced in ScaleCAD yet"})
    assert r["bucket"] == "not_sorted"
    assert r["reason"] == "Brass C360 isn't priced in ScaleCAD yet: its shape was checked, it isn't priced"


def test_names_counts_and_plain_words():
    assert cr.run_name("Ridgeline-bought-parts.zip", "list.csv") == "Ridgeline-bought-parts"
    assert cr.run_name("catalog.zip", "ridgeline-parts.csv") == "ridgeline-parts"
    assert cr.run_name("catalog.zip", None) is None
    assert cr.plain_body_name("Open CASCADE STEP translator 7.8 1.1") is None
    assert cr.plain_body_name("Part1") is None and cr.plain_body_name("Bracket arm") == "Bracket arm"
    assert cr.plain_error("504: Analysis exceeded ANALYSIS_TIMEOUT_SEC=60s. Reduce scope with ?processes=... or try x.") \
        == "504: Analysis exceeded the time limit"
    entry = {"kind": "assembly", "body_count": 3, "parent_mesh_hash": "p" * 64, "designs": [
        {"design": 0, "bodies": [1], "copies": 1, "name": "Open CASCADE STEP translator 7.8 1.1",
         "filename": "bracket-assembly - Open CASCADE STEP translator 7.8 1.1.stl", "status": "not_checked"}]}
    (row,) = cr.body_rows(item={"ulid": "I9", "filename": "bracket-assembly.step"}, entry=entry, parent_meta=None,
                          analyses={}, decisions={}, machines=MACHINES, default_quantity=10)
    assert row["name"] == "bracket-assembly.step, body 1 of 3" and row["body"]["name"] is None


def test_the_answer_counts_and_sums_savings_against_real_prices_only():
    rows = [
        {"bucket": "in_house", "saving": {"each": 3.0, "total": 600.0, "vs": "parts_list"}, "current_price": {"usd_each": 9.0},
         "total_cost_usd": 1200.0},
        {"bucket": "in_house", "saving": None, "current_price": None, "total_cost_usd": 100.0},
        {"bucket": "outside"}, {"bucket": "new_machine"}, {"bucket": "cant_make"}, {"bucket": "not_checked"},
    ]
    a = cr.make_or_buy_answer(rows)
    assert (a["make"], a["buy"], a["new_machine"], a["undecided"]) == (2, 1, 1, 2)
    assert (a["saving_usd"], a["saving_parts"], a["make_without_price"], a["with_price"]) == (600.0, 1, 1, 1)
    assert cr.make_or_buy_answer([{"bucket": "in_house"}])["saving_usd"] is None


def test_a_machine_shows_the_running_rate_you_set_on_every_row():
    # oo-11: $85/h set, 35% of it pays for the machine: $55.25/h on every row, not cost ÷ hours.
    vf2 = cr.machine_entry("Haas VF-2", "cnc_3axis", 3, 85.0, None)
    assert (vf2["count"], vf2["hourly_rate_usd"], vf2["running_rate_usd"], vf2["capital_frac_set"]) == (3, 85.0, 55.25, False)
    assert "running_rate_usd" not in cr.machine_entry("Bambu Lab X1C", "fdm")
    d = _decision("makeable_in_house", estimates=[_est("cnc_3axis", 10, 30.0, cycle=0.25, machine=12.19, owned=True)],
                  resource={"machine": "Haas VF-2", "process": "cnc_3axis"})
    r = cr.derive_part_row(item=ITEM, analysis=None, decision=d, meta=None, default_quantity=10,
                           machines=[vf2, {"name": "Bambu Lab X1C", "process": "fdm"}])
    assert r["machine_rate_usd"] == 55.25 and r["marginal"] is True
