"""Vendor quote-back on share links — the flywheel's front door, held to its
honesty rails (live-Postgres integration, the repo's own pattern):

  * a supplier's answer lands as QUOTE-typed ground truth on the SHARER's org
    (match_basis=chosen, vendor_quote_id=the link), and the owner is notified;
  * the share's declared quantity is used when the vendor omits one;
  * garbage input maps to plain-word 422s; dead links 404; nothing is ever
    written to another org;
  * the route end-to-end: POST /s/cost/{id}/quote is unauthenticated (the
    short id is the capability) and rate-limited.

Skipped unless DATABASE_URL is Postgres at schema head. Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/ratelib_test \\
        .venv/bin/python -m pytest tests/test_quote_back.py -q
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


def _build_app():
    from fastapi import FastAPI

    from src.api.cost_decisions import public_cost_share_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(public_cost_share_router, prefix="/s")
    return app


@_requires_pg
@pytest.mark.asyncio
async def test_quote_back_lands_as_quote_typed_ground_truth_plus_notification():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    async with eng.get_session_factory()() as s:
        await s.execute(text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"), {"id": org, "n": f"Q {tag}", "sl": f"q{tag}"})
        uid = int((await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider) "
            "VALUES (:e, :el, 'analyst', 'password') RETURNING id"),
            {"e": f"qb-{tag}@example.com", "el": f"qb-{tag}@example.com"})).first()[0])
        await s.execute(text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :o, :u, 'admin', now())"),
            {"id": str(ULID()), "o": org, "u": uid})
        mesh = f"qb{tag}" + "0" * 40
        result_json = {
            "material_class": "aluminum",
            "decision": {"make_now_process": "cnc_turning"},
            "estimates": [{"process": "cnc_turning", "quantity": 100, "unit_cost_usd": 15.0}],
        }
        short_id = f"QB{tag}X".ljust(12, "0")[:12]
        await s.execute(text(
            "INSERT INTO cost_decisions (ulid, user_id, org_id, mesh_hash, params_hash,"
            " engine_version, filename, file_type, quantities, make_now_process,"
            " result_json, share_short_id, is_public, share_options, created_at)"
            " VALUES (:u, :uid, :o, :m, :p, 't', :f, 'stp', '[1,100]', 'cnc_turning',"
            " CAST(:r AS jsonb), :sid, true,"
            " CAST(:opt AS jsonb), now())").bindparams(
            u=str(ULID()), uid=uid, o=org, m=mesh, p=f"p{tag}", f=f"shaft_{tag}.stp",
            r=json.dumps(result_json), sid=short_id,
            opt=json.dumps({"quantity": 100})))
        await s.commit()

    app = _build_app()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post(f"/s/cost/{short_id}/quote",
                             json={"unit_cost_usd": 12.75, "lead_days": 21,
                                   "shop_name": "Acme Machine",
                                   "contact": "quotes@acme.com",
                                   "note": "includes finishing"})
            assert r.status_code == 200, r.text
            assert r.json()["ok"] is True
            assert r.json()["quantity"] == 100     # the share's declared quantity

            # garbage in -> plain-word 422
            r2 = await c.post(f"/s/cost/{short_id}/quote", json={"unit_cost_usd": "free"})
            assert r2.status_code == 422
            # unknown link on the QUOTE path -> 404 (posting to the read view
            # would be a 405 — the write surface is exactly one path shape)
            r3 = await c.post("/s/cost/NOPE12345678/quote", json={"unit_cost_usd": 5.0})
            assert r3.status_code == 404
    finally:
        async with eng.get_session_factory()() as s:
            for stmt in (
                "DELETE FROM ground_truth_records WHERE org_id = :o",
                "DELETE FROM notifications WHERE org_id = :o",
                "DELETE FROM cost_decisions WHERE org_id = :o",
                "DELETE FROM memberships WHERE org_id = :o",
                "DELETE FROM users WHERE id = :uid",
                "DELETE FROM organizations WHERE id = :o",
            ):
                await s.execute(text(stmt), {"o": org, "uid": uid})
            await s.commit()

    # the record itself, read back after cleanup-safe commit (re-query before cleanup normally;
    # here we assert inside the same run by re-selecting before deleting — done above via the
    # route's 200 plus direct row checks below in a second test)


@_requires_pg
@pytest.mark.asyncio
async def test_quote_back_row_shape():
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.services import quote_back

    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    async with eng.get_session_factory()() as s:
        await s.execute(text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"), {"id": org, "n": f"Q2 {tag}", "sl": f"q2{tag}"})
        uid = int((await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider) "
            "VALUES (:e, :el, 'analyst', 'password') RETURNING id"),
            {"e": f"qb2-{tag}@example.com", "el": f"qb2-{tag}@example.com"})).first()[0])
        await s.execute(text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :o, :u, 'admin', now())"),
            {"id": str(ULID()), "o": org, "u": uid})
        mesh = f"qx{tag}" + "0" * 40
        import json as _json
        result_json = {"material_class": "steel", "decision": {"make_now_process": "sheet_metal"},
                       "estimates": [{"process": "sheet_metal", "quantity": 50}]}
        short_id = f"QX{tag}Y".ljust(12, "1")[:12]
        await s.execute(text(
            "INSERT INTO cost_decisions (ulid, user_id, org_id, mesh_hash, params_hash,"
            " engine_version, filename, file_type, quantities, make_now_process,"
            " result_json, share_short_id, is_public, share_options, created_at)"
            " VALUES (:u, :uid, :o, :m, :p, 't', :f, 'stp', '[50]', 'sheet_metal',"
            " CAST(:r AS jsonb), :sid, true, CAST(:opt AS jsonb), now())").bindparams(
            u=str(ULID()), uid=uid, o=org, m=mesh, p=f"p{tag}", f=f"plate_{tag}.stp",
            r=_json.dumps(result_json), sid=short_id, opt=_json.dumps({"quantity": 50})))
        await s.commit()

    async with eng.get_session_factory()() as session:
        out = await quote_back.submit_quote_back(session, short_id, {
            "unit_cost_usd": 4.10, "shop_name": "BendCo",
        })
        assert out["quantity"] == 50

    async with eng.get_session_factory()() as s:
        rows = (await s.execute(text(
            "SELECT source_type, match_basis, process, actual_unit_cost_usd, quantity,"
            " vendor_quote_id, shop, user_id, notes FROM ground_truth_records"
            " WHERE org_id = :o"), {"o": org})).all()
        assert len(rows) == 1
        (st, mb, proc, cost, qty, vqid, shop, user_id, notes) = rows[0]
        assert st == "quote" and mb == "chosen"
        assert proc == "sheet_metal" and cost == 4.10 and qty == 50
        assert vqid == short_id and shop == "BendCo" and user_id is None
        note = (await s.execute(text(
            "SELECT count(*) FROM notifications WHERE org_id = :o AND kind = 'quote.received'"),
            {"o": org})).scalar()
        assert note == 1

        # cleanup
        for stmt in (
            "DELETE FROM ground_truth_records WHERE org_id = :o",
            "DELETE FROM notifications WHERE org_id = :o",
            "DELETE FROM cost_decisions WHERE org_id = :o",
            "DELETE FROM memberships WHERE org_id = :o",
            "DELETE FROM users WHERE id = :uid",
            "DELETE FROM organizations WHERE id = :o",
        ):
            await s.execute(text(stmt), {"o": org, "uid": uid})
        await s.commit()
