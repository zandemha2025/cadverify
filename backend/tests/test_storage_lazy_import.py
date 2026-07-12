"""The S3 adapter must be import-safe when boto3 is absent.

We simulate a boto3-less environment with an import finder that blocks
``boto3``/``botocore``, then assert:
  * importing ``src.storage`` and ``src.storage.s3`` still succeeds;
  * constructing ``S3ObjectStore`` still succeeds (no eager client);
  * the missing dependency only surfaces -- with a clear, actionable message --
    when an operation actually needs the client.
The local adapter and the factory's default selection remain fully usable.
"""
from __future__ import annotations

import builtins
import importlib
import sys

import pytest


class _BlockBoto3:
    """A sys.meta_path finder that makes boto3/botocore imports fail."""

    def find_spec(self, name, path=None, target=None):
        if name == "boto3" or name.startswith("boto3.") or name == "botocore" or name.startswith("botocore."):
            raise ImportError(f"blocked for test: {name}")
        return None


@pytest.fixture
def no_boto3(monkeypatch):
    # Drop any cached boto3 modules and block re-import.
    for mod in list(sys.modules):
        if mod == "boto3" or mod.startswith("boto3.") or mod == "botocore" or mod.startswith("botocore."):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    finder = _BlockBoto3()
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        try:
            sys.meta_path.remove(finder)
        except ValueError:
            pass


def test_boto3_is_actually_blocked(no_boto3):
    with pytest.raises(ImportError):
        importlib.import_module("boto3")


def test_storage_package_imports_without_boto3(no_boto3):
    # Force a fresh import of the storage modules under the block.
    for mod in ["src.storage", "src.storage.s3", "src.storage.factory"]:
        sys.modules.pop(mod, None)
    storage = importlib.import_module("src.storage")
    assert hasattr(storage, "S3ObjectStore")
    assert hasattr(storage, "LocalObjectStore")


def test_s3_store_constructs_without_boto3(no_boto3):
    from src.storage import S3ObjectStore

    # Construction must not import boto3 (no eager client).
    store = S3ObjectStore("some-bucket", prefix="meshes")
    assert store is not None


def test_s3_operation_raises_clear_error_without_boto3(no_boto3):
    from src.storage import ObjectStoreError, S3ObjectStore

    store = S3ObjectStore("some-bucket")
    with pytest.raises(ObjectStoreError) as exc:
        store.put("k.bin", b"data")
    assert "boto3" in str(exc.value).lower()


def test_local_backend_default_works_without_boto3(no_boto3, tmp_path, monkeypatch):
    monkeypatch.delenv("OBJECT_STORE_BACKEND", raising=False)
    from src.storage import LocalObjectStore, get_object_store

    store = get_object_store("meshes", default_root=str(tmp_path / "blobs"))
    assert isinstance(store, LocalObjectStore)
    store.put("x.bin", b"ok")
    assert store.get("x.bin") == b"ok"
