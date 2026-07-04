"""Enterprise hardening tests for the batch pipeline (F-ARCH-9 + F-ARCH-5).

Covers two audit findings on POST /api/v1/batch and the ZIP extractor:

  F-ARCH-9 (memory-DoS): the ZIP upload must be rejected *before* it is fully
  buffered in RAM -- via an early Content-Length 413 and a streamed size check
  that aborts mid-read. And same-basename entries in different folders must NOT
  silently overwrite each other.

  F-ARCH-5 (S3 orphan): s3_bucket / s3_prefix / manifest_url input must be
  rejected up front with a 501 BEFORE any Batch row is created.

Mirrors tests/test_batch_router.py and tests/test_batch_cost_router.py -- mocked
dependencies, no Postgres/Redis required.
"""
from __future__ import annotations

import io
import os
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.batch_router import router
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Batch
from src.services import batch_service
from src.services.batch_service import (
    ZipTooLargeError,
    extract_zip_to_items,
    stream_upload_to_tempfile,
)

_TEST_USER = AuthedUser(user_id=42, api_key_id=1, key_prefix="cv_live_test")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: _TEST_USER
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    return app


def _make_batch() -> MagicMock:
    b = MagicMock(spec=Batch)
    b.id = 1
    b.ulid = "01BATCH00000000000001"
    b.status = "pending"
    b.input_mode = "zip"
    return b


def _small_zip() -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("part.stl", b"solid test\nendsolid test")
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# F-ARCH-9: streamed size check aborts mid-read (never buffers the whole thing)
# ---------------------------------------------------------------------------


class _CountingUpload:
    """Fake UploadFile that streams an effectively-unbounded body.

    read() never returns empty, so if the size guard buffered the *whole* upload
    it would loop forever. The test asserts it aborts after only a few reads.
    """

    def __init__(self, chunk: bytes = b"x" * 1024):
        self.reads = 0
        self._chunk = chunk

    async def read(self, size: int = -1) -> bytes:
        self.reads += 1
        return self._chunk


@pytest.mark.asyncio
async def test_stream_upload_aborts_before_full_buffer():
    up = _CountingUpload(chunk=b"x" * 1024)
    with pytest.raises(ZipTooLargeError):
        # Cap of 4 KiB against a 1 KiB/read infinite stream: must reject fast.
        await stream_upload_to_tempfile(up, max_bytes=4 * 1024, chunk_size=1024)
    # Aborted after a handful of reads -- proof it did not buffer the whole
    # (unbounded) upload into memory before rejecting.
    assert up.reads < 50


@pytest.mark.asyncio
async def test_stream_upload_leaves_no_tempfile_on_reject(tmp_path, monkeypatch):
    created: list[str] = []
    real_mkstemp = batch_service.tempfile.mkstemp

    def _tracking_mkstemp(*a, **kw):
        fd, path = real_mkstemp(*a, **kw)
        created.append(path)
        return fd, path

    monkeypatch.setattr(batch_service.tempfile, "mkstemp", _tracking_mkstemp)

    up = _CountingUpload(chunk=b"y" * 1024)
    with pytest.raises(ZipTooLargeError):
        await stream_upload_to_tempfile(up, max_bytes=2 * 1024, chunk_size=1024)

    assert created, "expected a temp file to have been opened"
    # The partial temp file must be cleaned up on rejection (no disk leak).
    assert not any(os.path.exists(p) for p in created)


# ---------------------------------------------------------------------------
# F-ARCH-9: Content-Length early 413 -- rejected before any buffering/DB work
# ---------------------------------------------------------------------------


