"""Additive manufacturing (3D printing) specific checks.

Covers FDM, SLA/DLP, SLS, MJF, DMLS/SLM, EBM, Binder Jetting, DED/WAAM.
"""

from __future__ import annotations

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from src.analysis.constants import (
    BUILD_VOLUMES,
    MIN_FEATURE_SIZE,
    MIN_WALL_THICKNESS,
    SUPPORT_ANGLE_THRESHOLD,
)
from src.analysis.models import (
    FeatureSegment,
    GeometryInfo,
    Issue,
    ProcessType,
    Severity,
)


def check_wall_thickness(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Check wall thickness using ray-casting from face centroids.

    Shoots rays inward from each face centroid and measures distance
    to the opposite wall.
    """
    issues = []
    min_wall = MIN_WALL_THICKNESS.get(process, 0.8)

    # Sample face centroids for ray casting
    centroids = mesh.triangles_center
    normals = mesh.face_normals

    # Shoot rays inward (opposite to face normal) with offset to clear origin face
    offset = 0.01  # mm
    ray_origins = centroids - normals * offset
    ray_directions = -normals

    # Use trimesh ray casting
    try:
        locations, index_ray, index_tri = mesh.ray.intersects_location(
            ray_origins=ray_origins,
            ray_directions=ray_directions,
        )
    except Exception:
        return issues  # Skip if ray casting fails

    if len(locations) == 0:
        return issues

    # Calculate thickness for each ray
    thin_faces = []
    min_measured = float("inf")

    # Group hits by source ray, skip self-hits (same face or distance < offset)
    for i in range(len(centroids)):
        mask = index_ray == i
        if not np.any(mask):
            continue
        hit_tris = index_tri[mask]
        hits = locations[mask]
        distances = np.linalg.norm(hits - ray_origins[i], axis=1)
        # Filter out self-hits: same triangle or very close hits
        valid = (hit_tris != i) & (distances > offset * 2)
        if not np.any(valid):
            continue
        # Wall thickness = distance to nearest opposite wall
        thickness = float(np.min(distances[valid]))
        if thickness < min_measured:
            min_measured = thickness
        if thickness < min_wall:
            thin_faces.append(i)

    if thin_faces:
        # Find the center of the thin region
        thin_centroids = centroids[thin_faces[:50]]
        region_center = tuple(np.mean(thin_centroids, axis=0).tolist())
        pct = len(thin_faces) / len(centroids) * 100

        issues.append(Issue(
            code="THIN_WALL",
            severity=Severity.ERROR if pct > 10 else Severity.WARNING,
            message=(
                f"{len(thin_faces)} faces ({pct:.1f}%) have wall thickness below "
                f"{min_wall}mm minimum for {process.value}. "
                f"Thinnest measured: {min_measured:.2f}mm."
            ),
            process=process,
            affected_faces=thin_faces[:100],
            region_center=region_center,
            measured_value=min_measured,
            required_value=min_wall,
            fix_suggestion=(
                f"Increase wall thickness to at least {min_wall}mm for "
                f"{process.value}. If thinner walls are needed, consider "
                f"SLA/DLP (min {MIN_WALL_THICKNESS[ProcessType.SLA]}mm) or "
                f"DMLS (min {MIN_WALL_THICKNESS[ProcessType.DMLS]}mm)."
            ),
        ))
    return issues


def check_overhangs(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Detect overhang faces that exceed the support threshold.

    Overhangs are faces whose normal has a large angle from vertical (Z-up).
    """
    issues = []
    threshold = SUPPORT_ANGLE_THRESHOLD.get(process, 45.0)

    if threshold >= 90.0:
        return issues  # Self-supporting process, no overhang issues

    normals = mesh.face_normals
    # Angle between face normal and the downward Z vector
    # A face pointing straight down has 180° from Z-up, 0° overhang
    z_up = np.array([0, 0, 1])
    cos_angles = np.dot(normals, z_up)
    # Convert to degrees from vertical
    angles_from_vertical = np.degrees(np.arccos(np.clip(cos_angles, -1, 1)))

    # Overhang = face pointing away from Z-up beyond threshold
    # (angles > 90° + threshold are overhangs)
    overhang_mask = angles_from_vertical > (90.0 + threshold)
    overhang_faces = np.where(overhang_mask)[0].tolist()

    if overhang_faces:
        pct = len(overhang_faces) / len(normals) * 100
        centroids = mesh.triangles_center[overhang_faces[:50]]
        region_center = tuple(np.mean(centroids, axis=0).tolist())

        severity = Severity.WARNING
        if pct > 30:
            severity = Severity.WARNING  # Heavy support but still printable

        issues.append(Issue(
            code="OVERHANG",
            severity=severity,
            message=(
                f"{len(overhang_faces)} faces ({pct:.1f}%) exceed "
                f"{threshold}° overhang threshold for {process.value}. "
                "These areas will need support structures."
            ),
            process=process,
            affected_faces=overhang_faces[:100],
            region_center=region_center,
            fix_suggestion=(
                f"Reorient the part to minimize overhangs, or redesign "
                f"overhanging features with self-supporting angles (<{threshold}°). "
                f"For {process.value}, supports increase cost and leave surface marks."
            ),
        ))
    return issues


def check_small_features(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Detect features smaller than the process resolution."""
    issues = []
    min_feature = MIN_FEATURE_SIZE.get(process, 0.4)

    # Check for thin edges by measuring edge lengths
    edges = mesh.edges_unique
    edge_lengths = mesh.edges_unique_length

    small_edges = edge_lengths[edge_lengths < min_feature]
    if len(small_edges) > 0:
        pct = len(small_edges) / len(edge_lengths) * 100
        smallest = float(np.min(small_edges))

        if pct > 5:  # Only flag if significant
            issues.append(Issue(
                code="SMALL_FEATURES",
                severity=Severity.WARNING,
                message=(
                    f"{len(small_edges)} edges ({pct:.1f}%) are smaller than "
                    f"{min_feature}mm minimum feature size for {process.value}. "
                    f"Smallest: {smallest:.3f}mm."
                ),
                process=process,
                measured_value=smallest,
                required_value=min_feature,
                fix_suggestion=(
                    f"Features below {min_feature}mm may not resolve in "
                    f"{process.value}. Increase feature size or switch to a "
                    f"higher-resolution process like SLA (min {MIN_FEATURE_SIZE[ProcessType.SLA]}mm)."
                ),
            ))
    return issues


def check_trapped_volumes(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Check for internal cavities that could trap powder/resin.

    Critical for powder-bed processes (SLS, MJF, DMLS, EBM, Binder Jetting).
    """
    issues = []
    powder_processes = {
        ProcessType.SLS, ProcessType.MJF, ProcessType.DMLS,
        ProcessType.SLM, ProcessType.EBM, ProcessType.BINDER_JET,
    }
    if process not in powder_processes:
        return issues

    # Check for internal voids by looking at mesh components
    # If mesh has fully enclosed internal cavities, flag them
    try:
        split_meshes = mesh.split()
        if len(split_meshes) > 1:
            # Check if any sub-mesh is fully contained within another
            main_vol = max(split_meshes, key=lambda m: m.volume if m.is_watertight else 0)
            for sub in split_meshes:
                if sub is main_vol:
                    continue
                if sub.is_watertight:
                    center = sub.centroid
                    if main_vol.contains([center])[0]:
                        issues.append(Issue(
                            code="TRAPPED_VOLUME",
                            severity=Severity.ERROR,
                            message=(
                                f"Internal cavity detected that will trap un-sintered "
                                f"powder in {process.value}. Volume: {sub.volume:.1f}mm³."
                            ),
                            process=process,
                            region_center=tuple(center.tolist()),
                            fix_suggestion=(
                                "Add drain holes (minimum 2mm diameter for most "
                                "powder-bed processes) to allow powder removal. "
                                "Place holes on non-critical surfaces."
                            ),
                        ))
    except Exception:
        pass  # Skip if split/containment check fails

    return issues


def check_build_volume(
    geometry: GeometryInfo,
    process: ProcessType,
) -> list[Issue]:
    """Check if part fits within typical build volumes for the process."""
    issues = []

    dims = geometry.bounding_box.dimensions
    max_vol = BUILD_VOLUMES.get(process)
    if max_vol is None:
        return issues

    exceeds = []
    for i, (dim, limit, axis) in enumerate(zip(dims, max_vol, ("X", "Y", "Z"))):
        if dim > limit:
            exceeds.append(f"{axis}: {dim:.1f}mm > {limit}mm")

    if exceeds:
        issues.append(Issue(
            code="EXCEEDS_BUILD_VOLUME",
            severity=Severity.ERROR,
            message=(
                f"Part exceeds typical build volume for {process.value}: "
                + ", ".join(exceeds)
            ),
            process=process,
            fix_suggestion=(
                "Scale down the part, split into multiple pieces, or use a "
                "larger-format machine. For very large parts, consider "
                "DED/WAAM (up to 5m) or industrial FDM (BigRep: 1m³)."
            ),
        ))
    return issues


def check_aspect_ratio(
    geometry: GeometryInfo,
    process: ProcessType,
) -> list[Issue]:
    """Check for extreme aspect ratios that cause print failures."""
    issues = []
    dims = sorted(geometry.bounding_box.dimensions)
    if dims[0] < 0.1:
        return issues  # Avoid division by near-zero

    aspect_ratio = dims[2] / dims[0]  # Longest / shortest

    if aspect_ratio > 15:
        issues.append(Issue(
            code="EXTREME_ASPECT_RATIO",
            severity=Severity.WARNING,
            message=(
                f"Aspect ratio of {aspect_ratio:.1f}:1 is very high. "
                f"Tall/thin parts are prone to failure during {process.value} printing."
            ),
            process=process,
            measured_value=aspect_ratio,
            fix_suggestion=(
                "Consider splitting into segments, adding temporary bracing, "
                "or reorienting the part. For FDM, a brim or raft helps adhesion."
            ),
        ))
    return issues


ADDITIVE_PROCESSES = list(MIN_WALL_THICKNESS.keys())


def run_additive_checks(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    process: ProcessType,
    segments: list[FeatureSegment] | None = None,
) -> list[Issue]:
    """Run all additive manufacturing checks for a given process."""
    issues: list[Issue] = []
    issues.extend(check_wall_thickness(mesh, process))
    issues.extend(check_overhangs(mesh, process))
    issues.extend(check_small_features(mesh, process))
    issues.extend(check_trapped_volumes(mesh, process))
    issues.extend(check_build_volume(geometry, process))
    issues.extend(check_aspect_ratio(geometry, process))
    return issues
