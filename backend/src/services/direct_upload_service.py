"""Secure org-scoped multipart uploads: batch ZIPs and single CAD parts.

The public API deals only in opaque ``direct_upload_id`` values. Bucket names,
provider upload IDs, and object keys are generated and retained server-side.
Every lifecycle read is scoped to the caller's active organization.

Two purposes uploaded by the browser:

* ``batch_zip``: a batch's ZIP, prepared into batch items on the worker.
* ``part``: one CAD file (STEP, IGES or STL; gzipped, or alone in a ZIP) of up
  to ``part_max_size_bytes()`` (2 GiB by default, on every plan), checked on the
  worker from the stored object (``src.services.stored_check_service``).

And one the worker fetches: ``link``, a part imported from a share link
(``src.services.link_import``). Its row reserves the organization's upload
admission (the part cap until the size is known) and is taken by its check
from the start; the bytes go straight to the worker's disk, so nothing is
stored under its key.

Transport: on S3 the browser PUTs each part to a presigned S3 URL. On the local
backend (development, staging; never a released process) it PUTs each part to
the API, which streams it to ``src.storage.local_multipart`` (``put_part``).
Either way an interrupted upload resumes: ``list_parts`` says which parts
arrived, and only the missing ones are sent again.
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
from typing import Any, Iterable, Protocol

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery, resolve_org
from src.config.public_urls import error_doc_url
from src.db.models import Batch, DirectUpload, Organization
from src.storage import (
    DirectUploadStoreConfigurationError,
    LocalMultipartStore,
    S3ObjectStore,
    get_direct_upload_store,
    get_local_direct_upload_store,
    selected_backend,
)

logger = logging.getLogger("cadverify.direct_upload_service")


class OwnedUpload(Protocol):
    """What the download and its ownership check read of a direct upload, as the
    worker's detached snapshot of a ``DirectUpload`` row carries it
    (``stored_check_tasks._snapshot``). Both functions take the row too."""

    @property
    def ulid(self) -> str: ...
    @property
    def org_id(self) -> str: ...
    @property
    def purpose(self) -> str: ...
    @property
    def filename(self) -> str: ...
    @property
    def object_key(self) -> str: ...
    @property
    def expected_size_bytes(self) -> int: ...
    @property
    def expected_checksum_sha256(self) -> str: ...


PURPOSE_BATCH_ZIP = "batch_zip"
PURPOSE_PART = "part"
# Not a multipart purpose: a link's row is made by POST /uploads/from-link only.
PURPOSE_LINK = "link"
ALLOWED_PURPOSES = frozenset({PURPOSE_BATCH_ZIP, PURPOSE_PART})
ALLOWED_BATCH_ZIP_CONTENT_TYPES = frozenset(
    {"application/zip", "application/x-zip-compressed"}
)
ALLOWED_BATCH_ZIP_EXTENSIONS = (".zip",)
# One CAD file, as is, gzipped, or as the one part in a ZIP.
PART_CAD_SUFFIXES = (".stl", ".step", ".stp", ".iges", ".igs")
PART_SUFFIXES = PART_CAD_SUFFIXES + tuple(f"{s}.gz" for s in PART_CAD_SUFFIXES) + (".zip",)
DEFAULT_PART_MAX_BYTES = 2 * 1024**3

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


def part_max_size_bytes() -> int:
    """The largest single CAD file any plan uploads (``DIRECT_UPLOAD_PART_MAX_BYTES``).

    Plan-independent, and the same number for the file as uploaded and, for a
    gzipped or zipped part, for the CAD file inside it. How large a file the
    worker can then check is a separate, memory-bound limit
    (``src.services.stored_check_service.processing_cap``).
    """
    return _env_int(
        "DIRECT_UPLOAD_PART_MAX_BYTES",
        DEFAULT_PART_MAX_BYTES,
        minimum=1024**2,
        maximum=5 * 1024**3,
    )


def max_size_bytes(purpose: str = PURPOSE_BATCH_ZIP) -> int:
    if purpose == PURPOSE_PART:
        return part_max_size_bytes()
    # Read through the batch service so tests/operator overrides share the exact
    # same authoritative cap as the proxied ZIP path.
    from src.services import batch_service

    return int(batch_service.BATCH_MAX_ZIP_BYTES)


def active_upload_count_limit(plan: str | None = None) -> int:
    """Maximum concurrently reserved direct uploads for one organization.

    A free (trial) account's organization gets ``DIRECT_UPLOAD_MAX_ACTIVE_PER_ORG_FREE``
    (2 by default); every other plan ``DIRECT_UPLOAD_MAX_ACTIVE_PER_ORG`` (4).
    """
    if plan == "trial":
        return _env_int("DIRECT_UPLOAD_MAX_ACTIVE_PER_ORG_FREE", 2, minimum=1, maximum=100)
    return _env_int(
        "DIRECT_UPLOAD_MAX_ACTIVE_PER_ORG",
        4,
        minimum=1,
        maximum=100,
    )


def active_upload_bytes_limit(plan: str | None = None) -> int:
    """Maximum declared bytes reserved by unclean uploads in one organization.

    Free (trial): ``DIRECT_UPLOAD_MAX_ACTIVE_BYTES_PER_ORG_FREE``, 4 GiB by
    default (two 2 GiB parts); every other plan 10 GiB.
    """
    if plan == "trial":
        return _env_int("DIRECT_UPLOAD_MAX_ACTIVE_BYTES_PER_ORG_FREE", 4 * 1024**3, minimum=1, maximum=1024**4)
    return _env_int(
        "DIRECT_UPLOAD_MAX_ACTIVE_BYTES_PER_ORG",
        10 * 1024**3,
        minimum=1,
        maximum=1024**4,
    )


def part_suffix(filename: str) -> str | None:
    """The accepted compound suffix of a part's name (``.step``, ``.stl.gz``, ``.zip``), else None."""
    lower = (filename or "").lower()
    for suffix in sorted(PART_SUFFIXES, key=len, reverse=True):
        if lower.endswith(suffix) and len(lower) > len(suffix):
            return suffix
    return None


