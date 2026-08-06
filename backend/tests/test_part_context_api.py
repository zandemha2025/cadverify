"""Declared part-context API integration tests (W3.5 rung-1) against live Postgres.

Drives ``/api/v1/part-context`` through an ASGI client with only the auth
principal overridden — ``require_role`` -> ``require_api_key``, the real
``get_db_session`` -> ``resolve_org``, and the migration-0014 table all run
against the live DB. Proves:

  * Upsert-then-read — PUT declares a context, GET returns it (provenance user).
  * Re-declare — a second PUT updates the SAME (org, mesh) row in place.
  * Validation — a non-positive annual_volume is a 400.
  * Cross-tenant isolation — org B's GET of org A's mesh_hash is a 404.

Skipped unless DATABASE_URL is Postgres at schema head (``alembic upgrade head``). Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/ratelib_test \\
        .venv/bin/python -m pytest tests/test_part_context_api.py -q
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

    from src.api.part_context import router as part_context_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(part_context_router, prefix="/api/v1/part-context")
    return app


def _act_as(app, user_id: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
    )


@_requires_pg
@pytest.mark.asyncio
async def test_part_context_upsert_read_and_isolation():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    org_a, org_b = str(ULID()), str(ULID())

    async def _mk_user(s, label):
        email = f"pc-{tag}-{label}@example.com"
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

    mesh = f"mesh-{tag}"

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # --- org A: no context yet -> 404 -----------------------------------
        _act_as(app, uid_a)
        r = await c.get(f"/api/v1/part-context/{mesh}")
        assert r.status_code == 404

        # --- PUT declares a context -----------------------------------------
        r = await c.put(
            f"/api/v1/part-context/{mesh}",
            json={
                "program": "Zoox",
                "parent_assembly": "chassis",
                "units_per_parent": 4,
                "annual_volume": 12000,
                "service_environment": {
                    "max_temp_c": 120,
                    "sour_service": True,
                    "pressure_bar": 350,
                },
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["program"] == "Zoox"
        assert body["annual_volume"] == 12000
        assert body["provenance"] == "user"

        # --- GET returns exactly what was declared --------------------------
        r = await c.get(f"/api/v1/part-context/{mesh}")
        assert r.status_code == 200
        got = r.json()
        assert got["parent_assembly"] == "chassis"
        assert got["units_per_parent"] == 4
        assert got["annual_volume"] == 12000
        assert got["service_environment"]["max_temp_c"] == 120
        assert got["service_environment"]["sour_service"] is True
        assert got["provenance"] == "user"

        # --- re-declare updates supplied fields but preserves omitted context
        #     so Verify can refresh service_environment without erasing lineage.
        r = await c.put(
            f"/api/v1/part-context/{mesh}",
            json={"program": "Zoox-2", "annual_volume": 9000},
        )
        assert r.status_code == 200, r.text
        r = await c.get(f"/api/v1/part-context/{mesh}")
        got = r.json()
        assert got["program"] == "Zoox-2"
        assert got["annual_volume"] == 9000
        assert got["parent_assembly"] == "chassis"
        assert got["units_per_parent"] == 4
        assert got["service_environment"]["pressure_bar"] == 350

        # --- explicit null still clears a declared field --------------------
        r = await c.put(
            f"/api/v1/part-context/{mesh}",
            json={"parent_assembly": None},
        )
        assert r.status_code == 200, r.text
        r = await c.get(f"/api/v1/part-context/{mesh}")
        got = r.json()
        assert got["program"] == "Zoox-2"
        assert got["parent_assembly"] is None
        assert got["units_per_parent"] == 4

        # --- a non-positive declared volume is a 400 ------------------------
        r = await c.put(
            f"/api/v1/part-context/{mesh}", json={"annual_volume": 0}
        )
        assert r.status_code == 400

        # --- cross-tenant isolation -----------------------------------------
        _act_as(app, uid_b)
        # org B cannot read org A's declared context for the same mesh_hash
        r = await c.get(f"/api/v1/part-context/{mesh}")
        assert r.status_code == 404

    # --- cleanup -------------------------------------------------------------
    async with eng.get_session_factory()() as s:
        await s.execute(
            text("DELETE FROM part_contexts WHERE org_id IN (:a, :b)"),
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
    # Release the async engine bound to THIS test's event loop (repo convention —
    # asyncpg pools are loop-bound; the next async PG test rebuilds it).
    await eng.dispose_engine()
