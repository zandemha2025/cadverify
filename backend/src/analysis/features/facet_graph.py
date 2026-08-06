"""Shared facet-level topology helpers for the chamfer / fillet detectors.

Both detectors need to reason about *groups of coplanar triangles* (a
"facet") rather than raw triangles, because a CAD-exported mesh routinely
splits every planar quad into two triangles joined by a 0deg diagonal. If a
detector walks the raw ``mesh.face_adjacency`` graph and only follows edges
whose dihedral angle sits inside some "interesting" band, that 0deg diagonal
edge is excluded from the band and the walk fractures into disconnected
2-triangle islands instead of one continuous strip. Collapsing coplanar
triangles into a single graph node (via ``mesh.facets``) sidesteps the
problem entirely.

``mesh.facets`` only reports groups of >=2 coplanar *adjacent* triangles, so
a triangle with no coplanar neighbor is left out of every group. We restore
full coverage by giving every such leftover triangle its own singleton
group ("pseudo-facet") so the graph below still has one node per mesh face,
covering both CAD-style quad-per-segment tessellation and continuously
triangulated (no coplanar pairs at all) meshes.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import trimesh

# Perf safety valve for the fillet/chamfer detectors. A well-formed CAD mesh
# collapses into a handful of facet-groups (a box = 6, a complex machined part
# rarely exceeds a few hundred), so this ceiling never bites real CAD. It only
# trips on organic / scanned / pathologically-tessellated meshes where nearly
# every triangle is its own singleton group — precisely the meshes on which the
# facet-graph traversal goes superlinear (measured: ~8.5s on an 82k-face
# icosphere) AND on which mesh-based fillet/chamfer detection is least reliable.
# Above this, the detectors honestly skip (omit the feature) rather than burn
# hot-path latency guessing.
MAX_FEATURE_FACET_NODES = 6000


def build_face_groups(mesh: trimesh.Trimesh) -> tuple[list[np.ndarray], np.ndarray]:
    """Group mesh faces into coplanar clusters plus singleton leftovers.

    Returns:
        groups: list where ``groups[g]`` is the int array of face indices in
            group ``g`` (real ``mesh.facets`` entries first, then
            singletons).
        face_to_group: int array of length ``len(mesh.faces)`` mapping each
            face index to its group id.
    """
    n = len(mesh.faces)
    face_to_group = np.full(n, -1, dtype=np.int64)
    groups: list[np.ndarray] = []

    try:
        facets = list(mesh.facets)
    except Exception:
        facets = []

    for g in facets:
        arr = np.asarray(g, dtype=np.int64)
        if arr.size == 0:
            continue
        gid = len(groups)
        face_to_group[arr] = gid
        groups.append(arr)

    ungrouped = np.where(face_to_group < 0)[0]
    for f in ungrouped:
        face_to_group[f] = len(groups)
        groups.append(np.array([f], dtype=np.int64))

    return groups, face_to_group


def group_pair_angles(
    mesh: trimesh.Trimesh, face_to_group: np.ndarray
) -> dict[tuple[int, int], list[tuple[float, bool]]]:
    """Aggregate raw face-adjacency dihedral angles up to the group level.

    Returns ``{(g_lo, g_hi): [(angle_deg, convex), ...]}`` for every pair of
    *distinct* groups that share at least one triangle edge. Multiple shared
    edges between the same two groups all contribute an entry (callers
    typically average them).
    """
    pair_angles: dict[tuple[int, int], list[tuple[float, bool]]] = defaultdict(list)
    try:
        adjacency = np.asarray(mesh.face_adjacency)
        angles = np.asarray(mesh.face_adjacency_angles)
        convex = np.asarray(mesh.face_adjacency_convex)
    except Exception:
        return pair_angles

    if len(adjacency) == 0:
        return pair_angles

    angles_deg = np.degrees(angles)
    for (a, b), ang, cv in zip(adjacency, angles_deg, convex):
        ga, gb = int(face_to_group[a]), int(face_to_group[b])
        if ga < 0 or gb < 0 or ga == gb:
            continue
        key = (ga, gb) if ga < gb else (gb, ga)
        pair_angles[key].append((float(ang), bool(cv)))
    return pair_angles


def group_aspect(
    g_faces: np.ndarray,
    vertices: np.ndarray,
    faces: np.ndarray,
    normals: np.ndarray,
) -> tuple[float | None, float | None, float | None]:
    """Best-effort in-plane length/width of a single facet group.

    Projects the group's vertices onto its average plane and takes an
    axis-aligned (in that local 2D frame) bounding box. Not a true oriented
    bounding box, but good enough to tell "long thin sliver" (a chamfer
    band, or one segment of a tessellated fillet strip) from "roughly
    square patch" (an ordinary flat face).

    Returns ``(aspect, width_mm, length_mm)``, or ``(None, None, None)`` on
    any degeneracy (too few vertices, zero-area normal, ...).
    """
    try:
        vert_idx = np.unique(faces[g_faces])
        pts = vertices[vert_idx]
        if len(pts) < 3:
            return None, None, None

        mean_normal = normals[g_faces].mean(axis=0)
        norm = np.linalg.norm(mean_normal)
        if norm <= 1e-12 or not np.isfinite(norm):
            return None, None, None
        n_hat = mean_normal / norm

        ref = np.array([1.0, 0.0, 0.0]) if abs(n_hat[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        e1 = ref - n_hat * np.dot(ref, n_hat)
        e1_norm = np.linalg.norm(e1)
        if e1_norm <= 1e-12:
            return None, None, None
        e1 = e1 / e1_norm
        e2 = np.cross(n_hat, e1)

        centered = pts - pts.mean(axis=0)
        u = centered @ e1
        v = centered @ e2
        du = float(u.max() - u.min())
        dv = float(v.max() - v.min())
        if not (np.isfinite(du) and np.isfinite(dv)):
            return None, None, None
        length = max(du, dv)
        width = max(min(du, dv), 1e-9)
        return length / width, width, length
    except Exception:
        return None, None, None


def group_neighbors(
    pair_angles: dict[tuple[int, int], list[tuple[float, bool]]],
) -> dict[int, list[tuple[int, float, bool]]]:
    """Per-group neighbor list: ``{g: [(other_g, mean_angle_deg, majority_convex), ...]}``."""
    neighbors: dict[int, list[tuple[int, float, bool]]] = defaultdict(list)
    for (ga, gb), entries in pair_angles.items():
        angs = [e[0] for e in entries]
        convs = [e[1] for e in entries]
        mean_ang = float(np.mean(angs))
        majority_convex = sum(convs) >= (len(convs) / 2.0)
        neighbors[ga].append((gb, mean_ang, majority_convex))
        neighbors[gb].append((ga, mean_ang, majority_convex))
    return neighbors
