"""Cylinder / hole / boss detection.

Pipeline:
    1. Walk the face-adjacency graph keeping only edges whose dihedral angle
       is small (smoothly curved surface patches).
    2. Union-find the remaining edges → connected components of smoothly
       curved faces.
    3. For each component, fit an axis as the smallest singular vector of its
       face-normal matrix — for a true cylinder, all face normals lie in the
       plane perpendicular to the axis, so the axis is in the null space.
    4. Validate the fit via the mean |normal · axis| residual; reject components
       that aren't actually cylindrical.
    5. Classify the remaining cylinders as HOLE vs BOSS by testing whether the
       average face normal points toward the axis (interior surface → hole)
       or away from it (exterior surface → boss).

This is deterministic, fast (O(N)), and doesn't need ML. Threshold choices
are documented inline and regression-tested in tests/test_features.py.
"""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.features.base import Feature, FeatureKind


def detect_cylinders(
    mesh: trimesh.Trimesh,
    smooth_angle_deg: float = 25.0,
    min_face_count: int = 6,
    max_axis_residual: float = 0.25,
) -> list[Feature]:
    """Detect cylindrical features.

    Args:
        smooth_angle_deg: dihedral threshold for "smoothly connected"; a
            typical tessellated cylinder has 10–20° between adjacent faces.
        min_face_count: skip components smaller than this (noise).
        max_axis_residual: mean |n·axis| acceptable as "actually a cylinder".
            0 means perfect; 0.25 allows mild imperfection from tessellation.
    """
    features: list[Feature] = []
    if len(mesh.faces) == 0:
        return features

    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)

    try:
        adjacency = np.asarray(mesh.face_adjacency)
        angles = np.asarray(mesh.face_adjacency_angles)
    except Exception:
        return features

    if len(adjacency) == 0:
        return features

    smooth_mask = angles < np.radians(smooth_angle_deg)
    if not np.any(smooth_mask):
        return features

    components = _union_find_components(len(mesh.faces), adjacency[smooth_mask])

    try:
        face_areas = np.asarray(mesh.area_faces, dtype=np.float64)
    except Exception:
        face_areas = np.ones(len(mesh.faces), dtype=np.float64)

    for comp in components:
        if len(comp) < min_face_count:
            continue

        comp_arr = np.asarray(comp, dtype=np.int64)
        comp_normals = normals[comp_arr]
        comp_centroids = centroids[comp_arr]
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            normal_lengths = np.linalg.norm(comp_normals, axis=1)
        finite_faces = (
            np.isfinite(comp_normals).all(axis=1)
            & np.isfinite(comp_centroids).all(axis=1)
            & np.isfinite(normal_lengths)
            & (normal_lengths > 1e-9)
            & (normal_lengths < 10.0)
        )
        if int(finite_faces.sum()) < min_face_count:
            continue
        if not np.all(finite_faces):
            comp_arr = comp_arr[finite_faces]
            comp_normals = comp_normals[finite_faces]
            comp_centroids = comp_centroids[finite_faces]
            normal_lengths = normal_lengths[finite_faces]
        comp_normals = comp_normals / normal_lengths[:, None]

        # Axis = smallest-singular-vector direction of the normal matrix.
        try:
            _, sv, vh = np.linalg.svd(comp_normals, full_matrices=False)
        except np.linalg.LinAlgError:
            continue
        axis = vh[-1]
        axis_norm = np.linalg.norm(axis)
        if not np.isfinite(axis_norm) or axis_norm <= 1e-12:
            continue
        axis = axis / axis_norm

        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            residual = float(np.mean(np.abs(comp_normals @ axis)))
        if not np.isfinite(residual):
            continue
        if residual > max_axis_residual:
            continue

        mean = comp_centroids.mean(axis=0)
        if not np.isfinite(mean).all():
            continue
        rel = comp_centroids - mean

        # Remove the component along the axis; the remainder is the radial
        # distance from the axis for each face's centroid.
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            axial = rel @ axis
        if not np.isfinite(axial).all():
            continue
        radial = rel - np.outer(axial, axis)
        radii = np.linalg.norm(radial, axis=1)
        radius = float(radii.mean())
        if radius <= 0 or not np.isfinite(radius):
            continue

        # Depth is measured along the axis using *vertex* extents, not
        # triangle centroids. Centroids of tall skinny side-triangles sit at
        # h/3 and 2h/3, so their range underestimates the true height.
        try:
            face_verts = np.asarray(mesh.faces[comp_arr], dtype=np.int64)
            unique_v = np.unique(face_verts)
            comp_vertices = np.asarray(mesh.vertices)[unique_v]
            if not np.isfinite(comp_vertices).all():
                raise ValueError("non-finite component vertex")
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                v_axial = (comp_vertices - mean) @ axis
            if not np.isfinite(v_axial).all():
                raise ValueError("non-finite component axial extent")
            depth = float(v_axial.max() - v_axial.min())
        except Exception:
            depth = float(axial.max() - axial.min())
        if not np.isfinite(depth):
            continue

        # Hole vs boss: does the average face normal point toward the axis?
        # For a hole (interior surface), the outward normal faces inward
        # relative to the axis, so n · (−radial_unit) > 0  →  n · radial_unit < 0.
        radial_norm = np.linalg.norm(radial, axis=1, keepdims=True)
        radial_unit = np.divide(
            radial,
            radial_norm,
            out=np.zeros_like(radial),
            where=radial_norm > 1e-12,
        )
        dot = float(np.mean(np.sum(comp_normals * radial_unit, axis=1)))
        if not np.isfinite(dot):
            continue
        kind = FeatureKind.CYLINDER_HOLE if dot < 0 else FeatureKind.CYLINDER_BOSS

        area = float(face_areas[comp_arr].sum())
        if not np.isfinite(area):
            continue

        features.append(
            Feature(
                kind=kind,
                face_indices=[int(i) for i in comp_arr],
                centroid=tuple(float(v) for v in mean),
                axis=tuple(float(v) for v in axis),
                radius=radius,
                depth=depth,
                area=area,
                confidence=max(0.0, 1.0 - residual),
                metadata={
                    "axis_residual": residual,
                    "singular_values": sv.tolist(),
                    "normal_to_radial_dot": dot,
                },
            )
        )

    return features


def _union_find_components(
    n_faces: int,
    edges: np.ndarray,
) -> list[list[int]]:
    """Union-find → list of connected components (lists of face indices)."""
    parent = np.arange(n_faces, dtype=np.int64)

    def find(i: int) -> int:
        root = i
        while parent[root] != root:
            root = int(parent[root])
        # Path compression
        while parent[i] != root:
            next_i = int(parent[i])
            parent[i] = root
            i = next_i
        return root

    for a, b in edges:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb

    groups: dict[int, list[int]] = {}
    for i in range(n_faces):
        root = find(i)
        groups.setdefault(root, []).append(i)
    # Filter out singletons (faces with no smooth neighbor) — not cylinders.
    return [g for g in groups.values() if len(g) > 1]
