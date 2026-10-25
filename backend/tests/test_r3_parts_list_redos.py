"""Security review R3, F1: no parts-list cell makes reading the list slow.

A parts list (POST /api/v1/catalog-runs/parts-list, POST /api/v1/batch and
POST /api/v1/catalog-runs with a list) is read cell by cell with regexes. Each
cell ScaleCAD reads holds at most 1,000 characters (a longer one is a problem in
the list's one report); a price, "per" or Ra cell is read on its words with
whitespace runs as one space and at most 40 characters; and the Ra, price and
certification readers are linear in the cell however it is written. An Ra cell
ScaleCAD can't read is still a note, never a refusal.
"""
from __future__ import annotations

import time

import pytest

from src.services import catalog_run_service, parts_list_specs
from src.services.catalog_run_service import PartsListError


def _list(column: str, cell: str) -> str:
    return f'file,{column}\npart.stl,"{cell}"\n'


def _timed(fn):
    t = time.monotonic()
    try:
        out = fn()
    except ValueError as exc:
        out = exc
    return out, time.monotonic() - t


def test_ra_cell_with_long_whitespace_run_is_linear():
    # Just under the cell cap: read, kept as a note, and fast (was ~2 s, cubic in the run of spaces).
    text = _list("Ra", "1" + " " * 990 + "x")
    rows, elapsed = _timed(lambda: parts_list_specs.attach(catalog_run_service.parse_parts_list(text), text))
    assert elapsed < 0.5, f"one 992-character Ra cell took {elapsed:.1f}s"
    assert [n["column"] for n in rows[0]["spec_notes"]] == ["Ra"]
    assert rows[0]["spec_notes"][0]["why"].startswith("not priced")
    assert "part_specs" not in rows[0]


def test_ra_cell_over_the_cap_is_a_problem_in_the_lists_report():
    text = _list("Ra", "1" + " " * 1600 + "x")  # the reviewer's 1.6 KB cell (~9 s before)
    exc, elapsed = _timed(lambda: catalog_run_service.parse_parts_list(text))
    assert elapsed < 0.5, f"took {elapsed:.1f}s"
    assert isinstance(exc, PartsListError)
    [problem] = exc.problems
    assert (problem["row"], problem["column"]) == (2, "Ra")
    assert problem["why"] == "is longer than 1,000 characters"
    assert len(problem["value"]) <= 41  # never the whole cell echoed back


def test_a_wordy_ra_cell_is_a_note_never_a_refusal():
    text = _list("Ra", "0.8 µm on the sealing faces, 3.2 µm everywhere else")
    rows = parts_list_specs.attach(catalog_run_service.parse_parts_list(text), text)
    [note] = rows[0]["spec_notes"]
    assert note["column"] == "Ra"
    assert note["why"] == "not priced: is longer than 40 characters: write a number with µm or µin"


@pytest.mark.parametrize("hostile", [
    "1" * 5_000 + "x",            # [0-9]*\.?[0-9]+ was quadratic in a run of digits (3 s)
    "ra" + "1" * 5_000 + " um ra x",
    "1" + " " * 1_000 + "x",      # three \s* around an empty unit was cubic (2 s; 18 s at 2,000)
], ids=["digit-run", "ra-digit-run", "space-run"])
def test_the_ra_pattern_itself_is_linear(hostile):
    _, elapsed = _timed(lambda: parts_list_specs._RA_CELL.fullmatch(hostile))
    assert elapsed < 0.1, f"{elapsed:.2f}s"


@pytest.mark.parametrize("cell, um, unit", [
    ("0.8 µm", 0.8, "um"), ("Ra 1.6um", 1.6, "um"), ("1.6  µm\tRa", 1.6, "um"), (".8 um", 0.8, "um"),
    ("32 µin", 32 * 0.0254, "uin"), ('63µ"', 63 * 0.0254, "uin"), ("ra125 microinches", 125 * 0.0254, "uin"),
])
def test_ra_cells_still_read_the_same(cell, um, unit):
    specs = parts_list_specs.parse_spec_cells({"ra": cell}, 2)
    assert specs["ra_um"] == pytest.approx(um) and specs["ra_unit"] == unit


def test_price_cell_with_long_whitespace_run_is_linear():
    text = "file,current price\npart.stl,1" + " " * 8000 + "x\n"
    exc, elapsed = _timed(lambda: catalog_run_service.parse_parts_list(text))
    assert elapsed < 0.2, f"one 8 KB price cell took {elapsed:.1f}s"
    assert isinstance(exc, PartsListError) and exc.problems[0]["column"] == "current price"


