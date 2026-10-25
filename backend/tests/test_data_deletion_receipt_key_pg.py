"""A deletion receipt read through an API key stays in the key's org (R2, minor).

``GET /api/v1/data-deletions/{id}`` answers the requester, or an admin of the
receipt's org. A bearer API key is bound to the org that issued it, so through
a key only that org's receipts answer; another org's is the same 404, even one
the key's owner asked for or administers there. A dashboard session keeps both.

Skipped unless DATABASE_URL points at Postgres migrated to head.
"""
from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("RATE_LIMIT_DISABLED", "1")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").startswith("postgresql"), reason="needs Postgres"
    ),
]


def _app(user):
    from fastapi import FastAPI

    from src.api.data_control import router
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import require_api_key

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_api_key] = lambda: user
    return app


async def test_a_key_reads_only_its_own_orgs_receipts():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.auth.require_api_key import AuthedUser
    from src.db.models import DataDeletion

    tag = uuid.uuid4().hex[:8]
    org_a, org_b = str(ULID()), str(ULID())
    async with eng.get_session_factory()() as s:
        for oid in (org_a, org_b):
            await s.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:i, :n, :s)"),
                            {"i": oid, "n": f"Del {tag}", "s": f"del-{oid.lower()}"})
        uid = int((await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider, current_org_id) "
            "VALUES (:e, :e, 'analyst', 'password', :o) RETURNING id"),
            {"e": f"del-{tag}@example.com", "o": org_a})).scalar_one())
        for oid in (org_a, org_b):
            await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role) VALUES (:i, :o, :u, 'admin')"),
                            {"i": str(ULID()), "o": oid, "u": uid})
        in_a = DataDeletion(scope="part", org_id=org_a, target="a" * 64, requested_by=uid)
        in_b = DataDeletion(scope="part", org_id=org_b, target="b" * 64, requested_by=uid)
        s.add_all([in_a, in_b])
        await s.commit()
        a_id, b_id = in_a.ulid, in_b.ulid

    key_a = AuthedUser(user_id=uid, api_key_id=7, key_prefix="cv_key_a", role="analyst", org_id=org_a)
    session = AuthedUser(user_id=uid, api_key_id=0, key_prefix="session", role="analyst")
    try:
        async with AsyncClient(transport=ASGITransport(app=_app(key_a)), base_url="http://t") as ac:
            assert (await ac.get(f"/api/v1/data-deletions/{a_id}")).status_code == 200
            other = await ac.get(f"/api/v1/data-deletions/{b_id}")
            assert other.status_code == 404, other.text
            assert other.json()["detail"] == "Deletion not found"
        async with AsyncClient(transport=ASGITransport(app=_app(session)), base_url="http://t") as ac:
            # The person's own dashboard session still reads both of their receipts.
            assert (await ac.get(f"/api/v1/data-deletions/{a_id}")).status_code == 200
            assert (await ac.get(f"/api/v1/data-deletions/{b_id}")).status_code == 200
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM data_deletions WHERE org_id IN (:a, :b)"), {"a": org_a, "b": org_b})
            await s.execute(text("DELETE FROM organizations WHERE id IN (:a, :b)"), {"a": org_a, "b": org_b})
            await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
            await s.commit()
        await eng.dispose_engine()
