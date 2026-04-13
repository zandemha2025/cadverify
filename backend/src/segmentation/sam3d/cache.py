"""Content-addressable cache for SAM-3D segmentation results.

Uses SHA-256 of mesh vertices + faces as the cache key.  Results are stored
as JSON files in a flat directory under ``cache_dir``.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import TYPE_CHECKING

import numpy as np

from src.segmentation.sam3d.types import SemanticLabel, SemanticSegment

if TYPE_CHECKING:
    import trimesh


def _mesh_hash(mesh: "trimesh.Trimesh") -> str:
    """Compute a deterministic SHA-256 hex digest for a mesh."""
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(mesh.vertices).tobytes())
    h.update(np.ascontiguousarray(mesh.faces).tobytes())
    return h.hexdigest()


def _cache_path(cache_dir: str, key: str) -> str:
    return os.path.join(cache_dir, f"{key}.json")


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _segment_to_dict(seg: SemanticSegment) -> dict:
    return {
        "label": seg.label.value,
        "face_indices": seg.face_indices,
        "centroid": list(seg.centroid),
        "confidence": seg.confidence,
        "view_agreement": seg.view_agreement,
        "metadata": seg.metadata,
    }


def _dict_to_segment(d: dict) -> SemanticSegment:
    return SemanticSegment(
        label=SemanticLabel(d["label"]),
        face_indices=d["face_indices"],
        centroid=tuple(d["centroid"]),
        confidence=d["confidence"],
        view_agreement=d["view_agreement"],
        metadata=d.get("metadata", {}),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get(
    mesh: "trimesh.Trimesh",
    cache_dir: str,
) -> list[SemanticSegment] | None:
    """Retrieve cached segments for *mesh*, or ``None`` on miss."""
    key = _mesh_hash(mesh)
    path = _cache_path(cache_dir, key)

    if not os.path.isfile(path):
        return None

    try:
        with open(path, "r") as f:
            data = json.load(f)
        return [_dict_to_segment(d) for d in data]
    except Exception:
        return None


def put(
    mesh: "trimesh.Trimesh",
    segments: list[SemanticSegment],
    cache_dir: str,
) -> None:
    """Store *segments* in the cache keyed by *mesh* content hash."""
    key = _mesh_hash(mesh)
    path = _cache_path(cache_dir, key)

    os.makedirs(cache_dir, exist_ok=True)

    data = [_segment_to_dict(s) for s in segments]
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception:
        # Cache write failures are non-fatal
        pass
