"""Joining an organization by invite (Postgres, migrated to head).

Security review R4 (F2, F4) and R1 (R1-2):

1. Accepting an invite never switches the person's active org by itself. The
   default /orgs/accept page accepted on load; with accept also switching, one
   visit to an admin-minted link moved the person's next upload into the
   inviting org. The org becomes active only when the person asks (``switch``).
2. Joining an org that requires two-step ends a session that never saw a code,
   as turning the rule on does for existing members. Before, only a voluntary
   POST /auth/two-step/step-up ended it, so a client that skipped it (the
   default accept page) kept a codeless session in the org, and could mint a
   365-day key there. Accounts with two-step on, and single sign-on accounts
   (their identity provider owns that step), keep their session.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import text

from tests.test_two_step import (  # noqa: F401  (fixtures + helpers)
    World, _cleanup, _cookie, _enrol, _signup, clock, env, requires_pg,
)


def _app() -> FastAPI:
    from src.api.org_routes import router as org_router
    from src.auth.keys_api import router as keys_router
    from src.auth.password import router as password_router
    from src.auth.rbac import OrgAuthContext, OrgRole, require_org_role
    from src.auth.require_api_key import AuthedUser, require_api_key

    app = FastAPI()
    app.include_router(password_router, prefix="/auth")
    app.include_router(org_router, prefix="/api/v1/orgs")
    app.include_router(keys_router)

    @app.get("/protected")
    async def protected(user: AuthedUser = Depends(require_api_key)):  # noqa: ANN001
        return {"user_id": user.user_id}

    @app.get("/org-data")
    async def org_data(ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer))):  # noqa: ANN001
        # Stand-in for any org-scoped read (parts, rates, records...).
        return {"org_id": ctx.org_id, "role": ctx.org_role}

    return app


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://t")


async def _q(sql: str, **params):
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        result = await s.execute(text(sql), params)
        rows = result.all() if result.returns_rows else []
        await s.commit()
    return rows


async def _current_org(uid: int) -> str | None:
    return (await _q("SELECT current_org_id FROM users WHERE id = :u", u=uid))[0][0]


async def _personal_org(uid: int) -> str:
    return (await _q("SELECT org_id FROM memberships WHERE user_id = :u", u=uid))[0][0]


def _token(link: str) -> str:
    return link.split("token=", 1)[1].split("&", 1)[0]


async def _invite(ac, admin_s: str, email: str, role: str = "member") -> str:
    r = await ac.post("/api/v1/orgs/invites", headers=_cookie(admin_s), json={"email": email, "role": role})
    assert r.status_code == 201, r.text
    return _token(r.json()["accept_link"])


async def _two_step_org(ac, w: World, clock) -> tuple[str, str]:
    """An org whose admin (with two-step on) has turned the rule on: (org_id, admin session)."""
    admin, admin_s = await _signup(ac, w.email("admin"))
    org = await _current_org(admin) or await _personal_org(admin)
    _secret, _codes, admin_s = await _enrol(ac, admin_s, clock)
    r = await ac.put("/auth/two-step/org", headers=_cookie(admin_s), json={"required": True})
    assert r.status_code == 200 and r.json()["required"] is True, r.text
    return org, admin_s


# ── F2: opening an invite link never joins or switches by itself ─────────────
@requires_pg
@pytest.mark.asyncio
async def test_accepting_an_invite_does_not_move_the_person_into_the_inviting_org(env):
    w = World()
    try:
        async with _client() as ac:
            _attacker, attacker_s = await _signup(ac, w.email("attacker"))
            victim, victim_s = await _signup(ac, w.email("victim"))
            own = await _current_org(victim) or await _personal_org(victim)
            token = await _invite(ac, attacker_s, w.email("victim"))
            # What the old /orgs/accept?token=... did as soon as it loaded.
            r = await ac.post("/api/v1/orgs/invites/accept", headers=_cookie(victim_s), json={"token": token})
            assert r.status_code == 200, r.text
            assert r.json()["switched"] is False and r.json()["signed_out"] is False
            assert await _current_org(victim) == own, "the victim's next upload now lands in the attacker's org"
            assert (await ac.get("/org-data", headers=_cookie(victim_s))).json()["org_id"] == own
    finally:
        await _cleanup(w)


@requires_pg
@pytest.mark.asyncio
async def test_the_org_becomes_active_only_when_the_person_asks(env):
    w = World()
    try:
        async with _client() as ac:
            admin, admin_s = await _signup(ac, w.email("admin"))
            team = await _current_org(admin) or await _personal_org(admin)
            dana, dana_s = await _signup(ac, w.email("dana"))
            token = await _invite(ac, admin_s, w.email("dana"), role="viewer")
            r = await ac.post("/api/v1/orgs/invites/accept", headers=_cookie(dana_s), json={"token": token, "switch": True})
            assert r.status_code == 200, r.text
            assert r.json() == {"org_id": team, "org_role": "viewer", "created": True, "switched": True, "signed_out": False}
            assert await _current_org(dana) == team
            assert (await ac.get("/org-data", headers=_cookie(dana_s))).json() == {"org_id": team, "role": "viewer"}
            actions = [a for (a,) in await _q("SELECT action FROM audit_log WHERE user_id = :u ORDER BY id", u=dana)]
            assert "member.joined" in actions and "org.switched" in actions
            # Round 13: the second member makes the admin's personal org the team's.
            assert (await _q("SELECT is_personal FROM organizations WHERE id = :o", o=team))[0][0] is False
    finally:
        await _cleanup(w)


@requires_pg
@pytest.mark.asyncio
async def test_an_api_key_cannot_switch_orgs_by_accepting(env):
    w = World()
    try:
        async with _client() as ac:
            _admin, admin_s = await _signup(ac, w.email("admin"))
            sam, sam_s = await _signup(ac, w.email("sam"))
            key = (await ac.post("/api/v1/keys", headers=_cookie(sam_s), json={"name": "ci", "scope": "read_write"})).json()["secret"]
            token = await _invite(ac, admin_s, w.email("sam"))
            own = await _current_org(sam) or await _personal_org(sam)
            r = await ac.post("/api/v1/orgs/invites/accept", headers={"Authorization": f"Bearer {key}"}, json={"token": token, "switch": True})
            assert r.status_code == 403 and r.json()["detail"]["code"] == "api_key_org_bound", r.text
            assert await _current_org(sam) == own
            # Nothing half-done: the invite is still pending.
            r = await ac.post("/api/v1/orgs/invites/summary", json={"token": token})
            assert r.status_code == 200, r.text
    finally:
        await _cleanup(w)


# ── F4 / R1-2: joining a two-step org ends a password-only session ──────────
@requires_pg
@pytest.mark.asyncio
async def test_joining_an_org_that_requires_two_step_ends_a_password_only_session(env, clock):
    w = World()
    try:
        async with _client() as ac:
            org, admin_s = await _two_step_org(ac, w, clock)
            late, late_s = await _signup(ac, w.email("late"))
            token = await _invite(ac, admin_s, w.email("late"))
            r = await ac.post("/api/v1/orgs/invites/accept", headers=_cookie(late_s), json={"token": token, "switch": True})
            assert r.status_code == 200, r.text
            assert r.json()["org_id"] == org and r.json()["signed_out"] is True and r.json()["switched"] is True
            # No step-up call (a client that skips it, or the sign-up proxy's step-up timing out).
            assert (await ac.get("/protected", headers=_cookie(late_s))).status_code == 401, \
                "a member without two-step keeps a working session in an org that requires it"
            assert (await ac.get("/org-data", headers=_cookie(late_s))).status_code == 401
            # The next sign-in asks them to set it up, then lands in the org they chose.
            r = await ac.post("/auth/login", json={"email": w.email("late"), "password": "Passw0rd-two-step-1"})
            assert r.status_code == 200 and r.json()["two_step"] == "setup" and "session" not in r.json(), r.text
            assert await _current_org(late) == org
            actions = [a for (a,) in await _q("SELECT action FROM audit_log WHERE user_id = :u ORDER BY id", u=late)]
            assert "user.sessions_revoked" in actions
    finally:
        await _cleanup(w)


@requires_pg
@pytest.mark.asyncio
async def test_a_codeless_session_in_a_two_step_org_cannot_mint_a_long_lived_key(env, clock):
    w = World()
    try:
        async with _client() as ac:
            _org, admin_s = await _two_step_org(ac, w, clock)
            _late, late_s = await _signup(ac, w.email("late"))
            token = await _invite(ac, admin_s, w.email("late"))
            assert (await ac.post("/api/v1/orgs/invites/accept", headers=_cookie(late_s), json={"token": token})).status_code == 200
            r = await ac.post("/api/v1/keys", headers=_cookie(late_s), json={"name": "x", "scope": "read_write", "expires_in_days": 365})
            assert r.status_code in (401, 403), f"key minted in the two-step org without a code: {r.status_code} {r.text}"
    finally:
        await _cleanup(w)


@requires_pg
@pytest.mark.asyncio
async def test_a_member_with_two_step_or_single_sign_on_keeps_their_session(env, clock):
    w = World()
    try:
        async with _client() as ac:
            org, admin_s = await _two_step_org(ac, w, clock)
            coded, coded_s = await _signup(ac, w.email("coded"))
            _secret, _codes, coded_s = await _enrol(ac, coded_s, clock)
            sso, sso_s = await _signup(ac, w.email("sso"))
            await _q(
                "INSERT INTO auth_identities (provider, issuer, subject, user_id) VALUES ('oidc', 'https://idp.example', :sub, :u)",
                sub=f"sub-{uuid.uuid4().hex}", u=sso,
            )
            for uid, session, who in ((coded, coded_s, "coded"), (sso, sso_s, "sso")):
                token = await _invite(ac, admin_s, w.email(who))
                r = await ac.post("/api/v1/orgs/invites/accept", headers=_cookie(session), json={"token": token, "switch": True})
                assert r.status_code == 200 and r.json()["signed_out"] is False, r.text
                assert (await ac.get("/org-data", headers=_cookie(session))).json()["org_id"] == org
                assert await _current_org(uid) == org
    finally:
        await _cleanup(w)


@requires_pg
@pytest.mark.asyncio
async def test_joining_an_org_without_the_rule_keeps_the_session(env):
    w = World()
    try:
        async with _client() as ac:
            _admin, admin_s = await _signup(ac, w.email("admin"))
            _pat, pat_s = await _signup(ac, w.email("pat"))
            token = await _invite(ac, admin_s, w.email("pat"))
            r = await ac.post("/api/v1/orgs/invites/accept", headers=_cookie(pat_s), json={"token": token})
            assert r.status_code == 200 and r.json()["signed_out"] is False, r.text
            assert (await ac.get("/protected", headers=_cookie(pat_s))).status_code == 200
    finally:
        await _cleanup(w)
