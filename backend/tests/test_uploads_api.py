"""HTTP contract tests for the org-scoped direct-upload lifecycle."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.uploads import router
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import DirectUpload
from src.services import direct_upload_service as service


def _upload(status: str = "initiated") -> DirectUpload:
    return DirectUpload(
        id=1,
        ulid="UPLOAD_01",
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
        actual_size_bytes=9 if status == "completed" else None,
        part_size_bytes=5 * 1024**2,
        part_count=1,
        object_key="incoming/org-a/UPLOAD_01/batch.zip",
        multipart_upload_id="provider-secret",
        prepare_attempts=0,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        completed_at=datetime.now(timezone.utc) if status == "completed" else None,
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


def test_initiate_returns_canonical_abort_url_without_provider_coordinates():
    upload = _upload()
    parts = [
        {
            "part_number": 1,
            "url": "https://signed.example/part",
            "expires_at": upload.expires_at.isoformat(),
        }
    ]
    initiate = AsyncMock(return_value=(upload, parts, True, False))
    with patch.object(service, "initiate", new=initiate):
        response = TestClient(_app()).post(
            "/api/v1/uploads/multipart",
            headers={"Idempotency-Key": "browser-attempt-0001"},
            json={
                "purpose": "batch_zip",
                "filename": "parts.zip",
                "content_type": "application/zip",
                "size_bytes": 9,
                "checksum_sha256": "a" * 64,
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["direct_upload_id"] == upload.ulid
    assert body["abort_url"] == f"/api/v1/uploads/{upload.ulid}/abort"
    assert body["complete_url"] == f"/api/v1/uploads/{upload.ulid}/complete"
    assert body["idempotent_replay"] is False
    assert body["checksum_sha256"] == "a" * 64
    assert "object_key" not in body
    assert "multipart_upload_id" not in body
    assert "bucket" not in body
    assert initiate.await_args.kwargs["checksum_sha256"] == "a" * 64
    assert initiate.await_args.kwargs["idempotency_key"] == "browser-attempt-0001"


def test_initiate_rejects_caller_bucket_and_key_fields():
    initiate = AsyncMock()
    with patch.object(service, "initiate", new=initiate):
        response = TestClient(_app()).post(
            "/api/v1/uploads/multipart",
            json={
                "purpose": "batch_zip",
                "filename": "parts.zip",
                "content_type": "application/zip",
                "size_bytes": 9,
                "checksum_sha256": "a" * 64,
                "bucket": "attacker-bucket",
                "key": "other-org/parts.zip",
            },
        )
    assert response.status_code == 422
    initiate.assert_not_awaited()


def test_initiate_requires_idempotency_header_before_touching_storage():
    response = TestClient(_app()).post(
        "/api/v1/uploads/multipart",
        json={
            "purpose": "batch_zip",
            "filename": "parts.zip",
            "content_type": "application/zip",
            "size_bytes": 9,
            "checksum_sha256": "a" * 64,
        },
    )
    assert response.status_code == 422
    assert (
        response.json()["detail"]["code"]
        == "DIRECT_UPLOAD_IDEMPOTENCY_KEY_REQUIRED"
    )


def test_initiate_requires_stable_sha256_contract():
    response = TestClient(_app()).post(
        "/api/v1/uploads/multipart",
        headers={"Idempotency-Key": "browser-attempt-0001"},
        json={
            "purpose": "batch_zip",
            "filename": "parts.zip",
            "content_type": "application/zip",
            "size_bytes": 9,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DIRECT_UPLOAD_INVALID_CHECKSUM"


def test_complete_and_abort_routes_use_stable_lifecycle_shapes():
    completed = _upload("completed")
    aborted = _upload("aborted")
    complete = AsyncMock(return_value=completed)
    abort = AsyncMock(return_value=aborted)
    with patch.object(service, "complete", new=complete), patch.object(
        service, "abort", new=abort
    ):
        client = TestClient(_app())
        complete_response = client.post(
            f"/api/v1/uploads/{completed.ulid}/complete",
            json={"parts": [{"part_number": 1, "etag": '"etag"'}]},
        )
        canonical_abort = client.post(
            f"/api/v1/uploads/{aborted.ulid}/abort"
        )
        compatibility_abort = client.delete(
            f"/api/v1/uploads/multipart/{aborted.ulid}"
        )

    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "completed"
    assert canonical_abort.status_code == 200
    assert compatibility_abort.status_code == 200
    request_session = complete.await_args.args[0]
    complete.assert_awaited_once_with(
        request_session,
        user_id=42,
        upload_ulid=completed.ulid,
        parts=[{"part_number": 1, "etag": '"etag"'}],
    )
    assert abort.await_count == 2


def test_cross_org_status_is_indistinguishable_404():
    not_found = service.DirectUploadError(
        404,
        "DIRECT_UPLOAD_NOT_FOUND",
        "Direct upload not found.",
    )
    with patch.object(
        service,
        "get_status",
        new=AsyncMock(side_effect=not_found),
    ):
        response = TestClient(_app()).get(
            "/api/v1/uploads/UPLOAD_FROM_OTHER_ORG"
        )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DIRECT_UPLOAD_NOT_FOUND"


def test_production_http_contract_refuses_missing_transient_store_without_leaking(
    monkeypatch,
):
    monkeypatch.setenv("RELEASE", "production")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "s3")
    monkeypatch.setenv("OBJECT_STORE_S3_BUCKET", "proofshape-durable-artifacts")
    monkeypatch.setenv("OBJECT_STORE_S3_PREFIX", "production")
    monkeypatch.setenv("OBJECT_STORE_S3_REGION", "us-east-1")
    for name in (
        "DIRECT_UPLOAD_S3_BUCKET",
        "DIRECT_UPLOAD_S3_PREFIX",
        "DIRECT_UPLOAD_S3_REGION",
        "DIRECT_UPLOAD_S3_KMS_KEY_ID",
        "DIRECT_UPLOAD_S3_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)

    client = TestClient(_app())
    capability_response = client.get(
        "/api/v1/uploads/capabilities?purpose=batch_zip"
    )
    initiate_response = client.post(
        "/api/v1/uploads/multipart",
        headers={"Idempotency-Key": "browser-attempt-0001"},
        json={
            "purpose": "batch_zip",
            "filename": "parts.zip",
            "content_type": "application/zip",
            "size_bytes": 9,
            "checksum_sha256": "a" * 64,
        },
    )

    assert capability_response.status_code == 200
    capability = capability_response.json()
    assert capability["available"] is False
    assert capability["unavailable_code"] == "DIRECT_UPLOAD_STORAGE_UNAVAILABLE"
    assert not {"bucket", "prefix", "region", "kms_key_id"}.intersection(
        capability
    )
    assert initiate_response.status_code == 503
    detail = initiate_response.json()["detail"]
    assert detail["code"] == "DIRECT_UPLOAD_STORAGE_UNAVAILABLE"
    assert "DIRECT_UPLOAD_S3" not in detail["message"]
    assert "proofshape-durable-artifacts" not in initiate_response.text
