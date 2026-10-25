"""Secure org-scoped S3 multipart uploads for large batch ZIP inputs.

The public API deals only in opaque ``direct_upload_id`` values. Bucket names,
provider upload IDs, and object keys are generated and retained server-side.
Every lifecycle read is scoped to the caller's active organization.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import re
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery, resolve_org
from src.config.public_urls import error_doc_url
from src.db.models import Batch, DirectUpload, Organization
from src.storage import (
    DirectUploadStoreConfigurationError,
    S3ObjectStore,
    get_direct_upload_store,
    selected_backend,
)

logger = logging.getLogger("cadverify.direct_upload_service")

PURPOSE_BATCH_ZIP = "batch_zip"
ALLOWED_PURPOSES = frozenset({PURPOSE_BATCH_ZIP})
ALLOWED_BATCH_ZIP_CONTENT_TYPES = frozenset(
    {"application/zip", "application/x-zip-compressed"}
)
ALLOWED_BATCH_ZIP_EXTENSIONS = (".zip",)

S3_MIN_PART_SIZE_BYTES = 5 * 1024**2
S3_MAX_PARTS = 10_000
DEFAULT_PART_SIZE_BYTES = 16 * 1024**2
DEFAULT_UPLOAD_TTL_SECONDS = 3600
DEFAULT_PART_URL_TTL_SECONDS = 900
MAX_PART_URLS_PER_RESPONSE = 1000

_SAFE_SCOPE_COMPONENT = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_ACTIVE_BEFORE_ATTACH = frozenset({"initiated", "completing", "completed"})
_ABORTABLE_STATUSES = frozenset({"initiated", "completed"})
_TERMINAL_STATUSES = frozenset({"consumed", "aborted", "expired", "failed"})


class DirectUploadError(Exception):
    """Stable user-facing direct-upload failure."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retry_after_seconds: int | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)

    @property
    def detail(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "doc_url": error_doc_url(self.code),
        }


class DirectUploadPreparationValidationError(DirectUploadError):
    """Deterministic input failure that an ARQ retry cannot repair."""


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    retry_after_seconds: int | None = None,
) -> DirectUploadError:
    return DirectUploadError(
        status_code,
        code,
        message,
        retry_after_seconds=retry_after_seconds,
    )


def _storage_error(action: str) -> DirectUploadError:
    return _error(
        503,
        "DIRECT_UPLOAD_STORAGE_ERROR",
        f"Object storage could not {action} the direct upload. Please retry.",
    )


def _persistence_error(action: str) -> DirectUploadError:
    return _error(
        503,
        "DIRECT_UPLOAD_PERSISTENCE_ERROR",
        f"The server could not durably {action} the direct upload. Please retry.",
    )


def _completion_recovery_error(upload_ulid: str) -> DirectUploadError:
    return _error(
        503,
        "DIRECT_UPLOAD_COMPLETION_RETRY",
        "S3 completion may have succeeded but is awaiting durable reconciliation. "
        f"Retry POST /api/v1/uploads/{upload_ulid}/complete with the same ETags "
        "or poll status; do not abort the upload.",
    )


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def upload_ttl_seconds() -> int:
    return _env_int(
        "DIRECT_UPLOAD_TTL_SECONDS",
        DEFAULT_UPLOAD_TTL_SECONDS,
        minimum=300,
        maximum=24 * 3600,
    )


def part_url_ttl_seconds() -> int:
    return min(
        upload_ttl_seconds(),
        _env_int(
            "DIRECT_UPLOAD_PART_URL_TTL_SECONDS",
            DEFAULT_PART_URL_TTL_SECONDS,
            minimum=60,
            maximum=3600,
        ),
    )


def max_size_bytes() -> int:
    # Read through the batch service so tests/operator overrides share the exact
    # same authoritative cap as the proxied ZIP path.
    from src.services import batch_service

    return int(batch_service.BATCH_MAX_ZIP_BYTES)


def active_upload_count_limit() -> int:
    """Maximum concurrently reserved direct uploads for one organization."""
    return _env_int(
        "DIRECT_UPLOAD_MAX_ACTIVE_PER_ORG",
        4,
        minimum=1,
        maximum=100,
    )


def active_upload_bytes_limit() -> int:
    """Maximum declared bytes reserved by unclean uploads in one organization."""
    return _env_int(
        "DIRECT_UPLOAD_MAX_ACTIVE_BYTES_PER_ORG",
        10 * 1024**3,
        minimum=1,
        maximum=1024**4,
    )


def part_size_bytes(expected_size_bytes: int) -> int:
    configured = _env_int(
        "DIRECT_UPLOAD_PART_SIZE_BYTES",
        DEFAULT_PART_SIZE_BYTES,
        minimum=S3_MIN_PART_SIZE_BYTES,
        maximum=5 * 1024**3,
    )
    # Initiation returns the complete slicing plan in one bounded response, so
    # keep the count within both S3's hard limit and our response limit even if
    # an operator configures the 5 MiB S3 minimum for a 5 GiB ZIP.
    effective_part_limit = min(S3_MAX_PARTS, MAX_PART_URLS_PER_RESPONSE)
    minimum_for_part_limit = math.ceil(expected_size_bytes / effective_part_limit)
    selected = max(configured, minimum_for_part_limit, S3_MIN_PART_SIZE_BYTES)
    # Stable MiB boundaries make client slicing deterministic.
    mib = 1024**2
    return math.ceil(selected / mib) * mib


def _require_s3_store() -> S3ObjectStore:
    """Return the dedicated incoming-upload store, failing closed otherwise."""
    if selected_backend() != "s3":
        raise _error(
            501,
            "DIRECT_UPLOAD_REQUIRES_S3",
            "Direct upload is unavailable because this server is not using S3 storage.",
        )
    try:
        store = get_direct_upload_store()
    except DirectUploadStoreConfigurationError as exc:
        raise _error(
            503,
            "DIRECT_UPLOAD_STORAGE_UNAVAILABLE",
            "Direct-upload object storage is not configured correctly.",
        ) from exc
    if not isinstance(store, S3ObjectStore):
        # Defense in depth against a factory/configuration regression.
        raise _error(
            501,
            "DIRECT_UPLOAD_REQUIRES_S3",
            "Direct upload is unavailable because this server is not using S3 storage.",
        )
    return store


