"""Part specs in a catalog run's parts list (``src.services.parts_list_specs``).

Unit: column names and cell words map to the spec vocabulary; a phrase ScaleCAD
doesn't price is kept as a not-priced note and never refuses a run (the single
cell reader still names the row); a bare Ra needs a unit. End to end (live Postgres): a
run's parts list declares specs per file, they are stored on each part's context
and the part's record is priced and gated with them.
"""
from __future__ import annotations

import os

import pytest

from src.services.catalog_run_service import parse_parts_list
from src.services.parts_list_specs import attach, not_priced, note_text, parse_spec_cells


def _rows(text: str) -> list[dict]:
    return attach(parse_parts_list(text), text)


def test_a_list_without_spec_columns_is_unchanged():
    text = "file,qty,material\na.step,10,6061\n"
    assert _rows(text) == parse_parts_list(text)
    assert "part_specs" not in _rows(text)[0]


def test_spec_columns_map_loose_words_to_the_vocabulary():
    text = ("Part Number;File;Qty;Surface finish;Ra (µin);Heat treat;Inspection;Certifications\n"
            "BRK-1;a.step;10;Type II anodize + bead blast;32;stress relieve;FAI;AS9100, NADCAP (heat treating), ITAR\n"
            "BRK-2;b.step;5;hard coat;;Q&T;CMM report, 100%;ISO 9001\n"
            "BRK-3;c.step;5;;;;;\n")
    a, b, c = _rows(text)
    assert a["part_specs"] == {
        "finishes": ["anodize_ii", "bead_blast"], "heat_treatments": ["stress_relief"],
        "inspection": ["fai_as9102"], "certifications": ["as9100", "nadcap", "itar"],
        "nadcap_processes": ["heat_treating"], "ra_um": pytest.approx(32 * 0.0254), "ra_unit": "uin"}
    assert b["part_specs"] == {"finishes": ["anodize_iii"], "heat_treatments": ["quench_temper"],
                               "inspection": ["cmm_report", "full_100"], "certifications": ["iso9001"]}
    assert "part_specs" not in c


def test_the_template_headers_read_with_their_unit():
    text = ("file,part_number,quantity,material,finish,ra_um,heat_treatment,inspection,certifications\n"
            "bracket.step,BRK-100,25,6061-T6 aluminum,Type II anodize,1.6,,FAI,AS9100\n"
            "housing.stl,HSG-200,500,PETG,,,,,\n"
            'cover.iges,CVR-300,40,304 stainless,Passivation,0.8,Stress relief,CMM report,"AS9100, NADCAP (chemical processing)"\n')
    a, b, c = _rows(text)
    assert a["part_specs"] == {"finishes": ["anodize_ii"], "inspection": ["fai_as9102"], "certifications": ["as9100"],
                               "ra_um": 1.6, "ra_unit": "um"}
    assert "part_specs" not in b
    assert c["part_specs"]["nadcap_processes"] == ["chemical_processing"]
    assert c["part_specs"]["heat_treatments"] == ["stress_relief"]


@pytest.mark.parametrize("cells, header_unit, expect", [
    ({"ra": "0.8 µm"}, None, (0.8, "um")),
    ({"ra": "Ra 1.6um"}, None, (1.6, "um")),
    ({"ra": "63 microinch"}, None, (pytest.approx(63 * 0.0254), "uin")),
    ({"ra": "3.2"}, "um", (3.2, "um")),
])
def test_ra_cells_with_a_unit(cells, header_unit, expect):
    specs = parse_spec_cells(cells, 2, ra_header_unit=header_unit)
    assert (specs["ra_um"], specs["ra_unit"]) == expect


@pytest.mark.parametrize("cells, words", [
    ({"ra": "32"}, "needs a unit"),
    ({"ra": "smooth"}, "isn't a number"),
    ({"finish": "gold leaf"}, "finish 'gold leaf' isn't one ScaleCAD knows"),
    ({"heat": "cryo"}, "heat treatment 'cryo'"),
    ({"certs": "NADCAP"}, "NADCAP needs the special process"),
    ({"finish": "as machined, anodize"}, "as_machined means no finish"),
])
def test_what_it_cant_read_names_the_row(cells, words):
    with pytest.raises(ValueError, match="Row 7") as exc:
        parse_spec_cells(cells, 7)
    assert words in str(exc.value)