def test_price_cell_just_under_the_cap_is_read_on_its_words():
    text = "file,current price\npart.stl,12.40" + " " * 900 + "per 100\n"
    rows, elapsed = _timed(lambda: catalog_run_service.parse_parts_list(text))
    assert elapsed < 0.2
    assert rows[0]["current_price_usd"] == pytest.approx(0.124) and rows[0]["current_price"] == "$12.40 per 100"


@pytest.mark.parametrize("hostile", ["1" + " " * 10_000 + "x",  # (.*?)\s*(?:/|per) was quadratic (1.1 s)
                                     "1" + " " * 100_000 + "x", "/" * 100_000, "1/" * 50_000 + "x"],
                         ids=["space-run", "long-space-run", "slashes", "slash-pairs"])
def test_the_price_split_is_linear(hostile):
    _, elapsed = _timed(lambda: catalog_run_service._split_per(hostile))
    assert elapsed < 0.1, f"{elapsed:.2f}s"


@pytest.mark.parametrize("cell, usd, shown", [
    ("$12.40", 12.40, "$12.40 each"), ("1,250 / 100", 12.50, "$1,250.00 per 100"),
    ("12.40 per C", 0.124, "$12.40 per 100"), ("USD 5 /each", 5.0, "$5.00 each"), ("n/a", None, None),
])
def test_price_cells_still_read_the_same(cell, usd, shown):
    got_usd, got_shown = catalog_run_service._parse_price(cell, "", 2)
    assert got_shown == shown
    assert got_usd == (pytest.approx(usd) if usd is not None else None)


@pytest.mark.parametrize("hostile", ["(" * 10_000 + "x",  # \([^)]*\) was quadratic (0.6 s)
                                     "AS9100 (" + "a" * 50_000, "(a" * 25_000],
                         ids=["opens", "unclosed", "open-pairs"])
def test_certification_cells_are_linear(hostile):
    notes: list = []
    _, elapsed = _timed(lambda: parts_list_specs.parse_spec_cells({"certs": hostile}, 2, notes=notes))
    assert elapsed < 0.2, f"{elapsed:.2f}s"


def test_certifications_still_split_out_the_nadcap_process():
    specs = parts_list_specs.parse_spec_cells({"certs": "AS9100, NADCAP (heat treating), ITAR"}, 2)
    assert specs["certifications"] == ["as9100", "nadcap", "itar"]
    assert specs["nadcap_processes"] == ["heat_treating"]


@pytest.mark.parametrize("column", ["description", "material", "finish", "heat treatment", "inspection",
                                    "certifications", "quantity", "part number"])
def test_every_cell_read_has_the_cap(column):
    text = f'file,{column}\npart.stl,"' + "a " * 600 + '"\n'
    exc, elapsed = _timed(lambda: catalog_run_service.parse_parts_list(text))
    assert elapsed < 0.2
    assert isinstance(exc, PartsListError)
    assert [(p["row"], p["column"]) for p in exc.problems] == [(2, column)]


def test_a_long_cell_in_a_column_scalecad_doesnt_read_is_fine():
    text = 'file,notes\npart.stl,"' + "a" * 5000 + '"\n'
    assert catalog_run_service.parse_parts_list(text)[0]["file"] == "part.stl"


def test_a_cell_past_the_csv_readers_own_limit_is_a_problem_not_a_crash():
    # The csv module refuses a field over 128 KiB with csv.Error (not a ValueError): it was a 500.
    text = "file,description\npart.stl,ok\nother.stl," + "a" * 200_000 + "\n"
    exc, _ = _timed(lambda: catalog_run_service.parse_parts_list(text))
    assert isinstance(exc, PartsListError)
    assert exc.problems[-1]["row"] == 3 and "longer than 1,000 characters" in exc.problems[-1]["why"]


def test_old_mac_line_endings_read_as_rows():
    text = "file,qty\rpart.stl,10\rother.stl,5\r"
    rows = catalog_run_service.read_parts_list(text)
    assert [(r["row"], r["file"], r["quantity"]) for r in rows] == [(2, "part.stl", 10), (3, "other.stl", 5)]


@pytest.mark.parametrize("column, cell", [("qty", "inf"), ("qty", "nan"), ("qty", "1e400"), ("per", "²")])
def test_number_cells_that_floats_or_ints_choke_on_are_cell_problems(column, cell):
    header = "file,current price,per" if column == "per" else f"file,{column}"
    row = f"part.stl,12.00,{cell}" if column == "per" else f"part.stl,{cell}"
    exc, _ = _timed(lambda: catalog_run_service.parse_parts_list(f"{header}\n{row}\n"))
    assert isinstance(exc, PartsListError), exc
    assert exc.problems[0]["column"] in ("quantity", "per")
