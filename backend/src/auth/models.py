"""Auth-table helpers using raw text() queries.

Engine and session factory are now centralised in src.db.engine (Phase 3).
This module retains its raw-SQL query functions for backward compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.engine import get_engine as _engine, get_session_factory


def _session() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


@dataclass
class ApiKeyRow:
    id: int
    user_id: int
    prefix: str
    hmac_index: str
    secret_hash: str
    revoked_at: object


async def upsert_user(
    email: str,
    google_sub: str | None,
    email_lower: str,
    disposable_flag: bool = False,
) -> int:
    async with _session()() as s:
        row = (
            await s.execute(
                text(
                    "INSERT INTO users (email, email_lower, google_sub, disposable_flag) "
                    "VALUES (:e, :el, :g, :d) "
                    "ON CONFLICT (email_lower) DO UPDATE SET "
                    "google_sub = COALESCE(users.google_sub, EXCLUDED.google_sub) "
                    "RETURNING id"
                ),
                {"e": email, "el": email_lower, "g": google_sub, "d": disposable_flag},
            )
        ).first()
        await s.commit()
        return int(row[0])


async def create_password_user(
    email: str,
    email_lower: str,
    password_hash: str,
    disposable_flag: bool = False,
) -> int | None:
    """INSERT a new email+password user.

    Returns the new user id, or None if email_lower already exists (caller maps
    None -> 409 email_taken). Does NOT attach a password to an existing OAuth/
    SAML row — ON CONFLICT DO NOTHING leaves any existing account untouched.
    """
    async with _session()() as s:
        row = (
            await s.execute(
                text(
                    "INSERT INTO users (email, email_lower, password_hash, auth_provider, disposable_flag) "
                    "VALUES (:e, :el, :ph, 'password', :d) "
                    "ON CONFLICT (email_lower) DO NOTHING RETURNING id"
                ),
                {"e": email, "el": email_lower, "ph": password_hash, "d": disposable_flag},
            )
        ).first()
        await s.commit()
        return int(row[0]) if row else None


async def get_login_credentials(
    email_lower: str,
) -> tuple[int, str | None, str] | None:
    """Return (user_id, password_hash, role) for a normalized email, else None.

    password_hash is None for accounts created via OAuth/SAML/magic-link.
    """
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "SELECT id, password_hash, role FROM users WHERE email_lower = :el"
                ),
                {"el": email_lower},
            )
        ).first()
        return (int(r[0]), r[1], r[2]) if r else None


async def get_user_public(user_id: int) -> tuple[str, str, str] | None:
    """Return (email, role, auth_provider) for GET /auth/me, else None."""
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "SELECT email, role, auth_provider FROM users WHERE id = :u"
                ),
                {"u": user_id},
            )
        ).first()
        return (r[0], r[1], r[2]) if r else None


async def update_password_hash(user_id: int, password_hash: str) -> None:
    """Persist a re-hashed password (Argon2 parameter upgrade on login)."""
    async with _session()() as s:
        await s.execute(
            text("UPDATE users SET password_hash = :ph WHERE id = :u"),
            {"ph": password_hash, "u": user_id},
        )
        await s.commit()


async def create_api_key(
    user_id: int, name: str, prefix: str, hmac_idx: str, secret_hash: str
) -> int:
    async with _session()() as s:
        row = (
            await s.execute(
                text(
                    "INSERT INTO api_keys (user_id, name, prefix, hmac_index, secret_hash) "
                    "VALUES (:u, :n, :p, :h, :s) RETURNING id"
                ),
                {"u": user_id, "n": name, "p": prefix, "h": hmac_idx, "s": secret_hash},
            )
        ).first()
        await s.commit()

        # Audit: api_key.created
        import asyncio
        from src.services.audit_service import fire_and_forget_audit, _lookup_email
        _email = await _lookup_email(user_id)
        asyncio.create_task(fire_and_forget_audit(
            user_id=user_id, user_email=_email,
            action="api_key.created", resource_type="api_key",
            detail={"key_prefix": prefix},
        ))

        return int(row[0])


async def user_has_active_api_key(user_id: int) -> bool:
    """True if the user already holds at least one non-revoked API key.

    Used by the SSO login paths (SAML ACS, Google callback, magic-link verify)
    to avoid minting a fresh key on every single login — a new key should be
    issued only when the account has none active.
    """
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "SELECT 1 FROM api_keys "
                    "WHERE user_id = :u AND revoked_at IS NULL LIMIT 1"
                ),
                {"u": user_id},
            )
        ).first()
        return r is not None


async def lookup_api_key(hmac_idx: str) -> ApiKeyRow | None:
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "SELECT id, user_id, prefix, hmac_index, secret_hash, revoked_at "
                    "FROM api_keys WHERE hmac_index = :h"
                ),
                {"h": hmac_idx},
            )
        ).first()
        return ApiKeyRow(*r) if r else None


async def lookup_user_role(user_id: int) -> str:
    """Return the role column for a user, defaulting to 'analyst'."""
    async with _session()() as s:
        r = (
            await s.execute(
                text("SELECT role FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        ).first()
        return r[0] if r else "analyst"


async def touch_last_used(api_key_id: int) -> None:
    async with _session()() as s:
        await s.execute(
            text("UPDATE api_keys SET last_used_at = now() WHERE id = :i"),
            {"i": api_key_id},
        )
        await s.commit()
