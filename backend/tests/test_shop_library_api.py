"""Governed shop-library API integration tests (W4 slice 2) against live Postgres.

Drives ``/api/v1/shop-library`` through an ASGI client with only the auth
principal overridden — ``require_role``/``require_org_role`` -> ``require_api_key``,
the real ``get_db_session`` -> ``resolve_org``, and the migration-0015 table all
run against the live DB. Proves:

  * Lifecycle — create draft → edit → publish → resolve the effective profile for
    a slug (via ``resolve_shop_overrides_for``).
  * Per-slug effective-dating — two slugs resolve independently; publishing a v2
    for a slug closes that slug's v1 ``effective_to``.
  * Cross-tenant isolation — an org admin can neither read nor publish another
    org's shop version (asserted by name).
  * Honesty — a governed profile is reported ``validated: false`` / provenance
    ``shop``.

Skipped unless DATABASE_URL is Postgres at schema head (``alembic upgrade head``). Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/shoplib_test \\
        .venv/bin/python -m pytest tests/test_shop_library_api.py -q
"""
from __future__ import annotations

import os
import uuid

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


def _build_app():
    from fastapi import FastAPI

    from src.api.shop_library import router as shop_library_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(shop_library_router, prefix="/api/v1/shop-library")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


@_requires_pg
@pytest.mark.asyncio
async def test_shop_library_lifecycle_isolation_and_honesty(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.services import shop_library_service as shop_svc

    monkeypatch.setenv("SHOP_LIBRARY_ENABLED", "1")

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())

    async def _mk_user(s, label):
        email = f"sl-{tag}-{label}@example.com"
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

    slug1, slug2 = "midwest-precision-cnc", "shenzhen-contract-mfg"
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # --- org A: draft for slug1 (seeded from the flat file) --------------
        _act_as(app, uid_a)
        r = await c.post(
            "/api/v1/shop-library", json={"slug": slug1, "name": "2026 Q3"}
        )
        assert r.status_code == 200, r.text
        v1 = r.json()
        assert v1["version"] == 1 and v1["status"] == "draft"
        assert v1["slug"] == slug1
        assert v1["validated"] is False and v1["provenance"] == "shop"
        assert v1["payload"]["labor_rate"] == 52.0  # migrated from flat file
        v1_id = v1["id"]

        # nothing published yet -> the engine resolves no governed profile
        async with eng.get_session_factory()() as s:
            assert (
                await shop_svc.resolve_shop_overrides_for(s, org_a, slug1)
            ) is None

        # --- edit the draft's labor rate then publish ------------------------
        payload = v1["payload"]
        payload["labor_rate"] = 61.0
        r = await c.patch(f"/api/v1/shop-library/{v1_id}", json={"payload": payload})
        assert r.status_code == 200, r.text

        r = await c.post(f"/api/v1/shop-library/{v1_id}/publish", json={})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "published"
        assert r.json()["effective_from"] is not None

        # now the governed profile resolves for slug1 with the edited rate
        async with eng.get_session_factory()() as s:
            resolved = await shop_svc.resolve_shop_overrides_for(s, org_a, slug1)
            assert resolved is not None
            assert resolved["labor_rate"] == 61.0

        # --- a SECOND slug resolves independently ----------------------------
        r = await c.post(
            "/api/v1/shop-library",
            json={"slug": slug2, "payload": {"labor_rate": 14.0, "name": "SZ"}},
        )
        assert r.status_code == 200, r.text
        v2_id = r.json()["id"]
        assert r.json()["version"] == 2 and r.json()["slug"] == slug2
        r = await c.post(f"/api/v1/shop-library/{v2_id}/publish", json={})
        assert r.status_code == 200, r.text

        async with eng.get_session_factory()() as s:
            # slug1 and slug2 resolve to their OWN payloads (no cross-slug leak)
            assert (
                await shop_svc.resolve_shop_overrides_for(s, org_a, slug1)
            )["labor_rate"] == 61.0
            assert (
                await shop_svc.resolve_shop_overrides_for(s, org_a, slug2)
            )["labor_rate"] == 14.0
            # a slug with no governed profile still resolves to None
            assert (
                await shop_svc.resolve_shop_overrides_for(s, org_a, "unpublished-slug")
            ) is None

        # --- publish a v3 for slug1 closes slug1's prior effective_to --------
        shop_svc.invalidate(org_a, slug1)
        r = await c.post(
            "/api/v1/shop-library", json={"from_version_id": v1_id}
        )
        v3_id = r.json()["id"]
        assert r.json()["slug"] == slug1  # inherits the source slug
        r = await c.post(f"/api/v1/shop-library/{v3_id}/publish", json={})
        assert r.status_code == 200, r.text

        r = await c.get("/api/v1/shop-library")
        by_id = {v["id"]: v for v in r.json()["versions"]}
        assert by_id[v1_id]["effective_to"] is not None  # slug1 v1 closed
        assert by_id[v3_id]["effective_to"] is None       # slug1 v3 open
        assert by_id[v2_id]["effective_to"] is None       # slug2 untouched

        # re-publishing an already-published version is a 409
        r = await c.post(f"/api/v1/shop-library/{v3_id}/publish", json={})
        assert r.status_code == 409

        # --- cross-tenant isolation ------------------------------------------
        _act_as(app, uid_b)
        r = await c.get(f"/api/v1/shop-library/{v3_id}")
        assert r.status_code == 404
        r = await c.post(f"/api/v1/shop-library/{v1_id}/publish", json={})
        assert r.status_code == 404
        r = await c.get("/api/v1/shop-library")
        assert r.json()["versions"] == []
        # org B has no governed profile for slug1 (A's never leaks over)
        async with eng.get_session_factory()() as s:
            assert (
                await shop_svc.resolve_shop_overrides_for(s, org_b, slug1)
            ) is None

    # --- cleanup -------------------------------------------------------------
    async with eng.get_session_factory()() as s:
        await s.execute(
            text("DELETE FROM shop_profile_versions WHERE org_id IN (:a, :b)"),
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
