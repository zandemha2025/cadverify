"""Batch attachment, lost-response idempotency, and manifest bound regressions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.batch_router import router
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Batch, DirectUpload
from src.services import batch_service, direct_upload_service


def _batch() -> Batch:
    return Batch(
        id=7,
        ulid="BATCH_DIRECT_01",
        org_id="org-a",
        user_id=42,
        input_mode="direct_upload",
        job_type="dfm",
        status="pending",
        total_items=0,
        completed_items=0,
        failed_items=0,
        concurrency_limit=10,
        manifest_json=None,
    )


def _upload(status: str = "completed") -> DirectUpload:
    return DirectUpload(
        id=3,
        ulid="UPLOAD_DIRECT_01",
        org_id="org-a",
        user_id=42,
        idempotency_key_hash="c" * 64,
        request_fingerprint="b" * 64,
        purpose="batch_zip",
        status=status,
        filename="parts.zip",
        content_type="application/zip",
        expected_size_bytes=9,
        expected_checksum_sha256="a" * 64,
        actual_size_bytes=9,
        part_size_bytes=5 * 1024**2,
        part_count=1,
        object_key="incoming/org-a/UPLOAD_DIRECT_01/batch.zip",
        multipart_upload_id="provider-private",
        prepare_attempts=0,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _app(session: AsyncMock | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=42,
        api_key_id=1,
        key_prefix="cv_live_test",
    )
    app.dependency_overrides[get_db_session] = lambda: session or AsyncMock()
    return app


def test_file_and_direct_upload_id_are_mutually_exclusive():
    response = TestClient(_app()).post(
        "/api/v1/batch",
        data={"direct_upload_id": "UPLOAD_DIRECT_01"},
        files={"file": ("parts.zip", b"zip", "application/zip")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "BATCH_INPUT_CONFLICT"


def test_lost_response_repeated_attach_returns_same_batch_and_job_identity():
    session = AsyncMock()
    upload = _upload()
    batch = _batch()
    lock = AsyncMock(side_effect=[(upload, None), (upload, batch)])
    create = AsyncMock(return_value=batch)

    async def attach(_session, *, upload, batch, actor_id):
        upload.status = "attached"
        upload.batch_id = batch.id

    attach_mock = AsyncMock(side_effect=attach)
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()

    with patch.object(
        direct_upload_service, "lock_for_batch_attachment", new=lock
    ), patch.object(
        direct_upload_service, "attach_to_batch", new=attach_mock
    ), patch.object(
        batch_service, "create_batch", new=create
    ), patch(
        "src.jobs.arq_backend.get_arq_pool", new=AsyncMock(return_value=pool)
    ):
        client = TestClient(_app(session))
        first = client.post(
            "/api/v1/batch", data={"direct_upload_id": upload.ulid}
        )
        # Treat the first 202 as if its response was lost and repeat exactly.
        repeated = client.post(
            "/api/v1/batch", data={"direct_upload_id": upload.ulid}
        )

    assert first.status_code == 202, first.text
    assert repeated.status_code == 202, repeated.text
    assert first.json()["batch_id"] == repeated.json()["batch_id"] == batch.ulid
    assert repeated.json()["status"] == "pending"
    create.assert_awaited_once()
    attach_mock.assert_awaited_once()
    assert pool.enqueue_job.await_count == 2
    assert {
        call.kwargs["_job_id"] for call in pool.enqueue_job.await_args_list
    } == {f"direct-upload-prepare:{upload.ulid}"}


def test_cross_org_attachment_is_404_and_creates_no_batch():
    create = AsyncMock()
    lock = AsyncMock(
        side_effect=direct_upload_service.DirectUploadError(
            404,
            "DIRECT_UPLOAD_NOT_FOUND",
            "Direct upload not found.",
        )
    )
    with patch.object(
        direct_upload_service, "lock_for_batch_attachment", new=lock
    ), patch.object(batch_service, "create_batch", new=create):
        response = TestClient(_app()).post(
            "/api/v1/batch",
            data={"direct_upload_id": "UPLOAD_OTHER_ORG"},
        )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DIRECT_UPLOAD_NOT_FOUND"
    create.assert_not_awaited()


def test_new_attachment_queue_failure_is_durable_and_cleans_blob():
    session = AsyncMock()
    upload = _upload()
    batch = _batch()
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))

    async def attach(_session, *, upload, batch, actor_id):
        upload.status = "attached"
        upload.batch_id = batch.id

    async def terminalize(_session, *, upload, batch, actor_id):
        upload.status = "failed"
        upload.error_code = "DIRECT_UPLOAD_PREPARATION_ENQUEUE_FAILED"
        batch.status = "failed"

    cleanup = AsyncMock()
    mark_clean = AsyncMock()
    with patch.object(
        direct_upload_service,
        "lock_for_batch_attachment",
        new=AsyncMock(return_value=(upload, None)),
    ), patch.object(
        direct_upload_service, "attach_to_batch", new=AsyncMock(side_effect=attach)
    ), patch.object(
        direct_upload_service,
        "mark_attachment_enqueue_failed",
        new=AsyncMock(side_effect=terminalize),
    ), patch.object(
        direct_upload_service, "delete_incoming_object", new=cleanup
    ), patch.object(
        direct_upload_service, "mark_storage_cleaned", new=mark_clean
    ), patch.object(
        batch_service, "create_batch", new=AsyncMock(return_value=batch)
    ), patch(
        "src.jobs.arq_backend.get_arq_pool", new=AsyncMock(return_value=pool)
    ):
        response = TestClient(_app(session)).post(
            "/api/v1/batch", data={"direct_upload_id": upload.ulid}
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "BATCH_ENQUEUE_FAILED"
    assert response.json()["detail"]["accepted_batch"]["status"] == "failed"
    assert upload.status == "failed"
    assert batch.status == "failed"
    cleanup.assert_awaited_once_with(upload)
    mark_clean.assert_awaited_once_with(session, upload)


@pytest.mark.parametrize("input_mode", ["direct", "proxied"])
def test_manifest_cap_rejects_before_batch_creation(monkeypatch, input_mode):
    monkeypatch.setattr(batch_service, "BATCH_MAX_MANIFEST_BYTES", 8)
    create = AsyncMock()
    with patch.object(batch_service, "create_batch", new=create):
        client = TestClient(_app())
        files = {"manifest": ("manifest.csv", b"123456789", "text/csv")}
        data = {}
        if input_mode == "direct":
            data["direct_upload_id"] = "UPLOAD_DIRECT_01"
        else:
            files["file"] = ("parts.zip", b"not-read", "application/zip")
        response = client.post("/api/v1/batch", data=data, files=files)

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "BATCH_MANIFEST_TOO_LARGE"
    create.assert_not_awaited()
