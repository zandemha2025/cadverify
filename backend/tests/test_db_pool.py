"""DB pool sizing is env-driven (F-ARCH-6): DB_POOL_SIZE / DB_MAX_OVERFLOW."""
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


def test_db_pool_size_defaults_to_5(reset_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)

    engine = eng.get_engine()
    assert engine.sync_engine.pool.size() == 5
