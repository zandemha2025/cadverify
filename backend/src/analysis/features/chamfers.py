"""Chamfer detection: narrow flat bevel bands between two larger surfaces.

A chamfer, geometrically, is a small planar (or near-planar) facet that
replaces a sharp edge with a bevel: it sits between exactly two larger
surfaces, meets each of them at a discrete "bevel" dihedral angle (clearly
neither coplanar ~0deg nor a sharp ~90deg corner), and is a narrow band
relative to the surfaces it connects.

Pipeline (all facet-level, see ``facet_graph.py`` for why):
    1. Group triangles into coplanar clusters (``mesh.facets``) plus
       singleton leftovers, so a chamfer band that happens to be a single
       un-paired triangle is not silently dropped.
    2. For each group, look at its neighbor groups. Keep only neighbors
       whose shared dihedral falls inside the bevel range (default 15-75deg).
       A qualifying chamfer facet must have *exactly two* such neighbors —
       the two surfaces it bevels between. (It may also border other groups
       at other angles, e.g. end caps at ~90deg; those don't disqualify it.)
    3. Reject unless the candidate is clearly narrower than both bevel
       neighbors (area ratio) and is an elongated band, not a small square
       patch (aspect ratio).

This is deliberately conservative: a real chamfer that is highly irregular,
curved, or fused into a much larger coplanar region will be missed rather
than mis-flagged. False positives are the expensive mistake here (an
invented chamfer is a bogus manufacturing note); false negatives just mean
"no comment made" which is `honest.
"""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.features.base import Feature, FeatureKind
from src.analysis.features.facet_graph import (
    MAX_FEATURE_FACET_NODES,
    build_face_groups,
    group_aspect,
    group_neighbors,
    group_pair_angles,
)


def detect_chamfers(
    mesh: trimesh.Trimesh,
    min_bevel_deg: float = 15.0,
    max_bevel_deg: float = 75.0,
    max_area_ratio: float = 0.35,
    min_neighbor_ratio: float = 1.3,
    min_aspect: float = 1.6,
) -> list[Feature]:
    """Detect narrow bevel-band chamfer features.

    Args:
        min_bevel_deg / max_bevel_deg: dihedral range that counts as a
            bevel (excludes near-coplanar ~0deg and near-square ~90deg
            transitions).
        max_area_ratio: candidate facet area must be <= this fraction of
            the SMALLER of its two bevel neighbors' areas ("narrow").
        min_neighbor_ratio: each bevel neighbor must be at least this many
            times larger in area than the candidate ("the neighbors are the
            big surfaces, not the bevel itself").
        min_aspect: candidate's in-plane length/width must be at least this
            (elongated band, not a small square corner patch).
    """
    features: list[Feature] = []
    if len(mesh.faces) == 0:
        return features

    try:
        groups, face_to_group = build_face_groups(mesh)
    except Exception:
        return features
    if len(groups) < 3:
        return features
    if len(groups) > MAX_FEATURE_FACET_NODES:
        # Organic / pathologically-tessellated mesh — honest skip (see fillets).
        return features

    pair_angles = group_pair_angles(mesh, face_to_group)
    if not pair_angles:
        return features
    neighbors = group_neighbors(pair_angles)

    try:
        face_areas = np.asarray(mesh.area_faces, dtype=np.float64)
        centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        normals = np.asarray(mesh.face_normals, dtype=np.float64)
    except Exception:
        return features

    total_area = float(mesh.area) if getattr(mesh, "area", 0) else 1.0

    def group_area(g: np.ndarray) -> float:
        return float(face_areas[g].sum())

    for g_id, g_faces in enumerate(groups):
        nbrs = neighbors.get(g_id, [])
        if not nbrs:
            continue
        bevel_nbrs = {
            other: ang
            for other, ang, _convex in nbrs
            if min_bevel_deg <= ang <= max_bevel_deg
        }
        if len(bevel_nbrs) != 2:
            continue

        area_g = group_area(g_faces)
        if area_g <= 0 or not np.isfinite(area_g):
            continue
        if area_g / total_area < 1e-6:
            continue  # numerical noise sliver

        (n1, ang1), (n2, ang2) = list(bevel_nbrs.items())
        area_n1 = group_area(groups[n1])
        area_n2 = group_area(groups[n2])
        if area_n1 <= 0 or area_n2 <= 0:
            continue
        if area_n1 < min_neighbor_ratio * area_g or area_n2 < min_neighbor_ratio * area_g:
            continue

        ratio = area_g / min(area_n1, area_n2)
        if ratio > max_area_ratio:
            continue

        aspect, width_mm, length_mm = group_aspect(g_faces, vertices, faces, normals)
        if aspect is not None and aspect < min_aspect:
            continue

        centroid = tuple(float(v) for v in centroids[g_faces].mean(axis=0))
        mean_bevel = (ang1 + ang2) / 2.0

        # Confidence: modest baseline heuristic, biased down for anything
        # marginal (imbalanced bevel angles, weak aspect, wide area ratio).
        conf = 0.6
        if abs(ang1 - ang2) < 8.0:
            conf += 0.08  # symmetric bevel — the common real-world case
        if ratio < 0.15:
            conf += 0.07  # clearly narrow
        if aspect is not None and aspect >= 3.0:
            conf += 0.05
        conf = float(min(0.8, max(0.5, conf)))

        features.append(
            Feature(
                kind=FeatureKind.CHAMFER,
                face_indices=[int(i) for i in g_faces],
                centroid=centroid,
                area=area_g,
                confidence=conf,
                metadata={
                    "dihedral_deg": mean_bevel,
                    "neighbor_dihedrals_deg": [ang1, ang2],
                    "area_ratio_to_neighbors": ratio,
                    "aspect": aspect,
                    "width_mm": width_mm,
                    "length_mm": length_mm,
                },
            )
        )

    return features