@patch("src.jobs.arq_backend.get_arq_pool")
@patch("src.api.batch_router.batch_service")
def test_content_length_over_cap_is_413_pre_buffer(mock_bs, mock_pool):
    """A declared Content-Length over the cap → 413 before the body is read."""
    mock_bs.stream_upload_to_tempfile = AsyncMock()
    mock_bs.create_batch = AsyncMock()

    app = _build_app()
    client = TestClient(app)

    # Shrink the cap in the router namespace so the small multipart body's real
    # Content-Length already exceeds it -- triggering the early header check.
    with patch("src.api.batch_router.BATCH_MAX_ZIP_BYTES", 8):
        resp = client.post(
            "/api/v1/batch",
            files={"file": ("test.zip", _small_zip(), "application/zip")},
        )

    assert resp.status_code == 413, resp.text
    # Rejected on the header alone: the body was never streamed to a temp file,
    # and no Batch row was created.
    mock_bs.stream_upload_to_tempfile.assert_not_called()
    mock_bs.create_batch.assert_not_called()


# ---------------------------------------------------------------------------
# F-ARCH-9: same-basename entries in different folders both survive
# ---------------------------------------------------------------------------


def test_same_basename_entries_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(batch_service, "BATCH_BLOB_DIR", str(tmp_path))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a/part.stl", b"solid A\nendsolid A")
        zf.writestr("b/part.stl", b"solid B\nendsolid B")
    buf.seek(0)

    items = extract_zip_to_items(buf.getvalue(), "batchULID1")

    # BOTH parts survive (no silent collapse to one item).
    assert len(items) == 2
    names = [it["filename"] for it in items]
    assert len(set(names)) == 2, f"names collided: {names}"
    assert "part.stl" in names  # first keeps the original name

    # And they land on distinct on-disk paths with distinct contents preserved.
    paths = [it["path"] for it in items]
    assert len(set(paths)) == 2
    contents = {open(p, "rb").read() for p in paths}
    assert contents == {b"solid A\nendsolid A", b"solid B\nendsolid B"}


# ---------------------------------------------------------------------------
# F-ARCH-5: S3 / manifest_url input rejected up front, no orphaned batch
# ---------------------------------------------------------------------------


@patch("src.api.batch_router.batch_service")
def test_s3_bucket_rejected_501_no_batch(mock_bs):
    mock_bs.create_batch = AsyncMock()
    app = _build_app()
    client = TestClient(app)

    resp = client.post("/api/v1/batch", data={"s3_bucket": "my-bucket"})

    assert resp.status_code == 501, resp.text
    assert resp.json()["detail"]["code"] == "S3_INPUT_NOT_IMPLEMENTED"
    mock_bs.create_batch.assert_not_called()


@patch("src.api.batch_router.batch_service")
def test_manifest_url_rejected_501_no_batch(mock_bs):
    """manifest_url (like s3) is advertised but unwired -> 501, no orphan."""
    mock_bs.create_batch = AsyncMock()
    app = _build_app()
    client = TestClient(app)

    resp = client.post(
        "/api/v1/batch",
        data={"manifest_url": "https://example.com/manifest.csv"},
    )

    assert resp.status_code == 501, resp.text
    assert resp.json()["detail"]["code"] == "S3_INPUT_NOT_IMPLEMENTED"
    mock_bs.create_batch.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path: a normal small valid ZIP still returns 202 (unchanged)
# ---------------------------------------------------------------------------


@patch("src.jobs.arq_backend.get_arq_pool")
@patch("src.api.batch_router.batch_service")
def test_small_valid_zip_still_202(mock_bs, mock_pool):
    mock_batch = _make_batch()
    mock_bs.create_batch = AsyncMock(return_value=mock_batch)
    mock_bs.stream_upload_to_tempfile = AsyncMock(
        return_value="/tmp/cv_batch_unit.zip"
    )
    mock_bs.extract_zip_path_to_items.return_value = [
        {"filename": "part.stl", "path": "/tmp/part.stl", "size": 100}
    ]
    mock_bs.create_batch_items = AsyncMock(return_value=1)

    mock_arq = AsyncMock()
    mock_arq.enqueue_job = AsyncMock()
    mock_pool.return_value = mock_arq

    app = _build_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/batch",
        files={"file": ("test.zip", _small_zip(), "application/zip")},
    )

    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert data["batch_id"] == mock_batch.ulid
    assert data["status"] == "pending"
    assert "webhook_secret" not in data
    mock_bs.stream_upload_to_tempfile.assert_awaited_once()
