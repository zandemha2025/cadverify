"""API process resource lifecycle tests."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_lifespan_shutdown_cleans_resources_in_dependency_order(monkeypatch):
    """CAD workers stop before DB disposal and bounded tracing teardown."""
    import main
    from src.db import engine
    from src.obs import tracing
    from src.parsers import parse_pool

    calls: list[str] = []

    def _stop_pool(**kwargs):
        assert kwargs == {"kill": True, "final": True}
        calls.append("parse_pool")

    async def _dispose():
        calls.append("database")

    def _stop_tracing():
        calls.append("tracing")

    monkeypatch.setattr(main, "_prewarm_enabled", lambda: False)
    monkeypatch.setattr(parse_pool, "shutdown", _stop_pool)
    monkeypatch.setattr(engine, "dispose_engine", _dispose)
    monkeypatch.setattr(tracing, "shutdown_tracing", _stop_tracing)

    async with main.lifespan(main.app):
        calls.append("serving")

    assert calls == ["serving", "parse_pool", "database", "tracing"]


@pytest.mark.parametrize("failing", ["parse_pool", "database", "tracing"])
@pytest.mark.asyncio
async def test_lifespan_cleanup_failures_do_not_skip_later_resources(
    monkeypatch, failing
):
    import main
    from src.db import engine
    from src.obs import tracing
    from src.parsers import parse_pool

    calls: list[str] = []

    def _stop_pool(**kwargs):
        del kwargs
        calls.append("parse_pool")
        if failing == "parse_pool":
            raise RuntimeError("parse cleanup failed")

    async def _dispose():
        calls.append("database")
        if failing == "database":
            raise RuntimeError("database cleanup failed")

    def _stop_tracing():
        calls.append("tracing")
        if failing == "tracing":
            raise RuntimeError("tracing cleanup failed")

    monkeypatch.setattr(main, "_prewarm_enabled", lambda: False)
    monkeypatch.setattr(parse_pool, "shutdown", _stop_pool)
    monkeypatch.setattr(engine, "dispose_engine", _dispose)
    monkeypatch.setattr(tracing, "shutdown_tracing", _stop_tracing)

    async with main.lifespan(main.app):
        calls.append("serving")

    assert calls == ["serving", "parse_pool", "database", "tracing"]
