"""Portfolio roll-up API integration tests (W3, D5) against live Postgres.

Drives ``GET /api/v1/catalog/portfolio`` through an ASGI client with only the
auth principal overridden — everything below auth (require_role -> require_api_key
-> resolve_org -> the org-scoped portfolio build) runs against the live DB. Proves:

  * Cross-tenant isolation — org A's roll-up never aggregates org B's parts (and
    vice-versa); the tenant boundary is the ORG (org-mate a2's costed part IS
    aggregated for a1).
  * Savings ranking — rows rank by the engine's redesign save_pct descending; the
    savings ``basis`` + qty trace to persisted engine fields; a costed part with
    no cheaper redesign carries ``savings: null`` + a reason (never a fabricated
    number).
  * Exclusion accounting — a drafted-only part (no cost decision) is excluded from
    the ranking and counted in ``excluded_no_cost_count``.
  * Posture aggregate — driver provenance counts summed across costed parts.

Skipped unless DATABASE_URL is Postgres at schema head (>= 0012). Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/portfolio_iso_test \\
        .venv/bin/python -m pytest tests/test_portfolio_api.py -q
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

    from src.api.catalog import router as catalog_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(catalog_router, prefix="/api/v1/catalog")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


def _cost_result(*, make_now="cnc_3axis", rec_units=(40.0, 30.0), alt=None):
    """A report_to_dict-shaped decision with recommendation + if_redesigned."""
    q = (50, 5000)
    recommendation = {
        str(qi): {"process": make_now, "material": "aluminum_6061", "unit_cost_usd": u}
        for qi, u in zip(q, rec_units)
    }
    if_redesigned = {str(qi): None for qi in q}
    if alt:
        if_redesigned.update(alt)
    return {
        "quantities": list(q),
        "decision": {
            "make_now_process": make_now,
            "make_now_material": "aluminum_6061",
            "crossover_qty": 1200.0,
            "recommendation": recommendation,
            "if_redesigned": if_redesigned,
        },
        "estimates": [
            {
                "process": make_now,
                "material": "aluminum_6061",
                "quantity": 50,
                "unit_cost_usd": rec_units[0],
                "dfm_ready": True,
                "dfm_blockers": [],
                "confidence": {"validated": False, "label": "assumption band"},
                "drivers": [
                    {"name": "machine_rate", "provenance": "DEFAULT", "source": "generic"},
                    {"name": "labor_rate", "provenance": "SHOP", "source": "your shop"},
                ],
            }
        ],
    }


@_requires_pg
@pytest.mark.asyncio
async def test_portfolio_isolation_ranking_and_honesty():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_a = str(ULID())
    org_b = str(ULID())
    created_users: list[int] = []

    async def _mk_user(s, label):
        email = f"pf-{tag}-{label}@example.com"
        uid = int((await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider) "
            "VALUES (:e, :el, 'analyst', 'password') RETURNING id"
        ), {"e": email, "el": email.lower()})).first()[0])
        created_users.append(uid)
        return uid

    async def _mk_membership(s, org_id, uid, role):
        await s.execute(text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :o, :u, :r, now())"
        ), {"id": str(ULID()), "o": org_id, "u": uid, "r": role})

    async def _mk_analysis(s, org_id, uid, mesh):
        u = str(ULID())
        await s.execute(text(
            "INSERT INTO analyses (ulid, user_id, org_id, mesh_hash, "
            "process_set_hash, analysis_version, filename, file_type, "
            "file_size_bytes, result_json, verdict, face_count, duration_ms) "
            "VALUES (:ul, :u, :o, :mh, :ph, '0.3.0', :fn, 'stl', 1024, "
            "CAST(:rj AS jsonb), 'issues', 12, 50.0)"
        ), {
            "ul": u, "u": uid, "o": org_id, "mh": mesh, "ph": f"pset-{u}",
            "fn": f"{mesh}.stl",
            "rj": json.dumps({"best_process": "cnc_3axis",
                              "universal_issues": [], "process_scores": []}),
        })

    async def _mk_cost(s, org_id, uid, mesh, result):
        u = str(ULID())
        await s.execute(text(
            "INSERT INTO cost_decisions (ulid, user_id, org_id, mesh_hash, "
            "params_hash, engine_version, filename, file_type, result_json, "
            "make_now_process, crossover_qty, quantities) VALUES (:ul, :u, :o, :mh, "
            ":ph, '0.3.0', :fn, 'stl', CAST(:rj AS jsonb), :mnp, 1200.0, "
            "CAST(:q AS jsonb))"
        ), {
            "ul": u, "u": uid, "o": org_id, "mh": mesh, "ph": f"params-{u}",
            "fn": f"{mesh}.stl", "rj": json.dumps(result),
            "mnp": (result.get("decision") or {}).get("make_now_process"),
            "q": json.dumps(result.get("quantities")),
        })

    # ---- seed ---------------------------------------------------------------
    async with eng.get_session_factory()() as s:
        for oid, name in ((org_a, f"Org A {tag}"), (org_b, f"Org B {tag}")):
            await s.execute(text(
                "INSERT INTO organizations (id, name, slug, created_at) "
                "VALUES (:id, :n, :sl, now())"
            ), {"id": oid, "n": name, "sl": name.lower().replace(" ", "-")})
        a1 = await _mk_user(s, "a1")
        a2 = await _mk_user(s, "a2")
        b1 = await _mk_user(s, "b1")
        await _mk_membership(s, org_a, a1, "admin")
        await _mk_membership(s, org_a, a2, "member")
        await _mk_membership(s, org_b, b1, "admin")

        # Org A costed parts:
        mDeep = f"meshA-deep-{tag}"      # 30 -> 6 @5000 = 80% off (deepest)
        mShallow = f"meshA-shal-{tag}"   # 18 -> 15 @5000 = ~16.7% off
        mNoSave = f"meshA-nosv-{tag}"    # no cheaper redesign → savings null
        mDrafted = f"meshA-draft-{tag}"  # analysis only → excluded (org-mate a2)
        await _mk_cost(s, org_a, a1, mDeep, _cost_result(
            rec_units=(40.0, 30.0),
            alt={"5000": {"process": "injection_molding", "material": "abs",
                          "unit_cost_usd": 6.0, "caveat": "invest in tooling"}}))
        await _mk_cost(s, org_a, a1, mShallow, _cost_result(
            rec_units=(20.0, 18.0),
            alt={"5000": {"process": "die_casting", "material": "zamak",
                          "unit_cost_usd": 15.0, "caveat": "add draft"}}))
        await _mk_cost(s, org_a, a1, mNoSave, _cost_result(rec_units=(40.0, 30.0)))
        await _mk_analysis(s, org_a, a2, mDrafted)   # org-mate, drafted-only

        # Org B costed part (distinct mesh).
        mB = f"meshB-{tag}"
        await _mk_cost(s, org_b, b1, mB, _cost_result(
            rec_units=(40.0, 30.0),
            alt={"5000": {"process": "im", "material": "abs",
                          "unit_cost_usd": 9.0, "caveat": "tool up"}}))
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # ============ ACT AS a1 (org A) ============
            _act_as(app, a1)
            r = await ac.get("/api/v1/catalog/portfolio")
            assert r.status_code == 200, r.text
            body = r.json()

            keys = [row["part_key"] for row in body["rows"]]
            # org-mate a2's costed rows would be visible; drafted is excluded.
            assert set(keys) == {mDeep, mShallow, mNoSave}
            assert mB not in keys                       # org B never leaks

            # ranked by save_pct descending; null-savings sinks last
            assert keys[0] == mDeep
            assert keys[1] == mShallow
            assert keys[2] == mNoSave

            by_key = {row["part_key"]: row for row in body["rows"]}
            deep = by_key[mDeep]
            assert deep["savings"]["basis"] == "decision.if_redesigned"
            assert deep["savings"]["qty"] == 5000
            assert deep["savings"]["make_now_unit_usd"] == 30.0
            assert deep["savings"]["redesigned_unit_usd"] == 6.0
            assert deep["savings"]["redesigned_process"] == "injection_molding"
            assert deep["savings"]["caveat"] == "invest in tooling"
            assert deep["make_now_process"] == "cnc_3axis"
            assert deep["validated"] is False           # copied from the band

            # a costed part with no cheaper redesign → savings null + reason
            nos = by_key[mNoSave]
            assert nos["savings"] is None
            assert "no engine-computed cheaper alternative" in nos["reason"]

            summary = body["summary"]
            assert summary["parts"] == 4
            assert summary["costed"] == 3
            assert summary["drafted"] == 1
            assert summary["excluded_no_cost_count"] == 1
            assert summary["truncated"] is False
            # posture aggregate: 3 costed parts × (1 DEFAULT + 1 SHOP)
            p = summary["posture"]
            assert p["default"] == 3 and p["shop"] == 3
            assert p["total"] == 6 and p["grounded"] == 3
            assert p["grounded_pct"] == 0.5

            # ============ ACT AS b1 (org B) — symmetric isolation ============
            _act_as(app, b1)
            r = await ac.get("/api/v1/catalog/portfolio")
            body_b = r.json()
            keys_b = {row["part_key"] for row in body_b["rows"]}
            assert keys_b == {mB}
            assert not ({mDeep, mShallow, mNoSave} & keys_b)
            assert body_b["summary"]["costed"] == 1
    finally:
        async with eng.get_session_factory()() as s:
            if created_users:
                ids = created_users
                await s.execute(
                    text("DELETE FROM analyses WHERE user_id = ANY(:i)"), {"i": ids})
                await s.execute(
                    text("DELETE FROM cost_decisions WHERE user_id = ANY(:i)"),
                    {"i": ids})
                await s.execute(
                    text("DELETE FROM memberships WHERE user_id = ANY(:i)"),
                    {"i": ids})
                await s.execute(
                    text("DELETE FROM users WHERE id = ANY(:i)"), {"i": ids})
            await s.execute(
                text("DELETE FROM organizations WHERE id IN (:a, :b)"),
                {"a": org_a, "b": org_b})
            await s.commit()
        await eng.dispose_engine()
