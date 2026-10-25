"""A catalog run treats a multi-body file as several parts on the board.

Each body shape of a file becomes its own row (its own analysis and cost
decision, at the file's quantity times its copies); a weldment's members show
their stock and material and say welding isn't priced; the file counts once
toward a free run. The pure row derivation is tested here; the run end to end
(live Postgres and the real engine) below it.
"""
from __future__ import annotations

import pytest

from tests import part_type_cases as cases


def test_body_quantity_ladders_are_per_file():
    from src.services.catalog_bodies import body_filename, scaled_ladder

    assert scaled_ladder("1;100;1000", 2) == "2,200,2000"
    assert scaled_ladder("1,10", 1) == "1,10"
    assert body_filename("frames/frame.stl", 3, None) == "frame - body 3.stl"
    assert body_filename("as1.step", 5, "bolt") == "as1 - bolt.stl"


def _entry(kind: str, designs: list[dict]) -> dict:
    return {"kind": kind, "body_count": sum(d["copies"] for d in designs), "shapes": len(designs),
            "parent_mesh_hash": "f" * 64, "designs": designs, "summary": "This file holds …"}


def test_weldment_members_show_stock_and_no_machining_price():
    from src.services.catalog_run_service import body_rows, split_file_note

    entry = _entry("weldment", [
        {"design": 1, "bodies": [1, 2], "copies": 2, "status": "member", "filename": "frame - body 1.stl",
         "shape": "Square tube 40 × 40 × 3 mm, 600 mm long", "analysis_id": 7, "decision_ulid": None,
         "stock_material": {"material": "Mild Steel", "mass_kg": 2.091, "usd": 2.51, "density_g_cm3": 7.85}},
        {"design": 2, "bodies": [3], "copies": 1, "status": "open", "filename": "frame - body 3.stl",
         "reason": "This body isn't a closed solid on its own.", "analysis_id": None, "decision_ulid": None},
        {"design": 3, "bodies": [4], "copies": 1, "status": "not_checked", "filename": "frame - body 4.stl",
         "reason": "The time for this file ran out before this body was reached."},
    ])
    rows = body_rows(item={"ulid": "IT1", "filename": "frame.stl"}, entry=entry, parent_meta={"quantity": 5},
                     analyses={7: {"ulid": "AN7", "mesh_hash": "a" * 64}}, decisions={}, machines=[],
                     default_quantity=100)
    tube, opened, late = rows
    assert tube["bucket"] == "not_sorted" and tube["quantity"] == 10 and tube["quantity_source"] == "list"
    assert tube["reason"].startswith("Weldment member: Square tube 40 × 40 × 3 mm")
    assert tube["price_withheld"] == "welding isn't priced yet" and tube["unit_cost_usd"] is None
    assert tube["material"]["name"] == "Mild Steel" and tube["mass_kg_total"] == pytest.approx(20.91)
    assert tube["part_key"] == "a" * 64 and tube["item_id"] == "IT1:1"
    assert tube["body"] == {"file": "frame.stl", "file_key": "f" * 64, "kind": "weldment", "ids": [1, 2],
                            "copies": 2, "of": 4, "shape": "Square tube 40 × 40 × 3 mm, 600 mm long", "name": None}
    assert opened["bucket"] == "cant_make" and "closed solid" in opened["reason"]
    assert late["bucket"] == "not_checked" and late["reason"].startswith("The time for this file ran out")
    note = split_file_note("frame.stl", entry)
    assert note["rows"] == 3 and note["bodies"] == 4
    assert "counts as one part of the run's allowance" in note["words"] and "welding isn't priced yet" in note["words"]


# ── end to end ──────────────────────────────────────────────────────────────

from tests.test_catalog_run_e2e import _PG, _as, _get, _post, _run_all, _usage, world  # noqa: E402,F401


@pytest.mark.asyncio
@pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head (DATABASE_URL=postgresql://...)")
async def test_a_catalog_run_puts_each_body_shape_on_the_board(world):
    app, uid = world["app"], world["users"]["work"]
    _as(app, uid)
    files = {
        "two cubes.stl": cases.two_cubes(),
        "frame.stl": cases.welded_frame(),
        "cube.stl": cases.cube(),
    }
    r = await _post(app, files, quantity=10)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["parts"] == 3 and body["catalog"]["new"] == 3
    await _run_all(body["batch_id"])
    board = (await _get(app, f"/api/v1/batch/{body['batch_id']}/catalog")).json()
    rows = {row["filename"]: row for row in board["rows"]}
    # the two identical cubes: one row, two per file
    cube_body = rows["two cubes - body 1.stl"]
    assert cube_body["body"]["copies"] == 2 and cube_body["quantity"] == 20
    assert cube_body["bucket"] in ("in_house", "outside", "new_machine") and cube_body["cost_decision_id"]
    assert "two cubes.stl" not in rows, "the file isn't priced as one block"
    # the frame: its two member shapes, cut stock, welding not priced
    members = [row for row in board["rows"] if (row.get("body") or {}).get("file") == "frame.stl"]
    assert len(members) == 2 and all(m["bucket"] == "not_sorted" for m in members)
    assert all(m["price_withheld"] == "welding isn't priced yet" and m["material"]["mass_kg_each"] for m in members)
    assert {m["quantity"] for m in members} == {20}
    # the one solid is a row of its own, as before
    assert "body" not in rows["cube.stl"] and rows["cube.stl"]["cost_decision_id"]
    notes = {n["filename"]: n for n in board["split_files"]}
    assert set(notes) == {"two cubes.stl", "frame.stl"} and notes["frame.stl"]["kind"] == "weldment"
    # each file counts once toward the free run, whatever it holds
    usage = await _usage(uid)
    assert (usage["used"], usage["reserved"]) == (3, 0)
    csv = (await _get(app, f"/api/v1/batch/{body['batch_id']}/catalog.csv")).text.strip().splitlines()
    assert len(csv) == 1 + 4