@pytest.mark.parametrize("cells, header_unit, specs, notes", [
    ({"finish": "Type II anodize, black"}, None, {"finishes": ["anodize_ii"]},
     [("finish", "black", "the anodize's colour; priced as the anodize")]),
    ({"finish": "Black oxide"}, None, None, [("finish", "Black oxide", "not priced: ScaleCAD has no price for it yet")]),
    ({"certs": "EN 10204 3.1"}, None, None,
     [("certification", "EN 10204 3.1", "not priced: ScaleCAD has no price for it yet")]),
    ({"finish": "Passivation", "inspection": "Roundness check"}, None, {"finishes": ["passivate"]},
     [("inspection", "Roundness check", "not priced: ScaleCAD has no price for it yet")]),
    ({"heat": "H1150"}, None, {"heat_treatments": ["solution_age"]}, []),
    ({"heat": "Q&T 28-32 HRC"}, None, {"heat_treatments": ["quench_temper"]}, []),
    ({"ra": "32", "finish": "passivate"}, None, {"finishes": ["passivate"]},
     [("Ra", "32", "not priced: needs a unit: write 32 µm or 32 µin")]),
    ({"certs": "NADCAP", "finish": "bead blast"}, None, {"finishes": ["bead_blast"]},
     [("certifications", "NADCAP", "not priced: NADCAP needs the special process it covers, for example heat_treating")]),
])
def test_a_run_keeps_what_it_cant_price_as_a_note_and_never_refuses(cells, header_unit, specs, notes):
    kept: list = []
    assert parse_spec_cells(cells, 9, ra_header_unit=header_unit, notes=kept) == specs
    assert [(n["column"], n["value"], n["why"]) for n in kept] == notes


def test_the_testers_real_parts_list_starts_a_run():
    """op-04: Ridgeline's 300-row list in the app's own template (finish, Ra, heat
    treatment, inspection, certifications as purchasing writes them)."""
    path = os.path.join(os.path.dirname(__file__), "assets", "parts-lists", "ridgeline_parts_list_2026Q3.csv")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    rows = _rows(text)
    assert len(rows) == 300 and rows[0]["part_number"] == "RFS-21011"
    # "Type II anodize, black" (quoted, as Excel writes it): one anodize, the colour kept.
    assert rows[0]["part_specs"] == {"finishes": ["anodize_ii"]}
    assert rows[0]["spec_notes"] == [{"column": "finish", "value": "black",
                                      "why": "the anodize's colour; priced as the anodize"}]
    notes = not_priced(rows)
    by_value: dict = {}
    for n in notes:
        by_value[n["value"]] = by_value.get(n["value"], 0) + 1
    assert by_value == {"EN 10204 3.1": 34, "Black oxide": 9, "Polish": 7, "Roundness check": 7}
    assert all(n["row"] and n["part"] for n in notes)
    assert sum(1 for r in rows if "solution_age" in (r.get("part_specs") or {}).get("heat_treatments", [])) == 9
    assert note_text(next(n for n in notes if n["value"] == "Black oxide")) == "Finish: Black oxide (not priced)"


def test_nadcap_without_a_named_process_takes_it_from_the_finish():
    specs = parse_spec_cells({"finish": "passivate", "certs": "NADCAP"}, 2)
    assert specs["certifications"] == ["nadcap"] and "nadcap_processes" not in specs


# ── end to end: a catalog run whose parts list declares specs ────────────────

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")


@pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head")
@pytest.mark.asyncio
async def test_a_runs_parts_list_specs_price_and_gate_each_part(world):
    from sqlalchemy import text

    import src.db.engine as eng
    from tests.test_catalog_run_e2e import _as, _post, _run_all, _stl

    app, uid = world["app"], world["users"]["work"]
    _as(app, uid)
    files = {"a.stl": _stl((40, 30, 20), seed=11), "b.stl": _stl((40, 30, 20), seed=12)}
    parts_list = ("File,Qty,Material,Finish,Ra (um),Certifications\n"
                  "a.stl,10,6061-T6,Type II anodize,,AS9100\n"
                  "b.stl,10,PLA,,0.4,\n")
    r = await _post(app, files, parts_list=parts_list, quantity=10)
    assert r.status_code == 202, r.text
    await _run_all(r.json()["batch_id"])
    async with eng.get_session_factory()() as s:
        ctx = dict((await s.execute(text(
            "SELECT d.filename, c.part_specs FROM part_contexts c JOIN cost_decisions d "
            "ON d.org_id = c.org_id AND d.mesh_hash = c.mesh_hash WHERE c.org_id = :o"), {"o": world["org"]})).all())
        results = dict((await s.execute(text(
            "SELECT filename, result_json FROM cost_decisions WHERE org_id = :o"), {"o": world["org"]})).all())
    assert ctx["a.stl"] == {"finishes": ["anodize_ii"], "certifications": ["as9100"]}
    assert ctx["b.stl"] == {"ra_um": 0.4, "ra_unit": "um"}
    a = results["a.stl"]
    assert a["specs"]["certifications"][0]["label"] == "AS9100"
    cnc = next(e for e in a["estimates"] if e["process"] == "cnc_3axis")
    assert "spec_anodize_ii" in cnc["line_items"]
    # The Haas is owned, but whether the shop holds AS9100 or anodizes isn't declared: can't confirm.
    assert a["verification"]["per_route"]["cnc_3axis"]["verdict"] == "unknown"
    b = results["b.stl"]
    fdm = [e for e in b["estimates"] if e["process"] == "fdm"]
    assert fdm and all(e["spec_excluded"] for e in fdm)
    assert b["verification"]["per_route"]["fdm"]["verdict"] == "not_makeable"


@pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head")
@pytest.mark.asyncio
async def test_a_spec_it_cant_price_starts_the_run_and_stays_on_the_row(world):
    from tests.test_catalog_run_e2e import _as, _get, _post, _stl

    _as(world["app"], world["users"]["work"])
    r = await _post(world["app"], {"a.stl": _stl((10, 10, 10))},
                    parts_list='file,qty,finish,certifications\na.stl,1,"Type II anodize, black",EN 10204 3.1\n')
    assert r.status_code == 202, r.text
    board = (await _get(world["app"], f"/api/v1/batch/{r.json()['batch_id']}/catalog")).json()
    assert board["parts_list"]["not_priced"]["count"] == 1
    row = board["rows"][0]
    assert row["specs"]["not_priced"] == ["Finish: black (colour of the anodize)",
                                          "Certification: EN 10204 3.1 (not priced)"]
    assert row["specs"]["summary"][0] == "Finish: Anodize, Type II"


@pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head")
@pytest.mark.asyncio
async def test_a_list_it_cant_read_is_a_clean_400_with_every_problem(world):
    from tests.test_catalog_run_e2e import _as, _post, _stl

    _as(world["app"], world["users"]["work"])
    r = await _post(world["app"], {"a.stl": _stl((10, 10, 10))},
                    parts_list="file,qty,price\na.stl,lots,1\nb.stl,2,abc\n")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["code"] == "INVALID_PARTS_LIST"
    assert [(p["row"], p["column"], p["value"]) for p in detail["problems"]] == [(2, "quantity", "lots"),
                                                                                (3, "current price", "abc")]
    assert detail["message"].startswith("2 cells in the parts list need a fix")


@pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head")
@pytest.mark.asyncio
async def test_a_picked_list_is_checked_without_the_zip(world):
    from httpx import ASGITransport, AsyncClient

    from tests.test_catalog_run_e2e import _as

    _as(world["app"], world["users"]["work"])
    path = os.path.join(os.path.dirname(__file__), "assets", "parts-lists", "ridgeline_parts_list_2026Q3.csv")
    with open(path, "rb") as fh:
        real = fh.read()
    async with AsyncClient(transport=ASGITransport(app=world["app"]), base_url="http://test") as ac:
        ok = await ac.post("/api/v1/catalog-runs/parts-list", files={"manifest": ("list.csv", real, "text/csv")})
        bad = await ac.post("/api/v1/catalog-runs/parts-list",
                            files={"manifest": ("list.csv", b"file,qty\na.stl,1.5\n,2\n", "text/csv")})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert (body["ok"], body["rows"], body["problems"]) == (True, 300, [])
    assert body["not_priced"]["count"] == 57 and body["with_price"] > 0
    assert bad.status_code == 200 and bad.json()["ok"] is False
    assert [p["row"] for p in bad.json()["problems"]] == [2, 3]


# The live-Postgres fixture of the catalog run tests.
from tests.test_catalog_run_e2e import world  # noqa: E402,F401
