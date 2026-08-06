"""DB pool sizing is env-driven (F-ARCH-6): DB_POOL_SIZE / DB_MAX_OVERFLOW /
DB_POOL_TIMEOUT / DB_POOL_RECYCLE (F-CAP-1)."""
from __future__ import annotations

import pytest

import src.db.engine as eng


@pytest.fixture
def reset_engine():
    saved_engine, saved_factory = eng._ENGINE, eng._SESSION_FACTORY
    eng._ENGINE = None
    eng._SESSION_FACTORY = None
    yield
    eng._ENGINE = None
    eng._SESSION_FACTORY = None
    eng._ENGINE, eng._SESSION_FACTORY = saved_engine, saved_factory


def test_db_pool_size_from_env(reset_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("DB_POOL_SIZE", "17")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "3")

    engine = eng.get_engine()
    assert engine.sync_engine.pool.size() == 17


def test_db_pool_size_defaults_to_10(reset_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)

    engine = eng.get_engine()
    assert engine.sync_engine.pool.size() == 10


def test_db_pool_timeout_and_recycle_from_env(reset_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "7")
    monkeypatch.setenv("DB_POOL_RECYCLE", "123")

    engine = eng.get_engine()
    pool = engine.sync_engine.pool
    assert pool._timeout == 7
    assert pool._recycle == 123


def test_db_pool_timeout_and_recycle_defaults(reset_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.delenv("DB_POOL_TIMEOUT", raising=False)
    monkeypatch.delenv("DB_POOL_RECYCLE", raising=False)

    engine = eng.get_engine()
    pool = engine.sync_engine.pool
    # Fail fast (10s) instead of SQLAlchemy's 30s default; recycle at 300s.
    assert pool._timeout == 10
    assert pool._recycle == 300
