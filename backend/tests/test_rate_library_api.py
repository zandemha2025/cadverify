"""Governed rate-library API integration tests (W4 slice 1) against live Postgres.

Drives ``/api/v1/rate-library`` through an ASGI client with only the auth
principal overridden — ``require_role``/``require_org_role`` -> ``require_api_key``,
the real ``get_db_session`` -> ``resolve_org``, and the migration-0013 table all
run against the live DB. Proves:

  * Lifecycle — create draft → edit → publish → resolve the effective card.
  * Effective-dating — publishing v2 closes v1's ``effective_to``; the engine
    resolves the version in effect.
  * Cross-tenant isolation — an org admin can neither read nor publish another
    org's version (asserted by name).
  * Honesty — a governed card is reported ``validated: false`` / provenance
    ``default``; ``/effective`` says plainly whether the engine is consuming it.

Skipped unless DATABASE_URL is Postgres at schema head (``alembic upgrade head``). Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/ratelib_test \\
        .venv/bin/python -m pytest tests/test_rate_library_api.py -q
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

    from src.api.rate_library import router as rate_library_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(rate_library_router, prefix="/api/v1/rate-library")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


@_requires_pg
@pytest.mark.asyncio
async def test_rate_library_lifecycle_isolation_and_honesty(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    monkeypatch.setenv("RATE_LIBRARY_ENABLED", "1")

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())

    async def _mk_user(s, label):
        email = f"rl-{tag}-{label}@example.com"
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
        # --- org A: create a draft -------------------------------------------
        _act_as(app, uid_a)
        r = await c.post("/api/v1/rate-library", json={"name": "2026 Q3"})
        assert r.status_code == 200, r.text
        v1 = r.json()
        assert v1["version"] == 1 and v1["status"] == "draft"
        assert v1["validated"] is False and v1["provenance"] == "default"
        v1_id = v1["id"]

        # engine is NOT yet consuming anything (only a draft exists)
        r = await c.get("/api/v1/rate-library/effective")
        assert r.status_code == 200
        assert r.json()["using_governed"] is False
        assert r.json()["source"] == "default_rate_card_v0"

        # --- edit the draft's labor rate then publish ------------------------
        payload = v1["payload"]
        payload["global"]["labor_rate"] = 55.0
        r = await c.patch(
            f"/api/v1/rate-library/{v1_id}", json={"payload": payload}
        )
        assert r.status_code == 200, r.text

        r = await c.post(f"/api/v1/rate-library/{v1_id}/publish", json={})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "published"
        assert r.json()["effective_from"] is not None

        # now the engine consumes it
        r = await c.get("/api/v1/rate-library/effective")
        body = r.json()
        assert body["using_governed"] is True
        assert body["source"] == "governed_rate_card"
        assert body["validated"] is False
        assert body["payload"]["global"]["labor_rate"] == 55.0

        # --- publish v2 closes v1's effective_to (effective-dating) ----------
        r = await c.post("/api/v1/rate-library", json={"from_version_id": v1_id})
        v2_id = r.json()["id"]
        assert r.json()["version"] == 2
        r = await c.post(f"/api/v1/rate-library/{v2_id}/publish", json={})
        assert r.status_code == 200, r.text

        r = await c.get("/api/v1/rate-library")
        versions = {v["version"]: v for v in r.json()["versions"]}
        assert versions[1]["effective_to"] is not None  # v1 closed
        assert versions[2]["effective_to"] is None       # v2 open

        # re-publishing an already-published version is a 409
        r = await c.post(f"/api/v1/rate-library/{v1_id}/publish", json={})
        assert r.status_code == 409

        # --- cross-tenant isolation ------------------------------------------
        _act_as(app, uid_b)
        # org B cannot GET org A's version
        r = await c.get(f"/api/v1/rate-library/{v2_id}")
        assert r.status_code == 404
        # org B cannot publish org A's version
        r = await c.post(f"/api/v1/rate-library/{v1_id}/publish", json={})
        assert r.status_code == 404
        # org B's own list is empty (never sees A's cards)
        r = await c.get("/api/v1/rate-library")
        assert r.json()["versions"] == []
        # org B's engine still uses the default (A's card never leaks over)
        r = await c.get("/api/v1/rate-library/effective")
        assert r.json()["using_governed"] is False

    # --- cleanup -------------------------------------------------------------
    async with eng.get_session_factory()() as s:
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


@_requires_pg
@pytest.mark.asyncio
async def test_rate_library_governance_discard_archive_diff(monkeypatch):
    """Discard/archive/diff against live Postgres: discard-draft-ok,
    discard-published-409, archive-superseded-ok, archive-in-effect-409, and a
    real cross-tenant-scoped structural diff."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    monkeypatch.setenv("RATE_LIBRARY_ENABLED", "1")

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())

    async def _mk_user(s, label):
        email = f"rlg-{tag}-{label}@example.com"
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
        for oid, nm in ((org_a, f"GA {tag}"), (org_b, f"GB {tag}")):
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
        _act_as(app, uid_a)

        # --- discard a draft: ok -------------------------------------------
        r = await c.post("/api/v1/rate-library", json={"name": "throwaway"})
        assert r.status_code == 200, r.text
        draft_id = r.json()["id"]
        r = await c.delete(f"/api/v1/rate-library/{draft_id}")
        assert r.status_code == 200, r.text
        # gone: 404 on subsequent read
        r = await c.get(f"/api/v1/rate-library/{draft_id}")
        assert r.status_code == 404

        # --- publish v1, then v2 (v1 becomes superseded) --------------------
        r = await c.post("/api/v1/rate-library", json={"name": "v1"})
        v1 = r.json()
        v1_id = v1["id"]
        payload1 = v1["payload"]
        payload1["global"]["labor_rate"] = 35.0
        await c.patch(f"/api/v1/rate-library/{v1_id}", json={"payload": payload1})
        r = await c.post(f"/api/v1/rate-library/{v1_id}/publish", json={})
        assert r.status_code == 200, r.text

        # discarding a PUBLISHED version is a 409 (audit trail)
        r = await c.delete(f"/api/v1/rate-library/{v1_id}")
        assert r.status_code == 409

        r = await c.post("/api/v1/rate-library", json={"from_version_id": v1_id})
        v2 = r.json()
        v2_id = v2["id"]
        payload2 = v2["payload"]
        payload2["global"]["labor_rate"] = 55.0
        await c.patch(f"/api/v1/rate-library/{v2_id}", json={"payload": payload2})

        # archiving v1 (still in effect — v2 not yet published) is a 409
        r = await c.post(f"/api/v1/rate-library/{v1_id}/archive", json={})
        assert r.status_code == 409, r.text

        r = await c.post(f"/api/v1/rate-library/{v2_id}/publish", json={})
        assert r.status_code == 200, r.text  # closes v1's effective_to

        # v1 is now superseded (closed) — archiving it is fine
        r = await c.post(f"/api/v1/rate-library/{v1_id}/archive", json={})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "archived"

        # archiving v2 (currently in effect) is a 409
        r = await c.post(f"/api/v1/rate-library/{v2_id}/archive", json={})
        assert r.status_code == 409

        # an archived version never resolves as effective
        r = await c.get("/api/v1/rate-library/effective")
        assert r.json()["payload"]["global"]["labor_rate"] == 55.0  # v2, not archived v1

        # --- real structural diff between v1 (35.0) and v2 (55.0) ----------
        r = await c.get(f"/api/v1/rate-library/{v1_id}/diff/{v2_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        changed = {c_["path"]: c_ for c_ in body["diff"]["changed"]}
        assert changed["global.labor_rate"] == {
            "path": "global.labor_rate",
            "from": 35.0,
            "to": 55.0,
        }

        # --- cross-tenant isolation on discard/archive/diff -----------------
        _act_as(app, uid_b)
        r = await c.delete(f"/api/v1/rate-library/{v2_id}")
        assert r.status_code == 404
        r = await c.post(f"/api/v1/rate-library/{v2_id}/archive", json={})
        assert r.status_code == 404
        r = await c.get(f"/api/v1/rate-library/{v1_id}/diff/{v2_id}")
        assert r.status_code == 404

    # --- cleanup -------------------------------------------------------------
    async with eng.get_session_factory()() as s:
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
