"""Checked against your real numbers, the way a cost engineer checks it (round 11, ce-11, ce-12, ce-15).

Priyanka Shah published rate card v1 (labor $35 -> $58/h), logged three jobs and
read "Checked against your real numbers":

* pocket-block 3-axis, 100 off, $52.40 (invoice): at v1 the model gives $49.63
  (her hand number) -> 49.63 / 52.40 - 1 = -5.3%;
* pocket-block 3-axis, 25 off, $61.20 (quote): her record was priced at 1, 100,
  1,000, 2,000, 5,000 and 10,000, not 25. The table graded it against $79.38, a
  straight line between $236.24 and $49.63 ScaleCAD never computed (+30%, "the
  worst error"). The model at 25, v1, by her hand:
      material 0.52 + machine 15.69 + tools 0.78 + labor 0.5 h x 58 = 29.00
      + in-process inspection 0.03 h x 58 = 1.74
      + (setup 0.75 + programming 2 + first article 0.5 = 3.25 h) x 58 / 25 = 7.54
      = $55.28 -> 55.28 / 61.20 - 1 = -9.7%;
* stepped-shaft turning, 100 off, $31.75: still on its v0 record ($23.82 at $35/h).
  One table, two rate cards, one median.

And the minutes: "14 min vs 13 min -13%" from 14.4 vs 12.55 min, where a calculator
on the shown minutes gives -7%.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from src.analysis.models import ProcessType as PT
from src.costing import cost_model
from src.costing.cost_model import cost_breakdown
from src.costing.drivers import GeoDrivers
from src.costing.rates import RATE_CARD_V0, build_rate_card
from src.costing.routing import select_material
from src.services import accuracy_service as acc
from src.services import rate_card_basis

CYCLE_HR = 0.209245


def _pocket_block():
    return GeoDrivers(
        volume_cm3=37.9, surface_area_cm2=106.92, bbox_mm=(20.0, 40.0, 60.0),
        bbox_volume_cm3=48.0, hull_volume_cm3=48.0, nominal_wall_mm=7.09, face_count=179296,
        max_bbox_mm=60.0, is_valid=True, rotational=False, rot_axis_len_mm=60.0,
        rot_cross_dia_mm=44.7, billet_bbox_mm=(20.0, 40.0, 60.0), billet_basis="oriented candidate")


def _as_dict(e):
    """The record's estimate as stored (estimate._serialize's fields used here)."""
    return {
        "process": e.process, "material": e.material, "quantity": e.quantity,
        "unit_cost_usd": round(e.unit_cost_usd, 2), "est_error_band_pct": e.est_error_band_pct,
        "line_items": e.line_items,
        "drivers": [{"name": d.name, "value": d.value, "unit": d.unit, "provenance": d.provenance.value,
                     "source": d.source, "error_band_pct": d.error_band_pct} for d in e.drivers],
        "confidence": {"low_usd": e.unit_cost_usd * 0.5, "high_usd": e.unit_cost_usd * 1.5},
        "qty_model": e.qty_model,
    }


@pytest.fixture()
def v1_record(monkeypatch):
    monkeypatch.setattr(cost_model, "_cnc_cycle",
                        lambda process, drivers, cls, rates: (CYCLE_HR, 0.1782, "her cycle"))
    card = copy.deepcopy(RATE_CARD_V0)
    card["global"]["labor_rate"] = 58.0
    rates = build_rate_card(base_rate_table=card)
    mat = select_material(PT.CNC_3AXIS, "steel", rates)

    def at(q):
        return cost_breakdown(PT.CNC_3AXIS, _pocket_block(), mat, "steel", q, rates, "US")
    ests = [_as_dict(at(q)) for q in (1, 100, 1000, 2000, 5000, 10000)]
    return {"id": "rec-v1", "filename": "pocket-block.step", "label": None,
            "result_json": {"estimates": ests, "rate_card": {"version": 1}}}, at


def _actual(q, cost=None, hours=None, **extra):
    return {"id": f"gt-{q}", "evidence_sha256": "pocket", "part_id": "pocket-block.step",
            "process": "cnc_3axis", "quantity": q, "actual_unit_cost_usd": cost,
            "actual_machine_hours": hours, "stand_in": False, **extra}


V1_CURRENT = {"priced": 1, "current": 1, "out_of_date": False, "text": "Priced at your rates v1."}


def test_25_off_is_graded_against_the_model_at_25_not_a_line_between_1_and_100(v1_record):
    rec, at = v1_record
    c = acc.compare(_actual(25, cost=61.20), rec, V1_CURRENT)
    cost = c["cost"]
    assert cost["basis"] == "model"
    # her hand number: 0.52 + 15.69 + 0.78 + 29.00 + 1.74 + 3.25 h x 58 / 25 = $55.28
    hand = 0.5222 + CYCLE_HR * 75 + 0.05 * CYCLE_HR * 75 + 0.5 * 58 + 0.03 * 58 + 3.25 * 58 / 25
    assert round(hand, 2) == 55.28
    assert round(cost["estimate"], 2) == 55.28
    # and the engine priced at 25 directly agrees, to the cent
    assert round(cost["estimate"], 2) == round(at(25).unit_cost_usd, 2)
    assert cost["error_pct"] == pytest.approx((55.28 / 61.20 - 1) * 100, abs=0.02)   # -9.7%, was +30%
    assert cost["shown"]["formula"] == "$55.28 ÷ $61.20 − 1 = −9.7%"
    # the row says where the number comes from: once over the quantity plus each part
    assert cost["basis_note"].startswith("ScaleCAD's model at 25: $188.50 once ÷ 25 + $47.74 a part = $55.28")
    assert "$79.38" not in str(c)


def test_100_off_at_v1_is_her_minus_5_percent(v1_record):
    rec, _ = v1_record
    c = acc.compare(_actual(100, cost=52.40), rec, V1_CURRENT)
    assert c["cost"]["basis"] == "exact" and c["cost"]["estimate"] == 49.63
    assert c["cost"]["shown"]["formula"] == "$49.63 ÷ $52.40 − 1 = −5.3%"


def test_a_v0_record_is_not_graded_on_cost_after_v1_is_published(v1_record):
    """ce-11: the shaft's $23.82 was priced at $35/h; at the published $58/h it's $31.73.
    The row says so and stays out of the cost median; v0 and v1 never mix silently."""
    rec, _ = v1_record
    shaft = {"id": "rec-shaft", "filename": "stepped-shaft.step", "label": None,
             "result_json": {"estimates": [{
                 "process": "cnc_turning", "material": "SS 304", "quantity": 100, "unit_cost_usd": 23.82,
                 "drivers": [{"name": "cycle_time", "value": 0.1, "unit": "hr", "provenance": "DEFAULT",
                              "source": "s", "error_band_pct": 30}],
                 "confidence": {"low_usd": 11.91, "high_usd": 35.73}}]}}
    stale = rate_card_basis.basis({}, datetime(2026, 10, 22, 15, 50, tzinfo=timezone.utc),
                                  [type("R", (), {"version": 1, "status": "published",
                                                  "effective_from": datetime(2026, 10, 22, 15, 59, tzinfo=timezone.utc),
                                                  "effective_to": None})()],
                                  enabled=True, now=datetime(2026, 10, 22, 16, 13, tzinfo=timezone.utc))
    row_shaft = acc.compare({**_actual(100, cost=31.75), "process": "cnc_turning", "evidence_sha256": "shaft"},
                            shaft, stale)
    assert row_shaft["cost"] is None and row_shaft["rates_excluded"] is True
    assert row_shaft["note"] == ("Cost not compared: Priced at rates v0; your rates are v1. "
                                 "Re-check the part to compare at v1")
    row_100 = acc.compare(_actual(100, cost=52.40), rec, V1_CURRENT)
    row_25 = acc.compare(_actual(25, cost=61.20), rec, V1_CURRENT)
    s = acc.summarize([row_100, row_25, row_shaft])
    assert s["cost"]["n"] == 2 and s["rates_excluded"] == 1 and s["rates_priced"] == [1]
    # median |error| of -5.3% and -9.7%; worst is the 25-off at -9.7%, not +30%
    assert s["cost"]["median_abs_pct"] == pytest.approx(7.5, abs=0.1)
    assert s["cost"]["worst_pct"] == pytest.approx(-9.7, abs=0.05)


def test_minutes_and_percent_reproduce_with_a_calculator(v1_record):
    """ce-12: 14.4 vs 12.55 min used to read "14 min vs 13 min -13%"."""
    rec, _ = v1_record
    c = acc.compare(_actual(100, hours=14.4 / 60), rec, V1_CURRENT)
    sh = c["hours"]["shown"]
    assert (sh["estimate"], sh["actual"]) == ("12.55 min", "14.40 min")
    assert sh["formula"] == "12.55 min ÷ 14.40 min − 1 = −12.8%"
    assert round((12.55 / 14.40 - 1) * 100, 1) == -12.8
    c = acc.compare(_actual(100, hours=15 / 60), rec, V1_CURRENT)
    assert c["hours"]["shown"]["formula"] == "12.55 min ÷ 15.00 min − 1 = −16.3%"


def test_setup_labor_and_inspection_hours_are_compared_line_by_line(v1_record):
    """ce-11: "the setup, labor and inspection hours I entered are neither shown nor compared"."""
    rec, _ = v1_record
    c = acc.compare(_actual(100, cost=52.40, actual_setup_hours=1.0, actual_labor_hours=0.4,
                            actual_inspection_hours=0.05), rec, V1_CURRENT)
    lines = {x["line"]: x for x in c["hour_lines"]}
    # the record states setup 0.75 h for the order, post-process 0.5 h a part, inspection
    # 0.5 h / 100 + 0.03 h = 0.035 h a part
    assert lines["setup"]["estimate"] == 0.75
    assert lines["setup"]["shown"]["formula"] == "45.00 min ÷ 60.00 min − 1 = −25.0%"
    assert lines["labor"]["estimate"] == 0.5
    assert lines["labor"]["shown"]["formula"] == "30.00 min ÷ 24.00 min − 1 = +25.0%"
    assert lines["inspection"]["estimate"] == pytest.approx(0.035)
    assert lines["inspection"]["shown"]["formula"] == "2.10 min ÷ 3.00 min − 1 = −30.0%"
    # an actual without them carries none
    assert acc.compare(_actual(100, cost=52.40), rec, V1_CURRENT)["hour_lines"] == []


def test_stated_hours_reads_learning_and_per_plate_setups():
    est = {"drivers": [
        {"name": "labor_cost", "source": "post-process 0.5 hr × $35/hr × 0.813 learning (the average part of 1,000, from the first lot of 100) × region-labor ×1"},
        {"name": "setup_cost", "source": "setup 0.5hr × $35/hr per plate × 300/120 parts a plate = 3 plates (at least one) ÷ 300 × region-labor ×1"},
        {"name": "nre_cost", "source": "CAM programming/NRE 2hr × $35/hr × region-labor ×1 ÷ 100 order (one-time)"},
    ]}
    h = acc.stated_hours(est)
    assert h["labor_part"] == pytest.approx(0.5 * 0.813)
    assert h["setup_order"] == pytest.approx(1.5)
    assert h["programming_order"] == 2.0
    assert "inspection_part" not in h


def test_unpriced_quantity_without_a_model_says_what_to_do():
    rec = {"id": "r", "filename": "f", "label": None, "result_json": {"estimates": [
        {"process": "cnc_3axis", "quantity": q, "unit_cost_usd": u, "drivers": [],
         "confidence": {"low_usd": u / 2, "high_usd": u * 1.5}} for q, u in ((1, 236.24), (100, 49.63))]}}
    c = acc.compare(_actual(25, cost=61.20), rec, V1_CURRENT)
    assert c["cost"] is None
    assert c["note"] == "Cost not compared: ScaleCAD priced 1, 100; this order was 25. Price 25 on the part to compare it"


def test_a_part_no_longer_in_scalecad_carries_no_card_and_no_lines():
    c = acc.compare(_actual(25, cost=1.0), None)
    assert c["rates"] is None and c["hour_lines"] == [] and "no longer in ScaleCAD" in c["note"]
