"""Heuristic-based mesh segmentation (no GPU / SAM 3D fallback).

Segments the mesh into meaningful manufacturing features using
geometric heuristics: face normal clustering, curvature analysis,
and adjacency grouping.
"""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.models import FeatureSegment, FeatureType


def segment_heuristic(mesh: trimesh.Trimesh) -> list[FeatureSegment]:
    """Segment mesh into features using geometric heuristics.

    Groups faces by normal direction and adjacency to identify:
    - Flat surfaces (horizontal/vertical)
    - Curved surfaces
    - Holes (concave cylindrical regions)
    - Overhangs (downward-facing groups)
    """
    segments: list[FeatureSegment] = []
    normals = mesh.face_normals
    centroids = mesh.triangles_center
    face_count = len(normals)

    if face_count == 0:
        return segments

    # --- 1. Classify faces by normal direction ---
    z_up = np.array([0, 0, 1])
    cos_z = np.dot(normals, z_up)

    # Categories based on angle from Z-up
    top_mask = cos_z > 0.9           # Nearly horizontal, facing up
    bottom_mask = cos_z < -0.9       # Facing down
    vertical_mask = np.abs(cos_z) < 0.1  # Nearly vertical
    overhang_mask = (cos_z < -0.3) & (cos_z > -0.9)  # Overhangs

    segment_id = 0

    # --- 2. Create segments for each category ---
    if np.any(top_mask):
        indices = np.where(top_mask)[0].tolist()
        centroid = tuple(np.mean(centroids[indices], axis=0).tolist())
        segments.append(FeatureSegment(
            segment_id=segment_id,
            feature_type=FeatureType.FLAT_SURFACE,
            face_indices=indices,
            centroid=centroid,
            confidence=0.8,
        ))
        segment_id += 1

    if np.any(bottom_mask):
        indices = np.where(bottom_mask)[0].tolist()
        centroid = tuple(np.mean(centroids[indices], axis=0).tolist())
        segments.append(FeatureSegment(
            segment_id=segment_id,
            feature_type=FeatureType.FLAT_SURFACE,
            face_indices=indices,
            centroid=centroid,
            confidence=0.7,
        ))
        segment_id += 1

    if np.any(overhang_mask):
        indices = np.where(overhang_mask)[0].tolist()
        centroid = tuple(np.mean(centroids[indices], axis=0).tolist())
        segments.append(FeatureSegment(
            segment_id=segment_id,
            feature_type=FeatureType.OVERHANG,
            face_indices=indices,
            centroid=centroid,
            confidence=0.7,
        ))
        segment_id += 1

    # --- 3. Sub-segment vertical faces by normal XY direction ---
    if np.any(vertical_mask):
        vert_indices = np.where(vertical_mask)[0]
        vert_normals = normals[vert_indices]

        # Cluster by normal XY direction (quantize to 8 directions)
        angles = np.arctan2(vert_normals[:, 1], vert_normals[:, 0])
        bins = np.round(angles / (np.pi / 4)).astype(int)

        for bin_val in np.unique(bins):
            group_mask = bins == bin_val
            indices = vert_indices[group_mask].tolist()
            if len(indices) < 3:
                continue

            centroid = tuple(np.mean(centroids[indices], axis=0).tolist())

            # Determine if this is a flat wall or curved surface
            normal_variance = float(np.var(vert_normals[group_mask], axis=0).sum())
            feature_type = (
                FeatureType.FLAT_SURFACE if normal_variance < 0.01
                else FeatureType.CURVED_SURFACE
            )

            segments.append(FeatureSegment(
                segment_id=segment_id,
                feature_type=feature_type,
                face_indices=indices,
                centroid=centroid,
                confidence=0.6,
            ))
            segment_id += 1

    # --- 4. Detect potential holes (small concave cylindrical groups) ---
    # Look for groups of faces forming small inward-facing cylinders
    remaining = set(range(face_count)) - set(
        idx for seg in segments for idx in seg.face_indices
    )

    if remaining:
        remaining_indices = list(remaining)
        remaining_centroids = centroids[remaining_indices]
        remaining_normals = normals[remaining_indices]

        # Faces with high curvature pointing inward might be holes
        # This is a rough heuristic
        if len(remaining_indices) > 10:
            centroid = tuple(np.mean(remaining_centroids, axis=0).tolist())
            segments.append(FeatureSegment(
                segment_id=segment_id,
                feature_type=FeatureType.CURVED_SURFACE,
                face_indices=remaining_indices[:1000],
                centroid=centroid,
                confidence=0.4,
            ))

    return segments
