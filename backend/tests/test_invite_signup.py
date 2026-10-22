"""Signing up from an invite (live Postgres): the landing page's facts, the join.

it-19 / it-17: the invite link names the org, the inviter and the role before
sign-in; joining makes that org active; and the invitee doesn't also "own" a
company-named org: the personal org sign-up made is "<First name>'s workspace".
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from ulid import ULID

from src.auth.require_api_key import AuthedUser, require_api_key

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


@pytest.fixture(autouse=True)
def _engine():
    import src.db.engine as eng

    eng._ENGINE = None
    eng._SESSION_FACTORY = None
    yield eng
    eng._ENGINE = None
    eng._SESSION_FACTORY = None


def _app(user_id: int | None) -> FastAPI:
    from src.api.org_routes import router as org_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(org_router, prefix="/api/v1/orgs")
    if user_id is not None:
        app.dependency_overrides[require_api_key] = lambda: AuthedUser(
            user_id=user_id, api_key_id=0, key_prefix="session", role="analyst"
        )
    return app


async def _q(sql: str, **params):
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        result = await s.execute(text(sql), params)
        rows = result.all() if result.returns_rows else []
        await s.commit()
    return rows


async def _cleanup(user_ids: list[int], org_ids: list[str]) -> None:
    rows = await _q("SELECT DISTINCT org_id FROM memberships WHERE user_id = ANY(:u)", u=user_ids)
    orgs = list({*org_ids, *[r[0] for r in rows]})
    await _q("DELETE FROM org_invites WHERE org_id = ANY(:o)", o=orgs)
    await _q("DELETE FROM audit_log WHERE user_id = ANY(:u) OR org_id = ANY(:o)", u=user_ids, o=orgs)
    await _q("DELETE FROM api_keys WHERE user_id = ANY(:u)", u=user_ids)
    await _q("DELETE FROM memberships WHERE user_id = ANY(:u)", u=user_ids)
    await _q("DELETE FROM users WHERE id = ANY(:u)", u=user_ids)
    await _q("DELETE FROM organizations WHERE id = ANY(:o)", o=orgs)


@_requires_pg
@pytest.mark.asyncio
async def test_signing_up_from_an_invite_joins_that_org_and_keeps_no_company_named_org(_engine):
    from src.auth.models import create_password_user

    tag = uuid.uuid4().hex[:8]
    domain = f"kestrel{tag}-parts.com"
    org = str(ULID())
    users: list[int] = []
    try:
        await _q(
            "INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :s, now())",
            id=org, n="Kestrel Aero Components, Inc.", s=f"kestrel-{tag}",
        )
        rows = await _q(
            "INSERT INTO users (email, email_lower, auth_provider, full_name, current_org_id) "
            "VALUES (:e, :e, 'password', 'Sam Okafor', :o) RETURNING id",
            e=f"sam@{domain}", o=org,
        )
        sam = int(rows[0][0])
        users.append(sam)
        await _q(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) VALUES (:i, :o, :u, 'admin', now())",
            i=str(ULID()), o=org, u=sam,
        )
        async with AsyncClient(transport=ASGITransport(app=_app(sam)), base_url="http://t") as admin:
            await admin.post("/api/v1/orgs/switch", json={"org_id": org})
            made = await admin.post("/api/v1/orgs/invites", json={"email": f"dana@{domain}", "role": "viewer"})
            assert made.status_code == 201, made.text
            token = made.json()["accept_link"].split("token=")[1]

        # Before sign-in: the link names the org, the inviter and the role.
        async with AsyncClient(transport=ASGITransport(app=_app(None)), base_url="http://t") as anon:
            r = await anon.post("/api/v1/orgs/invites/summary", json={"token": token})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["org_name"] == "Kestrel Aero Components, Inc."
            assert body["role"] == "viewer" and body["email"] == f"dana@{domain}"
            assert body["invited_by_name"] == "Sam Okafor"
            # The link is public: it names the inviter, never the inviter's address.
            assert set(body) == {"org_name", "role", "email", "invited_by_name", "expires_at"}
            assert f"sam@{domain}" not in r.text
            assert r.headers["cache-control"] == "no-store"
            assert (await anon.post("/api/v1/orgs/invites/summary", json={"token": "nope"})).status_code == 404

        # Sign-up gives a personal org named after the company domain...
        dana = await create_password_user(
            email=f"dana@{domain}", email_lower=f"dana@{domain}", password_hash="x", full_name="Dana Reyes"
        )
        users.append(dana)
        personal = await _q("SELECT o.id, o.name FROM organizations o JOIN memberships m ON m.org_id=o.id WHERE m.user_id=:u", u=dana)
        assert personal[0][1] == f"Kestrel{tag} Parts"
        personal_id = personal[0][0]

        # ...and accepting the invite joins the inviting org, makes it active,
        # and turns that personal org into her own workspace.
        async with AsyncClient(transport=ASGITransport(app=_app(dana)), base_url="http://t") as invitee:
            r = await invitee.post("/api/v1/orgs/invites/accept", json={"token": token})
            assert r.status_code == 200, r.text
            assert r.json() == {"org_id": org, "org_role": "viewer", "created": True}
            listed = (await invitee.get("/api/v1/orgs")).json()
        assert listed["active_org_id"] == org
        names = {o["org_id"]: (o["name"], o["org_role"]) for o in listed["organizations"]}
        assert names[org] == ("Kestrel Aero Components, Inc.", "viewer")
        assert names[personal_id] == ("Dana's workspace", "admin")
        flag = await _q("SELECT is_personal FROM organizations WHERE id=:o", o=personal_id)
        assert flag[0][0] is True

        # A used invite says so, with nothing about the org.
        async with AsyncClient(transport=ASGITransport(app=_app(None)), base_url="http://t") as anon:
            used = await anon.post("/api/v1/orgs/invites/summary", json={"token": token})
            assert used.status_code == 409 and "Kestrel" not in used.text
    finally:
        await _cleanup(users, [org])
        await _engine.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_a_personal_org_the_person_renamed_or_shares_is_left_alone(_engine):
    from src.services import org_service as svc

    tag = uuid.uuid4().hex[:8]
    users: list[int] = []
    orgs: list[str] = []
    try:
        team, mine = str(ULID()), str(ULID())
        orgs += [team, mine]
        for oid, name, personal in ((team, f"Team {tag}", False), (mine, "Lee's lab", True)):
            await _q(
                "INSERT INTO organizations (id, name, slug, is_personal, created_at) VALUES (:id, :n, :s, :p, now())",
                id=oid, n=name, s=f"o-{oid}".lower(), p=personal,
            )
        rows = await _q(
            "INSERT INTO users (email, email_lower, auth_provider, full_name) VALUES (:e, :e, 'password', 'Lee Park') RETURNING id",
            e=f"lee@acme{tag}.com",
        )
        lee = int(rows[0][0])
        users.append(lee)
        await _q(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) VALUES (:i, :o, :u, 'admin', now())",
            i=str(ULID()), o=mine, u=lee,
        )
        import src.db.engine as eng

        async with eng.get_session_factory()() as s:
            user = await s.get(svc.User, lee)
            await svc._settle_personal_workspace(s, user, team)
            await s.commit()
        assert (await _q("SELECT name FROM organizations WHERE id=:o", o=mine))[0][0] == "Lee's lab"
        assert svc.workspace_name("lee@acme.com", "Lee Park") == "Lee's workspace"
        assert svc.workspace_name("lee.park@acme.com", None) == "lee.park's workspace"
    finally:
        await _cleanup(users, orgs)
        await _engine.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_an_invite_summary_names_no_member_address_and_only_a_pending_invite_answers(_engine):
    """Anyone holding the link reads its summary without signing in, so it says
    the org, the role, the inviter's name, the invited address and the expiry,
    and nothing else: no inviter or member address, and nothing at all for an
    unknown, revoked, used or expired invite."""
    from src.services.org_service import generate_invite_token

    tag = uuid.uuid4().hex[:8]
    org = str(ULID())
    users: list[int] = []
    try:
        await _q("INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :s, now())",
                 id=org, n=f"Harbor Fab {tag}", s=f"harbor-{tag}")
        for who, name, role in (("ana", "Ana Ruiz", "admin"), ("ben", None, "member")):
            rows = await _q(
                "INSERT INTO users (email, email_lower, auth_provider, full_name, current_org_id) "
                "VALUES (:e, :e, 'password', :n, :o) RETURNING id",
                e=f"{who}@harbor{tag}.com", n=name, o=org)
            users.append(int(rows[0][0]))
            await _q("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                     "VALUES (:i, :o, :u, :r, now())", i=str(ULID()), o=org, u=users[-1], r=role)
        ana, ben = users
        tokens = {}
        for state, by, when, revoked in (
            ("pending", ana, "now() + interval '7 days'", None),
            ("nameless", ben, "now() + interval '7 days'", None),
            ("revoked", ana, "now() + interval '7 days'", "now()"),
            ("expired", ana, "now() - interval '1 minute'", None),
        ):
            raw, token_hash = generate_invite_token()
            tokens[state] = raw
            await _q(
                "INSERT INTO org_invites (org_id, email, role, token_hash, created_by, expires_at, revoked_at, created_at) "
                f"VALUES (:o, :e, 'member', :h, :b, {when}, {revoked or 'NULL'}, now())",
                o=org, e=f"new-{state}@elsewhere{tag}.com", h=token_hash, b=by)

        async with AsyncClient(transport=ASGITransport(app=_app(None)), base_url="http://t") as anon:
            r = await anon.post("/api/v1/orgs/invites/summary", json={"token": tokens["pending"]})
            assert r.status_code == 200, r.text
            assert r.json()["org_name"] == f"Harbor Fab {tag}" and r.json()["invited_by_name"] == "Ana Ruiz"
            assert r.json()["email"] == f"new-pending@elsewhere{tag}.com"
            # An inviter with no name is just not named: their address doesn't stand in.
            nameless = await anon.post("/api/v1/orgs/invites/summary", json={"token": tokens["nameless"]})
            assert nameless.status_code == 200 and nameless.json()["invited_by_name"] is None
            for res in (r, nameless):
                assert set(res.json()) == {"org_name", "role", "email", "invited_by_name", "expires_at"}
                assert f"harbor{tag}.com" not in res.text and "new-revoked" not in res.text
            for state, status in (("revoked", 409), ("expired", 409)):
                res = await anon.post("/api/v1/orgs/invites/summary", json={"token": tokens[state]})
                assert res.status_code == status, (state, res.text)
                assert "Harbor" not in res.text and "@" not in res.text and "Ana" not in res.text
            for bad in (tokens["pending"][:-1], tokens["pending"] + "x", "x" * 43):
                res = await anon.post("/api/v1/orgs/invites/summary", json={"token": bad})
                assert res.status_code == 404 and "Harbor" not in res.text
            assert (await anon.post("/api/v1/orgs/invites/summary", json={"token": "  "})).status_code == 400
    finally:
        await _cleanup(users, [org])
        await _engine.dispose_engine()


def test_the_invite_summary_is_rate_limited_per_visitor(monkeypatch):
    """30 a minute from one address, then 429 (the token itself is 256 random bits)."""
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    import src.auth.rate_limit as rl
    from src.db.engine import get_db_session
    from src.services import org_service

    monkeypatch.setenv("REDIS_URL", "memory://")
    monkeypatch.setattr(rl.limiter, "enabled", True)
    rl.limiter.reset()

    async def _unknown(_session, _token):
        raise HTTPException(status_code=404, detail="Invite not found or already used.")

    monkeypatch.setattr(org_service, "invite_summary", _unknown)
    app = _app(None)
    app.add_exception_handler(RateLimitExceeded, rl.rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.dependency_overrides[get_db_session] = lambda: None
    try:
        client = TestClient(app)
        for _ in range(30):
            assert client.post("/api/v1/orgs/invites/summary", json={"token": "guess"}).status_code == 404
        r = client.post("/api/v1/orgs/invites/summary", json={"token": "guess"})
        assert r.status_code == 429 and r.headers.get("Retry-After")
    finally:
        rl.limiter.reset()
