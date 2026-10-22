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
            assert body["invited_by"] == f"sam@{domain}" and body["invited_by_name"] == "Sam Okafor"
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
