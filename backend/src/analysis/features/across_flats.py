"""Across-flats measurement — REAL geometry, not a bounding box.

A hex fastener's *across-flats* (AF) is the flat-to-flat width of its head/nut and
the number a wrench and a catalog are keyed to. A bounding box cannot read it: an
axis-aligned bbox of a hex (or of a hex rotated in its own plane) over-reads, and
for the idealized AS1 nut the world bbox is 20×20 while the true oriented
cross-section is a 15×20 rectangle. So we measure it properly:

    1. Find the fastener AXIS (the bore / thread axis):
         * PRIMARY — reuse the existing cylinder detector's through-bore: the
           largest-area detected ``cylinder_hole`` axis. This is the real signal.
         * FALLBACK — the vertex principal axis whose PERPENDICULAR cross-section is
           most rotationally uniform (smallest across-corners / across-flats ratio).
           For a thin nut that is the thin (bore) axis; for an elongated bolt it is
           the shaft/length axis. No re-mesh — pure vertex algebra.
       The chosen signal is reported in ``axis_source`` so callers stay honest about
       which path produced the number.

    2. Project every vertex onto the plane perpendicular to the axis, take the 2D
       convex hull, and run rotating calipers:
         * across_flats  = the MINIMUM caliper width. By the rotating-calipers
           minimum-width theorem this width is always realized along a hull-edge
           normal, so we scan hull-edge normals. For a hexagon this IS the AF.
         * across_corners = the shape DIAMETER (maximum pairwise hull-vertex
           distance) = the maximum width over all orientations. For a hexagon this
           is the corner-to-corner distance.

    3. The AF/AC ratio is a HEX-CONFIRMATION signal: a regular hexagon has
       across_corners / across_flats = 2/√3 ≈ 1.1547. A value far from that means
       the cross-section is NOT a clean hexagon (a square/rectangle idealization,
       a round head, …) and callers must NOT claim "hex".

Validated: a synthetic AF=19 regular hexagon measures AF 19.000 / ratio 1.1547;
the real AS1 nut measures AF 15.0 / AC 25.0 / ratio 1.667 (a rectangle — honestly
not a hex).
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

# 2/sqrt(3): across-corners / across-flats of a regular hexagon.
HEX_AC_AF_RATIO = 2.0 / np.sqrt(3.0)


def _convex_hull_2d(points: np.ndarray) -> Optional[np.ndarray]:
    """Return the CCW hull vertices of a 2D point set, or None if degenerate."""
    if len(points) < 3:
        return None
    try:
        from scipy.spatial import ConvexHull

        hull = ConvexHull(points)
        return np.asarray(points[hull.vertices], dtype=np.float64)
    except Exception:
        return None


def _rotating_calipers(hull: np.ndarray) -> tuple[float, float]:
    """(min caliper width, diameter) of a convex polygon given its hull vertices.

    min width  -> across-flats  (scanned over hull-edge normals; the minimum-width
                  direction is provably an edge normal).
    diameter   -> across-corners (max pairwise distance between hull vertices).
    """
    n = len(hull)
    edges = np.roll(hull, -1, axis=0) - hull
    lengths = np.linalg.norm(edges, axis=1)
    min_width = np.inf
    for e, L in zip(edges, lengths):
        if L < 1e-9:
            continue
        d = e / L
        normal = np.array([-d[1], d[0]])
        proj = hull @ normal
        width = float(proj.max() - proj.min())
        if width < min_width:
            min_width = width
    # Diameter = max pairwise vertex distance (max width over all orientations).
    diffs = hull[:, None, :] - hull[None, :, :]
    diameter = float(np.sqrt((diffs ** 2).sum(axis=2)).max())
    if not np.isfinite(min_width):
        min_width = diameter
    return min_width, diameter


def _cross_section_ratio(vertices_centered: np.ndarray, axis: np.ndarray) -> float:
    """across-corners / across-flats of the cross-section perpendicular to `axis`.

    Used to score a candidate axis: the true bore axis of a nut/bolt yields the most
    rotationally-uniform (smallest-ratio) cross-section. Returns +inf if degenerate.
    """
    axis = axis / (np.linalg.norm(axis) + 1e-12)
    # Two orthonormal in-plane basis vectors.
    ref = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = ref - axis * (ref @ axis)
    e1 /= np.linalg.norm(e1) + 1e-12
    e2 = np.cross(axis, e1)
    pts = np.column_stack([vertices_centered @ e1, vertices_centered @ e2])
    hull = _convex_hull_2d(pts)
    if hull is None:
        return np.inf
    af, ac = _rotating_calipers(hull)
    if af <= 1e-9:
        return np.inf
    return ac / af


def _cylinder_consensus_axis(features) -> Optional[np.ndarray]:
    """The dominant axis of the detected cylindrical features (bore + coaxial bosses/
    chamfers), by an area-weighted orientation tensor. Reuses the existing cylinder
    detector's output. Robust to a few spuriously-fitted skew cylinders — the real
    fastener's many coaxial cylinders outvote them. Returns a unit axis or None."""
    if not features:
        return None
    tensor = np.zeros((3, 3), dtype=np.float64)
    weight = 0.0
    for f in features:
        kind = getattr(getattr(f, "kind", None), "value", None)
        axis = getattr(f, "axis", None)
        if kind not in ("cylinder_hole", "cylinder_boss") or axis is None:
            continue
        a = np.asarray(axis, dtype=np.float64)
        norm = np.linalg.norm(a)
        if not np.isfinite(norm) or norm <= 1e-9:
            continue
        a = a / norm
        w = float(getattr(f, "area", None) or 1.0)
        # Sign-independent (a and -a describe the same axis): outer product.
        tensor += w * np.outer(a, a)
        weight += w
    if weight <= 0:
        return None
    try:
        _, eigvecs = np.linalg.eigh(tensor)
    except np.linalg.LinAlgError:
        return None
    return eigvecs[:, -1]  # dominant orientation


