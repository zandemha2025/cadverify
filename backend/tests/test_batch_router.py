"""Unit tests for batch_router endpoints.

Uses mocked dependencies (no real DB or arq pool).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.batch_router import router
from src.auth.require_api_key import AuthedUser
from src.db.models import Batch, BatchItem

# ---------------------------------------------------------------------------
# Test app setup
# ---------------------------------------------------------------------------

app = FastAPI()
app.include_router(router)

_TEST_USER = AuthedUser(user_id=42, api_key_id=1, key_prefix="cv_live_test")


def _override_auth():
    return _TEST_USER


def _override_session():
    return AsyncMock()


app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_batch(
    ulid: str = "01BATCH00000000000001",
    user_id: int = 42,
    status: str = "processing",
    total_items: int = 10,
    completed_items: int = 5,
    failed_items: int = 1,
) -> MagicMock:
    batch = MagicMock(spec=Batch)
    batch.id = 1
    batch.ulid = ulid
    batch.user_id = user_id
    batch.status = status
    batch.input_mode = "zip"
    batch.total_items = total_items
    batch.completed_items = completed_items
    batch.failed_items = failed_items
    batch.concurrency_limit = 10
    batch.webhook_url = None
    batch.webhook_secret = None
    batch.created_at = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    batch.started_at = datetime(2026, 4, 15, 12, 0, 1, tzinfo=timezone.utc)
    batch.completed_at = None
    return batch


def _make_batch_item(
    ulid: str = "01ITEM000000000000001",
    filename: str = "part1.stl",
    status: str = "completed",
) -> MagicMock:
    item = MagicMock(spec=BatchItem)
    item.id = 1
    item.ulid = ulid
    item.filename = filename
    item.status = status
    item.priority = "normal"
    item.analysis_id = 100
    item.error_message = None
    item.duration_ms = 450.0
    item.created_at = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    return item


# ---------------------------------------------------------------------------
# POST /batch -- create
# ---------------------------------------------------------------------------


@patch("src.jobs.arq_backend.get_arq_pool")
@patch("src.api.batch_router.batch_service")
def test_create_batch_returns_202(mock_bs, mock_pool):
    """POST /batch with ZIP returns 202 + batch_id."""
    from src.db.engine import get_db_session
    from src.auth.require_api_key import require_api_key
    import io
    import zipfile

    app.dependency_overrides[require_api_key] = _override_auth
    app.dependency_overrides[get_db_session] = _override_session

    # Create a minimal ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("part.stl", b"solid test\nendsolid test")
    buf.seek(0)

    mock_batch = _make_batch(status="pending")
    mock_bs.create_batch = AsyncMock(return_value=mock_batch)
    mock_bs.extract_zip_to_items.return_value = [
        {"filename": "part.stl", "path": "/tmp/part.stl", "size": 100}
    ]
    mock_bs.create_batch_items = AsyncMock(return_value=1)
    mock_bs.BATCH_MAX_ZIP_BYTES = 5 * 1024**3

    mock_arq = AsyncMock()
    mock_arq.enqueue_job = AsyncMock()
    mock_pool.return_value = mock_arq

    client = TestClient(app)
    resp = client.post(
        "/api/v1/batch",
        files={"file": ("test.zip", buf, "application/zip")},
    )

    assert resp.status_code == 202
    data = resp.json()
    assert "batch_id" in data
    assert data["status"] == "pending"
    assert "status_url" in data
    # Ensure webhook_secret is NOT in response (T-09-03)
    assert "webhook_secret" not in data

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /batch/{id} -- progress
# ---------------------------------------------------------------------------


@patch("src.api.batch_router.batch_service")
def test_get_batch_progress(mock_bs):
    """GET /batch/{id} returns progress fields."""
    from src.db.engine import get_db_session
    from src.auth.require_api_key import require_api_key

    app.dependency_overrides[require_api_key] = _override_auth
    app.dependency_overrides[get_db_session] = _override_session

    mock_bs.get_batch_progress = AsyncMock(return_value={
        "batch_ulid": "01BATCH00000000000001",
        "status": "processing",
        "input_mode": "zip",
        "total_items": 10,
        "completed_items": 5,
        "failed_items": 1,
        "pending_items": 4,
        "concurrency_limit": 10,
        "created_at": "2026-04-15T12:00:00+00:00",
        "started_at": "2026-04-15T12:00:01+00:00",
        "completed_at": None,
    })

    client = TestClient(app)
    resp = client.get("/api/v1/batch/01BATCH00000000000001")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 10
    assert data["completed_items"] == 5
    assert data["failed_items"] == 1

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /batch/{id} -- not found
# ---------------------------------------------------------------------------


@patch("src.api.batch_router.batch_service")
def test_get_batch_not_found(mock_bs):
    """GET /batch/nonexistent returns 404."""
    from src.db.engine import get_db_session
    from src.auth.require_api_key import require_api_key

    app.dependency_overrides[require_api_key] = _override_auth
    app.dependency_overrides[get_db_session] = _override_session

    mock_bs.get_batch_progress = AsyncMock(return_value=None)

    client = TestClient(app)
    resp = client.get("/api/v1/batch/NONEXISTENT")

    assert resp.status_code == 404

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /batch/{id}/items -- paginated
# ---------------------------------------------------------------------------


def test_get_batch_items_paginated():
    """GET /batch/{id}/items returns paginated items."""
    from src.db.engine import get_db_session
    from src.auth.require_api_key import require_api_key

    app.dependency_overrides[require_api_key] = _override_auth

    mock_session = AsyncMock()
    mock_batch = _make_batch()
    mock_item = _make_batch_item()

    # Mock session.execute for batch lookup
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_batch
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db_session] = lambda: mock_session

    with patch("src.api.batch_router.batch_service") as mock_bs:
        mock_bs.get_batch_items_page = AsyncMock(return_value=([mock_item], False))

        client = TestClient(app)
        resp = client.get("/api/v1/batch/01BATCH00000000000001/items")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["has_more"] is False

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /batch/{id}/results/csv -- CSV export
# ---------------------------------------------------------------------------


def test_csv_export_returns_csv():
    """GET /batch/{id}/results/csv returns text/csv."""
    from src.db.engine import get_db_session
    from src.auth.require_api_key import require_api_key

    app.dependency_overrides[require_api_key] = _override_auth

    mock_session = AsyncMock()
    mock_batch = _make_batch(status="completed")

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_batch
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db_session] = lambda: mock_session

    async def _mock_csv_gen(*args, **kwargs):
        yield "filename,status\n"
        yield "part1.stl,completed\n"

    with patch("src.api.batch_router.batch_service") as mock_bs:
        mock_bs.generate_results_csv = _mock_csv_gen

        client = TestClient(app)
        resp = client.get("/api/v1/batch/01BATCH00000000000001/results/csv")

    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "attachment" in resp.headers.get("content-disposition", "")

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /batch/{id}/cancel
# ---------------------------------------------------------------------------


def test_cancel_batch():
    """POST /batch/{id}/cancel returns cancelled status."""
    from src.db.engine import get_db_session
    from src.auth.require_api_key import require_api_key

    app.dependency_overrides[require_api_key] = _override_auth

    mock_session = AsyncMock()
    mock_batch = _make_batch(status="processing")

    # First call returns batch, second returns pending items
    mock_result1 = MagicMock()
    mock_scalars1 = MagicMock()
    mock_scalars1.first.return_value = mock_batch
    mock_result1.scalars.return_value = mock_scalars1

    mock_result2 = MagicMock()
    mock_scalars2 = MagicMock()
    mock_scalars2.all.return_value = []
    mock_result2.scalars.return_value = mock_scalars2

    mock_session.execute = AsyncMock(side_effect=[mock_result1, mock_result2])
    mock_session.commit = AsyncMock()

    app.dependency_overrides[get_db_session] = lambda: mock_session

    client = TestClient(app)
    resp = client.post("/api/v1/batch/01BATCH00000000000001/cancel")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /batch/{id}/cancel -- already completed (409)
# ---------------------------------------------------------------------------


def test_cancel_completed_batch_409():
    """Cancelling a completed batch returns 409."""
    from src.db.engine import get_db_session
    from src.auth.require_api_key import require_api_key

    app.dependency_overrides[require_api_key] = _override_auth

    mock_session = AsyncMock()
    mock_batch = _make_batch(status="completed")

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_batch
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db_session] = lambda: mock_session

    client = TestClient(app)
    resp = client.post("/api/v1/batch/01BATCH00000000000001/cancel")

    assert resp.status_code == 409

    app.dependency_overrides.clear()
