"""SCIM tenant boundary: an org's SCIM token manages only that org's accounts.

The rule under test: SCIM may create a new account, or manage an account that
is already a member of the caller's org or holds a ScimIdentity there. Every
other account reads as 404 (lookups, group adds) or 409 (create with its email)
and is left exactly as it was: no membership, no identity, no email change, no
active-org switch, no sign-out. Email changes need an account this org's SCIM
provisioned that belongs to no other org, and deprovisioning only removes this
org's membership.

Live-Postgres tests skip unless DATABASE_URL is a Postgres URL at schema head:

    DATABASE_URL=postgresql://... python -m pytest tests/test_scim_tenant_boundary.py -q
"""
from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from ulid import ULID

from src.api import scim
from src.auth.org_context import (
    ensure_personal_org,
    is_personal_org,
    personal_org_name,
    personal_org_slug,
)
from src.auth.rbac import OrgAuthContext
from src.db.engine import get_db_session
from src.services import scim_service as svc

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)

PATCH = svc.PATCH_SCHEMA
USER = svc.CORE_USER_SCHEMA


# ══════════════════════════════════════════════════════════════════════════
# Pure: personal-org classification and the mount switch
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "email",
    ["pat@corp.example", "Pat.Smith+x@corp.example", "o'neil@corp.example", "@odd", "x@y"],
)
def test_personal_org_names_are_recognised(email):
    assert is_personal_org(personal_org_name(email), personal_org_slug(email)) is True


@pytest.mark.parametrize(
    "name",
    ["Acme Corp", "pat's Organization", "Pat.Smith's Organization", "Org"],
)
def test_named_orgs_are_not_personal(name):
    # The exact slug create_org derives for a named org.
    slug = personal_org_slug(name.strip().replace(" ", "-"))
    assert is_personal_org(name, slug) is False


def test_personal_org_check_ignores_non_text():
    assert is_personal_org(None, None) is False
    assert is_personal_org("pat's Organization", None) is False


@pytest.mark.parametrize(
    ("auth_mode", "flag", "expected"),
    [
        ("password", None, False),
        ("google", None, False),
        ("saml", None, True),
        ("oidc", None, True),
        ("hybrid", None, True),
        ("password", "1", True),
        ("password", "true", True),
        ("saml", "0", False),
        (None, None, False),
    ],
)
def test_scim_mounts_only_with_single_sign_on_or_explicit_flag(
    monkeypatch, auth_mode, flag, expected
):
    if auth_mode is None:
        monkeypatch.delenv("AUTH_MODE", raising=False)
    else:
        monkeypatch.setenv("AUTH_MODE", auth_mode)
    if flag is None:
        monkeypatch.delenv("SCIM_ENABLED", raising=False)
    else:
        monkeypatch.setenv("SCIM_ENABLED", flag)
    assert scim.scim_routes_enabled() is expected


def test_mount_scim_logs_and_includes_routes_only_when_enabled(monkeypatch, caplog):
    monkeypatch.delenv("SCIM_ENABLED", raising=False)

    monkeypatch.setenv("AUTH_MODE", "password")
    off = FastAPI()
    with caplog.at_level(logging.INFO, logger="cadverify.scim"):
        assert scim.mount_scim(off) is False
    assert not [p for p in off.openapi()["paths"] if p.startswith("/scim/v2")]
    assert "SCIM provisioning not mounted" in caplog.text

    caplog.clear()
    monkeypatch.setenv("AUTH_MODE", "saml")
    on = FastAPI()
    with caplog.at_level(logging.INFO, logger="cadverify.scim"):
        assert scim.mount_scim(on) is True
    assert "/scim/v2/Users" in on.openapi()["paths"]
    assert "SCIM provisioning mounted at /scim/v2" in caplog.text


@pytest.mark.asyncio
async def test_personal_org_key_is_refused_before_any_scim_work():
    email = "pat@corp.example"
    org_row = MagicMock()
    org_row.first.return_value = (personal_org_name(email), personal_org_slug(email))
    session = AsyncMock()
    session.execute = AsyncMock(return_value=org_row)

    app = FastAPI()
    app.include_router(scim.router)

    async def _fake_ctx():
        return OrgAuthContext(
            user_id=1, api_key_id=1, key_prefix="test", role="analyst",
            is_superadmin=False, org_id="org_personal", org_role="admin",
        )

    async def _fake_session():
        yield session

    app.dependency_overrides[scim.require_scim_admin] = _fake_ctx
    app.dependency_overrides[get_db_session] = _fake_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example"
    ) as client:
        resp = await client.post(
            "/scim/v2/Users", json={"schemas": [USER], "userName": "x@corp.example"}
        )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "scim_org_required"
    # Only the org lookup ran; nothing was provisioned.
    assert session.execute.await_count == 1
    session.commit.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════
