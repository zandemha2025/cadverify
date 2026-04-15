"""Sheet metal specific checks."""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.constants import (
    BEND_RADIUS_MULTIPLIER,
    STANDARD_GAUGES,
)
from src.analysis.models import (
    FeatureSegment,
    GeometryInfo,
    Issue,
    ProcessType,
    Severity,
)

# Minimum hole diameter = sheet thickness
# Minimum hole-to-edge distance = 2x sheet thickness
# Minimum hole-to-bend distance = 2x sheet thickness + bend radius


def check_sheet_thickness(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    process: ProcessType,
) -> list[Issue]:
    """Check if the part's thickness profile matches sheet metal.

    Sheet metal parts should have roughly uniform thickness.
    """
    issues = []
    dims = sorted(geometry.bounding_box.dimensions)

    # The thinnest dimension should be the sheet thickness
    thickness = dims[0]

    if thickness < 0.3:
        issues.append(Issue(
            code="TOO_THIN_SHEET",
            severity=Severity.ERROR,
            message=f"Thickness {thickness:.2f}mm is below minimum sheet gauge (0.5mm).",
            process=process,
            measured_value=thickness,
            required_value=0.5,
            fix_suggestion="Increase thickness to at least 0.5mm standard gauge.",
        ))
    elif thickness > 8.0:
        issues.append(Issue(
            code="TOO_THICK_SHEET",
            severity=Severity.WARNING,
            message=(
                f"Thickness {thickness:.1f}mm exceeds typical sheet metal range (0.5-6mm). "
                "Consider plate machining instead."
            ),
            process=process,
            measured_value=thickness,
            fix_suggestion="Use CNC machining for thick plate, or redesign for thinner sheet.",
        ))

    # Check if it's a standard gauge
    closest_gauge = min(STANDARD_GAUGES, key=lambda g: abs(g - thickness))
    if abs(closest_gauge - thickness) > 0.1 and 0.5 <= thickness <= 6.0:
        issues.append(Issue(
            code="NON_STANDARD_GAUGE",
            severity=Severity.INFO,
            message=(
                f"Thickness {thickness:.2f}mm is not a standard gauge. "
                f"Nearest standard: {closest_gauge}mm."
            ),
            process=process,
            measured_value=thickness,
            fix_suggestion=f"Adjust design to use {closest_gauge}mm standard gauge for cost savings.",
        ))
    return issues


def check_bend_feasibility(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    process: ProcessType,
) -> list[Issue]:
    """Check if bends are feasible based on geometry.

    Analyzes the mesh for sharp edges that would represent bends
    and checks minimum bend radius constraints.
    """
    issues = []

    # Find sharp edges (dihedral angle significantly different from 180°)
    face_adjacency = mesh.face_adjacency
    face_adjacency_angles = mesh.face_adjacency_angles

    if len(face_adjacency_angles) == 0:
        return issues

    # Sharp bends: angles significantly less than pi (180°)
    bend_threshold = np.radians(160)  # Faces meeting at < 160° = a bend
    sharp_mask = face_adjacency_angles < bend_threshold
    sharp_edges = face_adjacency[sharp_mask]

    if len(sharp_edges) > 0:
        # Check for very sharp bends (< 90°)
        very_sharp = face_adjacency_angles[sharp_mask] < np.radians(90)
        if np.any(very_sharp):
            issues.append(Issue(
                code="SHARP_BEND",
                severity=Severity.ERROR,
                message=(
                    f"Detected {int(np.sum(very_sharp))} very sharp bends (< 90°). "
                    "Minimum bend radius must be >= material thickness."
                ),
                process=process,
                fix_suggestion=(
                    "Increase bend radius to at least 1x material thickness. "
                    "For stainless steel, use 1.5x; for titanium, use 3x."
                ),
            ))
    return issues


def check_hole_placement(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    process: ProcessType,
) -> list[Issue]:
    """Check hole-to-edge and hole-to-bend distances."""
    issues = []

    # This is a simplified check — real sheet metal analysis needs
    # feature recognition to identify holes and bends
    dims = sorted(geometry.bounding_box.dimensions)
    thickness = dims[0]

    # Flag general guidance about hole placement
    if geometry.face_count > 100:  # Complex enough to likely have holes
        issues.append(Issue(
            code="HOLE_PLACEMENT_CHECK",
            severity=Severity.INFO,
            message=(
                f"For sheet thickness {thickness:.1f}mm: minimum hole diameter "
                f"should be {thickness:.1f}mm, hole-to-edge distance "
                f"{thickness * 2:.1f}mm, hole-to-bend distance "
                f"{thickness * 2 + thickness:.1f}mm."
            ),
            process=process,
            fix_suggestion="Verify all holes meet minimum distance requirements for the gauge.",
        ))
    return issues


def run_sheet_metal_checks(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    process: ProcessType,
    segments: list[FeatureSegment] | None = None,
) -> list[Issue]:
    """Run all sheet metal checks."""
    issues: list[Issue] = []
    issues.extend(check_sheet_thickness(mesh, geometry, process))
    issues.extend(check_bend_feasibility(mesh, geometry, process))
    issues.extend(check_hole_placement(mesh, geometry, process))
    return issues
