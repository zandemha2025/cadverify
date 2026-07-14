"""Object-store selection for durable artifacts and transient direct uploads.

Local disk remains the default for durable application artifacts unless an
operator explicitly opts into S3. Browser-to-S3 multipart uploads are a
different retention class: they must use the dedicated ``DIRECT_UPLOAD_S3_*``
contract and are never silently routed through the durable artifact bucket.

Environment:
* ``OBJECT_STORE_BACKEND``  -- ``"local"`` (default) or ``"s3"``.
* S3 (only read when backend=s3): ``OBJECT_STORE_S3_BUCKET`` (required),
  ``OBJECT_STORE_S3_ENDPOINT`` (MinIO/custom endpoint, optional),
  ``OBJECT_STORE_S3_REGION`` (optional), ``OBJECT_STORE_S3_PREFIX`` (optional).
* Direct uploads: ``DIRECT_UPLOAD_S3_BUCKET``, ``DIRECT_UPLOAD_S3_PREFIX``,
  ``DIRECT_UPLOAD_S3_REGION``, and ``DIRECT_UPLOAD_S3_KMS_KEY_ID`` are all
  required. ``DIRECT_UPLOAD_S3_ENDPOINT`` is optional for explicit local/Moto
  testing and is never inherited from the durable store.

``get_object_store(purpose, default_root)`` returns a store for a logical
namespace. For the local backend the root defaults to the caller-supplied
``default_root`` (the existing ``*_BLOB_DIR`` value), so wiring a call site
through this factory is byte-for-byte behavior-preserving.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from src.storage.base import ObjectStore
from src.storage.local import LocalObjectStore
from src.storage.s3 import S3ObjectStore

_S3_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


class DirectUploadStoreConfigurationError(ValueError):
    """Raised when the isolated transient-upload namespace is unsafe."""


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
        root_prefix = os.getenv("OBJECT_STORE_S3_PREFIX", "").strip("/")
        prefix = "/".join(part for part in (root_prefix, purpose) if part)
        return S3ObjectStore(
            bucket,
            prefix=prefix,
            endpoint_url=os.getenv("OBJECT_STORE_S3_ENDPOINT") or None,
            region_name=os.getenv("OBJECT_STORE_S3_REGION") or None,
            kms_key_id=os.getenv("OBJECT_STORE_S3_KMS_KEY_ID") or None,
        )
    raise ValueError(
        f"unknown OBJECT_STORE_BACKEND={backend!r} (expected 'local' or 's3')"
    )


def _required_direct_upload_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise DirectUploadStoreConfigurationError(
            f"{name} is required for the transient direct-upload store"
        )
    return value


def _normalise_direct_upload_prefix(raw: str) -> str:
    prefix = raw.strip("/")
    components = prefix.split("/") if prefix else []
    if (
        not components
        or any(component in {"", ".", ".."} for component in components)
        or "\\" in prefix
    ):
        raise DirectUploadStoreConfigurationError(
            "DIRECT_UPLOAD_S3_PREFIX must be a non-empty relative S3 prefix"
        )
    return prefix


def _direct_upload_endpoint() -> str | None:
    endpoint = os.getenv("DIRECT_UPLOAD_S3_ENDPOINT", "").strip()
    if not endpoint:
        return None
    try:
        parsed = urlsplit(endpoint)
    except ValueError as exc:
        raise DirectUploadStoreConfigurationError(
            "DIRECT_UPLOAD_S3_ENDPOINT must be a canonical HTTP(S) origin"
        ) from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise DirectUploadStoreConfigurationError(
            "DIRECT_UPLOAD_S3_ENDPOINT must be a canonical HTTP(S) origin"
        )

    # A custom endpoint is useful for an explicit local Moto/MinIO test. A
    # released service may use one only over TLS; the AWS deployment leaves this
    # unset and therefore uses the regional AWS endpoint selected by boto3.
    from src.config.production import is_production

    if is_production() and parsed.scheme != "https":
        raise DirectUploadStoreConfigurationError(
            "DIRECT_UPLOAD_S3_ENDPOINT must use HTTPS in production"
        )
    return endpoint.rstrip("/")


def get_direct_upload_store() -> S3ObjectStore:
    """Return the isolated, short-lived incoming-upload S3 namespace.

    There is intentionally no implicit local or durable-store fallback. Tests
    that use Moto/MinIO must provide the complete ``DIRECT_UPLOAD_S3_*`` set and
    an explicit ``DIRECT_UPLOAD_S3_ENDPOINT`` when one is needed. Requiring a
    physically different bucket prevents versioned durable retention from
    accidentally preserving customer upload ZIPs after application cleanup.
    """
    if selected_backend() != "s3":
        raise DirectUploadStoreConfigurationError(
            "direct uploads require OBJECT_STORE_BACKEND=s3"
        )

    durable_bucket = os.getenv("OBJECT_STORE_S3_BUCKET", "").strip()
    if not durable_bucket:
        raise DirectUploadStoreConfigurationError(
            "OBJECT_STORE_S3_BUCKET is required to prove transient isolation"
        )

    bucket = _required_direct_upload_env("DIRECT_UPLOAD_S3_BUCKET")
    if not _S3_BUCKET.fullmatch(bucket) or ".." in bucket:
        raise DirectUploadStoreConfigurationError(
            "DIRECT_UPLOAD_S3_BUCKET is not a valid AWS S3 bucket name"
        )
    if bucket.casefold() == durable_bucket.casefold():
        raise DirectUploadStoreConfigurationError(
            "DIRECT_UPLOAD_S3_BUCKET must be physically distinct from "
            "OBJECT_STORE_S3_BUCKET"
        )

    root_prefix = _normalise_direct_upload_prefix(
        _required_direct_upload_env("DIRECT_UPLOAD_S3_PREFIX")
    )
    region = _required_direct_upload_env("DIRECT_UPLOAD_S3_REGION")
    kms_key_id = _required_direct_upload_env("DIRECT_UPLOAD_S3_KMS_KEY_ID")
    prefix = f"{root_prefix}/direct-uploads"

    return S3ObjectStore(
        bucket,
        prefix=prefix,
        endpoint_url=_direct_upload_endpoint(),
        region_name=region,
        kms_key_id=kms_key_id,
    )
