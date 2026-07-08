"""Object-store selection. Local disk is the default; behavior is unchanged
unless an operator explicitly opts into an S3 backend.

Environment:
* ``OBJECT_STORE_BACKEND``  -- ``"local"`` (default) or ``"s3"``.
* S3 (only read when backend=s3): ``OBJECT_STORE_S3_BUCKET`` (required),
  ``OBJECT_STORE_S3_ENDPOINT`` (MinIO/custom endpoint, optional),
  ``OBJECT_STORE_S3_REGION`` (optional), ``OBJECT_STORE_S3_PREFIX`` (optional).

``get_object_store(purpose, default_root)`` returns a store for a logical
namespace. For the local backend the root defaults to the caller-supplied
``default_root`` (the existing ``*_BLOB_DIR`` value), so wiring a call site
through this factory is byte-for-byte behavior-preserving.
"""
from __future__ import annotations

import os

from src.storage.base import ObjectStore
from src.storage.local import LocalObjectStore
from src.storage.s3 import S3ObjectStore

_TRUTHY = {"1", "true", "yes", "on"}


def selected_backend() -> str:
    return os.getenv("OBJECT_STORE_BACKEND", "local").strip().lower() or "local"


def get_object_store(purpose: str, *, default_root: str) -> ObjectStore:
    """Return the configured object store for ``purpose``.

    ``purpose`` is a short logical namespace (e.g. ``"meshes"``) used as the S3
    key prefix and, for local, as the leaf under ``default_root`` only when an
    explicit ``OBJECT_STORE_LOCAL_ROOT`` is set. When no object-store env is
    configured the local store is rooted exactly at ``default_root`` so nothing
    about the on-disk layout changes.
    """
    backend = selected_backend()
    if backend == "local":
        local_root_base = os.getenv("OBJECT_STORE_LOCAL_ROOT")
        if local_root_base:
            root = os.path.join(local_root_base, purpose)
        else:
            root = default_root
        return LocalObjectStore(root)
    if backend == "s3":
        bucket = os.getenv("OBJECT_STORE_S3_BUCKET")
        if not bucket:
            raise ValueError(
                "OBJECT_STORE_BACKEND=s3 requires OBJECT_STORE_S3_BUCKET to be set"
            )
        prefix = os.getenv("OBJECT_STORE_S3_PREFIX", purpose)
        return S3ObjectStore(
            bucket,
            prefix=prefix,
            endpoint_url=os.getenv("OBJECT_STORE_S3_ENDPOINT") or None,
            region_name=os.getenv("OBJECT_STORE_S3_REGION") or None,
        )
    raise ValueError(
        f"unknown OBJECT_STORE_BACKEND={backend!r} (expected 'local' or 's3')"
    )
