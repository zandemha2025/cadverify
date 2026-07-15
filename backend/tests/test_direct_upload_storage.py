"""S3 adapter contract for server-owned multipart direct uploads."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.db.models import DirectUpload
from src.services import direct_upload_service
from src.storage import S3ObjectStore


@pytest.fixture
def multipart_store():
    moto = pytest.importorskip("moto")
    boto3 = pytest.importorskip("boto3")
    mock = moto.mock_aws()
    mock.start()
    try:
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="cadverify-direct-test")
        yield S3ObjectStore(
            "cadverify-direct-test",
            prefix="direct-uploads",
            client=client,
        ), client
    finally:
        mock.stop()


def test_s3_multipart_initiate_sign_complete_and_stat(multipart_store):
    store, client = multipart_store
    key = "incoming/org-a/upload-a/batch.zip"
    upload_id = store.create_multipart_upload(
        key,
        content_type="application/zip",
        metadata={"purpose": "batch_zip"},
    )
    signed = store.presign_upload_part(key, upload_id, 1, expires_in=300)
    assert signed.startswith("https://")
    receipt = client.upload_part(
        Bucket="cadverify-direct-test",
        Key=f"direct-uploads/{key}",
        UploadId=upload_id,
        PartNumber=1,
        Body=b"zip bytes",
    )
    metadata = store.complete_multipart_upload(
        key,
        upload_id,
        [{"PartNumber": 1, "ETag": receipt["ETag"]}],
    )
    assert metadata.size_bytes == len(b"zip bytes")
    assert metadata.content_type == "application/zip"
    assert metadata.etag


def test_s3_multipart_abort_and_key_scope(multipart_store):
    store, client = multipart_store
    key = "incoming/org-a/upload-b/batch.zip"
    upload_id = store.create_multipart_upload(
        key, content_type="application/zip"
    )
    store.abort_multipart_upload(key, upload_id)
    active = client.list_multipart_uploads(Bucket="cadverify-direct-test")
    assert active.get("Uploads", []) == []
    with pytest.raises(ValueError, match="escapes prefix"):
        store.create_multipart_upload(
            "../other-tenant/batch.zip", content_type="application/zip"
        )


def test_moto_s3_stream_is_verified_against_browser_sha256_without_buffering(
    multipart_store,
):
    store, client = multipart_store
    content = b"zip bytes"
    key = "incoming/org-a/upload-checksum/batch.zip"
    upload_id = store.create_multipart_upload(
        key,
        content_type="application/zip",
        metadata={"expected-sha256": hashlib.sha256(content).hexdigest()},
    )
    receipt = client.upload_part(
        Bucket="cadverify-direct-test",
        Key=f"direct-uploads/{key}",
        UploadId=upload_id,
        PartNumber=1,
        Body=content,
    )
    store.complete_multipart_upload(
        key,
        upload_id,
        [{"PartNumber": 1, "ETag": receipt["ETag"]}],
    )
    upload = DirectUpload(
        id=1,
        ulid="upload-checksum",
        org_id="org-a",
        user_id=1,
        idempotency_key_hash="c" * 64,
        request_fingerprint="b" * 64,
        purpose="batch_zip",
        status="completed",
        filename="parts.zip",
        content_type="application/zip",
        expected_size_bytes=len(content),
        expected_checksum_sha256=hashlib.sha256(content).hexdigest(),
        actual_size_bytes=len(content),
        part_size_bytes=5 * 1024**2,
        part_count=1,
        object_key=key,
        multipart_upload_id=upload_id,
        prepare_attempts=0,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    with patch.object(direct_upload_service, "_require_s3_store", return_value=store):
        path = direct_upload_service.download_to_bounded_tempfile(upload)
        try:
            with open(path, "rb") as verified:
                assert verified.read() == content
        finally:
            os.unlink(path)

        upload.expected_checksum_sha256 = "0" * 64
        with pytest.raises(
            direct_upload_service.DirectUploadPreparationValidationError
        ) as exc:
            direct_upload_service.download_to_bounded_tempfile(upload)

    assert exc.value.code == "DIRECT_UPLOAD_CHECKSUM_MISMATCH"
