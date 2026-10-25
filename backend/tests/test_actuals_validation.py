"""Your actuals: reading, matching, error math, thresholds, calibration fit and overlay (pure)."""
from __future__ import annotations

import io
import zipfile

import pytest

from src.services import accuracy_service as acc
from src.services import actuals_service as svc
from src.services import calibration_service as cal

H = {c: (c * 64)[:64] for c in "abcdef"}


def _parts():
    return svc.PartIndex([
        svc.PartRef(key=H["a"], file_name="bracket.step", record_id="r1", part_numbers={"PN-100"}),
        svc.PartRef(key=H["b"], file_name="bracket.stl", record_id="r2"),           # same stem as a
        svc.PartRef(key=H["c"], file_name="housing.step", record_id="r3", label="HSG-7", part_numbers={"HSG-7"}),
        svc.PartRef(key=H["d"], file_name="BRK-001.step", record_id="r4"),
        svc.PartRef(key=H["e"], file_name="plate.stl", record_id="r5", part_numbers={"PL-1"}),
        svc.PartRef(key=H["f"], file_name="plate-rev2.stl", record_id="r6", part_numbers={"PL-1"}),
    ])


# --------------------------------------------------------------- matching rules

def test_match_by_exact_file_name():
    m = svc.match_identity({"file_name": "Bracket.STEP"}, _parts())
    assert (m.status, m.key, m.basis) == ("matched", H["a"], "file_name")


def test_file_name_without_extension_that_fits_two_parts_is_asked():
    m = svc.match_identity({"file_name": "bracket"}, _parts())
    assert m.status == "ambiguous"
    assert set(m.candidates) == {H["a"], H["b"]}
    assert "2 checked parts" in m.reason


def test_match_by_declared_part_number_and_by_record_label():
    idx = _parts()
    assert svc.match_identity({"part_number": "pn-100"}, idx).key == H["a"]
    m = svc.match_identity({"part_number": "HSG-7"}, idx)
    assert (m.status, m.key, m.basis) == ("matched", H["c"], "part_number")


def test_part_number_that_is_the_file_name_matches_like_a_catalog_run():
    m = svc.match_identity({"part_number": "BRK-001"}, _parts())
    assert (m.status, m.key) == ("matched", H["d"])


def test_part_number_on_two_parts_is_asked_and_a_file_name_narrows_it():
    idx = _parts()
    m = svc.match_identity({"part_number": "PL-1"}, idx)
    assert m.status == "ambiguous" and set(m.candidates) == {H["e"], H["f"]}
    m = svc.match_identity({"part_number": "PL-1", "file_name": "plate-rev2.stl"}, idx)
    assert (m.status, m.key) == ("matched", H["f"])


def test_match_by_file_hash_and_conflict_with_another_identifier_is_asked():
    idx = _parts()
    m = svc.match_identity({"file_hash": H["c"].upper()}, idx)
    assert (m.status, m.key, m.basis) == ("matched", H["c"], "file_hash")
    m = svc.match_identity({"file_hash": H["c"], "part_number": "PN-100"}, idx)
    assert m.status == "ambiguous"
    assert set(m.candidates) == {H["a"], H["c"]}
    assert "different parts" in m.reason


def test_identifiers_that_disagree_are_asked_never_guessed():
    m = svc.match_identity({"part_number": "PN-100", "file_name": "housing.step"}, _parts())
    assert m.status == "ambiguous"
    assert set(m.candidates) == {H["a"], H["c"]}


def test_unmatched_says_why():
    idx = _parts()
    m = svc.match_identity({"part_number": "NOPE-1"}, idx)
    assert m.status == "unmatched" and "part number NOPE-1" in m.reason
    m = svc.match_identity({"file_hash": "0" * 64}, idx)
    assert m.status == "unmatched" and "file hash" in m.reason
    assert "No part number, file name or file hash" in svc.match_identity({}, idx).reason


def test_either_column_tries_part_number_then_file_name():
    idx = _parts()
    assert svc.match_identity({"part": "HSG-7"}, idx).key == H["c"]
    assert svc.match_identity({"part": "housing.step"}, idx).key == H["c"]


# --------------------------------------------------------------- reading files

def _rows(csv_text, mapping=None, choices=None, machines=None):
    t = svc.read_table("a.csv", csv_text.encode())
    m = svc.Mapping.from_json(mapping, t)
    return t, m, svc.evaluate_rows(t, m, _parts(), machines or [], choices)