def _principal_axes(vertices_centered: np.ndarray) -> list[np.ndarray]:
    """The 3 vertex principal (eigen) axes, as unit vectors."""
    if len(vertices_centered) < 4:
        return []
    cov = vertices_centered.T @ vertices_centered
    try:
        _, eigvecs = np.linalg.eigh(cov)
    except np.linalg.LinAlgError:
        return []
    return [eigvecs[:, i] for i in range(3)]


def measure_across_flats(mesh, features=None) -> Optional[dict[str, Any]]:
    """Measure a fastener's real across-flats from its mesh.

    Args:
        mesh: a trimesh with ``.vertices``.
        features: optional pre-computed feature list (reuse the existing detector's
            cylinders to pin the bore axis). If omitted, the principal-axis fallback
            is used.

    Returns a dict with:
        across_flats_mm    : minimum caliper width (the AF)
        across_corners_mm  : cross-section diameter (across-corners)
        ac_af_ratio        : across_corners / across_flats (~1.155 for a real hex)
        hex_consistent     : bool — ratio within a hex tolerance band
        axis               : the fastener axis used (unit 3-vector, as a list)
        axis_source        : "bore_cylinder" or "principal_axis"
    or None if the mesh is too degenerate to measure.
    """
    try:
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
    except Exception:
        return None
    if vertices.ndim != 2 or vertices.shape[0] < 4:
        return None
    finite = np.isfinite(vertices).all(axis=1)
    vertices = vertices[finite]
    if len(vertices) < 4:
        return None

    centered = vertices - vertices.mean(axis=0)

    # Candidate axes: the cylinder-feature consensus (the real bore signal) plus the
    # three vertex principal axes. We pick the candidate whose PERPENDICULAR cross-
    # section is the most rotationally uniform (smallest across-corners/across-flats),
    # which is the true bore/thread axis — and is self-correcting when a spuriously
    # fitted skew cylinder would otherwise mislead a naive "largest hole" pick.
    candidates: list[tuple[np.ndarray, str]] = []
    cyl_axis = _cylinder_consensus_axis(features)
    if cyl_axis is not None:
        candidates.append((cyl_axis, "bore_cylinder"))
    for pa in _principal_axes(centered):
        candidates.append((pa, "principal_axis"))
    if not candidates:
        return None

    axis, axis_source, best_ratio = None, None, np.inf
    for cand, source in candidates:
        cand = cand / (np.linalg.norm(cand) + 1e-12)
        ratio = _cross_section_ratio(centered, cand)
        # Prefer the bore-cylinder signal on a near-tie (it is the real feature).
        better = ratio < best_ratio - 1e-6
        if better:
            axis, axis_source, best_ratio = cand, source, ratio
    if axis is None:
        return None

    # If the winning axis coincides with the cylinder consensus, credit that signal.
    if cyl_axis is not None:
        cyl_unit = cyl_axis / (np.linalg.norm(cyl_axis) + 1e-12)
        if abs(float(axis @ cyl_unit)) > 0.98:
            axis_source = "bore_cylinder"

    axis = axis / (np.linalg.norm(axis) + 1e-12)
    ref = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = ref - axis * (ref @ axis)
    e1 /= np.linalg.norm(e1) + 1e-12
    e2 = np.cross(axis, e1)
    pts = np.column_stack([centered @ e1, centered @ e2])

    hull = _convex_hull_2d(pts)
    if hull is None:
        return None
    across_flats, across_corners = _rotating_calipers(hull)
    if across_flats <= 1e-6:
        return None
    ratio = across_corners / across_flats
    # A real hexagon: AC/AF = 1.1547. Allow a tolerance band for tessellation.
    hex_consistent = bool(1.10 <= ratio <= 1.22)

    return {
        "across_flats_mm": round(float(across_flats), 3),
        "across_corners_mm": round(float(across_corners), 3),
        "ac_af_ratio": round(float(ratio), 4),
        "hex_consistent": hex_consistent,
        "axis": [round(float(a), 4) for a in axis],
        "axis_source": axis_source,
    }
