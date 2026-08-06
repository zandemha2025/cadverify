"""W4 governance change-request flow — integration tests against live Postgres.

Drives ``/api/v1/governance`` (plus the rate-library router, to author the target
drafts) through an ASGI client with only the auth principal overridden — the real
``get_db_session`` / ``resolve_org`` / ``require_org_role`` and the migration-0016
``change_requests`` table all run against the live DB. Proves:

  * Approve PUBLISHES — propose a rate-card draft -> approve -> the target
    version is now ``published`` and resolves as the effective governed card.
  * Reject LEAVES A DRAFT — a second draft -> propose -> reject -> the version
    is still a ``draft`` and never resolves as effective.
  * Cross-tenant isolation — org B can neither see nor approve org A's change
    request (asserted by name).

Skipped unless DATABASE_URL is Postgres at schema head (``alembic upgrade head``). Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/ratelib_test \\
        .venv/bin/python -m pytest tests/test_governance_api.py -q
"""
from __future__ import annotations

import os
import uuid

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


@pytest.fixture(autouse=True)
def _loop_hermetic_engine():
    """Keep asyncpg pools bound to each pytest-asyncio test loop.

    The DB engine is a module singleton; in the full live-Postgres suite a pool
    created by an earlier async test can be bound to a now-closed event loop.
    Dropping the singleton here mirrors the org-membership integration tests.
    """
    import src.db.engine as _eng

    _eng._ENGINE = None
    _eng._SESSION_FACTORY = None
    try:
        yield
    finally:
        _eng._ENGINE = None
        _eng._SESSION_FACTORY = None


def _build_app():
    from fastapi import FastAPI

    from src.api.governance import router as governance_router
    from src.api.rate_library import router as rate_library_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(rate_library_router, prefix="/api/v1/rate-library")
    app.include_router(governance_router, prefix="/api/v1/governance")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


