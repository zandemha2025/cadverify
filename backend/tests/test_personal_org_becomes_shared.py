"""A personal org becomes shared when a second member joins (0060 follow-up).

Every account gets a personal org at sign-up (``organizations.is_personal``).
A company that starts in one person's account and invites the team never makes
a second org, so if the flag stayed true the team's org could never use SSO
group mappings or SCIM (both refuse a personal org). When an invite brings in
the second member, the org is the team's: ``is_personal`` turns false, in the
same transaction, with an ``org.became_shared`` audit row. An org that is still
solo stays personal.

Live Postgres, real routes and services; only the auth principal is stubbed.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from ulid import ULID

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)")


async def _mk_user(s, tag, label):
    email = f"pos-{tag}-{label}@example.com"
    return int((await s.execute(text(
        "INSERT INTO users (email, email_lower, role, auth_provider) "
        "VALUES (:e, :e, 'analyst', 'password') RETURNING id"), {"e": email})).first()[0])


async def _mk_personal_org(s, tag, label, owner):
    oid = str(ULID())
    await s.execute(text(
        "INSERT INTO organizations (id, name, slug, is_personal, created_at) "
        "VALUES (:id, :n, :sl, true, now())"), {"id": oid, "n": f"{label} {tag}", "sl": f"pos-{tag}-{label.lower()}"})
    await s.execute(text(
        "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
        "VALUES (:id, :o, :u, 'admin', now())"), {"id": str(ULID()), "o": oid, "u": owner})
    await s.execute(text("UPDATE users SET current_org_id = :o WHERE id = :u"), {"o": oid, "u": owner})
    return oid


async def _is_personal(eng, org_id):
    async with eng.get_session_factory()() as s:
        return (await s.execute(text("SELECT is_personal FROM organizations WHERE id = :o"), {"o": org_id})).scalar_one()


def _act_as(app, user_id):
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst")


async def _scim_org(eng, org_id):
    """The SCIM gate for an admin key issued in ``org_id``."""
    from src.api.scim import _org_id
    from src.auth.rbac import OrgAuthContext

    ctx = OrgAuthContext(user_id=0, api_key_id=0, key_prefix="k", role="analyst", is_superadmin=False,
                         org_id=org_id, org_role="admin")
    async with eng.get_session_factory()() as s:
        return await _org_id(ctx, s)


async def _map_group(eng, org_id, owner):
    from src.services.org_saml_service import create_saml_group_mapping

    async with eng.get_session_factory()() as s:
        row = await create_saml_group_mapping(
            s, org_id, attribute_name="groups", group_value=f"eng-{org_id[-6:]}", org_role="member", created_by=owner)
        await s.rollback()
        return row


@_requires_pg
@pytest.mark.asyncio
async def test_a_second_member_joining_by_invite_makes_the_org_shared_and_it_is_audited(monkeypatch):
    from fastapi import FastAPI, HTTPException
    from httpx import ASGITransport, AsyncClient

    import src.db.engine as eng
    from src.api.org_routes import router as org_router
    from src.auth.rate_limit import limiter

    tag = uuid.uuid4().hex[:10]
    async with eng.get_session_factory()() as s:
        dana = await _mk_user(s, tag, "dana")
        sam = await _mk_user(s, tag, "sam")
        team = await _mk_personal_org(s, tag, "Northfield", dana)
        sams_own = await _mk_personal_org(s, tag, "Sam", sam)
        await s.commit()
    monkeypatch.setenv("SSO_ORG_ID", team)
    try:
        # Solo: SCIM and SSO group mapping are refused for a personal org.
        with pytest.raises(HTTPException) as e:
            await _scim_org(eng, team)
        assert e.value.detail["code"] == "scim_org_required"
        with pytest.raises(HTTPException) as e:
            await _map_group(eng, team, dana)
        assert e.value.detail["code"] == "sso_org_required"

        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(org_router, prefix="/api/v1/orgs")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            _act_as(app, dana)
            r = await ac.post("/api/v1/orgs/invites", json={"email": f"pos-{tag}-sam@example.com", "role": "member"})
            assert r.status_code == 201, r.text
            raw = r.json()["accept_link"].split("token=")[1]
            # Inviting alone changes nothing: the org is still Dana's alone.
            assert await _is_personal(eng, team) is True

            _act_as(app, sam)
            r = await ac.post("/api/v1/orgs/invites/accept", json={"token": raw})
            assert r.status_code == 200 and r.json()["created"] is True, r.text

        assert await _is_personal(eng, team) is False
        # Sam's own org still has only Sam in it: it stays personal.
        assert await _is_personal(eng, sams_own) is True
        async with eng.get_session_factory()() as s:
            rows = (await s.execute(text(
                "SELECT user_id, resource_type, resource_id, detail_json FROM audit_log "
                "WHERE org_id = :o AND action = 'org.became_shared'"), {"o": team})).all()
        assert len(rows) == 1
        user_id, rtype, rid, detail = rows[0]
        assert (user_id, rtype, rid) == (sam, "org", team)
        assert detail["members"] == 2 and detail["via"] == "invite" and detail["org_id"] == team

        # Shared now: SCIM and SSO group mapping are allowed for it.
        assert await _scim_org(eng, team) == team
        assert (await _map_group(eng, team, dana)).org_id == team
    finally:
        async with eng.get_session_factory()() as s:
            for tbl in ("org_invites", "saml_group_mappings"):
                await s.execute(text(f"DELETE FROM {tbl} WHERE org_id IN (:a, :b)"), {"a": team, "b": sams_own})
            await s.execute(text("DELETE FROM audit_log WHERE user_id IN (:a, :b) OR org_id IN (:o, :p)"),
                            {"a": dana, "b": sam, "o": team, "p": sams_own})
            await s.execute(text("DELETE FROM memberships WHERE user_id IN (:a, :b)"), {"a": dana, "b": sam})
            await s.execute(text("UPDATE users SET current_org_id = NULL WHERE id IN (:a, :b)"), {"a": dana, "b": sam})
            await s.execute(text("DELETE FROM organizations WHERE id IN (:a, :b)"), {"a": team, "b": sams_own})
            await s.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": dana, "b": sam})
            await s.commit()
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_an_org_that_is_still_solo_stays_personal():
    import src.db.engine as eng
    from src.services import org_service as svc

    tag = uuid.uuid4().hex[:10]
    async with eng.get_session_factory()() as s:
        dana = await _mk_user(s, tag, "dana")
        solo = await _mk_personal_org(s, tag, "Solo", dana)
        await s.commit()
    try:
        async with eng.get_session_factory()() as s:
            # Dana re-accepting an invite into her own org adds nobody.
            _inv, raw = await svc.create_invite(s, solo, "admin", f"pos-{tag}-dana@example.com", "member", dana)
            _m, _i, created = await svc.accept_invite(s, dana, raw)
            await s.commit()
            assert created is False
            assert await svc.share_org_if_team(s, solo, dana) is False
        assert await _is_personal(eng, solo) is True
        async with eng.get_session_factory()() as s:
            n = (await s.execute(text(
                "SELECT count(*) FROM audit_log WHERE org_id = :o AND action = 'org.became_shared'"),
                {"o": solo})).scalar_one()
        assert n == 0
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM org_invites WHERE org_id = :o"), {"o": solo})
            await s.execute(text("DELETE FROM audit_log WHERE user_id = :a OR org_id = :o"), {"a": dana, "o": solo})
            await s.execute(text("DELETE FROM memberships WHERE user_id = :a"), {"a": dana})
            await s.execute(text("UPDATE users SET current_org_id = NULL WHERE id = :a"), {"a": dana})
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": solo})
            await s.execute(text("DELETE FROM users WHERE id = :a"), {"a": dana})
            await s.commit()
        await eng.dispose_engine()
