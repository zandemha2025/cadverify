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
        async with eng.get_session_factory()() as s:
            from sqlalchemy import text
            for o in (locals().get("oid"), locals().get("other_oid")):
                if o:
                    await s.execute(text("DELETE FROM cost_decisions WHERE org_id = :o"), {"o": o})
            await s.commit()
        await eng.dispose_engine()


def test_slim_result_keeps_only_what_the_screens_read():
    rj = _result([1, 10, 100])
    slim = svc.slim_result(rj, [1, 10, 100])
    assert {e["quantity"] for e in slim["estimates"]} == {10}
    assert "verification" not in slim
    assert svc.headline_qty([50, 5000]) == 50 and svc.headline_qty([]) is None
    assert svc.slim_result(None, None) == {"assumptions": [], "material_class": None, "decision": None, "estimates": []}
