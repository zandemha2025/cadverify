"""Async SQLAlchemy engine singleton, session factory, and FastAPI dependency.

Centralises database connection management for the entire backend.
Phase 2's auth/models.py imports from here instead of maintaining its own
engine/session singletons.
"""
from __future__ import annotations

import os
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """ORM declarative base for all mapped classes."""

    pass


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
    so this is a no-op outside production and for local hosts. Never overrides
    an explicit sslmode/ssl already in the URL. Off-switch: DB_REQUIRE_TLS=0.
    """
    if os.getenv("DB_REQUIRE_TLS", "1") == "0" or not _is_production():
        return url
    lowered = url.lower()
    if "sslmode=" in lowered or "ssl=" in lowered:
        return url
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    if host in _LOCAL_DB_HOSTS or host.endswith(".local"):
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}sslmode=require"


def _async_url(url: str) -> str:
    """Convert postgresql:// to postgresql+asyncpg:// and fix unsupported params."""
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # asyncpg uses 'ssl' not 'sslmode'
    url = url.replace("sslmode=require", "ssl=require")
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
        if not url.startswith("sqlite"):
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


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends-compatible generator yielding a request-scoped session.

    Commits on success, rolls back on error, always closes.
    """
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the engine on application shutdown."""
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        await _ENGINE.dispose()
        _ENGINE = None
        _SESSION_FACTORY = None
