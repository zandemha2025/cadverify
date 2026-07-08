"""Shared CONTRACT tests: every object-store adapter must satisfy one spec.

The same behavioral suite runs against:
  * ``local``  -- the real local-filesystem adapter (runs for real here).
  * ``s3``     -- the boto3 adapter, exercised against an in-memory S3
                  stand-in (moto). This genuinely drives the boto3 code path
                  (``put_object``/``get_object``/``head_object``/``delete_object``)
                  without a live endpoint. LIVE S3/MinIO is an EXTERNAL GATE
                  (see ``test_storage_s3_live.py`` / the ops-truth doc).

If moto/boto3 are unavailable, the ``s3`` parametrization is skipped (never
silently passed) and the ``local`` contract still runs.
"""
from __future__ import annotations

import io

import pytest

from src.storage import LocalObjectStore, ObjectNotFoundError, ObjectStore

# ---------------------------------------------------------------------------
# Adapter fixtures -- each yields a ready-to-use ObjectStore.
# ---------------------------------------------------------------------------


@pytest.fixture
def local_store(tmp_path) -> LocalObjectStore:
    return LocalObjectStore(tmp_path / "blobs")


@pytest.fixture
def s3_store():
    """A moto-backed S3 store (in-memory), or skip if moto/boto3 absent."""
    moto = pytest.importorskip("moto", reason="moto not installed; S3 contract skipped")
    boto3 = pytest.importorskip("boto3", reason="boto3 not installed; S3 contract skipped")
    from src.storage import S3ObjectStore

    mock = moto.mock_aws()
    mock.start()
    try:
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="cadverify-test")
        yield S3ObjectStore("cadverify-test", prefix="meshes", client=client)
    finally:
        mock.stop()


@pytest.fixture(params=["local", "s3"])
def store(request) -> ObjectStore:
    return request.getfixturevalue(f"{request.param}_store")


# ---------------------------------------------------------------------------
# The shared behavioral spec.
# ---------------------------------------------------------------------------


def test_put_get_roundtrip(store: ObjectStore):
    payload = b"solid mesh bytes \x00\x01\x02"
    store.put("a/b/model.bin", payload, content_type="application/octet-stream")
    assert store.get("a/b/model.bin") == payload


def test_exists_reflects_presence(store: ObjectStore):
    assert store.exists("missing.bin") is False
    store.put("present.bin", b"x")
    assert store.exists("present.bin") is True


def test_get_missing_raises_object_not_found(store: ObjectStore):
    with pytest.raises(ObjectNotFoundError):
        store.get("nope/never.bin")


def test_open_missing_raises_object_not_found(store: ObjectStore):
    with pytest.raises(ObjectNotFoundError):
        store.open("nope/never.bin")


def test_overwrite_replaces_bytes(store: ObjectStore):
    store.put("k.bin", b"first")
    store.put("k.bin", b"second-longer")
    assert store.get("k.bin") == b"second-longer"


def test_delete_is_idempotent(store: ObjectStore):
    store.put("d.bin", b"bye")
    store.delete("d.bin")
    assert store.exists("d.bin") is False
    # deleting again must not raise
    store.delete("d.bin")


def test_put_accepts_binary_stream(store: ObjectStore):
    """Streaming-friendly: put() takes a readable binary file object."""
    src = io.BytesIO(b"streamed-" + b"z" * 1024)
    store.put("stream.bin", src)
    assert store.get("stream.bin") == b"streamed-" + b"z" * 1024


def test_open_returns_readable_stream(store: ObjectStore):
    store.put("r.bin", b"chunkable-content")
    fh = store.open("r.bin")
    try:
        assert fh.read() == b"chunkable-content"
    finally:
        fh.close()


def test_url_is_scheme_qualified_locator(store: ObjectStore):
    store.put("u.bin", b"x")
    url = store.url("u.bin")
    assert isinstance(url, str) and url
    assert url.startswith(("file://", "s3://"))


def test_content_type_is_accepted(store: ObjectStore):
    # Local ignores it; S3 records it. Neither may error on a valid type.
    store.put("ct.bin", b"payload", content_type="model/stl")
    assert store.get("ct.bin") == b"payload"


def test_key_traversal_is_rejected(store: ObjectStore):
    with pytest.raises((ValueError, Exception)):
        store.put("../escape.bin", b"nope")


# ---------------------------------------------------------------------------
# Local-adapter specifics (the on-disk contract the wiring relies on).
# ---------------------------------------------------------------------------


def test_local_put_lands_on_disk_at_expected_path(local_store: LocalObjectStore):
    import os

    local_store.put("meshes/deadbeef.bin", b"bytes")
    path = local_store.local_path("meshes/deadbeef.bin")
    assert os.path.isfile(path)
    with open(path, "rb") as fh:
        assert fh.read() == b"bytes"


def test_content_type_recorded_on_s3(s3_store):
    """S3 adapter really writes ContentType metadata (moto-verified)."""
    s3_store.put("typed.bin", b"payload", content_type="model/stl")
    head = s3_store._client().head_object(Bucket="cadverify-test", Key="meshes/typed.bin")
    assert head["ContentType"] == "model/stl"
