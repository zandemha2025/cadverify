"""Wave-B W6-1 regression tests (portfolio refetch/rate-limit lockout).

Two levers of the fix, both exercised against live Postgres through an ASGI
client with only the auth principal overridden:

  1. The portfolio READ limit is a sane interactive ceiling — a realistic burst
     of ``GET /portfolio`` calls (well past the old 60/hour) no longer 429s.
  2. ``PUT /part-context/{mesh}`` returns a ``portfolio_delta`` whose row + program
     rollup are BYTE-IDENTICAL to what a full ``GET /portfolio`` refetch shows, so
     the client can patch local state instead of refetching the whole (rate-
     limited) portfolio on every edit — and the displayed rollup never drifts.

Skipped unless DATABASE_URL is Postgres at schema head. Run:

    DATABASE_URL=postgresql://postgres@localhost:5433/cadverify_wb1 \\
        .venv/bin/python -m pytest tests/test_portfolio_w6_ratelimit.py -q
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
    from slowapi.errors import RateLimitExceeded

    from src.api.catalog import router as catalog_router
    from src.api.part_context import router as part_context_router
    from src.auth.rate_limit import limiter, rate_limit_handler

    app = FastAPI()
    app.state.limiter = limiter
    # Faithful 429 shape (otherwise slowapi raises → a 500 that hides the lockout).
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.include_router(catalog_router, prefix="/api/v1/catalog")
    app.include_router(part_context_router, prefix="/api/v1/part-context")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


def _cost_result(*, unit=230.0, make_now="cnc_3axis"):
    # Both edited volumes are real engine points. Program exposure is allowed to
    # annualize only from an exact recommendation at the declared quantity.
    q = (1000, 2000)
    return {
        "quantities": list(q),
        "decision": {
            "make_now_process": make_now,
            "make_now_material": "aluminum_6061",
            "crossover_qty": 1200.0,
            "recommendation": {
                str(quantity): {"process": make_now, "unit_cost_usd": unit}
                for quantity in q
            },
            "if_redesigned": {str(quantity): None for quantity in q},
        },
        "estimates": [
            {
                "process": make_now,
                "material": "aluminum_6061",
                "quantity": quantity,
                "unit_cost_usd": unit,
                "dfm_ready": True,
                "dfm_blockers": [],
                "confidence": {"validated": False, "label": "assumption band"},
                "drivers": [{"name": "labor", "provenance": "SHOP", "source": "shop"}],
            }
            for quantity in q
        ],
    }


@_requires_pg
@pytest.mark.asyncio
async def test_portfolio_read_limit_raised_and_put_delta_matches_refetch():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    created_users: list[int] = []

    async def _mk_user(s):
        email = f"w6-{tag}@example.com"
        uid = int((await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider) "
            "VALUES (:e, :el, 'analyst', 'password') RETURNING id"
        ), {"e": email, "el": email.lower()})).first()[0])
        created_users.append(uid)
        return uid

    async def _mk_cost(s, uid, mesh, unit):
        u = str(ULID())
        result = _cost_result(unit=unit)
        await s.execute(text(
            "INSERT INTO cost_decisions (ulid, user_id, org_id, mesh_hash, "
            "params_hash, engine_version, filename, file_type, result_json, "
            "make_now_process, crossover_qty, quantities) VALUES (:ul, :u, :o, :mh, "
            ":ph, '0.3.0', :fn, 'stl', CAST(:rj AS jsonb), :mnp, 1200.0, "
            "CAST(:q AS jsonb))"
        ), {
            "ul": u, "u": uid, "o": org, "mh": mesh, "ph": f"params-{u}",
            "fn": f"{mesh}.stl", "rj": json.dumps(result),
            "mnp": "cnc_3axis", "q": json.dumps(result["quantities"]),
        })

    mA, mB = f"meshA-{tag}", f"meshB-{tag}"
    async with eng.get_session_factory()() as s:
        await s.execute(text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"
        ), {"id": org, "n": f"W6 {tag}", "sl": f"w6-{tag}"})
        uid = await _mk_user(s)
        await s.execute(text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :o, :u, 'admin', now())"
        ), {"id": str(ULID()), "o": org, "u": uid})
        await _mk_cost(s, uid, mA, 230.0)  # 230 × 1000 = 230,000/yr
        await _mk_cost(s, uid, mB, 100.0)
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, uid)

            # (1) Lever one: a realistic burst PAST the old 60/hour cap does not
            # 429 at the raised interactive limit (600/hour). 70 calls proves the
            # old lockout is gone without exercising the full 600 ceiling.
            for _ in range(70):
                r = await ac.get("/api/v1/catalog/portfolio")
                assert r.status_code == 200, f"portfolio 429'd at the old cap: {r.text}"

            # (2) Lever two: assign mA @ 1000 units → the PUT delta must equal a
            # full refetch. First declare the program + volume.
            r = await ac.put(
                f"/api/v1/part-context/{mA}",
                json={"program": "Actuator", "annual_volume": 1000},
            )
            assert r.status_code == 200, r.text
            put_body = r.json()
            delta = put_body["portfolio_delta"]
            assert delta["row"]["part_key"] == mA
            assert delta["row"]["annualized_cost_usd"] == 230000.0
            assert delta["row"]["context"]["annual_volume"] == 1000

            # Byte-identity: the delta row + programs equal the full refetch's.
            r = await ac.get("/api/v1/catalog/portfolio")
            body = r.json()
            fetched_row = next(x for x in body["rows"] if x["part_key"] == mA)
            assert delta["row"] == fetched_row
            assert delta["programs"] == body["summary"]["programs"]
            prog = next(p for p in delta["programs"] if p["program"] == "Actuator")
            assert prog["annualized_cost_usd"] == 230000.0
            assert prog["parts"] == 1

            # (3) A volume EDIT re-declares and the delta tracks the new number,
            # still matching a refetch — the client never has to refetch to update.
            r = await ac.put(
                f"/api/v1/part-context/{mA}", json={"annual_volume": 2000}
            )
            assert r.status_code == 200, r.text
            delta2 = r.json()["portfolio_delta"]
            assert delta2["row"]["annualized_cost_usd"] == 460000.0
            assert delta2["row"]["annualized_unit_cost"]["qty"] == 2000
            r = await ac.get("/api/v1/catalog/portfolio")
            body2 = r.json()
            fetched2 = next(x for x in body2["rows"] if x["part_key"] == mA)
            assert delta2["row"] == fetched2
            assert delta2["programs"] == body2["summary"]["programs"]
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM part_contexts WHERE org_id = :o"), {"o": org})
            if created_users:
                await s.execute(
                    text("DELETE FROM cost_decisions WHERE user_id = ANY(:i)"),
                    {"i": created_users})
                await s.execute(
                    text("DELETE FROM memberships WHERE user_id = ANY(:i)"),
                    {"i": created_users})
                await s.execute(
                    text("DELETE FROM users WHERE id = ANY(:i)"), {"i": created_users})
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.commit()
        await eng.dispose_engine()
