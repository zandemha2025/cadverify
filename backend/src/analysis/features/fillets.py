"""Fillet detection: smooth rounded strips bridging two larger surfaces.

A fillet, tessellated, is a *run* of narrow, individually-elongated facets
whose dihedral steps are each small (a smooth roll rather than a sharp
break) and whose steps accumulate to a substantial total turn, bounded at
both ends by a larger surface that is NOT itself a narrow sliver.
Structurally this is a path in the facet-adjacency graph (see
``facet_graph.py``): walk edges whose dihedral angle is small-but-nonzero
between facet-groups that are themselves narrow slivers, and the run should
look like a 1-D strip — two endpoints, everything else degree-2 — not a
closed loop (that is a bare cylindrical wall, already handled by
``detect_cylinders``) and not a branching patch (ambiguous; skip rather
than guess).

One important, non-obvious wrinkle discovered while building the fixtures
for this detector: a real, *tangent* (G1-continuous) fillet meets its
flanking flat faces at a SMALL dihedral angle at the tessellation
resolution typically used for CAD exports — not a large, easily
distinguished break. A first draft of this detector used "large boundary
angle" to decide where the strip ends, and that pulled the huge flanking
flat faces straight into the "fillet" component (their tangent-point edge
to the first strip segment is often even smaller than the strip's own
interior steps). The fix: only facet-groups that are THEMSELVES narrow
slivers (high individual in-plane aspect ratio) are eligible to be strip
nodes at all; the flanking faces (low individual aspect — they're squarish,
not sliver-shaped) are structurally excluded from the graph before the walk
even starts, regardless of the angle at the tangent seam.

Deliberately conservative gates, in the order applied:
    1. Only individually-narrow facet-groups (own aspect ratio above a
       threshold) are eligible strip nodes at all.
    2. Component size >= 3 eligible facet-groups.
    3. Topology: exactly two degree-1 nodes (path endpoints), everything
       else degree-2, nothing degree>2 (no branch/blob). A closed loop
       (every node degree-2, no endpoints) is explicitly rejected — this is
       the guard against mislabeling a full cylindrical wall as a fillet.
    4. Curvature direction (convex vs concave) is uniform along the path —
       a real single-radius fillet doesn't flip sign.
    5. Total accumulated turn across the path lands in a plausible fillet
       range (default 45-135deg).
    6. Both path endpoints border a group outside the strip that is NOT
       itself an eligible sliver and is at least as large by area (the two
       flanking surfaces a fillet blends between).
    7. The strip, measured along its fitted axis, is thin relative to its
       axial length (aspect ratio) — not a blobby patch.

Radius/axis is fit the same way ``detect_cylinders`` fits a cylinder axis
(SVD of the component's unit face normals — for a true partial cylinder the
axis is the smallest singular vector) since a straight-edge fillet *is* a
partial cylinder. This is best-effort: a strip whose SVD axis fit fails
(no clean directionality) is dropped rather than reported with a
meaningless radius.
"""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.features.base import Feature, FeatureKind
from src.analysis.features.facet_graph import (
    MAX_FEATURE_FACET_NODES,
    build_face_groups,
    group_aspect,
    group_pair_angles,
)


