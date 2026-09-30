"""Cylinder / hole / boss detection.

Pipeline:
    1. Walk the face-adjacency graph keeping only edges whose dihedral angle
       is small (smoothly curved surface patches).
    2. Union-find the remaining edges → connected components of smoothly
       curved faces.
    3. For each component, fit an axis as the smallest singular vector of its
       face-normal matrix — for a true cylinder, all face normals lie in the
       plane perpendicular to the axis, so the axis is in the null space.
    4. Validate the axis and fit the vertices to a circular cross-section.
       Nonconstant-radius candidates remain CURVED without an invented radius;
       a validated circular taper retains rotational-surface evidence.
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
    """Detect cylinders and retain noncircular candidates as curved surfaces.

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

        # Planar-patch rejection: a FLAT face also has residual ~0 (any
        # in-plane axis is orthogonal to its one normal direction), which
        # would mint phantom max-confidence cylinders out of every flat side
        # of a box. Real cylinder-wall normals sweep an arc — they need TWO
        # meaningful singular directions; a plane has only one.
        if sv[0] <= 0 or (sv[1] / sv[0]) < 0.1:
            continue

        circle = fit_circular_section(comp_arr, mesh.faces, mesh.vertices, axis)
        if circle is None:
            continue
        mean, fitted_radius, radii, axial_vertices = circle
        radial_residual = float(np.sqrt(np.mean((radii - fitted_radius) ** 2)) / fitted_radius)
        # 2% permits coarse tessellation chords while rejecting oval bores and
        # material tapers. Axis alignment alone cannot establish a diameter.
        circular = radial_residual <= 0.02
        conical = False
        if not circular:
            slope, intercept = np.linalg.lstsq(
                np.column_stack((axial_vertices, np.ones_like(axial_vertices))),
                radii, rcond=None,
            )[0]
            predicted = slope * axial_vertices + intercept
            taper_residual = float(np.sqrt(np.mean((radii - predicted) ** 2)) / fitted_radius)
            conical = bool(taper_residual <= 0.02 and np.all(predicted > 0))
        depth = float(np.ptp(axial_vertices))
        rel = comp_centroids - mean
        radial = rel - np.outer(rel @ axis, axis)

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
        # A real cylinder wall's normals align strongly with the radial
        # direction (|dot| near 1). Near-zero alignment means this surface is
        # not a wall around the axis — skip rather than guess boss-vs-hole.
        if abs(dot) < 0.3:
            continue
        kind = (FeatureKind.CYLINDER_HOLE if dot < 0 else FeatureKind.CYLINDER_BOSS) if circular else FeatureKind.CURVED

        area = float(face_areas[comp_arr].sum())
        if not np.isfinite(area):
            continue

        features.append(
            Feature(
                kind=kind,
                face_indices=[int(i) for i in comp_arr],
                centroid=tuple(float(v) for v in mean),
                axis=tuple(float(v) for v in axis),
                radius=fitted_radius if circular else None,
                depth=depth,
                area=area,
                confidence=max(0.0, 1.0 - residual),
                metadata={
                    "axis_residual": residual,
                    "radial_residual": radial_residual,
                    "surface": "circular" if circular else "conical" if conical else "non_circular",
                    "interior": dot < 0,
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

def fit_circular_section(
    comp_faces: np.ndarray,
    faces: np.ndarray,
    vertices: np.ndarray,
    axis: np.ndarray,
) -> tuple[np.ndarray, float, np.ndarray, np.ndarray] | None:
    """Fit the existing Kasa circle model; return axis center, radius, radial
    distances and axial positions so callers can validate constant radius.
    """
    try:
        vert_idx = np.unique(faces[comp_faces])
        pts = vertices[vert_idx]
        if len(pts) < 4 or not np.isfinite(pts).all():
            return None

        p0 = pts.mean(axis=0)
        ref = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        e1 = ref - axis * np.dot(ref, axis)
        e1_norm = np.linalg.norm(e1)
        if e1_norm <= 1e-12:
            return None
        e1 = e1 / e1_norm
        e2 = np.cross(axis, e1)

        u = (pts - p0) @ e1
        v = (pts - p0) @ e2
        A = np.stack([2 * u, 2 * v, np.ones_like(u)], axis=1)
        b = u**2 + v**2
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        a_, b_, c_ = sol
        r_sq = c_ + a_**2 + b_**2
        if not np.isfinite(r_sq) or r_sq <= 0:
            return None
        radius = float(np.sqrt(r_sq))
        if not np.isfinite(radius) or radius <= 0:
            return None
        center = p0 + a_ * e1 + b_ * e2
        radii = np.hypot(u - a_, v - b_)
        axial = (pts - center) @ axis
        if not np.isfinite(radii).all() or not np.isfinite(axial).all():
            return None
        return center, radius, radii, axial
    except Exception:
        return None
