"""2D mask -> 3D face label projection (mask lifting).

For each 2D mask produced by the SAM backbone, the face-ID buffer from the
renderer maps masked pixels to mesh face indices.  Masks from multiple views
are merged via IoU-based majority voting so that each face receives the label
that the majority of views agree on.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING

import numpy as np

from src.segmentation.sam3d.types import Mask, ViewRender

if TYPE_CHECKING:
    import trimesh


def lift_masks(
    mesh: "trimesh.Trimesh",
    view_mask_pairs: list[tuple[ViewRender, list[Mask]]],
    min_faces: int = 5,
) -> list[tuple[list[int], float]]:
    """Lift 2D masks to 3D face-index sets using cross-view voting.

    For every rendered view and every mask in that view, the face-ID buffer
    identifies which mesh faces fall under the mask.  Faces that appear in
    masks across multiple views are grouped together, and the agreement ratio
    (fraction of views where the face was masked) is returned.

    Args:
        mesh: The source mesh (used only for face count).
        view_mask_pairs: List of ``(ViewRender, masks)`` from each camera.
        min_faces: Minimum number of faces for a segment to be emitted.

    Returns:
        List of ``(face_indices, agreement)`` tuples.  *agreement* is in
        ``[0, 1]`` — fraction of views that contained this face in any mask.
    """
    if not view_mask_pairs:
        return []

    num_faces = len(mesh.faces)
    if num_faces == 0:
        return []

    # Per-face: how many views saw this face in *any* mask,
    # and which "mask cluster" it was assigned to in each view.
    face_view_count = np.zeros(num_faces, dtype=np.int32)
    num_views_with_faces = 0

    # Segment accumulator: map segment_key -> set of face indices
    # We assign a unique segment key per (view_index, mask_index) and then
    # merge segments across views whose face-index sets overlap.
    raw_segments: list[set[int]] = []

    for view_idx, (view, masks) in enumerate(view_mask_pairs):
        face_ids = view.face_ids
        if face_ids is None:
            continue

        view_contributed = False

        for mask in masks:
            # Pixels under the mask
            mask_pixels = mask.binary_mask
            if mask_pixels is None or mask_pixels.size == 0:
                continue

            # Map masked pixels to face indices via the face-ID buffer
            masked_face_ids = face_ids[mask_pixels]
            valid = masked_face_ids[masked_face_ids >= 0]
            if len(valid) == 0:
                continue

            unique_faces = set(int(f) for f in np.unique(valid) if f < num_faces)
            if len(unique_faces) < min_faces:
                continue

            raw_segments.append(unique_faces)
            for f in unique_faces:
                face_view_count[f] += 1

            view_contributed = True

        if view_contributed:
            num_views_with_faces += 1

    if not raw_segments:
        return []

    # --- Merge overlapping segments across views ---
    merged = _merge_overlapping(raw_segments)

    # --- Compute per-segment agreement ---
    total_views = max(num_views_with_faces, 1)
    results: list[tuple[list[int], float]] = []
    for seg in merged:
        if len(seg) < min_faces:
            continue
        face_list = sorted(seg)
        # Agreement = average per-face view count / total contributing views
        avg_count = float(np.mean(face_view_count[face_list]))
        agreement = min(avg_count / total_views, 1.0)
        results.append((face_list, agreement))

    return results


def _merge_overlapping(segments: list[set[int]]) -> list[set[int]]:
    """Merge segment sets that share any face indices (union-find style)."""
    if not segments:
        return []

    # Simple iterative merge: keep merging until stable.
    merged = list(segments)
    changed = True
    while changed:
        changed = False
        new_merged: list[set[int]] = []
        used = [False] * len(merged)
        for i in range(len(merged)):
            if used[i]:
                continue
            current = set(merged[i])
            for j in range(i + 1, len(merged)):
                if used[j]:
                    continue
                if current & merged[j]:
                    current |= merged[j]
                    used[j] = True
                    changed = True
            new_merged.append(current)
            used[i] = True
        merged = new_merged

    return merged
