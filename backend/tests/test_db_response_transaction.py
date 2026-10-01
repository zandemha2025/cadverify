"""A successful HTTP response must never precede its database commit."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import pytest

from src.db import engine


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "commit", "handler"])
async def test_transaction_finishes_before_response_and_stream_keeps_session(monkeypatch, failure):
    events = []
    session = AsyncMock()

    async def commit():
        events.append("commit")
        if failure == "commit":
            raise RuntimeError("commit unavailable")

    async def rollback():
        events.append("rollback")

    session.commit.side_effect = commit
    session.rollback.side_effect = rollback

    @asynccontextmanager
    async def open_session():
        events.append("open")
        try:
            yield session
        finally:
            events.append("close")

    monkeypatch.setattr(engine, "get_session_factory", lambda: open_session)
    app = FastAPI()

    @app.post("/saved")
    async def save(db=Depends(engine.get_db_session)):
        assert db is session
        events.append("write")
        if failure == "handler":
            raise HTTPException(409, "write rejected")

        async def content():
            # Batch CSV streams continue querying after response headers.
            assert "close" not in events
            events.append("stream")
            yield b"saved"

        return StreamingResponse(content())

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            events.append(f"status:{message['status']}")

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "method": "POST", "path": "/saved", "raw_path": b"/saved",
        "query_string": b"", "headers": [], "scheme": "http",
        "server": ("test", 80), "client": ("test", 1234), "root_path": "",
    }
    if failure == "commit":
        with pytest.raises(RuntimeError, match="commit unavailable"):
            await app(scope, receive, send)
        assert "status:200" not in events, events
        assert "rollback" in events
        assert "status:500" in events
    else:
        await app(scope, receive, send)
        if failure == "handler":
            assert "commit" not in events
            assert events.index("rollback") < events.index("status:409")
        else:
            assert events.index("commit") < events.index("status:200"), events
            assert events.index("stream") < events.index("close")
    assert events.count("close") == 1
