"""A saved receipt must never leave the server before its transaction commits."""
import inspect
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes import validate_cost
from src.api.batch_router import get_batch_results_csv
from src.db import engine


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_fails", [False, True])
async def test_saved_response_waits_for_commit(monkeypatch, commit_fails):
    session = AsyncMock()
    session.__aenter__.return_value = session
    if commit_fails:
        session.commit.side_effect = RuntimeError("commit failed")
    monkeypatch.setattr(engine, "get_session_factory", lambda: lambda: session)
    # Exercise the real route's dependency declaration, including its scope.
    dependency = inspect.signature(validate_cost).parameters["session"].default
    app = FastAPI()

    @app.post("/save")
    async def save(db: AsyncSession = dependency):
        await db.flush()
        return {"saved": {"id": "new-decision"}}

    responses = []

    async def send(message):
        if message["type"] == "http.response.start":
            responses.append((message["status"], session.commit.await_count))

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/save",
             "raw_path": b"/save", "query_string": b"", "headers": [],
             "client": ("127.0.0.1", 1), "server": ("test", 80)}
    if commit_fails:
        with pytest.raises(RuntimeError, match="commit failed"):
            await app(scope, receive, send)
        assert responses == [(500, 1)]
        session.rollback.assert_awaited_once()
    else:
        await app(scope, receive, send)
        assert responses == [(200, 1)]
        session.rollback.assert_not_awaited()
    session.__aexit__.assert_awaited_once()


def test_csv_session_remains_open_during_stream(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(engine, "get_session_factory", lambda: lambda: session)
    dependency = inspect.signature(get_batch_results_csv).parameters["session"].default
    app = FastAPI()

    @app.get("/csv")
    async def csv(db: AsyncSession = dependency):
        async def pages():
            for _ in range(2):
                db.__aexit__.assert_not_awaited()
                await db.execute("next page")
                yield "row\n"
        return StreamingResponse(pages(), media_type="text/csv")

    assert TestClient(app).get("/csv").text == "row\nrow\n"
    assert session.execute.await_count == 2
    session.__aexit__.assert_awaited_once()
