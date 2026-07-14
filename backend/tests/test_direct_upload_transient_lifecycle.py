"""Real S3 lifecycle proof for the isolated transient upload namespace."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import DirectUpload
from src.services import direct_upload_service
from src.storage import get_direct_upload_store, get_object_store


def _row(value):
    result = MagicMock()
    result.scalars.return_value.first.return_value = value
    return result


def _rows(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


@pytest.fixture
def isolated_moto_stores(monkeypatch):
    moto = pytest.importorskip("moto")
    boto3 = pytest.importorskip("boto3")
    mock = moto.mock_aws()
    mock.start()
    try:
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="proofshape-durable-test")
        client.put_bucket_versioning(
            Bucket="proofshape-durable-test",
            VersioningConfiguration={"Status": "Enabled"},
        )
        client.create_bucket(Bucket="proofshape-transient-test")

        monkeypatch.setenv("RELEASE", "test")
        monkeypatch.setenv("OBJECT_STORE_BACKEND", "s3")
        monkeypatch.setenv("OBJECT_STORE_S3_BUCKET", "proofshape-durable-test")
        monkeypatch.setenv("OBJECT_STORE_S3_PREFIX", "test")
        monkeypatch.setenv("OBJECT_STORE_S3_REGION", "us-east-1")
        monkeypatch.setenv("OBJECT_STORE_S3_KMS_KEY_ID", "alias/durable-test")
        monkeypatch.delenv("OBJECT_STORE_S3_ENDPOINT", raising=False)
        monkeypatch.setenv("DIRECT_UPLOAD_S3_BUCKET", "proofshape-transient-test")
        monkeypatch.setenv("DIRECT_UPLOAD_S3_PREFIX", "test")
        monkeypatch.setenv("DIRECT_UPLOAD_S3_REGION", "us-east-1")
        monkeypatch.setenv(
            "DIRECT_UPLOAD_S3_KMS_KEY_ID",
            "arn:aws:kms:us-east-1:111122223333:key/transient-test",
        )
        monkeypatch.delenv("DIRECT_UPLOAD_S3_ENDPOINT", raising=False)

        durable = get_object_store("batch-files", default_root="/unused")
        transient = get_direct_upload_store()
        durable.put(
            "sentinel/accepted.step",
            b"durable accepted artifact",
            content_type="application/step",
        )
        yield client, durable, transient
    finally:
        mock.stop()


def _upload_model(
    *,
    ulid: str,
    org_id: str,
    key: str,
    provider_upload_id: str,
    content: bytes,
    status: str = "initiated",
) -> DirectUpload:
    return DirectUpload(
        id=1,
        ulid=ulid,
        org_id=org_id,
        user_id=42,
        idempotency_key_hash="c" * 64,
        request_fingerprint="b" * 64,
        purpose="batch_zip",
        status=status,
        filename="parts.zip",
        content_type="application/zip",
        expected_size_bytes=len(content),
        expected_checksum_sha256=hashlib.sha256(content).hexdigest(),
        actual_size_bytes=(len(content) if status != "initiated" else None),
        part_size_bytes=5 * 1024**2,
        part_count=1,
        object_key=key,
        multipart_upload_id=provider_upload_id,
        prepare_attempts=0,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        completed_at=(
            datetime.now(timezone.utc) if status != "initiated" else None
        ),
    )


def _start_part(transient, client, *, key: str, content: bytes):
    provider_upload_id = transient.create_multipart_upload(
        key,
        content_type="application/zip",
        metadata={"expected-sha256": hashlib.sha256(content).hexdigest()},
    )
    receipt = client.upload_part(
        Bucket="proofshape-transient-test",
        Key=f"test/direct-uploads/{key}",
        UploadId=provider_upload_id,
        PartNumber=1,
        Body=content,
    )
    return provider_upload_id, receipt["ETag"]


def test_real_multipart_create_presign_complete_head_and_physical_delete(
    isolated_moto_stores,
):
    client, durable, transient = isolated_moto_stores
    key = "incoming/org-a/UPLOAD_LIFECYCLE/batch.zip"
    content = b"real browser multipart bytes"
    provider_upload_id = transient.create_multipart_upload(
        key,
        content_type="application/zip",
        metadata={"purpose": "batch_zip"},
    )

    signed_url = transient.presign_upload_part(
        key,
        provider_upload_id,
        1,
        expires_in=300,
    )
    assert signed_url.startswith("https://")
    receipt = client.upload_part(
        Bucket="proofshape-transient-test",
        Key=f"test/direct-uploads/{key}",
        UploadId=provider_upload_id,
        PartNumber=1,
        Body=content,
    )
    metadata = transient.complete_multipart_upload(
        key,
        provider_upload_id,
        [{"PartNumber": 1, "ETag": receipt["ETag"]}],
    )
    head = client.head_object(
        Bucket="proofshape-transient-test",
        Key=f"test/direct-uploads/{key}",
    )

    assert metadata.size_bytes == len(content)
    assert metadata.content_type == "application/zip"
    assert head["ServerSideEncryption"] == "aws:kms"
    assert head["SSEKMSKeyId"].endswith("key/transient-test")
    with transient.open(key) as stream:
        assert stream.read() == content
    assert durable.get("sentinel/accepted.step") == b"durable accepted artifact"
    transient_versioning = client.get_bucket_versioning(
        Bucket="proofshape-transient-test"
    )
    assert "Status" not in transient_versioning

    transient.delete(key)

    assert transient.exists(key) is False
    versions = client.list_object_versions(
        Bucket="proofshape-transient-test",
        Prefix=f"test/direct-uploads/{key}",
    )
    assert versions.get("Versions", []) == []
    assert versions.get("DeleteMarkers", []) == []
    assert durable.get("sentinel/accepted.step") == b"durable accepted artifact"


@pytest.mark.asyncio
async def test_service_initiation_creates_only_transient_provider_state(
    isolated_moto_stores,
):
    client, durable, transient = isolated_moto_stores
    session = AsyncMock()
    session.add = MagicMock()

    with patch.object(
        direct_upload_service,
        "resolve_org",
        new=AsyncMock(return_value="org-a"),
    ), patch.object(
        direct_upload_service,
        "_lock_org_upload_admission",
        new=AsyncMock(),
    ), patch.object(
        direct_upload_service,
        "_idempotent_upload",
        new=AsyncMock(return_value=None),
    ), patch.object(
        direct_upload_service,
        "_enforce_upload_admission",
        new=AsyncMock(),
    ), patch(
        "src.services.audit_service.emit_event",
        new_callable=AsyncMock,
    ):
        upload, parts, urls_complete, replayed = await direct_upload_service.initiate(
            session,
            user_id=42,
            purpose="batch_zip",
            filename="parts.zip",
            content_type="application/zip",
            size_bytes=9,
            checksum_sha256="a" * 64,
            idempotency_key="browser-attempt-0001",
        )

    transient_uploads = client.list_multipart_uploads(
        Bucket="proofshape-transient-test",
        Prefix=f"test/direct-uploads/{upload.object_key}",
    ).get("Uploads", [])
    durable_uploads = client.list_multipart_uploads(
        Bucket="proofshape-durable-test",
    ).get("Uploads", [])
    assert len(transient_uploads) == 1
    assert transient_uploads[0]["UploadId"] == upload.multipart_upload_id
    assert durable_uploads == []
    assert parts[0]["part_number"] == 1
    assert urls_complete is True
    assert replayed is False
    public = json.dumps(direct_upload_service.serialize(upload), sort_keys=True)
    assert upload.multipart_upload_id not in public
    assert upload.object_key not in public
    assert "proofshape-transient-test" not in public
    assert durable.get("sentinel/accepted.step") == b"durable accepted artifact"

    transient.abort_multipart_upload(
        upload.object_key,
        upload.multipart_upload_id,
    )


@pytest.mark.asyncio
async def test_refresh_complete_and_head_reconciliation_use_transient_store(
    isolated_moto_stores,
):
    client, durable, transient = isolated_moto_stores
    content = b"completion body"
    key = "incoming/org-a/UPLOAD_COMPLETE/batch.zip"
    provider_upload_id, etag = _start_part(
        transient,
        client,
        key=key,
        content=content,
    )
    upload = _upload_model(
        ulid="UPLOAD_COMPLETE",
        org_id="org-a",
        key=key,
        provider_upload_id=provider_upload_id,
        content=content,
    )
    session = AsyncMock()
    session.execute.return_value = _row(upload)

    refreshed = await direct_upload_service.refresh_part_urls(
        session,
        user_id=42,
        upload_ulid=upload.ulid,
        part_numbers=[1],
    )
    assert refreshed[0]["part_number"] == 1
    assert refreshed[0]["url"].startswith("https://")

    with patch(
        "src.services.audit_service.emit_event",
        new_callable=AsyncMock,
    ):
        completed = await direct_upload_service.complete(
            session,
            user_id=42,
            upload_ulid=upload.ulid,
            parts=[{"part_number": 1, "etag": etag}],
        )

    assert completed.status == "completed"
    assert transient.stat(key).size_bytes == len(content)
    assert durable.get("sentinel/accepted.step") == b"durable accepted artifact"
    public = json.dumps(direct_upload_service.serialize(completed), sort_keys=True)
    assert provider_upload_id not in public
    assert key not in public
    assert "proofshape-transient-test" not in public

    # Simulate a lost CompleteMultipartUpload response: provider completion has
    # already consumed the upload id while the durable row remains completing.
    reconcile_key = "incoming/org-a/UPLOAD_RECONCILE/batch.zip"
    reconcile_id, reconcile_etag = _start_part(
        transient,
        client,
        key=reconcile_key,
        content=content,
    )
    transient.complete_multipart_upload(
        reconcile_key,
        reconcile_id,
        [{"PartNumber": 1, "ETag": reconcile_etag}],
    )
    reconciling = _upload_model(
        ulid="UPLOAD_RECONCILE",
        org_id="org-a",
        key=reconcile_key,
        provider_upload_id=reconcile_id,
        content=content,
        status="completing",
    )
    reconcile_session = AsyncMock()
    reconcile_session.execute.return_value = _row(reconciling)
    with patch.object(
        direct_upload_service,
        "_require_s3_store",
        return_value=transient,
    ), patch.object(
        transient,
        "complete_multipart_upload",
        side_effect=RuntimeError("provider completion response was lost"),
    ), patch(
        "src.services.audit_service.emit_event",
        new_callable=AsyncMock,
    ) as emit:
        recovered = await direct_upload_service.complete(
            reconcile_session,
            user_id=42,
            upload_ulid=reconciling.ulid,
            parts=[{"part_number": 1, "etag": reconcile_etag}],
        )

    assert recovered.status == "completed"
    assert recovered.actual_size_bytes == len(content)
    assert emit.await_args.kwargs["detail"]["reconciled_provider_completion"] is True


@pytest.mark.asyncio
async def test_worker_handoff_streams_transient_then_keeps_durable_artifact(
    isolated_moto_stores,
):
    client, durable, transient = isolated_moto_stores
    content = b"PK\x03\x04validated worker handoff"
    key = "incoming/org-a/UPLOAD_WORKER/batch.zip"
    provider_upload_id, etag = _start_part(
        transient,
        client,
        key=key,
        content=content,
    )
    transient.complete_multipart_upload(
        key,
        provider_upload_id,
        [{"PartNumber": 1, "ETag": etag}],
    )
    upload = _upload_model(
        ulid="UPLOAD_WORKER",
        org_id="org-a",
        key=key,
        provider_upload_id=provider_upload_id,
        content=content,
        status="attached",
    )

    path = direct_upload_service.download_to_bounded_tempfile(upload)
    try:
        with open(path, "rb") as stream:
            verified = stream.read()
        assert verified == content
        durable.put(
            "accepted/UPLOAD_WORKER/part.step",
            b"accepted CAD",
            content_type="application/step",
        )
    finally:
        os.unlink(path)

    await direct_upload_service.delete_incoming_object(upload)

    assert transient.exists(key) is False
    assert durable.get("accepted/UPLOAD_WORKER/part.step") == b"accepted CAD"
    assert durable.get("sentinel/accepted.step") == b"durable accepted artifact"


@pytest.mark.asyncio
async def test_abort_and_sweeper_physically_remove_only_owned_transient_objects(
    isolated_moto_stores,
):
    client, durable, transient = isolated_moto_stores
    initiated_key = "incoming/org-a/UPLOAD_ABORT/batch.zip"
    initiated_id = transient.create_multipart_upload(
        initiated_key,
        content_type="application/zip",
    )
    initiated = _upload_model(
        ulid="UPLOAD_ABORT",
        org_id="org-a",
        key=initiated_key,
        provider_upload_id=initiated_id,
        content=b"pending",
    )
    abort_session = AsyncMock()
    abort_session.execute.return_value = _row(initiated)
    with patch(
        "src.services.audit_service.emit_event",
        new_callable=AsyncMock,
    ):
        aborted = await direct_upload_service.abort(
            abort_session,
            user_id=42,
            upload_ulid=initiated.ulid,
        )
    assert aborted.status == "aborted"
    assert client.list_multipart_uploads(
        Bucket="proofshape-transient-test",
        Prefix=f"test/direct-uploads/{initiated_key}",
    ).get("Uploads", []) == []

    expired_content = b"completed but unattached"
    expired_key = "incoming/org-a/UPLOAD_SWEEP/batch.zip"
    expired_id, expired_etag = _start_part(
        transient,
        client,
        key=expired_key,
        content=expired_content,
    )
    transient.complete_multipart_upload(
        expired_key,
        expired_id,
        [{"PartNumber": 1, "ETag": expired_etag}],
    )
    expired = _upload_model(
        ulid="UPLOAD_SWEEP",
        org_id="org-a",
        key=expired_key,
        provider_upload_id=expired_id,
        content=expired_content,
        status="completed",
    )
    expired.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    sweep_session = AsyncMock()
    sweep_session.execute.side_effect = [_rows([expired.id]), _row(expired)]
    with patch(
        "src.services.audit_service.emit_event",
        new_callable=AsyncMock,
    ):
        cleaned = await direct_upload_service.sweep_expired_and_unclean_uploads(
            sweep_session,
        )

    assert cleaned == 1
    assert expired.status == "expired"
    assert expired.storage_cleaned_at is not None
    assert transient.exists(expired_key) is False
    assert durable.get("sentinel/accepted.step") == b"durable accepted artifact"


@pytest.mark.asyncio
async def test_tampered_cross_tenant_row_cannot_read_or_delete_owned_object(
    isolated_moto_stores,
):
    client, _durable, transient = isolated_moto_stores
    content = b"org a private upload"
    key = "incoming/org-a/UPLOAD_TENANT/batch.zip"
    provider_upload_id, etag = _start_part(
        transient,
        client,
        key=key,
        content=content,
    )
    transient.complete_multipart_upload(
        key,
        provider_upload_id,
        [{"PartNumber": 1, "ETag": etag}],
    )
    tampered = _upload_model(
        ulid="UPLOAD_TENANT",
        org_id="org-b",
        key=key,
        provider_upload_id=provider_upload_id,
        content=content,
        status="completed",
    )

    with pytest.raises(
        direct_upload_service.DirectUploadPreparationValidationError
    ) as read_error:
        direct_upload_service.download_to_bounded_tempfile(tampered)
    with pytest.raises(
        direct_upload_service.DirectUploadPreparationValidationError
    ) as delete_error:
        await direct_upload_service.delete_incoming_object(tampered)

    assert read_error.value.code == "DIRECT_UPLOAD_OBJECT_KEY_INVALID"
    assert delete_error.value.code == "DIRECT_UPLOAD_OBJECT_KEY_INVALID"
    assert transient.get(key) == content
