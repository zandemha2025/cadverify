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


def get_engine():
    """Return (and lazily create) the async engine singleton."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_async_engine(
            os.environ["DATABASE_URL"],
            pool_pre_ping=True,
            pool_size=5,
        )
    return _ENGINE


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