def detect_fillets(
    mesh: trimesh.Trimesh,
    min_step_deg: float = 2.0,
    max_step_deg: float = 20.0,
    min_total_turn_deg: float = 45.0,
    max_total_turn_deg: float = 135.0,
    min_groups: int = 3,
    min_segment_aspect: float = 1.6,
    min_strip_aspect: float = 1.3,
) -> list[Feature]:
    """Detect rounded-edge fillet strips.

    Args:
        min_step_deg / max_step_deg: per-edge dihedral range that counts as
            "smooth roll" (excludes coplanar ~0deg and sharp breaks).
        min_total_turn_deg / max_total_turn_deg: acceptable accumulated turn
            across the whole strip.
        min_groups: minimum eligible facet-groups (tessellation segments)
            in a qualifying strip.
        min_segment_aspect: a facet-group must have at least this in-plane
            length/width ratio to be eligible as a strip node at all (this
            is what keeps the big flanking flat faces out of the strip).
        min_strip_aspect: the whole strip's axial length / average
            transverse width must be at least this (thin strip, not blob).
    """
    features: list[Feature] = []
    if len(mesh.faces) == 0:
        return features

    try:
        groups, face_to_group = build_face_groups(mesh)
    except Exception:
        return features
    if len(groups) < min_groups:
        return features
    if len(groups) > MAX_FEATURE_FACET_NODES:
        # Organic / pathologically-tessellated mesh — the strip traversal goes
        # superlinear here and detection is unreliable anyway. Honest skip.
        return features

    pair_angles = group_pair_angles(mesh, face_to_group)
    if not pair_angles:
        return features

    try:
        face_areas = np.asarray(mesh.area_faces, dtype=np.float64)
        centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
        normals = np.asarray(mesh.face_normals, dtype=np.float64)
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
    except Exception:
        return features

    # A group is only eligible to be a strip node if it is itself a narrow
    # sliver. This is what keeps large flanking flat/curved faces out of the
    # graph even when the tangent seam's dihedral happens to fall inside the
    # "small step" range (see module docstring).
    eligible: set[int] = set()
    group_area_cache: dict[int, float] = {}
    for gid, g_faces in enumerate(groups):
        group_area_cache[gid] = float(face_areas[g_faces].sum())
        aspect, _w, _l = group_aspect(g_faces, vertices, faces, normals)
        if aspect is not None and aspect >= min_segment_aspect:
            eligible.add(gid)

    # Small-step edges only, restricted to eligible (sliver) nodes.
    small_edges: dict[int, list[tuple[int, float, bool]]] = {}
    for (ga, gb), entries in pair_angles.items():
        if ga not in eligible or gb not in eligible:
            continue
        angs = [e[0] for e in entries]
        convs = [e[1] for e in entries]
        mean_ang = float(np.mean(angs))
        if not (min_step_deg <= mean_ang <= max_step_deg):
            continue
        majority_convex = sum(convs) >= (len(convs) / 2.0)
        small_edges.setdefault(ga, []).append((gb, mean_ang, majority_convex))
        small_edges.setdefault(gb, []).append((ga, mean_ang, majority_convex))

    if not small_edges:
        return features

    components = _connected_components(small_edges)

    for comp in components:
        if len(comp) < min_groups:
            continue

        comp_set = set(comp)
        degree: dict[int, list[tuple[int, float, bool]]] = {}
        ok_topology = True
        for g in comp:
            nbrs_in_comp = [e for e in small_edges.get(g, []) if e[0] in comp_set]
            degree[g] = nbrs_in_comp
            if len(nbrs_in_comp) > 2:
                ok_topology = False
                break
        if not ok_topology:
            continue

        endpoints = [g for g in comp if len(degree[g]) == 1]
        internal = [g for g in comp if len(degree[g]) == 2]
        if len(endpoints) != 2 or len(endpoints) + len(internal) != len(comp):
            # Not exactly 2 endpoints -> either a closed loop (0 endpoints,
            # e.g. a bare cylindrical wall) or a malformed/branching graph.
            # Both are explicitly rejected rather than guessed at.
            continue

        path, convex_flags, step_angles = _walk_path(endpoints[0], degree)
        if path is None or len(path) != len(comp):
            continue  # didn't recover a single simple path through everything

        if len(set(convex_flags)) > 1:
            continue  # curvature direction flips sign — not a simple fillet

        total_turn = float(sum(step_angles))
        if not (min_total_turn_deg <= total_turn <= max_total_turn_deg):
            continue

        # Flanking check: both path endpoints must border a group outside
        # the strip that is itself NOT an eligible sliver (i.e. it's a real
        # bounding surface, not more strip) and is at least as large.
        flank_ok = True
        flank_info = []
        for end_g in (path[0], path[-1]):
            flank = _best_flank(end_g, comp_set, eligible, pair_angles, group_area_cache)
            if flank is None:
                flank_ok = False
                break
            flank_info.append(flank)
        if not flank_ok:
            continue

        comp_faces = np.concatenate([groups[g] for g in path])
        area = float(face_areas[comp_faces].sum())
        if area <= 0 or not np.isfinite(area):
            continue

        axis, radius, residual = _fit_axis_radius(comp_faces, normals, centroids, vertices, faces)
        if axis is None:
            continue  # can't validate strip shape without a directionality fit

        # Axial length: spread of the strip's own vertices along its fitted
        # axis (mirrors detect_cylinders' depth calc). For a fillet running
        # along a straight edge this axis IS the strip's run direction, so
        # this is the correct "length"; the transverse (developed arc)
        # width is then area / length.
        vert_idx = np.unique(faces[comp_faces])
        pts = vertices[vert_idx]
        mean_pt = pts.mean(axis=0)
        axial = (pts - mean_pt) @ np.asarray(axis)
        length_mm = float(axial.max() - axial.min()) if len(axial) else 0.0
        if length_mm <= 1e-6:
            continue
        width_mm = area / length_mm
        aspect = length_mm / max(width_mm, 1e-9)
        if aspect < min_strip_aspect:
            continue

        conf = 0.55
        if 60.0 <= total_turn <= 120.0:
            conf += 0.1
        if aspect >= 3.0:
            conf += 0.05
        if residual is not None and residual < 0.3:
            conf += 0.05
        conf = float(min(0.75, max(0.5, conf)))

        centroid = tuple(float(v) for v in centroids[comp_faces].mean(axis=0))

        features.append(
            Feature(
                kind=FeatureKind.FILLET,
                face_indices=[int(i) for i in comp_faces],
                centroid=centroid,
                area=area,
                axis=axis,
                radius=radius,
                confidence=conf,
                metadata={
                    "total_turn_deg": total_turn,
                    "n_segments": len(path),
                    "aspect": aspect,
                    "axial_length_mm": length_mm,
                    "avg_width_mm": width_mm,
                    "axis_residual": residual,
                    "convex": bool(convex_flags[0]) if convex_flags else None,
                    "flank_group_ids": [f[0] for f in flank_info],
                },
            )
        )

    return features


