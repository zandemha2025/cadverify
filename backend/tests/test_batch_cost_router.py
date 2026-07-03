"""Router-level tests for the W3 job_type gate on POST /batch.

Drives the endpoint through an ASGI client with auth + DB session overridden.
The job_type validation (422) and the BATCH_COST_ENABLED gate (501) both fire
BEFORE any file/DB work, so these need no Postgres. Also asserts the gate lets a
cost batch THROUGH when the flag is on (it then fails on the missing upload,
proving the gate is not what blocked it) — and that DFM is never gated.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


def _build_app():
    from fastapi import FastAPI

    from src.api.batch_router import router as batch_router
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    app = FastAPI()
    app.include_router(batch_router)

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=1, api_key_id=0, key_prefix="session", role="analyst"
    )

    async def _fake_db():
        yield None  # never used: the gate returns before touching the session

    app.dependency_overrides[get_db_session] = _fake_db
    return app


@pytest.mark.asyncio
async def test_invalid_job_type_is_422():
    from httpx import ASGITransport, AsyncClient

    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.post("/api/v1/batch", data={"job_type": "bogus"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "INVALID_JOB_TYPE"


@pytest.mark.asyncio
async def test_cost_batch_rejected_when_flag_off(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("BATCH_COST_ENABLED", "0")
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.post("/api/v1/batch", data={"job_type": "cost"})
    assert r.status_code == 501, r.text
    assert r.json()["detail"]["code"] == "BATCH_COST_NOT_ENABLED"


@pytest.mark.asyncio
async def test_cost_batch_passes_gate_when_flag_on(monkeypatch):
    """Flag ON (default): the cost gate lets it through, so it fails later on the
    missing upload (400) — proving the 501 was the gate, not a hard block."""
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("BATCH_COST_ENABLED", "1")
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.post("/api/v1/batch", data={"job_type": "cost"})
    # No file and no s3_bucket → the input-mode check (which runs AFTER the gate)
    # returns 400, not 501.
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_dfm_batch_never_gated(monkeypatch):
    """DFM is never gated even with the cost flag off — it reaches the input-mode
    check (400 on the missing upload)."""
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("BATCH_COST_ENABLED", "0")
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.post("/api/v1/batch", data={"job_type": "dfm"})
    assert r.status_code == 400, r.text
