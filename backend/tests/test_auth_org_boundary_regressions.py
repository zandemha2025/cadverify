"""Focused regressions for tenant-bound API keys and global platform roles."""
from __future__ import annotations

import base64
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from src.api import admin_routes, org_routes
from src.auth.hashing import hmac_index, mint_token
from src.auth.models import ApiKeyRow
from src.auth.rbac import OrgAuthContext
from src.auth.require_api_key import AuthedUser, require_api_key


class _Request:
    def __init__(self) -> None:
        self.cookies = {}
        self.state = SimpleNamespace()
        self.client = SimpleNamespace(host="127.0.0.1")


def _pepper(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY_PEPPER", base64.b64encode(b"o" * 32).decode())


@pytest.mark.asyncio
async def test_api_key_auth_retains_and_enforces_issuing_org(monkeypatch):
    _pepper(monkeypatch)
    token, prefix, secret_hash = mint_token()
    row = ApiKeyRow(
        id=17,
        user_id=42,
        prefix=prefix,
        hmac_index=hmac_index(token),
        secret_hash=secret_hash,
        revoked_at=None,
        role="analyst",
        is_active=True,
        org_id="org-a",
        active_org_id="org-a",
    )
    monkeypatch.setattr(
        "src.auth.require_api_key.lookup_api_key", AsyncMock(return_value=row)
    )
    monkeypatch.setattr(
        "src.auth.require_api_key.touch_last_used", AsyncMock()
    )

    user = await require_api_key(
        _Request(), authorization=f"Bearer {token}"
    )
    assert user.api_key_id == 17
    assert user.org_id == "org-a"

    row.active_org_id = "org-b"
    with pytest.raises(HTTPException) as exc:
        await require_api_key(_Request(), authorization=f"Bearer {token}")
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "api_key_org_mismatch"


@pytest.mark.asyncio
async def test_api_key_cannot_switch_organizations(monkeypatch):
    switch = AsyncMock()
    monkeypatch.setattr(org_routes.svc, "switch_org", switch)
    user = AuthedUser(
        user_id=42,
        api_key_id=17,
        key_prefix="cv_live_bound",
        role="analyst",
        org_id="org-a",
    )

    with pytest.raises(HTTPException) as exc:
        await org_routes.switch_org(
            request=Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/api/v1/orgs/switch",
                    "headers": [],
                    "query_string": b"",
                    "server": ("testserver", 80),
                    "client": ("127.0.0.1", 1234),
                    "scheme": "http",
                }
            ),
            response=Response(),
            body=org_routes.SwitchBody(org_id="org-b"),
            user=user,
            session=AsyncMock(),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "api_key_org_bound"
    switch.assert_not_awaited()