def part_content_type(filename: str) -> str:
    """The content type a part is stored under, from its name (never the browser's guess)."""
    suffix = part_suffix(filename) or ""
    if suffix.endswith(".gz"):
        return "application/gzip"
    if suffix == ".zip":
        return "application/zip"
    return "application/octet-stream"


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


def _require_s3_store() -> S3ObjectStore | LocalMultipartStore:
    """Return the dedicated incoming-upload store, failing closed otherwise.

    The S3 namespace, or on the local backend outside production the local
    incoming directory (parts relayed through the API). The name predates the
    local store; tests patch it.
    """
    backend = selected_backend()
    if backend == "local":
        try:
            return get_local_direct_upload_store()
        except DirectUploadStoreConfigurationError as exc:
            raise _error(
                501,
                "DIRECT_UPLOAD_REQUIRES_S3",
                "Direct upload is unavailable because this server is not using S3 storage.",
            ) from exc
    if backend != "s3":
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


def capability(purpose: str = PURPOSE_BATCH_ZIP, *, plan: str | None = None) -> dict[str, Any]:
    if purpose not in ALLOWED_PURPOSES:
        raise _error(
            422,
            "DIRECT_UPLOAD_INVALID_PURPOSE",
            "purpose must be 'batch_zip' or 'part'.",
        )
    available = True
    unavailable_code: str | None = None
    transport: str | None = None
    try:
        transport = getattr(_require_s3_store(), "transport", "s3")
    except DirectUploadError as exc:
        available = False
        unavailable_code = exc.code
    part = purpose == PURPOSE_PART
    return {
        "purpose": purpose,
        "available": available,
        "direct_upload": available,
        "unavailable_code": unavailable_code,
        # "s3": PUT each part to its presigned URL. "relay": PUT it to the API path given.
        "transport": transport,
        "accepted_content_types": ["*"] if part else sorted(ALLOWED_BATCH_ZIP_CONTENT_TYPES),
        "accepted_extensions": list(PART_SUFFIXES if part else ALLOWED_BATCH_ZIP_EXTENSIONS),
        "max_size_bytes": max_size_bytes(purpose),
        "part_size_bytes": part_size_bytes(max_size_bytes(purpose)),
        "max_parts": S3_MAX_PARTS,
        "upload_expires_in_seconds": upload_ttl_seconds(),
        "part_url_expires_in_seconds": part_url_ttl_seconds(),
        "max_part_urls_per_response": MAX_PART_URLS_PER_RESPONSE,
        "idempotency_key_header": "Idempotency-Key",
        "idempotency_key_required": True,
        "checksum_algorithm": "sha256",
        "checksum_encoding": "hex",
        "checksum_required": True,
        "max_active_uploads_per_org": active_upload_count_limit(plan),
        "max_active_upload_bytes_per_org": active_upload_bytes_limit(plan),
        "resumable": True,
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
            "purpose must be 'batch_zip' or 'part'.",
        )
    part = purpose == PURPOSE_PART
    if (
        not filename
        or len(filename) > 255
        or filename in {".", ".."}
        or os.path.basename(filename) != filename
        or "\\" in filename
        or any(ord(char) < 32 for char in filename)
        or (part and part_suffix(filename) is None)
        or (not part and not filename.lower().endswith(ALLOWED_BATCH_ZIP_EXTENSIONS))
    ):
        raise _error(
            422,
            "DIRECT_UPLOAD_INVALID_FILENAME",
            (
                "part filename must be a basename ending in .step, .stp, .iges, .igs or .stl, "
                "optionally with .gz, or .zip."
                if part
                else "batch_zip filename must be a basename ending in .zip."
            ),
        )
    # A part's stored type comes from its name (part_content_type); the
    # browser's guess is only checked for sanity.
    if part:
        if not isinstance(content_type, str) or len(content_type) > 255 or any(ord(c) < 32 for c in content_type):
            raise _error(
                422,
                "DIRECT_UPLOAD_INVALID_CONTENT_TYPE",
                "content_type must be a media type string.",
            )
    elif content_type not in ALLOWED_BATCH_ZIP_CONTENT_TYPES:
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
    maximum = max_size_bytes(purpose)
    if size_bytes > maximum:
        raise _error(
            413,
            "DIRECT_UPLOAD_TOO_LARGE",
            (
                f"This file is {_gib(size_bytes)}; the largest single file ScaleCAD takes is {_gib(maximum)}."
                if part
                else f"size_bytes exceeds the maximum batch ZIP size of {maximum} bytes."
            ),
        )
    if not isinstance(checksum_sha256, str) or not _SHA256_HEX.fullmatch(
        checksum_sha256
    ):
        raise _error(
            422,
            "DIRECT_UPLOAD_INVALID_CHECKSUM",
            "checksum_sha256 must be the 64-character hexadecimal SHA-256 of the file."
            if part
            else "checksum_sha256 must be the 64-character hexadecimal SHA-256 of the ZIP.",
        )
    return checksum_sha256.lower()


