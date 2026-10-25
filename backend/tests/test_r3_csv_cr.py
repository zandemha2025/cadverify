"""Security review R3, F4: a CSV cell holding a carriage return stays one cell.

``_csv_escape`` left a bare CR unquoted, so a cell such as a parts-list
description or a ZIP entry name "bracket\\r=cmd|' /C calc'!A0" became a second
CSV row whose first cell was a live formula (GET /api/v1/batch/{id}/catalog.csv
via catalog_run_service.board_csv_rows, and GET /api/v1/batch/{id}/results.csv).
Every CSV export now uses one helper (src.services.csv_safe): quoted as the csv
module quotes, and the formula guard at the start of every line in a cell.
"""
from __future__ import annotations

import csv
import io

import pytest

from src.services.batch_service import _csv_escape
from src.services.cost_decision_service import spreadsheet_safe_cell

_FORMULA = ("=", "+", "-", "@")
_HOSTILE = "bracket\r=cmd|' /C calc'!A0"


def _rows(line: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(line, newline="")))


def test_cr_in_a_cell_never_starts_a_formula_row():
    line = "part.stl," + _csv_escape(_HOSTILE) + ",ok\n"
    rows = _rows(line)
    assert len(rows) == 1, rows  # was: [['part.stl', 'bracket'], ["=cmd|' /C calc'!A0", 'ok']]
    assert not any(cell.lstrip().startswith(_FORMULA) for row in rows for cell in row)


@pytest.mark.parametrize("cell", [_HOSTILE, "a\n=1+1", "a\r\n@SUM(A1)", "a\r\n  -2+3", "a\n\t+1", "a\n\n=x"])
def test_a_reader_that_splits_on_any_line_break_meets_no_formula(cell):
    from src.services import csv_safe

    # A naive importer that splits on every CR/LF, quotes or not.
    for line in csv_safe.safe_cell(cell).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        assert not line.lstrip(" \t").startswith(_FORMULA), line


def test_the_guard_at_the_start_of_a_cell_is_unchanged():
    assert spreadsheet_safe_cell("=1+1") == "'=1+1"
    assert spreadsheet_safe_cell("  @x") == "'  @x"
    assert spreadsheet_safe_cell("\tplain") == "'\tplain"
    assert spreadsheet_safe_cell("plain") == "plain"
    assert spreadsheet_safe_cell(-5) == -5 and spreadsheet_safe_cell(None) is None
    assert spreadsheet_safe_cell("Bracket\nrev B") == "Bracket\nrev B"


@pytest.mark.parametrize("value", ["plain", "a,b", 'say "hi"', "a\rb", "a\nb", "a\r\nb", " lead", "x;y",
                                   "=1", "multi\r=line, \"quoted\""])
def test_quoting_matches_the_csv_module(value):
    from src.services import csv_safe

    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow([csv_safe.safe_cell(value)])
    assert csv_safe.csv_field(value) == buf.getvalue()


def test_the_catalog_board_csv_keeps_a_cr_cell_in_its_row():
    from src.services import catalog_run_service

    board = {"rows": [{"filename": "part.stl", "description": _HOSTILE, "bucket": "in_house"},
                      {"filename": "other.stl", "description": "plain"}]}
    body = "".join(catalog_run_service.board_csv_rows(board))
    rows = _rows(body)
    assert len(rows) == 3, rows  # header + two parts
    assert [r[0] for r in rows[1:]] == ["part.stl", "other.stl"]
    assert not any(cell.lstrip().startswith(_FORMULA) for row in rows for cell in row)


def test_the_cost_and_line_item_writers_use_the_same_guard():
    from src.services import cost_decision_service

    out = cost_decision_service.build_estimates_csv(
        {"estimates": [{"process": "cnc", "material": "6061\r=cmd|' /C calc'!A0", "quantity": 1}]})
    rows = _rows(out)
    assert len(rows) == 2, rows
    assert rows[1][1] == "6061\r'=cmd|' /C calc'!A0"