@pytest.mark.asyncio
async def test_org_admin_cannot_mutate_global_platform_role():
    ctx = OrgAuthContext(
        user_id=7,
        api_key_id=0,
        key_prefix="session",
        role="analyst",
        is_superadmin=False,
        org_id="org-a",
        org_role="admin",
    )
    session = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await admin_routes.update_user_role(
            user_id=99,
            body=admin_routes.RoleUpdate(role="analyst"),
            ctx=ctx,
            session=session,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "platform_superadmin_required"
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_scim_membership_removal_revokes_org_keys(monkeypatch):
    from src.services import scim_service

    membership = SimpleNamespace(org_role="member")
    user = SimpleNamespace(id=55, current_org_id="org-b", session_version=3)
    session = AsyncMock()
    monkeypatch.setattr(
        scim_service, "_membership", AsyncMock(return_value=membership)
    )
    revoke = AsyncMock(return_value=2)
    monkeypatch.setattr(scim_service, "revoke_org_api_keys", revoke)

    await scim_service._deprovision_membership(
        session, org_id="org-b", user=user
    )

    revoke.assert_awaited_once_with(session, 55, "org-b")
    session.delete.assert_awaited_once_with(membership)
    assert user.current_org_id is None
    assert user.session_version == 4


_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


@_requires_pg
@pytest.mark.asyncio
async def test_two_org_key_offboarding_and_global_role_boundary(monkeypatch):
    """Live-Postgres proof for both fixes with one user shared by two orgs."""
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.auth.models import lookup_api_key
    from src.services import org_service

    _pepper(monkeypatch)
    monkeypatch.setattr(
        "src.auth.require_api_key.touch_last_used", AsyncMock()
    )
    tag = uuid.uuid4().hex[:12]
    org_a, org_b = str(ULID()), str(ULID())
    user_ids: list[int] = []

    async def _user(session, label: str, role: str, current_org: str | None) -> int:
        email = f"org-boundary-{tag}-{label}@example.com"
        row = (
            await session.execute(
                text(
                    "INSERT INTO users "
                    "(email, email_lower, role, auth_provider, current_org_id) "
                    "VALUES (:e, :e, :r, 'password', :o) RETURNING id"
                ),
                {"e": email, "r": role, "o": current_org},
            )
        ).first()
        uid = int(row[0])
        user_ids.append(uid)
        return uid

    async def _membership(session, org_id: str, user_id: int, role: str) -> None:
        await session.execute(
            text(
                "INSERT INTO memberships "
                "(id, org_id, user_id, org_role, created_at) "
                "VALUES (:id, :o, :u, :r, now())"
            ),
            {"id": str(ULID()), "o": org_id, "u": user_id, "r": role},
        )

    token_a, prefix_a, hash_a = mint_token()
    token_b, prefix_b, hash_b = mint_token()
    shared_user = admin_a = superadmin = 0
    try:
        async with eng.get_session_factory()() as session:
            for org_id, label in ((org_a, "A"), (org_b, "B")):
                await session.execute(
                    text(
                        "INSERT INTO organizations (id, name, slug, created_at) "
                        "VALUES (:id, :n, :s, now())"
                    ),
                    {
                        "id": org_id,
                        "n": f"Boundary org {label} {tag}",
                        "s": f"boundary-{label.lower()}-{tag}",
                    },
                )
            shared_user = await _user(session, "shared", "viewer", org_a)
            admin_a = await _user(session, "admin-a", "analyst", org_a)
            superadmin = await _user(session, "super", "superadmin", None)
            await _membership(session, org_a, shared_user, "member")
            await _membership(session, org_b, shared_user, "member")
            await _membership(session, org_a, admin_a, "admin")
            await session.execute(
                text(
                    "INSERT INTO api_keys "
                    "(user_id, org_id, name, prefix, hmac_index, secret_hash) "
                    "VALUES (:u, :o, :n, :p, :h, :s)"
                ),
                [
                    {
                        "u": shared_user,
                        "o": org_a,
                        "n": "Org A key",
                        "p": prefix_a,
                        "h": hmac_index(token_a),
                        "s": hash_a,
                    },
                    {
                        "u": shared_user,
                        "o": org_b,
                        "n": "Org B key",
                        "p": prefix_b,
                        "h": hmac_index(token_b),
                        "s": hash_b,
                    },
                ],
            )
            await session.commit()

        key_a = await lookup_api_key(hmac_index(token_a))
        assert key_a is not None
        assert key_a.org_id == org_a
        assert key_a.active_org_id == org_a
        authed_a = await require_api_key(
            _Request(), authorization=f"Bearer {token_a}"
        )
        assert authed_a.org_id == org_a

        with pytest.raises(HTTPException) as wrong_org:
            await require_api_key(
                _Request(), authorization=f"Bearer {token_b}"
            )
        assert wrong_org.value.detail["code"] == "api_key_org_mismatch"

        async with eng.get_session_factory()() as session:
            await org_service.switch_org(session, shared_user, org_b)
            await session.commit()

        with pytest.raises(HTTPException) as old_org:
            await require_api_key(
                _Request(), authorization=f"Bearer {token_a}"
            )
        assert old_org.value.detail["code"] == "api_key_org_mismatch"
        authed_b = await require_api_key(
            _Request(), authorization=f"Bearer {token_b}"
        )
        assert authed_b.org_id == org_b

        async with eng.get_session_factory()() as session:
            await org_service.remove_member(
                session, org_b, shared_user, shared_user
            )
            await session.commit()
            key_states = dict(
                (
                    await session.execute(
                        text(
                            "SELECT org_id, revoked_at IS NOT NULL FROM api_keys "
                            "WHERE user_id = :u"
                        ),
                        {"u": shared_user},
                    )
                ).all()
            )
        assert key_states == {org_a: False, org_b: True}
        with pytest.raises(HTTPException) as removed:
            await require_api_key(
                _Request(), authorization=f"Bearer {token_b}"
            )
        assert removed.value.status_code == 401
        assert removed.value.detail["code"] == "auth_invalid"
        assert (await require_api_key(
            _Request(), authorization=f"Bearer {token_a}"
        )).org_id == org_a

        org_admin_ctx = OrgAuthContext(
            user_id=admin_a,
            api_key_id=0,
            key_prefix="session",
            role="analyst",
            is_superadmin=False,
            org_id=org_a,
            org_role="admin",
        )
        async with eng.get_session_factory()() as session:
            with pytest.raises(HTTPException) as denied:
                await admin_routes.update_user_role(
                    shared_user,
                    admin_routes.RoleUpdate(role="analyst"),
                    org_admin_ctx,
                    session,
                )
            assert denied.value.detail["code"] == "platform_superadmin_required"
            role = (
                await session.execute(
                    text("SELECT role FROM users WHERE id = :u"),
                    {"u": shared_user},
                )
            ).scalar_one()
            assert role == "viewer"

        super_ctx = OrgAuthContext(
            user_id=superadmin,
            api_key_id=0,
            key_prefix="session",
            role="superadmin",
            is_superadmin=True,
            org_id=None,
            org_role=None,
        )
        async with eng.get_session_factory()() as session:
            result = await admin_routes.update_user_role(
                shared_user,
                admin_routes.RoleUpdate(role="analyst"),
                super_ctx,
                session,
            )
            assert result["role"] == "analyst"
    finally:
        async with eng.get_session_factory()() as session:
            if user_ids:
                await session.execute(
                    text("DELETE FROM audit_log WHERE user_id = ANY(:ids)"),
                    {"ids": user_ids},
                )
                await session.execute(
                    text("DELETE FROM users WHERE id = ANY(:ids)"),
                    {"ids": user_ids},
                )
            await session.execute(
                text("DELETE FROM organizations WHERE id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )
            await session.commit()
        await eng.dispose_engine()
