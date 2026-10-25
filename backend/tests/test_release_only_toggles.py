"""In a release (RELEASE set to a non-dev value) test and introspection
surfaces are off unless explicitly enabled.

- The release-evidence fault headers are ignored, even with the E2E token
  configured and supplied.
- /docs, /redoc, /openapi.json and /scalar are not served unless
  API_DOCS_ENABLED=1.
- /metrics answers 404 unless METRICS_ENABLED=1.

Outside a release (local, test, CI) each keeps working as before.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.config import api_docs
from src.services.release_fault_injection import (
    BATCH_FAULT_MODES,
    FAULT_MODE_HEADER,
    FAULT_TOKEN_HEADER,
    requested_release_fault,
)


def _fault_request(token: str, mode: str):
    return SimpleNamespace(headers={FAULT_TOKEN_HEADER: token, FAULT_MODE_HEADER: mode})


async def _get(app, path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path)


# ── fault injection ─────────────────────────────────────────────────────────
def test_fault_headers_are_ignored_in_a_release(monkeypatch):
    monkeypatch.setenv("E2E_FAULT_INJECTION_TOKEN", "release-secret-token")
    monkeypatch.setenv("RELEASE", "3f2a9c1")
    assert requested_release_fault(_fault_request("release-secret-token", "batch_queue"), BATCH_FAULT_MODES) is None


def test_fault_headers_still_work_outside_a_release(monkeypatch):
    monkeypatch.setenv("E2E_FAULT_INJECTION_TOKEN", "release-secret-token")
    for release in ("", "dev", "test", "ci"):
        monkeypatch.setenv("RELEASE", release)
        req = _fault_request("release-secret-token", "batch_queue")
        assert requested_release_fault(req, BATCH_FAULT_MODES) == "batch_queue"


# ── API docs ────────────────────────────────────────────────────────────────
def _docs_app() -> FastAPI:
    app = FastAPI(**api_docs.fastapi_docs_kwargs())
    api_docs.mount_scalar(app)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/scalar"])
async def test_docs_are_off_in_a_release(monkeypatch, path):
    monkeypatch.setenv("RELEASE", "3f2a9c1")
    monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
    assert (await _get(_docs_app(), path)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_docs_can_be_enabled_in_a_release(monkeypatch, path):
    monkeypatch.setenv("RELEASE", "3f2a9c1")
    monkeypatch.setenv("API_DOCS_ENABLED", "1")
    assert (await _get(_docs_app(), path)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_docs_stay_on_outside_a_release(monkeypatch, path):
    monkeypatch.setenv("RELEASE", "dev")
    monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
    assert (await _get(_docs_app(), path)).status_code == 200


def test_the_app_uses_the_docs_setting():
    import main

    assert main.app.docs_url == api_docs.fastapi_docs_kwargs()["docs_url"]
    assert main.app.openapi_url == api_docs.fastapi_docs_kwargs()["openapi_url"]


# ── metrics ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _no_queue_scan(monkeypatch):
    """/metrics refreshes queue gauges from the database; these tests need none."""
    async def _skip(*_a, **_k):
        raise RuntimeError("no database in this test")

    monkeypatch.setattr("src.services.ops_health_service.summarize_queue_health", _skip)


def _metrics_app() -> FastAPI:
    from src.api.metrics import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_metrics_are_off_by_default_in_a_release(monkeypatch):
    monkeypatch.setenv("RELEASE", "3f2a9c1")
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    assert (await _get(_metrics_app(), "/metrics")).status_code == 404


@pytest.mark.asyncio
async def test_metrics_can_be_enabled_in_a_release(monkeypatch):
    monkeypatch.setenv("RELEASE", "3f2a9c1")
    monkeypatch.setenv("METRICS_ENABLED", "1")
    assert (await _get(_metrics_app(), "/metrics")).status_code in (200, 503)


@pytest.mark.asyncio
async def test_metrics_stay_on_by_default_outside_a_release(monkeypatch):
    monkeypatch.setenv("RELEASE", "dev")
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    assert (await _get(_metrics_app(), "/metrics")).status_code in (200, 503)
