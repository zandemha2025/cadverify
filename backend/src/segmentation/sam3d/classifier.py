"""Manufacturing feature classifier for mesh segments.

Stub implementation uses rule-based geometric heuristics (normal variance,
curvature, spatial extent).  Designed to be swapped for a trained MLP when
model weights are available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from src.segmentation.sam3d.types import SemanticLabel

if TYPE_CHECKING:
    import trimesh


def classify(
    mesh: "trimesh.Trimesh",
    face_indices: list[int],
) -> tuple[SemanticLabel, float]:
    """Classify a face-index set into a :class:`SemanticLabel`.

    Args:
        mesh: The full mesh.
        face_indices: Indices of the faces belonging to this segment.

    Returns:
        ``(label, confidence)`` where confidence is in ``[0, 1]``.
    """
    if not face_indices or len(mesh.faces) == 0:
        return SemanticLabel.UNKNOWN, 0.0

    normals = mesh.face_normals[face_indices]
    centroids = mesh.triangles_center[face_indices]
    areas = mesh.area_faces[face_indices]

    # ---- Geometric descriptors ----
    normal_var = float(np.var(normals, axis=0).sum())
    avg_normal = normals.mean(axis=0)
    avg_z = float(avg_normal[2])
    extent = np.ptp(centroids, axis=0)
    min_extent = float(np.min(extent))
    max_extent = float(np.max(extent))
    total_area = float(np.sum(areas))
    aspect_ratio = max_extent / max(min_extent, 1e-9)

    # ---- Rule-based classification ----

    # Flat, upward/downward-facing -> datum surface or gasket face
    if normal_var < 0.01:
        if abs(avg_z) > 0.9:
            # Perfectly flat horizontal surface
            if total_area > _median_face_area(mesh) * 10:
                return SemanticLabel.DATUM_SURFACE, 0.75
            return SemanticLabel.GASKET_FACE, 0.60
        # Flat vertical surface
        if aspect_ratio > 5.0:
            return SemanticLabel.STRUCTURAL_WEB, 0.55
        return SemanticLabel.FLANGE, 0.50

    # Cylindrical (moderate curvature, elongated)
    if 0.01 <= normal_var < 0.3:
        if aspect_ratio > 3.0 and min_extent < 5.0:
            return SemanticLabel.COOLING_CHANNEL, 0.55
        if min_extent < 3.0:
            return SemanticLabel.THREAD_REGION, 0.45
        return SemanticLabel.BEARING_SEAT, 0.50

    # Highly curved, compact -> holes / keyways
    if normal_var >= 0.3:
        if max_extent < 15.0 and min_extent < 8.0:
            if avg_z < -0.2:
                return SemanticLabel.MOUNTING_HOLE, 0.60
            if aspect_ratio > 2.0:
                return SemanticLabel.KEYWAY, 0.50
            return SemanticLabel.MOUNTING_HOLE, 0.55
        # Large highly-curved region
        if total_area > _median_face_area(mesh) * 20:
            return SemanticLabel.LIGHTENING_POCKET, 0.50
        return SemanticLabel.BEARING_SEAT, 0.45

    return SemanticLabel.UNKNOWN, 0.30


def _median_face_area(mesh: "trimesh.Trimesh") -> float:
    """Return the median face area, with a safe fallback."""
    if len(mesh.faces) == 0:
        return 1.0
    return float(np.median(mesh.area_faces))
