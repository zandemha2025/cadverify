"""S3-compatible object-store adapter (boto3 against any S3 endpoint).

Works against AWS S3, MinIO, or any S3-compatible endpoint via ``endpoint_url``.

Import safety (F-ARCH constraint): this module MUST be importable when boto3 is
absent. ``boto3`` is therefore imported lazily inside :meth:`_client`, so the
only place a missing dependency surfaces is when an S3 store is actually
constructed/used -- with a clear, actionable error -- never at import time and
never for a deployment that only uses the local adapter.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, BinaryIO

from src.storage.base import ObjectNotFoundError, ObjectStore, ObjectStoreError, Payload

if TYPE_CHECKING:  # pragma: no cover - typing only, not imported at runtime
    pass


_BOTO3_MISSING_MSG = (
    "The S3 object-store backend requires boto3. Install it "
    "(`pip install boto3`) or select OBJECT_STORE_BACKEND=local."
)


class S3ObjectStore(ObjectStore):
    """Store objects in an S3 bucket under an optional key ``prefix``.

    Parameters mirror what an operator configures via env (see
    :func:`~src.storage.factory.get_object_store`). A pre-built boto3 ``client``
    may be injected (used by the contract tests against an in-memory stand-in).
    """

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        client: Any | None = None,
    ):
        if not bucket:
            raise ValueError("S3ObjectStore requires a bucket name")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._endpoint_url = endpoint_url
        self._region_name = region_name
        self._injected_client = client
        self._cached_client = client

    # -- lazy boto3 client ---------------------------------------------------
    def _client(self) -> Any:
        if self._cached_client is not None:
            return self._cached_client
        try:
            import boto3  # type: ignore[import-not-found]  # optional dep; lazy
        except ImportError as exc:  # pragma: no cover - exercised via test shim
            raise ObjectStoreError(_BOTO3_MISSING_MSG) from exc
        self._cached_client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region_name,
        )
        return self._cached_client

    def _full_key(self, key: str) -> str:
        if not key or key.startswith("/"):
            raise ValueError(f"invalid object key {key!r}")
        if ".." in key.split("/"):
            raise ValueError(f"object key escapes prefix: {key!r}")
        return f"{self._prefix}/{key}" if self._prefix else key

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        # botocore ClientError carries an HTTP status / error code; a missing
        # object is 404 / NoSuchKey / 404-coded head_object.
        resp = getattr(exc, "response", None) or {}
        err = resp.get("Error", {}) if isinstance(resp, dict) else {}
        code = str(err.get("Code", ""))
        status = resp.get("ResponseMetadata", {}).get("HTTPStatusCode") if isinstance(resp, dict) else None
        return code in {"404", "NoSuchKey", "NoSuchBucket"} or status == 404

    # -- write ---------------------------------------------------------------
    def put(self, key: str, data: Payload, *, content_type: str | None = None) -> str:
        # Coalesce to a single bytes body. boto3 supports streaming bodies, but
        # a bounded join keeps behavior identical across botocore versions and
        # avoids surprises with non-seekable streams on retry.
        body = b"".join(self._iter_chunks(data))
        extra: dict[str, Any] = {}
        if content_type:
            extra["ContentType"] = content_type
        self._client().put_object(
            Bucket=self._bucket, Key=self._full_key(key), Body=body, **extra
        )
        return self.url(key)

    # -- read ----------------------------------------------------------------
    def get(self, key: str) -> bytes:
        try:
            resp = self._client().get_object(Bucket=self._bucket, Key=self._full_key(key))
        except Exception as exc:  # noqa: BLE001 - normalise botocore errors
            if self._is_not_found(exc):
                raise ObjectNotFoundError(key) from exc
            raise
        return resp["Body"].read()

    def open(self, key: str) -> BinaryIO:
        try:
            resp = self._client().get_object(Bucket=self._bucket, Key=self._full_key(key))
        except Exception as exc:  # noqa: BLE001
            if self._is_not_found(exc):
                raise ObjectNotFoundError(key) from exc
            raise
        # botocore StreamingBody is a readable binary file-like object.
        return resp["Body"]

    # -- metadata / lifecycle ------------------------------------------------
    def exists(self, key: str) -> bool:
        try:
            self._client().head_object(Bucket=self._bucket, Key=self._full_key(key))
            return True
        except Exception as exc:  # noqa: BLE001
            if self._is_not_found(exc):
                return False
            raise

    def delete(self, key: str) -> None:
        # S3 delete_object is idempotent (no error for a missing key).
        self._client().delete_object(Bucket=self._bucket, Key=self._full_key(key))

    def url(self, key: str) -> str:
        return f"s3://{self._bucket}/{self._full_key(key)}"

    def presigned_url(self, key: str, *, expires_in: int = 3600) -> str:
        """Return a time-limited HTTPS URL for ``key`` (S3-specific extra)."""
        return self._client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": self._full_key(key)},
            ExpiresIn=expires_in,
        )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"S3ObjectStore(bucket={self._bucket!r}, prefix={self._prefix!r})"
