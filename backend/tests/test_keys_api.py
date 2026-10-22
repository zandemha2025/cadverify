"""/api/v1/keys against live Postgres: scope, expiry, org admin governance, secret once.

Each test builds its own organization, people and keys and removes them after.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock
from ulid import ULID

from src.auth import keys_api
from src.auth.dashboard_session import require_dashboard_session

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


async def _pg(sql: str, *args):
    import asyncpg

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@pytest.fixture
def _engine():
    import src.db.engine as eng

    eng._ENGINE = None
    eng._SESSION_FACTORY = None
    yield eng
    eng._ENGINE = None
    eng._SESSION_FACTORY = None


class _Org:
    """One shared org with an admin, a member and a viewer (plus cleanup)."""

    def __init__(self) -> None:
        self.tag = uuid.uuid4().hex[:10]
        self.id = str(ULID())
        self.other_id = str(ULID())
        self.users: dict[str, int] = {}

    async def make(self) -> "_Org":
        for org_id, name in ((self.id, f"Kestrel {self.tag}"), (self.other_id, f"Other {self.tag}")):
            await _pg(
                "INSERT INTO organizations (id, name, slug, created_at) VALUES ($1, $2, $3, now())",
                org_id,
                name,
                f"org-{ULID()}".lower(),
            )
        for who, role in (("admin", "admin"), ("member", "member"), ("viewer", "viewer")):
            await self.person(who, role)
        await self.person("outsider", "admin", org_id=self.other_id)
        return self

    async def person(self, who: str, role: str, org_id: str | None = None) -> int:
        org_id = org_id or self.id
        rows = await _pg(
            "INSERT INTO users (email, email_lower, auth_provider, current_org_id) "
            "VALUES ($1, $1, 'password', $2) RETURNING id",
            f"{who}-{self.tag}@kestrel.example",
            org_id,
        )
        uid = int(rows[0]["id"])
        self.users[who] = uid
        await _pg(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES ($1, $2, $3, $4, now())",
            str(ULID()),
            org_id,
            uid,
            role,
        )
        return uid

    async def cleanup(self) -> None:
        ids = list(self.users.values())
        orgs = [self.id, self.other_id]
        await _pg("DELETE FROM audit_log WHERE org_id = ANY($1::text[])", orgs)
        await _pg("DELETE FROM api_keys WHERE user_id = ANY($1::bigint[])", ids)
        await _pg("DELETE FROM memberships WHERE org_id = ANY($1::text[])", orgs)
        await _pg("DELETE FROM users WHERE id = ANY($1::bigint[])", ids)
        await _pg("DELETE FROM organizations WHERE id = ANY($1::text[])", orgs)


def _client(user_id: int) -> AsyncClient:
    app = FastAPI()
    app.include_router(keys_api.router)

    async def _session() -> int:
        return user_id

    app.dependency_overrides[require_dashboard_session] = _session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest_asyncio.fixture
async def org(_engine):
    o = await _Org().make()
    try:
        yield o
    finally:
        await o.cleanup()
        await _engine.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_create_returns_the_secret_once_with_scope_and_expiry(org):
    async with _client(org.users["member"]) as c:
        r = await c.post("/api/v1/keys", json={"name": "  PLM integration  ", "expires_in_days": 90})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["secret"].startswith(f"cv_live_{body['prefix']}_")
        assert body["name"] == "PLM integration"
        # Read only is the default for everyone.
        assert body["scope"] == body["effective_scope"] == "read"
        expires = datetime.fromisoformat(body["expires_at"])
        assert timedelta(days=89, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=90)
        assert r.headers["cache-control"] == "no-store"
        # The legacy developer page still gets its reveal cookie.
        assert "cv_mint_once=cv_live_" in r.headers["set-cookie"]
        listed = (await c.get("/api/v1/keys")).json()
    assert [k["id"] for k in listed] == [body["id"]]
    assert "secret" not in listed[0] and listed[0]["scope"] == "read" and listed[0]["expired"] is False
    stored = await _pg("SELECT secret_hash, scope FROM api_keys WHERE id=$1", body["id"])
    assert body["secret"] not in stored[0]["secret_hash"] and stored[0]["scope"] == "read"
    audit = await _pg(
        "SELECT detail_json FROM audit_log WHERE action='api_key.created' AND resource_id=$1",
        str(body["id"]),
    )
    assert '"scope": "read"' in audit[0]["detail_json"]


@_requires_pg
@pytest.mark.asyncio
async def test_a_viewer_can_make_only_read_only_keys(org):
    async with _client(org.users["viewer"]) as c:
        refused = await c.post("/api/v1/keys", json={"name": "dana", "scope": "read_write"})
        assert refused.status_code == 403
        assert refused.json()["detail"]["code"] == "api_key_scope_not_allowed"
        made = await c.post("/api/v1/keys", json={"name": "dana", "scope": "read"})
        assert made.status_code == 200 and made.json()["scope"] == "read"
    rows = await _pg("SELECT count(*) AS n FROM api_keys WHERE user_id=$1", org.users["viewer"])
    assert int(rows[0]["n"]) == 1


@_requires_pg
@pytest.mark.asyncio
async def test_bad_scope_or_expiry_is_refused(org):
    async with _client(org.users["member"]) as c:
        assert (await c.post("/api/v1/keys", json={"scope": "admin"})).status_code == 422
        assert (await c.post("/api/v1/keys", json={"expires_in_days": 7})).status_code == 422


@_requires_pg
@pytest.mark.asyncio
async def test_an_org_admin_lists_and_revokes_every_key_in_the_org(org):
    async with _client(org.users["viewer"]) as viewer:
        dana = (await viewer.post("/api/v1/keys", json={"name": "dana test"})).json()
    async with _client(org.users["member"]) as member:
        lee = (await member.post("/api/v1/keys", json={"name": "ERP", "scope": "read_write"})).json()
        # A member sees only their own keys and can't list or revoke others'.
        assert (await member.get("/api/v1/keys/org")).status_code == 403
        assert (await member.delete(f"/api/v1/keys/{dana['id']}")).status_code == 404
    async with _client(org.users["outsider"]) as outsider:
        # An admin of another org can't touch this org's keys.
        assert (await outsider.delete(f"/api/v1/keys/{dana['id']}")).status_code == 404
    async with _client(org.users["admin"]) as admin:
        mine = (await admin.post("/api/v1/keys", json={"name": "Sam"})).json()
        listing = await admin.get("/api/v1/keys/org")
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["org_id"] == org.id and body["org_name"] == f"Kestrel {org.tag}"
        by_id = {k["id"]: k for k in body["keys"]}
        assert set(by_id) == {dana["id"], lee["id"], mine["id"]}
        assert by_id[dana["id"]]["owner_email"] == f"viewer-{org.tag}@kestrel.example"
        assert by_id[dana["id"]]["owner_role"] == "viewer"
        assert by_id[lee["id"]]["owner_role"] == "member" and by_id[lee["id"]]["scope"] == "read_write"
        assert by_id[mine["id"]]["yours"] is True and by_id[dana["id"]]["yours"] is False
        assert all("secret" not in k for k in body["keys"])

        revoked = await admin.delete(f"/api/v1/keys/{dana['id']}")
        assert revoked.status_code == 204
        # The admin can't rotate or rename someone else's key (that would hand
        # the admin a secret that acts as that person).
        assert (await admin.post(f"/api/v1/keys/{lee['id']}/rotate")).status_code == 404
        assert (await admin.patch(f"/api/v1/keys/{lee['id']}", json={"name": "x"})).status_code == 404
    rows = await _pg("SELECT revoked_at FROM api_keys WHERE id=$1", dana["id"])
    assert rows[0]["revoked_at"] is not None
    audit = await _pg(
        "SELECT user_id, detail_json FROM audit_log WHERE action='api_key.revoked' AND resource_id=$1",
        str(dana["id"]),
    )
    assert int(audit[0]["user_id"]) == org.users["admin"]
    assert '"reason": "org_admin_revoked"' in audit[0]["detail_json"]


@_requires_pg
@pytest.mark.asyncio
async def test_rotate_keeps_name_scope_and_lifetime_and_returns_the_new_secret(org):
    async with _client(org.users["member"]) as c:
        made = (await c.post("/api/v1/keys", json={"name": "rotate-me", "scope": "read_write", "expires_in_days": 30})).json()
        rotated = await c.post(f"/api/v1/keys/{made['id']}/rotate")
        assert rotated.status_code == 200, rotated.text
        new = rotated.json()
        assert new["id"] != made["id"] and new["prefix"] != made["prefix"]
        assert new["secret"].startswith(f"cv_live_{new['prefix']}_") and new["secret"] != made["secret"]
        assert new["name"] == "rotate-me" and new["scope"] == "read_write"
        left = datetime.fromisoformat(new["expires_at"]) - datetime.now(timezone.utc)
        assert timedelta(days=29, hours=23) < left <= timedelta(days=30)
        # The old key is revoked and can't be rotated again.
        assert (await c.post(f"/api/v1/keys/{made['id']}/rotate")).status_code == 404
        assert (await c.post("/api/v1/keys/999999999/rotate")).status_code == 404


@_requires_pg
@pytest.mark.asyncio
async def test_rotating_a_demoted_members_key_makes_it_read_only(org):
    async with _client(org.users["member"]) as c:
        made = (await c.post("/api/v1/keys", json={"name": "was member", "scope": "read_write"})).json()
        await _pg(
            "UPDATE memberships SET org_role='viewer' WHERE user_id=$1 AND org_id=$2",
            org.users["member"],
            org.id,
        )
        listed = (await c.get("/api/v1/keys")).json()
        assert listed[0]["scope"] == "read_write" and listed[0]["effective_scope"] == "read"
        rotated = (await c.post(f"/api/v1/keys/{made['id']}/rotate")).json()
    assert rotated["scope"] == rotated["effective_scope"] == "read"


@_requires_pg
@pytest.mark.asyncio
async def test_rename_trims_and_revoke_then_rename_still_names_it(org):
    async with _client(org.users["member"]) as c:
        made = (await c.post("/api/v1/keys", json={"name": "old"})).json()
        renamed = await c.patch(f"/api/v1/keys/{made['id']}", json={"name": "  new  "})
        assert renamed.status_code == 200 and renamed.json()["name"] == "new"
        assert (await c.delete(f"/api/v1/keys/{made['id']}")).status_code == 204
        assert (await c.delete(f"/api/v1/keys/{made['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_rotate_audit_failure_never_commits_revocation(monkeypatch):
    class Result:
        def __init__(self, row):
            self.row = row

        def first(self):
            return self.row

    session = AsyncMock()
    session.execute.side_effect = [
        Result(("rotate-me", "org-1", "oldpref", "read", None)),
        Result(("member",)),
        Result((99,)),
    ]

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return False

    class Factory:
        def __call__(self):
            return SessionContext()

    async def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(keys_api, "_session", lambda: Factory())
    monkeypatch.setattr(keys_api, "append_audit_entry", fail_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await keys_api.rotate_key(7, Response(), user_id=1)

    session.commit.assert_not_awaited()
