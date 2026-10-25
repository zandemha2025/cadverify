"""Batch and catalog CSV downloads name their file from the stored batch id,
never from the raw ``batch_id`` path parameter."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import batch_router
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session

ULID = "01HXBATCH00000000000000001"
ODD = 'x";filename*=UTF-8\'\'evil.html;x="'


def _app(session) -> FastAPI:
    app = FastAPI()
    app.include_router(batch_router.router)
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=1, api_key_id=0, key_prefix="session", role="analyst"
    )

    async def _session():
        yield session

    app.dependency_overrides[get_db_session] = _session
    return app


async def _get(app: FastAPI, path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_catalog_csv_filename_comes_from_the_stored_batch(monkeypatch):
    batch = SimpleNamespace(ulid=ULID)
    monkeypatch.setattr(batch_router, "_catalog_batch", AsyncMock(return_value=batch))
    monkeypatch.setattr(batch_router.catalog_run_service, "build_board", AsyncMock(return_value={}))
    monkeypatch.setattr(batch_router.catalog_run_service, "board_csv_rows", lambda board: ["a,b\n"])

    resp = await _get(_app(AsyncMock()), f"/api/v1/batch/{ODD}/catalog.csv")

    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == f'attachment; filename="catalog_run_{ULID}.csv"'


@pytest.mark.asyncio
async def test_results_csv_filename_comes_from_the_stored_batch(monkeypatch):
    batch = SimpleNamespace(ulid=ULID, status="completed", id=7, job_type="dfm")
    result = MagicMock()
    result.scalars.return_value.first.return_value = batch
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    async def _rows(*_args, **_kwargs):
        yield "a,b\n"

    monkeypatch.setattr(batch_router.batch_service, "generate_results_csv", _rows)

    resp = await _get(_app(session), f"/api/v1/batch/{ODD}/results/csv")

    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == f'attachment; filename="batch_{ULID}_results.csv"'


def test_download_stem_keeps_only_plain_characters():
    assert batch_router._download_stem(ULID) == ULID
    assert batch_router._download_stem('a"b;c\r\nd/../e') == "a_b_c_d_.._e"
    assert batch_router._download_stem("") == "batch"