def capability(purpose: str = PURPOSE_BATCH_ZIP) -> dict[str, Any]:
    if purpose not in ALLOWED_PURPOSES:
        raise _error(
            422,
            "DIRECT_UPLOAD_INVALID_PURPOSE",
            "purpose must be 'batch_zip'.",
        )
    available = True
    unavailable_code: str | None = None
    try:
        _require_s3_store()
    except DirectUploadError as exc:
        available = False
        unavailable_code = exc.code
    return {
        "purpose": purpose,
        "available": available,
        "direct_upload": available,
        "unavailable_code": unavailable_code,
        "accepted_content_types": sorted(ALLOWED_BATCH_ZIP_CONTENT_TYPES),
        "accepted_extensions": list(ALLOWED_BATCH_ZIP_EXTENSIONS),
        "max_size_bytes": max_size_bytes(),
        "part_size_bytes": part_size_bytes(max_size_bytes()),
        "max_parts": S3_MAX_PARTS,
        "upload_expires_in_seconds": upload_ttl_seconds(),
        "part_url_expires_in_seconds": part_url_ttl_seconds(),
        "max_part_urls_per_response": MAX_PART_URLS_PER_RESPONSE,
        "idempotency_key_header": "Idempotency-Key",
        "idempotency_key_required": True,
        "checksum_algorithm": "sha256",
        "checksum_encoding": "hex",
        "checksum_required": True,
        "max_active_uploads_per_org": active_upload_count_limit(),
        "max_active_upload_bytes_per_org": active_upload_bytes_limit(),
    }


def _validate_initiate(
    *,
    purpose: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    checksum_sha256: str | None = None,
) -> str:
    if purpose not in ALLOWED_PURPOSES:
        raise _error(
            422,
            "DIRECT_UPLOAD_INVALID_PURPOSE",
            "purpose must be 'batch_zip'.",
        )
    if (
        not filename
        or len(filename) > 255
        or filename in {".", ".."}
        or os.path.basename(filename) != filename
        or "\\" in filename
        or any(ord(char) < 32 for char in filename)
        or not filename.lower().endswith(ALLOWED_BATCH_ZIP_EXTENSIONS)
    ):
        raise _error(
            422,
            "DIRECT_UPLOAD_INVALID_FILENAME",
            "batch_zip filename must be a basename ending in .zip.",
        )
    if content_type not in ALLOWED_BATCH_ZIP_CONTENT_TYPES:
        raise _error(
            422,
            "DIRECT_UPLOAD_INVALID_CONTENT_TYPE",
            "batch_zip content_type must be an accepted ZIP media type.",
        )
    if isinstance(size_bytes, bool) or size_bytes <= 0:
        raise _error(
            422,
            "DIRECT_UPLOAD_INVALID_SIZE",
            "size_bytes must be greater than zero.",
        )
    maximum = max_size_bytes()
    if size_bytes > maximum:
        raise _error(
            413,
            "DIRECT_UPLOAD_TOO_LARGE",
            f"size_bytes exceeds the maximum batch ZIP size of {maximum} bytes.",
        )
    if not isinstance(checksum_sha256, str) or not _SHA256_HEX.fullmatch(
        checksum_sha256
    ):
        raise _error(
            422,
            "DIRECT_UPLOAD_INVALID_CHECKSUM",
            "checksum_sha256 must be the 64-character hexadecimal SHA-256 of the ZIP.",
        )
    return checksum_sha256.lower()


def _validate_idempotency_key(idempotency_key: str | None) -> str:
    if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(
        idempotency_key
    ):
        raise _error(
            422,
            "DIRECT_UPLOAD_IDEMPOTENCY_KEY_REQUIRED",
            "Idempotency-Key must be 16-128 URL-safe characters.",
        )
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


