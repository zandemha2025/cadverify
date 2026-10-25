"""Transactional identity provisioning and immutable OIDC binding proofs."""
from __future__ import annotations

import base64
import os
import uuid

import asyncpg
import pytest
from fastapi import HTTPException, Response
from ulid import ULID

from src.auth.provisioning import (
    FederatedIdentity,
    provision_authenticated_login,
)


_PG_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _PG_URL.startswith("postgresql"),
    reason="requires local Postgres (set DATABASE_URL=postgresql://...)",
)


async def _fetch(sql: str, *args):
    conn = await asyncpg.connect(_PG_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _execute(sql: str, *args) -> None:
    conn = await asyncpg.connect(_PG_URL)
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


def _reset_engine() -> None:
    import src.db.engine as engine

    engine._ENGINE = None
    engine._SESSION_FACTORY = None


async def _cleanup(email_lower: str) -> None:
    rows = await _fetch("SELECT id FROM users WHERE email_lower=$1", email_lower)
    if not rows:
        return
    user_id = int(rows[0]["id"])
    orgs = await _fetch(
        "SELECT DISTINCT org_id FROM memberships WHERE user_id=$1", user_id
    )
    await _execute("DELETE FROM audit_log WHERE user_id=$1", user_id)
    await _execute("DELETE FROM auth_identities WHERE user_id=$1", user_id)
    await _execute("DELETE FROM api_keys WHERE user_id=$1", user_id)
    for row in orgs:
        await _execute(
            "DELETE FROM saml_group_mappings WHERE org_id=$1", row["org_id"]
        )
    await _execute("DELETE FROM memberships WHERE user_id=$1", user_id)
    await _execute("DELETE FROM users WHERE id=$1", user_id)
    for row in orgs:
        await _execute("DELETE FROM organizations WHERE id=$1", row["org_id"])


@pytest.mark.asyncio
async def test_oidc_subject_binding_is_immutable_and_audit_atomic(monkeypatch):
    monkeypatch.setenv(
        "API_KEY_PEPPER", base64.b64encode(b"p" * 32).decode()
    )
    tag = uuid.uuid4().hex[:12]
    email = f"oidc-binding-{tag}@example.com"
    issuer = "https://idp.example.test"
    identity = FederatedIdentity("oidc", issuer, f"subject-{tag}", True)
    _reset_engine()
    try:
        first = await provision_authenticated_login(
            email=email,
            provider="oidc",
            key_name="OIDC Default",
            default_role="viewer",
            identity=identity,
            group_detail_key="oidc_group_assignment",
        )
        second = await provision_authenticated_login(
            email=email,
            provider="oidc",
            key_name="OIDC Default",
            default_role="viewer",
            identity=identity,
            group_detail_key="oidc_group_assignment",
        )

        assert first.created is True and first.key_token
        assert second.created is False and second.key_token is None
        assert first.user_id == second.user_id

        identity_rows = await _fetch(
            "SELECT user_id, subject FROM auth_identities "
            "WHERE provider='oidc' AND issuer=$1",
            issuer,
        )
        assert [(int(r["user_id"]), r["subject"]) for r in identity_rows] == [
            (first.user_id, f"subject-{tag}")
        ]
        actions = await _fetch(
            "SELECT action, count(*) AS n FROM audit_log WHERE user_id=$1 "
            "GROUP BY action",
            first.user_id,
        )
        counts = {r["action"]: int(r["n"]) for r in actions}
        assert counts["user.provisioned"] == 1
        assert counts["api_key.created"] == 1
        assert counts["auth.login"] == 2

        with pytest.raises(HTTPException) as collision:
            await provision_authenticated_login(
                email=email,
                provider="oidc",
                key_name="OIDC Default",
                default_role="viewer",
                identity=FederatedIdentity(
                    "oidc", issuer, f"different-subject-{tag}", True
                ),
            )
        assert collision.value.detail["code"] == "oidc_link_required"

        with pytest.raises(HTTPException) as changed:
            await provision_authenticated_login(
                email=f"reassigned-{tag}@example.com",
                provider="oidc",
                key_name="OIDC Default",
                default_role="viewer",
                identity=identity,
            )
        assert changed.value.detail["code"] == "federated_identity_email_changed"
    finally:
        _reset_engine()
        await _cleanup(email.lower())
        _reset_engine()


@pytest.mark.asyncio
async def test_oidc_first_link_requires_verified_email_and_audit_failure_rolls_back(
    monkeypatch,
):
    monkeypatch.setenv(
        "API_KEY_PEPPER", base64.b64encode(b"q" * 32).decode()
    )
    tag = uuid.uuid4().hex[:12]
    unverified_email = f"oidc-unverified-{tag}@example.com"
    rollback_email = f"oidc-rollback-{tag}@example.com"
    issuer = "https://idp.example.test"
    _reset_engine()
    try:
        with pytest.raises(HTTPException) as unverified:
            await provision_authenticated_login(
                email=unverified_email,
                provider="oidc",
                key_name="OIDC Default",
                default_role="viewer",
                identity=FederatedIdentity(
                    "oidc", issuer, f"unverified-{tag}", False
                ),
            )
        assert unverified.value.detail["code"] == "oidc_email_unverified"
        assert not await _fetch(
            "SELECT id FROM users WHERE email_lower=$1", unverified_email.lower()
        )

        async def fail_audit(*_args, **_kwargs):
            raise RuntimeError("audit ledger unavailable")

        monkeypatch.setattr(
            "src.auth.provisioning.append_audit_entry", fail_audit
        )
        with pytest.raises(RuntimeError, match="audit ledger unavailable"):
            await provision_authenticated_login(
                email=rollback_email,
                provider="oidc",
                key_name="OIDC Default",
                default_role="viewer",
                identity=FederatedIdentity(
                    "oidc", issuer, f"rollback-{tag}", True
                ),
            )
        assert not await _fetch(
            "SELECT id FROM users WHERE email_lower=$1", rollback_email.lower()
        )
        assert not await _fetch(
            "SELECT id FROM auth_identities WHERE issuer=$1 AND subject=$2",
            issuer,
            f"rollback-{tag}",
        )
    finally:
        _reset_engine()
        await _cleanup(unverified_email.lower())
        await _cleanup(rollback_email.lower())
        _reset_engine()


@pytest.mark.asyncio
async def test_sso_keys_follow_active_org_and_remain_manageable(monkeypatch):
    """A returning SSO user receives and manages a key in the mapped org."""
    from src.auth.keys_api import list_keys, revoke_key, rotate_key

    monkeypatch.setenv("API_KEY_PEPPER", base64.b64encode(b"r" * 32).decode())
    tag = uuid.uuid4().hex[:12]
    email = f"oidc-org-key-{tag}@example.com"
    issuer = "https://idp.example.test"
    identity = FederatedIdentity("oidc", issuer, f"subject-{tag}", True)
    mapped_org_id = str(ULID())
    group_value = f"cad-key-users-{tag}"
    _reset_engine()
    try:
        first = await provision_authenticated_login(
            email=email,
            provider="oidc",
            key_name="OIDC Default",
            default_role="viewer",
            identity=identity,
            group_detail_key="oidc_group_assignment",
        )
        assert first.key_id is not None
        personal_org_row = await _fetch(
            "SELECT current_org_id FROM users WHERE id=$1", first.user_id
        )
        personal_org_id = str(personal_org_row[0]["current_org_id"])

        await _execute(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES ($1,$2,$3,now())",
            mapped_org_id,
            f"Mapped key org {tag}",
            f"mapped-key-{tag}",
        )
        await _execute(
            "INSERT INTO saml_group_mappings "
            "(org_id, attribute_name, group_value, org_role) "
            "VALUES ($1,'groups',$2,'member')",
            mapped_org_id,
            group_value,
        )

        second = await provision_authenticated_login(
            email=email,
            provider="oidc",
            key_name="OIDC Default",
            default_role="viewer",
            identity=identity,
            group_attributes={"groups": [group_value]},
            group_detail_key="oidc_group_assignment",
        )
        assert second.key_id is not None
        assert second.key_id != first.key_id
        assert second.group_assignment.org_id == mapped_org_id

        current = await _fetch(
            "SELECT current_org_id FROM users WHERE id=$1", first.user_id
        )
        assert str(current[0]["current_org_id"]) == mapped_org_id
        active_keys = await list_keys(user_id=first.user_id)
        assert [key.id for key in active_keys] == [second.key_id]

        rotated = await rotate_key(second.key_id, Response(), user_id=first.user_id)
        assert rotated["id"] != second.key_id
        revoked = await revoke_key(rotated["id"], user_id=first.user_id)
        assert revoked.status_code == 204

        await _execute(
            "UPDATE users SET current_org_id=$1 WHERE id=$2",
            personal_org_id,
            first.user_id,
        )
        personal_keys = await list_keys(user_id=first.user_id)
        assert [key.id for key in personal_keys] == [first.key_id]
    finally:
        _reset_engine()
        await _cleanup(email.lower())
        _reset_engine()