def _connected_components(
    small_edges: dict[int, list[tuple[int, float, bool]]],
) -> list[list[int]]:
    """Union-find connected components over the small-step graph's nodes."""
    nodes = list(small_edges.keys())
    parent = {n: n for n in nodes}

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for g, nbrs in small_edges.items():
        for other, _ang, _cv in nbrs:
            ra, rb = find(g), find(other)
            if ra != rb:
                parent[ra] = rb

    groups: dict[int, list[int]] = {}
    for n in nodes:
        root = find(n)
        groups.setdefault(root, []).append(n)
    return list(groups.values())


def _walk_path(
    start: int, degree: dict[int, list[tuple[int, float, bool]]]
) -> tuple[list[int] | None, list[bool], list[float]]:
    """Walk a simple path from a degree-1 endpoint through the component.

    Returns (ordered_node_list, per_step_convex_flags, per_step_angles_deg),
    or (None, [], []) if the graph isn't actually a simple path (defensive;
    the caller has already checked degree sequence but a stray isolated
    duplicate edge could still confuse the walk).
    """
    path = [start]
    convex_flags: list[bool] = []
    step_angles: list[float] = []
    current = start
    visited = {start}
    guard = 0
    max_steps = len(degree) + 2
    while True:
        guard += 1
        if guard > max_steps:
            return None, [], []
        # Advance to whichever neighbor of `current` hasn't been visited yet.
        next_edge = None
        for e in degree[current]:
            if e[0] not in visited:
                next_edge = e
                break
        if next_edge is None:
            break
        nxt, ang, cv = next_edge
        path.append(nxt)
        convex_flags.append(cv)
        step_angles.append(ang)
        visited.add(nxt)
        current = nxt

    return path, convex_flags, step_angles