def _gib(n: int) -> str:
    """'2 GB', '1.4 GB', '650 MB' (binary units, as the app states sizes)."""
    if n >= 1024**3:
        value = n / 1024**3
        return f"{value:.0f} GB" if value >= 10 or value == int(value) else f"{value:.1f} GB"
    return f"{max(1, round(n / 1024**2))} MB"


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


def _object_key(org_id: str, upload_ulid: str, purpose: str = PURPOSE_BATCH_ZIP, filename: str | None = None) -> str:
    if not _SAFE_SCOPE_COMPONENT.fullmatch(org_id):
        raise RuntimeError("invalid organization identifier for direct-upload storage")
    if not _SAFE_SCOPE_COMPONENT.fullmatch(upload_ulid):
        raise RuntimeError("invalid direct-upload identifier for object storage")
    if purpose == PURPOSE_LINK:
        # Reserved under the same layout; a fetched link's bytes are never stored here.
        return f"incoming/{org_id}/{upload_ulid}/link"
    if purpose == PURPOSE_PART:
        suffix = part_suffix(filename or "")
        if suffix is None:
            raise RuntimeError("invalid part filename for direct-upload storage")
        # The name the server chose, never the caller's: only the suffix carries over.
        return f"incoming/{org_id}/{upload_ulid}/part{suffix}"
    return f"incoming/{org_id}/{upload_ulid}/batch.zip"


