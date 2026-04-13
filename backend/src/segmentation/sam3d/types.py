"""Semantic segment types for manufacturing feature labeling."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class SemanticLabel(str, Enum):
    """Manufacturing-domain semantic labels for mesh regions."""

    BEARING_SEAT = "bearing_seat"
    GASKET_FACE = "gasket_face"
    MOUNTING_HOLE = "mounting_hole"
    COOLING_CHANNEL = "cooling_channel"
    LIGHTENING_POCKET = "lightening_pocket"
    STRUCTURAL_WEB = "structural_web"
    THREAD_REGION = "thread_region"
    KEYWAY = "keyway"
    FLANGE = "flange"
    DATUM_SURFACE = "datum_surface"
    UNKNOWN = "unknown"


@dataclass
class SemanticSegment:
    """A semantically-labeled region of a mesh.

    Attributes:
        label: Manufacturing feature classification.
        face_indices: Mesh face indices belonging to this segment.
        centroid: Geometric center (x, y, z) of the segment.
        confidence: Classifier confidence in ``[0, 1]``.
        view_agreement: Fraction of rendered views that agreed on this label.
        metadata: Arbitrary per-segment data (geometric stats, debug info).
    """

    label: SemanticLabel
    face_indices: list[int]
    centroid: tuple[float, float, float]
    confidence: float
    view_agreement: float
    metadata: dict = field(default_factory=dict)


@dataclass
class Mask:
    """A 2D binary mask produced by the SAM backbone."""

    binary_mask: np.ndarray  # (H, W) bool
    confidence: float


@dataclass
class ViewRender:
    """Output of a single camera view render.

    Attributes:
        rgb: (H, W, 3) uint8 image.
        depth: (H, W) float32 depth buffer.
        face_ids: (H, W) int32 — each pixel maps to a mesh face index (-1 = background).
        camera_transform: 4x4 camera-to-world transform.
    """

    rgb: np.ndarray
    depth: np.ndarray
    face_ids: np.ndarray
    camera_transform: np.ndarray
