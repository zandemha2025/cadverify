"""Bearer keys on real routes (live Postgres): scope, expiry, viewers, refusal log.

The real ``require_api_key`` authenticates every request here (no auth
override), so this covers the path an integration takes.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from ulid import ULID

from src.auth.hashing import hmac_index, mint_token
from src.auth.require_api_key import AuthedUser, require_api_key

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


class _Shop:
    def __init__(self) -> None:
        self.tag = uuid.uuid4().hex[:10]
        self.org = str(ULID())
        self.users: dict[str, int] = {}

    async def make(self) -> "_Shop":
        await _pg(
            "INSERT INTO organizations (id, name, slug, created_at) VALUES ($1, $2, $3, now())",
            self.org,
            f"Kestrel {self.tag}",
            f"kestrel-{self.tag}",
        )
        for who, role in (("viewer", "viewer"), ("member", "member")):
            rows = await _pg(
                "INSERT INTO users (email, email_lower, auth_provider, current_org_id) "
                "VALUES ($1, $1, 'password', $2) RETURNING id",
                f"{who}-{self.tag}@kestrel.example",
                self.org,
            )
            self.users[who] = int(rows[0]["id"])
            await _pg(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                "VALUES ($1, $2, $3, $4, now())",
                str(ULID()),
                self.org,
                self.users[who],
                role,
            )
        return self

    async def key(self, who: str, scope: str | None, expires_at: datetime | None = None) -> str:
        token, prefix, secret_hash = mint_token()
        await _pg(
            "INSERT INTO api_keys (user_id, org_id, name, prefix, hmac_index, secret_hash, scope, expires_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            self.users[who],
            self.org,
            f"{who} key",
            prefix,
            hmac_index(token),
            secret_hash,
            scope,
            expires_at,
        )
        return token

    async def refusals(self) -> list[dict]:
        rows = await _pg(
            "SELECT user_id, result_summary, detail_json FROM audit_log "
            "WHERE org_id=$1 AND action='access.refused' ORDER BY id",
            self.org,
        )
        return [
            {"user_id": int(r["user_id"]), "summary": r["result_summary"], **json.loads(r["detail_json"])}
            for r in rows
        ]

    async def cleanup(self) -> None:
        ids = list(self.users.values())
        await _pg("DELETE FROM machine_instances WHERE org_id=$1", self.org)
        await _pg("DELETE FROM audit_log WHERE org_id=$1", self.org)
        await _pg("DELETE FROM api_keys WHERE user_id = ANY($1::bigint[])", ids)
        await _pg("DELETE FROM memberships WHERE org_id=$1", self.org)
        await _pg("DELETE FROM users WHERE id = ANY($1::bigint[])", ids)
        await _pg("DELETE FROM organizations WHERE id=$1", self.org)


@pytest_asyncio.fixture
async def shop(_engine, monkeypatch):
    monkeypatch.setattr("src.auth.require_api_key.touch_last_used", AsyncMock())
    s = await _Shop().make()
    try:
        yield s
    finally:
        await s.cleanup()
        await _engine.dispose_engine()


def _app(engine, *, as_user: AuthedUser | None = None) -> FastAPI:
    from src.api import machine_inventory
    from src.db.engine import get_db_session

    app = FastAPI()
    app.include_router(machine_inventory.router, prefix="/api/v1/machine-inventory")

    async def _session():
        async with engine.get_session_factory()() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db_session] = _session
    if as_user is not None:
        app.dependency_overrides[require_api_key] = lambda: as_user
    return app


def _client(app: FastAPI, token: str | None = None) -> AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=headers)


_MACHINE = {"name": "Mill", "process": "cnc_3axis"}


@_requires_pg
@pytest.mark.asyncio
async def test_a_read_only_key_reads_but_every_write_is_refused_and_logged(shop, _engine):
    token = await shop.key("member", "read")
    async with _client(_app(_engine), token) as c:
        assert (await c.get("/api/v1/machine-inventory")).status_code == 200
        refused = await c.post("/api/v1/machine-inventory", json=_MACHINE)
        assert refused.status_code == 403
        detail = refused.json()["detail"]
        assert detail["code"] == "api_key_read_only"
        assert detail["message"].startswith("This API key is read only")
        # PATCH and DELETE are writes too, whatever the route.
        assert (await c.patch("/api/v1/machine-inventory/1", json={"name": "x"})).status_code == 403
        # A retry within the minute is refused but not logged again.
        assert (await c.post("/api/v1/machine-inventory", json=_MACHINE)).status_code == 403
    rows = await _pg("SELECT count(*) AS n FROM machine_instances WHERE org_id=$1", shop.org)
    assert int(rows[0]["n"]) == 0
    logged = await shop.refusals()
    posts = [r for r in logged if r["method"] == "POST"]
    assert len(posts) == 1
    assert posts[0]["summary"] == "Refused: change the shop's machines"
    assert posts[0]["user_id"] == shop.users["member"]
    assert posts[0]["org_role"] == "member" and posts[0]["via"] == "api_key"
    assert posts[0]["reason"] == "api_key_read_only"


@_requires_pg
@pytest.mark.asyncio
async def test_a_read_and_write_key_writes_and_a_key_from_before_scopes_still_does(shop, _engine):
    for scope in ("read_write", None):
        token = await shop.key("member", scope)
        async with _client(_app(_engine), token) as c:
            made = await c.post("/api/v1/machine-inventory", json={**_MACHINE, "name": f"Mill {scope}"})
            assert made.status_code in (200, 201), made.text
    rows = await _pg("SELECT count(*) AS n FROM machine_instances WHERE org_id=$1", shop.org)
    assert int(rows[0]["n"]) == 2


@_requires_pg
@pytest.mark.asyncio
async def test_a_viewers_key_never_writes_whatever_its_scope_says(shop, _engine):
    # A key stored as read and write (made before a demotion, or before scopes).
    for scope in ("read_write", None):
        token = await shop.key("viewer", scope)
        async with _client(_app(_engine), token) as c:
            assert (await c.get("/api/v1/machine-inventory")).status_code == 200
            refused = await c.post("/api/v1/machine-inventory", json=_MACHINE)
            assert refused.status_code == 403
            detail = refused.json()["detail"]
            assert detail["code"] == "api_key_read_only"
            assert "belongs to a viewer" in detail["message"]
    logged = await shop.refusals()
    assert logged and all(r["org_role"] == "viewer" for r in logged)


@_requires_pg
@pytest.mark.asyncio
async def test_an_expired_key_gets_401_with_a_plain_message(shop, _engine):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    token = await shop.key("member", "read_write", expires_at=past)
    async with _client(_app(_engine), token) as c:
        r = await c.get("/api/v1/machine-inventory")
    assert r.status_code == 401
    detail = r.json()["detail"]
    assert detail["code"] == "api_key_expired"
    assert detail["message"] == (
        f"This API key expired on {past.strftime('%b')} {past.day}, {past.year}. "
        "Create a new key in Account, API and keys."
    )
    future = datetime.now(timezone.utc) + timedelta(days=1)
    live = await shop.key("member", "read", expires_at=future)
    async with _client(_app(_engine), live) as c:
        assert (await c.get("/api/v1/machine-inventory")).status_code == 200


@_requires_pg
@pytest.mark.asyncio
async def test_a_viewers_refused_write_in_the_app_is_logged_with_role(shop, _engine):
    viewer = AuthedUser(
        user_id=shop.users["viewer"], api_key_id=0, key_prefix="session", role="analyst"
    )
    async with _client(_app(_engine, as_user=viewer)) as c:
        r = await c.post("/api/v1/machine-inventory", json=_MACHINE)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "org_member_required"
        # Reads are never logged as refusals.
        assert (await c.get("/api/v1/machine-inventory")).status_code == 200
    logged = await shop.refusals()
    assert len(logged) == 1
    assert logged[0]["summary"] == "Refused: change the shop's machines"
    assert logged[0]["org_role"] == "viewer" and logged[0]["via"] == "session"
    assert logged[0]["user_id"] == shop.users["viewer"]
