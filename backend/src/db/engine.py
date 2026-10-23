"""Async SQLAlchemy engine singleton, session factory, and FastAPI dependency.

Centralises database connection management for the entire backend.
Phase 2's auth/models.py imports from here instead of maintaining its own
engine/session singletons.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, AsyncGenerator, ClassVar, Optional

from fastapi import Depends
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """ORM declarative base for all mapped classes."""

    if TYPE_CHECKING:
        # Every class mapped here is declared on a real Table (never a select),
        # so ``Model.__table__.update()`` type-checks as it runs.
        __table__: ClassVar[Table]  # pyright: ignore[reportIncompatibleVariableOverride]  # FromClause narrowed to the Table each model really has


_ENGINE = None
_SESSION_FACTORY: Optional[async_sessionmaker[AsyncSession]] = None


def _is_production() -> bool:
    """True when RELEASE names a real deployment (not a dev/test/local build)."""
    return os.getenv("RELEASE", "dev").strip().lower() not in {
        "",
        "dev",
        "development",
        "local",
        "test",
        "ci",
    }


_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres", ""}


def _ensure_prod_tls(url: str) -> str:
    """Default sslmode=require for production databases (M4).

    Local dev (localhost / the docker-compose 'postgres' service) has no TLS,
    so this is a no-op outside production. Released processes reject an
    explicit TLS bypass before either migrations or application queries can
    connect; the strict production deployment contract also rejects local
    plaintext database hosts.
    """
    if not _is_production():
        return url
    if os.getenv("DB_REQUIRE_TLS", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        raise RuntimeError("DB_REQUIRE_TLS cannot be disabled in a released process")

    from urllib.parse import parse_qs, urlsplit

    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    sslmode = [value.lower() for value in query.get("sslmode", [])]
    ssl = [value.lower() for value in query.get("ssl", [])]
    secure_modes = {"require", "verify-ca", "verify-full", "true", "1"}
    if sslmode or ssl:
        if any(value not in secure_modes for value in (*sslmode, *ssl)):
            raise RuntimeError(
                "production database URL contains an insecure TLS mode"
            )
        return url

    host = (parsed.hostname or "").lower()
    if host in _LOCAL_DB_HOSTS or host.endswith(".local"):
        if os.getenv("PRODUCTION_TLS_REQUIRED", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            raise RuntimeError(
                "strict production database URLs must explicitly enable TLS"
            )
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}sslmode=require"


def _async_url(url: str) -> str:
    """Convert postgresql:// to postgresql+asyncpg:// and fix unsupported params."""
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # asyncpg uses 'ssl' not libpq's 'sslmode'. Preserve the requested secure
    # verification level rather than silently downgrading verify-ca/full.
    for mode in ("require", "verify-ca", "verify-full"):
        url = url.replace(f"sslmode={mode}", f"ssl={mode}")
    # asyncpg doesn't support channel_binding param (Neon adds it by default)
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require&", "?").replace("?channel_binding=require", "")
    return url


def get_engine():
    """Return (and lazily create) the async engine singleton."""
    global _ENGINE
    if _ENGINE is None:
        # Pool sizing is env-driven (F-ARCH-6): the batch coordinator and worker
        # concurrency can hold several sessions at once, so operators must be
        # able to size the pool to their deployment instead of a hardcoded 5.
        url = _async_url(_ensure_prod_tls(os.environ["DATABASE_URL"]))
        kwargs = {"pool_pre_ping": True}
        if os.getenv("DB_POOL", "").strip().lower() == "null":
            # Tests (tests/conftest.py) run every async test on its own event
            # loop; a pooled asyncpg connection is bound to the loop that opened
            # it, so the test suite keeps no connections between uses.
            from sqlalchemy.pool import NullPool

            kwargs = {"poolclass": NullPool}
        elif not url.startswith("sqlite"):
            # F-CAP-1: pool_size bumped 5 -> 10 (the /validate family holds a
            # session for the whole 30-80s analysis, and 5+10 overflow=15 was
            # too tight under real concurrency; see admission.py for the
            # companion admission-control gate that keeps in-flight analyses
            # under the pool's real capacity). pool_timeout fails fast (10s)
            # instead of the SQLAlchemy default 30s so a saturated pool surfaces
            # quickly rather than piling up waiters. pool_recycle (300s) drops
            # connections before they go stale/idle-reaped by the DB side.
            kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "10"))
            kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "10"))
            kwargs["pool_timeout"] = int(os.getenv("DB_POOL_TIMEOUT", "10"))
            kwargs["pool_recycle"] = int(os.getenv("DB_POOL_RECYCLE", "300"))
        _ENGINE = create_async_engine(url, **kwargs)
    return _ENGINE


def pool_status() -> str:
    """One log-friendly line on the pool (size, checked out, overflow), or "pool=none"."""
    if _ENGINE is None:
        return "pool=none"
    pool = _ENGINE.pool
    try:
        return (
            f"pool_size={pool.size()} checked_out={pool.checkedout()} "
            f"overflow={pool.overflow()} idle={pool.checkedin()}"
        )
    except Exception:  # NullPool / StaticPool have no counters
        return f"pool={type(pool).__name__}"


async def init_engine() -> None:
    """Initialize the async engine and session factory.

    Called by FastAPI lifespan or worker startup. Safe to call multiple
    times -- subsequent calls are no-ops if engine already exists.
    """
    get_engine()
    get_session_factory()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return (and lazily create) the async session factory singleton."""
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
        )
    return _SESSION_FACTORY


async def _open_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Keep the session alive through streaming reads; always close it."""
    async with get_session_factory()() as session:
        yield session


async def _commit_db_session(
    session: AsyncSession = Depends(_open_db_session),
) -> AsyncGenerator[AsyncSession, None]:
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def get_db_session(
    session: AsyncSession = Depends(_commit_db_session, scope="function"),
) -> AsyncSession:
    """Commit before sending success, while retaining the session for streams.

    Default yield dependencies exit AFTER the response: returning a saved ID
    then can race its commit or even report success for a failed transaction.
    The function-scoped transaction ends before headers; request-scoped cleanup
    still closes the session after batch CSV's remaining read-only queries.
    """
    return session


async def dispose_engine() -> None:
    """Dispose the engine on application shutdown."""
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        await _ENGINE.dispose()
        _ENGINE = None
        _SESSION_FACTORY = None
