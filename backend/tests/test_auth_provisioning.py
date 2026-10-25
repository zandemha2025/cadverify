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

        # An SSO sign-in mints no API key (nowhere to show its secret).
        assert first.created is True and first.key_token is None
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
        assert "api_key.created" not in counts
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
async def test_sso_sign_in_mints_no_key_and_keys_made_later_follow_the_active_org(monkeypatch):
    """A SAML/OIDC sign-in has nowhere to show a secret, so it mints no key.

    Keys the person makes on the API page live in the org that was active,
    and stay listed and manageable when a group mapping moves them.
    """
    from src.auth.keys_api import CreateIn, create_key, list_keys, revoke_key, rotate_key

    monkeypatch.setenv("API_KEY_PEPPER", base64.b64encode(b"r" * 32).decode())
    tag = uuid.uuid4().hex[:12]
    email = f"oidc-org-key-{tag}@example.com"
    issuer = "https://idp.example.test"
    identity = FederatedIdentity("oidc", issuer, f"subject-{tag}", True)
    mapped_org_id = str(ULID())
    # The mapped org owns this deployment's IdP, so its mappings apply.
    monkeypatch.setenv("SSO_ORG_ID", mapped_org_id)
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
        assert first.key_id is None and first.key_token is None
        assert await _fetch("SELECT 1 FROM api_keys WHERE user_id=$1", first.user_id) == []
        personal_org_row = await _fetch(
            "SELECT current_org_id FROM users WHERE id=$1", first.user_id
        )
        personal_org_id = str(personal_org_row[0]["current_org_id"])
        personal_key = await create_key(CreateIn(name="personal"), Response(), user_id=first.user_id)

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
        assert second.key_id is None
        assert second.group_assignment.org_id == mapped_org_id
        current = await _fetch(
            "SELECT current_org_id FROM users WHERE id=$1", first.user_id
        )
        assert str(current[0]["current_org_id"]) == mapped_org_id

        mapped_key = await create_key(CreateIn(name="mapped"), Response(), user_id=first.user_id)
        assert [key.id for key in await list_keys(user_id=first.user_id)] == [mapped_key["id"]]
        rotated = await rotate_key(mapped_key["id"], Response(), user_id=first.user_id)
        assert rotated["id"] != mapped_key["id"]
        revoked = await revoke_key(rotated["id"], user_id=first.user_id)
        assert revoked.status_code == 204

        await _execute(
            "UPDATE users SET current_org_id=$1 WHERE id=$2",
            personal_org_id,
            first.user_id,
        )
        personal_keys = await list_keys(user_id=first.user_id)
        assert [key.id for key in personal_keys] == [personal_key["id"]]
    finally:
        _reset_engine()
        await _cleanup(email.lower())
        _reset_engine()


@pytest.mark.asyncio
async def test_email_link_sign_in_mints_one_read_only_key_that_expires(monkeypatch):
    monkeypatch.setenv("API_KEY_PEPPER", base64.b64encode(b"m" * 32).decode())
    email = f"magic-key-{uuid.uuid4().hex[:12]}@example.com"
    _reset_engine()
    try:
        first = await provision_authenticated_login(
            email=email, provider="magic_link", key_name="Default", default_role="analyst"
        )
        assert first.key_id is not None and first.key_token.startswith("cv_live_")
        rows = await _fetch(
            "SELECT scope, expires_at - created_at AS life FROM api_keys WHERE id=$1",
            first.key_id,
        )
        assert rows[0]["scope"] == "read" and rows[0]["life"].days == 90
        again = await provision_authenticated_login(
            email=email, provider="magic_link", key_name="Default", default_role="analyst"
        )
        assert again.key_id is None
    finally:
        _reset_engine()
        await _cleanup(email.lower())
        _reset_engine()
