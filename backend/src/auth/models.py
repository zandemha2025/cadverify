"""Async SQLAlchemy engine + auth-table helpers.

Phase 3 will promote this module to backend/src/db/ and introduce an ORM
registry. Phase 2 uses raw `text()` statements against the tables created
by 0001_create_users_api_keys migration.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_ENGINE = None
_SESSION: Optional[async_sessionmaker[AsyncSession]] = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_async_engine(
            os.environ["DATABASE_URL"], pool_pre_ping=True, pool_size=5
        )
    return _ENGINE


def _session() -> async_sessionmaker[AsyncSession]:
    global _SESSION
    if _SESSION is None:
        _SESSION = async_sessionmaker(_engine(), expire_on_commit=False)
    return _SESSION


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


async def touch_last_used(api_key_id: int) -> None:
    async with _session()() as s:
        await s.execute(
            text("UPDATE api_keys SET last_used_at = now() WHERE id = :i"),
            {"i": api_key_id},
        )
        await s.commit()