def validate_owned_object_key(upload: DirectUpload | OwnedUpload) -> None:
    """Reject a corrupted/tampered row before any provider object is touched."""
    try:
        expected = _object_key(upload.org_id, upload.ulid, upload.purpose or PURPOSE_BATCH_ZIP, upload.filename)
    except RuntimeError:
        expected = None
    if upload.object_key != expected:
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
    if upload.purpose == PURPOSE_LINK:
        # A link's size and SHA-256 are known once fetched; until then its row
        # holds the admission reservation and a placeholder, not facts.
        fetched = upload.checksum_verified_at is not None
        return {
            "direct_upload_id": upload.ulid,
            "purpose": upload.purpose,
            "status": upload.status,
            "filename": upload.filename,
            "content_type": upload.content_type,
            "size_bytes": upload.actual_size_bytes if fetched else None,
            "actual_size_bytes": upload.actual_size_bytes,
            "checksum_algorithm": "sha256",
            "checksum_sha256": upload.expected_checksum_sha256 if fetched else None,
            "checksum_verified_at": _serialize_timestamp(upload.checksum_verified_at),
            "integrity_status": integrity_status,
            "expires_at": _serialize_timestamp(upload.expires_at),
            "completed_at": _serialize_timestamp(upload.completed_at),
            "can_abort": False,
            "error": (
                {"code": upload.error_code, "message": upload.error_message}
                if upload.error_code
                else None
            ),
        }
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


def relay_part_url(upload_ulid: str, part_number: int) -> str:
    """Where a browser PUTs one part on the local backend (through the API)."""
    return f"/api/v1/uploads/{upload_ulid}/parts/{part_number}"


async def _presign_parts(
    store: S3ObjectStore | LocalMultipartStore,
    upload: DirectUpload,
    part_numbers: list[int],
) -> tuple[list[dict[str, Any]], datetime]:
    now = _now()
    remaining = max(1, int((_utc(upload.expires_at) - now).total_seconds()))
    expires_in = min(part_url_ttl_seconds(), remaining)
    expires_at = now + timedelta(seconds=expires_in)

    if getattr(store, "transport", "s3") == "relay" or isinstance(store, LocalMultipartStore):
        # The relay path is authenticated and org-scoped like every other
        # upload call; it needs no signature and lives as long as the upload.
        parts = [{"part_number": n, "url": relay_part_url(upload.ulid, n)} for n in part_numbers]
        for part in parts:
            part["expires_at"] = _utc(upload.expires_at).isoformat()
        return parts, _utc(upload.expires_at)

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
    plan: str | None = None,
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
    count_limit = active_upload_count_limit(plan)
    bytes_limit = active_upload_bytes_limit(plan)
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
    plan: str | None = None,
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
    if purpose == PURPOSE_PART:
        content_type = part_content_type(filename)

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
        plan=plan,
    )

    upload_ulid = str(ULID())
    key = _object_key(org_id, upload_ulid, purpose, filename)
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
    if upload.purpose == PURPOSE_LINK:
        validate_owned_object_key(upload)
        return  # nothing was stored for a link
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


async def list_uploaded_parts(
    session: AsyncSession,
    *,
    user_id: int,
    upload_ulid: str,
) -> list[dict[str, Any]]:
    """The parts storage has received, so an interrupted upload sends only the rest."""
    upload = await _get_owned_upload(session, user_id, upload_ulid, for_update=False)
    if await _expire_if_needed(session, upload, actor_id=user_id):
        raise _error(410, "DIRECT_UPLOAD_EXPIRED", "Direct upload has expired.")
    if upload.status != "initiated":
        return []
    store = _require_s3_store()
    validate_owned_object_key(upload)
    try:
        parts = await asyncio.to_thread(store.list_parts, upload.object_key, upload.multipart_upload_id)
    except Exception as exc:
        raise _storage_error("list the parts of") from exc
    return [p for p in parts if 1 <= int(p["part_number"]) <= upload.part_count]


