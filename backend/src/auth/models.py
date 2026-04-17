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
        return int(row[0])


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
