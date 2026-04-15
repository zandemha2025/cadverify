"""Alembic env.py — async engine variant.

Migrations are hand-written (no autogenerate); Phase 3 may introduce
SQLAlchemy ORM models and promote target_metadata to a real registry.
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = None  # no autogenerate


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
