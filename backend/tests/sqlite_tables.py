"""Hermetic in-memory SQLite copies of real ORM tables for storage-seam tests.

The production tables are Postgres-shaped: JSONB columns, BIGINT surrogate keys
and ``'false'``/``'true'`` boolean server defaults. ``sqlite_sessionmaker`` copies
the requested models' tables into a scratch ``MetaData`` and adapts only their
DDL: JSONB renders as generic JSON, a single BIGINT primary key becomes SQLite's
INTEGER rowid alias (so ORM inserts get autoincrement ids), and boolean server
defaults render as 0/1. The ORM classes and the service/route code under test
are untouched, so their own statements run against these tables unmodified.

Pass every table a requested table has a foreign key to (``create_all`` raises
``NoReferencedTableError`` otherwise).
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Integer, MetaData, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.schema import DefaultClause

_BOOL_DEFAULTS = {"false": "0", "true": "1"}


def _sqlite_bool_default(col) -> None:
    default = col.server_default
    arg = getattr(default, "arg", None)
    literal = str(getattr(arg, "text", arg)).strip().lower()
    if literal in _BOOL_DEFAULTS:
        clause = DefaultClause(text(_BOOL_DEFAULTS[literal]))
        clause.column = col
        col.server_default = clause


async def sqlite_sessionmaker(*models) -> tuple[AsyncEngine, async_sessionmaker]:
    md = MetaData()
    for model in models:
        table = model.__table__.to_metadata(md)
        single_pk = len(table.primary_key.columns) == 1
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
            if single_pk and col.primary_key and isinstance(col.type, BigInteger):
                col.type = Integer()
            if isinstance(col.type, Boolean) and col.server_default is not None:
                _sqlite_bool_default(col)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(md.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