# Live-PG fixtures
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _loop_hermetic_engine():
    import src.db.engine as _eng

    _eng._ENGINE = None
    _eng._SESSION_FACTORY = None
    try:
        yield
    finally:
        _eng._ENGINE = None
        _eng._SESSION_FACTORY = None


class _World:
    """Two named orgs plus the people the boundary tests need."""

    def __init__(self, tag: str):
        self.tag = tag
        self.org_ids: list[str] = []
        self.user_ids: list[int] = []

    def email(self, who: str) -> str:
        return f"{who}-{self.tag}@corp.example"


async def _mk_named_org(s, world: _World, name: str) -> str:
    oid = str(ULID())
    await s.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"
        ),
        {"id": oid, "n": name, "sl": personal_org_slug(name.replace(" ", "-"))},
    )
    world.org_ids.append(oid)
    return oid


async def _mk_user(s, world: _World, email: str, provider: str = "password") -> int:
    uid = (
        await s.execute(
            text(
                "INSERT INTO users (email, email_lower, auth_provider) "
                "VALUES (:e, :l, :p) RETURNING id"
            ),
            {"e": email, "l": svc.normalize_email(email), "p": provider},
        )
    ).scalar_one()
    world.user_ids.append(int(uid))
    return int(uid)


async def _join(s, org_id: str, uid: int, role: str = "member") -> None:
    await s.execute(
        text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :o, :u, :r, now())"
        ),
        {"id": str(ULID()), "o": org_id, "u": uid, "r": role},
    )


async def _personal_user(s, world: _World, who: str) -> tuple[int, str]:
    """A password account with its own personal org, as at sign-up."""
    email = world.email(who)
    uid = await _mk_user(s, world, email)
    org = await ensure_personal_org(s, uid, email)
    world.org_ids.append(org)
    return uid, org


async def _mk_key(s, uid: int, org_id: str) -> int:
    return int(
        (
            await s.execute(
                text(
                    "INSERT INTO api_keys (user_id, org_id, prefix, hmac_index, secret_hash) "
                    "VALUES (:u, :o, 'test', :h, 'x') RETURNING id"
                ),
                {"u": uid, "o": org_id, "h": uuid.uuid4().hex},
            )
        ).scalar_one()
    )


async def _row(s, sql: str, **params):
    return (await s.execute(text(sql), params)).first()


async def _user_state(s, uid: int):
    return await _row(
        s,
        "SELECT email, email_lower, current_org_id, session_version FROM users WHERE id=:u",
        u=uid,
    )


async def _role(s, org_id: str, uid: int):
    r = await _row(
        s, "SELECT org_role FROM memberships WHERE org_id=:o AND user_id=:u", o=org_id, u=uid
    )
    return r[0] if r else None


async def _has_identity(s, org_id: str, uid: int) -> bool:
    r = await _row(
        s, "SELECT 1 FROM scim_identities WHERE org_id=:o AND user_id=:u", o=org_id, u=uid
    )
    return r is not None


async def _teardown(eng, world: _World):
    async with eng.get_session_factory()() as s:
        if world.user_ids:
            for table in ("scim_identities", "memberships", "api_keys", "audit_log"):
                await s.execute(
                    text(f"DELETE FROM {table} WHERE user_id = ANY(:u)"),  # fixed table names
                    {"u": world.user_ids},
                )
        if world.org_ids:
            await s.execute(
                text("DELETE FROM scim_identities WHERE org_id = ANY(:o)"), {"o": world.org_ids}
            )
            await s.execute(
                text("DELETE FROM memberships WHERE org_id = ANY(:o)"), {"o": world.org_ids}
            )
            await s.execute(
                text("UPDATE users SET current_org_id = NULL WHERE current_org_id = ANY(:o)"),
                {"o": world.org_ids},
            )
            await s.execute(
                text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": world.org_ids}
            )
        if world.user_ids:
            await s.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": world.user_ids})
        await s.commit()


def _ctx(org_id: str, user_id: int) -> OrgAuthContext:
    return OrgAuthContext(
        user_id=user_id,
        api_key_id=1,
        key_prefix="test",
        role="analyst",
        is_superadmin=False,
        org_id=org_id,
        org_role="admin",
    )