def test_semicolon_csv_with_erp_headers_is_mapped_and_matched():
    text = "Part No;Qty;Machine hrs each;Cost/part;Work center;Completed\nPN-100;25;4,1;$118.50;Haas VF-2;3/14/2026\n"
    t, m, rows = _rows(text, machines=[{"name": "Haas VF-2", "process": "cnc_3axis"}])
    assert m.columns["part_number"] == 0 and m.columns["quantity"] == 1
    assert m.columns["machine_hours"] == 2 and m.columns["cost_each"] == 3
    assert m.columns["machine"] == 4 and m.columns["date"] == 5
    (r,) = rows
    assert r.status == "matched" and r.part.key == H["a"]
    v = r.values
    assert v["quantity"] == 25 and v["hours_each"] == 4.1 and v["cost_each"] == 118.5
    assert v["process"] == "cnc_3axis" and v["method_from"] == "machine"
    assert v["date"] == "2026-03-14"


def test_totals_minutes_and_currency():
    text = ("file,qty,total machine hours,total cost,process\n"
            "housing.step,10,25,1000,3 axis mill\n"
            "housing.step,4,,€90,cnc mill\n")
    t, m, rows = _rows(text)
    assert rows[0].values["hours_each"] == 2.5 and rows[0].values["cost_each"] == 100.0
    assert rows[0].values["process"] == "cnc_3axis"
    assert rows[1].status == "error" and "US dollars" in rows[1].errors[0]
    text = "file,qty,cycle time (min),process\nhousing.step,1,90,turning\n"
    t, m, rows = _rows(text)
    assert m.hours_unit == "min"
    assert rows[0].values["hours_each"] == 1.5 and rows[0].values["process"] == "cnc_turning"


def test_unknown_process_and_rows_without_one_are_asked():
    text = "file,qty,hours,process\nhousing.step,1,2,glorp\nhousing.step,2,2,\n"
    t, m, rows = _rows(text)
    assert rows[0].status == "error" and "pick the method" in rows[0].errors[0]
    assert rows[1].status == "error" and "No process" in rows[1].errors[0]
    vals = svc.process_values(t, m, [])
    assert {v["key"] for v in vals} == {"glorp", ""}
    t, m, rows = _rows(text, mapping={"columns": m.columns, "process_map": {"glorp": "sls", "": "fdm"}})
    assert rows[0].values["process"] == "sls" and rows[1].values["process"] == "fdm"


def test_choices_resolve_an_ambiguous_row_or_skip_it():
    text = "file,qty,hours,process\nbracket,1,2,fdm\nbracket,2,2,fdm\n"
    t, m, rows = _rows(text)
    assert [r.status for r in rows] == ["ambiguous", "ambiguous"]
    t, m, rows = _rows(text, mapping=m.public(), choices={"2": H["b"], "3": "skip"})
    assert rows[0].status == "matched" and rows[0].part.key == H["b"] and rows[0].match.basis == "chosen"
    assert rows[1].status == "unmatched" and rows[1].match.reason == "Skipped"


def test_a_choice_for_another_orgs_part_is_ignored():
    text = "file,qty,hours,process\nbracket,1,2,fdm\n"
    t, m, rows = _rows(text, choices={"2": "9" * 64})
    assert rows[0].status == "ambiguous"


def test_test_rows_are_labelled():
    text = "file,qty,hours,process,kind\nhousing.step,1,2,fdm,test\nhousing.step,2,2,fdm,actual\n"
    t, m, rows = _rows(text)
    assert rows[0].values["test"] is True and rows[0].values["source_type"] == "demo"
    assert rows[1].values["test"] is False
    t, m, rows = _rows(text, mapping={**m.public(), "test": True})
    assert all(r.values["test"] for r in rows)


