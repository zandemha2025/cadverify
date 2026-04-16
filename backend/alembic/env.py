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

from src.db.engine import Base  # noqa: E402
import src.db.models  # noqa: E402, F401 — register all models with Base.metadata

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    async def do() -> None:
        url = os.environ["DATABASE_URL"]
        engine = create_async_engine(url, poolclass=None)
        async with engine.connect() as conn:
            await conn.run_sync(
                lambda c: context.configure(connection=c, target_metadata=target_metadata)
            )
            await conn.run_sync(lambda _: context.run_migrations())
        await engine.dispose()

    asyncio.run(do())


run_migrations_online()