@asynccontextmanager
async def _scim_client(eng, org_id: str, admin_id: int):
    """The real SCIM router over a real session, authenticated as ``org_id``'s admin."""
    app = FastAPI()
    app.include_router(scim.router)

    async def _fake_ctx():
        return _ctx(org_id, admin_id)

    async def _real_session():
        async with eng.get_session_factory()() as s:
            yield s

    app.dependency_overrides[scim.require_scim_admin] = _fake_ctx
    app.dependency_overrides[get_db_session] = _real_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example"
    ) as client:
        yield client


async def _world_with_outsider(eng):
    """Org A (the caller) with its admin; org B with an outside account V.

    V signed up with a password (so V also has a personal org) and is a member
    of B. Nothing links V to A.
    """
    world = _World(uuid.uuid4().hex[:10])
    async with eng.get_session_factory()() as s:
        org_a = await _mk_named_org(s, world, f"Acme {world.tag}")
        org_b = await _mk_named_org(s, world, f"Beta {world.tag}")
        admin_a = await _mk_user(s, world, world.email("admin-a"))
        await _join(s, org_a, admin_a, "admin")
        victim, victim_personal = await _personal_user(s, world, "victim")
        await _join(s, org_b, victim, "admin")
        await s.commit()
    world.org_a, world.org_b = org_a, org_b
    world.admin_a, world.victim, world.victim_personal = admin_a, victim, victim_personal
    return world


async def _assert_untouched(eng, world: _World, before) -> None:
    async with eng.get_session_factory()() as s:
        assert await _user_state(s, world.victim) == before
        assert await _role(s, world.org_a, world.victim) is None
        assert await _has_identity(s, world.org_a, world.victim) is False
        assert await _role(s, world.org_b, world.victim) == "admin"


