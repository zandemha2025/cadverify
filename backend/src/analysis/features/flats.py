"""Flat-surface detection via trimesh's coplanar face grouping.

trimesh.Trimesh.facets already groups adjacent coplanar faces. We just need
to filter tiny noise groups and wrap the result in Feature objects.
"""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.features.base import Feature, FeatureKind


def detect_flats(
    mesh: trimesh.Trimesh,
    min_face_count: int = 2,
    min_area_ratio: float = 1e-4,
) -> list[Feature]:
    """Return one Feature per coplanar face group.

    Args:
        mesh: input mesh.
        min_face_count: ignore facets with fewer triangles than this.
        min_area_ratio: ignore facets whose area is below this fraction of
            the total mesh surface area (filters numerical noise).
    """
    features: list[Feature] = []
    if len(mesh.faces) == 0:
        return features

    try:
        facets = list(mesh.facets)
        facet_areas = np.asarray(mesh.facets_area, dtype=np.float64)
    except Exception:
        return features

    if len(facets) == 0:
        return features

    total_area = float(mesh.area) if mesh.area > 0 else 1.0
    centroids_all = np.asarray(mesh.triangles_center)
    normals = np.asarray(mesh.face_normals)

    for i, face_indices in enumerate(facets):
        indices = np.asarray(face_indices, dtype=int)
        if len(indices) < min_face_count:
            continue
        area = float(facet_areas[i])
        if area / total_area < min_area_ratio:
            continue

        centroid = tuple(float(v) for v in centroids_all[indices].mean(axis=0))
        # Use the area-weighted average normal as the facet's axis.
        face_a = np.asarray(mesh.area_faces[indices], dtype=np.float64)
        weighted = (normals[indices] * face_a[:, None]).sum(axis=0)
        norm = np.linalg.norm(weighted)
        axis = tuple(float(v) for v in (weighted / norm)) if norm > 0 else None

        features.append(
            Feature(
                kind=FeatureKind.FLAT,
                face_indices=indices.tolist(),
                centroid=centroid,
                area=area,
                axis=axis,
                confidence=0.98,
                metadata={"area_ratio": area / total_area},
            )
        )

    return features
