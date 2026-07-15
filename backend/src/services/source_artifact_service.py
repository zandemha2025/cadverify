"""Durable, organization-scoped source CAD artifacts.

Successful analyses and should-cost runs persist the exact uploaded bytes in the
configured object store.  The key is deterministic by organization, SHA-256,
and validated CAD suffix, so retries are idempotent and one tenant can never
address another tenant's source object.

The service deliberately exposes bytes, not provider URLs.  Callers therefore
cannot turn an ``s3://`` locator into a cross-tenant or long-lived public link.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path

from src.storage import ObjectNotFoundError, get_object_store


SOURCE_ARTIFACT_BLOB_DIR = os.getenv(
    "SOURCE_ARTIFACT_BLOB_DIR", "/data/blobs/source-artifacts"
)
_SAFE_ORG = re.compile(r"^[0-9A-Za-z_-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUFFIXES = frozenset({".stl", ".step", ".stp", ".iges", ".igs"})


def _store():
    return get_object_store(
        "source-artifacts",
        default_root=os.getenv("SOURCE_ARTIFACT_BLOB_DIR", SOURCE_ARTIFACT_BLOB_DIR),
    )


def normalize_suffix(filename_or_suffix: str) -> str:
    """Return a supported lowercase CAD suffix or raise ``ValueError``."""
    value = str(filename_or_suffix or "").strip().lower()
    suffix = value if value.startswith(".") and "/" not in value else Path(value).suffix
    if suffix not in _SUFFIXES:
        raise ValueError(f"unsupported source CAD suffix {suffix or '<missing>'!r}")
    return suffix


def artifact_key(org_id: str, mesh_hash: str, filename_or_suffix: str) -> str:
    """Build a traversal-safe object key for one exact source artifact."""
    org = str(org_id or "")
    digest = str(mesh_hash or "").lower()
    if not _SAFE_ORG.fullmatch(org):
        raise ValueError("invalid organization id for source artifact")
    if not _SHA256.fullmatch(digest):
        raise ValueError("source artifact hash must be a lowercase SHA-256 digest")
    suffix = normalize_suffix(filename_or_suffix)
    return f"{org}/{digest}/source{suffix}"


def costable_key(org_id: str, mesh_hash: str) -> str:
    """Object key for the canonical triangulated derivative used by costing."""
    # Reuse artifact_key's validation and then replace only the fixed basename.
    return artifact_key(org_id, mesh_hash, ".stl").replace("/source.stl", "/costable.stl")


async def save_source_artifact(
    org_id: str,
    mesh_hash: str,
    filename_or_suffix: str,
    data: bytes,
) -> str:
    """Persist exact source bytes idempotently and return the opaque store URL."""
    key = artifact_key(org_id, mesh_hash, filename_or_suffix)
    if hashlib.sha256(data).hexdigest() != str(mesh_hash).lower():
        raise ValueError("source artifact bytes do not match the declared SHA-256")
    store = _store()
    if not await asyncio.to_thread(store.exists, key):
        await asyncio.to_thread(
            store.put,
            key,
            data,
            content_type="application/octet-stream",
        )
    return store.url(key)


async def save_costable_mesh_artifact(
    org_id: str,
    mesh_hash: str,
    stl_bytes: bytes,
) -> str:
    """Persist the canonical STL derivative needed by the calibration engine."""
    if not isinstance(stl_bytes, (bytes, bytearray, memoryview)) or not stl_bytes:
        raise ValueError("costable mesh artifact must contain STL bytes")
    key = costable_key(org_id, mesh_hash)
    store = _store()
    if not await asyncio.to_thread(store.exists, key):
        await asyncio.to_thread(
            store.put,
            key,
            bytes(stl_bytes),
            content_type="model/stl",
        )
    return store.url(key)


async def costable_mesh_exists(org_id: str, mesh_hash: str) -> bool:
    return await asyncio.to_thread(_store().exists, costable_key(org_id, mesh_hash))


async def read_costable_mesh_artifact(org_id: str, mesh_hash: str) -> bytes:
    """Read a canonical STL derivative, falling back to an original STL only."""
    store = _store()
    key = costable_key(org_id, mesh_hash)
    if await asyncio.to_thread(store.exists, key):
        return await asyncio.to_thread(store.get, key)
    payload, suffix = await read_source_artifact(org_id, mesh_hash)
    if suffix != ".stl":
        raise ObjectNotFoundError(key)
    return payload


async def read_source_artifact(
    org_id: str,
    mesh_hash: str,
    filename_or_suffix: str | None = None,
) -> tuple[bytes, str]:
    """Read one tenant source and return ``(bytes, suffix)``.

    When the caller has only the evidence SHA, the object namespace is listed
    and exactly one deterministic source variant is selected.  Multiple suffix
    aliases with identical bytes are harmless; lexical order keeps the result
    reproducible.
    """
    org = str(org_id or "")
    digest = str(mesh_hash or "").lower()
    if not _SAFE_ORG.fullmatch(org):
        raise ValueError("invalid organization id for source artifact")
    if not _SHA256.fullmatch(digest):
        raise ValueError("source artifact hash must be a lowercase SHA-256 digest")
    store = _store()
    if filename_or_suffix is not None:
        key = artifact_key(org, digest, filename_or_suffix)
    else:
        prefix = f"{org}/{digest}/"
        keys = [
            item
            for item in await asyncio.to_thread(store.list_keys, prefix)
            if Path(item).suffix.lower() in _SUFFIXES
        ]
        if not keys:
            raise ObjectNotFoundError(prefix)
        key = sorted(keys)[0]
    return await asyncio.to_thread(store.get, key), Path(key).suffix.lower()