# ══════════════════════════════════════════════════════════════════════════
# An outside account cannot be touched through any SCIM route
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_create_with_an_outside_accounts_email_is_409_and_changes_nothing():
    import src.db.engine as eng

    world = await _world_with_outsider(eng)
    try:
        async with eng.get_session_factory()() as s:
            before = await _user_state(s, world.victim)
        victim_email = world.email("victim")
        local, domain = victim_email.split("@")
        async with _scim_client(eng, world.org_a, world.admin_a) as client:
            for user_name in (victim_email, victim_email.upper(), f"{local}+scim@{domain}"):
                resp = await client.post(
                    "/scim/v2/Users",
                    json={
                        "schemas": [USER],
                        "userName": user_name,
                        "active": True,
                        "roles": [{"value": "admin"}],
                    },
                )
                assert resp.status_code == 409, resp.text
                assert resp.json()["detail"]["scimType"] == "uniqueness"
        await _assert_untouched(eng, world, before)
    finally:
        await _teardown(eng, world)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_group_add_and_replace_of_an_outside_id_is_404_and_changes_nothing():
    import src.db.engine as eng

    world = await _world_with_outsider(eng)
    try:
        async with eng.get_session_factory()() as s:
            before = await _user_state(s, world.victim)
        vid = str(world.victim)
        payloads = [
            {"schemas": [PATCH], "Operations": [{"op": "add", "path": "members", "value": [{"value": vid}]}]},
            {"schemas": [PATCH], "Operations": [{"op": "add", "path": f'members[value eq "{vid}"]'}]},
            {"schemas": [PATCH], "Operations": [{"op": "add", "value": [{"value": vid}]}]},
            {"schemas": [PATCH], "Operations": [{"op": "replace", "path": "members", "value": [{"value": vid}]}]},
        ]
        async with _scim_client(eng, world.org_a, world.admin_a) as client:
            for payload in payloads:
                resp = await client.patch("/scim/v2/Groups/role:admin", json=payload)
                assert resp.status_code == 404, resp.text
                missing = await client.patch(
                    "/scim/v2/Groups/role:admin",
                    json={
                        "schemas": [PATCH],
                        "Operations": [
                            {"op": "add", "path": "members", "value": [{"value": "999999999"}]}
                        ],
                    },
                )
                # An outside id reads exactly like an id that does not exist.
                assert missing.status_code == 404
                assert missing.json() == resp.json()
        await _assert_untouched(eng, world, before)
        async with eng.get_session_factory()() as s:
            # replace must not have dropped A's own admin either
            assert await _role(s, world.org_a, world.admin_a) == "admin"
    finally:
        await _teardown(eng, world)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_user_routes_by_outside_id_read_as_404_and_change_nothing():
    import src.db.engine as eng

    world = await _world_with_outsider(eng)
    try:
        async with eng.get_session_factory()() as s:
            before = await _user_state(s, world.victim)
        vid = world.victim
        async with _scim_client(eng, world.org_a, world.admin_a) as client:
            missing = await client.get("/scim/v2/Users/999999999")
            assert missing.status_code == 404
            got = await client.get(f"/scim/v2/Users/{vid}")
            assert got.status_code == 404
            assert got.json() == missing.json()

            patched = await client.patch(
                f"/scim/v2/Users/{vid}",
                json={
                    "schemas": [PATCH],
                    "Operations": [
                        {"op": "replace", "path": "userName", "value": world.email("attacker")}
                    ],
                },
            )
            assert patched.status_code == 404
            replaced = await client.put(
                f"/scim/v2/Users/{vid}", json={"schemas": [USER], "active": False}
            )
            assert replaced.status_code == 404
            deleted = await client.delete(f"/scim/v2/Users/{vid}")
            assert deleted.status_code == 404
        await _assert_untouched(eng, world, before)
    finally:
        await _teardown(eng, world)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Email changes: only for an account this org's SCIM provisioned exclusively
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_email_change_allowed_for_an_account_this_orgs_scim_owns():
    import src.db.engine as eng

    world = await _world_with_outsider(eng)
    try:
        async with _scim_client(eng, world.org_a, world.admin_a) as client:
            created = await client.post(
                "/scim/v2/Users",
                json={"schemas": [USER], "userName": world.email("new-hire"), "active": True},
            )
            assert created.status_code == 201, created.text
            uid = int(created.json()["id"])
            world.user_ids.append(uid)
            renamed = await client.patch(
                f"/scim/v2/Users/{uid}",
                json={
                    "schemas": [PATCH],
                    "Operations": [
                        {"op": "replace", "path": "userName", "value": world.email("renamed")}
                    ],
                },
            )
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["userName"] == world.email("renamed")
    finally:
        await _teardown(eng, world)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_email_change_refused_for_a_member_who_signed_up_themselves():
    import src.db.engine as eng

    world = await _world_with_outsider(eng)
    try:
        async with eng.get_session_factory()() as s:
            # A password account that is a member of A (and has its own personal org).
            member, _personal = await _personal_user(s, world, "member")
            await _join(s, world.org_a, member, "member")
            await s.commit()
        async with _scim_client(eng, world.org_a, world.admin_a) as client:
            # Okta's normal link of an existing member works.
            linked = await client.post(
                "/scim/v2/Users",
                json={"schemas": [USER], "userName": world.email("member"), "active": True},
            )
            assert linked.status_code == 201, linked.text
            assert int(linked.json()["id"]) == member
            async with eng.get_session_factory()() as s:
                before = await _user_state(s, member)

            # Re-sending the unchanged userName is not a change.
            same = await client.patch(
                f"/scim/v2/Users/{member}",
                json={
                    "schemas": [PATCH],
                    "Operations": [{"op": "replace", "value": {"userName": world.email("member")}}],
                },
            )
            assert same.status_code == 200, same.text

            for op in (
                {"op": "replace", "path": "userName", "value": world.email("hijack")},
                {"op": "replace", "path": 'emails[type eq "work"].value', "value": world.email("hijack")},
                {"op": "replace", "value": {"userName": world.email("member").upper()}},
            ):
                resp = await client.patch(
                    f"/scim/v2/Users/{member}", json={"schemas": [PATCH], "Operations": [op]}
                )
                assert resp.status_code == 409, resp.text
        async with eng.get_session_factory()() as s:
            assert await _user_state(s, member) == before
    finally:
        await _teardown(eng, world)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_email_change_refused_when_scim_account_also_belongs_to_another_org():
    import src.db.engine as eng

    world = await _world_with_outsider(eng)
    try:
        async with _scim_client(eng, world.org_a, world.admin_a) as client:
            created = await client.post(
                "/scim/v2/Users",
                json={"schemas": [USER], "userName": world.email("shared"), "active": True},
            )
            assert created.status_code == 201, created.text
            uid = int(created.json()["id"])
            world.user_ids.append(uid)
            async with eng.get_session_factory()() as s:
                await _join(s, world.org_b, uid, "viewer")
                await s.commit()
                before = await _user_state(s, uid)
            resp = await client.patch(
                f"/scim/v2/Users/{uid}",
                json={
                    "schemas": [PATCH],
                    "Operations": [
                        {"op": "replace", "path": "userName", "value": world.email("elsewhere")}
                    ],
                },
            )
            assert resp.status_code == 409, resp.text
        async with eng.get_session_factory()() as s:
            assert await _user_state(s, uid) == before
    finally:
        await _teardown(eng, world)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Deprovisioning removes this org's access only
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_deprovision_of_a_member_with_other_orgs_keeps_their_sessions_elsewhere():
    import src.db.engine as eng

    world = await _world_with_outsider(eng)
    try:
        async with eng.get_session_factory()() as s:
            member, personal = await _personal_user(s, world, "member")
            await _join(s, world.org_a, member, "member")
            key_a = await _mk_key(s, member, world.org_a)
            key_personal = await _mk_key(s, member, personal)
            await s.commit()
        async with _scim_client(eng, world.org_a, world.admin_a) as client:
            linked = await client.post(
                "/scim/v2/Users",
                json={"schemas": [USER], "userName": world.email("member"), "active": True},
            )
            assert linked.status_code == 201, linked.text
            async with eng.get_session_factory()() as s:
                before = await _user_state(s, member)
            # Linking an existing member does not move their active org.
            assert before.current_org_id == personal
            deleted = await client.delete(f"/scim/v2/Users/{member}")
            assert deleted.status_code == 204, deleted.text
        async with eng.get_session_factory()() as s:
            after = await _user_state(s, member)
            assert await _role(s, world.org_a, member) is None
            assert await _role(s, personal, member) == "admin"
            assert after.session_version == before.session_version
            assert after.current_org_id == personal
            revoked = {
                r[0]: r[1]
                for r in (
                    await s.execute(
                        text("SELECT id, revoked_at IS NOT NULL FROM api_keys WHERE user_id=:u"),
                        {"u": member},
                    )
                ).all()
            }
            assert revoked == {key_a: True, key_personal: False}
    finally:
        await _teardown(eng, world)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_deprovision_of_a_scim_owned_account_still_signs_it_out():
    import src.db.engine as eng

    world = await _world_with_outsider(eng)
    try:
        async with _scim_client(eng, world.org_a, world.admin_a) as client:
            created = await client.post(
                "/scim/v2/Users",
                json={"schemas": [USER], "userName": world.email("leaver"), "active": True},
            )
            assert created.status_code == 201, created.text
            uid = int(created.json()["id"])
            world.user_ids.append(uid)
            async with eng.get_session_factory()() as s:
                before = await _user_state(s, uid)
            deleted = await client.delete(f"/scim/v2/Users/{uid}")
            assert deleted.status_code == 204
            # The inactive resource stays readable to its IdP.
            fetched = await client.get(f"/scim/v2/Users/{uid}")
            assert fetched.status_code == 200
            assert fetched.json()["active"] is False
        async with eng.get_session_factory()() as s:
            after = await _user_state(s, uid)
            assert await _role(s, world.org_a, uid) is None
            assert after.session_version == before.session_version + 1
    finally:
        await _teardown(eng, world)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_group_add_of_this_orgs_own_member_still_works():
    import src.db.engine as eng

    world = await _world_with_outsider(eng)
    try:
        async with eng.get_session_factory()() as s:
            member, _personal = await _personal_user(s, world, "member")
            await _join(s, world.org_a, member, "viewer")
            await s.commit()
        async with _scim_client(eng, world.org_a, world.admin_a) as client:
            resp = await client.patch(
                "/scim/v2/Groups/role:member",
                json={
                    "schemas": [PATCH],
                    "Operations": [
                        {"op": "add", "path": "members", "value": [{"value": str(member)}]}
                    ],
                },
            )
            assert resp.status_code == 200, resp.text
            assert str(member) in {m["value"] for m in resp.json()["members"]}
        async with eng.get_session_factory()() as s:
            assert await _role(s, world.org_a, member) == "member"
            assert await _has_identity(s, world.org_a, member) is True
    finally:
        await _teardown(eng, world)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Personal orgs never use SCIM
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_personal_org_admin_key_is_refused_with_scim_org_required():
    import src.db.engine as eng

    world = await _world_with_outsider(eng)
    try:
        async with _scim_client(eng, world.victim_personal, world.victim) as client:
            for method, path in (
                ("GET", "/scim/v2/ServiceProviderConfig"),
                ("GET", "/scim/v2/Users"),
                ("POST", "/scim/v2/Users"),
                ("PATCH", "/scim/v2/Groups/role:admin"),
            ):
                resp = await client.request(
                    method,
                    path,
                    json={"schemas": [USER], "userName": world.email("someone")}
                    if method != "GET"
                    else None,
                )
                assert resp.status_code == 403, (path, resp.text)
                detail = resp.json()["detail"]
                assert detail["code"] == "scim_org_required"
                assert "personal" in detail["message"].lower()
        async with _scim_client(eng, world.org_a, world.admin_a) as client:
            ok = await client.get("/scim/v2/ServiceProviderConfig")
            assert ok.status_code == 200
    finally:
        await _teardown(eng, world)
        await eng.dispose_engine()
