"""Feature dataclass and kind enum shared by every detector."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

if TYPE_CHECKING:
    import trimesh


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


def _outer_rotational_features(features: Optional[list[Feature]]) -> list[Feature]:
    candidates = []
    for feature in features or []:
        if feature.kind != FeatureKind.CYLINDER_BOSS and not (
            feature.kind == FeatureKind.CURVED
            and (feature.metadata or {}).get("surface") == "conical"
            and (feature.metadata or {}).get("interior") is False
        ):
            continue
        singular_values = (feature.metadata or {}).get("singular_values", [])
        if (
            len(singular_values) < 2
            or float(singular_values[0]) <= 0
            or float(singular_values[1]) / float(singular_values[0]) < 0.25
        ):
            continue
        area = feature.area or 0.0
        if area > 0:
            candidates.append(feature)
    return candidates


def has_rotational_surface_evidence(
    features: Optional[list[Feature]],
    surface_area_mm2: float,
    *,
    min_fraction: float = 0.05,
    mesh: Optional[trimesh.Trimesh] = None,
) -> bool:
    """Return true only for a materially sized, measured outer rotational surface.

    The cylinder detector also sees triangulated planar patches. Those patches
    have normal variation in only one direction, while a circular cylinder or
    cone spans two independent radial directions. Requiring that rank plus a minimum
    share of total surface area prevents a small bore—or a boxy part with similar
    inertia moments—from being presented as lathe-ready. A complete spherical
    mesh is also rotational, even though it has no cylindrical surface.
    """
    if not np.isfinite(surface_area_mm2) or surface_area_mm2 <= 0:
        return False
    boss_area = sum(float(f.area or 0.0) for f in _outer_rotational_features(features))
    if boss_area >= min_fraction * float(surface_area_mm2):
        return True
    if mesh is None or not mesh.is_volume:
        return False
    # ponytail: whole spheres within 2% tessellation error only; general curved
    # solids of revolution need a measured axial-profile test, not an inertia guess.
    # Check face interiors too: every vertex of a cube lies on one sphere.
    center = mesh.center_mass
    radii = np.linalg.norm(mesh.vertices - center, axis=1)
    face_radii = np.linalg.norm(mesh.triangles_center - center, axis=1)
    radius = float(np.mean(radii))
    return bool(
        np.isfinite(radius) and radius > 0
        and np.all(np.abs(radii / radius - 1) <= 0.02)
        and np.all(np.abs(face_radii / radius - 1) <= 0.02)
    )


def turning_dimensions(
    mesh: trimesh.Trimesh, features: Optional[list[Feature]],
) -> Optional[tuple[float, float, float]]:
    """Measured axial length, enclosing diameter and radial roundness.

    Use the detected outer cylinder/cone axis; inertia alone is ambiguous when
    all moments are equal. Whole spheres use a principal axis. Measurements
    follow the part frame, so rigid rotation cannot change its lathe stock.
    """
    if not mesh.is_volume or not has_rotational_surface_evidence(features, mesh.area, mesh=mesh):
        return None
    candidates = [f for f in _outer_rotational_features(features) if f.axis is not None]
    if candidates:
        axis = np.asarray(max(candidates, key=lambda f: f.area or 0.0).axis, dtype=float)
    else:
        # The only supported shape without an outer cylinder/cone is a sphere.
        axis = np.linalg.eigh(mesh.moment_inertia)[1][:, 0]
    if not np.all(np.isfinite(axis)) or np.linalg.norm(axis) == 0:
        return None
    axis = axis / np.linalg.norm(axis)
    vertices = np.asarray(mesh.vertices) - mesh.center_mass
    axial = vertices @ axis
    radial = vertices - axial[:, None] * axis
    length = float(np.ptp(axial))
    diameter = 2.0 * float(np.max(np.linalg.norm(radial, axis=1)))
    basis = np.cross(axis, np.eye(3)[np.argmin(np.abs(axis))])
    basis /= np.linalg.norm(basis)
    spans = np.ptp(vertices @ np.column_stack((basis, np.cross(axis, basis))), axis=0)
    roundness = float(np.min(spans) / np.max(spans)) if np.max(spans) > 0 else 0.0
    return length, diameter, roundness
