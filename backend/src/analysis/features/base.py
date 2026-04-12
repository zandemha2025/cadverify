"""Feature dataclass and kind enum shared by every detector."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class FeatureKind(str, Enum):
    # Surfaces
    FLAT = "flat"
    CURVED = "curved"

    # Cylindrical
    CYLINDER_HOLE = "cylinder_hole"
    CYLINDER_BOSS = "cylinder_boss"

    # Transitions
    FILLET = "fillet"
    CHAMFER = "chamfer"

    # Concave regions
    POCKET = "pocket"

    # Extrusions
    RIB = "rib"
    THREAD = "thread"

    UNKNOWN = "unknown"


@dataclass
class Feature:
    """A manufacturing feature anchored to a set of mesh faces.

    Type-specific fields are optional so one dataclass handles every kind.
    Downstream code branches on `kind` and reads only what's meaningful.
    """

    kind: FeatureKind
    face_indices: list[int]
    centroid: tuple[float, float, float]
    confidence: float = 1.0

    # Optional geometric descriptors (populated per kind).
    axis: Optional[tuple[float, float, float]] = None      # unit vector
    radius: Optional[float] = None                          # mm
    depth: Optional[float] = None                           # mm (along axis)
    area: Optional[float] = None                            # mm² (surface area)

    # Free-form per-detector metadata (e.g. dihedral residuals, fit quality).
    metadata: dict[str, Any] = field(default_factory=dict)
