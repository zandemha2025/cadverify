"""Pre-parse upload validation: magic bytes and triangle-count cap."""
from __future__ import annotations

import logging
import os

from fastapi import HTTPException

logger = logging.getLogger("cadverify.upload_validation")

_STEP_MAGIC: bytes = b"ISO-10303-21"


def _max_triangles() -> int:
    """Read MAX_TRIANGLES lazily so tests can override via monkeypatch."""
    try:
        n = int(os.getenv("MAX_TRIANGLES", "2000000"))
    except ValueError:
        n = 2_000_000
    return max(1, n)


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


def enforce_triangle_cap(mesh) -> None:
    """Reject meshes whose triangle count exceeds MAX_TRIANGLES."""
    face_count = len(mesh.faces)
    limit = _max_triangles()
    if face_count > limit:
        logger.info(
            "Rejected oversize mesh: %d faces exceeds cap %d", face_count, limit
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Mesh has {face_count:,} triangles, exceeds MAX_TRIANGLES limit "
                f"of {limit:,}. Reduce mesh resolution or contact support."
            ),
        )