def _request_fingerprint(
    *,
    purpose: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    checksum_sha256: str,
) -> str:
    canonical = json.dumps(
        {
            "checksum_sha256": checksum_sha256,
            "content_type": content_type,
            "filename": filename,
            "purpose": purpose,
            "size_bytes": size_bytes,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _object_key(org_id: str, upload_ulid: str) -> str:
    if not _SAFE_SCOPE_COMPONENT.fullmatch(org_id):
        raise RuntimeError("invalid organization identifier for direct-upload storage")
    if not _SAFE_SCOPE_COMPONENT.fullmatch(upload_ulid):
        raise RuntimeError("invalid direct-upload identifier for object storage")
    return f"incoming/{org_id}/{upload_ulid}/batch.zip"


def validate_owned_object_key(upload: DirectUpload) -> None:
    """Reject a corrupted/tampered row before any provider object is touched."""
    if upload.object_key != _object_key(upload.org_id, upload.ulid):
        raise DirectUploadPreparationValidationError(
            409,
            "DIRECT_UPLOAD_OBJECT_KEY_INVALID",
            "Direct-upload storage ownership metadata is invalid.",
        )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(upload: DirectUpload, *, now: datetime | None = None) -> bool:
    return _utc(upload.expires_at) <= (now or _now())


def _serialize_timestamp(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None


def serialize(
    upload: DirectUpload, *, attached_batch_ulid: str | None = None
) -> dict[str, Any]:
    """Public lifecycle representation (provider coordinates intentionally absent)."""
    integrity_status = "pending"
    if upload.checksum_verified_at is not None:
        integrity_status = "verified"
    elif upload.error_code == "DIRECT_UPLOAD_CHECKSUM_MISMATCH":
        integrity_status = "failed"
    return {
        "direct_upload_id": upload.ulid,
        "purpose": upload.purpose,
        "status": upload.status,
        "filename": upload.filename,
        "content_type": upload.content_type,
        "size_bytes": upload.expected_size_bytes,
        "actual_size_bytes": upload.actual_size_bytes,
        "checksum_algorithm": "sha256",
        "checksum_sha256": upload.expected_checksum_sha256,
        "checksum_verified_at": _serialize_timestamp(upload.checksum_verified_at),
        "integrity_status": integrity_status,
        "part_size_bytes": upload.part_size_bytes,
        "part_count": upload.part_count,
        "expires_at": _serialize_timestamp(upload.expires_at),
        "completed_at": _serialize_timestamp(upload.completed_at),
        "batch_id": attached_batch_ulid,
        "batch_status_url": (
            f"/api/v1/batch/{attached_batch_ulid}"
            if attached_batch_ulid is not None
            else None
        ),
        "can_abort": upload.status in _ABORTABLE_STATUSES,
        "completion_recovery_required": upload.status == "completing",
        "error": (
            {"code": upload.error_code, "message": upload.error_message}
            if upload.error_code
            else None
        ),
    }


async def _presign_parts(
    store: S3ObjectStore,
    upload: DirectUpload,
    part_numbers: list[int],
) -> tuple[list[dict[str, Any]], datetime]:
    now = _now()
    remaining = max(1, int((_utc(upload.expires_at) - now).total_seconds()))
    expires_in = min(part_url_ttl_seconds(), remaining)
    expires_at = now + timedelta(seconds=expires_in)

    def _generate() -> list[dict[str, Any]]:
        return [
            {
                "part_number": number,
                "url": store.presign_upload_part(
                    upload.object_key,
                    upload.multipart_upload_id,
                    number,
                    expires_in=expires_in,
                ),
            }
            for number in part_numbers
        ]

    try:
        parts = await asyncio.to_thread(_generate)
    except Exception as exc:
        raise _storage_error("sign part URLs for") from exc
    for part in parts:
        part["expires_at"] = expires_at.isoformat()
    return parts, expires_at


async def _lock_org_upload_admission(
    session: AsyncSession,
    org_id: str,
) -> None:
    """Serialize idempotency and quota admission for one organization."""
    locked_org = (
        await session.execute(
            select(Organization.id)
            .where(Organization.id == org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if locked_org != org_id:
        raise _error(
            403,
            "DIRECT_UPLOAD_ORG_REQUIRED",
            "An active organization is required for direct upload.",
        )


async def _idempotent_upload(
    session: AsyncSession,
    *,
    org_id: str,
    idempotency_key_hash: str,
) -> DirectUpload | None:
    return (
        await session.execute(
            select(DirectUpload)
            .where(
                DirectUpload.org_id == org_id,
                DirectUpload.idempotency_key_hash == idempotency_key_hash,
            )
            .with_for_update()
        )
    ).scalars().first()


async def _enforce_upload_admission(
    session: AsyncSession,
    *,
    org_id: str,
    requested_size_bytes: int,
) -> None:
    """Reserve bounded count/bytes while the org row lock prevents races.

    Every row whose provider storage has not been durably acknowledged as
    cleaned reserves its declared size. This includes incomplete uploads,
    completed-but-unattached objects, active preparation, and terminal cleanup
    retries, preventing abort/failure churn from bypassing the quota.
    """
    result = await session.execute(
        select(
            func.count(DirectUpload.id),
            func.coalesce(func.sum(DirectUpload.expected_size_bytes), 0),
        ).where(
            DirectUpload.org_id == org_id,
            DirectUpload.storage_cleaned_at.is_(None),
        )
    )
    active_count, reserved_bytes = result.one()
    count_limit = active_upload_count_limit()
    bytes_limit = active_upload_bytes_limit()
    if int(active_count) >= count_limit:
        raise _error(
            429,
            "DIRECT_UPLOAD_ADMISSION_LIMIT",
            f"This organization already has {count_limit} active direct uploads; "
            "finish or abort one before starting another.",
            retry_after_seconds=60,
        )
    if int(reserved_bytes) + requested_size_bytes > bytes_limit:
        raise _error(
            429,
            "DIRECT_UPLOAD_ADMISSION_BYTES_LIMIT",
            f"This direct upload would exceed the organization's active-byte "
            f"limit of {bytes_limit}; finish or abort an existing upload first.",
            retry_after_seconds=60,
        )


async def initiate(
    session: AsyncSession,
    *,
    user_id: int,
    purpose: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    checksum_sha256: str | None,
    idempotency_key: str | None,
) -> tuple[DirectUpload, list[dict[str, Any]], bool, bool]:
    """Initiate provider multipart state and atomically persist ownership+audit."""
    normalized_checksum = _validate_initiate(
        purpose=purpose,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        checksum_sha256=checksum_sha256,
    )
    idempotency_key_hash = _validate_idempotency_key(idempotency_key)
    request_fingerprint = _request_fingerprint(
        purpose=purpose,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        checksum_sha256=normalized_checksum,
    )
    store = _require_s3_store()
    org_id = await resolve_org(session, user_id)
    if not org_id:
        raise _error(
            403,
            "DIRECT_UPLOAD_ORG_REQUIRED",
            "An active organization is required for direct upload.",
        )

    await _lock_org_upload_admission(session, org_id)
    existing = await _idempotent_upload(
        session,
        org_id=org_id,
        idempotency_key_hash=idempotency_key_hash,
    )
    if existing is not None:
        if not hmac.compare_digest(
            existing.request_fingerprint,
            request_fingerprint,
        ):
            raise _error(
                409,
                "DIRECT_UPLOAD_IDEMPOTENCY_CONFLICT",
                "Idempotency-Key was already used with different upload parameters.",
            )
        if existing.status in _ACTIVE_BEFORE_ATTACH and _is_expired(existing):
            await _expire_if_needed(session, existing, actor_id=user_id)
        replay_parts: list[dict[str, Any]] = []
        urls_complete = False
        if existing.status == "initiated":
            replay_parts, _ = await _presign_parts(
                store,
                existing,
                list(range(1, existing.part_count + 1)),
            )
            urls_complete = True
        from src.services.audit_service import emit_event

        await emit_event(
            session,
            actor_id=user_id,
            action="direct_upload.initiation_replayed",
            resource_type="direct_upload",
            resource_id=existing.ulid,
            detail={"status": existing.status},
            org_id=org_id,
        )
        await session.commit()
        return existing, replay_parts, urls_complete, True

    await _enforce_upload_admission(
        session,
        org_id=org_id,
        requested_size_bytes=size_bytes,
    )

    upload_ulid = str(ULID())
    key = _object_key(org_id, upload_ulid)
    selected_part_size = part_size_bytes(size_bytes)
    part_count = math.ceil(size_bytes / selected_part_size)
    expires_at = _now() + timedelta(seconds=upload_ttl_seconds())

    try:
        provider_upload_id = await asyncio.to_thread(
            store.create_multipart_upload,
            key,
            content_type=content_type,
            metadata={
                "cadverify-upload-id": upload_ulid,
                "purpose": purpose,
                "expected-size": str(size_bytes),
                "expected-sha256": normalized_checksum,
            },
        )
    except DirectUploadError:
        raise
    except Exception as exc:
        raise _storage_error("initiate") from exc

    upload = DirectUpload(
        ulid=upload_ulid,
        org_id=org_id,
        user_id=user_id,
        idempotency_key_hash=idempotency_key_hash,
        request_fingerprint=request_fingerprint,
        purpose=purpose,
        status="initiated",
        filename=filename,
        content_type=content_type,
        expected_size_bytes=size_bytes,
        expected_checksum_sha256=normalized_checksum,
        part_size_bytes=selected_part_size,
        part_count=part_count,
        object_key=key,
        multipart_upload_id=provider_upload_id,
        expires_at=expires_at,
    )
    # The browser client needs an exact complete slicing plan before it starts
    # PUTs. With the shared 5 GiB batch cap and 16 MiB default this is 320 URLs;
    # the S3 hard ceiling remains 10,000.
    initial_numbers = list(range(1, part_count + 1))
    try:
        part_urls, _ = await _presign_parts(store, upload, initial_numbers)
    except BaseException:
        try:
            await asyncio.to_thread(
                store.abort_multipart_upload,
                key,
                provider_upload_id,
            )
        except Exception:
            logger.exception("Could not abort multipart upload after signing failure")
        raise

    try:
        session.add(upload)
        await session.flush()
        from src.services.audit_service import emit_event

        await emit_event(
            session,
            actor_id=user_id,
            action="direct_upload.initiated",
            resource_type="direct_upload",
            resource_id=upload.ulid,
            detail={
                "purpose": purpose,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "part_count": part_count,
            },
            org_id=org_id,
        )
        await session.commit()
    except BaseException as exc:
        await session.rollback()
        try:
            await asyncio.to_thread(
                store.abort_multipart_upload,
                key,
                provider_upload_id,
            )
        except Exception:
            logger.exception("Could not abort multipart upload after DB rollback")
        if isinstance(exc, Exception):
            raise _persistence_error("record initiation for") from exc
        raise
    return upload, part_urls, True, False


def _owned_upload_stmt(user_id: int, upload_ulid: str):
    return select(DirectUpload).where(
        DirectUpload.ulid == upload_ulid,
        DirectUpload.org_id == caller_org_subquery(user_id),
    )


async def _get_owned_upload(
    session: AsyncSession,
    user_id: int,
    upload_ulid: str,
    *,
    for_update: bool = False,
) -> DirectUpload:
    if not _SAFE_SCOPE_COMPONENT.fullmatch(upload_ulid or ""):
        raise _error(404, "DIRECT_UPLOAD_NOT_FOUND", "Direct upload not found.")
    stmt = _owned_upload_stmt(user_id, upload_ulid)
    if for_update:
        stmt = stmt.with_for_update()
    upload = (await session.execute(stmt)).scalars().first()
    if upload is None:
        # 404 for both absence and cross-org access.
        raise _error(404, "DIRECT_UPLOAD_NOT_FOUND", "Direct upload not found.")
    return upload


async def _cleanup_provider_state(upload: DirectUpload) -> None:
    store = _require_s3_store()
    validate_owned_object_key(upload)
    if upload.status in {"initiated", "completing"}:
        await asyncio.to_thread(
            store.abort_multipart_upload,
            upload.object_key,
            upload.multipart_upload_id,
        )
        # A `completing` row may represent either an active multipart upload or
        # a completed object whose provider/DB response was lost. The adapter's
        # abort is idempotent for NoSuchUpload; deleting the exact owned key
        # covers the latter without accepting caller-supplied coordinates.
        if upload.status == "completing":
            await asyncio.to_thread(store.delete, upload.object_key)
    else:
        await asyncio.to_thread(store.delete, upload.object_key)


async def _expire_if_needed(
    session: AsyncSession,
    upload: DirectUpload,
    *,
    actor_id: int,
) -> bool:
    if upload.status not in _ACTIVE_BEFORE_ATTACH or not _is_expired(upload):
        return False
    try:
        await _cleanup_provider_state(upload)
    except Exception as exc:
        logger.exception("Failed to clean expired direct upload %s", upload.ulid)
        upload.error_code = "DIRECT_UPLOAD_EXPIRY_CLEANUP_PENDING"
        upload.error_message = "Expired upload cleanup will be retried automatically."
        from src.services.audit_service import emit_event

        await emit_event(
            session,
            actor_id=actor_id,
            action="direct_upload.cleanup_failed",
            resource_type="direct_upload",
            resource_id=upload.ulid,
            detail={"code": upload.error_code},
            org_id=upload.org_id,
        )
        await session.commit()
        raise _storage_error("clean up expired") from exc
    now = _now()
    upload.status = "expired"
    upload.storage_cleaned_at = now
    upload.terminal_at = now
    upload.error_code = "DIRECT_UPLOAD_EXPIRED"
    upload.error_message = "The direct upload expired before it was consumed."
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=actor_id,
        action="direct_upload.expired",
        resource_type="direct_upload",
        resource_id=upload.ulid,
        detail={"cleanup_error": False},
        org_id=upload.org_id,
    )
    await session.commit()
    return True


async def get_status(
    session: AsyncSession, *, user_id: int, upload_ulid: str
) -> DirectUpload:
    upload = await _get_owned_upload(
        session, user_id, upload_ulid, for_update=True
    )
    await _expire_if_needed(session, upload, actor_id=user_id)
    return upload


def _validate_part_numbers(upload: DirectUpload, numbers: Iterable[int]) -> list[int]:
    normalized = list(numbers)
    if not normalized:
        raise _error(
            422,
            "DIRECT_UPLOAD_PARTS_INVALID",
            "At least one part_number is required.",
        )
    if len(normalized) > MAX_PART_URLS_PER_RESPONSE:
        raise _error(
            422,
            "DIRECT_UPLOAD_TOO_MANY_PART_URLS",
            f"At most {MAX_PART_URLS_PER_RESPONSE} part URLs may be refreshed at once.",
        )
    if len(set(normalized)) != len(normalized) or any(
        not isinstance(number, int)
        or isinstance(number, bool)
        or number < 1
        or number > upload.part_count
        for number in normalized
    ):
        raise _error(
            422,
            "DIRECT_UPLOAD_PARTS_INVALID",
            f"part_numbers must be unique integers in [1, {upload.part_count}].",
        )
    return sorted(normalized)


async def refresh_part_urls(
    session: AsyncSession,
    *,
    user_id: int,
    upload_ulid: str,
    part_numbers: list[int],
) -> list[dict[str, Any]]:
    upload = await _get_owned_upload(
        session, user_id, upload_ulid, for_update=True
    )
    if await _expire_if_needed(session, upload, actor_id=user_id):
        raise _error(410, "DIRECT_UPLOAD_EXPIRED", "Direct upload has expired.")
    if upload.status != "initiated":
        raise _error(
            409,
            "DIRECT_UPLOAD_INVALID_STATE",
            f"Part URLs cannot be refreshed while status is {upload.status}.",
        )
    numbers = _validate_part_numbers(upload, part_numbers)
    store = _require_s3_store()
    urls, _ = await _presign_parts(store, upload, numbers)
    return urls


def _normalize_completed_parts(
    upload: DirectUpload, parts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    expected_numbers = set(range(1, upload.part_count + 1))
    seen: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for item in parts:
        number = item.get("part_number")
        etag = item.get("etag")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number in seen
            or number not in expected_numbers
            or not isinstance(etag, str)
            or not etag.strip()
            or len(etag) > 256
            or any(ord(char) < 32 for char in etag)
        ):
            raise _error(
                422,
                "DIRECT_UPLOAD_PARTS_INVALID",
                "Completion parts must contain each expected part_number once with a valid ETag.",
            )
        seen.add(number)
        normalized.append({"PartNumber": number, "ETag": etag.strip()})
    if seen != expected_numbers:
        raise _error(
            422,
            "DIRECT_UPLOAD_PARTS_INVALID",
            f"Completion requires exactly parts 1 through {upload.part_count}.",
        )
    return sorted(normalized, key=lambda item: item["PartNumber"])


async def complete(
    session: AsyncSession,
    *,
    user_id: int,
    upload_ulid: str,
    parts: list[dict[str, Any]],
) -> DirectUpload:
    upload = await _get_owned_upload(
        session, user_id, upload_ulid, for_update=True
    )
    if upload.status == "completed":
        return upload  # idempotent duplicate completion delivery
    if await _expire_if_needed(session, upload, actor_id=user_id):
        raise _error(410, "DIRECT_UPLOAD_EXPIRED", "Direct upload has expired.")
    if upload.status not in {"initiated", "completing"}:
        raise _error(
            409,
            "DIRECT_UPLOAD_INVALID_STATE",
            f"Direct upload cannot be completed while status is {upload.status}.",
        )
    normalized_parts = _normalize_completed_parts(upload, parts)
    store = _require_s3_store()
    validate_owned_object_key(upload)

    if upload.status == "initiated":
        # Persist provider intent before calling CompleteMultipartUpload. If the
        # provider succeeds but its response or our final DB/audit commit is
        # lost, `completing` is an explicit recoverable state whose retry HEADs
        # the exact server-owned key. We never leave a consumed multipart ID
        # ambiguously represented as an ordinary `initiated` upload.
        upload.status = "completing"
        upload.error_code = None
        upload.error_message = None
        from src.services.audit_service import emit_event

        try:
            await emit_event(
                session,
                actor_id=user_id,
                action="direct_upload.completion_started",
                resource_type="direct_upload",
                resource_id=upload.ulid,
                detail={"part_count": upload.part_count},
                org_id=upload.org_id,
            )
            await session.commit()
        except BaseException as exc:
            await session.rollback()
            # No provider mutation has happened yet, so rollback to `initiated`
            # remains safe if the intent/audit transaction itself cannot commit.
            if isinstance(exc, Exception):
                raise _persistence_error("record completion intent for") from exc
            raise

        # Hold a fresh row lock across the provider operation. This prevents an
        # abort racing completion while retaining the durable pre-call state if
        # the final transaction rolls back.
        upload = await _get_owned_upload(
            session, user_id, upload_ulid, for_update=True
        )
        if upload.status == "completed":
            return upload
        if upload.status != "completing":
            raise _error(
                409,
                "DIRECT_UPLOAD_INVALID_STATE",
                f"Direct upload cannot be completed while status is {upload.status}.",
            )

    try:
        metadata = await asyncio.to_thread(
            store.complete_multipart_upload,
            upload.object_key,
            upload.multipart_upload_id,
            normalized_parts,
        )
        reconciled_provider_completion = False
    except Exception:
        # CompleteMultipartUpload is not atomic with our database transaction.
        # A lost provider response (or a previous DB/audit failure) commonly
        # surfaces on retry as NoSuchUpload even though the exact owned object
        # now exists. Reconcile only through authoritative HEAD metadata on the
        # server-generated key; arbitrary caller coordinates are never involved.
        try:
            metadata = await asyncio.to_thread(store.stat, upload.object_key)
            reconciled_provider_completion = True
        except Exception as stat_exc:
            # The durable `completing` checkpoint is itself enough for retry;
            # persist an actionable status detail when the audit/DB is healthy.
            upload.error_code = "DIRECT_UPLOAD_COMPLETION_RETRY"
            upload.error_message = (
                "Object storage could not confirm completion; retry completion "
                "with the same part ETags."
            )
            from src.services.audit_service import emit_event

            try:
                await emit_event(
                    session,
                    actor_id=user_id,
                    action="direct_upload.completion_retry",
                    resource_type="direct_upload",
                    resource_id=upload.ulid,
                    detail={"code": upload.error_code},
                    org_id=upload.org_id,
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                logger.exception(
                    "Could not persist direct-upload completion retry detail for %s",
                    upload_ulid,
                )
            raise _completion_recovery_error(upload_ulid) from stat_exc

    size_matches = metadata.size_bytes == upload.expected_size_bytes
    type_matches = metadata.content_type == upload.content_type
    if not size_matches or not type_matches:
        now = _now()
        upload.status = "failed"
        upload.actual_size_bytes = metadata.size_bytes
        upload.object_etag = metadata.etag
        upload.terminal_at = now
        upload.storage_cleaned_at = None
        upload.error_code = "DIRECT_UPLOAD_OBJECT_MISMATCH"
        mismatch_message = (
            "Completed object metadata did not match the declared size and content type."
        )
        upload.error_message = mismatch_message
        from src.services.audit_service import emit_event

        try:
            await emit_event(
                session,
                actor_id=user_id,
                action="direct_upload.failed",
                resource_type="direct_upload",
                resource_id=upload.ulid,
                detail={
                    "code": upload.error_code,
                    "expected_size_bytes": upload.expected_size_bytes,
                    "actual_size_bytes": metadata.size_bytes,
                    "expected_content_type": upload.content_type,
                    "actual_content_type": metadata.content_type,
                    "reconciled_provider_completion": reconciled_provider_completion,
                },
                org_id=upload.org_id,
            )
            # Terminalize before deleting. If this transaction fails, the
            # provider object remains available for the `completing` retry to
            # HEAD and terminalize again; a consumed upload ID is never stranded.
            await session.commit()
        except BaseException as exc:
            await session.rollback()
            logger.exception(
                "Direct-upload mismatch DB/audit commit failed; provider object retained"
            )
            if isinstance(exc, Exception):
                raise _completion_recovery_error(upload_ulid) from exc
            raise

        try:
            await asyncio.to_thread(store.delete, upload.object_key)
            upload.storage_cleaned_at = _now()
            await emit_event(
                session,
                actor_id=user_id,
                action="direct_upload.cleaned",
                resource_type="direct_upload",
                resource_id=upload.ulid,
                detail={"prior_status": "failed", "status": "failed"},
                org_id=upload.org_id,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            # The durable failed row remains sweep-eligible and S3 delete is
            # idempotent if only the cleanup acknowledgement failed.
            logger.exception("Failed to clean mismatched direct upload %s", upload.ulid)
        raise _error(
            422,
            "DIRECT_UPLOAD_OBJECT_MISMATCH",
            mismatch_message,
        )

    now = _now()
    upload.status = "completed"
    upload.actual_size_bytes = metadata.size_bytes
    upload.object_etag = metadata.etag
    upload.completed_at = now
    upload.error_code = None
    upload.error_message = None
    from src.services.audit_service import emit_event

    try:
        await emit_event(
            session,
            actor_id=user_id,
            action="direct_upload.completed",
            resource_type="direct_upload",
            resource_id=upload.ulid,
            detail={
                "size_bytes": metadata.size_bytes,
                "part_count": upload.part_count,
                "reconciled_provider_completion": reconciled_provider_completion,
            },
            org_id=upload.org_id,
        )
        await session.commit()
    except BaseException as exc:
        await session.rollback()
        # Keep the provider object intact. The durable row may have rolled back
        # to the explicit `completing` checkpoint; a retry reconciles via stat()
        # even though the multipart upload ID has already been consumed by S3.
        logger.exception(
            "Direct-upload completion DB/audit commit failed; provider object retained for reconciliation"
        )
        if isinstance(exc, Exception):
            raise _completion_recovery_error(upload_ulid) from exc
        raise
    return upload


async def abort(
    session: AsyncSession, *, user_id: int, upload_ulid: str
) -> DirectUpload:
    upload = await _get_owned_upload(
        session, user_id, upload_ulid, for_update=True
    )
    if upload.status == "aborted":
        return upload
    if upload.status == "completing":
        # A lost CompleteMultipartUpload response is intentionally recoverable
        # through retry + HEAD reconciliation. Reject an eager client abort so
        # it cannot delete the only object capable of resolving that ambiguity.
        raise _error(
            409,
            "DIRECT_UPLOAD_COMPLETION_RECOVERY_REQUIRED",
            "Completion is being reconciled; retry completion or poll status instead of aborting.",
        )
    if upload.status not in _ABORTABLE_STATUSES:
        raise _error(
            409,
            "DIRECT_UPLOAD_INVALID_STATE",
            f"Direct upload cannot be aborted while status is {upload.status}.",
        )
    try:
        await _cleanup_provider_state(upload)
    except Exception as exc:
        raise _storage_error("abort") from exc
    now = _now()
    prior_status = upload.status
    upload.status = "aborted"
    upload.terminal_at = now
    upload.storage_cleaned_at = now
    upload.error_code = None
    upload.error_message = None
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=user_id,
        action="direct_upload.aborted",
        resource_type="direct_upload",
        resource_id=upload.ulid,
        detail={"prior_status": prior_status},
        org_id=upload.org_id,
    )
    await session.commit()
    return upload


async def lock_completed_for_batch(
    session: AsyncSession, *, user_id: int, upload_ulid: str
) -> DirectUpload:
    """Lock and validate a completed upload before creating its Batch row."""
    upload = await _get_owned_upload(
        session, user_id, upload_ulid, for_update=True
    )
    if await _expire_if_needed(session, upload, actor_id=user_id):
        raise _error(410, "DIRECT_UPLOAD_EXPIRED", "Direct upload has expired.")
    if upload.status != "completed" or upload.batch_id is not None:
        raise _error(
            409,
            "DIRECT_UPLOAD_NOT_AVAILABLE",
            "Direct upload is not completed or has already been attached to a batch.",
        )
    return upload


async def lock_for_batch_attachment(
    session: AsyncSession,
    *,
    user_id: int,
    upload_ulid: str,
) -> tuple[DirectUpload, Batch | None]:
    """Resolve a new attachment or recover the batch from an earlier POST.

    Ownership is intentionally organization-scoped, not creator-scoped: any
    analyst operating in the same active organization may finish or attach the
    organization's upload. The initial lookup uses ``caller_org_subquery``;
    another organization receives the same 404 as a missing ID.
    """
    upload = await _get_owned_upload(
        session, user_id, upload_ulid, for_update=True
    )
    if upload.status == "completed" and upload.batch_id is None:
        if await _expire_if_needed(session, upload, actor_id=user_id):
            raise _error(410, "DIRECT_UPLOAD_EXPIRED", "Direct upload has expired.")
        return upload, None

    recoverable_states = {
        "attached",
        "preparing",
        "prepared",
        "consumed",
        "failed",
    }
    if upload.batch_id is not None and upload.status in recoverable_states:
        batch = (
            await session.execute(
                select(Batch).where(
                    Batch.id == upload.batch_id,
                    Batch.org_id == upload.org_id,
                )
            )
        ).scalars().first()
        if batch is not None:
            return upload, batch
    raise _error(
        409,
        "DIRECT_UPLOAD_NOT_AVAILABLE",
        "Direct upload is not completed, or its prior batch is no longer recoverable.",
    )


async def attached_batch_ulid(
    session: AsyncSession, upload: DirectUpload
) -> str | None:
    if upload.batch_id is None:
        return None
    return (
        await session.execute(
            select(Batch.ulid).where(
                Batch.id == upload.batch_id,
                Batch.org_id == upload.org_id,
            )
        )
    ).scalar_one_or_none()


async def attach_to_batch(
    session: AsyncSession,
    *,
    upload: DirectUpload,
    batch: Batch,
    actor_id: int,
) -> None:
    """Attach a locked upload and its batch submission in one transaction."""
    if upload.status != "completed" or upload.batch_id is not None:
        raise _error(
            409,
            "DIRECT_UPLOAD_NOT_AVAILABLE",
            "Direct upload is not available for batch creation.",
        )
    if upload.org_id != batch.org_id:
        raise _error(
            404,
            "DIRECT_UPLOAD_NOT_FOUND",
            "Direct upload not found.",
        )
    now = _now()
    upload.status = "attached"
    upload.batch_id = batch.id
    upload.attached_at = now
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=actor_id,
        action="direct_upload.attached",
        resource_type="direct_upload",
        resource_id=upload.ulid,
        detail={"batch_id": batch.ulid, "purpose": upload.purpose},
        org_id=upload.org_id,
    )


async def mark_attachment_enqueue_failed(
    session: AsyncSession,
    *,
    upload: DirectUpload,
    batch: Batch,
    actor_id: int,
) -> None:
    """Terminalize a committed attachment whose preparation job was not queued."""
    from src.services import batch_service
    from src.services.audit_service import emit_event

    now = _now()
    batch_service.mark_batch_failed(batch, "direct_upload_enqueue_failed")
    upload.status = "failed"
    upload.terminal_at = now
    upload.error_code = "DIRECT_UPLOAD_PREPARATION_ENQUEUE_FAILED"
    upload.error_message = "The direct-upload preparation job could not be scheduled."
    await batch_service.mark_pending_items_terminal(session, batch.id, "skipped")
    await emit_event(
        session,
        actor_id=actor_id,
        action="direct_upload.failed",
        resource_type="direct_upload",
        resource_id=upload.ulid,
        detail={"code": upload.error_code, "batch_id": batch.ulid},
        org_id=upload.org_id,
    )


def download_to_bounded_tempfile(upload: DirectUpload) -> str:
    """Stream the incoming S3 ZIP into a bounded local tempfile.

    The caller owns the returned path. Partial files and streams are always
    closed on failure; the object is never materialized in process memory.
    """
    validate_owned_object_key(upload)
    if upload.expected_size_bytes > max_size_bytes():
        raise DirectUploadPreparationValidationError(
            413,
            "DIRECT_UPLOAD_TOO_LARGE",
            "Direct-upload ZIP exceeds the configured batch size limit.",
        )
    if not isinstance(upload.expected_checksum_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}",
        upload.expected_checksum_sha256,
    ):
        raise DirectUploadPreparationValidationError(
            409,
            "DIRECT_UPLOAD_CHECKSUM_METADATA_INVALID",
            "Direct-upload checksum ownership metadata is invalid.",
        )
    store = _require_s3_store()
    fd, path = tempfile.mkstemp(prefix="cv_direct_batch_", suffix=".zip")
    stream = None
    total = 0
    digest = hashlib.sha256()
    try:
        stream = store.open(upload.object_key)
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > upload.expected_size_bytes or total > max_size_bytes():
                    raise DirectUploadPreparationValidationError(
                        422,
                        "DIRECT_UPLOAD_SIZE_MISMATCH",
                        "Downloaded ZIP exceeded its completed direct-upload size.",
                    )
                digest.update(chunk)
                out.write(chunk)
        if total != upload.expected_size_bytes:
            raise DirectUploadPreparationValidationError(
                422,
                "DIRECT_UPLOAD_SIZE_MISMATCH",
                "Downloaded ZIP size did not match the completed direct upload.",
            )
        actual_checksum = digest.hexdigest()
        if not hmac.compare_digest(
            actual_checksum,
            upload.expected_checksum_sha256,
        ):
            raise DirectUploadPreparationValidationError(
                422,
                "DIRECT_UPLOAD_CHECKSUM_MISMATCH",
                "Downloaded ZIP did not match the SHA-256 declared at initiation.",
            )
        return path
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass


async def delete_incoming_object(upload: DirectUpload) -> None:
    validate_owned_object_key(upload)
    store = _require_s3_store()
    try:
        await asyncio.to_thread(store.delete, upload.object_key)
    except Exception as exc:
        raise _storage_error("delete") from exc


async def mark_storage_cleaned(
    session: AsyncSession, upload: DirectUpload, *, commit: bool = True
) -> None:
    """Durably acknowledge successful provider cleanup for cron reconciliation."""
    upload.storage_cleaned_at = _now()
    if commit:
        await session.commit()


async def sweep_expired_and_unclean_uploads(
    session: AsyncSession,
    *,
    limit: int = 100,
    now: datetime | None = None,
) -> int:
    """Clean expired unattached uploads and retry terminal blob cleanup.

    S3 incomplete-multipart lifecycle rules do not remove successfully completed
    but unattached objects. This database-driven sweep covers both forms and
    keeps rows with failed cleanup eligible for the next cron run.
    """
    from src.services import batch_service
    from src.services.audit_service import emit_event

    now = now or _now()
    candidate_ids = list(
        (
            await session.execute(
                select(DirectUpload.id)
                .outerjoin(Batch, Batch.id == DirectUpload.batch_id)
                .where(
                    or_(
                        and_(
                            DirectUpload.status.in_([
                                "initiated",
                                "completing",
                                "completed",
                            ]),
                            DirectUpload.batch_id.is_(None),
                            DirectUpload.expires_at <= now,
                        ),
                        and_(
                            DirectUpload.status.in_(["aborted", "expired", "failed"]),
                            DirectUpload.storage_cleaned_at.is_(None),
                        ),
                        and_(
                            DirectUpload.status.in_(["attached", "preparing", "prepared"]),
                            Batch.status.in_(["failed", "cancelled"]),
                            DirectUpload.storage_cleaned_at.is_(None),
                        ),
                    )
                )
                .order_by(DirectUpload.expires_at.asc(), DirectUpload.id.asc())
                .limit(max(1, min(limit, 1000)))
            )
        ).scalars().all()
    )

    cleaned = 0
    for upload_id in candidate_ids:
        upload = (
            await session.execute(
                select(DirectUpload)
                .where(DirectUpload.id == upload_id)
                .with_for_update(skip_locked=True)
            )
        ).scalars().first()
        if upload is None or upload.storage_cleaned_at is not None:
            await session.rollback()
            continue
        batch = None
        if upload.batch_id is not None:
            batch = (
                await session.execute(
                    select(Batch).where(
                        Batch.id == upload.batch_id,
                        Batch.org_id == upload.org_id,
                    )
                )
            ).scalars().first()

        try:
            await _cleanup_provider_state(upload)
            if batch is not None and batch.status in {"failed", "cancelled"}:
                await asyncio.to_thread(batch_service.cleanup_batch_files, batch.ulid)
        except Exception:
            upload.error_code = "DIRECT_UPLOAD_CLEANUP_PENDING"
            upload.error_message = "Storage cleanup will be retried automatically."
            await emit_event(
                session,
                actor_id=upload.user_id,
                action="direct_upload.cleanup_failed",
                resource_type="direct_upload",
                resource_id=upload.ulid,
                detail={"code": upload.error_code},
                org_id=upload.org_id,
            )
            await session.commit()
            logger.exception("Direct-upload cleanup sweep failed for %s", upload.ulid)
            continue

        prior_status = upload.status
        upload.storage_cleaned_at = now
        if prior_status in {"initiated", "completing", "completed"}:
            upload.status = "expired"
            upload.terminal_at = now
            upload.error_code = "DIRECT_UPLOAD_EXPIRED"
            upload.error_message = "The direct upload expired before it was consumed."
        elif prior_status in {"attached", "preparing", "prepared"}:
            upload.status = "aborted" if batch and batch.status == "cancelled" else "failed"
            upload.terminal_at = now
            upload.error_code = "DIRECT_UPLOAD_BATCH_TERMINAL"
            upload.error_message = (
                f"Attached batch became {batch.status}." if batch else "Attached batch was lost."
            )
        await emit_event(
            session,
            actor_id=upload.user_id,
            action="direct_upload.cleaned",
            resource_type="direct_upload",
            resource_id=upload.ulid,
            detail={"prior_status": prior_status, "status": upload.status},
            org_id=upload.org_id,
        )
        await session.commit()
        cleaned += 1
    return cleaned


def preparation_error(exc: BaseException) -> tuple[str, str, bool]:
    """Normalize a task exception to durable code/message/retryability."""
    if isinstance(exc, DirectUploadPreparationValidationError):
        return exc.code, exc.message, False
    if isinstance(exc, DirectUploadError):
        return exc.code, exc.message, exc.status_code >= 500
    # Bad ZIPs and the existing zip-bomb/item controls raise ValueError.
    if isinstance(exc, (ValueError, zipfile.BadZipFile)):
        return "DIRECT_UPLOAD_INVALID_ZIP", str(exc)[:500], False
    return (
        "DIRECT_UPLOAD_PREPARATION_FAILED",
        "The direct-upload ZIP could not be prepared.",
        True,
    )


__all__ = [
    "ALLOWED_BATCH_ZIP_CONTENT_TYPES",
    "DirectUploadError",
    "DirectUploadPreparationValidationError",
    "PURPOSE_BATCH_ZIP",
    "abort",
    "attach_to_batch",
    "attached_batch_ulid",
    "capability",
    "complete",
    "delete_incoming_object",
    "download_to_bounded_tempfile",
    "get_status",
    "initiate",
    "lock_completed_for_batch",
    "lock_for_batch_attachment",
    "mark_attachment_enqueue_failed",
    "mark_storage_cleaned",
    "preparation_error",
    "refresh_part_urls",
    "serialize",
    "sweep_expired_and_unclean_uploads",
    "validate_owned_object_key",
]
