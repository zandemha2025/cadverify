"""Alembic env.py — async engine variant with ORM metadata.

Uses ORM Base.metadata for autogenerate support.
"""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure backend/src is on sys.path so ORM models can be imported
_backend_dir = str(Path(__file__).resolve().parents[1])
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from src.db.engine import Base, _async_url, _ensure_prod_tls  # noqa: E402
import src.db.models  # noqa: E402, F401 — register all models with Base.metadata

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    async def do() -> None:
        url = _async_url(_ensure_prod_tls(os.environ["DATABASE_URL"]))
        engine = create_async_engine(url, poolclass=None)

        def _run(connection) -> None:
            context.configure(connection=connection, target_metadata=target_metadata)
            # begin_transaction() is required so the DDL + alembic_version bump
            # are committed; without it the async connection rolls back on close.
            with context.begin_transaction():
                context.run_migrations()

        async with engine.connect() as conn:
            await conn.run_sync(_run)
        await engine.dispose()

    asyncio.run(do())


run_migrations_online()
