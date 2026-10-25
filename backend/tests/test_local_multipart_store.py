"""Local multipart store: the relay path for direct uploads on the local backend."""
from __future__ import annotations

import hashlib
import io

import pytest

from src.storage import LocalMultipartStore, ObjectNotFoundError, ObjectStoreError, PartTooLargeError


@pytest.fixture
def store(tmp_path):
    return LocalMultipartStore(tmp_path / "incoming")


KEY = "incoming/org-a/UPLOAD1/part.step"


def _md5(b: bytes) -> str:
    return f'"{hashlib.md5(b).hexdigest()}"'


def test_parts_join_in_order_into_the_object(store):
    uid = store.create_multipart_upload(KEY, content_type="application/octet-stream", metadata={"purpose": "part"})
    second, first = b"world" * 3, b"hello " * 4
    e2, n2 = store.put_part(KEY, uid, 2, io.BytesIO(second), max_bytes=100)
    e1, n1 = store.put_part(KEY, uid, 1, io.BytesIO(first), max_bytes=100)
    assert (e1, n1, e2, n2) == (_md5(first), len(first), _md5(second), len(second))
    assert store.list_parts(KEY, uid) == [
        {"part_number": 1, "etag": e1, "size_bytes": len(first)},
        {"part_number": 2, "etag": e2, "size_bytes": len(second)},
    ]
    meta = store.complete_multipart_upload(KEY, uid, [{"PartNumber": 2, "ETag": e2}, {"PartNumber": 1, "ETag": e1}])
    assert meta.size_bytes == len(first + second)
    assert meta.content_type == "application/octet-stream"
    assert meta.etag and meta.etag.endswith('-2"')
    with store.open(KEY) as fh:
        assert fh.read() == first + second
    # The parts are gone and never listed as objects.
    assert store.list_keys("incoming") == [KEY]
    with pytest.raises(ObjectNotFoundError):
        store.list_parts(KEY, uid)


def test_a_resent_part_replaces_the_first_copy(store):
    uid = store.create_multipart_upload(KEY, content_type="application/octet-stream")
    store.put_part(KEY, uid, 1, io.BytesIO(b"broken"), max_bytes=100)
    etag, _ = store.put_part(KEY, uid, 1, io.BytesIO(b"good bytes"), max_bytes=100)
    assert store.list_parts(KEY, uid) == [{"part_number": 1, "etag": etag, "size_bytes": 10}]
    store.complete_multipart_upload(KEY, uid, [{"PartNumber": 1, "ETag": etag}])
    assert store.get(KEY) == b"good bytes"


def test_an_oversized_part_is_refused_and_leaves_nothing(store):
    uid = store.create_multipart_upload(KEY, content_type="application/octet-stream")
    with pytest.raises(PartTooLargeError):
        store.put_part(KEY, uid, 1, io.BytesIO(b"x" * 101), max_bytes=100)
    assert store.list_parts(KEY, uid) == []


def test_completion_checks_every_part_and_its_etag(store):
    uid = store.create_multipart_upload(KEY, content_type="application/octet-stream")
    etag, _ = store.put_part(KEY, uid, 1, io.BytesIO(b"abc"), max_bytes=10)
    with pytest.raises(ObjectStoreError, match="never received"):
        store.complete_multipart_upload(KEY, uid, [{"PartNumber": 1, "ETag": etag}, {"PartNumber": 2, "ETag": etag}])
    with pytest.raises(ObjectStoreError, match="does not match"):
        store.complete_multipart_upload(KEY, uid, [{"PartNumber": 1, "ETag": '"0000"'}])
    assert not store.exists(KEY)


def test_an_upload_belongs_to_its_key_and_ids_are_opaque(store):
    uid = store.create_multipart_upload(KEY, content_type="application/octet-stream")
    with pytest.raises(ObjectStoreError):
        store.put_part("incoming/org-b/OTHER/part.step", uid, 1, io.BytesIO(b"x"), max_bytes=10)
    with pytest.raises(ValueError):
        store.list_parts(KEY, "../../etc")
    with pytest.raises(ValueError):
        store.create_multipart_upload("../escape", content_type="application/octet-stream")


def test_abort_is_idempotent_and_delete_removes_metadata(store):
    uid = store.create_multipart_upload(KEY, content_type="application/zip")
    etag, _ = store.put_part(KEY, uid, 1, io.BytesIO(b"zip"), max_bytes=10)
    store.abort_multipart_upload(KEY, uid)
    store.abort_multipart_upload(KEY, uid)
    uid = store.create_multipart_upload(KEY, content_type="application/zip")
    etag, _ = store.put_part(KEY, uid, 1, io.BytesIO(b"zip"), max_bytes=10)
    store.complete_multipart_upload(KEY, uid, [{"PartNumber": 1, "ETag": etag}])
    assert store.stat(KEY).content_type == "application/zip"
    store.delete(KEY)
    store.delete(KEY)
    with pytest.raises(ObjectNotFoundError):
        store.stat(KEY)
    assert store.list_keys("") == []


def test_s3_lists_received_parts_for_resume():
    moto = pytest.importorskip("moto")
    boto3 = pytest.importorskip("boto3")
    from src.storage import S3ObjectStore

    with moto.mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="cadverify-direct-test")
        store = S3ObjectStore("cadverify-direct-test", prefix="direct-uploads", client=client)
        uid = store.create_multipart_upload(KEY, content_type="application/octet-stream")
        body = b"p" * (5 * 1024 * 1024)
        r1 = client.upload_part(Bucket="cadverify-direct-test", Key=f"direct-uploads/{KEY}", UploadId=uid, PartNumber=1, Body=body)
        r3 = client.upload_part(Bucket="cadverify-direct-test", Key=f"direct-uploads/{KEY}", UploadId=uid, PartNumber=3, Body=b"tail")
        assert store.list_parts(KEY, uid) == [
            {"part_number": 1, "etag": r1["ETag"], "size_bytes": len(body)},
            {"part_number": 3, "etag": r3["ETag"], "size_bytes": 4},
        ]
        assert store.transport == "s3"
