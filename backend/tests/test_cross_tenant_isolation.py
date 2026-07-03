"""End-to-end cross-tenant isolation for the W1 step-3 org-threaded data routes.

The load-bearing proof that org scoping on the ~43 data routes is *real*, not a
decorative WHERE clause. Two orgs are seeded against **live Postgres** with a
full object spread each — analyses, cost_decisions, batches (+items), jobs,
api_keys — and every list/get endpoint is driven through an ASGI client with
only the auth principal overridden. Everything below auth (require_role ->
require_api_key, the real get_db_session -> the org-subquery filters in the
handlers/services) runs against the live DB.

Design of the seed proves the boundary is the ORG, not the user:

  * Org A has TWO users (a1, a2). a1 can read a2's analysis / cost-decision /
    batch by id and sees them in its lists — impossible under the old per-user
    scoping — which proves the org_id filter is what's doing the work.
  * Org B has one user (b1). a1/a2 get 404 (never 403) on every one of B's
    objects by id, and B's rows never appear in A's lists (and vice-versa).
  * API keys stay PERSONAL: a1 sees only a1's key, never org-mate a2's — keys
    are user-scoped credentials (org_id is defense-in-depth), so this asserts
    the deliberate exception to org-level sharing.
  * The public share routes (/s/{id}, /s/cost/{id}) stay UNSCOPED and keep
    working with no auth at all.

Skipped unless DATABASE_URL is Postgres at schema head (>= 0010). Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/find_isolation \\
        .venv/bin/python -m pytest tests/test_cross_tenant_isolation.py -q
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
    """A FastAPI app mounting the org-scoped data routers at their real prefixes
    (mirrors main.py) with the slowapi limiter state the @limiter.limit routes
    need. Only the auth dependencies get overridden per acting principal."""
    from fastapi import FastAPI

    from src.api.batch_router import router as batch_router
    from src.api.cost_decisions import public_cost_share_router
    from src.api.cost_decisions import router as cost_router
    from src.api.history import router as history_router
    from src.api.jobs_router import router as jobs_router
    from src.api.pdf import router as pdf_router
    from src.api.share import public_share_router, share_router
    from src.auth.keys_api import router as keys_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(batch_router)                       # /api/v1/batch*
    app.include_router(jobs_router, prefix="/api/v1")      # /api/v1/jobs/*
    app.include_router(history_router, prefix="/api/v1/analyses")
    app.include_router(share_router, prefix="/api/v1/analyses")
    app.include_router(pdf_router, prefix="/api/v1/analyses")
    app.include_router(public_share_router, prefix="/s")
    app.include_router(cost_router, prefix="/api/v1/cost-decisions")
    app.include_router(public_cost_share_router, prefix="/s")
    app.include_router(keys_router)                        # /api/v1/keys
    return app


def _act_as(app, user_id: int) -> None:
    """Point BOTH auth axes (Bearer/session for data routes, dashboard session
    for keys) at a specific seeded principal."""
    from src.auth.dashboard_session import require_dashboard_session
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )
    app.dependency_overrides[require_dashboard_session] = lambda: user_id


@_requires_pg
@pytest.mark.asyncio
async def test_cross_tenant_isolation_matrix():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_a = str(ULID())
    org_b = str(ULID())
    created_users: list[int] = []
    _RESULT = json.dumps({"process_scores": [], "best_process": None})

    async def _mk_user(s, label: str) -> int:
        email = f"iso-{tag}-{label}@example.com"
        uid = int(
            (
                await s.execute(
                    text(
                        "INSERT INTO users (email, email_lower, role, auth_provider) "
                        "VALUES (:e, :el, 'analyst', 'password') RETURNING id"
                    ),
                    {"e": email, "el": email.lower()},
                )
            ).first()[0]
        )
        created_users.append(uid)
        return uid

    async def _mk_membership(s, org_id, uid, role):
        await s.execute(
            text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                "VALUES (:id, :o, :u, :r, now())"
            ),
            {"id": str(ULID()), "o": org_id, "u": uid, "r": role},
        )

    async def _mk_analysis(s, org_id, uid, *, public=False, short=None) -> str:
        u = str(ULID())
        await s.execute(
            text(
                "INSERT INTO analyses (ulid, user_id, org_id, mesh_hash, "
                "process_set_hash, analysis_version, filename, file_type, "
                "file_size_bytes, result_json, verdict, face_count, duration_ms, "
                "is_public, share_short_id) VALUES (:ul, :u, :o, :mh, :ph, '0.3.0', "
                ":fn, 'stl', 1024, CAST(:rj AS jsonb), 'pass', 12, 50.0, :pub, :sh)"
            ),
            {
                "ul": u, "u": uid, "o": org_id, "mh": f"mesh-{u}",
                "ph": f"pset-{u}", "fn": f"{u}.stl", "rj": _RESULT,
                "pub": public, "sh": short,
            },
        )
        return u

    async def _mk_cost(s, org_id, uid, *, public=False, short=None) -> str:
        u = str(ULID())
        await s.execute(
            text(
                "INSERT INTO cost_decisions (ulid, user_id, org_id, mesh_hash, "
                "params_hash, engine_version, filename, file_type, result_json, "
                "make_now_process, crossover_qty, is_public, share_short_id) "
                "VALUES (:ul, :u, :o, :mh, :ph, '0.3.0', :fn, 'stl', "
                "CAST(:rj AS jsonb), 'cnc_3axis', 100.0, :pub, :sh)"
            ),
            {
                "ul": u, "u": uid, "o": org_id, "mh": f"mesh-{u}",
                "ph": f"params-{u}", "fn": f"{u}.stl",
                "rj": json.dumps({"decision": {}, "estimates": []}),
                "pub": public, "sh": short,
            },
        )
        return u

    async def _mk_batch(s, org_id, uid) -> str:
        u = str(ULID())
        bid = int(
            (
                await s.execute(
                    text(
                        "INSERT INTO batches (ulid, user_id, org_id, status, "
                        "input_mode, total_items, completed_items, failed_items) "
                        "VALUES (:ul, :u, :o, 'completed', 'zip', 1, 1, 0) "
                        "RETURNING id"
                    ),
                    {"ul": u, "u": uid, "o": org_id},
                )
            ).first()[0]
        )
        await s.execute(
            text(
                "INSERT INTO batch_items (ulid, batch_id, org_id, filename, status) "
                "VALUES (:ul, :b, :o, 'part.stl', 'completed')"
            ),
            {"ul": str(ULID()), "b": bid, "o": org_id},
        )
        return u

    async def _mk_job(s, org_id, uid) -> str:
        u = str(ULID())
        await s.execute(
            text(
                "INSERT INTO jobs (ulid, user_id, org_id, job_type, status, "
                "result_json) VALUES (:ul, :u, :o, 'sam3d', 'done', CAST(:rj AS jsonb))"
            ),
            {"ul": u, "u": uid, "o": org_id, "rj": json.dumps({"ok": True})},
        )
        return u

    async def _mk_key(s, org_id, uid, label) -> int:
        return int(
            (
                await s.execute(
                    text(
                        "INSERT INTO api_keys (user_id, org_id, name, prefix, "
                        "hmac_index, secret_hash) VALUES (:u, :o, :n, :p, :h, 'x') "
                        "RETURNING id"
                    ),
                    {
                        "u": uid, "o": org_id, "n": label,
                        "p": f"pfx{label}", "h": f"hmac-{tag}-{label}",
                    },
                )
            ).first()[0]
        )

    # ---- seed ---------------------------------------------------------------
    async with eng.get_session_factory()() as s:
        for oid, name in ((org_a, f"Org A {tag}"), (org_b, f"Org B {tag}")):
            await s.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_at) "
                    "VALUES (:id, :n, :sl, now())"
                ),
                {"id": oid, "n": name, "sl": name.lower().replace(" ", "-")},
            )
        a1 = await _mk_user(s, "a1")
        a2 = await _mk_user(s, "a2")
        b1 = await _mk_user(s, "b1")
        await _mk_membership(s, org_a, a1, "admin")
        await _mk_membership(s, org_a, a2, "member")
        await _mk_membership(s, org_b, b1, "admin")

        an_a1 = await _mk_analysis(s, org_a, a1, public=True, short=f"pubA{tag}")
        an_a2 = await _mk_analysis(s, org_a, a2)
        an_b1 = await _mk_analysis(s, org_b, b1)

        cd_a1 = await _mk_cost(s, org_a, a1, public=True, short=f"pubcostA{tag}")
        cd_a2 = await _mk_cost(s, org_a, a2)
        cd_b1 = await _mk_cost(s, org_b, b1)

        ba_a1 = await _mk_batch(s, org_a, a1)
        ba_a2 = await _mk_batch(s, org_a, a2)
        ba_b1 = await _mk_batch(s, org_b, b1)

        jb_a1 = await _mk_job(s, org_a, a1)
        jb_b1 = await _mk_job(s, org_b, b1)

        key_a1 = await _mk_key(s, org_a, a1, "a1")
        key_a2 = await _mk_key(s, org_a, a2, "a2")
        key_b1 = await _mk_key(s, org_b, b1, "b1")
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # ================================================================
            # ACT AS a1 (org A). Org-level scope: a1 sees a2's rows; never B's.
            # ================================================================
            _act_as(app, a1)

            # --- analyses list + get ---
            r = await ac.get("/api/v1/analyses?limit=100")
            assert r.status_code == 200, r.text
            ids = {a["id"] for a in r.json()["analyses"]}
            assert {an_a1, an_a2} <= ids            # org-mate visible (org scope)
            assert an_b1 not in ids                 # cross-org never leaks
            assert (await ac.get(f"/api/v1/analyses/{an_a2}")).status_code == 200
            assert (await ac.get(f"/api/v1/analyses/{an_b1}")).status_code == 404

            # --- cost-decisions list + get + exports ---
            r = await ac.get("/api/v1/cost-decisions?limit=100")
            assert r.status_code == 200, r.text
            ids = {c["id"] for c in r.json()["cost_decisions"]}
            assert {cd_a1, cd_a2} <= ids
            assert cd_b1 not in ids
            assert (await ac.get(f"/api/v1/cost-decisions/{cd_a2}")).status_code == 200
            assert (await ac.get(f"/api/v1/cost-decisions/{cd_b1}")).status_code == 404
            assert (
                await ac.get(f"/api/v1/cost-decisions/{cd_b1}/export.json")
            ).status_code == 404
            assert (
                await ac.get(f"/api/v1/cost-decisions/{cd_b1}/export.csv")
            ).status_code == 404
            # compare across the org boundary is blocked (get_owned -> 404)
            assert (
                await ac.get(f"/api/v1/cost-decisions/compare?ids={cd_a1},{cd_b1}")
            ).status_code == 404

            # --- batches list + get + items + csv ---
            r = await ac.get("/api/v1/batches?limit=100")
            assert r.status_code == 200, r.text
            ids = {b["batch_ulid"] for b in r.json()["batches"]}
            assert {ba_a1, ba_a2} <= ids
            assert ba_b1 not in ids
            assert (await ac.get(f"/api/v1/batch/{ba_a2}")).status_code == 200
            assert (await ac.get(f"/api/v1/batch/{ba_b1}")).status_code == 404
            assert (await ac.get(f"/api/v1/batch/{ba_b1}/items")).status_code == 404
            assert (
                await ac.get(f"/api/v1/batch/{ba_b1}/results/csv")
            ).status_code == 404

            # --- jobs get + result ---
            assert (await ac.get(f"/api/v1/jobs/{jb_a1}")).status_code == 200
            assert (await ac.get(f"/api/v1/jobs/{jb_b1}")).status_code == 404
            assert (await ac.get(f"/api/v1/jobs/{jb_b1}/result")).status_code == 404

            # --- api keys: PERSONAL (user-scoped), not org-shared ---
            r = await ac.get("/api/v1/keys")
            assert r.status_code == 200, r.text
            kids = {k["id"] for k in r.json()}
            assert key_a1 in kids
            assert key_a2 not in kids               # org-mate's key stays private
            assert key_b1 not in kids
            # cross-org key by id -> 404 on every mutation
            assert (await ac.delete(f"/api/v1/keys/{key_b1}")).status_code == 404
            assert (
                await ac.patch(f"/api/v1/keys/{key_b1}", json={"name": "x"})
            ).status_code == 404
            assert (
                await ac.post(f"/api/v1/keys/{key_b1}/rotate")
            ).status_code == 404
            # owner is never locked out by the added org predicate
            assert (
                await ac.patch(f"/api/v1/keys/{key_a1}", json={"name": "renamed"})
            ).status_code == 200

            # ================================================================
            # ACT AS b1 (org B). Symmetric: sees only B, 404 on all of A.
            # ================================================================
            _act_as(app, b1)

            r = await ac.get("/api/v1/analyses?limit=100")
            ids = {a["id"] for a in r.json()["analyses"]}
            assert an_b1 in ids
            assert not ({an_a1, an_a2} & ids)
            assert (await ac.get(f"/api/v1/analyses/{an_a1}")).status_code == 404

            r = await ac.get("/api/v1/cost-decisions?limit=100")
            ids = {c["id"] for c in r.json()["cost_decisions"]}
            assert cd_b1 in ids
            assert not ({cd_a1, cd_a2} & ids)
            assert (await ac.get(f"/api/v1/cost-decisions/{cd_a1}")).status_code == 404

            r = await ac.get("/api/v1/batches?limit=100")
            ids = {b["batch_ulid"] for b in r.json()["batches"]}
            assert ba_b1 in ids
            assert not ({ba_a1, ba_a2} & ids)
            assert (await ac.get(f"/api/v1/batch/{ba_a1}")).status_code == 404
            assert (await ac.get(f"/api/v1/jobs/{jb_a1}")).status_code == 404

            # ================================================================
            # Public share routes stay UNSCOPED and work with NO auth at all.
            # ================================================================
            app.dependency_overrides.clear()
            assert (await ac.get(f"/s/pubA{tag}")).status_code == 200
            assert (await ac.get(f"/s/cost/pubcostA{tag}")).status_code == 200
            assert (await ac.get(f"/s/does-not-exist-{tag}")).status_code == 404
    finally:
        # ---- teardown (FK-safe, no leaks) ----------------------------------
        async with eng.get_session_factory()() as s:
            if created_users:
                ids = created_users
                await s.execute(
                    text("DELETE FROM batch_items WHERE org_id IN (:a, :b)"),
                    {"a": org_a, "b": org_b},
                )
                await s.execute(
                    text("DELETE FROM batches WHERE user_id = ANY(:i)"), {"i": ids}
                )
                await s.execute(
                    text("DELETE FROM jobs WHERE user_id = ANY(:i)"), {"i": ids}
                )
                await s.execute(
                    text("DELETE FROM analyses WHERE user_id = ANY(:i)"), {"i": ids}
                )
                await s.execute(
                    text("DELETE FROM cost_decisions WHERE user_id = ANY(:i)"),
                    {"i": ids},
                )
                await s.execute(
                    text("DELETE FROM api_keys WHERE user_id = ANY(:i)"), {"i": ids}
                )
                await s.execute(
                    text("DELETE FROM memberships WHERE user_id = ANY(:i)"), {"i": ids}
                )
                await s.execute(
                    text("DELETE FROM users WHERE id = ANY(:i)"), {"i": ids}
                )
            await s.execute(
                text("DELETE FROM organizations WHERE id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )
            await s.commit()
        await eng.dispose_engine()
