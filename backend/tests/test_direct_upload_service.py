"""Direct-upload validation, tenancy, completion recovery, and cleanup tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from src.db.models import Batch, DirectUpload
from src.services import direct_upload_service as service
from src.storage import ObjectMetadata


def _upload(*, status: str = "initiated") -> DirectUpload:
    return DirectUpload(
        id=1,
        ulid="UPLOAD_01",
        org_id="org-a",
        user_id=11,
        idempotency_key_hash="c" * 64,
        request_fingerprint="b" * 64,
        purpose="batch_zip",
        status=status,
        filename="parts.zip",
        content_type="application/zip",
        expected_size_bytes=9,
        expected_checksum_sha256="a" * 64,
        actual_size_bytes=None,
        part_size_bytes=5 * 1024**2,
        part_count=1,
        object_key="incoming/org-a/UPLOAD_01/batch.zip",
        multipart_upload_id="provider-upload-1",
        prepare_attempts=0,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _batch(*, status: str = "extracting") -> Batch:
    batch = Batch(
        id=7,
        ulid="BATCH_01",
        user_id=11,
        org_id="org-a",
        status=status,
        input_mode="direct_upload",
        job_type="dfm",
        total_items=0,
        completed_items=0,
        failed_items=0,
        concurrency_limit=10,
    )
    return batch


def _row(value):
    result = MagicMock()
    result.scalars.return_value.first.return_value = value
    return result


def _rows(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


class _CompletionStore:
    def __init__(self):
        self.complete_error: Exception | None = None
        self.stat_error: Exception | None = None
        self.metadata = ObjectMetadata(9, "application/zip", '"etag"')
        self.deleted: list[str] = []
        self.aborted: list[tuple[str, str]] = []
        self.complete_calls = 0
        self.stat_calls = 0

    def complete_multipart_upload(self, *_args):
        self.complete_calls += 1
        if self.complete_error:
            raise self.complete_error
        return self.metadata

    def stat(self, _key):
        self.stat_calls += 1
        if self.stat_error:
            raise self.stat_error
        return self.metadata

    def delete(self, key):
        self.deleted.append(key)

    def abort_multipart_upload(self, key, upload_id):
        self.aborted.append((key, upload_id))


class _InitiationStore(_CompletionStore):
    def __init__(self):
        super().__init__()
        self.created: list[tuple[str, str, dict[str, str]]] = []
        self.signed: list[tuple[str, str, int, int]] = []

    def create_multipart_upload(self, key, *, content_type, metadata):
        self.created.append((key, content_type, metadata))
        return "provider-upload-private"

    def presign_upload_part(self, key, upload_id, number, *, expires_in):
        self.signed.append((key, upload_id, number, expires_in))
        return f"https://signed.example/{number}"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"purpose": "avatar"}, "DIRECT_UPLOAD_INVALID_PURPOSE"),
        ({"filename": "../parts.zip"}, "DIRECT_UPLOAD_INVALID_FILENAME"),
        ({"filename": "parts.step"}, "DIRECT_UPLOAD_INVALID_FILENAME"),
        ({"content_type": "text/plain"}, "DIRECT_UPLOAD_INVALID_CONTENT_TYPE"),
        ({"size_bytes": 0}, "DIRECT_UPLOAD_INVALID_SIZE"),
        ({"checksum_sha256": "not-a-digest"}, "DIRECT_UPLOAD_INVALID_CHECKSUM"),
    ],
)
def test_initiation_validation_is_exact_and_structured(kwargs, code):
    values = {
        "purpose": "batch_zip",
        "filename": "parts.zip",
        "content_type": "application/zip",
        "size_bytes": 9,
        "checksum_sha256": "a" * 64,
    }
    values.update(kwargs)
    with pytest.raises(service.DirectUploadError) as exc:
        service._validate_initiate(**values)
    assert exc.value.code == code


def test_capability_fails_closed_on_non_s3(monkeypatch):
    monkeypatch.setattr(service, "selected_backend", lambda: "local")
    result = service.capability("batch_zip")
    assert result["available"] is False
    assert result["direct_upload"] is False
    assert result["unavailable_code"] == "DIRECT_UPLOAD_REQUIRES_S3"


def test_capability_advertises_required_integrity_idempotency_and_admission():
    with patch.object(service, "_require_s3_store", return_value=MagicMock()):
        result = service.capability("batch_zip")
    assert result["checksum_algorithm"] == "sha256"
    assert result["checksum_required"] is True
    assert result["idempotency_key_header"] == "Idempotency-Key"
    assert result["idempotency_key_required"] is True
    assert result["max_active_uploads_per_org"] >= 1
    assert result["max_active_upload_bytes_per_org"] >= 1


def test_every_lifecycle_lookup_is_active_org_scoped_not_creator_scoped():
    statement = service._owned_upload_stmt(22, "UPLOAD_01")
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "memberships" in sql
    assert "current_org_id" in sql
    assert "direct_uploads.org_id" in sql
    # Intentional policy: another analyst in the same active org can operate the
    # org-owned upload; creator user_id is evidence, not the access boundary.
    assert "direct_uploads.user_id =" not in sql


@pytest.mark.asyncio
async def test_initiate_persists_server_owned_org_key_and_audit_atomically():
    store = _InitiationStore()
    session = AsyncMock()
    session.add = MagicMock()
    with patch.object(service, "_require_s3_store", return_value=store), patch.object(
        service, "resolve_org", new=AsyncMock(return_value="org-a")
    ), patch.object(
        service, "_lock_org_upload_admission", new=AsyncMock()
    ), patch.object(
        service, "_idempotent_upload", new=AsyncMock(return_value=None)
    ), patch.object(
        service, "_enforce_upload_admission", new=AsyncMock()
    ), patch(
        "src.services.audit_service.emit_event", new_callable=AsyncMock
    ) as emit:
        upload, part_urls, complete, replayed = await service.initiate(
            session,
            user_id=22,
            purpose="batch_zip",
            filename="parts.zip",
            content_type="application/zip",
            size_bytes=9,
            checksum_sha256="a" * 64,
            idempotency_key="browser-attempt-0001",
        )

    assert upload.status == "initiated"
    assert upload.org_id == "org-a"
    assert upload.object_key == f"incoming/org-a/{upload.ulid}/batch.zip"
    assert store.created[0][0] == upload.object_key
    assert store.created[0][2]["cadverify-upload-id"] == upload.ulid
    assert store.created[0][2]["expected-sha256"] == "a" * 64
    assert upload.expected_checksum_sha256 == "a" * 64
    assert len(upload.idempotency_key_hash) == 64
    assert len(upload.request_fingerprint) == 64
    assert part_urls[0]["part_number"] == 1
    assert complete is True
    assert replayed is False
    session.flush.assert_awaited_once()
    session.commit.assert_awaited_once()
    emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_initiation_idempotency_replays_same_provider_session_without_readmission():
    store = _InitiationStore()
    existing = _upload()
    key = "browser-attempt-0001"
    existing.idempotency_key_hash = service._validate_idempotency_key(key)
    existing.request_fingerprint = service._request_fingerprint(
        purpose="batch_zip",
        filename="parts.zip",
        content_type="application/zip",
        size_bytes=9,
        checksum_sha256="a" * 64,
    )
    session = AsyncMock()
    admission = AsyncMock()

    with patch.object(service, "_require_s3_store", return_value=store), patch.object(
        service, "resolve_org", new=AsyncMock(return_value="org-a")
    ), patch.object(
        service, "_lock_org_upload_admission", new=AsyncMock()
    ), patch.object(
        service, "_idempotent_upload", new=AsyncMock(return_value=existing)
    ), patch.object(
        service, "_enforce_upload_admission", new=admission
    ), patch(
        "src.services.audit_service.emit_event", new_callable=AsyncMock
    ):
        replay, parts, complete, replayed = await service.initiate(
            session,
            user_id=22,
            purpose="batch_zip",
            filename="parts.zip",
            content_type="application/zip",
            size_bytes=9,
            checksum_sha256="a" * 64,
            idempotency_key=key,
        )

    assert replay is existing
    assert replayed is True
    assert complete is True
    assert parts[0]["part_number"] == 1
    assert store.created == []
    admission.assert_not_awaited()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotency_key_reuse_with_different_fingerprint_is_409():
    store = _InitiationStore()
    existing = _upload()
    existing.request_fingerprint = "f" * 64
    session = AsyncMock()
    with patch.object(service, "_require_s3_store", return_value=store), patch.object(
        service, "resolve_org", new=AsyncMock(return_value="org-a")
    ), patch.object(
        service, "_lock_org_upload_admission", new=AsyncMock()
    ), patch.object(
        service, "_idempotent_upload", new=AsyncMock(return_value=existing)
    ):
        with pytest.raises(service.DirectUploadError) as exc:
            await service.initiate(
                session,
                user_id=22,
                purpose="batch_zip",
                filename="parts.zip",
                content_type="application/zip",
                size_bytes=9,
                checksum_sha256="a" * 64,
                idempotency_key="browser-attempt-0001",
            )

    assert exc.value.status_code == 409
    assert exc.value.code == "DIRECT_UPLOAD_IDEMPOTENCY_CONFLICT"
    assert store.created == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("active_count", "reserved_bytes", "code"),
    [
        (4, 0, "DIRECT_UPLOAD_ADMISSION_LIMIT"),
        (1, 10 * 1024**3, "DIRECT_UPLOAD_ADMISSION_BYTES_LIMIT"),
    ],
)
async def test_active_upload_admission_bounds_count_and_declared_bytes(
    active_count,
    reserved_bytes,
    code,
):
    result = MagicMock()
    result.one.return_value = (active_count, reserved_bytes)
    session = AsyncMock()
    session.execute.return_value = result

    with pytest.raises(service.DirectUploadError) as exc:
        await service._enforce_upload_admission(
            session,
            org_id="org-a",
            requested_size_bytes=9,
        )

    assert exc.value.status_code == 429
    assert exc.value.code == code
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "direct_uploads.org_id" in sql
    assert "storage_cleaned_at is null" in sql


@pytest.mark.asyncio
async def test_org_row_lock_serializes_idempotency_and_quota_admission():
    result = MagicMock()
    result.scalar_one_or_none.return_value = "org-a"
    session = AsyncMock()
    session.execute.return_value = result

    await service._lock_org_upload_admission(session, "org-a")

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "from organizations" in sql
    assert "for update" in sql


def test_idempotency_key_and_checksum_are_required_and_exact():
    with pytest.raises(service.DirectUploadError) as missing_key:
        service._validate_idempotency_key(None)
    assert missing_key.value.code == "DIRECT_UPLOAD_IDEMPOTENCY_KEY_REQUIRED"

    with pytest.raises(service.DirectUploadError) as weak_key:
        service._validate_idempotency_key("short")
    assert weak_key.value.code == "DIRECT_UPLOAD_IDEMPOTENCY_KEY_REQUIRED"


@pytest.mark.asyncio
async def test_cross_org_or_missing_lifecycle_lookup_returns_same_404():
    session = AsyncMock()
    session.execute.return_value = _row(None)
    with pytest.raises(service.DirectUploadError) as exc:
        await service.get_status(
            session,
            user_id=22,
            upload_ulid="UPLOAD_OTHER_ORG",
        )
    assert exc.value.status_code == 404
    assert exc.value.code == "DIRECT_UPLOAD_NOT_FOUND"


@pytest.mark.asyncio
async def test_complete_recovers_provider_completed_object_by_exact_metadata():
    upload = _upload()
    store = _CompletionStore()
    store.complete_error = RuntimeError("NoSuchUpload")
    session = AsyncMock()
    session.execute.return_value = _row(upload)

    with patch.object(service, "_require_s3_store", return_value=store), patch(
        "src.services.audit_service.emit_event", new_callable=AsyncMock
    ):
        completed = await service.complete(
            session,
            user_id=22,
            upload_ulid=upload.ulid,
            parts=[{"part_number": 1, "etag": '"part-etag"'}],
        )

    assert completed.status == "completed"
    assert completed.actual_size_bytes == 9
    assert store.deleted == []
    assert session.commit.await_count == 2  # durable intent, then completion
    assert store.complete_calls == 1
    assert store.stat_calls == 1


@pytest.mark.asyncio
async def test_provider_completion_survives_db_failure_and_reconciles_on_retry():
    upload = _upload()
    store = _CompletionStore()
    failed_session = AsyncMock()
    failed_session.execute.return_value = _row(upload)
    durable_states: list[str] = []

    async def commit_then_lose_final_response():
        durable_states.append(upload.status)
        if len(durable_states) == 2:
            raise RuntimeError("database unavailable")

    failed_session.commit.side_effect = commit_then_lose_final_response

    with patch.object(service, "_require_s3_store", return_value=store), patch(
        "src.services.audit_service.emit_event", new_callable=AsyncMock
    ):
        with pytest.raises(service.DirectUploadError) as completion_error:
            await service.complete(
                failed_session,
                user_id=22,
                upload_ulid=upload.ulid,
                parts=[{"part_number": 1, "etag": '"part-etag"'}],
            )
    assert completion_error.value.code == "DIRECT_UPLOAD_COMPLETION_RETRY"

    # The provider object is deliberately retained; deleting it would make the
    # consumed multipart ID permanently unrecoverable.
    assert store.deleted == []
    failed_session.rollback.assert_awaited_once()
    assert durable_states == ["completing", "completed"]
    assert store.complete_calls == 1

    # Model the real rollback to the durable explicit checkpoint and provider's
    # consumed multipart ID, then retry. There is no ambiguous initiated row.
    upload.status = "completing"
    upload.actual_size_bytes = None
    upload.object_etag = None
    upload.completed_at = None
    store.complete_error = RuntimeError("NoSuchUpload")
    retry_session = AsyncMock()
    retry_session.execute.return_value = _row(upload)
    with patch.object(service, "_require_s3_store", return_value=store), patch(
        "src.services.audit_service.emit_event", new_callable=AsyncMock
    ):
        recovered = await service.complete(
            retry_session,
            user_id=22,
            upload_ulid=upload.ulid,
            parts=[{"part_number": 1, "etag": '"part-etag"'}],
        )
    assert recovered.status == "completed"
    retry_session.commit.assert_awaited_once()
    assert store.complete_calls == 2
    assert store.stat_calls == 1


@pytest.mark.asyncio
async def test_complete_fails_closed_when_provider_and_stat_both_fail():
    upload = _upload()
    store = _CompletionStore()
    store.complete_error = RuntimeError("S3 down")
    store.stat_error = RuntimeError("S3 still down")
    session = AsyncMock()
    session.execute.return_value = _row(upload)
    with patch.object(service, "_require_s3_store", return_value=store), patch(
        "src.services.audit_service.emit_event", new_callable=AsyncMock
    ):
        with pytest.raises(service.DirectUploadError) as exc:
            await service.complete(
                session,
                user_id=22,
                upload_ulid=upload.ulid,
                parts=[{"part_number": 1, "etag": '"part-etag"'}],
            )
    assert exc.value.code == "DIRECT_UPLOAD_COMPLETION_RETRY"
    assert upload.status == "completing"
    assert upload.error_code == "DIRECT_UPLOAD_COMPLETION_RETRY"
    assert session.commit.await_count == 2  # intent + retry detail


@pytest.mark.asyncio
async def test_abort_refuses_ambiguous_completing_state_to_preserve_reconciliation():
    upload = _upload(status="completing")
    session = AsyncMock()
    session.execute.return_value = _row(upload)
    store = _CompletionStore()
    with patch.object(service, "_require_s3_store", return_value=store):
        with pytest.raises(service.DirectUploadError) as exc:
            await service.abort(
                session,
                user_id=22,
                upload_ulid=upload.ulid,
            )
    assert exc.value.status_code == 409
    assert exc.value.code == "DIRECT_UPLOAD_COMPLETION_RECOVERY_REQUIRED"
    assert store.aborted == []
    assert store.deleted == []


@pytest.mark.asyncio
async def test_completed_unattached_expiry_sweep_deletes_object_and_marks_row():
    upload = _upload(status="completed")
    upload.completed_at = datetime.now(timezone.utc) - timedelta(hours=2)
    upload.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    store = _CompletionStore()
    session = AsyncMock()
    session.execute.side_effect = [_rows([upload.id]), _row(upload)]

    with patch.object(service, "_require_s3_store", return_value=store), patch(
        "src.services.audit_service.emit_event", new_callable=AsyncMock
    ):
        cleaned = await service.sweep_expired_and_unclean_uploads(session)

    assert cleaned == 1
    assert upload.status == "expired"
    assert upload.storage_cleaned_at is not None
    assert store.deleted == [upload.object_key]


@pytest.mark.asyncio
async def test_repeated_attachment_resolves_original_batch_without_new_claim():
    upload = _upload(status="attached")
    batch = _batch()
    upload.batch_id = batch.id
    session = AsyncMock()
    session.execute.side_effect = [_row(upload), _row(batch)]
    resolved_upload, resolved_batch = await service.lock_for_batch_attachment(
        session,
        user_id=22,
        upload_ulid=upload.ulid,
    )
    assert resolved_upload is upload
    assert resolved_batch is batch
