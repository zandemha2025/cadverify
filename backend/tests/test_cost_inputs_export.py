"""Exports a cost engineer can rebuild the price from (round 11, ce-14).

Priyanka exported record #Z7JG57 (pocket-block.step, out of date since rate card
v1) as "CSV of cost inputs", PDF and JSON. The cents matched the screen, but the
CSV held "only per-line dollar results in one packed text cell ('nre=0.7;
labor=17.5; machine=15.6934; ...')", with no hours, rates, kg, $/kg, record id,
date or rate-card version; the PDF of the out-of-date record said nothing about
it, its footer's "generated" time was the check time; every pocket-block record
exported as pocket-block-cost.csv.

Her lines at 100 off, v0: labor 0.5 h x $35 = 17.50, machine 0.2092 h x $75 =
15.69, programming 2 h x $35 / 100 = 0.70, setup 0.75 h x $35 / 100 = 0.26,
inspection 0.035 h x $35 = 1.23, material 0.5222, tools 0.78: $36.68 by the cent
against a $36.69 price, so a Rounding line of $0.01 makes the column add up.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.analysis.models import ProcessType as PT
from src.costing import cost_model
from src.costing.cost_model import cost_breakdown
from src.costing.drivers import GeoDrivers
from src.costing.rates import build_rate_card
from src.costing.routing import select_material
from src.services import cost_decision_service as svc
from src.services import cost_pdf_service

CYCLE_HR = 0.209245
CHECKED = datetime(2026, 10, 22, 15, 32, 26, tzinfo=timezone.utc)
EXPORTED = datetime(2026, 10, 22, 16, 20, 5, tzinfo=timezone.utc)
STALE = {"priced": 0, "current": 1, "out_of_date": True, "text": "Priced at rates v0; your rates are v1."}


def _block():
    return GeoDrivers(
        volume_cm3=37.9, surface_area_cm2=106.92, bbox_mm=(20.0, 40.0, 60.0),
        bbox_volume_cm3=48.0, hull_volume_cm3=48.0, nominal_wall_mm=7.09, face_count=179296,
        max_bbox_mm=60.0, is_valid=True, rotational=False, rot_axis_len_mm=60.0,
        rot_cross_dia_mm=44.7, billet_bbox_mm=(20.0, 40.0, 60.0), billet_basis="oriented candidate")


@pytest.fixture()
def record(monkeypatch):
    monkeypatch.setattr(cost_model, "_cnc_cycle",
                        lambda process, drivers, cls, rates: (CYCLE_HR, 0.1782, "her cycle"))
    rates = build_rate_card()
    mat = select_material(PT.CNC_3AXIS, "steel", rates)
    ests = []
    for q in (1, 100):
        e = cost_breakdown(PT.CNC_3AXIS, _block(), mat, "steel", q, rates, "US")
        ests.append({
            "process": e.process, "material": e.material, "quantity": e.quantity,
            "unit_cost_usd": round(e.unit_cost_usd, 2), "line_items": e.line_items,
            "material_mass": dict(e.material_mass or {}),
            "drivers": [{"name": d.name, "value": d.value, "unit": d.unit, "provenance": d.provenance.value,
                         "source": d.source, "error_band_pct": d.error_band_pct} for d in e.drivers],
        })
    rj = {"estimates": ests, "assumptions": [{"name": "labor_rate", "value": 35.0, "unit": "$/hr",
                                              "provenance": "DEFAULT", "source": "loaded shop-floor labor"}]}
    return SimpleNamespace(ulid="01M5J0000000000000000Z7JG57", filename="pocket-block.step", created_at=CHECKED,
                           result_json=rj)


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_holds_the_inputs_one_column_each_with_the_screen_line_names(record):
    gov = {"is_stale": True, "stale_reason": "rate_library_published:v1"}
    rows = _rows(svc.build_cost_inputs_csv(record, governance=gov, rates=STALE, exported_at=EXPORTED))
    at100 = {r["line"]: r for r in rows if r["quantity"] == "100"}
    assert set(at100) == {"Material", "Machine", "Labor", "Setup", "Programming", "Inspection",
                          "Tools and coolant", "Rounding"}
    # the record on every row
    r = at100["Labor"]
    assert r["record_id"] == "01M5J0000000000000000Z7JG57" and r["part"] == "pocket-block.step"
    assert r["checked_at"].startswith("2026-10-22T15:32:26") and r["exported_at"].startswith("2026-10-22T16:20:05")
    assert (r["rates_priced_at"], r["rates_in_effect"], r["out_of_date"]) == ("0", "1", "True")
    assert r["out_of_date_reason"] == "Priced at rates v0; your rates are v1."
    # her inputs, line by line
    assert (r["line_usd"], r["hours"], r["hours_for"], r["rate_usd_per_h"], r["source"]) == \
        ("17.50", "0.5", "a part", "35.0", "typical")
    m = at100["Machine"]
    assert (m["line_usd"], m["hours"], m["hours_for"], m["rate_usd_per_h"]) == ("15.69", "0.2092", "a part", "75.0")
    s = at100["Setup"]
    assert (s["line_usd"], s["hours"], s["hours_for"]) == ("0.26", "0.75", "the order")
    p = at100["Programming"]
    assert (p["line_usd"], p["hours"], p["hours_for"]) == ("0.70", "2.0", "the order")
    i = at100["Inspection"]
    assert (i["line_usd"], i["hours"], i["hours_for"]) == ("1.23", "0.035", "a part")
    mat = at100["Material"]
    assert float(mat["kg"]) > 0 and float(mat["usd_per_kg"]) == pytest.approx(1.2)
    # kg x $/kg x (1 + scrap): 0.41448 x 1.2 x 1.05 = 0.5222 -> $0.52
    assert mat["scrap"] == "0.05"
    assert round(float(mat["kg"]) * float(mat["usd_per_kg"]) * (1 + float(mat["scrap"])), 2) == float(mat["line_usd"]) == 0.52
    # the column adds up to the price, to the cent: 36.68 + 0.01 rounding = 36.69
    assert at100["Rounding"]["line_usd"] == "0.01"
    assert round(sum(float(x["line_usd"]) for x in at100.values()), 2) == float(r["unit_cost_usd"]) == 36.69
    # the engine's own arithmetic rides along
    assert "post-process 0.5 hr" in r["formula"]


def test_a_negative_rounding_line_is_a_number_so_the_column_still_adds_up():
    # Two lines of $0.006 show as $0.01 each against a $0.01 price: Rounding is
    # -$0.01. Written as text it was escaped against formulas ("'-0.01") and the
    # column no longer added up in a spreadsheet (MJF/FDM/SLA records, training guide).
    est = {"process": "fdm", "material": "PLA", "quantity": 100, "unit_cost_usd": 0.01,
           "line_items": {"labor": 0.006, "machine": 0.006}, "drivers": []}
    record = SimpleNamespace(ulid="01M5J0000000000000000ROUND1", filename="clip.stl", created_at=CHECKED,
                             result_json={"estimates": [est]})
    text = svc.build_cost_inputs_csv(record, governance={}, rates={}, exported_at=EXPORTED)
    rows = {r["line"]: r for r in _rows(text)}
    assert rows["Rounding"]["line_usd"] == "-0.01"
    assert (rows["Labor"]["line_usd"], rows["Machine"]["line_usd"]) == ("0.01", "0.01")
    assert round(sum(float(r["line_usd"]) for r in rows.values()), 2) == 0.01
    assert "'-" not in text


def test_pdf_of_an_out_of_date_record_says_so_and_names_its_rates(record):
    from src.services.rate_card_basis import basis

    gov = {"is_stale": True, "stale_reason": "rate_library_published:v1", "stale_at": "2026-10-22T15:58:15+00:00"}
    lines = cost_pdf_service.stale_lines(gov, STALE)
    assert lines == ["Priced at rates v0; your rates are v1. Re-cost before quoting."]
    # a record out of date for another reason says that instead
    assert cost_pdf_service.stale_lines({"is_stale": True, "stale_reason": "machine_inventory_changed",
                                         "stale_at": "2026-10-22T16:00:00"}, None) == \
        ["Your machines changed on 2026-10-22 16:00 UTC: check the part again before relying on it."]
    assert cost_pdf_service.stale_lines({}, {"out_of_date": False}) == []

    d = SimpleNamespace(**vars(record), label=None, file_type="step", engine_version="t", mesh_hash="abc",
                        approval_status="unreviewed", approved_by_user_id=None, approved_at=None,
                        approval_note=None, stale_at=datetime(2026, 10, 22, 15, 58, tzinfo=timezone.utc),
                        stale_reason="rate_library_published:v1", user_disposition=None, disposition_note=None,
                        disposition_basis=None, disposition_updated_at=None, disposition_updated_by_user_id=None)
    html = cost_pdf_service.render_cost_html(d, rates=STALE)
    assert "Out of date." in html and "Priced at rates v0; your rates are v1. Re-cost before quoting." in html
    assert "priced at typical rates (v0)" in html
    # the footer names the check time as the check time, and its rates
    assert "checked 2026-10-22 15:32 UTC at typical rates (v0)" in html
    assert "generated" not in html.split('class="footer"')[-1]
    # a current v1 record names its card
    html1 = cost_pdf_service.render_cost_html(d, rates=basis({"rate_card": {"version": 1}}, CHECKED, [],
                                                              enabled=True, now=CHECKED) | {"out_of_date": False, "priced": 1})
    assert "priced at your rates v1" in html1


def test_export_filenames_are_unique_per_record():
    a = cost_pdf_service.safe_cost_filename("pocket-block.step", "01M5J0000000000000000Z7JG57", "cost.csv")
    b = cost_pdf_service.safe_cost_filename("pocket-block.step", "01M5J4MJ00000000000000X2QW", "cost.csv")
    assert a == "pocket-block-Z7JG57-cost.csv" and b == "pocket-block-00X2QW-cost.csv" and a != b
    assert cost_pdf_service.safe_cost_filename("pocket-block.step", "01M5J0000000000000000Z7JG57") == \
        "pocket-block-Z7JG57-cost-report.pdf"
    assert cost_pdf_service.safe_cost_filename("pocket-block.step") == "pocket-block-cost-report.pdf"
