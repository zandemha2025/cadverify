"""S3-compatible object-store adapter (boto3 against any S3 endpoint).

Works against AWS S3, MinIO, or any S3-compatible endpoint via ``endpoint_url``.

Import safety (F-ARCH constraint): this module MUST be importable when boto3 is
absent. ``boto3`` is therefore imported lazily inside :meth:`_client`, so the
only place a missing dependency surfaces is when an S3 store is actually
constructed/used -- with a clear, actionable error -- never at import time and
never for a deployment that only uses the local adapter.
"""
from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any, BinaryIO

from src.storage.base import (
    ObjectMetadata,
    ObjectNotFoundError,
    ObjectStore,
    ObjectStoreError,
    Payload,
)

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
        kms_key_id: str | None = None,
        client: Any | None = None,
    ):
        if not bucket:
            raise ValueError("S3ObjectStore requires a bucket name")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._endpoint_url = endpoint_url
        self._region_name = region_name
        self._kms_key_id = kms_key_id
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
        # A missing bucket is an infrastructure failure, not a missing customer
        # object. Do not launder it into a user-facing 404.
        if code == "NoSuchBucket":
            return False
        return code in {"404", "NoSuchKey", "NotFound"} or status == 404

    # -- write ---------------------------------------------------------------
    def put(self, key: str, data: Payload, *, content_type: str | None = None) -> str:
        extra: dict[str, Any] = {}
        if content_type:
            extra["ContentType"] = content_type
        if self._kms_key_id:
            extra["ServerSideEncryption"] = "aws:kms"
            extra["SSEKMSKeyId"] = self._kms_key_id
        client = self._client()
        full_key = self._full_key(key)
        if isinstance(data, (bytes, bytearray, memoryview)):
            client.put_object(
                Bucket=self._bucket, Key=full_key, Body=bytes(data), **extra
            )
        else:
            # boto3's managed transfer accepts non-seekable streams and switches
            # to multipart upload for large objects. This keeps a 5 GiB batch ZIP
            # entry from being joined into process memory before upload.
            kwargs: dict[str, Any] = {}
            if extra:
                kwargs["ExtraArgs"] = extra
            client.upload_fileobj(data, self._bucket, full_key, **kwargs)
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

    def list_keys(self, prefix: str = "") -> list[str]:
        full_prefix = self._full_key(f"{prefix.rstrip('/')}/") if prefix else (
            f"{self._prefix}/" if self._prefix else ""
        )
        paginator = self._client().get_paginator("list_objects_v2")
        keys: list[str] = []
        namespace = f"{self._prefix}/" if self._prefix else ""
        for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
            for item in page.get("Contents", []):
                provider_key = str(item["Key"])
                key = provider_key[len(namespace):] if namespace else provider_key
                keys.append(key)
        return sorted(keys)

    def delete_prefix(self, prefix: str) -> int:
        keys = self.list_keys(prefix)
        client = self._client()
        count = 0
        for start in range(0, len(keys), 1000):
            chunk = keys[start : start + 1000]
            if not chunk:
                continue
            response = client.delete_objects(
                Bucket=self._bucket,
                Delete={
                    "Objects": [{"Key": self._full_key(key)} for key in chunk],
                    "Quiet": True,
                },
            )
            errors = response.get("Errors", []) if isinstance(response, dict) else []
            if errors:
                codes = sorted(
                    {str(item.get("Code", "unknown")) for item in errors}
                )
                raise ObjectStoreError(
                    "S3 prefix deletion was only partially applied "
                    f"({len(errors)} errors; codes={','.join(codes)})"
                )
            count += len(chunk)
        return count

    def healthcheck(self) -> None:
        # Prove the exact data-plane permissions the application relies on,
        # including KMS encryption when configured. A bucket-level HEAD alone
        # can pass with credentials that are unable to store customer objects.
        key = f".cadverify-health/{secrets.token_hex(16)}.bin"
        payload = secrets.token_bytes(32)
        created = False
        try:
            self.put(key, payload, content_type="application/octet-stream")
            created = True
            if self.get(key) != payload:
                raise ObjectStoreError("S3 health canary round-trip mismatch")
            if key not in self.list_keys(".cadverify-health"):
                raise ObjectStoreError("S3 health canary was not listable")
            self.delete(key)
            created = False
            if self.exists(key):
                raise ObjectStoreError("S3 health canary was not deleted")
        finally:
            if created:
                try:
                    self.delete(key)
                except Exception:  # noqa: BLE001 - preserve original probe error
                    pass

    # -- direct multipart upload ---------------------------------------------
    def create_multipart_upload(
        self,
        key: str,
        *,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Create a provider multipart upload for one namespaced key.

        Bucket selection and prefix expansion remain adapter-owned. Callers can
        supply only a validated relative key, so this method never becomes a
        raw provider-coordinate escape hatch.
        """
        if not content_type:
            raise ValueError("multipart upload requires a content type")
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": self._full_key(key),
            "ContentType": content_type,
        }
        if metadata:
            params["Metadata"] = dict(metadata)
        if self._kms_key_id:
            params["ServerSideEncryption"] = "aws:kms"
            params["SSEKMSKeyId"] = self._kms_key_id
        response = self._client().create_multipart_upload(**params)
        upload_id = response.get("UploadId")
        if not isinstance(upload_id, str) or not upload_id:
            raise ObjectStoreError("S3 did not return a multipart upload id")
        return upload_id

    def presign_upload_part(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        *,
        expires_in: int,
    ) -> str:
        """Return a time-limited PUT URL for exactly one multipart part."""
        if not upload_id:
            raise ValueError("multipart upload id is required")
        if not 1 <= part_number <= 10_000:
            raise ValueError("multipart part_number must be in [1, 10000]")
        if not 1 <= expires_in <= 7 * 24 * 3600:
            raise ValueError("multipart URL expiry must be in [1, 604800]")
        return self._client().generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self._bucket,
                "Key": self._full_key(key),
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        parts: list[dict[str, Any]],
    ) -> ObjectMetadata:
        """Complete a multipart upload and return authoritative object metadata."""
        if not upload_id:
            raise ValueError("multipart upload id is required")
        if not parts:
            raise ValueError("multipart completion requires at least one part")
        self._client().complete_multipart_upload(
            Bucket=self._bucket,
            Key=self._full_key(key),
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )
        return self.stat(key)

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        """Abort an unfinished provider multipart upload idempotently."""
        if not upload_id:
            raise ValueError("multipart upload id is required")
        try:
            self._client().abort_multipart_upload(
                Bucket=self._bucket,
                Key=self._full_key(key),
                UploadId=upload_id,
            )
        except Exception as exc:  # noqa: BLE001 - inspect provider error code
            response = getattr(exc, "response", None) or {}
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            if str(error.get("Code", "")) == "NoSuchUpload":
                return
            raise

    def stat(self, key: str) -> ObjectMetadata:
        """Return authoritative size/type/ETag metadata for ``key``."""
        try:
            response = self._client().head_object(
                Bucket=self._bucket,
                Key=self._full_key(key),
            )
        except Exception as exc:  # noqa: BLE001 - normalise missing objects
            if self._is_not_found(exc):
                raise ObjectNotFoundError(key) from exc
            raise
        return ObjectMetadata(
            size_bytes=int(response["ContentLength"]),
            content_type=response.get("ContentType"),
            etag=response.get("ETag"),
        )

    def presigned_url(self, key: str, *, expires_in: int = 3600) -> str:
        """Return a time-limited HTTPS URL for ``key`` (S3-specific extra)."""
        return self._client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": self._full_key(key)},
            ExpiresIn=expires_in,
        )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"S3ObjectStore(bucket={self._bucket!r}, prefix={self._prefix!r})"
