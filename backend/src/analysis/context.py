"""Shared geometry context for all process analyzers.

Builds *once* per request and is reused by every ProcessAnalyzer. This replaces
the old pattern where every analyzer re-ran its own ray cast / normal / edge
analysis — which made /validate O(processes x faces) and produced duplicated,
inconsistent measurements.

Design contract:
    * Everything expensive lives here. Analyzers must not call mesh.ray.* again.
    * All fields are numpy arrays or plain Python objects so the context is
      pickle-friendly (needed for Celery when SAM-3D lands in Phase 3).
    * Failure to compute any single field degrades to a safe default
      (np.inf for thickness, empty arrays for topology) — a malformed mesh
      never breaks the analysis; it just produces higher-uncertainty issues.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import logging

import numpy as np
import trimesh
from scipy.spatial import KDTree

from src.analysis.models import FeatureSegment, GeometryInfo

logger = logging.getLogger("cadverify.context")


def _raycast_sample_threshold() -> int:
    """Face count above which sampling is used. Env var: RAYCAST_SAMPLE_THRESHOLD."""
    try:
        return max(1, int(os.getenv("RAYCAST_SAMPLE_THRESHOLD", "50000")))
    except Exception:
        return 50000


if TYPE_CHECKING:  # avoid circular import at runtime
    from src.analysis.features.base import Feature


@dataclass
class GeometryContext:
    """Precomputed, shared geometry state handed to every ProcessAnalyzer."""

    mesh: trimesh.Trimesh
    info: GeometryInfo

    # Scale
    bbox_diag: float
    scale_eps: float  # ray-cast offset; scale-aware to avoid sub-mm drift

    # Per-face arrays (length = N_faces)
    normals: np.ndarray              # (N, 3) float
    centroids: np.ndarray            # (N, 3) float
    face_areas: np.ndarray           # (N,)   float
    angles_from_up_deg: np.ndarray   # (N,)   float — angle between face normal and +Z
    wall_thickness: np.ndarray       # (N,)   float — inward ray cast, inf on failure

    # Per-edge arrays
    edge_lengths: np.ndarray         # (E,) float
    dihedral_angles_rad: np.ndarray  # (A,) float — from face_adjacency_angles
    face_adjacency: np.ndarray       # (A, 2) int  — from face_adjacency
    concave_mask: np.ndarray         # (A,) bool   — ~face_adjacency_convex

    # Topology
    bodies: list[trimesh.Trimesh]
    facet_groups: list[np.ndarray]   # from mesh.facets — coplanar face clusters

    # Feature / segmentation outputs (populated by downstream steps)
    features: list["Feature"] = field(default_factory=list)
    segments: list[FeatureSegment] = field(default_factory=list)

    # Room for extensions (symmetry axis, SAM-3D labels, ...)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ──────────────────────────────────────────────────────────
    # Builder
    # ──────────────────────────────────────────────────────────
    @classmethod
    def build(cls, mesh: trimesh.Trimesh, info: GeometryInfo) -> "GeometryContext":
        extents = mesh.extents
        if extents is None or len(mesh.faces) == 0:
            bbox_diag = 0.0
        else:
            bbox_diag = float(np.linalg.norm(np.asarray(extents, dtype=np.float64)))
        # Scale-aware epsilon clamped to handle sub-mm features (micro parts)
        # and multi-meter assemblies without drifting the ray-cast origin
        # either below numerical noise or past thin walls.
        scale_eps = max(1e-4, min(bbox_diag * 1e-4, 0.1))

        normals = np.asarray(mesh.face_normals, dtype=np.float64)
        centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
        face_areas = np.asarray(mesh.area_faces, dtype=np.float64)

        cos_z = np.clip(normals @ np.array([0.0, 0.0, 1.0]), -1.0, 1.0)
        angles_from_up_deg = np.degrees(np.arccos(cos_z))

        wall_thickness = _compute_wall_thickness(mesh, normals, centroids, scale_eps)

        edge_lengths = _safe_attr(mesh, "edges_unique_length", default=np.empty(0))
        adjacency = _safe_attr(mesh, "face_adjacency", default=np.empty((0, 2), dtype=int))
        dihedral = _safe_attr(mesh, "face_adjacency_angles", default=np.empty(0))
        try:
            convex = np.asarray(mesh.face_adjacency_convex, dtype=bool)
            concave_mask = ~convex
        except Exception:
            logger.warning(
                "face_adjacency_convex failed (n_adj=%d); defaulting to all-convex",
                len(dihedral),
                exc_info=True,
            )
            concave_mask = np.zeros(len(dihedral), dtype=bool)

        try:
            bodies = list(mesh.split(only_watertight=False))
        except Exception:
            logger.warning(
                "mesh.split failed (n_faces=%d); treating as single body",
                len(mesh.faces),
                exc_info=True,
            )
            bodies = [mesh]

        try:
            facet_groups = [np.asarray(f, dtype=int) for f in mesh.facets]
        except Exception:
            logger.warning(
                "mesh.facets extraction failed (n_faces=%d); no facet groups",
                len(mesh.faces),
                exc_info=True,
            )
            facet_groups = []

        return cls(
            mesh=mesh,
            info=info,
            bbox_diag=bbox_diag,
            scale_eps=scale_eps,
            normals=normals,
            centroids=centroids,
            face_areas=face_areas,
            angles_from_up_deg=angles_from_up_deg,
            wall_thickness=wall_thickness,
            edge_lengths=np.asarray(edge_lengths, dtype=np.float64),
            dihedral_angles_rad=np.asarray(dihedral, dtype=np.float64),
            face_adjacency=np.asarray(adjacency, dtype=np.int64),
            concave_mask=concave_mask,
            bodies=bodies,
            facet_groups=facet_groups,
        )


# ──────────────────────────────────────────────────────────────
# Vectorized wall-thickness ray cast
# ──────────────────────────────────────────────────────────────
def _compute_wall_thickness(
    mesh: trimesh.Trimesh,
    normals: np.ndarray,
    centroids: np.ndarray,
    eps: float,
) -> np.ndarray:
    """Measure per-face wall thickness via inward ray cast.

    For each face, fires one ray from slightly-inside the surface along -normal.
    The nearest valid hit (not the source face itself) is the wall thickness.
    Old code did this with a Python per-face loop; this version uses
    np.minimum.at to scatter-min distances back to their source rays, which is
    strictly vectorized and correctly handles the multi-hit case.

    Returns an array of length N_faces. Uncomputable faces get np.inf, which
    analyzers interpret as 'unknown' rather than 'thick'.
    """
    n = len(centroids)
    thickness = np.full(n, np.inf, dtype=np.float64)
    if n == 0:
        return thickness

    threshold = _raycast_sample_threshold()
    if n > threshold:
        return _compute_wall_thickness_sampled(mesh, normals, centroids, eps, n)

    origins = centroids - normals * eps  # start just inside the surface
    directions = -normals

    try:
        locs, idx_ray, idx_tri = mesh.ray.intersects_location(
            ray_origins=origins,
            ray_directions=directions,
            multiple_hits=True,
        )
    except Exception:
        logger.warning(
            "_compute_wall_thickness ray cast failed (n_faces=%d, eps=%.3g)",
            len(centroids),
            eps,
            exc_info=True,
        )
        return thickness

    if len(locs) == 0:
        return thickness

    # distance from each hit to its source ray origin
    dists = np.linalg.norm(locs - origins[idx_ray], axis=1)

    # Exclude self-hits: the source face usually reports itself.
    # Also exclude anything within 2*eps (numerical noise right at the origin).
    valid = (idx_tri != idx_ray) & (dists > 2.0 * eps)
    if not np.any(valid):
        return thickness

    np.minimum.at(thickness, idx_ray[valid], dists[valid])
    return thickness


def _compute_wall_thickness_sampled(
    mesh: trimesh.Trimesh,
    normals: np.ndarray,
    centroids: np.ndarray,
    eps: float,
    n: int,
) -> np.ndarray:
    """Sampled wall thickness: ray-cast ~5000 faces, propagate via KDTree."""
    thickness = np.full(n, np.inf, dtype=np.float64)
    stride = max(1, n // 5000)
    sample_idx = np.arange(0, n, stride)

    origins = centroids[sample_idx] - normals[sample_idx] * eps
    directions = -normals[sample_idx]

    try:
        locs, idx_ray, idx_tri = mesh.ray.intersects_location(
            ray_origins=origins,
            ray_directions=directions,
            multiple_hits=True,
        )
    except Exception:
        logger.warning(
            "_compute_wall_thickness_sampled ray cast failed (n_sampled=%d, eps=%.3g)",
            len(sample_idx), eps, exc_info=True,
        )
        return thickness

    if len(locs) == 0:
        return thickness

    # Compute distances and filter self-hits
    sampled_thickness = np.full(len(sample_idx), np.inf, dtype=np.float64)
    dists = np.linalg.norm(locs - origins[idx_ray], axis=1)
    # idx_tri refers to mesh face indices, not sample indices
    # idx_ray refers to sample ray indices (0..len(sample_idx)-1)
    valid = (idx_tri != sample_idx[idx_ray]) & (dists > 2.0 * eps)
    if np.any(valid):
        np.minimum.at(sampled_thickness, idx_ray[valid], dists[valid])

    # Assign sampled values
    thickness[sample_idx] = sampled_thickness

    # Propagate to unsampled faces via KDTree nearest-neighbor
    unsampled_mask = np.ones(n, dtype=bool)
    unsampled_mask[sample_idx] = False
    unsampled_idx = np.where(unsampled_mask)[0]

    if len(unsampled_idx) > 0 and np.any(np.isfinite(sampled_thickness)):
        finite_mask = np.isfinite(sampled_thickness)
        if np.any(finite_mask):
            finite_sample_idx = sample_idx[finite_mask]
            tree = KDTree(centroids[finite_sample_idx])
            _, nn_idx = tree.query(centroids[unsampled_idx], k=1)
            thickness[unsampled_idx] = thickness[finite_sample_idx[nn_idx]]

    logger.info(
        "Sampled wall thickness: %d/%d faces ray-cast, %d propagated via KDTree",
        len(sample_idx), n, len(unsampled_idx),
    )
    return thickness


def _safe_attr(obj: Any, name: str, default):
    try:
        return getattr(obj, name)
    except Exception:
        logger.warning("getattr %s failed", name, exc_info=True)
        return default