def _best_flank(
    end_g: int,
    comp_set: set[int],
    eligible: set[int],
    pair_angles: dict[tuple[int, int], list[tuple[float, bool]]],
    group_area_cache: dict[int, float],
) -> tuple[int, float] | None:
    """Find a neighbor of ``end_g`` outside the strip that isn't itself a sliver.

    Returns ``(other_group_id, mean_boundary_angle_deg)`` for the largest
    qualifying flank, or ``None`` if the endpoint has no real bounding
    surface (e.g. it runs off the edge of the mesh, or every neighbor is
    itself another eligible sliver — ambiguous, so no feature is emitted).
    """
    end_area = group_area_cache.get(end_g, 0.0)
    best = None
    for (ga, gb), entries in pair_angles.items():
        if ga == end_g:
            other = gb
        elif gb == end_g:
            other = ga
        else:
            continue
        if other in comp_set or other in eligible:
            continue
        other_area = group_area_cache.get(other, 0.0)
        if other_area < end_area:
            continue  # flanking surface should be the bigger one, not a stray sliver
        mean_ang = float(np.mean([e[0] for e in entries]))
        if best is None or other_area > group_area_cache.get(best[0], 0.0):
            best = (other, mean_ang)
    return best


def _fit_axis_radius(
    comp_faces: np.ndarray,
    normals: np.ndarray,
    centroids: np.ndarray,
    vertices: np.ndarray | None = None,
    faces: np.ndarray | None = None,
) -> tuple[tuple[float, float, float] | None, float | None, float | None]:
    """Best-effort partial-cylinder axis/radius fit.

    Axis: SVD of unit face normals (same math as ``detect_cylinders`` — for
    a true partial cylinder the axis is the smallest singular vector; this
    part is unaffected by how much of the circle the strip covers).

    Radius: a fillet strip only ever covers a fraction of a full circle
    (typically 45-135deg per the module's turn gate), and a naive "mean
    radial distance of points from their own centroid" estimate is *biased
    low* for a partial arc (the centroid of an arc's points sits inside the
    true circle, pulled toward the chord — for an ~80deg arc this understates
    radius by roughly 60%, confirmed numerically while building this
    detector). Instead we do a proper 2D least-squares circle fit (Kasa
    method) of the strip's vertices projected onto the plane perpendicular
    to the fitted axis, which is unbiased for a partial arc.

    Returns (axis, radius, mean |normal . axis| residual), any of which may
    be None if the fit is degenerate.
    """
    try:
        comp_normals = normals[comp_faces]
        comp_centroids = centroids[comp_faces]
        lengths = np.linalg.norm(comp_normals, axis=1)
        finite = (
            np.isfinite(comp_normals).all(axis=1)
            & np.isfinite(comp_centroids).all(axis=1)
            & (lengths > 1e-9)
        )
        if int(finite.sum()) < 3:
            return None, None, None
        comp_normals_u = comp_normals[finite] / lengths[finite, None]

        _, _sv, vh = np.linalg.svd(comp_normals_u, full_matrices=False)
        axis = vh[-1]
        axis_norm = np.linalg.norm(axis)
        if not np.isfinite(axis_norm) or axis_norm <= 1e-12:
            return None, None, None
        axis = axis / axis_norm

        residual = float(np.mean(np.abs(comp_normals_u @ axis)))
        if not np.isfinite(residual):
            residual = None

        radius = None
        if vertices is not None and faces is not None:
            radius = _kasa_circle_radius(comp_faces, faces, vertices, axis)
        if radius is None:
            # Fallback: naive mean-radial-distance (biased low for a partial
            # arc, but better than nothing if the circle fit is degenerate).
            mean = comp_centroids.mean(axis=0)
            rel = comp_centroids - mean
            axial = rel @ axis
            radial = rel - np.outer(axial, axis)
            radii = np.linalg.norm(radial, axis=1)
            r = float(radii.mean())
            radius = r if np.isfinite(r) and r > 0 else None

        axis_out = tuple(float(v) for v in axis)
        return axis_out, radius, residual
    except Exception:
        return None, None, None


def _kasa_circle_radius(
    comp_faces: np.ndarray,
    faces: np.ndarray,
    vertices: np.ndarray,
    axis: np.ndarray,
) -> float | None:
    """Least-squares (Kasa) circle radius of the strip's vertices in cross-section.

    Projects vertices onto the plane perpendicular to ``axis`` and fits a
    circle algebraically. Unbiased for a partial arc, unlike a naive
    mean-centroid radial-distance estimate.
    """
    try:
        vert_idx = np.unique(faces[comp_faces])
        pts = vertices[vert_idx]
        if len(pts) < 4:
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
        return radius if np.isfinite(radius) and radius > 0 else None
    except Exception:
        return None
