"""Cost lines add up to the unit cost to the cent: screen, PDF and CSV (ce-01).

The cost engineer added the printed lines with a calculator. Her cases, with the
engine's own four-decimal lines from her CSV export: each line rounded on its own
misses the unit cost by a cent or two, so a Rounding line carries the difference.
"""

from __future__ import annotations

import csv
import io

import pytest

from src.costing.footing import cents, foot, footed_items, keys_in

# Her CSV export of pocket-block.step (steel, v0 rates), line items as the engine stored them.
POCKET_3AX = {
    1: (149.30, {"nre": 70.0, "labor": 17.5, "machine": 15.6934, "material": 0.5222,
                 "inspection": 18.55, "consumables": 0.7847, "amortized_fixed": 26.25}),
    100: (36.69, {"nre": 0.7, "labor": 17.5, "machine": 15.6934, "material": 0.5222,
                  "inspection": 1.225, "consumables": 0.7847, "amortized_fixed": 0.2625}),
    1000: (25.32, {"nre": 0.07, "labor": 12.332, "machine": 11.0589, "material": 0.5222,
                   "inspection": 0.7574, "consumables": 0.5529, "amortized_fixed": 0.0262}),
    10000: (17.93, {"nre": 0.007, "labor": 8.6902, "machine": 7.7931, "material": 0.5222,
                    "inspection": 0.5232, "consumables": 0.3897, "amortized_fixed": 0.0026}),
}
POCKET_5AX = {
    1: (214.74, {"nre": 105.0, "labor": 17.5, "machine": 26.9374, "material": 0.9574,
                 "inspection": 28.0, "consumables": 1.3469, "amortized_fixed": 35.0}),
    100: (50.15, {"nre": 1.05, "labor": 17.5, "machine": 26.9374, "material": 0.9574,
                  "inspection": 2.0125, "consumables": 1.3469, "amortized_fixed": 0.35}),
}
# Stepped shaft, 304 stainless, turning at 100, as she rebuilt it: setup 0.175,
# inspection 1.015 and tools 0.4865 each round up.
SHAFT_TURN_100 = (23.82, {"nre": 0.35, "labor": 10.5, "machine": 9.73, "material": 1.5665,
                          "inspection": 1.015, "consumables": 0.4865, "amortized_fixed": 0.175})


def _printed(items):
    return [cents(v) for v in items.values()]


@pytest.mark.parametrize("unit,items,printed_sum,rounding", [
    # 70.00 + 17.50 + 15.69 + 0.52 + 18.55 + 0.78 + 26.25 = 149.29 vs $149.30
    (*POCKET_3AX[1], 14929, +1),
    # 0.70 + 17.50 + 15.69 + 0.52 + 1.23 + 0.78 + 0.26 = 36.68 vs $36.69
    (*POCKET_3AX[100], 3668, +1),
    # 0.07 + 12.33 + 11.06 + 0.52 + 0.76 + 0.55 + 0.03 = 25.32: foots already
    (*POCKET_3AX[1000], 2532, 0),
    # 0.01 + 8.69 + 7.79 + 0.52 + 0.52 + 0.39 + 0.00 = 17.92 vs $17.93
    (*POCKET_3AX[10000], 1792, +1),
    # 5-axis at 1: 214.75 vs $214.74
    (*POCKET_5AX[1], 21475, -1),
    # 5-axis at 100: 1.05 + 17.50 + 26.94 + 0.96 + 2.01 + 1.35 + 0.35 = 50.16 vs $50.15
    (*POCKET_5AX[100], 5016, -1),
    # shaft: 0.35 + 10.50 + 9.73 + 1.57 + 1.02 + 0.49 + 0.18 = 23.84 vs $23.82
    (*SHAFT_TURN_100, 2384, -2),
])
def test_her_lines_foot_with_a_rounding_line(unit, items, printed_sum, rounding):
    assert sum(_printed(items)) == printed_sum              # what she added up
    f = foot(items, unit)
    assert f["rounding_cents"] == rounding
    assert sum(c for _k, c in f["lines"]) + f["rounding_cents"] == f["unit_cents"] == cents(unit)
    # each line is still its own formula's value to the cent
    assert dict(f["lines"]) == {k: cents(v) for k, v in items.items()}
    shown = footed_items(items, unit)
    assert round(sum(shown.values()), 2) == unit
    assert ("rounding" in shown) == (rounding != 0)


def test_half_up_like_the_screen():
    # The screen's toLocaleString reads 1.225 as 1.23 and 0.175 as 0.18; so does every export.
    assert [cents(1.225), cents(0.175), cents(1.015), cents(0.4865), cents(36.6878)] == [123, 18, 102, 49, 3669]
    assert cents(-0.175) == -18


def test_zero_lines_are_left_out_and_keys_put_rounding_last():
    f = foot({"amortized_fixed": 0.0, "material": 1.8725, "machine": 1.7027, "labor": 1.75, "tooling": 60.0}, 65.33)
    assert [k for k, _c in f["lines"]] == ["material", "machine", "labor", "tooling"]
    rows = [{"line_items": POCKET_3AX[100][1], "unit_cost_usd": 36.69},
            {"line_items": POCKET_3AX[1000][1], "unit_cost_usd": 25.32}]
    assert keys_in(rows)[-1] == "rounding"


def test_csv_line_items_foot_to_the_unit_cost():
    from src.services.cost_decision_service import build_estimates_csv

    result = {"estimates": [
        {"process": "cnc_3axis", "material": "Mild Steel", "quantity": q, "unit_cost_usd": unit,
         "fixed_cost_usd": 113.75, "variable_cost_usd": 35.55, "line_items": items, "confidence": {}}
        for q, (unit, items) in POCKET_3AX.items()]}
    rows = list(csv.DictReader(io.StringIO(build_estimates_csv(result))))
    for row in rows:
        parts = dict(p.split("=") for p in row["line_items"].split("; "))
        assert round(sum(float(v) for v in parts.values()), 2) == float(row["unit_cost_usd"]), row
    at100 = dict(p.split("=") for p in rows[1]["line_items"].split("; "))
    assert at100["inspection"] == "1.23" and at100["rounding"] == "0.01"


def test_pdf_line_table_foots():
    from src.services.cost_pdf_service import _footed, _format_money, _line_keys

    ests = [{"unit_cost_usd": unit, "line_items": items} for unit, items in
            (POCKET_3AX[100], POCKET_5AX[100], SHAFT_TURN_100)]
    keys = _line_keys(ests)
    assert keys[-1] == "rounding"
    for e in ests:
        row = _footed(e)
        printed = [_format_money(row[k]) for k in keys if k in row]
        total = sum(cents(float(p.strip("$").replace(",", ""))) for p in printed)
        assert total == cents(e["unit_cost_usd"])
        assert _format_money(e["unit_cost_usd"]) == f"${e['unit_cost_usd']:,.2f}"
    # the PDF and the screen read a half cent the same way
    assert _format_money(0.175) == "$0.18"


def test_a_gap_rounding_cannot_make_is_never_called_rounding():
    # Seven lines can be off by at most four cents together; $5 is not rounding.
    items = POCKET_3AX[100][1]
    f = foot(items, 41.69)
    assert not f["is_rounding"]
    shown = footed_items(items, 41.69)
    assert "rounding" not in shown and shown["not_in_lines"] == pytest.approx(5.01)
    assert foot(items, 36.69)["is_rounding"]
