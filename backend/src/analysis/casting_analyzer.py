"""Casting-specific checks (investment, sand, die casting handled in molding_analyzer)."""

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


# Minimum fillet radius (mm) — sharp internal corners cause stress concentration and cracking
MIN_FILLET_RADIUS = {
    ProcessType.INVESTMENT_CASTING: 0.5,
    ProcessType.SAND_CASTING: 3.0,
    ProcessType.DIE_CASTING: 1.0,
}


def check_fillet_requirements(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Check for sharp internal corners that need fillets.

    Sharp corners cause stress risers in castings and prevent
    proper material flow.
    """
    issues = []
    min_fillet = MIN_FILLET_RADIUS.get(process)
    if min_fillet is None:
        return issues

    # Find concave edges (internal corners)
    face_adjacency = mesh.face_adjacency
    face_adjacency_angles = mesh.face_adjacency_angles

    if len(face_adjacency_angles) == 0:
        return issues

    # Sharp concave edges: small dihedral angle = sharp internal corner
    sharp_threshold = np.radians(120)  # < 120° = needs fillet
    sharp_mask = face_adjacency_angles < sharp_threshold
    sharp_count = int(np.sum(sharp_mask))

    if sharp_count > 5:
        issues.append(Issue(
            code="MISSING_FILLETS",
            severity=Severity.WARNING,
            message=(
                f"{sharp_count} sharp internal corners detected. "
                f"Casting requires fillets of at least {min_fillet}mm radius "
                "for proper material flow and stress distribution."
            ),
            process=process,
            required_value=min_fillet,
            fix_suggestion=(
                f"Add {min_fillet}mm+ fillets to all internal corners. "
                "Generous fillets improve casting quality, reduce porosity, "
                "and prevent hot spots during solidification."
            ),
        ))
    return issues


def check_core_feasibility(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Check if internal cavities can be formed with cores.

    Sand casting cores must be supportable and removable.
    Investment casting has fewer core limitations.
    """
    issues = []
    if process != ProcessType.SAND_CASTING:
        return issues

    # Check for internal voids that would need cores
    try:
        splits = mesh.split()
        if len(splits) > 1:
            main = max(splits, key=lambda m: m.volume if m.is_watertight else 0)
            for sub in splits:
                if sub is main and sub.is_watertight:
                    continue
                if sub.is_watertight and sub.volume > 0:
                    center = sub.centroid
                    if main.is_watertight and main.contains([center])[0]:
                        # Check core aspect ratio
                        core_dims = sorted(sub.extents)
                        if core_dims[0] > 0 and core_dims[2] / core_dims[0] > 6:
                            issues.append(Issue(
                                code="FRAGILE_CORE",
                                severity=Severity.WARNING,
                                message=(
                                    "Internal cavity requires a long, thin core "
                                    f"(aspect ratio {core_dims[2] / core_dims[0]:.1f}:1). "
                                    "Core may break during casting."
                                ),
                                process=process,
                                region_center=tuple(center.tolist()),
                                fix_suggestion=(
                                    "Redesign cavity to reduce core aspect ratio below 4:1. "
                                    "Consider splitting into multiple simpler cores."
                                ),
                            ))
    except Exception:
        pass
    return issues


def check_shrinkage_geometry(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    process: ProcessType,
) -> list[Issue]:
    """Flag geometry patterns prone to shrinkage defects."""
    issues = []

    # Large solid sections are prone to shrinkage porosity
    # Check for high volume-to-surface-area ratio (indicates bulky sections)
    if geometry.volume > 0 and geometry.surface_area > 0:
        compactness = geometry.volume / geometry.surface_area
        # A perfect sphere has the highest V/SA ratio
        # Parts with compactness > ~15mm are likely to have shrinkage issues
        if compactness > 15:
            issues.append(Issue(
                code="SHRINKAGE_RISK",
                severity=Severity.WARNING,
                message=(
                    f"Volume/surface-area ratio ({compactness:.1f}mm) indicates "
                    "bulky sections prone to shrinkage porosity during solidification."
                ),
                process=process,
                measured_value=compactness,
                fix_suggestion=(
                    "Core out thick sections to reduce mass. Maintain uniform "
                    "wall thickness to promote even cooling. Add risers in "
                    "thick sections during foundry planning."
                ),
            ))
    return issues


CASTING_PROCESSES = [
    ProcessType.INVESTMENT_CASTING,
    ProcessType.SAND_CASTING,
]


def run_casting_checks(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    process: ProcessType,
    segments: list[FeatureSegment] | None = None,
) -> list[Issue]:
    """Run all casting-specific checks."""
    issues: list[Issue] = []
    issues.extend(check_fillet_requirements(mesh, process))
    issues.extend(check_core_feasibility(mesh, process))
    issues.extend(check_shrinkage_geometry(mesh, geometry, process))
    return issues
