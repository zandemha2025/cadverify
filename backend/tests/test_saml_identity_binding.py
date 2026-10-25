"""SAML sign-in binds to its IdP identity and never takes over an outside account.

A SAML sign-in reaches an existing account with the same email only when that
account is already bound to the same IdP identity (issuer + NameID), is a member
of the org that owns the IdP (``SSO_ORG_ID``), or was created by SAML before
identities were bound. Any other existing account (password, magic link,
Google) answers 409 ``saml_link_required`` and is left as it was.

Skipped unless DATABASE_URL is a Postgres URL at schema head.
"""
from __future__ import annotations

import base64
import os
import uuid

import asyncpg
import pytest
from fastapi import HTTPException
from ulid import ULID

from src.auth.saml import _saml_provision_login

_PG_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _PG_URL.startswith("postgresql"),
    reason="requires local Postgres (set DATABASE_URL=postgresql://...)",
)

ISSUER = "https://idp.example.test/saml"


async def _q(sql: str, *args):
    conn = await asyncpg.connect(_PG_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


def _reset_engine() -> None:
    import src.db.engine as engine

    engine._ENGINE = None
    engine._SESSION_FACTORY = None


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("API_KEY_PEPPER", base64.b64encode(b"p" * 32).decode())
    tag = uuid.uuid4().hex[:10]
    state = {"tag": tag, "users": [], "orgs": []}
    _reset_engine()
    yield state
    _reset_engine()


async def _cleanup(state) -> None:
    rows = await _q(
        "SELECT id FROM users WHERE email_lower LIKE $1", f"%-{state['tag']}@corp.example"
    )
    user_ids = [int(r["id"]) for r in rows] + state["users"]
    orgs = [
        r["org_id"]
        for r in await _q(
            "SELECT DISTINCT org_id FROM memberships WHERE user_id = ANY($1::bigint[])", user_ids
        )
    ] + state["orgs"]
    for table in ("audit_log", "auth_identities", "api_keys", "memberships"):
        await _q(f"DELETE FROM {table} WHERE user_id = ANY($1::bigint[])", user_ids)  # fixed names
    await _q("DELETE FROM saml_group_mappings WHERE org_id = ANY($1::text[])", orgs)
    await _q("DELETE FROM memberships WHERE org_id = ANY($1::text[])", orgs)
    await _q("DELETE FROM users WHERE id = ANY($1::bigint[])", user_ids)
    await _q("DELETE FROM organizations WHERE id = ANY($1::text[])", orgs)


async def _org(state, name: str) -> str:
    oid = str(ULID())
    await _q(
        "INSERT INTO organizations (id, name, slug, created_at) VALUES ($1, $2, $3, now())",
        oid,
        f"{name} {state['tag']}",
        f"{name.lower()}-{state['tag']}-{oid[-6:].lower()}",
    )
    state["orgs"].append(oid)
    return oid


async def _account(state, who: str, provider: str = "password", *, active: bool = True) -> tuple[int, str]:
    email = f"{who}-{state['tag']}@corp.example"
    rows = await _q(
        "INSERT INTO users (email, email_lower, auth_provider, password_hash, is_active) "
        "VALUES ($1, $1, $2, $3, $4) RETURNING id",
        email,
        provider,
        "argon2-hash" if provider == "password" else None,
        active,
    )
    uid = int(rows[0]["id"])
    state["users"].append(uid)
    return uid, email


async def _join(org_id: str, uid: int, role: str = "member") -> None:
    await _q(
        "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
        "VALUES ($1, $2, $3, $4, now())",
        str(ULID()),
        org_id,
        uid,
        role,
    )


async def _identities(uid: int):
    return [
        (r["provider"], r["issuer"], r["subject"])
        for r in await _q(
            "SELECT provider, issuer, subject FROM auth_identities WHERE user_id=$1", uid
        )
    ]


async def _account_state(uid: int):
    rows = await _q(
        "SELECT email, auth_provider, password_hash, session_version FROM users WHERE id=$1", uid
    )
    return tuple(rows[0])


@pytest.mark.asyncio
async def test_saml_refuses_to_take_over_a_password_account_outside_the_idp_org(world, monkeypatch):
    try:
        owner = await _org(world, "Owner")
        monkeypatch.setenv("SSO_ORG_ID", owner)
        uid, email = await _account(world, "outsider")
        before = await _account_state(uid)

        for nameid in (email, email.upper()):
            with pytest.raises(HTTPException) as exc:
                await _saml_provision_login(nameid, None, issuer=ISSUER)
            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == "saml_link_required"

        assert await _identities(uid) == []
        assert await _account_state(uid) == before
        assert await _q("SELECT 1 FROM api_keys WHERE user_id=$1", uid) == []
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_saml_also_refuses_when_no_org_owns_the_idp(world, monkeypatch):
    try:
        monkeypatch.delenv("SSO_ORG_ID", raising=False)
        uid, email = await _account(world, "member")
        owner = await _org(world, "Owner")
        await _join(owner, uid)
        with pytest.raises(HTTPException) as exc:
            await _saml_provision_login(email, None, issuer=ISSUER)
        assert exc.value.status_code == 409
        assert await _identities(uid) == []
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_saml_binds_a_member_of_the_idp_org_then_reuses_the_binding(world, monkeypatch):
    try:
        owner = await _org(world, "Owner")
        monkeypatch.setenv("SSO_ORG_ID", owner)
        uid, email = await _account(world, "employee")
        await _join(owner, uid)

        first = await _saml_provision_login(email, None, issuer=ISSUER)
        assert first.user_id == uid and first.created is False
        assert await _identities(uid) == [("saml", ISSUER, email.lower())]
        linked = await _q(
            "SELECT count(*) AS n FROM audit_log WHERE user_id=$1 AND action='auth.identity_linked'",
            uid,
        )
        assert int(linked[0]["n"]) == 1

        # The IdP's casing of the NameID may vary; it is the same identity.
        again = await _saml_provision_login(email.upper(), None, issuer=ISSUER)
        assert again.user_id == uid
        assert await _identities(uid) == [("saml", ISSUER, email.lower())]
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_saml_never_rebinds_an_account_to_a_different_nameid(world, monkeypatch):
    try:
        owner = await _org(world, "Owner")
        monkeypatch.setenv("SSO_ORG_ID", owner)
        uid, email = await _account(world, "bound")
        await _join(owner, uid)
        await _q(
            "INSERT INTO auth_identities (provider, issuer, subject, user_id, email_at_link) "
            "VALUES ('saml', $1, $2, $3, $4)",
            ISSUER,
            f"someone-else-{world['tag']}@corp.example",
            uid,
            email,
        )
        with pytest.raises(HTTPException) as exc:
            await _saml_provision_login(email, None, issuer=ISSUER)
        assert exc.value.status_code == 409
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_saml_binds_an_account_saml_itself_created_before_binding(world, monkeypatch):
    try:
        monkeypatch.delenv("SSO_ORG_ID", raising=False)
        uid, email = await _account(world, "legacy", provider="saml")
        login = await _saml_provision_login(email, None, issuer=ISSUER)
        assert login.user_id == uid
        assert await _identities(uid) == [("saml", ISSUER, email.lower())]
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_saml_refuses_a_deactivated_member(world, monkeypatch):
    try:
        owner = await _org(world, "Owner")
        monkeypatch.setenv("SSO_ORG_ID", owner)
        uid, email = await _account(world, "former", active=False)
        await _join(owner, uid)
        with pytest.raises(HTTPException) as exc:
            await _saml_provision_login(email, None, issuer=ISSUER)
        assert exc.value.status_code == 403
        assert await _identities(uid) == []
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_saml_new_user_gets_a_bound_account_and_the_owner_orgs_group_role(world, monkeypatch):
    try:
        owner = await _org(world, "Owner")
        other = await _org(world, "Other")
        monkeypatch.setenv("SSO_ORG_ID", owner)
        group = f"cn=cad-{world['tag']}"
        for org_id, role in ((owner, "member"), (other, "admin")):
            await _q(
                "INSERT INTO saml_group_mappings (org_id, attribute_name, group_value, org_role) "
                "VALUES ($1, 'memberOf', $2, $3)",
                org_id,
                group,
                role,
            )
        email = f"new-hire-{world['tag']}@corp.example"
        login = await _saml_provision_login(email, {"memberOf": [group]}, issuer=ISSUER)

        assert login.created is True
        assert login.group_assignment.org_id == owner
        assert await _identities(login.user_id) == [("saml", ISSUER, email.lower())]
        roles = {
            r["org_id"]: r["org_role"]
            for r in await _q(
                "SELECT org_id, org_role FROM memberships WHERE user_id=$1", login.user_id
            )
        }
        assert roles.get(owner) == "member"
        assert other not in roles
        provider = await _q("SELECT auth_provider FROM users WHERE id=$1", login.user_id)
        assert provider[0]["auth_provider"] == "saml"
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_saml_without_an_idp_entity_id_is_refused(world):
    with pytest.raises(HTTPException) as exc:
        await _saml_provision_login("someone@corp.example", None, issuer="")
    assert exc.value.status_code == 500
    assert exc.value.detail["code"] == "saml_idp_unconfigured"
