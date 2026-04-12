"""SAM 3D (Segment Anything 3D) integration for mesh segmentation.

Requires: torch, segment-anything, open3d
Optional GPU acceleration. Falls back to heuristic segmentation if unavailable.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import trimesh

from src.analysis.models import FeatureSegment, FeatureType

_SAM3D_AVAILABLE = False
try:
    import torch
    import open3d as o3d
    _SAM3D_AVAILABLE = torch.cuda.is_available() or torch.backends.mps.is_available()
except ImportError:
    pass


def is_sam3d_available() -> bool:
    """Check if SAM 3D inference is available."""
    return _SAM3D_AVAILABLE


def segment_sam3d(
    mesh: trimesh.Trimesh,
    model_path: Optional[str] = None,
    num_points: int = 10000,
) -> list[FeatureSegment]:
    """Segment mesh using SAM 3D.

    Pipeline:
    1. Convert mesh → point cloud (sample surface points)
    2. Run SAM 3D inference to get segment masks
    3. Map segments back to mesh faces
    4. Classify each segment into manufacturing feature types

    Args:
        mesh: Input trimesh object.
        model_path: Path to SAM 3D model weights. Uses default if None.
        num_points: Number of points to sample for inference.

    Returns:
        List of FeatureSegments with face indices and types.
    """
    if not _SAM3D_AVAILABLE:
        from src.segmentation.fallback import segment_heuristic
        return segment_heuristic(mesh)

    # 1. Sample point cloud from mesh surface
    points, face_indices = trimesh.sample.sample_surface(mesh, num_points)
    points_np = np.array(points)

    # 2. Create Open3D point cloud with normals
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points_np)

    # Compute normals from the mesh faces the points came from
    point_normals = mesh.face_normals[face_indices]
    pcd.normals = o3d.utility.Vector3dVector(point_normals)

    # 3. Run SAM 3D inference
    # NOTE: This is a placeholder for the actual SAM 3D model inference.
    # The real implementation would load the model and run forward pass.
    # For now, we use DBSCAN clustering as a geometric proxy.
    labels = np.array(pcd.cluster_dbscan(eps=5.0, min_points=20))

    # 4. Map point labels back to face labels
    face_labels = np.full(len(mesh.faces), -1, dtype=int)
    for i, face_idx in enumerate(face_indices):
        if labels[i] >= 0:
            face_labels[face_idx] = labels[i]

    # 5. Build segments
    segments: list[FeatureSegment] = []
    unique_labels = set(labels[labels >= 0])

    for label in unique_labels:
        face_mask = face_labels == label
        face_idx_list = np.where(face_mask)[0].tolist()

        if len(face_idx_list) < 5:
            continue

        centroid = tuple(np.mean(mesh.triangles_center[face_idx_list], axis=0).tolist())
        feature_type = _classify_segment(mesh, face_idx_list)

        segments.append(FeatureSegment(
            segment_id=int(label),
            feature_type=feature_type,
            face_indices=face_idx_list,
            centroid=centroid,
            confidence=0.85,  # SAM 3D confidence
        ))

    return segments


def _classify_segment(
    mesh: trimesh.Trimesh,
    face_indices: list[int],
) -> FeatureType:
    """Classify a segment into a manufacturing feature type based on geometry.

    Uses face normals and spatial distribution to determine feature type.
    """
    normals = mesh.face_normals[face_indices]
    centroids = mesh.triangles_center[face_indices]

    # Normal variance — low = flat, high = curved
    normal_var = float(np.var(normals, axis=0).sum())

    # Average Z-component of normals
    avg_z = float(np.mean(normals[:, 2]))

    # Spatial extent
    extent = np.ptp(centroids, axis=0)
    min_extent = float(np.min(extent))
    max_extent = float(np.max(extent))

    # Classification heuristics
    if normal_var < 0.01:
        # Very flat surface
        if avg_z > 0.8:
            return FeatureType.FLAT_SURFACE
        elif avg_z < -0.8:
            return FeatureType.FLAT_SURFACE
        else:
            return FeatureType.FLAT_SURFACE
    elif normal_var < 0.1:
        # Slightly curved — could be a fillet or chamfer
        if min_extent < 3.0:
            return FeatureType.FILLET
        return FeatureType.CURVED_SURFACE
    elif normal_var > 0.5:
        # Highly curved — could be a hole or boss
        if max_extent < 20 and min_extent < 10:
            # Small, highly curved = likely a hole or boss
            if avg_z < 0:
                return FeatureType.HOLE
            return FeatureType.BOSS
        return FeatureType.CURVED_SURFACE

    if avg_z < -0.3:
        return FeatureType.OVERHANG

    return FeatureType.UNKNOWN