def expected_part_bytes(upload: DirectUpload, part_number: int) -> int:
    """Exact size of one part: the part size, or the remainder for the last part."""
    if part_number < upload.part_count:
        return int(upload.part_size_bytes)
    return int(upload.expected_size_bytes) - int(upload.part_size_bytes) * (upload.part_count - 1)


async def lock_part_for_relay(
    session: AsyncSession,
    *,
    user_id: int,
    upload_ulid: str,
    part_number: int,
) -> tuple[DirectUpload, LocalMultipartStore, int]:
    """Check a relayed part PUT before reading its body: owner, state, number and exact size.

    Returns the upload, the local store and the part's exact expected size.
    The row lock is released before the body is read (the caller commits), so
    parts upload in parallel.
    """
    store = _require_s3_store()
    if getattr(store, "transport", "s3") != "relay" or not isinstance(store, LocalMultipartStore):
        raise _error(
            409,
            "DIRECT_UPLOAD_RELAY_UNAVAILABLE",
            "Parts of this upload go straight to storage; PUT them to the part URLs given.",
        )
    upload = await _get_owned_upload(session, user_id, upload_ulid, for_update=True)
    if await _expire_if_needed(session, upload, actor_id=user_id):
        raise _error(410, "DIRECT_UPLOAD_EXPIRED", "Direct upload has expired.")
    if upload.status != "initiated":
        raise _error(
            409,
            "DIRECT_UPLOAD_INVALID_STATE",
            f"Parts cannot be uploaded while status is {upload.status}.",
        )
    if isinstance(part_number, bool) or not 1 <= int(part_number) <= upload.part_count:
        raise _error(
            422,
            "DIRECT_UPLOAD_PARTS_INVALID",
            f"part_number must be in [1, {upload.part_count}].",
        )
    validate_owned_object_key(upload)
    return upload, store, expected_part_bytes(upload, int(part_number))


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


