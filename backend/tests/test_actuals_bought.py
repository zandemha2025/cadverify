"""Actuals: what we paid a supplier is not what it cost us to make (op-18).

A supplier's invoice is compared with ScaleCAD's buy price (the record's outside
side at the same quantity), never with the in-house estimate, and never
calibrates your machines. The import says which a file is, guessed from its
headers, and a row's own Kind cell wins.
"""
from __future__ import annotations

from src.services import accuracy_service as acc
from src.services.actuals_service import Mapping, Table, guess_source, kind_of


def _est(process, qty, cost, hours, *, owned=False):
    drivers = [{"name": "cycle_time", "value": hours, "error_band_pct": 20.0},
               {"name": "machine_cost", "value": cost * 0.4}]
    if owned:
        drivers.append({"name": "owned_in_house", "value": 1.0})
    return {"process": process, "quantity": qty, "material": "SS316L", "unit_cost_usd": cost,
            "confidence": {"low_usd": cost * 0.8, "high_usd": cost * 1.2}, "drivers": drivers}


# RFS-21039: made on your VF-2 at $26.17 at 500; 3-axis milling at a job shop $38.55.
RECORD = {"id": "R1", "filename": "RFS-21039.step", "result_json": {
    "estimates": [_est("cnc_3axis", 500, 26.17, 0.33, owned=True), _est("dmls", 500, 330.0, 2.0)],
    "decision": {"options": {"500": {
        "in_house": {"process": "cnc_3axis", "unit_cost_usd": 26.17, "low_usd": 22.0, "high_usd": 30.0},
        "outside": {"process": "cnc_3axis", "unit_cost_usd": 38.55, "low_usd": 31.0, "high_usd": 46.0,
                    "same_process": True}}}}}}


def _actual(source_type, cost, *, hours=None, qty=500, key="k1"):
    return {"id": key, "evidence_sha256": key, "part_number": "RFS-21039", "process": "cnc_3axis",
            "quantity": qty, "actual_unit_cost_usd": cost, "actual_machine_hours": hours,
            "source_type": source_type, "stand_in": False}


def test_an_invoice_is_graded_against_the_buy_price_never_the_in_house_estimate():
    row = acc.compare(_actual("invoice", 33.05, hours=0.5), RECORD)
    assert row["kind"] == "bought"
    assert row["cost"]["estimate"] == 38.55 and row["cost"]["basis"] == "buy"
    assert row["cost"]["estimate"] != 26.17
    assert row["compared_with"] == "ScaleCAD's outside price for 3-axis milling at a job shop, at 500"
    # A supplier's invoice says nothing about your machine time.
    assert row["hours"] is None and "Hours not compared" in row["note"]
    # A quantity the record didn't price isn't compared (never drawn between two priced quantities).
    other = acc.compare(_actual("invoice", 33.05, qty=250), RECORD)
    assert other["cost"] is None and "wasn't priced at 250" in other["note"]


def test_a_job_we_ran_ourselves_is_still_graded_against_the_estimate():
    row = acc.compare(_actual("actual", 30.0, hours=0.4), RECORD)
    assert row["kind"] == "made" and row["cost"]["estimate"] == 26.17
    assert row["hours"]["estimate"] == 0.33
    assert row["compared_with"] == "ScaleCAD's estimate for 3-axis milling, at 500"


def test_the_summary_says_which_population_and_calibration_ignores_invoices():
    rows = [acc.compare(_actual("invoice", 33.05 + i, key=f"b{i}"), RECORD) for i in range(10)]
    s = acc.summarize(rows)
    assert (s["parts"], s["actuals"], s["enough"]) == (0, 0, False)
    assert s["bought"]["actuals"] == 10 and s["bought"]["parts"] == 10 and s["bought"]["enough"]
    assert s["bought"]["population"].startswith("What you paid suppliers")
    assert s["population"].startswith("Your own job costs")
    prop = acc.proposal(rows)
    assert prop["parts"] == 0 and prop["processes"] == [] and not prop["enough"] and prop["bought_excluded"] == 10
    made = rows + [acc.compare(_actual("actual", 30.0 + i, hours=0.4, key=f"m{i}"), RECORD) for i in range(3)]
    assert acc.proposal(made)["parts"] == 3


def test_a_part_none_of_your_machines_makes_takes_its_cheapest_outside_estimate():
    rec = {"id": "R2", "filename": "x.step", "result_json": {"estimates": [_est("dmls", 50, 300.0, 2.0),
                                                                          _est("cnc_5axis", 50, 120.0, 1.0)]}}
    row = acc.compare({**_actual("invoice", 100.0, qty=50), "process": "cnc_5axis"}, rec)
    assert row["cost"]["estimate"] == 120.0
    assert row["compared_with"] == "ScaleCAD's outside price for 5-axis milling, at 50"


def test_the_import_reads_po_receipts_as_what_we_paid_a_supplier():
    headers = ["Item", "Vendor", "PO", "Receipt Date", "Qty Received", "Unit Cost"]
    assert guess_source(headers) == ("bought", "it has a Vendor column")
    m = Mapping.from_json(None, Table(headers=headers, rows=[], lines=[], kind="csv"))
    assert (m.source, m.default_kind) == ("bought", "invoice")
    assert m.public()["source_guess"] == "it has a Vendor column"
    # The person's choice wins over the guess; a row's Kind cell wins over both.
    m2 = Mapping.from_json({"columns": {}, "source": "made"}, Table(headers=headers, rows=[], lines=[], kind="csv"))
    assert m2.default_kind == "actual"
    assert kind_of("", "invoice") == ("invoice", False)
    assert kind_of("Work order", "invoice") == ("actual", False)
    assert kind_of("PO receipt") == ("invoice", False)
    assert kind_of("Supplier quote") == ("quote", False)


def test_her_po_receipts_import_as_supplier_invoices_and_a_kind_cell_still_wins():
    """op-18: Item, Vendor, PO, Receipt Date, Qty Received, Unit Cost; no process column."""
    from src.services import actuals_service as svc

    text = ("Item,Vendor,PO,Receipt Date,Qty Received,Unit Cost,Kind\n"
            "RFS-21039,Apex Machining,PO-4411,08/14/2026,500,33.05,\n"
            "RFS-21039,Apex Machining,PO-4412,09/02/2026,250,34.10,work order\n")
    table = svc.read_table("receipts.csv", text.encode())
    m = svc.Mapping.from_json(None, table)
    m.columns["quantity"] = table.headers.index("Qty Received")
    m.process_map[""] = "cnc_3axis"
    index = svc.PartIndex([svc.PartRef(key="h" * 64, file_name="RFS-21039.step", record_id="r1",
                                       part_numbers={"RFS-21039"})])
    rows = svc.evaluate_rows(table, m, index, [])
    assert [r.values["source_type"] for r in rows] == ["invoice", "actual"]
    assert svc.to_payload(rows[0])["source_type"] == "invoice"
