"""Retry, cleanup, state visibility, and resource bounds for direct ZIP prep."""
from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import Batch, DirectUpload
from src.jobs import batch_tasks
from src.services import batch_service, direct_upload_service


def _upload(status: str = "attached") -> DirectUpload:
    return DirectUpload(
        id=3,
        ulid="UPLOAD_TASK_01",
        org_id="org-a",
        user_id=42,
        idempotency_key_hash="c" * 64,
        request_fingerprint="b" * 64,
        batch_id=7,
        purpose="batch_zip",
        status=status,
        filename="parts.zip",
        content_type="application/zip",
        expected_size_bytes=9,
        expected_checksum_sha256="a" * 64,
        actual_size_bytes=9,
        part_size_bytes=5 * 1024**2,
        part_count=1,
        object_key="incoming/org-a/UPLOAD_TASK_01/batch.zip",
        multipart_upload_id="provider-private",
        prepare_attempts=0,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _batch(status: str = "extracting") -> Batch:
    return Batch(
        id=7,
        ulid="BATCH_TASK_01",
        org_id="org-a",
        user_id=42,
        input_mode="direct_upload",
        job_type="dfm",
        status=status,
        total_items=0,
        completed_items=0,
        failed_items=0,
        concurrency_limit=10,
        manifest_json={
            "direct_upload_manifest": [
                {"filename": "part.stl", "priority": "high"}
            ]
        },
    )


def _row(value):
    result = MagicMock()
    result.scalars.return_value.first.return_value = value
    return result


class _Context:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


def _factory_for(upload: DirectUpload, batch: Batch, commits=None):
    session = AsyncMock()

    async def execute(statement):
        sql = str(statement).lower()
        if "from direct_uploads" in sql:
            return _row(upload)
        if "from batches" in sql:
            return _row(batch)
        return MagicMock()  # defensive BatchItem delete checkpoint

    session.execute.side_effect = execute

    async def commit():
        if commits is not None:
            commits.append(
                {
                    "upload": upload.status,
                    "batch": batch.status,
                    "total": batch.total_items,
                    "heartbeat": (batch.manifest_json or {}).get("heartbeat_at"),
                }
            )

    session.commit.side_effect = commit
    factory = MagicMock(side_effect=lambda: _Context(session))
    return factory, session


@pytest.mark.asyncio
async def test_preparation_state_checkpoints_and_duplicate_delivery_are_idempotent():
    upload = _upload()
    batch = _batch()
    commits: list[dict] = []
    factory, _session = _factory_for(upload, batch, commits)
    items = [{"filename": "part.stl", "size": 9}]
    extract = AsyncMock(return_value=items)
    create_items = AsyncMock(return_value=1)
    delete_incoming = AsyncMock()
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()

    with patch.object(batch_tasks, "get_session_factory", return_value=factory), patch.object(
        batch_tasks, "_download_and_extract_direct_upload", new=extract
    ), patch.object(
        batch_service, "create_batch_items", new=create_items
    ), patch.object(
        direct_upload_service, "delete_incoming_object", new=delete_incoming
    ), patch(
        "src.services.audit_service.emit_event", new_callable=AsyncMock
    ):
        ctx = {"redis": pool, "job_try": 1}
        await batch_tasks.prepare_direct_upload_batch(ctx, upload.ulid)
        # At-least-once duplicate delivery after success must be a no-op.
        await batch_tasks.prepare_direct_upload_batch(ctx, upload.ulid)

    assert commits[0]["upload"] == "preparing"
    assert commits[0]["batch"] == "extracting"
    assert commits[0]["heartbeat"] is not None
    assert commits[1]["upload"] == "prepared"
    assert commits[1]["batch"] == "pending"
    assert commits[1]["total"] == 1
    assert commits[2]["upload"] == "consumed"
    assert upload.status == "consumed"
    assert upload.storage_cleaned_at is not None
    assert upload.checksum_verified_at is not None
    assert batch.input_mode == "zip"
    assert batch.status == "pending"
    assert create_items.await_count == 1
    assert create_items.await_args.args[2][0]["priority"] == "high"
    extract.assert_awaited_once()
    delete_incoming.assert_awaited_once_with(upload)
    pool.enqueue_job.assert_awaited_once_with(
        "run_batch_coordinator",
        batch.ulid,
        _job_id=f"batch-coordinator:{batch.ulid}",
    )


@pytest.mark.asyncio
async def test_transient_preparation_failure_releases_claim_for_retry():
    upload = _upload()
    batch = _batch()
    commits: list[dict] = []
    factory, _session = _factory_for(upload, batch, commits)
    storage_error = direct_upload_service.DirectUploadError(
        503,
        "DIRECT_UPLOAD_STORAGE_ERROR",
        "Object storage is temporarily unavailable.",
    )

    with patch.object(batch_tasks, "get_session_factory", return_value=factory), patch.object(
        batch_tasks,
        "_download_and_extract_direct_upload",
        new=AsyncMock(side_effect=storage_error),
    ), patch(
        "src.services.audit_service.emit_event", new_callable=AsyncMock
    ):
        with pytest.raises(direct_upload_service.DirectUploadError):
            await batch_tasks.prepare_direct_upload_batch(
                {"redis": AsyncMock(), "job_try": 1}, upload.ulid
            )

    assert commits[0]["upload"] == "preparing"
    assert commits[0]["batch"] == "extracting"
    assert upload.status == "attached"
    assert upload.preparation_started_at is None
    assert upload.error_code == "DIRECT_UPLOAD_STORAGE_ERROR"
    assert upload.prepare_attempts == 1


@pytest.mark.asyncio
async def test_deterministic_preparation_failure_is_terminal_and_cleans_all_blobs():
    upload = _upload()
    batch = _batch()
    factory, _session = _factory_for(upload, batch)
    invalid = direct_upload_service.DirectUploadPreparationValidationError(
        422,
        "DIRECT_UPLOAD_INVALID_ZIP",
        "ZIP violates the configured safety bound.",
    )
    delete_incoming = AsyncMock()
    cleanup_extracted = MagicMock()
    terminal_items = AsyncMock()

    with patch.object(batch_tasks, "get_session_factory", return_value=factory), patch.object(
        batch_tasks,
        "_download_and_extract_direct_upload",
        new=AsyncMock(side_effect=invalid),
    ), patch.object(
        direct_upload_service, "delete_incoming_object", new=delete_incoming
    ), patch.object(
        batch_service, "cleanup_batch_files", new=cleanup_extracted
    ), patch.object(
        batch_service, "mark_pending_items_terminal", new=terminal_items
    ), patch(
        "src.services.audit_service.emit_event", new_callable=AsyncMock
    ):
        await batch_tasks.prepare_direct_upload_batch(
            {"redis": AsyncMock(), "job_try": 1}, upload.ulid
        )

    assert upload.status == "failed"
    assert upload.error_code == "DIRECT_UPLOAD_INVALID_ZIP"
    assert upload.storage_cleaned_at is not None
    assert batch.status == "failed"
    delete_incoming.assert_awaited_once_with(upload)
    cleanup_extracted.assert_called_once_with(batch.ulid)
    terminal_items.assert_awaited_once_with(
        _session, batch.id, "skipped"
    )


@pytest.mark.asyncio
async def test_preparation_semaphore_bounds_complete_tempfile_lifetime(tmp_path):
    uploads = [_upload(), _upload()]
    uploads[1].ulid = "UPLOAD_TASK_02"
    uploads[1].object_key = "incoming/org-a/UPLOAD_TASK_02/batch.zip"
    batches = [_batch(), _batch()]
    batches[1].ulid = "BATCH_TASK_02"
    ctx = {"direct_upload_preparation_semaphore": asyncio.Semaphore(1)}
    lock = threading.Lock()
    active = 0
    maximum_active = 0
    next_path = 0
    paths = [tmp_path / "one.zip", tmp_path / "two.zip"]

    def download(_upload):
        nonlocal active, maximum_active, next_path
        with lock:
            path = paths[next_path]
            next_path += 1
            active += 1
            maximum_active = max(maximum_active, active)
        path.write_bytes(b"zip")
        return str(path)

    def extract(_path, _batch_ulid):
        nonlocal active
        time.sleep(0.03)
        with lock:
            active -= 1
        return []

    with patch.object(
        direct_upload_service, "download_to_bounded_tempfile", side_effect=download
    ), patch.object(batch_service, "extract_zip_path_to_items", side_effect=extract):
        await asyncio.gather(
            *[
                batch_tasks._download_and_extract_direct_upload(ctx, upload, batch)
                for upload, batch in zip(uploads, batches)
            ]
        )

    assert maximum_active == 1
    assert all(not path.exists() for path in paths)


def test_direct_preparation_concurrency_config_is_safe_and_bounded(monkeypatch):
    monkeypatch.delenv("DIRECT_UPLOAD_PREP_CONCURRENCY", raising=False)
    assert batch_tasks.direct_upload_prep_concurrency() == 1
    monkeypatch.setenv("DIRECT_UPLOAD_PREP_CONCURRENCY", "3")
    assert batch_tasks.direct_upload_prep_concurrency() == 3
    monkeypatch.setenv("DIRECT_UPLOAD_PREP_CONCURRENCY", "99")
    assert batch_tasks.direct_upload_prep_concurrency() == 4
    monkeypatch.setenv("DIRECT_UPLOAD_PREP_CONCURRENCY", "invalid")
    assert batch_tasks.direct_upload_prep_concurrency() == 1


@pytest.mark.asyncio
async def test_worker_startup_initializes_dedicated_preparation_semaphore(monkeypatch):
    from src.jobs import worker

    monkeypatch.setenv("DIRECT_UPLOAD_PREP_CONCURRENCY", "2")
    ctx = {}
    with patch(
        "src.segmentation.sam3d.config.SAM3DConfig.from_env",
        return_value=SimpleNamespace(enabled=False, model_path=None),
    ), patch(
        "src.services.reconstruction_service.check_reconstruction_availability",
        return_value={"available": False, "effective_backend": "none"},
    ), patch("src.db.engine.init_engine", new=AsyncMock()):
        await worker.startup(ctx)

    semaphore = ctx["direct_upload_preparation_semaphore"]
    assert isinstance(semaphore, asyncio.Semaphore)
    assert semaphore._value == 2
    configured = next(
        fn for fn in worker.WorkerSettings.functions
        if getattr(fn, "name", None) == "prepare_direct_upload_batch"
    )
    assert configured.timeout_s == batch_tasks.DIRECT_UPLOAD_PREP_TIMEOUT_SECONDS
    assert configured.timeout_s > worker.WorkerSettings.job_timeout
    assert configured.max_tries == batch_tasks.DIRECT_UPLOAD_PREP_MAX_TRIES


@pytest.mark.asyncio
async def test_direct_upload_cleanup_cron_delegates_to_database_sweeper():
    upload = _upload("expired")
    batch = _batch("failed")
    factory, _session = _factory_for(upload, batch)
    sweep = AsyncMock(return_value=2)
    with patch.object(batch_tasks, "get_session_factory", return_value=factory), patch.object(
        direct_upload_service, "sweep_expired_and_unclean_uploads", new=sweep
    ):
        assert await batch_tasks.sweep_expired_direct_uploads({}) == 2
    sweep.assert_awaited_once_with(_session)
