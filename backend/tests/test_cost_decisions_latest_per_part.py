"""GET /cost-decisions/latest-per-part: one read for the Rates and Real costs screens.

The screens used to read up to 16 records one by one against a 60/hour
per-route limit. This read returns the newest decision per part for the
caller's org, with the screens' fields for the newest parts, in one request.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from ulid import ULID

from src.services import cost_decision_service as svc

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(not _PG, reason="requires Postgres (DATABASE_URL=postgresql://...)")


def _result(quantities, process="cnc_3axis", material="6061-T6 Aluminum", labor=35.0):
    return {
        "material_class": "aluminum",
        "quantities": quantities,
        "assumptions": [{"name": "labor_rate", "value": labor, "unit": "$/hr",
                         "provenance": "DEFAULT", "source": "card v0"}],
        "decision": {"make_now_process": process, "make_now_material": material,
                     "recommendation": {str(q): {"process": process, "material": material,
                                                 "unit_cost_usd": 10.0} for q in quantities},
                     "crossover_qty": None},
        "estimates": [{"process": p, "material": material, "quantity": q, "unit_cost_usd": 10.0 + q,
                       "drivers": []} for q in quantities for p in (process, "fdm")],
        "verification": {"per_route": {}},  # not part of the slim view
    }


async def _seed(s, label: str):
    from sqlalchemy import text

    oid = str(ULID())
    await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:i, :n, :s, now())"),
                    {"i": oid, "n": f"Org {label}", "s": f"org-{oid[-10:].lower()}"})
    email = f"latest-{oid[-10:]}@example.com"
    uid = int((await s.execute(text(
        "INSERT INTO users (email, email_lower, role, auth_provider) VALUES (:e, :e, 'analyst', 'password') RETURNING id"),
        {"e": email})).first()[0])
    await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                         "VALUES (:i, :o, :u, 'admin', now())"), {"i": str(ULID()), "o": oid, "u": uid})
    return oid, uid


def _decision(oid, uid, mesh, filename, quantities, when, **result_kw):
    from src.db.models import CostDecision

    rj = _result(quantities, **result_kw)
    return CostDecision(
        ulid=str(ULID.from_datetime(when)), user_id=uid, org_id=oid, mesh_hash=mesh,
        params_hash=f"p-{ULID()}", engine_version="test", filename=filename, file_type="stl",
        result_json=rj, make_now_process=rj["decision"]["make_now_process"], crossover_qty=None,
        quantities=quantities, created_at=when,
    )


@_requires_pg
@pytest.mark.asyncio
async def test_newest_decision_per_part_with_the_screens_fields_in_one_read():
    import src.db.engine as eng
    from src.api.cost_decisions import router
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    try:
        async with eng.get_session_factory()() as s:
            oid, uid = await _seed(s, "a")
            other_oid, other_uid = await _seed(s, "b")
            rows = [
                # Part A checked three times: only the newest counts.
                _decision(oid, uid, "mesh-a", "bracket.step", [1, 100], t0, labor=30.0),
                _decision(oid, uid, "mesh-a", "bracket.step", [1, 10, 100], t0 + timedelta(hours=1), labor=31.0),
                _decision(oid, uid, "mesh-a", "bracket.step", [1, 10, 1000], t0 + timedelta(hours=5), labor=35.0),
                # Part B once, part C twice (C's newest is the org's newest record).
                _decision(oid, uid, "mesh-b", "housing.stl", [50, 5000], t0 + timedelta(hours=2)),
                _decision(oid, uid, "mesh-c", "plate.iges", [1, 100], t0 + timedelta(hours=3)),
                _decision(oid, uid, "mesh-c", "plate.iges", [100, 1000], t0 + timedelta(hours=6), process="sls"),
                # Another org's newer record never shows.
                _decision(other_oid, other_uid, "mesh-a", "bracket.step", [10], t0 + timedelta(hours=9)),
            ]
            s.add_all(rows)
            await s.flush()

            out = await svc.latest_per_part(s, uid, detail_limit=2)
            assert [p["filename"] for p in out["parts"]] == ["plate.iges", "bracket.step", "housing.stl"]
            assert (out["total_parts"], out["has_more"]) == (3, False)
            assert [d["id"] for d in out["details"]] == [rows[5].ulid, rows[2].ulid]
            plate, bracket = out["details"]
            # Headline quantity: 10 when the check priced it, else its first.
            assert (plate["headline_qty"], bracket["headline_qty"]) == (100, 10)
            assert {e["quantity"] for e in bracket["result"]["estimates"]} == {10}
            assert {e["process"] for e in plate["result"]["estimates"]} == {"sls", "fdm"}
            assert bracket["result"]["assumptions"][0]["value"] == 35.0
            assert bracket["result"]["decision"]["make_now_material"] == "6061-T6 Aluminum"
            assert set(bracket["result"]) == {"assumptions", "material_class", "decision", "estimates"}
            assert "is_stale" in bracket and bracket["mesh_hash"] == "mesh-a"
            # Paging and no details.
            capped = await svc.latest_per_part(s, uid, limit=1, detail_limit=0)
            assert ([p["filename"] for p in capped["parts"]], capped["has_more"], capped["details"]) == (["plate.iges"], True, [])
            other = await svc.latest_per_part(s, other_uid)
            assert [p["filename"] for p in other["parts"]] == ["bracket.step"]
            await s.commit()

        # Over HTTP: one request, org-scoped, viewer access.
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/cost-decisions")
        app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=uid, api_key_id=0, key_prefix="session")

        async def _session():
            async with eng.get_session_factory()() as s2:
                yield s2

        app.dependency_overrides[get_db_session] = _session
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            r = await client.get("/api/v1/cost-decisions/latest-per-part", params={"detail_limit": 12})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["total_parts"] == 3 and len(body["details"]) == 3
            assert (await client.get("/api/v1/cost-decisions/latest-per-part", params={"detail_limit": 51})).status_code == 422
            # The per-record read still works next to it.
            assert (await client.get(f"/api/v1/cost-decisions/{rows[2].ulid}")).status_code == 200
    finally:
        # Leave no rows behind: other suites scan every user in the database.
        async with eng.get_session_factory()() as s:
            from sqlalchemy import text
            for o in (locals().get("oid"), locals().get("other_oid")):
                if o:
                    await s.execute(text("DELETE FROM cost_decisions WHERE org_id = :o"), {"o": o})
                    users = (await s.execute(text("SELECT user_id FROM memberships WHERE org_id = :o"), {"o": o})).scalars().all()
                    await s.execute(text("DELETE FROM memberships WHERE org_id = :o"), {"o": o})
                    for u in users:
                        await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
                    await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": o})
            await s.commit()
        await eng.dispose_engine()


def test_slim_result_keeps_only_what_the_screens_read():
    rj = _result([1, 10, 100])
    slim = svc.slim_result(rj, [1, 10, 100])
    assert {e["quantity"] for e in slim["estimates"]} == {10}
    assert "verification" not in slim
    assert svc.headline_qty([50, 5000]) == 50 and svc.headline_qty([]) is None
    assert svc.slim_result(None, None) == {"assumptions": [], "material_class": None, "decision": None, "estimates": []}


async def _whole_record_latest_per_part(s, user_id, *, limit=svc.LATEST_PARTS_MAX, detail_limit=12):
    """The read as it was before slim inputs: what-ifs filtered and ranked in SQL
    over every stored result, and the shown records' whole results loaded. The
    oracle the served response must match byte for byte."""
    from sqlalchemy import func, select
    from sqlalchemy.orm import defer

    from src.auth.org_context import caller_org_subquery
    from src.db.models import CostDecision
    from src.services.rate_card_basis import basis_for

    ranked = (
        select(CostDecision.id.label("id"), func.row_number().over(
            partition_by=CostDecision.mesh_hash, order_by=CostDecision.ulid.desc()).label("rn"))
        .where(CostDecision.org_id == caller_org_subquery(user_id), svc.current_price_clause())
        .subquery()
    )
    newest = select(ranked.c.id).where(ranked.c.rn == 1)
    total = (await s.execute(select(func.count()).select_from(newest.subquery()))).scalar_one()
    rows = (await s.execute(select(CostDecision).options(defer(CostDecision.result_json))
                            .where(CostDecision.id.in_(newest)).order_by(CostDecision.ulid.desc())
                            .limit(limit))).scalars().all()
    shown = rows[:detail_limit]
    rates = await basis_for(s, rows[0].org_id, rows) if rows else {}
    results = {}
    if shown:
        results = dict((await s.execute(select(CostDecision.id, CostDecision.result_json)
                                        .where(CostDecision.id.in_([d.id for d in shown])))).all())
    return {
        "parts": [{**svc._list_item(d, result_json=None), "rates": rates.get(d.ulid)} for d in rows],
        "total_parts": int(total or 0),
        "has_more": int(total or 0) > len(rows),
        "details": [{**svc._list_item(d, result_json=None), "rates": rates.get(d.ulid),
                     "headline_qty": svc.headline_qty(d.quantities),
                     "result": svc.slim_result(results.get(d.id), d.quantities)} for d in shown],
    }


@_requires_pg
@pytest.mark.asyncio
async def test_response_is_pinned_and_no_saved_result_is_read_per_request():
    """The served response equals the whole-record read byte for byte, with the
    same fields; no request reads a saved result after a record's first, and
    the list itself never reads one."""
    import json

    from sqlalchemy import event, text

    import src.db.engine as eng
    from src.api.cost_decisions import router
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    what_if = {"what_if": {"label": "What if: overhead 15%", "overrides": {"overhead": 0.15}, "shop": None}}
    reads: list[str] = []

    def _count(conn, cursor, statement, params, context, executemany):
        if "result_json" in statement:
            reads.append(statement)

    try:
        async with eng.get_session_factory()() as s:
            oid, uid = await _seed(s, "pin")
            other_oid, other_uid = await _seed(s, "pin-other")
            mk = lambda *a, **k: _decision(oid, uid, *a, **k)  # noqa: E731
            rows = [
                mk("mesh-a", "bracket.step", [1, 100], t0),
                mk("mesh-a", "bracket.step", [1, 10, 100], t0 + timedelta(hours=1), labor=31.0),
                mk("mesh-b", "housing.stl", [50, 5000], t0 + timedelta(hours=2)),
                mk("mesh-c", "plate.iges", [100, 1000], t0 + timedelta(hours=3), process="sls"),
                mk("mesh-d", "only-what-if.step", [10], t0 + timedelta(hours=4)),
                _decision(other_oid, other_uid, "mesh-a", "theirs.step", [10], t0 + timedelta(hours=9)),
            ]
            # mesh-a's newest record is a what-if (never its price); mesh-d has only a what-if.
            what_ifs = [mk("mesh-a", "bracket.step", [1, 10], t0 + timedelta(hours=5)),
                        mk("mesh-d", "only-what-if.step", [10], t0 + timedelta(hours=6))]
            for d in what_ifs:
                d.result_json = {**d.result_json, **what_if}
            rows[-2].result_json = {**rows[-2].result_json, **what_if}  # mesh-d's first is a what-if too
            s.add_all(rows + what_ifs)
            await s.commit()

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/cost-decisions")
        app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=uid, api_key_id=0, key_prefix="session")

        async def _session():
            async with eng.get_session_factory()() as s2:
                yield s2

        app.dependency_overrides[get_db_session] = _session
        engine = eng.get_engine()
        event.listen(engine.sync_engine, "before_cursor_execute", _count)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                cases = [{}, {"detail_limit": 0}, {"limit": 1, "detail_limit": 1}, {"limit": 2, "detail_limit": 50}]
                first = {}
                for params in cases:
                    reads.clear()
                    r = await client.get("/api/v1/cost-decisions/latest-per-part", params=params)
                    assert r.status_code == 200, r.text
                    first[str(params)] = (r.content, list(reads))
                reads.clear()
                again = {str(p): (await client.get("/api/v1/cost-decisions/latest-per-part", params=p)).content
                         for p in cases}
                assert reads == []  # every record answered from memory
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _count)

        # The first request read the what-if test of the org's records and the
        # shown records' results, each once, and the listing never read a result.
        stmts = first["{}"][1]
        assert len(stmts) == 2 and all("row_number" not in q.lower() for q in stmts)
        assert first["{'detail_limit': 0}"][1] == []  # all already known

        async with eng.get_session_factory()() as s:
            for params in cases:
                expected = await _whole_record_latest_per_part(s, uid, **params)
                body = json.dumps(expected, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
                assert first[str(params)][0] == body == again[str(params)], params

        body = json.loads(first["{}"][0])
        assert set(body) == {"parts", "total_parts", "has_more", "details"}
        assert (body["total_parts"], body["has_more"]) == (3, False)  # mesh-d has no current price
        assert [p["filename"] for p in body["parts"]] == ["plate.iges", "housing.stl", "bracket.step"]
        bracket = body["parts"][2]
        assert bracket["what_if"] is None and bracket["quantities"] == [1, 10, 100]  # not the newer what-if
        part_keys = {
            "what_if", "id", "mesh_hash", "filename", "file_type", "label", "make_now_process", "crossover_qty",
            "quantities", "created_at", "is_public", "share_url", "share_status", "share_expires_at",
            "share_created_at", "share_ended_at", "share_end_date_added", "share_shows", "approval_status",
            "approved_by_user_id", "approved_at", "approval_note", "is_stale", "stale_at", "stale_reason",
            "user_disposition", "user_disposition_label", "disposition_note", "disposition_basis",
            "disposition_updated_at", "disposition_updated_by_user_id", "rates",
        }
        assert all(set(p) == part_keys for p in body["parts"])
        assert all(set(d) == part_keys | {"headline_qty", "result"} for d in body["details"])
        assert set(body["parts"][0]["rates"]) == {"priced", "current", "out_of_date", "text"}
        for d in body["details"]:
            assert set(d["result"]) == {"assumptions", "material_class", "decision", "estimates"}
            assert set(d["result"]["decision"]) == {"make_now_process", "make_now_material", "recommendation"}
            assert {e["quantity"] for e in d["result"]["estimates"]} == {d["headline_qty"]}
    finally:
        async with eng.get_session_factory()() as s:
            for o in (locals().get("oid"), locals().get("other_oid")):
                if o:
                    await s.execute(text("DELETE FROM cost_decisions WHERE org_id = :o"), {"o": o})
                    users = (await s.execute(text("SELECT user_id FROM memberships WHERE org_id = :o"), {"o": o})).scalars().all()
                    await s.execute(text("DELETE FROM memberships WHERE org_id = :o"), {"o": o})
                    for u in users:
                        await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
                    await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": o})
            await s.commit()
        await eng.dispose_engine()
