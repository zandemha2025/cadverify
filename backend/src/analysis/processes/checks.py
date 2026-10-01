"""Reusable DFM check functions parameterized by process thresholds.

Each function takes a GeometryContext + process-specific parameters and
returns a list[Issue]. Analyzers compose these like building blocks —
FDM calls check_wall_thickness(ctx, 0.8, ...) while SLA calls it with 0.3.

Design rules:
    * Every check returns [] on success — never None.
    * Thresholds are arguments, never hardcoded — the analyzer owns the number.
    * Citation strings ride through to the Issue for enterprise audit.
    * All geometry reads come from ctx (precomputed), never from mesh.ray.*.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from src.analysis.citations import parse_citation
from src.analysis.serialization import format_measurement
from src.analysis.constants import STANDARD_GAUGES, SHEET_GAUGE_MIN_MM, SHEET_GAUGE_MAX_MM
from src.analysis.context import GeometryContext, fitting_box_dimensions, wall_thickness_tolerance
from src.analysis.features.base import (
    Feature,
    FeatureKind,
    has_rotational_surface_evidence,
    turning_dimensions,
)
from src.analysis.models import Issue, ProcessType, Severity

logger = logging.getLogger("cadverify.checks")


# ──────────────────────────────────────────────────────────────
# Wall thickness
# ──────────────────────────────────────────────────────────────
def _wall_upper(ctx: GeometryContext) -> np.ndarray:
    upper = ctx.wall_thickness_upper
    if upper is None:
        upper = (np.full(len(ctx.wall_thickness), np.inf) if ctx.mesh.metadata.get("coordinate_error")
                 else ctx.wall_thickness)
    return np.where(np.isfinite(ctx.wall_thickness), upper, np.inf)


def _wall_precision_issues(ctx: GeometryContext, process: ProcessType) -> list[Issue]:
    upper = _wall_upper(ctx)
    if not ctx.mesh.metadata.get("coordinate_error") and np.all(np.isfinite(upper)):
        return []
    return [Issue(
        code="WALL_THICKNESS_PRECISION", severity=Severity.WARNING, process=process,
        message=(
            f"Wall checks have stable measurements for {int(np.isfinite(upper).sum())} of {len(upper)} faces. "
            "Thin-wall failures allow for source-coordinate rounding. Ambiguous hits and "
            "unsampled faces cannot verify a minimum wall; a result near the limit is uncertain."
        ),
        fix_suggestion="Confirm critical wall thicknesses in the source CAD before manufacturing.",
    )]


def check_wall_thickness(
    ctx: GeometryContext,
    min_wall_mm: float,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    wt = ctx.wall_thickness
    finite = np.isfinite(wt)
    thin = finite & (_wall_upper(ctx) < min_wall_mm - wall_thickness_tolerance(ctx.mesh, ctx.scale_eps))
    thin_faces = np.where(thin)[0]
    issues = _wall_precision_issues(ctx, process)
    if len(thin_faces) == 0:
        return issues
    pct = len(thin_faces) / max(len(ctx.centroids), 1) * 100
    min_measured = float(wt[thin].min())
    region = _region_center(ctx, thin_faces)
    sev = Severity.ERROR if pct > 10 else Severity.WARNING
    issues.append(Issue(
        code="THIN_WALL",
        measurement_unit="mm",
        severity=sev,
        message=(
            f"{len(thin_faces)} faces ({pct:.1f}%) below {min_wall_mm}mm "
            f"min wall for {process.value}. Thinnest: {format_measurement(min_measured, min_wall_mm)}mm."
        ),
        process=process,
        affected_faces=thin_faces.tolist(),
        region_center=region,
        measured_value=min_measured,
        required_value=min_wall_mm,
        fix_suggestion=f"Increase wall thickness to >= {min_wall_mm}mm. {cite}",
        citation=parse_citation(cite),
    ))
    return issues


# ──────────────────────────────────────────────────────────────
# Overhangs
# ──────────────────────────────────────────────────────────────
def check_overhangs(
    ctx: GeometryContext,
    max_angle_deg: float,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    """Faces whose angle from Z-up exceeds 90 + max_angle_deg need supports."""
    if max_angle_deg >= 90.0:
        return []  # self-supporting process
    threshold = 90.0 + max_angle_deg
    oh_mask = ctx.angles_from_up_deg > threshold
    # Faces resting ON the build plate need no supports: exclude near-flat
    # downward faces whose centroid sits at the part's z-minimum (scale-aware
    # tolerance so micro and macro parts both behave).
    if len(ctx.centroids):
        z = ctx.centroids[:, 2]
        z_tol = max(0.1, ctx.bbox_diag * 1e-3)
        on_plate = (z <= float(z.min()) + z_tol) & (ctx.angles_from_up_deg >= 175.0)
        oh_mask = oh_mask & ~on_plate
    oh_faces = np.where(oh_mask)[0]
    if len(oh_faces) == 0:
        return []
    pct = len(oh_faces) / max(len(ctx.centroids), 1) * 100
    region = _region_center(ctx, oh_faces)
    return [Issue(
        code="OVERHANG",
        severity=Severity.WARNING,
        message=(
            f"{len(oh_faces)} faces ({pct:.1f}%) exceed {max_angle_deg}° "
            f"overhang threshold for {process.value}. Supports required."
        ),
        process=process,
        affected_faces=oh_faces.tolist(),
        region_center=region,
        fix_suggestion=(
            f"Reorient part or redesign overhangs < {max_angle_deg}° "
            f"for {process.value}. {cite}"
        ),
        citation=parse_citation(cite),
    )]


# ──────────────────────────────────────────────────────────────
# Small features
# ──────────────────────────────────────────────────────────────
def check_small_features(
    ctx: GeometryContext,
    min_size_mm: float,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    precision = ctx.edge_length_precision
    if precision is None:
        precision = np.full(len(ctx.edge_lengths), np.inf if ctx.mesh.metadata.get("coordinate_error") else 0.)
    return small_feature_issues(ctx.edge_lengths, precision, min_size_mm, process,
                               cite=cite, topology_stable=ctx.edge_topology_stable)


def small_feature_issues(
    lengths: np.ndarray, precision: np.ndarray, min_size_mm: float,
    process: ProcessType, *, cite: str = "", topology_stable: bool = True,
) -> list[Issue]:
    issues: list[Issue] = []
    uncertain = (~np.isfinite(precision) | ((lengths - precision <= min_size_mm) &
                                         (lengths + precision >= min_size_mm) & (precision > 0)))
    if np.any(uncertain) or not topology_stable:
        issues.append(Issue(
            code="FEATURE_SIZE_PRECISION", severity=Severity.WARNING, process=process,
            message=("Some geometric boundaries cannot be compared reliably with "
                     f"the {min_size_mm}mm resolution limit because of source precision or unstable rim measurements."),
            fix_suggestion="Measure these features in the source CAD before manufacturing.",
        ))
    small = lengths[lengths + precision < min_size_mm]
    if len(small) == 0:
        return issues
    pct = len(small) / len(lengths) * 100
    if pct < 5:
        return issues  # not significant
    smallest = float(small.min())
    issues.append(Issue(
        code="SMALL_FEATURES",
        measurement_unit="mm",
        severity=Severity.WARNING,
        message=(
            f"{len(small)} geometric boundary spans ({pct:.1f}%) below {min_size_mm}mm "
            f"resolution for {process.value}. Smallest: {format_measurement(smallest, min_size_mm)}mm."
        ),
        process=process,
        measured_value=smallest,
        required_value=min_size_mm,
        fix_suggestion=f"Enlarge features to >= {min_size_mm}mm. {cite}",
        citation=parse_citation(cite),
    ))
    return issues


# ──────────────────────────────────────────────────────────────
# Build volume / workpiece size
# ──────────────────────────────────────────────────────────────
def check_build_volume(
    ctx: GeometryContext,
    max_dims_mm: tuple[float, float, float],
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    dims = ctx.info.bounding_box.dimensions
    if process == ProcessType.CNC_TURNING:
        measured = turning_dimensions(ctx.mesh, ctx.features)
        if measured is not None:
            length, diameter, _ = measured
            dims = (diameter, diameter, length)
    exceeds = []
    for dim, limit, axis in zip(dims, max_dims_mm, ("X", "Y", "Z")):
        if dim > limit:
            exceeds.append(f"{axis}: {format_measurement(dim, limit)}mm > {limit}mm")
    tolerance = 0.0 if process == ProcessType.CNC_TURNING else wall_thickness_tolerance(ctx.mesh, ctx.scale_eps)
    precision = 0.0 if process == ProcessType.CNC_TURNING else 2 * float(ctx.mesh.metadata.get("coordinate_error", 0.0))
    if not exceeds and all(d + precision <= cap + tolerance for d, cap in zip(dims, max_dims_mm)):
        return []
    uncertain = bool(precision and not exceeds)
    if process != ProcessType.CNC_TURNING and not ctx.metadata.get("decimation", {}).get("succeeded"):
        enclosing, basis = ctx.enclosing_box
        fitting = fitting_box_dimensions(enclosing, tuple(cap + tolerance for cap in max_dims_mm))
        if fitting is not None:
            if not exceeds:
                return []
            return [Issue(
                code="BUILD_REORIENTATION_REQUIRED",
                severity=Severity.INFO,
                message=(
                    f"The uploaded orientation exceeds the {max_dims_mm}mm envelope for {process.value}, "
                    f"but a {tuple(round(d, 6) for d in fitting)}mm enclosing box fits after reorientation "
                    f"({basis})."
                ),
                process=process,
                fix_suggestion=(
                    "Reorient in the manufacturing setup. Review supports, tool access and fixtures "
                    "in that orientation; this envelope check does not clear other DFM findings."
                ),
                citation=parse_citation(cite),
            )]
        # The enclosure already includes +precision. Subtract it twice for
        # the lower bound; overlap cannot establish either fit or non-fit.
        uncertain = uncertain or bool(precision and fitting_box_dimensions(
            tuple(d - 2 * precision for d in enclosing),
            tuple(cap + tolerance for cap in max_dims_mm)) is not None)
    if uncertain:
        return [Issue(
            code="BUILD_ENVELOPE_PRECISION", severity=Severity.WARNING, process=process,
            message=(f"Source-coordinate rounding (enclosing dimensions up to ±{precision:.3g}mm) "
                     f"overlaps the {max_dims_mm}mm envelope for {process.value}; fit remains uncertain."),
            fix_suggestion="Confirm dimensions and the planned orientation in source CAD, or use a larger machine.",
            citation=parse_citation(cite),
        )]
    return [Issue(
        code="EXCEEDS_BUILD_VOLUME",
        severity=Severity.ERROR,
        message=(
            f"Part exceeds build envelope for {process.value}: "
            + ", ".join(exceeds) + f". {cite}"
        ),
        process=process,
        fix_suggestion="Scale down, split part, or use a larger machine.",
        citation=parse_citation(cite),
    )]


# ──────────────────────────────────────────────────────────────
# Aspect ratio
# ──────────────────────────────────────────────────────────────
def check_aspect_ratio(
    ctx: GeometryContext,
    max_ratio: float,
    process: ProcessType,
) -> list[Issue]:
    dims = sorted(ctx.info.bounding_box.dimensions)
    if dims[0] < 0.1:
        return []
    ratio = dims[2] / dims[0]
    if ratio <= max_ratio:
        return []
    return [Issue(
        code="EXTREME_ASPECT_RATIO",
        measurement_unit="ratio",
        severity=Severity.WARNING,
        message=(
            f"Aspect ratio {format_measurement(ratio, max_ratio)}:1 exceeds {max_ratio}:1 for "
            f"{process.value}. Tall/thin parts risk failure."
        ),
        process=process,
        measured_value=ratio,
        required_value=max_ratio,
        fix_suggestion="Split into segments, add bracing, or reorient.",
    )]


# ──────────────────────────────────────────────────────────────
# Trapped volumes / powder escape
# ──────────────────────────────────────────────────────────────
def check_trapped_volumes(
    ctx: GeometryContext,
    process: ProcessType,
    *,
    min_drain_mm: float = 3.5,
    cite: str = "",
) -> list[Issue]:
    """Detect fully enclosed cavities (trapped powder/resin)."""
    issues: list[Issue] = []
    try:
        # A cavity connected through an undersized drain is one watertight shell,
        # so component containment alone cannot see it. Reuse the feature pass to
        # identify a measured cylindrical opening, then prove that one end opens
        # to the exterior while the other opens into a void materially wider than
        # the bore. This deliberately refuses to infer from a small blind hole.
        undersized = _undersized_cavity_drain(ctx, min_drain_mm)
        if undersized is not None:
            diameter, cavity_center, affected_faces = undersized
            issues.append(Issue(
                code="TRAPPED_VOLUME",
                measurement_unit="mm",
                severity=Severity.ERROR,
                message=(
                    f"Drain opening {format_measurement(diameter, min_drain_mm)}mm is below the {min_drain_mm}mm "
                    f"minimum for {process.value}; material can remain trapped."
                ),
                process=process,
                affected_faces=affected_faces,
                region_center=cavity_center,
                measured_value=diameter,
                required_value=min_drain_mm,
                fix_suggestion=(
                    f"Enlarge drain holes to >= {min_drain_mm}mm diameter. {cite}"
                ),
                citation=parse_citation(cite),
            ))

        if len(ctx.bodies) <= 1:
            return issues
        main_index = max(range(len(ctx.bodies)), key=ctx.body_volumes.__getitem__)
        main = ctx.bodies[main_index]
        if ctx.body_volumes[main_index] <= 0:
            return issues
        for index, sub in enumerate(ctx.bodies):
            sub_volume = ctx.body_volumes[index]
            if index == main_index or sub_volume <= 0:
                continue
            center = sub.centroid
            if main.is_watertight and main.contains([center])[0]:
                issues.append(Issue(
                    code="TRAPPED_VOLUME",
                    severity=Severity.ERROR,
                    message=(
                        f"Internal cavity ({sub_volume:.0f}mm³) traps material "
                        f"in {process.value}. Needs >= {min_drain_mm}mm drain holes."
                    ),
                    process=process,
                    region_center=tuple(float(v) for v in center),
                    fix_suggestion=(
                        f"Add drain holes >= {min_drain_mm}mm diameter. {cite}"
                    ),
                    citation=parse_citation(cite),
                ))
    except Exception:
        logger.warning(
            "check_trapped_volumes containment test failed for %s",
            process.value,
            exc_info=True,
        )
        issues.append(Issue(
            code="ANALYSIS_PARTIAL",
            severity=Severity.INFO,
            message=(
                f"Trapped-volume check incomplete for {process.value} "
                f"(geometry/containment error)."
            ),
            process=process,
            fix_suggestion="Verify mesh integrity via /validate/quick.",
        ))
    return issues


def _undersized_cavity_drain(
    ctx: GeometryContext,
    min_drain_mm: float,
) -> tuple[float, tuple[float, float, float], list[int]] | None:
    """Return measured proof of a too-small drain into a wider internal void."""
    from src.analysis.features.base import FeatureKind

    mesh = ctx.mesh
    if not mesh.is_watertight or min_drain_mm <= 0:
        return None
    for feature in ctx.features:
        if (
            feature.kind != FeatureKind.CYLINDER_HOLE
            or feature.radius is None
            or feature.depth is None
            or feature.axis is None
            or feature.radius <= 0
            or feature.depth <= 0
        ):
            continue
        diameter = 2.0 * float(feature.radius)
        if diameter >= min_drain_mm:
            continue
        axis = np.asarray(feature.axis, dtype=np.float64)
        center = np.asarray(feature.centroid, dtype=np.float64)
        if not np.isfinite(axis).all() or not np.isfinite(center).all():
            continue
        axis_norm = float(np.linalg.norm(axis))
        if axis_norm <= 1e-9:
            continue
        axis /= axis_norm
        probe = max(ctx.scale_eps, min(float(feature.radius) * 0.1, 0.1))
        endpoints = [
            center - axis * (float(feature.depth) / 2.0 + probe),
            center + axis * (float(feature.depth) / 2.0 + probe),
        ]
        outward_clear: list[bool] = []
        axial_hit_distance: list[float | None] = []
        for index, endpoint in enumerate(endpoints):
            direction = axis * (-1.0 if index == 0 else 1.0)
            try:
                locations, _, _ = mesh.ray.intersects_location(
                    [endpoint], [direction], multiple_hits=False
                )
            except Exception:
                outward_clear.append(False)
                axial_hit_distance.append(None)
                continue
            outward_clear.append(len(locations) == 0)
            axial_hit_distance.append(
                None if len(locations) == 0 else float(np.linalg.norm(locations[0] - endpoint))
            )
        if outward_clear.count(True) != 1:
            continue
        cavity_index = 1 - outward_clear.index(True)
        cavity_point = endpoints[cavity_index]
        axial_distance = axial_hit_distance[cavity_index]
        if axial_distance is None or axial_distance <= max(diameter, float(feature.depth)):
            continue
        try:
            if bool(mesh.contains([cavity_point])[0]):
                continue
        except Exception:
            continue

        # A blind bore ends in solid at its inner endpoint. A drain enters a
        # cavity whose local void is wider than the bore in perpendicular axes.
        basis = np.array([1.0, 0.0, 0.0])
        if abs(float(np.dot(basis, axis))) > 0.9:
            basis = np.array([0.0, 1.0, 0.0])
        u = np.cross(axis, basis)
        u /= np.linalg.norm(u)
        v = np.cross(axis, u)
        radial_distances: list[float] = []
        try:
            for direction in (u, -u, v, -v):
                locations, _, _ = mesh.ray.intersects_location(
                    [cavity_point], [direction], multiple_hits=False
                )
                if len(locations) == 0:
                    break
                radial_distances.append(float(np.linalg.norm(locations[0] - cavity_point)))
        except Exception:
            continue
        if len(radial_distances) != 4 or min(radial_distances) <= diameter:
            continue
        return (
            diameter,
            (
                float(cavity_point[0]),
                float(cavity_point[1]),
                float(cavity_point[2]),
            ),
            [int(index) for index in feature.face_indices],
        )
    return None


# ──────────────────────────────────────────────────────────────
# Draft angles (molding / casting / forging)
# ──────────────────────────────────────────────────────────────
def check_draft_angles(
    ctx: GeometryContext,
    min_draft_deg: float,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    """Check sidewall faces for sufficient draft relative to Z pull."""
    normals = ctx.normals
    areas = ctx.face_areas
    # Sidewalls: faces roughly perpendicular to Z (80–100° from Z-up)
    sidewall_mask = (ctx.angles_from_up_deg > 80) & (ctx.angles_from_up_deg < 100)
    sidewall_faces = np.where(sidewall_mask)[0]
    if len(sidewall_faces) == 0:
        return []
    # Draft = |90 - angle_from_z|
    draft = np.abs(90.0 - ctx.angles_from_up_deg[sidewall_faces])
    no_draft = draft < min_draft_deg
    no_draft_faces = sidewall_faces[no_draft]
    if len(no_draft_faces) == 0:
        return []
    no_draft_area = float(areas[no_draft_faces].sum())
    total_sidewall_area = float(areas[sidewall_faces].sum())
    pct = no_draft_area / max(total_sidewall_area, 1e-9) * 100
    return [Issue(
        code="INSUFFICIENT_DRAFT",
        measurement_unit="deg",
        severity=Severity.ERROR,
        message=(
            f"{len(no_draft_faces)} sidewall faces ({pct:.1f}% of sidewall area) "
            f"below {min_draft_deg}° draft for {process.value}."
        ),
        process=process,
        affected_faces=no_draft_faces.tolist(),
        required_value=min_draft_deg,
        fix_suggestion=(
            f"Add >= {min_draft_deg}° draft to all walls in pull direction. {cite}"
        ),
        citation=parse_citation(cite),
    )]


# ──────────────────────────────────────────────────────────────
# Wall uniformity (molding / casting)
# ──────────────────────────────────────────────────────────────
def check_wall_uniformity(
    ctx: GeometryContext,
    min_wall: float,
    max_wall: float,
    ideal_wall: float,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    issues = _wall_precision_issues(ctx, process)
    wt = ctx.wall_thickness
    upper = _wall_upper(ctx)
    t_min_upper = float(upper.min()) if len(upper) else float("inf")
    t_min = float(wt[np.argmin(upper)]) if np.isfinite(t_min_upper) else float("inf")
    t_max = ctx.maximum_inscribed_diameter
    tolerance = wall_thickness_tolerance(ctx.mesh, ctx.scale_eps)

    if t_min_upper < min_wall - tolerance:
        issues.append(Issue(
            code="THIN_WALL_MOLDING",
            measurement_unit="mm",
            severity=Severity.ERROR,
            message=f"Min wall {format_measurement(t_min, min_wall)}mm < {min_wall}mm for {process.value}.",
            process=process,
            measured_value=t_min,
            required_value=min_wall,
            fix_suggestion=f"Increase to >= {min_wall}mm. {cite}",
            citation=parse_citation(cite),
        ))
    if t_max is None or not np.isfinite(t_min):
        missing = "Maximum" if t_max is None else "Minimum"
        if t_max is None and not np.isfinite(t_min):
            missing = "Minimum and maximum"
        issues.append(Issue(
            code="WALL_UNIFORMITY_UNAVAILABLE",
            severity=Severity.WARNING,
            message=f"{missing} wall thickness and uniformity could not be verified.",
            process=process,
            fix_suggestion="Check wall sections in the source CAD before manufacturing.",
        ))
        if t_max is None:
            return issues
    issues.append(Issue(
        code="WALL_UNIFORMITY_SAMPLED",
        measurement_unit="mm",
        severity=Severity.WARNING,
        message=(
            f"Largest sampled interior section: {t_max:.6g}mm. "
            "Thickness uses interior clearances; unsampled sections may be thicker."
        ),
        process=process,
        measured_value=t_max,
        fix_suggestion="Confirm critical wall sections in the source CAD.",
    ))
    # The observed interior point remains inside only when its clearance is
    # larger than source rounding. This bounds this witness, not global maxima.
    diameter_error = 2 * float(ctx.mesh.metadata.get("coordinate_error", 0.0))
    if (ctx.metadata.get("decimation", {}).get("succeeded") or t_max <= diameter_error):
        diameter_error = float("inf")
    t_max_lower = t_max - diameter_error
    if t_max_lower > max_wall + tolerance:
        issues.append(Issue(
            code="THICK_WALL",
            measurement_unit="mm",
            severity=Severity.WARNING,
            message=f"Sampled thick section {format_measurement(t_max, max_wall)}mm > {max_wall}mm — sink marks / long cycle risk.",
            process=process,
            measured_value=t_max,
            required_value=max_wall,
            fix_suggestion=f"Core out thick sections. Target {ideal_wall}mm. {cite}",
            citation=parse_citation(cite),
        ))
    if t_max > 0 and np.isfinite(t_min) and t_min > 0 and t_max_lower > 2.0 * t_min_upper + 3.0 * tolerance:
        issues.append(Issue(
            code="NON_UNIFORM_WALLS",
            measurement_unit="ratio",
            severity=Severity.WARNING,
            message=(
                f"Sampled wall ratio {format_measurement(t_max / t_min, 2.0)}:1 ({format_measurement(t_min)}–{format_measurement(t_max)}mm) "
                f"may increase warping risk in {process.value}."
            ),
            process=process,
            measured_value=t_max / t_min,
            required_value=2.0,
            fix_suggestion=f"Aim for uniform {ideal_wall}mm. Use ribs, not solid. {cite}",
            citation=parse_citation(cite),
        ))
    return issues


# ──────────────────────────────────────────────────────────────
# Undercuts (CNC / molding)
# ──────────────────────────────────────────────────────────────
def check_setup_access(
    ctx: GeometryContext,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    """Find geometry without re-entrant surfaces; otherwise request setup review."""
    if ctx.undercut_free_geometry:
        return []
    faces = np.empty(0, dtype=int)
    if len(ctx.mesh.faces) and not ctx.metadata.get("decimation", {}).get("succeeded"):
        tol = wall_thickness_tolerance(ctx.mesh, ctx.scale_eps)
        z = ctx.mesh.vertices[:, 2]
        base = np.all(z[ctx.mesh.faces] <= z.min() + tol, axis=1)
        faces = np.where((ctx.normals[:, 2] < -1e-7) & ~base)[0]
    return [Issue(
        code="SETUP_ACCESS_UNVERIFIED",
        severity=Severity.WARNING,
        message=(
            "A setup without re-entrant surfaces could not be verified from this mesh. "
            + (f"{len(faces)} mesh faces point away from file +Z above its base. " if len(faces) else "")
            + "Part orientation and the actual tooling may change access."
        ),
        process=process,
        affected_faces=faces.tolist(),
        fix_suggestion=f"Review setup direction, fixturing/tooling and clearance. {cite}".strip(),
        citation=parse_citation(cite),
    )]


# ──────────────────────────────────────────────────────────────
# Undercuts (molding-specific: top half + bottom half)
# ──────────────────────────────────────────────────────────────
def check_undercuts_molding(
    ctx: GeometryContext,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    mid_z = (ctx.info.bounding_box.min_z + ctx.info.bounding_box.max_z) / 2
    upper = ctx.centroids[:, 2] > mid_z
    lower = ~upper
    uc_upper = upper & (ctx.normals[:, 2] < -0.3)
    uc_lower = lower & (ctx.normals[:, 2] > 0.3)
    uc_faces = np.where(uc_upper | uc_lower)[0]
    if len(uc_faces) == 0:
        return []
    return [Issue(
        code="UNDERCUT_MOLDING",
        severity=Severity.WARNING,
        message=(
            f"{len(uc_faces)} faces form undercuts requiring side actions "
            f"in {process.value} tooling."
        ),
        process=process,
        affected_faces=uc_faces.tolist(),
        fix_suggestion=f"Redesign to eliminate undercuts or add slides. {cite}",
        citation=parse_citation(cite),
    )]


# ──────────────────────────────────────────────────────────────
# Internal corner radii (CNC)
# ──────────────────────────────────────────────────────────────
def check_internal_radii(
    ctx: GeometryContext,
    min_radius_mm: float,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    """Flag sharp concave edges that tools can't reach."""
    if len(ctx.concave_mask) == 0 or len(ctx.dihedral_angles_rad) == 0:
        return []
    sharp = ctx.concave_mask & (ctx.dihedral_angles_rad > np.radians(30))
    sharp_count = int(np.sum(sharp))
    if sharp_count < 10:
        return []
    return [Issue(
        code="SHARP_INTERNAL_CORNERS",
        measurement_unit="mm",
        severity=Severity.WARNING,
        message=(
            f"{sharp_count} sharp concave edges — tool radius {min_radius_mm}mm "
            f"cannot reach. Applies to {process.value}."
        ),
        process=process,
        required_value=min_radius_mm,
        fix_suggestion=f"Add fillets >= {min_radius_mm}mm to internal corners. {cite}",
        citation=parse_citation(cite),
    )]


