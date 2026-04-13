"""SAM-3D pipeline orchestrator.

Coordinates multi-view rendering, SAM-2 mask generation, 2D-to-3D lifting,
and manufacturing feature classification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from src.segmentation.sam3d import cache
from src.segmentation.sam3d import classifier
from src.segmentation.sam3d import renderer
from src.segmentation.sam3d.backbone import SAM2Backbone
from src.segmentation.sam3d.config import SAM3DConfig
from src.segmentation.sam3d import lifter
from src.segmentation.sam3d.types import SemanticSegment

if TYPE_CHECKING:
    import trimesh

# Module-level backbone singleton (lazy-loaded).
_backbone: SAM2Backbone | None = None


def _get_backbone(config: SAM3DConfig) -> SAM2Backbone:
    """Return the module-level SAM-2 backbone, loading weights if needed."""
    global _backbone
    if _backbone is None:
        _backbone = SAM2Backbone()
    if not _backbone.is_loaded and config.model_path:
        _backbone.load(config.model_path)
    return _backbone


def is_sam3d_available() -> bool:
    """Check whether the SAM-3D pipeline is enabled via configuration."""
    config = SAM3DConfig.from_env()
    return config.enabled


def segment_sam3d(
    mesh: "trimesh.Trimesh",
    config: SAM3DConfig | None = None,
) -> list[SemanticSegment]:
    """Run the full SAM-3D semantic segmentation pipeline.

    Pipeline stages:
        1. Check content-addressable cache
        2. Render mesh from *num_views* camera positions
        3. Run SAM-2 automatic mask generation on each rendered view
        4. Lift 2D masks to 3D face labels via cross-view voting
        5. Classify each segment into a manufacturing semantic label
        6. Store results in cache

    Args:
        mesh: Input trimesh object.
        config: Pipeline configuration.  Falls back to env-var config.

    Returns:
        List of :class:`SemanticSegment`.  Empty when the pipeline is
        disabled, dependencies are missing, or the mesh has no faces.
    """
    config = config or SAM3DConfig.from_env()

    if not config.enabled:
        return []

    if mesh is None or len(mesh.faces) == 0:
        return []

    # 1. Check cache
    cached = cache.get(mesh, config.cache_dir)
    if cached is not None:
        return cached

    # 2. Render views
    views = renderer.render_views(mesh, config.num_views)
    if not views:
        return []

    # 3. Generate masks per view
    backbone = _get_backbone(config)
    view_mask_pairs = []
    for view in views:
        masks = backbone.generate_masks(view.rgb)
        view_mask_pairs.append((view, masks))

    # 4. Lift 2D masks to 3D face labels
    face_segments = lifter.lift_masks(
        mesh,
        view_mask_pairs,
        min_faces=config.min_segment_faces,
    )

    # 5. Classify each segment
    segments: list[SemanticSegment] = []
    for seg_faces, agreement in face_segments:
        label, confidence = classifier.classify(mesh, seg_faces)

        if confidence < config.confidence_threshold:
            continue

        face_centroids = mesh.triangles_center[seg_faces]
        centroid = tuple(face_centroids.mean(axis=0).tolist())

        segments.append(SemanticSegment(
            label=label,
            face_indices=seg_faces,
            centroid=centroid,
            confidence=confidence,
            view_agreement=agreement,
        ))

    # 6. Cache result
    cache.put(mesh, segments, config.cache_dir)

    return segments