def _xlsx(rows):
    """A minimal .xlsx: shared strings, a date-styled cell, numbers."""
    shared = []

    def s(v):
        if v not in shared:
            shared.append(v)
        return shared.index(v)

    sheet_rows = []
    for ri, row in enumerate(rows, start=1):
        cells = []
        for ci, v in enumerate(row):
            ref = f"{chr(65 + ci)}{ri}"
            if isinstance(v, str):
                cells.append(f'<c r="{ref}" t="s"><v>{s(v)}</v></c>')
            elif isinstance(v, tuple):  # (serial, 'date')
                cells.append(f'<c r="{ref}" s="1"><v>{v[0]}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
        sheet_rows.append(f'<row r="{ri}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rns}><sheets><sheet name="Jobs" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(f"<si><t>{v}</t></si>" for v in shared) + "</sst>")
        z.writestr("xl/styles.xml", f'<styleSheet {ns}><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    return buf.getvalue()


def test_xlsx_first_sheet_with_dates_and_numbers():
    data = _xlsx([["Part number", "Quantity", "Machine hours", "Date"], ["HSG-7", 12, 3.25, (46095, "date")]])
    t = svc.read_table("jobs.xlsx", data)
    assert t.kind == "xlsx" and t.headers == ["Part number", "Quantity", "Machine hours", "Date"]
    assert t.rows[0] == ["HSG-7", "12", "3.25", "2026-03-14"]


def test_unreadable_files_say_what_to_do():
    with pytest.raises(svc.TableError, match="xlsx or CSV"):
        svc.read_table("old.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest")
    with pytest.raises(svc.TableError, match="no rows"):
        svc.read_table("a.csv", b"file,qty\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<!DOCTYPE x [<!ENTITY a "b">]><workbook/>')
    with pytest.raises(svc.TableError, match="CSV"):
        svc.read_table("evil.xlsx", buf.getvalue())


def test_numbers_and_dates():
    assert svc.parse_number("1,234.50") == 1234.5
    assert svc.parse_number("12,5") == 12.5
    assert svc.parse_number("1.234,5") == 1234.5
    assert svc.parse_number("$40") == 40.0
    assert svc.parse_number("4.1 h") == 4.1
    assert str(svc.parse_date("14/03/2026")) == "2026-03-14"
    assert str(svc.parse_date("03/04/2026", "dmy")) == "2026-04-03"
    assert svc.date_order_of(["01/02/2026", "25/02/2026"]) == "dmy"


# --------------------------------------------------------------- error math

def _est(process, q, unit, hours, *, low=None, high=None, band=50.0, machine=None, calibration=None):
    e = {
        "process": process, "quantity": q, "unit_cost_usd": unit, "material": "Aluminum 6061",
        "est_error_band_pct": band,
        "drivers": [
            {"name": "cycle_time", "value": hours, "unit": "hr", "provenance": "DEFAULT", "source": "s", "error_band_pct": band},
            {"name": "machine_cost", "value": machine if machine is not None else hours * 75, "unit": "$", "provenance": "DEFAULT", "source": "s"},
        ],
        "confidence": {"low_usd": low if low is not None else unit * 0.5, "high_usd": high if high is not None else unit * 1.5,
                       "point_usd": unit, "half_width_pct": 50.0, "validated": False},
        "line_items": {"machine": machine if machine is not None else hours * 75},
    }
    if calibration:
        e["calibration"] = calibration
    return e


def _record(*ests, key="k"):
    return {"id": "rec-" + key, "filename": f"{key}.step", "label": None, "result_json": {"estimates": list(ests)}}


def _actual(key, process="cnc_3axis", q=100, hours=None, cost=None, test=False):
    return {"id": f"gt-{key}-{q}", "evidence_sha256": key, "part_id": f"{key}.step", "process": process, "quantity": q,
            "actual_machine_hours": hours, "actual_unit_cost_usd": cost, "stand_in": test}


def test_error_is_estimate_over_actual_with_range_coverage():
    rec = _record(_est("cnc_3axis", 100, 50.0, 4.4))
    c = acc.compare(_actual("k", hours=4.1, cost=40.0), rec)
    assert c["hours"]["error_pct"] == pytest.approx(7.32, abs=0.01)    # 4.4 vs 4.1: +7%
    assert c["hours"]["inside"] is True                                  # 2.2 .. 6.6
    assert c["cost"]["error_pct"] == pytest.approx(25.0)
    assert c["cost"]["inside"] is True and c["cost"]["basis"] == "exact"
    c = acc.compare(_actual("k", hours=10.0, cost=200.0), rec)
    assert c["hours"]["inside"] is False and c["cost"]["inside"] is False


def test_cost_at_an_unpriced_quantity_is_never_a_line_between_two_prices():
    """ce-15: without the record's quantity model, an unpriced quantity isn't compared
    (it used to be graded against a log-log line ScaleCAD never computed)."""
    rec = _record(_est("cnc_3axis", 10, 100.0, 2.0), _est("cnc_3axis", 1000, 10.0, 2.0))
    c = acc.compare(_actual("k", q=100, cost=31.62), rec)
    assert c["cost"] is None and "priced 10, 1,000; this order was 100" in c["note"]
    c = acc.compare(_actual("k", q=5000, cost=9.0, hours=2.0), rec)
    assert c["cost"] is None and "priced 10, 1,000" in c["note"]
    assert c["hours"] is not None                                        # hours per part still compared


def test_method_not_priced_and_part_gone():
    rec = _record(_est("fdm", 100, 5.0, 1.0))
    assert acc.compare(_actual("k", hours=1.0), rec)["note"] == "ScaleCAD didn't price this method for this part"
    assert "no longer in ScaleCAD" in acc.compare(_actual("k", hours=1.0), None)["note"]


def test_comparison_uses_the_estimate_from_before_calibration():
    before = {"unit_cost_usd": 50.0, "cycle_time_hr": 4.4, "machine_cost_usd": 330.0, "low_usd": 25.0, "high_usd": 75.0}
    rec = _record(_est("cnc_3axis", 100, 44.0, 3.9, calibration={"before": before}))
    c = acc.compare(_actual("k", hours=4.1, cost=40.0), rec)
    assert c["hours"]["estimate"] == 4.4 and c["cost"]["estimate"] == 50.0
    assert c["calibrated_record"] is True


def _many(n, hours_err=0.1, process="cnc_3axis", start=0):
    rows = []
    for i in range(start, start + n):
        key = f"p{i}"
        est = 4.0
        actual = est / (1 + hours_err)
        rows.append(acc.compare(_actual(key, process=process, hours=actual, cost=40.0),
                                _record(_est(process, 100, 44.0, est), key=key)))
    return rows


def test_too_few_parts_is_said_and_eight_is_a_fair_picture():
    s = acc.summarize(_many(3))
    assert s["parts"] == 3 and s["enough"] is False and s["min_parts"] == 8
    assert s["hours"]["median_abs_pct"] == pytest.approx(10.0)
    s = acc.summarize(_many(8))
    assert s["enough"] is True and s["hours"]["inside"] == 8
    per = {p["process"]: p for p in s["per_process"]}
    assert per["cnc_3axis"]["hours"]["enough"] is True


def test_per_method_needs_three_and_test_rows_never_count():
    rows = _many(8) + _many(2, process="fdm", start=20)
    rows += [acc.compare(_actual("t1", hours=100.0, test=True), _record(_est("cnc_3axis", 100, 44.0, 4.0), key="t1"))]
    s = acc.summarize(rows)
    per = {p["process"]: p for p in s["per_process"]}
    assert per["fdm"]["hours"]["enough"] is False
    assert s["test"] == 1 and s["hours"]["worst_pct"] == pytest.approx(10.0)


def test_worst_is_the_largest_error_by_size_with_its_sign():
    rows = _many(2) + [acc.compare(_actual("x", hours=8.0), _record(_est("cnc_3axis", 100, 44.0, 4.0), key="x"))]
    s = acc.summarize(rows)
    assert s["hours"]["worst_pct"] == pytest.approx(-50.0)
    assert s["hours"]["worst"]["part_key"] == "x"


# --------------------------------------------------------------- calibration fit

def test_proposal_offers_a_factor_that_helps_held_out():
    rows = _many(9, hours_err=0.12)                     # ScaleCAD 12% high on every part
    p = {x["process"]: x for x in acc.proposal(rows)["processes"]}["cnc_3axis"]
    h = p["hours"]
    assert h["offer"] is True and h["factor"] == pytest.approx(1 / 1.12, abs=1e-3)
    assert h["before_pct"] == pytest.approx(12.0) and h["after_pct"] == pytest.approx(0.0, abs=0.1)


def test_proposal_declines_with_the_reason():
    assert {x["process"]: x for x in acc.proposal(_many(9, hours_err=0.01))["processes"]}["cnc_3axis"]["hours"]["why"] == "no_change"
    assert {x["process"]: x for x in acc.proposal(_many(9, hours_err=9.0))["processes"]}["cnc_3axis"]["hours"]["why"] == "out_of_range"
    few = acc.proposal(_many(4, hours_err=0.2))
    assert few["enough"] is False
    assert few["processes"][0]["hours"]["why"] == "org_few"
    two = acc.proposal(_many(8) + _many(2, process="fdm", start=30))
    assert {x["process"]: x for x in two["processes"]}["fdm"]["hours"]["why"] == "few"


def test_noisy_actuals_that_a_factor_cant_fix_are_not_offered():
    rows = []
    for i, ratio in enumerate([0.5, 2.0, 0.5, 2.0, 0.5, 2.0, 0.5, 2.0, 1.0]):
        key = f"n{i}"
        rows.append(acc.compare(_actual(key, hours=4.0 * ratio), _record(_est("cnc_3axis", 100, 44.0, 4.0), key=key)))
    h = acc.proposal(rows)["processes"][0]["hours"]
    assert h["offer"] is False and h["why"] in ("no_change", "no_better")


# --------------------------------------------------------------- overlay

def test_overlay_scales_hours_machine_line_and_cost_and_keeps_the_engine_numbers():
    result = {"estimates": [_est("cnc_3axis", 100, 100.0, 2.0, machine=150.0), _est("fdm", 100, 5.0, 1.0)],
              "decision": {"recommendation": {"100": {"process": "cnc_3axis", "unit_cost_usd": 100.0}},
                           "options": {"100": {"in_house": {"process": "cnc_3axis", "unit_cost_usd": 100.0, "low_usd": 50.0, "high_usd": 150.0},
                                               "outside": {"process": "fdm", "unit_cost_usd": 5.0}}}}}
    out = cal.overlay(result, {"cnc_3axis": {"hours": 0.8, "cost": 1.1, "hours_parts": 9, "cost_parts": 9}},
                      calibration_id="C1", applied_at="2026-10-22T00:00:00+00:00")
    assert out is not result and result["estimates"][0]["unit_cost_usd"] == 100.0   # input untouched
    e = out["estimates"][0]
    drivers = {d["name"]: d for d in e["drivers"]}
    assert drivers["cycle_time"]["value"] == pytest.approx(1.6) and drivers["cycle_time"]["provenance"] == "SHOP"
    assert drivers["machine_cost"]["value"] == pytest.approx(120.0)
    # 100 - 30 (machine) = 70, then × 1.1 = 77; the actuals line carries the +7.
    assert e["unit_cost_usd"] == pytest.approx(77.0)
    assert drivers[cal.CAL_DRIVER]["value"] == pytest.approx(7.0)
    assert e["confidence"]["low_usd"] == pytest.approx(38.5) and e["confidence"]["high_usd"] == pytest.approx(115.5)
    assert e["calibration"]["before"]["unit_cost_usd"] == 100.0
    assert e["calibration"]["before"]["cycle_time_hr"] == 2.0
    assert out["estimates"][1] == result["estimates"][1]                              # other methods unchanged
    assert out["decision"]["recommendation"]["100"]["unit_cost_usd"] == pytest.approx(77.0)
    assert out["decision"]["options"]["100"]["in_house"]["unit_cost_usd"] == pytest.approx(77.0)
    assert out["decision"]["options"]["100"]["outside"]["unit_cost_usd"] == 5.0
    assert out["calibration"]["processes"] == ["cnc_3axis"]
    # The comparison reads the engine's numbers back off the calibrated record.
    c = acc.compare(_actual("k", hours=2.0, cost=100.0), {"id": "r", "filename": "k.step", "result_json": out})
    assert c["hours"]["error_pct"] == 0.0 and c["cost"]["error_pct"] == 0.0


def test_overlay_without_factors_returns_the_same_object():
    result = {"estimates": [_est("fdm", 100, 5.0, 1.0)]}
    assert cal.overlay(result, {}, calibration_id="C", applied_at=None) is result
    assert cal.overlay(result, {"cnc_3axis": {"hours": 0.9}}, calibration_id="C", applied_at=None)["estimates"] == result["estimates"]


@pytest.mark.asyncio
async def test_served_hook_is_a_no_op_without_a_real_session():
    from unittest.mock import AsyncMock

    result = {"estimates": [_est("fdm", 100, 5.0, 1.0)]}
    assert await cal.apply_org_calibration(None, "org", result) is result
    assert await cal.apply_org_calibration(AsyncMock(), "org", result) is result