@_requires_pg
@pytest.mark.asyncio
async def test_governance_flow_publish_reject_and_isolation(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    monkeypatch.setenv("RATE_LIBRARY_ENABLED", "1")

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())

    async def _mk_user(s, label):
        email = f"gov-{tag}-{label}@example.com"
        return int(
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

    async with eng.get_session_factory()() as s:
        for oid, nm in ((org_a, f"A {tag}"), (org_b, f"B {tag}")):
            await s.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_at) "
                    "VALUES (:id, :n, :sl, now())"
                ),
                {"id": oid, "n": nm, "sl": f"{oid[-8:].lower()}"},
            )
        uid_a = await _mk_user(s, "a")
        uid_b = await _mk_user(s, "b")
        for oid, uid in ((org_a, uid_a), (org_b, uid_b)):
            await s.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                    "VALUES (:id, :o, :u, 'admin', now())"
                ),
                {"id": str(ULID()), "o": oid, "u": uid},
            )
        await s.commit()

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # --- org A authors a draft rate card ---------------------------------
        _act_as(app, uid_a)
        r = await c.post("/api/v1/rate-library", json={"name": "2026 Q3"})
        assert r.status_code == 200, r.text
        v1 = r.json()
        v1_id = v1["id"]
        payload = v1["payload"]
        payload["global"]["labor_rate"] = 55.0
        r = await c.patch(f"/api/v1/rate-library/{v1_id}", json={"payload": payload})
        assert r.status_code == 200, r.text

        # engine not consuming anything yet (only a draft exists)
        r = await c.get("/api/v1/rate-library/effective")
        assert r.json()["using_governed"] is False

        # --- propose the draft for review ------------------------------------
        r = await c.post(
            "/api/v1/governance/change-requests",
            json={
                "asset_type": "rate_card",
                "target_version_id": v1_id,
                "title": "Adopt 2026 Q3 labor rate",
            },
        )
        assert r.status_code == 200, r.text
        cr = r.json()
        cr_id = cr["id"]
        assert cr["status"] == "proposed"
        assert cr["asset_type"] == "rate_card"
        assert cr["target_version_id"] == v1_id
        assert cr["proposed_by"] == uid_a

        # proposing a NON-draft (nothing published yet, so reuse a bad id) 404
        r = await c.post(
            "/api/v1/governance/change-requests",
            json={"asset_type": "rate_card", "target_version_id": 10_000_000},
        )
        assert r.status_code == 404

        # --- approve -> PUBLISHES the draft ----------------------------------
        r = await c.post(f"/api/v1/governance/change-requests/{cr_id}/approve")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["change_request"]["status"] == "approved"
        assert body["change_request"]["reviewed_by"] == uid_a
        assert body["change_request"]["decided_at"] is not None
        assert body["published_version"]["status"] == "published"
        assert body["published_version"]["id"] == v1_id

        # the target version is now PUBLISHED and resolves as effective
        r = await c.get(f"/api/v1/rate-library/{v1_id}")
        assert r.json()["status"] == "published"
        r = await c.get("/api/v1/rate-library/effective")
        eff = r.json()
        assert eff["using_governed"] is True
        assert eff["payload"]["global"]["labor_rate"] == 55.0

        # approving an already-decided request is a 409
        r = await c.post(f"/api/v1/governance/change-requests/{cr_id}/approve")
        assert r.status_code == 409

        # --- second draft -> propose -> reject -> stays a draft --------------
        r = await c.post("/api/v1/rate-library", json={"from_version_id": v1_id})
        v2 = r.json()
        v2_id = v2["id"]
        r = await c.post(
            "/api/v1/governance/change-requests",
            json={"asset_type": "rate_card", "target_version_id": v2_id},
        )
        cr2_id = r.json()["id"]
        r = await c.post(
            f"/api/v1/governance/change-requests/{cr2_id}/reject",
            json={"note": "hold for Q4 numbers"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "rejected"
        assert "hold for Q4" in r.json()["note"]

        # the rejected draft is STILL a draft (never published)
        r = await c.get(f"/api/v1/rate-library/{v2_id}")
        assert r.json()["status"] == "draft"
        # and the effective card is still v1 (the rejected draft never resolves)
        r = await c.get("/api/v1/rate-library/effective")
        assert r.json()["payload"]["global"]["labor_rate"] == 55.0

        # list reflects both requests for org A
        r = await c.get("/api/v1/governance/change-requests")
        got = {x["id"]: x for x in r.json()["change_requests"]}
        assert got[cr_id]["status"] == "approved"
        assert got[cr2_id]["status"] == "rejected"

        # --- cross-tenant isolation ------------------------------------------
        _act_as(app, uid_b)
        # org B cannot GET org A's change request
        r = await c.get(f"/api/v1/governance/change-requests/{cr_id}")
        assert r.status_code == 404
        # org B's list never sees org A's requests
        r = await c.get("/api/v1/governance/change-requests")
        assert r.json()["change_requests"] == []
        # org B cannot approve/reject org A's request (404 — not even visible)
        r = await c.post(f"/api/v1/governance/change-requests/{cr2_id}/approve")
        assert r.status_code == 404
        r = await c.post(
            f"/api/v1/governance/change-requests/{cr2_id}/reject", json={}
        )
        assert r.status_code == 404
        # org B cannot propose over org A's version (target not in B's org) 404
        r = await c.post(
            "/api/v1/governance/change-requests",
            json={"asset_type": "rate_card", "target_version_id": v2_id},
        )
        assert r.status_code == 404

    # --- cleanup -------------------------------------------------------------
    async with eng.get_session_factory()() as s:
        await s.execute(
            text("DELETE FROM change_requests WHERE org_id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.execute(
            text("DELETE FROM rate_card_versions WHERE org_id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.execute(
            text("DELETE FROM memberships WHERE org_id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.execute(
            text("DELETE FROM users WHERE id IN (:a, :b)"),
            {"a": uid_a, "b": uid_b},
        )
        await s.execute(
            text("DELETE FROM organizations WHERE id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.commit()
    # Release the async engine bound to THIS test's event loop so the next async
    # PG test in the process rebuilds it on its own loop (repo convention — every
    # other PG integration test does this; asyncpg pools are loop-bound).
    await eng.dispose_engine()
