"""Where data lives, as this deployment's configuration states it (it-10, it-11)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deployment_facts import router

_ENV = ("OBJECT_STORE_BACKEND", "OBJECT_STORE_S3_REGION", "OBJECT_STORE_S3_ENDPOINT", "OBJECT_STORE_S3_KMS_KEY_ID",
        "OBJECT_STORE_S3_BUCKET", "DEPLOYMENT_HOSTING", "DEPLOYMENT_DATA_REGION", "DEPLOYMENT_ENCRYPTION_AT_REST",
        "DEPLOYMENT_BACKUP_RETENTION_DAYS")


@pytest.fixture
def client(monkeypatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_nothing_configured_says_nothing_beyond_local_disk(client):
    body = client.get("/api/v1/deployment").json()
    assert body == {
        "file_storage": {"kind": "local", "region": None, "encryption": None, "s3_compatible": False},
        "declared": {"hosting": None, "data_region": None, "encryption_at_rest": None, "backup_retention_days": None},
    }


def test_s3_with_a_kms_key_is_stated_without_bucket_or_key(client, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "s3")
    monkeypatch.setenv("OBJECT_STORE_S3_BUCKET", "secret-bucket-name")
    monkeypatch.setenv("OBJECT_STORE_S3_REGION", "us-east-1")
    monkeypatch.setenv("OBJECT_STORE_S3_KMS_KEY_ID", "arn:aws:kms:us-east-1:123456789012:key/abc")
    r = client.get("/api/v1/deployment")
    assert r.json()["file_storage"] == {"kind": "s3", "region": "us-east-1", "encryption": "sse-kms", "s3_compatible": False}
    assert "secret-bucket-name" not in r.text and "arn:aws" not in r.text
    assert r.headers["cache-control"] == "public, max-age=300"


def test_s3_without_a_key_claims_no_encryption(client, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "s3")
    monkeypatch.setenv("OBJECT_STORE_S3_ENDPOINT", "https://minio.internal:9000")
    monkeypatch.setenv("OBJECT_STORE_S3_REGION", "not a region")
    fs = client.get("/api/v1/deployment").json()["file_storage"]
    assert fs == {"kind": "s3", "region": None, "encryption": None, "s3_compatible": True}


def test_declared_facts_come_only_from_operator_variables(client, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_HOSTING", "Render <script>")
    monkeypatch.setenv("DEPLOYMENT_DATA_REGION", "Oregon, US")
    monkeypatch.setenv("DEPLOYMENT_BACKUP_RETENTION_DAYS", "30")
    declared = client.get("/api/v1/deployment").json()["declared"]
    assert declared["hosting"] == "Render script" and declared["data_region"] == "Oregon, US"
    assert declared["backup_retention_days"] == 30 and declared["encryption_at_rest"] is None
    monkeypatch.setenv("DEPLOYMENT_BACKUP_RETENTION_DAYS", "forever")
    assert client.get("/api/v1/deployment").json()["declared"]["backup_retention_days"] is None
