"""Atomic authenticated-user provisioning and session audit boundary.

Federated/email authentication paths use this one transaction for user/org/key
state, optional IdP group assignment, and required audit rows. A database or
audit failure therefore leaves no partially provisioned identity or credential
and no signed session may be issued by the caller.
"""
from __future__ import annotations

from src.config.public_urls import error_doc_url

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.disposable import normalize_email
from src.auth.hashing import hmac_index, mint_token
from src.auth.models import _account_deactivated, _session
from src.auth.org_context import ensure_personal_org, resolve_org
from src.services.audit_service import append_audit_entry
from src.services.org_saml_service import (
    SamlGroupAssignment,
    apply_saml_group_assignment,
)


@dataclass(frozen=True)
class FederatedIdentity:
    provider: str
    issuer: str
    subject: str
    email_verified: bool


@dataclass(frozen=True)
class ProvisionedLogin:
    user_id: int
    user_email: str
    session_version: int
    created: bool
    group_assignment: SamlGroupAssignment
    key_id: int | None = None
    key_prefix: str | None = None
    key_token: str | None = None


def _auth_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={
            "code": code,
            "message": message,
            "doc_url": error_doc_url(code),
        },
    )


async def _lock_key(session: AsyncSession, key: str) -> None:
    """Serialize first-login races on Postgres without a table-wide lock."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": key},
        )


async def _email_user(
    session: AsyncSession,
    *,
    email: str,
    provider: str,
    default_role: str,
) -> tuple[int, str, bool]:
    """Get/create an email-authenticated user while holding a transaction lock."""
    email_clean = email.strip()
    email_lower = normalize_email(email_clean)
    await _lock_key(session, f"email:{email_lower}")
    existing = (
        await session.execute(
            text(
                "SELECT id, email, is_active FROM users "
                "WHERE email_lower = :email_lower FOR UPDATE"
            ),
            {"email_lower": email_lower},
        )
    ).first()
    if existing is not None:
        if existing[2] is False:
            raise _account_deactivated()
        # Preserve established credentials/providers; only replace the original
        # Google default when it never had a Google subject (legacy behavior).
        await session.execute(
            text(
                "UPDATE users SET auth_provider = CASE "
                "WHEN google_sub IS NULL AND auth_provider = 'google' "
                "THEN :provider ELSE auth_provider END WHERE id = :user_id"
            ),
            {"provider": provider, "user_id": int(existing[0])},
        )
        return int(existing[0]), str(existing[1]), False

    row = (
        await session.execute(
            text(
                "INSERT INTO users "
                "(email, email_lower, google_sub, auth_provider, disposable_flag, role) "
                "VALUES (:email, :email_lower, NULL, :provider, false, :role) "
                "RETURNING id"
            ),
            {
                "email": email_clean,
                "email_lower": email_lower,
                "provider": provider,
                "role": default_role,
            },
        )
    ).first()
    if row is None:
        raise RuntimeError("user insert returned no row")
    return int(row[0]), email_clean, True


async def _federated_user(
    session: AsyncSession,
    *,
    identity: FederatedIdentity,
    email: str | None,
    default_role: str,
) -> tuple[int, str, bool]:
    """Resolve immutable issuer+subject, creating only a brand-new account.

    A verified email is accepted as bootstrap metadata for a new account. It is
    deliberately *not* sufficient to attach a new subject to an existing user;
    that requires an authenticated/admin-approved linking workflow.
    """
    provider = identity.provider.strip().lower()
    issuer = identity.issuer.strip().rstrip("/")
    subject = identity.subject.strip()
    if provider not in {"oidc", "saml"} or not issuer or not subject:
        raise _auth_error(400, "federated_identity_invalid", "Identity binding is incomplete.")
    if len(issuer) > 2048 or len(subject) > 2048:
        raise _auth_error(400, "federated_identity_invalid", "Identity binding is too long.")

    await _lock_key(session, f"identity:{provider}:{issuer}:{subject}")
    mapped = (
        await session.execute(
            text(
                "SELECT u.id, u.email, u.email_lower, u.is_active "
                "FROM auth_identities ai JOIN users u ON u.id = ai.user_id "
                "WHERE ai.provider = :provider AND ai.issuer = :issuer "
                "AND ai.subject = :subject FOR UPDATE"
            ),
            {"provider": provider, "issuer": issuer, "subject": subject},
        )
    ).first()
    if mapped is not None:
        if mapped[3] is False:
            raise _account_deactivated()
        if email and normalize_email(email) != str(mapped[2]):
            raise _auth_error(
                403,
                "federated_identity_email_changed",
                "The identity email no longer matches its approved account binding.",
            )
        await session.execute(
            text(
                "UPDATE auth_identities SET last_login_at = now() "
                "WHERE provider = :provider AND issuer = :issuer AND subject = :subject"
            ),
            {"provider": provider, "issuer": issuer, "subject": subject},
        )
        return int(mapped[0]), str(mapped[1]), False

    if not email:
        raise _auth_error(
            400,
            "oidc_no_email",
            "A verified email is required to create a new federated account.",
        )
    if identity.email_verified is not True:
        raise _auth_error(
            403,
            "oidc_email_unverified",
            "The identity provider must verify the email before first sign-in.",
        )

    email_clean = email.strip()
    email_lower = normalize_email(email_clean)
    await _lock_key(session, f"email:{email_lower}")
    collision = (
        await session.execute(
            text("SELECT id FROM users WHERE email_lower = :email_lower FOR UPDATE"),
            {"email_lower": email_lower},
        )
    ).first()
    if collision is not None:
        raise _auth_error(
            409,
            "oidc_link_required",
            "An account already uses this email. Sign in to that account and approve identity linking.",
        )

    user = (
        await session.execute(
            text(
                "INSERT INTO users "
                "(email, email_lower, google_sub, auth_provider, disposable_flag, role) "
                "VALUES (:email, :email_lower, NULL, :provider, false, :role) "
                "RETURNING id"
            ),
            {
                "email": email_clean,
                "email_lower": email_lower,
                "provider": provider,
                "role": default_role,
            },
        )
    ).first()
    if user is None:
        raise RuntimeError("federated user insert returned no row")
    user_id = int(user[0])
    await session.execute(
        text(
            "INSERT INTO auth_identities "
            "(provider, issuer, subject, user_id, email_at_link) "
            "VALUES (:provider, :issuer, :subject, :user_id, :email)"
        ),
        {
            "provider": provider,
            "issuer": issuer,
            "subject": subject,
            "user_id": user_id,
            "email": email_lower,
        },
    )
    return user_id, email_clean, True


async def _ensure_key(
    session: AsyncSession,
    *,
    user_id: int,
    org_id: str,
    key_name: str,
) -> tuple[int | None, str | None, str | None]:
    active = (
        await session.execute(
            text(
                "SELECT id FROM api_keys WHERE user_id = :user_id "
                "AND org_id = :org_id "
                "AND revoked_at IS NULL LIMIT 1 FOR UPDATE"
            ),
            {"user_id": user_id, "org_id": org_id},
        )
    ).first()
    if active is not None:
        return None, None, None

    token, prefix, secret_hash = mint_token()
    row = (
        await session.execute(
            text(
                "INSERT INTO api_keys "
                "(user_id, org_id, name, prefix, hmac_index, secret_hash) "
                "VALUES (:user_id, :org_id, :name, :prefix, :hmac_index, :secret_hash) "
                "RETURNING id"
            ),
            {
                "user_id": user_id,
                "org_id": org_id,
                "name": key_name,
                "prefix": prefix,
                "hmac_index": hmac_index(token),
                "secret_hash": secret_hash,
            },
        )
    ).first()
    if row is None:
        raise RuntimeError("API key insert returned no row")
    key_id = int(row[0])
    await append_audit_entry(
        session,
        user_id,
        "api_key.created",
        "api_key",
        str(key_id),
        {"key_prefix": prefix, "provisioned_with_login": True},
        org_id=org_id,
    )
    return key_id, prefix, token


async def provision_authenticated_login(
    *,
    email: str | None,
    provider: str,
    key_name: str,
    default_role: str,
    identity: FederatedIdentity | None = None,
    group_attributes: dict[str, list[str]] | None = None,
    group_detail_key: str | None = None,
    login_detail: dict[str, Any] | None = None,
) -> ProvisionedLogin:
    """Provision and audit one successful authentication in one commit."""
    async with _session()() as session:
        try:
            if identity is not None:
                user_id, stored_email, created = await _federated_user(
                    session,
                    identity=identity,
                    email=email,
                    default_role=default_role,
                )
            else:
                if not email:
                    raise _auth_error(400, "auth_email_required", "Email is required.")
                user_id, stored_email, created = await _email_user(
                    session,
                    email=email,
                    provider=provider,
                    default_role=default_role,
                )

            org_id = await ensure_personal_org(session, user_id, stored_email)
            assignment = SamlGroupAssignment(matched=False)
            if group_attributes:
                assignment = await apply_saml_group_assignment(
                    session, user_id, group_attributes
                )

            # Resolve through the same validated active-org rule used by the
            # dashboard and API-key management. Group assignment updates
            # ``current_org_id`` before this read; an existing multi-org user
            # without group claims retains their already-selected live org.
            effective_org_id = await resolve_org(session, user_id) or org_id
            key_id, key_prefix, key_token = await _ensure_key(
                session,
                user_id=user_id,
                org_id=effective_org_id,
                key_name=key_name,
            )
            if created:
                await append_audit_entry(
                    session,
                    user_id,
                    "user.provisioned",
                    "user",
                    str(user_id),
                    {"auth_provider": provider, "role": default_role},
                    user_email=stored_email,
                    org_id=org_id,
                )

            detail: dict[str, Any] = {"auth_provider": provider, **(login_detail or {})}
            if group_detail_key:
                detail[group_detail_key] = assignment.to_audit_detail()
            await append_audit_entry(
                session,
                user_id,
                "auth.login",
                "session",
                detail=detail,
                user_email=stored_email,
                org_id=effective_org_id,
            )
            version_row = (
                await session.execute(
                    text("SELECT session_version FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
            ).first()
            if version_row is None:
                raise RuntimeError("provisioned user disappeared before commit")
            session_version = int(version_row[0])
            await session.commit()
            return ProvisionedLogin(
                user_id=user_id,
                user_email=stored_email,
                session_version=session_version,
                created=created,
                group_assignment=assignment,
                key_id=key_id,
                key_prefix=key_prefix,
                key_token=key_token,
            )
        except Exception:
            await session.rollback()
            raise
