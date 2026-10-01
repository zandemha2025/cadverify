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


def costable_key(org_id: str, mesh_hash: str, source_units: str = "mm") -> str:
    """Unit-specific mm geometry; legacy unqualified derivatives are not reused."""
    from src.costing.units import mesh_source_units

    mesh_source_units("source.stl", source_units)  # validate before forming a key
    # Reuse artifact_key's validation and then replace only the fixed basename.
    return artifact_key(org_id, mesh_hash, ".stl").replace(
        "/source.stl", f"/costable-v2-{source_units}.stl"
    )


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
    *, source_units: str = "mm",
) -> str:
    """Persist the canonical STL derivative needed by the calibration engine."""
    if not isinstance(stl_bytes, (bytes, bytearray, memoryview)) or not stl_bytes:
        raise ValueError("costable mesh artifact must contain STL bytes")
    key = costable_key(org_id, mesh_hash, source_units)
    store = _store()
    if not await asyncio.to_thread(store.exists, key):
        await asyncio.to_thread(
            store.put,
            key,
            bytes(stl_bytes),
            content_type="model/stl",
        )
    return store.url(key)


async def costable_mesh_exists(org_id: str, mesh_hash: str, *, source_units: str = "mm") -> bool:
    return await asyncio.to_thread(_store().exists, costable_key(org_id, mesh_hash, source_units))


async def read_costable_mesh_artifact(
    org_id: str, mesh_hash: str, *, source_units: str = "mm",
) -> bytes:
    """Return mm geometry for the requested interpretation of the exact source."""
    from src.costing.units import mesh_source_units, scale_mesh_to_mm

    payload, suffix = await read_source_artifact(org_id, mesh_hash)
    units = mesh_source_units(f"source{suffix}", source_units)
    store = _store()
    key = costable_key(org_id, mesh_hash, units)
    if await asyncio.to_thread(store.exists, key):
        return await asyncio.to_thread(store.get, key)
    # Reuse the bounded, cached parser. Old derivatives might have been written
    # under either unit interpretation; only the retained source can rebuild them.
    from src.api.routes import _parse_mesh_async

    mesh, _ = await _parse_mesh_async(payload, f"source{suffix}")
    mesh = scale_mesh_to_mm(mesh, units)
    stl = await asyncio.to_thread(mesh.export, file_type="stl")
    if not isinstance(stl, bytes):
        raise ValueError("CAD parser did not produce binary STL geometry")
    await save_costable_mesh_artifact(org_id, mesh_hash, stl, source_units=units)
    return stl


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
            if Path(item).stem == "source" and Path(item).suffix.lower() in _SUFFIXES
        ]
        if not keys:
            raise ObjectNotFoundError(prefix)
        key = sorted(keys)[0]
    return await asyncio.to_thread(store.get, key), Path(key).suffix.lower()
