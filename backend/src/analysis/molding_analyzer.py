"""Injection molding and die casting specific checks."""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.models import (
    FeatureSegment,
    GeometryInfo,
    Issue,
    ProcessType,
    Severity,
)

# Minimum draft angle (degrees) by process
MIN_DRAFT_ANGLE = {
    ProcessType.INJECTION_MOLDING: 1.0,
    ProcessType.DIE_CASTING: 1.0,
    ProcessType.INVESTMENT_CASTING: 0.5,
    ProcessType.SAND_CASTING: 3.0,
    ProcessType.FORGING: 5.0,
}

# Wall thickness ranges (mm) — [min, max, ideal]
WALL_THICKNESS_RANGE = {
    ProcessType.INJECTION_MOLDING: (0.5, 6.0, 2.5),
    ProcessType.DIE_CASTING: (0.8, 12.0, 3.0),
    ProcessType.INVESTMENT_CASTING: (1.0, 50.0, 5.0),
    ProcessType.SAND_CASTING: (3.0, 100.0, 8.0),
    ProcessType.FORGING: (3.0, 200.0, 10.0),
}


def check_draft_angles(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Check that faces have sufficient draft angle for mold release.

    Draft is measured as the angle between the face normal and the
    pull direction (assumed Z-axis).
    """
    issues = []
    min_draft = MIN_DRAFT_ANGLE.get(process)
    if min_draft is None:
        return issues

    normals = mesh.face_normals
    face_areas = mesh.area_faces

    # Pull direction is Z-axis — faces on sidewalls need draft
    # Draft angle = 90° - angle_from_z_axis for vertical faces
    z_axis = np.array([0, 0, 1])
    cos_z = np.abs(np.dot(normals, z_axis))
    angles_from_z = np.degrees(np.arccos(np.clip(cos_z, 0, 1)))

    # Faces near 90° from Z are sidewalls — check their draft
    sidewall_mask = (angles_from_z > 80) & (angles_from_z < 100)
    sidewall_faces = np.where(sidewall_mask)[0]

    if len(sidewall_faces) == 0:
        return issues

    # Draft angle = |90° - angle_from_z|
    draft_angles = np.abs(90.0 - angles_from_z[sidewall_faces])
    no_draft_mask = draft_angles < min_draft
    no_draft_faces = sidewall_faces[no_draft_mask].tolist()

    if no_draft_faces:
        no_draft_area = float(np.sum(face_areas[no_draft_faces]))
        total_sidewall_area = float(np.sum(face_areas[sidewall_faces]))
        pct = no_draft_area / total_sidewall_area * 100 if total_sidewall_area > 0 else 0

        issues.append(Issue(
            code="INSUFFICIENT_DRAFT",
            severity=Severity.ERROR,
            message=(
                f"{len(no_draft_faces)} sidewall faces ({pct:.1f}% of sidewall area) "
                f"have less than {min_draft}° draft angle. "
                f"Parts will stick in the mold/die."
            ),
            process=process,
            affected_faces=no_draft_faces[:100],
            required_value=min_draft,
            fix_suggestion=(
                f"Add at least {min_draft}° draft to all vertical walls in "
                f"the pull direction. Standard practice for "
                f"{process.value}: {min_draft}-3° on external faces, "
                f"double that on internal faces/ribs."
            ),
        ))
    return issues


def check_wall_uniformity(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Check for wall thickness uniformity.

    Uneven walls cause sink marks, warping, and internal stresses
    in molding and casting processes.
    """
    issues = []
    thickness_range = WALL_THICKNESS_RANGE.get(process)
    if thickness_range is None:
        return issues

    min_wall, max_wall, ideal_wall = thickness_range

    # Measure wall thickness via ray casting
    centroids = mesh.triangles_center
    normals = mesh.face_normals
    ray_origins = centroids + normals * 0.001
    ray_directions = -normals

    try:
        locations, index_ray, _ = mesh.ray.intersects_location(
            ray_origins=ray_origins,
            ray_directions=ray_directions,
        )
    except Exception:
        return issues

    if len(locations) == 0:
        return issues

    thicknesses = []
    for i in range(len(centroids)):
        mask = index_ray == i
        if not np.any(mask):
            continue
        hits = locations[mask]
        dist = float(np.min(np.linalg.norm(hits - ray_origins[i], axis=1)))
        thicknesses.append(dist)

    if not thicknesses:
        return issues

    t = np.array(thicknesses)
    t_min, t_max, t_mean = float(t.min()), float(t.max()), float(t.mean())
    t_std = float(t.std())

    # Check min/max limits
    if t_min < min_wall:
        issues.append(Issue(
            code="THIN_WALL_MOLDING",
            severity=Severity.ERROR,
            message=(
                f"Minimum wall thickness {t_min:.2f}mm is below "
                f"{min_wall}mm minimum for {process.value}. "
                "Thin areas won't fill properly."
            ),
            process=process,
            measured_value=t_min,
            required_value=min_wall,
            fix_suggestion=f"Increase wall thickness to at least {min_wall}mm.",
        ))

    if t_max > max_wall:
        issues.append(Issue(
            code="THICK_WALL_MOLDING",
            severity=Severity.WARNING,
            message=(
                f"Maximum wall thickness {t_max:.2f}mm exceeds "
                f"{max_wall}mm. Thick sections cause sink marks "
                "and long cycle times."
            ),
            process=process,
            measured_value=t_max,
            required_value=max_wall,
            fix_suggestion="Core out thick sections or redesign to uniform wall thickness.",
        ))

    # Check uniformity
    if t_max > 0 and (t_max / t_min) > 2.0:
        issues.append(Issue(
            code="NON_UNIFORM_WALLS",
            severity=Severity.WARNING,
            message=(
                f"Wall thickness varies from {t_min:.2f}mm to {t_max:.2f}mm "
                f"(ratio {t_max / t_min:.1f}:1). Non-uniform walls cause "
                "warping, sink marks, and internal stresses."
            ),
            process=process,
            measured_value=t_max / t_min,
            required_value=2.0,
            fix_suggestion=(
                f"Aim for uniform {ideal_wall}mm walls. Gradually transition "
                "between thick and thin sections (3:1 taper ratio). "
                "Use ribs instead of solid sections for strength."
            ),
        ))
    return issues


def check_undercuts_molding(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Check for undercuts that prevent mold release.

    In molding/casting, undercuts require side actions, slides,
    or collapsible cores — all add tooling cost.
    """
    issues = []
    if process not in (ProcessType.INJECTION_MOLDING, ProcessType.DIE_CASTING):
        return issues

    normals = mesh.face_normals
    centroids = mesh.triangles_center

    # Parting line assumed at mid-height Z
    mid_z = (mesh.bounds[0][2] + mesh.bounds[1][2]) / 2

    # Upper half: faces pointing inward-and-down are undercuts
    upper_mask = centroids[:, 2] > mid_z
    upper_downward = upper_mask & (normals[:, 2] < -0.3)

    # Lower half: faces pointing inward-and-up are undercuts
    lower_mask = centroids[:, 2] <= mid_z
    lower_upward = lower_mask & (normals[:, 2] > 0.3)

    # Also check lateral undercuts (faces pointing inward on X/Y)
    # that can't be reached from the parting direction
    # Simplified: faces with horizontal normals that are "inside" the part
    undercut_faces = np.where(upper_downward | lower_upward)[0].tolist()

    if undercut_faces:
        issues.append(Issue(
            code="UNDERCUT_MOLDING",
            severity=Severity.WARNING,
            message=(
                f"{len(undercut_faces)} faces form undercuts that prevent "
                f"mold release. Requires side actions or slides in the "
                f"{process.value} tooling."
            ),
            process=process,
            affected_faces=undercut_faces[:100],
            fix_suggestion=(
                "Redesign to eliminate undercuts: replace hooks with snap-fits, "
                "change hole orientations to align with pull direction, or "
                "accept higher tooling cost for side actions."
            ),
        ))
    return issues


MOLDING_PROCESSES = [
    ProcessType.INJECTION_MOLDING,
    ProcessType.DIE_CASTING,
    ProcessType.INVESTMENT_CASTING,
    ProcessType.SAND_CASTING,
    ProcessType.FORGING,
]


def run_molding_checks(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    process: ProcessType,
    segments: list[FeatureSegment] | None = None,
) -> list[Issue]:
    """Run all injection molding / casting checks."""
    issues: list[Issue] = []
    issues.extend(check_draft_angles(mesh, process))
    issues.extend(check_wall_uniformity(mesh, process))
    issues.extend(check_undercuts_molding(mesh, process))
    return issues
