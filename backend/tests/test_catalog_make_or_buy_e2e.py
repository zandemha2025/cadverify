"""The ops owner's make-or-buy answer, end to end (round 9, oo-07/08/09/10/12/16/21).

A run with a parts list naming materials and current prices, against the org's
Haas VF-2 (aluminum, steel) and Bambu X1C (PLA, PETG, ABS, nylon, TPU):

* the listed material is the material priced: a Delrin pin isn't printed in
  PLA, a PETG cup prints in PETG, an Inconel shim is never plastic (oo-08);
* "Make in-house" means it is cheaper to make: a part your machine makes for
  more than you pay today is "Buy outside" and says what making it would cost
  (oo-09), and the saving is against the current price (oo-21);
* a file not on the list is kept apart from the answer (oo-10);
* the run is named after its ZIP, counts the shop's machines (oo-12);
* a part that ran out of time is checked again once by itself, then says so in
  plain words; "Check again" puts failed parts back in the run (oo-07, oo-16).

Skipped unless DATABASE_URL is PostgreSQL at schema head (0059+).
"""
from __future__ import annotations

import pytest
import trimesh

from tests.test_catalog_run_e2e import _PG, _as, _get, _run_all, _stl, _zip, world  # noqa: F401

pytestmark = pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head (DATABASE_URL=postgresql://...)")


def _cyl(r: float, h: float, *, seed: int = 0) -> bytes:
    mesh = trimesh.creation.cylinder(radius=r, height=h, sections=64)
    mesh.apply_scale(1.0 + seed * 1e-4)
    return mesh.export(file_type="stl")


async def _post_named(app, files: dict[str, bytes], parts_list: str, zip_name: str, **form):
    from httpx import ASGITransport, AsyncClient

    upload = {"file": (zip_name, _zip(files), "application/zip"),
              "manifest": ("ridgeline-parts.csv", parts_list.encode(), "text/csv")}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post("/api/v1/catalog-runs", files=upload, data={k: str(v) for k, v in form.items()})


async def _post_json(app, path: str, body: dict | None = None):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post(path, json=body or {})


@pytest.mark.asyncio
async def test_the_listed_material_is_priced_and_in_house_means_cheaper(world):
    app, uid = world["app"], world["users"]["pilot"]
    _as(app, uid)
    files = {
        "pin.stl": _cyl(5, 40),
        "cup.stl": _stl((40, 40, 30), seed=3),
        "shim.stl": _stl((120, 80, 0.8), seed=4),
        "block-paid-a-lot.stl": _stl((60, 40, 30), seed=5),
        "block-paid-little.stl": _stl((60, 40, 31), seed=6),
        "not-on-the-list.stl": _stl((30, 30, 30), seed=7),
    }
    parts_list = (
        "Part Number,File,Description,Qty,Material,Current price,Per\n"
        "PR-2005,pin.stl,Pin,1000,Delrin,,\n"
        "PR-2002,cup.stl,Cup,40,PETG,,\n"
        "MB-1012,shim.stl,Shim sheet,10,Inconel 718,,\n"
        "MB-2001,block-paid-a-lot.stl,Spacer block,200,6061-T6 aluminum,\"$5,000.00\",each\n"
        "MB-2002,block-paid-little.stl,Spacer block B,200,6061-T6 aluminum,50,100\n"
    )
    r = await _post_named(app, files, parts_list, "Ridgeline-bought-parts.zip", quantity=100)
    assert r.status_code == 202, r.text
    batch_id = r.json()["batch_id"]
    await _run_all(batch_id)
    board = (await _get(app, f"/api/v1/batch/{batch_id}/catalog")).json()
    rows = {row["filename"]: row for row in board["rows"]}

    # oo-12: named after the ZIP; the shop's machines counted as Your shop counts them.
    assert board["name"] == "Ridgeline-bought-parts"
    assert board["machine_count"] == 2 and board["files"] == 6
    # oo-23: the Batches list names the run as its page does.
    listed = (await _get(app, "/api/v1/batches")).json()["batches"]
    assert [b["name"] for b in listed if b["batch_ulid"] == batch_id] == ["Ridgeline-bought-parts"]
    assert board["org_name"].startswith("catalog-")

    # oo-08: Delrin is machined in Delrin (the mill isn't declared for plastic), never printed in PLA.
    pin = rows["pin.stl"]
    assert pin["material"]["name"] == "Delrin (POM)", pin
    assert (pin["route"] or {}).get("process") != "fdm"
    assert pin["bucket"] in ("new_machine", "outside")
    # PETG prints in PETG on the X1C, which runs it.
    cup = rows["cup.stl"]
    assert cup["material"]["name"] == "PETG" and cup["route"]["machine"] == "Bambu Lab X1C", cup
    # Inconel is priced as Inconel, never as plastic, and never on a printer of yours.
    shim = rows["shim.stl"]
    assert shim["material"]["name"] and "Inconel" in shim["material"]["name"], shim
    assert (shim["route"] or {}).get("process") not in ("fdm", "sla", "sls", "mjf")

    # oo-09/oo-21: in-house when it costs less than what you pay today, with the saving.
    dear = rows["block-paid-a-lot.stl"]
    assert dear["bucket"] == "in_house", dear
    assert dear["current_price"] == {"usd_each": 5000.0, "source": "parts_list", "text": "$5,000.00 each"}
    assert dear["saving"]["each"] == pytest.approx(5000.0 - dear["make"]["unit_cost_usd"], abs=0.01)
    assert dear["saving"]["total"] == pytest.approx(dear["saving"]["each"] * 200, abs=0.5)
    # Buy when your machine costs more than you pay ($50 per 100 = $0.50 each).
    cheap = rows["block-paid-little.stl"]
    assert cheap["bucket"] == "outside", cheap
    assert cheap["could_make"]["machine"] == "Haas VF-2" and cheap["could_make"]["times"] > 1
    assert cheap["reason"].startswith("Could make in-house at $") and "× the buy price" in cheap["reason"]
    assert cheap["unit_cost_usd"] == 0.5

    # oo-14: the Make or buy tab names the machine of yours, at the part's listed quantity.
    from src.api.catalog import router as catalog_router

    app.include_router(catalog_router, prefix="/api/v1/catalog")
    page = (await _get(app, "/api/v1/catalog/makeability?bucket=makeable_in_house")).json()
    tab = {row["part_key"]: row for row in page["rows"]}
    assert tab[dear["part_key"]]["at_quantity"]["qty"] == 200
    assert tab[dear["part_key"]]["at_quantity"]["owned"]["machine"] == "Haas VF-2"

    # oo-10: a file not on the list is apart from the answer.
    assert rows["not-on-the-list.stl"]["listed"] is False
    assert board["unlisted"]["parts"] == 1
    answer = board["answer"]
    assert answer["parts"] == 5
    assert answer["make"] == board["totals"]["in_house"]["parts"]
    assert answer["saving_parts"] == 1 and answer["saving_usd"] == pytest.approx(dear["saving"]["total"], abs=0.01)
    assert board["bucket_rule"].startswith("Make in-house when one of your machines makes it for less")

    # The price and the yearly quantity are on the part for its own page; the record isn't out of date.
    from sqlalchemy import text

    import src.db.engine as eng
    async with eng.get_session_factory()() as s:
        ctx = (await s.execute(text(
            "SELECT buy_price, annual_volume FROM part_contexts WHERE org_id = :o AND mesh_hash = :h"),
            {"o": world["org"], "h": dear["part_key"]})).one()
        stale = (await s.execute(text("SELECT stale_at FROM cost_decisions WHERE ulid = :u"),
                                 {"u": dear["cost_decision_id"]})).scalar_one()
    assert ctx[0]["source"] == "parts_list" and ctx[0]["usd_each"] == 5000.0 and ctx[1] == 200
    assert stale is None

    # oo-22: one notification for the run, none per part.
    from src.jobs.batch_tasks import _notify_run_finished

    await _notify_run_finished(batch_id)
    async with eng.get_session_factory()() as s:
        kinds = (await s.execute(text("SELECT kind, title, body FROM notifications WHERE org_id = :o"),
                                 {"o": world["org"]})).all()
    assert [k for k, _t, _b in kinds] == ["catalog.run_finished"], kinds
    assert kinds[0][1] == "Catalog run finished - Ridgeline-bought-parts"
    assert "make in-house" in kinds[0][2] and "against what you pay today" in kinds[0][2]

    # A price typed on the part wins over the list's, and the row says which it used.
    from httpx import ASGITransport, AsyncClient

    from src.api.part_context import router as ctx_router

    app.include_router(ctx_router, prefix="/api/v1/part-context")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        put = await ac.put(f"/api/v1/part-context/{cheap['part_key']}", json={"buy_price": {"usd_each": 9000}})
    assert put.status_code == 200, put.text
    assert put.json()["buy_price"]["source"] == "you" and "decisions_marked_stale" not in put.json()
    board = (await _get(app, f"/api/v1/batch/{batch_id}/catalog")).json()
    cheap = next(row for row in board["rows"] if row["filename"] == "block-paid-little.stl")
    assert cheap["current_price"]["source"] == "you" and cheap["bucket"] == "in_house"


@pytest.mark.asyncio
async def test_a_part_out_of_time_is_checked_again_once_then_check_again_reruns_it(world, monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy import text

    import src.db.engine as eng
    from src.services import analysis_service

    app, uid = world["app"], world["users"]["pilot"]
    _as(app, uid)
    real = analysis_service.run_analysis
    calls = {"n": 0}

    async def slow(**kw):
        if kw.get("filename") == "slow.stl" and calls["n"] < 2:
            calls["n"] += 1
            raise HTTPException(status_code=504, detail="Analysis exceeded ANALYSIS_TIMEOUT_SEC=60s. Reduce scope.")
        return await real(**kw)

    monkeypatch.setattr(analysis_service, "run_analysis", slow)
    r = await _post_named(app, {"slow.stl": _stl((20, 20, 20), seed=11), "ok.stl": _stl((25, 20, 20), seed=12)},
                          "File,Qty\nslow.stl,5\nok.stl,5\n", "catalog.zip")
    assert r.status_code == 202, r.text
    batch_id = r.json()["batch_id"]
    await _run_all(batch_id)  # slow.stl times out: back in the run, last
    async with eng.get_session_factory()() as s:
        status, priority = (await s.execute(text(
            "SELECT bi.status, bi.priority FROM batch_items bi JOIN batches b ON b.id = bi.batch_id "
            "WHERE b.ulid = :b AND bi.filename = 'slow.stl'"), {"b": batch_id})).one()
    assert (status, priority) == ("pending", "low")
    await _run_all(batch_id)  # times out again: not checked, in plain words
    board = (await _get(app, f"/api/v1/batch/{batch_id}/catalog")).json()
    assert board["name"] == "ridgeline-parts"  # a browser-packed ZIP: the parts list's name
    slow_row = next(row for row in board["rows"] if row["filename"] == "slow.stl")
    assert slow_row["bucket"] == "not_checked"
    assert "TIMEOUT_SEC" not in (slow_row["reason"] or "") and "TIMEOUT_SEC" not in (slow_row["error"] or "")
    assert slow_row["reason"] == "Checking ran past its time limit; check it again"
    csv = await _get(app, f"/api/v1/batch/{batch_id}/catalog.csv")
    assert "TIMEOUT_SEC" not in csv.text

    # Check again: the failed part goes back in the run, which reopens, and lands on its own row.
    world["pool"].jobs.clear()
    again = await _post_json(app, f"/api/v1/batch/{batch_id}/catalog/recheck")
    assert again.status_code == 202, again.text
    assert again.json()["rechecking"] == [slow_row["item_id"]] and again.json()["status"] == "processing"
    assert world["pool"].jobs and world["pool"].jobs[-1][0] == "run_batch_coordinator"
    await _run_all(batch_id)
    board = (await _get(app, f"/api/v1/batch/{batch_id}/catalog")).json()
    slow_row = next(row for row in board["rows"] if row["filename"] == "slow.stl")
    assert slow_row["status"] == "completed" and slow_row["bucket"] != "not_checked"
    assert slow_row["quantity"] == 5 and slow_row["quantity_source"] == "list"
    nothing = await _post_json(app, f"/api/v1/batch/{batch_id}/catalog/recheck")
    assert nothing.status_code == 409 and nothing.json()["detail"]["code"] == "nothing_to_recheck"
