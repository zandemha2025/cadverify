"""Pre-parse upload validation: magic bytes and triangle-count caps."""
from __future__ import annotations

import logging
import os
import struct

from fastapi import HTTPException

logger = logging.getLogger("cadverify.upload_validation")

_STEP_MAGIC: bytes = b"ISO-10303-21"
_BINARY_STL_HEADER_BYTES = 84
_BINARY_STL_TRIANGLE_BYTES = 50


def _positive_env_int(name: str, default: int) -> int:
    try:
        n = int(os.getenv(name, str(default)))
    except ValueError:
        n = default
    return max(1, n)


def _max_triangles() -> int:
    """Read MAX_TRIANGLES lazily so tests can override via monkeypatch."""
    return _positive_env_int("MAX_TRIANGLES", 2_000_000)


def demo_max_triangles() -> int:
    """Read DEMO_MAX_TRIANGLES lazily so tests can override via monkeypatch."""
    return _positive_env_int("DEMO_MAX_TRIANGLES", 500_000)


def binary_stl_triangle_count(data: bytes) -> int | None:
    """Return the declared triangle count for exact-length binary STL data.

    ASCII STL files can also be longer than 84 bytes, so only trust the binary
    count when the file length exactly matches the STL binary layout.
    """
    if len(data) < _BINARY_STL_HEADER_BYTES:
        return None
    (count,) = struct.unpack_from("<I", data, 80)
    expected_size = _BINARY_STL_HEADER_BYTES + count * _BINARY_STL_TRIANGLE_BYTES
    if expected_size == len(data):
        return count
    return None


def validate_magic(data: bytes, suffix: str) -> None:
    """Verify declared file type matches the leading bytes.

    Raises HTTPException(400) on mismatch. Detail strings are static —
    user content is never reflected back to the caller.
    """
    suffix = suffix.lower()
    if suffix in (".step", ".stp"):
        if len(data) < len(_STEP_MAGIC) or data[: len(_STEP_MAGIC)] != _STEP_MAGIC:
            logger.info("Rejected STEP upload: missing ISO-10303-21 magic")
            raise HTTPException(
                status_code=400,
                detail=(
                    "File does not appear to be a valid STEP file "
                    "(missing ISO-10303-21 header)."
                ),
            )
        return
    if suffix == ".stl":
        # Binary STL minimum: 80-byte header + 4-byte uint triangle count.
        if len(data) < 84:
            logger.info("Rejected STL upload: too short for a valid STL")
            raise HTTPException(
                status_code=400,
                detail=(
                    "File is too small to be a valid STL "
                    "(minimum 84 bytes for header + triangle count)."
                ),
            )
        # ASCII STL check: header starts with 'solid' (case-insensitive).
        # Either way length check above is sufficient; no further action needed.
        return
    # Other suffixes are rejected earlier in routes.py; no-op here.
    return


def enforce_stl_triangle_count_cap(
    data: bytes,
    *,
    limit: int | None = None,
    limit_name: str = "MAX_TRIANGLES",
    status_code: int = 400,
    subject: str = "Mesh",
) -> None:
    """Reject exact-length binary STL files whose declared count exceeds a cap."""
    triangle_count = binary_stl_triangle_count(data)
    if triangle_count is None:
        return
    cap = _max_triangles() if limit is None else max(1, limit)
    if triangle_count > cap:
        logger.info(
            "Rejected oversize STL: %d declared faces exceeds cap %d",
            triangle_count,
            cap,
        )
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"{subject} has {triangle_count:,} triangles, exceeds "
                f"{limit_name} limit of {cap:,}. Reduce mesh resolution "
                "and try again."
            ),
        )


def enforce_triangle_cap(
    mesh,
    *,
    limit: int | None = None,
    limit_name: str = "MAX_TRIANGLES",
    status_code: int = 400,
    subject: str = "Mesh",
) -> None:
    """Reject meshes whose triangle count exceeds the configured cap."""
    face_count = len(mesh.faces)
    cap = _max_triangles() if limit is None else max(1, limit)
    if face_count > cap:
        logger.info(
            "Rejected oversize mesh: %d faces exceeds cap %d", face_count, cap
        )
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"{subject} has {face_count:,} triangles, exceeds "
                f"{limit_name} limit of {cap:,}. Reduce mesh resolution "
                "and try again."
            ),
        )
