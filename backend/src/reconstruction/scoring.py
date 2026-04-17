"""Mesh quality confidence scoring for reconstructed geometry.

Produces a 0-1 score based on five weighted geometric metrics.
Thresholds are configurable via environment variables.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np
import trimesh

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------

RECON_CONFIDENCE_HIGH: float = float(os.getenv("RECON_CONFIDENCE_HIGH", "0.7"))
RECON_CONFIDENCE_LOW: float = float(os.getenv("RECON_CONFIDENCE_LOW", "0.4"))


# ---------------------------------------------------------------------------
# Individual metric functions (internal)
# ---------------------------------------------------------------------------


def _watertight_score(mesh: trimesh.Trimesh) -> float:
    """1.0 if watertight, else 0.0."""
    return 1.0 if mesh.is_watertight else 0.0


def _degenerate_faces_score(mesh: trimesh.Trimesh) -> float:
    """Ratio of non-degenerate faces to total faces."""
    total = len(mesh.faces)
    if total == 0:
        return 0.0
    degen_count = int(np.sum(mesh.area_faces < 1e-10))
    return 1.0 - (degen_count / total)


def _self_intersection_score(mesh: trimesh.Trimesh) -> float:
    """Sample-based self-intersection estimate. 0.5 on failure."""
    try:
        if mesh.is_volume:
            return 1.0
        # Rough heuristic: ratio of broken faces from split bodies
        bodies = mesh.split(only_watertight=False)
        if len(bodies) <= 1:
            return 0.8
        intersect_ratio = (len(bodies) - 1) / max(len(bodies), 1)
        return 1.0 - min(1.0, intersect_ratio)
    except Exception:
        return 0.5


def _face_count_adequacy_score(mesh: trimesh.Trimesh) -> float:
    """Sigmoid-like score: 1.0 inside [5000, 200000], decreasing outside."""
    n = len(mesh.faces)
    low, high = 5000, 200_000
    if low <= n <= high:
        return 1.0
    if n < low:
        return max(0.0, n / low)
    # n > high
    return max(0.0, 1.0 - (n - high) / high)


def _surface_smoothness_score(mesh: trimesh.Trimesh) -> float:
    """Mean dot-product of adjacent face normals (higher = smoother)."""
    try:
        adj = mesh.face_adjacency
        if len(adj) == 0:
            return 0.5
        normals = mesh.face_normals
        n0 = normals[adj[:, 0]]
        n1 = normals[adj[:, 1]]
        dots = np.sum(n0 * n1, axis=1)
        # dots in [-1, 1]; map to [0, 1]
        mean_dot = float(np.mean(dots))
        return max(0.0, min(1.0, (mean_dot + 1.0) / 2.0))
    except Exception:
        return 0.5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_reconstruction_confidence(mesh: trimesh.Trimesh) -> float:
    """Compute a 0-1 confidence score for a reconstructed mesh.

    Five weighted metrics (from CONTEXT.md D-09):
        - Watertight:          0.30
        - Degenerate faces:    0.20
        - Self-intersections:  0.20
        - Face count adequacy: 0.15
        - Surface smoothness:  0.15

    Returns:
        Confidence score clamped to [0.0, 1.0], rounded to 3 decimal places.
    """
    if len(mesh.faces) == 0:
        return 0.0

    score = (
        0.30 * _watertight_score(mesh)
        + 0.20 * _degenerate_faces_score(mesh)
        + 0.20 * _self_intersection_score(mesh)
        + 0.15 * _face_count_adequacy_score(mesh)
        + 0.15 * _surface_smoothness_score(mesh)
    )
    return round(max(0.0, min(1.0, score)), 3)


def confidence_level(score: float) -> str:
    """Categorise a confidence score as high / medium / low."""
    if score >= RECON_CONFIDENCE_HIGH:
        return "high"
    if score >= RECON_CONFIDENCE_LOW:
        return "medium"
    return "low"


def confidence_message(level: str) -> Optional[str]:
    """Return a user-facing message for the given confidence level."""
    if level == "high":
        return None
    if level == "medium":
        return "Reconstruction quality is moderate; results may be less reliable."
    return (
        "Reconstruction quality is low; consider uploading additional "
        "images or a CAD file."
    )