def download_to_bounded_tempfile(upload: DirectUpload | OwnedUpload, progress=None) -> str:
    """Stream the incoming object into a bounded local tempfile, verifying it.

    Size and SHA-256 must match what was declared at initiation. The caller
    owns the returned path. Partial files and streams are always closed on
    failure; the object is never materialized in process memory.
    ``progress(bytes_read)`` is called every few MiB when given.
    """
    validate_owned_object_key(upload)
    purpose = upload.purpose or PURPOSE_BATCH_ZIP
    limit = max_size_bytes(purpose)
    if upload.expected_size_bytes > limit:
        raise DirectUploadPreparationValidationError(
            413,
            "DIRECT_UPLOAD_TOO_LARGE",
            "Direct-upload ZIP exceeds the configured batch size limit."
            if purpose == PURPOSE_BATCH_ZIP
            else "This file is over the largest single file ScaleCAD takes.",
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
    noun = "ZIP" if purpose == PURPOSE_BATCH_ZIP else "file"
    store = _require_s3_store()
    if purpose == PURPOSE_PART:
        fd, path = tempfile.mkstemp(prefix="cv_direct_part_", suffix=part_suffix(upload.filename) or ".bin")
    else:
        fd, path = tempfile.mkstemp(prefix="cv_direct_batch_", suffix=".zip")
    stream = None
    total = 0
    reported = 0
    digest = hashlib.sha256()
    try:
        stream = store.open(upload.object_key)
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if progress is not None and total - reported >= 8 * 1024 * 1024:
                    reported = total
                    progress(total)
                if total > upload.expected_size_bytes or total > limit:
                    raise DirectUploadPreparationValidationError(
                        422,
                        "DIRECT_UPLOAD_SIZE_MISMATCH",
                        f"Downloaded {noun} exceeded its completed direct-upload size.",
                    )
                digest.update(chunk)
                out.write(chunk)
        if total != upload.expected_size_bytes:
            raise DirectUploadPreparationValidationError(
                422,
                "DIRECT_UPLOAD_SIZE_MISMATCH",
                f"Downloaded {noun} size did not match the completed direct upload.",
            )
        actual_checksum = digest.hexdigest()
        if not hmac.compare_digest(
            actual_checksum,
            upload.expected_checksum_sha256,
        ):
            raise DirectUploadPreparationValidationError(
                422,
                "DIRECT_UPLOAD_CHECKSUM_MISMATCH",
                f"Downloaded {noun} did not match the SHA-256 declared at initiation.",
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


PART_CHECK_ABANDON_AFTER = timedelta(hours=24)


async def lock_completed_part_for_check(
    session: AsyncSession, *, user_id: int, upload_ulid: str
) -> DirectUpload:
    """Lock a completed part upload in the caller's org before a check is started on it."""
    upload = await _get_owned_upload(session, user_id, upload_ulid, for_update=True)
    if upload.purpose == PURPOSE_LINK:
        return upload  # taken by its own check when it was made; that check is answered
    if upload.purpose != PURPOSE_PART:
        raise _error(
            409,
            "DIRECT_UPLOAD_WRONG_PURPOSE",
            "This upload is a batch ZIP; start a batch or catalog run with it instead.",
        )
    if await _expire_if_needed(session, upload, actor_id=user_id):
        raise _error(410, "DIRECT_UPLOAD_EXPIRED", "Direct upload has expired.")
    return upload


def attach_to_check(upload: DirectUpload) -> None:
    """Mark a locked, completed part upload as taken by a check (same transaction as its job)."""
    if upload.status != "completed":
        raise _error(
            409,
            "DIRECT_UPLOAD_NOT_AVAILABLE",
            "This upload is not finished, or a check already took it.",
        )
    upload.status = "attached"
    upload.attached_at = _now()


async def finish_part_upload(
    session: AsyncSession,
    upload: DirectUpload,
    *,
    ok: bool,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """End a part upload after its check: the incoming object is deleted either way.

    A checked part's bytes live on as the organization's kept source
    (``source_artifact_service``); the incoming copy is transient. A failed
    delete leaves ``storage_cleaned_at`` empty for the sweep to retry.
    """
    now = _now()
    upload.status = "consumed" if ok else "failed"
    upload.terminal_at = now
    if ok:
        upload.consumed_at = now
        upload.error_code = None
        upload.error_message = None
    else:
        upload.error_code = error_code or "DIRECT_UPLOAD_CHECK_FAILED"
        upload.error_message = (error_message or "The check of this file didn't finish.")[:500]
    await session.commit()
    try:
        await delete_incoming_object(upload)
    except DirectUploadError:
        logger.warning("incoming part %s not deleted yet; the sweep retries", upload.ulid)
        return
    upload.storage_cleaned_at = _now()
    await session.commit()


LINK_PLACEHOLDER_SHA256 = "0" * 64


async def reserve_link_upload(
    session: AsyncSession,
    *,
    user_id: int,
    org_id: str,
    filename: str,
    request_fingerprint: str,
    idempotency_key: str | None,
    plan: str | None = None,
) -> tuple[DirectUpload, bool]:
    """The row a link import holds while the worker fetches and checks it.

    Admitted like a direct upload (the organization's count and bytes, under
    its row lock), reserving ``part_max_size_bytes()`` until the fetch knows the
    size. Taken by its check at once (``attached``). The caller adds the
    check's job and commits. Returns ``(upload, replayed)``: the same
    Idempotency-Key with the same link returns the upload already made.
    """
    if idempotency_key is not None:
        key_hash = _validate_idempotency_key(idempotency_key)
    else:
        key_hash = hashlib.sha256(f"link:{ULID()}".encode("ascii")).hexdigest()
    await _lock_org_upload_admission(session, org_id)
    existing = await _idempotent_upload(session, org_id=org_id, idempotency_key_hash=key_hash)
    if existing is not None:
        if existing.purpose != PURPOSE_LINK or not hmac.compare_digest(existing.request_fingerprint, request_fingerprint):
            raise _error(
                409,
                "DIRECT_UPLOAD_IDEMPOTENCY_CONFLICT",
                "Idempotency-Key was already used with different upload parameters.",
            )
        return existing, True
    reserved = part_max_size_bytes()
    await _enforce_upload_admission(session, org_id=org_id, requested_size_bytes=reserved, plan=plan)
    upload_ulid = str(ULID())
    now = _now()
    upload = DirectUpload(
        ulid=upload_ulid,
        org_id=org_id,
        user_id=user_id,
        idempotency_key_hash=key_hash,
        request_fingerprint=request_fingerprint,
        purpose=PURPOSE_LINK,
        status="attached",
        filename=filename,
        content_type="application/octet-stream",
        expected_size_bytes=reserved,
        expected_checksum_sha256=LINK_PLACEHOLDER_SHA256,
        part_size_bytes=DEFAULT_PART_SIZE_BYTES,
        part_count=1,
        object_key=_object_key(org_id, upload_ulid, PURPOSE_LINK),
        multipart_upload_id=PURPOSE_LINK,
        expires_at=now + timedelta(seconds=upload_ttl_seconds()),
        attached_at=now,
    )
    session.add(upload)
    await session.flush()
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=user_id,
        action="direct_upload.link_reserved",
        resource_type="direct_upload",
        resource_id=upload.ulid,
        detail={"purpose": PURPOSE_LINK, "reserved_bytes": reserved},
        org_id=org_id,
    )
    return upload, False


async def record_link_fetched(
    session: AsyncSession,
    upload: DirectUpload,
    *,
    size_bytes: int,
    sha256: str,
    filename: str,
) -> None:
    """A link's bytes arrived on the worker: its real size, SHA-256 and name.

    The admission reservation drops from the part cap to the real size.
    """
    now = _now()
    upload.filename = filename
    upload.content_type = part_content_type(filename)
    upload.expected_size_bytes = size_bytes
    upload.actual_size_bytes = size_bytes
    upload.expected_checksum_sha256 = sha256
    upload.checksum_verified_at = now
    upload.completed_at = now
    await session.commit()


async def delete_incoming_object(upload: DirectUpload) -> None:
    validate_owned_object_key(upload)
    if upload.purpose == PURPOSE_LINK:
        return  # a link's bytes went to the worker's disk, never to this store
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
                        # A part whose check never finished (its worker died):
                        # its object goes after PART_CHECK_ABANDON_AFTER.
                        and_(
                            DirectUpload.purpose.in_([PURPOSE_PART, PURPOSE_LINK]),
                            DirectUpload.status.in_(["attached", "preparing"]),
                            DirectUpload.attached_at <= now - PART_CHECK_ABANDON_AFTER,
                            DirectUpload.storage_cleaned_at.is_(None),
                        ),
                        and_(
                            DirectUpload.purpose.in_([PURPOSE_PART, PURPOSE_LINK]),
                            DirectUpload.status == "consumed",
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
        if upload.purpose in (PURPOSE_PART, PURPOSE_LINK) and prior_status in {"attached", "preparing"}:
            upload.status = "failed"
            upload.terminal_at = now
            upload.error_code = "DIRECT_UPLOAD_CHECK_ABANDONED"
            upload.error_message = "The check of this file never finished; upload it again to check it."
        elif prior_status == "consumed":
            pass
        elif prior_status in {"initiated", "completing", "completed"}:
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
    "PURPOSE_LINK",
    "PURPOSE_PART",
    "attach_to_check",
    "expected_part_bytes",
    "finish_part_upload",
    "list_uploaded_parts",
    "lock_completed_part_for_check",
    "lock_part_for_relay",
    "part_content_type",
    "part_max_size_bytes",
    "part_suffix",
    "relay_part_url",
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
    "record_link_fetched",
    "refresh_part_urls",
    "reserve_link_upload",
    "serialize",
    "sweep_expired_and_unclean_uploads",
    "validate_owned_object_key",
]
