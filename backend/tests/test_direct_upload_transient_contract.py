"""Fail-closed configuration contract for transient browser uploads."""
from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from src.services import direct_upload_service
from src.storage import (
    DirectUploadStoreConfigurationError,
    get_direct_upload_store,
    get_object_store,
)


def _configure_complete_contract(monkeypatch, *, release: str = "production") -> None:
    monkeypatch.setenv("RELEASE", release)
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "s3")
    monkeypatch.setenv("OBJECT_STORE_S3_BUCKET", "proofshape-durable-artifacts")
    monkeypatch.setenv("OBJECT_STORE_S3_PREFIX", "production")
    monkeypatch.setenv("OBJECT_STORE_S3_REGION", "us-west-2")
    monkeypatch.setenv("OBJECT_STORE_S3_KMS_KEY_ID", "alias/durable-artifacts")
    monkeypatch.setenv("OBJECT_STORE_S3_ENDPOINT", "https://durable.example.test")
    monkeypatch.setenv("DIRECT_UPLOAD_S3_BUCKET", "proofshape-transient-uploads")
    monkeypatch.setenv("DIRECT_UPLOAD_S3_PREFIX", "/production/")
    monkeypatch.setenv("DIRECT_UPLOAD_S3_REGION", "us-east-1")
    monkeypatch.setenv(
        "DIRECT_UPLOAD_S3_KMS_KEY_ID",
        "arn:aws:kms:us-east-1:111122223333:key/transient-key",
    )
    monkeypatch.delenv("DIRECT_UPLOAD_S3_ENDPOINT", raising=False)


def test_transient_factory_uses_only_direct_upload_coordinates(monkeypatch):
    _configure_complete_contract(monkeypatch)

    transient = get_direct_upload_store()
    durable = get_object_store("batch-files", default_root="/unused")

    assert transient._bucket == "proofshape-transient-uploads"
    assert transient._prefix == "production/direct-uploads"
    assert transient._region_name == "us-east-1"
    assert transient._kms_key_id.endswith("key/transient-key")
    assert transient._endpoint_url is None
    assert durable._bucket == "proofshape-durable-artifacts"
    assert durable._prefix == "production/batch-files"
    assert durable._region_name == "us-west-2"
    assert durable._kms_key_id == "alias/durable-artifacts"
    assert durable._endpoint_url == "https://durable.example.test"


def test_transient_kms_and_namespace_are_sent_to_s3_not_durable_values(monkeypatch):
    _configure_complete_contract(monkeypatch)
    store = get_direct_upload_store()
    calls: list[dict] = []

    class _Client:
        def create_multipart_upload(self, **kwargs):
            calls.append(kwargs)
            return {"UploadId": "provider-private"}

    store._cached_client = _Client()
    upload_id = store.create_multipart_upload(
        "incoming/org-a/upload-a/batch.zip",
        content_type="application/zip",
        metadata={"purpose": "batch_zip"},
    )

    assert upload_id == "provider-private"
    assert calls == [
        {
            "Bucket": "proofshape-transient-uploads",
            "Key": (
                "production/direct-uploads/incoming/org-a/upload-a/batch.zip"
            ),
            "ContentType": "application/zip",
            "Metadata": {"purpose": "batch_zip"},
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": (
                "arn:aws:kms:us-east-1:111122223333:key/transient-key"
            ),
        }
    ]


@pytest.mark.parametrize(
    "missing",
    [
        "DIRECT_UPLOAD_S3_BUCKET",
        "DIRECT_UPLOAD_S3_PREFIX",
        "DIRECT_UPLOAD_S3_REGION",
        "DIRECT_UPLOAD_S3_KMS_KEY_ID",
    ],
)
def test_transient_factory_requires_the_complete_exact_contract(monkeypatch, missing):
    _configure_complete_contract(monkeypatch)
    monkeypatch.delenv(missing)

    with pytest.raises(DirectUploadStoreConfigurationError, match=missing):
        get_direct_upload_store()


def test_transient_factory_never_falls_back_to_complete_durable_config(monkeypatch):
    _configure_complete_contract(monkeypatch)
    for name in (
        "DIRECT_UPLOAD_S3_BUCKET",
        "DIRECT_UPLOAD_S3_PREFIX",
        "DIRECT_UPLOAD_S3_REGION",
        "DIRECT_UPLOAD_S3_KMS_KEY_ID",
    ):
        monkeypatch.delenv(name)

    with pytest.raises(
        DirectUploadStoreConfigurationError,
        match="DIRECT_UPLOAD_S3_BUCKET",
    ):
        get_direct_upload_store()


def test_transient_factory_rejects_same_physical_bucket_even_with_other_prefix(
    monkeypatch,
):
    _configure_complete_contract(monkeypatch)
    monkeypatch.setenv("DIRECT_UPLOAD_S3_BUCKET", "proofshape-durable-artifacts")
    monkeypatch.setenv("DIRECT_UPLOAD_S3_PREFIX", "short-lived-only")

    with pytest.raises(
        DirectUploadStoreConfigurationError,
        match="physically distinct",
    ):
        get_direct_upload_store()


@pytest.mark.parametrize("prefix", ["", "/", "../escape", "safe/../escape", "a\\b"])
def test_transient_factory_rejects_empty_or_escaping_prefix(monkeypatch, prefix):
    _configure_complete_contract(monkeypatch)
    monkeypatch.setenv("DIRECT_UPLOAD_S3_PREFIX", prefix)

    with pytest.raises(
        DirectUploadStoreConfigurationError,
        match="DIRECT_UPLOAD_S3_PREFIX",
    ):
        get_direct_upload_store()


def test_explicit_moto_endpoint_is_allowed_only_as_explicit_nonproduction_config(
    monkeypatch,
):
    _configure_complete_contract(monkeypatch, release="test")
    monkeypatch.setenv("DIRECT_UPLOAD_S3_ENDPOINT", "http://127.0.0.1:5001/")

    store = get_direct_upload_store()

    assert store._endpoint_url == "http://127.0.0.1:5001"
    assert urlsplit(store._endpoint_url).hostname == "127.0.0.1"


def test_production_rejects_insecure_direct_upload_endpoint(monkeypatch):
    _configure_complete_contract(monkeypatch, release="2026.07.14")
    monkeypatch.setenv("DIRECT_UPLOAD_S3_ENDPOINT", "http://moto.internal:5001")

    with pytest.raises(
        DirectUploadStoreConfigurationError,
        match="HTTPS in production",
    ):
        get_direct_upload_store()


def test_production_capability_and_service_fail_closed_without_transient_contract(
    monkeypatch,
):
    _configure_complete_contract(monkeypatch)
    monkeypatch.delenv("DIRECT_UPLOAD_S3_KMS_KEY_ID")

    capability = direct_upload_service.capability()

    assert capability["available"] is False
    assert capability["direct_upload"] is False
    assert capability["unavailable_code"] == "DIRECT_UPLOAD_STORAGE_UNAVAILABLE"
    assert "bucket" not in capability
    assert "prefix" not in capability
    assert "region" not in capability
    assert "kms" not in capability
    with pytest.raises(direct_upload_service.DirectUploadError) as exc:
        direct_upload_service._require_s3_store()
    assert exc.value.status_code == 503
    assert exc.value.code == "DIRECT_UPLOAD_STORAGE_UNAVAILABLE"
    assert "DIRECT_UPLOAD_S3" not in exc.value.message
    assert "proofshape-" not in exc.value.message
