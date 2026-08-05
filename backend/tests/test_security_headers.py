"""Tests for the SecurityHeadersMiddleware (S6)."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from src.api.security_headers import SECURITY_HEADERS, SecurityHeadersMiddleware


def _app(enabled: bool | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, enabled=enabled)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise HTTPException(status_code=418, detail="teapot")

    @app.get("/stream")
    def stream():
        def gen():
            yield b"a"
            yield b"b"

        return StreamingResponse(gen(), media_type="text/plain")

    return app


def test_all_security_headers_present():
    client = TestClient(_app(enabled=True))
    resp = client.get("/ok")
    for key, value in SECURITY_HEADERS.items():
        assert resp.headers.get(key) == value


def test_server_header_replaced():
    client = TestClient(_app(enabled=True))
    resp = client.get("/ok")
    assert resp.headers.get("server") == "ProofShape"
    assert "uvicorn" not in resp.headers.get("server", "").lower()


def test_headers_on_error_responses():
    client = TestClient(_app(enabled=True), raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 418
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"


def test_streaming_response_not_buffered_but_headers_set():
    client = TestClient(_app(enabled=True))
    resp = client.get("/stream")
    assert resp.status_code == 200
    assert resp.content == b"ab"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_off_switch_omits_headers():
    client = TestClient(_app(enabled=False))
    resp = client.get("/ok")
    assert resp.headers.get("X-Content-Type-Options") is None
    assert resp.headers.get("X-Frame-Options") is None


def test_env_off_switch(monkeypatch):
    monkeypatch.setenv("SECURITY_HEADERS_ENABLED", "0")
    # enabled=None -> read env at construction time.
    client = TestClient(_app(enabled=None))
    resp = client.get("/ok")
    assert resp.headers.get("X-Content-Type-Options") is None
