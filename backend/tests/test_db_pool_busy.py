"""An exhausted DB pool answers 503 ``server_busy`` with Retry-After, never 500
(capacity report C7: at 50 browsers, 210 requests answered 500 with
"QueuePool limit of size 10 overflow 10 reached").

* The real app registers the handler, and its body is the existing busy shape.
* With a real Postgres pool of one connection held elsewhere, an ordinary page
  read through the real app waits the pool's timeout and answers busy.
* Cookie auth never reads a pool timeout as "no database": it is busy too, so a
  dev harness can't let an unchecked session through and a release doesn't say
  "authentication unavailable".
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy.exc import TimeoutError as DBPoolTimeout

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")


def _busy_asserts(r) -> None:
    assert r.status_code == 503, r.text
    assert r.headers.get("retry-after") == "5"
    body = r.json()
    assert body["code"] == "server_busy"
    assert body["message"] == "server is at capacity, retry shortly"
    assert body["doc_url"].endswith("server_busy")


def test_main_app_registers_the_pool_handler():
    import main
    from src.api.errors import db_pool_busy_handler

    assert main.app.exception_handlers.get(DBPoolTimeout) is db_pool_busy_handler


def test_busy_body_matches_the_admission_refusal():
    from src.api.admission import _admission_err
    from src.api.errors import server_busy_payload

    refusal = _admission_err("server_busy", "server is at capacity, retry shortly", 5)
    assert refusal.detail == server_busy_payload()


@pytest.mark.asyncio
async def test_pool_timeout_in_a_route_answers_busy():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.api.errors import db_pool_busy_handler

    app = FastAPI()
    app.add_exception_handler(DBPoolTimeout, db_pool_busy_handler)

    @app.get("/page")
    async def page():
        raise DBPoolTimeout(
            "QueuePool limit of size 10 overflow 10 reached, connection timed out, timeout 10.00"
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        _busy_asserts(await c.get("/page"))


@pytest.mark.asyncio
async def test_cookie_auth_treats_pool_timeout_as_busy(monkeypatch):
    import src.auth.require_api_key as rak

    async def _no_room(user_id):
        raise DBPoolTimeout("QueuePool limit reached")

    monkeypatch.setattr(rak, "lookup_session_user", _no_room)
    # Neither the dev "no database" convenience nor a release's
    # auth_dependency_unavailable: the pool timeout itself propagates.
    for production in (False, True):
        monkeypatch.setattr(rak, "is_production", lambda: production)
        with pytest.raises(DBPoolTimeout):
            await rak._session_owner_state(1)


@pytest.mark.asyncio
async def test_dashboard_session_treats_pool_timeout_as_busy(monkeypatch):
    import src.auth.dashboard_session as ds
    import src.auth.models as auth_models

    async def _no_room(user_id):
        raise DBPoolTimeout("QueuePool limit reached")

    monkeypatch.setattr(auth_models, "lookup_session_user", _no_room)
    monkeypatch.setattr(ds, "unsign_payload", lambda cookie: ds.SessionPayload(user_id=1, issued_at=0, session_version=0))

    class _Req:
        cookies = {ds.COOKIE_NAME: "signed"}

    for production in (False, True):
        monkeypatch.setattr(ds, "is_production", lambda: production)
        with pytest.raises(DBPoolTimeout):
            await ds.require_dashboard_session(_Req())


@pytest.mark.asyncio
@pytest.mark.skipif(not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)")
async def test_real_exhausted_pool_answers_busy_through_the_app(monkeypatch):
    """One pooled connection, held by someone else for the whole request: the
    page read waits the pool timeout, then answers 503 server_busy."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import main
    import src.db.engine as eng
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    monkeypatch.delenv("DB_POOL", raising=False)
    monkeypatch.setenv("DB_POOL_SIZE", "1")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "1")
    saved = eng._ENGINE, eng._SESSION_FACTORY
    eng._ENGINE, eng._SESSION_FACTORY = None, None
    # The suite's main-app bypass swaps in a mock session; this test needs the real one.
    saved_session_override = main.app.dependency_overrides.pop(get_db_session, None)
    main.app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=1, api_key_id=0, key_prefix="session", role="analyst"
    )
    engine = eng.get_engine()
    try:
        async with engine.connect() as held:
            await held.execute(text("select 1"))
            assert "checked_out=1" in eng.pool_status()
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t") as c:
                _busy_asserts(await c.get("/api/v1/account/preferences"))
    finally:
        main.app.dependency_overrides.pop(require_api_key, None)
        if saved_session_override is not None:
            main.app.dependency_overrides[get_db_session] = saved_session_override
        await engine.dispose()
        eng._ENGINE, eng._SESSION_FACTORY = saved
