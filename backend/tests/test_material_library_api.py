"""Governed materials-library API integration tests (W4 slice 3) against live Postgres.

Drives ``/api/v1/material-library`` through an ASGI client with only the auth
principal overridden — the real ``get_db_session`` -> ``resolve_org`` and the
migration-0017 table run against the live DB. Proves:

  * Lifecycle — create draft -> edit -> publish -> resolve the effective catalog.
  * Effective-dating — publishing v2 closes v1's ``effective_to``; the engine
    resolves the version in effect.
  * Cross-tenant isolation — an org admin can neither read nor publish another
    org's version.
  * Honesty — a governed catalog is reported ``validated: false`` / provenance
    ``default``; ``/effective`` says plainly whether the engine is consuming it.

Skipped unless DATABASE_URL is Postgres at schema head (``alembic upgrade head``). Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/matlib_test \\
        .venv/bin/python -m pytest tests/test_material_library_api.py -q
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

    from src.api.material_library import router as material_library_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(material_library_router, prefix="/api/v1/material-library")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


@_requires_pg
@pytest.mark.asyncio
async def test_material_library_lifecycle_isolation_and_honesty(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    monkeypatch.setenv("MATERIAL_LIBRARY_ENABLED", "1")

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())

    async def _mk_user(s, label):
        email = f"ml-{tag}-{label}@example.com"
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
        # --- org A: create a draft with a real material_prices catalog -------
        _act_as(app, uid_a)
        r = await c.post(
            "/api/v1/material-library",
            json={
                "name": "2026 Q3 materials",
                "payload": {
                    "material_prices": {"PA12 (Nylon 12)": 24.0},
                    "materials": {},
                },
            },
        )
        assert r.status_code == 200, r.text
        v1 = r.json()
        assert v1["version"] == 1 and v1["status"] == "draft"
        assert v1["validated"] is False and v1["provenance"] == "default"
        v1_id = v1["id"]

        # engine is NOT yet overlaying anything (only a draft exists)
        r = await c.get("/api/v1/material-library/effective")
        assert r.status_code == 200
        assert r.json()["using_governed"] is False
        assert r.json()["source"] == "base_rate_table_material_prices"

        # --- edit the draft then publish -------------------------------------
        r = await c.patch(
            f"/api/v1/material-library/{v1_id}",
            json={"payload": {"material_prices": {"PA12 (Nylon 12)": 26.5}}},
        )
        assert r.status_code == 200, r.text

        # a negative price is rejected at the API (400)
        r = await c.patch(
            f"/api/v1/material-library/{v1_id}",
            json={"payload": {"material_prices": {"@polymer": -1.0}}},
        )
        assert r.status_code == 400

        r = await c.post(f"/api/v1/material-library/{v1_id}/publish", json={})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "published"
        assert r.json()["effective_from"] is not None

        # now the engine overlays it
        r = await c.get("/api/v1/material-library/effective")
        body = r.json()
        assert body["using_governed"] is True
        assert body["source"] == "governed_material_catalog"
        assert body["validated"] is False
        assert body["payload"]["material_prices"]["PA12 (Nylon 12)"] == 26.5

        # --- publish v2 closes v1's effective_to (effective-dating) ----------
        r = await c.post(
            "/api/v1/material-library", json={"from_version_id": v1_id}
        )
        v2_id = r.json()["id"]
        assert r.json()["version"] == 2
        r = await c.post(f"/api/v1/material-library/{v2_id}/publish", json={})
        assert r.status_code == 200, r.text

        r = await c.get("/api/v1/material-library")
        versions = {v["version"]: v for v in r.json()["versions"]}
        assert versions[1]["effective_to"] is not None  # v1 closed
        assert versions[2]["effective_to"] is None       # v2 open

        # re-publishing an already-published version is a 409
        r = await c.post(f"/api/v1/material-library/{v1_id}/publish", json={})
        assert r.status_code == 409

        # --- cross-tenant isolation ------------------------------------------
        _act_as(app, uid_b)
        # org B cannot GET org A's version
        r = await c.get(f"/api/v1/material-library/{v2_id}")
        assert r.status_code == 404
        # org B cannot publish org A's version
        r = await c.post(f"/api/v1/material-library/{v1_id}/publish", json={})
        assert r.status_code == 404
        # org B's own list is empty (never sees A's catalogs)
        r = await c.get("/api/v1/material-library")
        assert r.json()["versions"] == []
        # org B's engine still uses the base table (A's catalog never leaks over)
        r = await c.get("/api/v1/material-library/effective")
        assert r.json()["using_governed"] is False

    # --- cleanup -------------------------------------------------------------
    async with eng.get_session_factory()() as s:
        await s.execute(
            text("DELETE FROM material_library_versions WHERE org_id IN (:a, :b)"),
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