# ──────────────────────────────────────────────────────────────
# Fixture / datum surfaces (CNC)
# ──────────────────────────────────────────────────────────────
def check_fixture_surfaces(
    ctx: GeometryContext,
    min_flat_pct: float,
    process: ProcessType,
) -> list[Issue]:
    if len(ctx.facet_groups) == 0:
        return []
    flat_area = sum(float(ctx.face_areas[fg].sum()) for fg in ctx.facet_groups)
    total_area = float(ctx.info.surface_area) or 1.0
    flat_pct = flat_area / total_area * 100
    if flat_pct >= min_flat_pct:
        return []
    return [Issue(
        code="NO_FIXTURE_SURFACES",
        severity=Severity.WARNING,
        message=f"Only {flat_pct:.1f}% flat area — hard to fixture for {process.value}.",
        process=process,
        fix_suggestion="Add flat datum surfaces or plan custom fixtures.",
    )]


# ──────────────────────────────────────────────────────────────
# Concave edge fillets (casting)
# ──────────────────────────────────────────────────────────────
def check_fillet_requirements(
    ctx: GeometryContext,
    min_fillet_mm: float,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    if len(ctx.dihedral_angles_rad) == 0:
        return []
    # An "internal corner" is a CONCAVE sharp edge — convex edges (a box's
    # outer corners) and coplanar seams need no fillet for material flow.
    # trimesh stores the angle BETWEEN normals: 0 is smooth/coplanar, not
    # a sharp interior angle. An interior angle below 120° turns normals >60°.
    sharp = (ctx.dihedral_angles_rad > np.radians(60)) & ctx.concave_mask
    count = int(np.sum(sharp))
    if count == 0:
        return []
    return [Issue(
        code="MISSING_FILLETS",
        measurement_unit="mm",
        severity=Severity.WARNING,
        message=(
            f"{count} sharp concave mesh edges need >= {min_fillet_mm}mm fillets "
            f"for {process.value} flow and stress distribution."
        ),
        process=process,
        required_value=min_fillet_mm,
        fix_suggestion=f"Add {min_fillet_mm}mm+ fillets. {cite}",
        citation=parse_citation(cite),
    )]


# ──────────────────────────────────────────────────────────────
# Shrinkage / bulk (casting)
# ──────────────────────────────────────────────────────────────
def check_shrinkage_risk(
    ctx: GeometryContext,
    process: ProcessType,
    *,
    max_compactness: float = 15.0,
) -> list[Issue]:
    vol = ctx.info.volume
    sa = ctx.info.surface_area
    if vol <= 0 or sa <= 0:
        return []
    compactness = vol / sa
    if compactness <= max_compactness:
        return []
    return [Issue(
        code="SHRINKAGE_RISK",
        measurement_unit="mm",
        severity=Severity.WARNING,
        message=(
            f"V/SA ratio {format_measurement(compactness, max_compactness)}mm — bulky sections cause shrinkage "
            f"porosity in {process.value}."
        ),
        process=process,
        measured_value=compactness,
        fix_suggestion="Core out thick sections for even cooling.",
    )]


# ──────────────────────────────────────────────────────────────
# Residual stress risk (metal AM)
# ──────────────────────────────────────────────────────────────
def check_residual_stress(
    ctx: GeometryContext,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    """Large flat sections parallel to build plate → curl risk."""
    if len(ctx.facet_groups) == 0:
        return []
    total = float(ctx.info.surface_area) or 1.0
    for fg in ctx.facet_groups:
        area = float(ctx.face_areas[fg].sum())
        if area / total < 0.15:
            continue
        avg_normal = ctx.normals[fg].mean(axis=0)
        if abs(avg_normal[2]) > 0.95:  # nearly horizontal
            return [Issue(
                code="RESIDUAL_STRESS_RISK",
                severity=Severity.WARNING,
                message=(
                    f"Large horizontal surface ({area:.0f}mm², "
                    f"{area / total * 100:.0f}% of total) — curl risk in {process.value}."
                ),
                process=process,
                fix_suggestion=f"Add breakup features or reorient. HIP recommended. {cite}",
                citation=parse_citation(cite),
            )]
    return []


# ──────────────────────────────────────────────────────────────
# Rotational symmetry (CNC turning)
# ──────────────────────────────────────────────────────────────
def check_rotational_symmetry(
    ctx: GeometryContext,
    process: ProcessType,
    *,
    tolerance: float = 0.10,
) -> list[Issue]:
    """Part must be roughly rotationally symmetric for turning."""
    # Trimesh's inertia calculation derives mass properties and divides by
    # signed volume. Open or zero-volume meshes have already failed the
    # universal solid-geometry gate; asking for inertia here adds no truthful
    # signal and can emit divide-by-zero RuntimeWarnings plus a noisy traceback.
    if not ctx.info.is_watertight or not np.isfinite(ctx.info.volume) or ctx.info.volume <= 0:
        return []
    try:
        inertia = ctx.mesh.moment_inertia
        eig = np.linalg.eigvalsh(inertia)
        eig = np.sort(eig)
        if eig[0] <= 0:
            return []
        # Two eigenvalues should be approximately equal for rotational symmetry
        ratio_01 = eig[0] / eig[1] if eig[1] > 0 else 0
        ratio_12 = eig[1] / eig[2] if eig[2] > 0 else 0
        is_symmetric = (
            (abs(1.0 - ratio_01) < tolerance)
            or (abs(1.0 - ratio_12) < tolerance)
        ) and has_rotational_surface_evidence(ctx.features, ctx.info.surface_area, mesh=ctx.mesh)
        if not is_symmetric:
            return [Issue(
                code="NOT_ROTATIONALLY_SYMMETRIC",
                severity=Severity.ERROR,
                message=(
                    f"Part lacks positive rotational geometry (eigenvalue ratios: "
                    f"{ratio_01:.2f}, {ratio_12:.2f}; insufficient outer rotational "
                    f"surface evidence). Required for {process.value}."
                ),
                process=process,
                fix_suggestion="CNC turning requires axially symmetric geometry. Use mill-turn or 3/5-axis CNC.",
            )]
    except Exception:
        logger.warning(
            "check_rotational_symmetry eigen analysis failed for %s",
            process.value,
            exc_info=True,
        )
        return [Issue(
            code="ANALYSIS_PARTIAL",
            severity=Severity.INFO,
            message=(
                f"Rotational-symmetry check incomplete for {process.value} "
                f"(eigen decomposition failed)."
            ),
            process=process,
            fix_suggestion="Verify mesh integrity via /validate/quick.",
        )]
    return []


# ──────────────────────────────────────────────────────────────
# L/D ratio (CNC turning)
# ──────────────────────────────────────────────────────────────
def check_length_diameter_ratio(
    ctx: GeometryContext,
    max_ld: float,
    process: ProcessType,
) -> list[Issue]:
    dims = sorted(ctx.info.bounding_box.dimensions)
    # For turning: length = longest, diameter = second longest
    if dims[0] < 0.1 or dims[1] < 0.1:
        return []
    length = dims[2]
    diameter = dims[1]
    measured = turning_dimensions(ctx.mesh, ctx.features)
    if measured is not None:
        length, diameter, _ = measured
    ld = length / diameter
    if ld <= max_ld:
        return []
    return [Issue(
        code="HIGH_LD_RATIO",
        measurement_unit="ratio",
        severity=Severity.WARNING,
        message=(
            f"L/D ratio {format_measurement(ld, max_ld)}:1 exceeds {max_ld}:1 — deflection risk "
            f"on {process.value}. Steady rest recommended."
        ),
        process=process,
        measured_value=ld,
        required_value=max_ld,
        fix_suggestion="Reduce L/D or plan steady rest / tailstock support.",
    )]


# ──────────────────────────────────────────────────────────────
# Straight-profile check (wire EDM)
# ──────────────────────────────────────────────────────────────
def check_prismatic(
    ctx: GeometryContext,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    """Confirm a straight extrusion; other wire paths require setup review."""
    measured = ctx.straight_profile_geometry
    if measured is not None and measured[2] == 0:
        return []
    return [Issue(
        code="PRISMATIC_PROFILE_PRECISION" if measured is not None else "PRISMATIC_PROFILE_UNVERIFIED",
        severity=Severity.WARNING,
        message=(
            "A straight extrusion is consistent with the mesh within source-coordinate rounding; "
            "confirm the exact wire profile in the source CAD."
            if measured is not None else
            "A constant straight extrusion could not be verified. "
            "Tapered or multi-axis wire EDM may be possible and requires setup review."
        ),
        process=process,
        fix_suggestion=f"Review the CAM wire path, threading access, taper, fixturing and required setups. {cite}".strip(),
        citation=parse_citation(cite),
    )]


# ──────────────────────────────────────────────────────────────
# Sheet metal thickness (single gauge)
# ──────────────────────────────────────────────────────────────
def check_sheet_gauge(
    ctx: GeometryContext,
    process: ProcessType,
) -> list[Issue]:
    issues: list[Issue] = []
    dims = ctx.flat_sheet_dimensions
    if dims is None:
        return [Issue(
            code="SHEET_GAUGE_UNVERIFIED", severity=Severity.WARNING,
            message="A constant flat-sheet gauge could not be verified from this geometry.",
            process=process,
            fix_suggestion="Confirm material thickness and provide a flat pattern for bent or nonuniform parts; the overall envelope is not a sheet gauge.",
        )]
    t = dims[0]
    precision = ctx.sheet_precision
    tolerance = wall_thickness_tolerance(ctx.mesh, ctx.scale_eps) + precision
    if precision:
        issues.append(Issue(
            code="SHEET_GAUGE_PRECISION", severity=Severity.WARNING,
            measurement_unit="mm", measured_value=t, process=process,
            message=f"Estimated sheet gauge {t:.6g}mm has up to ±{precision:.3g}mm uncertainty from binary STL coordinate rounding.",
            fix_suggestion="Confirm thickness in the source CAD, especially near a stock or machine limit. Export STEP for more precise sheet measurements.",
        ))
    if t < SHEET_GAUGE_MIN_MM - tolerance:
        issues.append(Issue(
            code="TOO_THIN_SHEET", severity=Severity.ERROR,
            measurement_unit="mm",
            message=f"Thickness {format_measurement(t, SHEET_GAUGE_MIN_MM)}mm below the default {SHEET_GAUGE_MIN_MM:g}mm minimum sheet gauge.",
            process=process, measured_value=t, required_value=SHEET_GAUGE_MIN_MM,
            fix_suggestion=f"Use >= {SHEET_GAUGE_MIN_MM:g}mm for default sheet profiles; confirm material-specific stock and machine limits.",
        ))
    elif t > SHEET_GAUGE_MAX_MM + tolerance:
        issues.append(Issue(
            code="TOO_THICK_SHEET", severity=Severity.WARNING,
            measurement_unit="mm",
            message=f"Thickness {format_measurement(t, SHEET_GAUGE_MAX_MM)}mm exceeds the default {SHEET_GAUGE_MAX_MM:g}mm maximum sheet gauge.",
            process=process, measured_value=t, required_value=SHEET_GAUGE_MAX_MM,
            fix_suggestion="Confirm stock and machine capacity for this thickness, or consider plate machining.",
        ))
    closest = min(STANDARD_GAUGES, key=lambda g: abs(g - t))
    if (
        abs(closest - t) > 0.1 + tolerance
        and SHEET_GAUGE_MIN_MM - tolerance <= t <= SHEET_GAUGE_MAX_MM + tolerance
    ):
        issues.append(Issue(
            code="NON_STANDARD_GAUGE", severity=Severity.INFO,
            measurement_unit="mm",
            message=f"Thickness {format_measurement(t, closest)}mm is not in the default stock list; nearest listed gauge: {closest:g}mm.",
            process=process, measured_value=t,
            fix_suggestion=f"Confirm supplier stock; {closest:g}mm is the nearest gauge in the default catalog.",
        ))
    return issues


# ──────────────────────────────────────────────────────────────
# Bend feasibility (sheet metal)
# ──────────────────────────────────────────────────────────────
def check_bends(
    ctx: GeometryContext,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    """Flag bends too tight to form (radius < thickness ~ a knife-edge fold).

    ``ctx.dihedral_angles_rad`` is the angle BETWEEN ADJACENT FACE NORMALS:
        0 rad   -> coplanar (a FLAT region, NOT a bend)
        pi/2    -> a clean 90 deg sheet-metal bend (manufacturable)
        ->pi    -> the sheet folds back on itself (included angle -> 0, a
                   knife-edge: unmanufacturable as a single air bend)

    The previous threshold ``< 90 deg`` was inverted: it flagged every flat,
    coplanar facet pair (angle ~0) as a "sharp bend", which hard-failed sheet
    metal on EVERY part that has a flat face — i.e. every part. A real DFM
    violation is a fold so tight the radius drops below the gauge, which shows
    up as a normal-divergence ABOVE ~150 deg (included bend angle < 30 deg).
    Flat blanks (0 deg) and normal 90 deg bends now pass, as they must.
    """
    if len(ctx.dihedral_angles_rad) == 0:
        return []
    knife = ctx.dihedral_angles_rad > np.radians(150)
    count = int(np.sum(knife))
    if count == 0:
        return []
    tightest_deg = float(np.degrees(ctx.dihedral_angles_rad[knife].max()))
    return [Issue(
        code="SHARP_BEND", severity=Severity.ERROR,
        measurement_unit="deg",
        message=(
            f"{count} knife-edge folds (normal divergence up to {format_measurement(tightest_deg, 150.0)}° "
            f"≈ included bend angle < 30°) — bend radius must be >= material "
            f"thickness. DIN 6935."
        ),
        process=process,
        measured_value=tightest_deg,
        fix_suggestion=f"Increase bend radius to >= 1x material thickness. {cite}",
        citation=parse_citation(cite),
    )]


# ──────────────────────────────────────────────────────────────
# Core feasibility (sand casting)
# ──────────────────────────────────────────────────────────────
def check_core_feasibility(
    ctx: GeometryContext,
    process: ProcessType,
) -> list[Issue]:
    issues: list[Issue] = []
    if len(ctx.bodies) <= 1:
        return issues
    try:
        main_index = max(range(len(ctx.bodies)), key=ctx.body_volumes.__getitem__)
        main = ctx.bodies[main_index]
        if ctx.body_volumes[main_index] <= 0:
            return issues
        for index, sub in enumerate(ctx.bodies):
            if index == main_index or ctx.body_volumes[index] <= 0:
                continue
            center = sub.centroid
            if main.is_watertight and main.contains([center])[0]:
                dims = sorted(sub.extents)
                if dims[0] > 0 and dims[2] / dims[0] > 6:
                    issues.append(Issue(
                        code="FRAGILE_CORE", severity=Severity.WARNING,
                        message=(
                            f"Core aspect ratio {dims[2] / dims[0]:.1f}:1 "
                            f"— may break during {process.value}."
                        ),
                        process=process,
                        region_center=tuple(float(v) for v in center),
                        fix_suggestion="Reduce core aspect ratio below 4:1.",
                    ))
    except Exception:
        logger.warning(
            "check_core_feasibility containment test failed for %s",
            process.value,
            exc_info=True,
        )
        issues.append(Issue(
            code="ANALYSIS_PARTIAL",
            severity=Severity.INFO,
            message=(
                f"Core feasibility check incomplete for {process.value} "
                f"(watertightness/containment error)."
            ),
            process=process,
            fix_suggestion="Verify mesh integrity via /validate/quick.",
        ))
    return issues


# ──────────────────────────────────────────────────────────────
# Hole depth-to-diameter (CNC / additive)
# ──────────────────────────────────────────────────────────────
def check_hole_depth_ratio(
    ctx: GeometryContext,
    max_ratio: float,
    process: ProcessType,
) -> list[Issue]:
    issues: list[Issue] = []
    for f in ctx.features:
        if f.kind != FeatureKind.CYLINDER_HOLE:
            continue
        if f.radius is None or f.depth is None or f.radius <= 0:
            continue
        diameter = f.radius * 2
        ratio = f.depth / diameter
        if ratio > max_ratio:
            issues.append(Issue(
                code="DEEP_HOLE",
                measurement_unit="ratio",
                severity=Severity.WARNING,
                message=(
                    f"Hole depth/diameter {format_measurement(ratio, max_ratio)}:1 exceeds {max_ratio}:1 "
                    f"for {process.value} at ({f.centroid[0]:.0f}, {f.centroid[1]:.0f}, {f.centroid[2]:.0f})."
                ),
                process=process,
                measured_value=ratio,
                required_value=max_ratio,
                region_center=f.centroid,
                fix_suggestion="Reduce depth, widen hole, or use specialized tooling.",
            ))
    return issues


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _region_center(ctx: GeometryContext, face_indices: np.ndarray) -> Optional[tuple[float, float, float]]:
    if len(face_indices) == 0:
        return None
    sample = face_indices[:50]
    c = ctx.centroids[sample].mean(axis=0)
    return (float(c[0]), float(c[1]), float(c[2]))
