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

from src.analysis.constants import STANDARD_GAUGES
from src.analysis.context import GeometryContext
from src.analysis.features.base import Feature, FeatureKind
from src.analysis.models import Issue, ProcessType, Severity

logger = logging.getLogger("cadverify.checks")


# ──────────────────────────────────────────────────────────────
# Wall thickness
# ──────────────────────────────────────────────────────────────
def check_wall_thickness(
    ctx: GeometryContext,
    min_wall_mm: float,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    wt = ctx.wall_thickness
    finite = np.isfinite(wt)
    thin = finite & (wt < min_wall_mm)
    thin_faces = np.where(thin)[0]
    if len(thin_faces) == 0:
        return []
    pct = len(thin_faces) / max(len(ctx.centroids), 1) * 100
    min_measured = float(wt[thin].min())
    region = _region_center(ctx, thin_faces)
    sev = Severity.ERROR if pct > 10 else Severity.WARNING
    return [Issue(
        code="THIN_WALL",
        severity=sev,
        message=(
            f"{len(thin_faces)} faces ({pct:.1f}%) below {min_wall_mm}mm "
            f"min wall for {process.value}. Thinnest: {min_measured:.2f}mm."
        ),
        process=process,
        affected_faces=thin_faces[:100].tolist(),
        region_center=region,
        measured_value=min_measured,
        required_value=min_wall_mm,
        fix_suggestion=f"Increase wall thickness to >= {min_wall_mm}mm. {cite}",
    )]


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
        affected_faces=oh_faces[:100].tolist(),
        region_center=region,
        fix_suggestion=(
            f"Reorient part or redesign overhangs < {max_angle_deg}° "
            f"for {process.value}. {cite}"
        ),
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
    if len(ctx.edge_lengths) == 0:
        return []
    small = ctx.edge_lengths[ctx.edge_lengths < min_size_mm]
    if len(small) == 0:
        return []
    pct = len(small) / len(ctx.edge_lengths) * 100
    if pct < 5:
        return []  # not significant
    smallest = float(small.min())
    return [Issue(
        code="SMALL_FEATURES",
        severity=Severity.WARNING,
        message=(
            f"{len(small)} edges ({pct:.1f}%) below {min_size_mm}mm "
            f"resolution for {process.value}. Smallest: {smallest:.3f}mm."
        ),
        process=process,
        measured_value=smallest,
        required_value=min_size_mm,
        fix_suggestion=f"Enlarge features to >= {min_size_mm}mm. {cite}",
    )]


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
    exceeds = []
    for dim, limit, axis in zip(dims, max_dims_mm, ("X", "Y", "Z")):
        if dim > limit:
            exceeds.append(f"{axis}: {dim:.0f}mm > {limit}mm")
    if not exceeds:
        return []
    return [Issue(
        code="EXCEEDS_BUILD_VOLUME",
        severity=Severity.ERROR,
        message=(
            f"Part exceeds build envelope for {process.value}: "
            + ", ".join(exceeds) + f". {cite}"
        ),
        process=process,
        fix_suggestion="Scale down, split part, or use a larger machine.",
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
        severity=Severity.WARNING,
        message=(
            f"Aspect ratio {ratio:.1f}:1 exceeds {max_ratio}:1 for "
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
    if len(ctx.bodies) <= 1:
        return issues
    try:
        main = max(ctx.bodies, key=lambda m: m.volume if m.is_watertight else 0)
        for sub in ctx.bodies:
            if sub is main or not sub.is_watertight:
                continue
            center = sub.centroid
            if main.is_watertight and main.contains([center])[0]:
                issues.append(Issue(
                    code="TRAPPED_VOLUME",
                    severity=Severity.ERROR,
                    message=(
                        f"Internal cavity ({sub.volume:.0f}mm³) traps material "
                        f"in {process.value}. Needs >= {min_drain_mm}mm drain holes."
                    ),
                    process=process,
                    region_center=tuple(float(v) for v in center),
                    fix_suggestion=(
                        f"Add drain holes >= {min_drain_mm}mm diameter. {cite}"
                    ),
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
        severity=Severity.ERROR,
        message=(
            f"{len(no_draft_faces)} sidewall faces ({pct:.1f}% of sidewall area) "
            f"below {min_draft_deg}° draft for {process.value}."
        ),
        process=process,
        affected_faces=no_draft_faces[:100].tolist(),
        required_value=min_draft_deg,
        fix_suggestion=(
            f"Add >= {min_draft_deg}° draft to all walls in pull direction. {cite}"
        ),
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
    issues: list[Issue] = []
    wt = ctx.wall_thickness
    finite_mask = np.isfinite(wt)
    if not np.any(finite_mask):
        return issues
    t = wt[finite_mask]
    t_min, t_max = float(t.min()), float(t.max())

    if t_min < min_wall:
        issues.append(Issue(
            code="THIN_WALL_MOLDING",
            severity=Severity.ERROR,
            message=f"Min wall {t_min:.2f}mm < {min_wall}mm for {process.value}.",
            process=process,
            measured_value=t_min,
            required_value=min_wall,
            fix_suggestion=f"Increase to >= {min_wall}mm. {cite}",
        ))
    if t_max > max_wall:
        issues.append(Issue(
            code="THICK_WALL",
            severity=Severity.WARNING,
            message=f"Max wall {t_max:.1f}mm > {max_wall}mm — sink marks / long cycle.",
            process=process,
            measured_value=t_max,
            required_value=max_wall,
            fix_suggestion=f"Core out thick sections. Target {ideal_wall}mm. {cite}",
        ))
    if t_max > 0 and t_min > 0 and (t_max / t_min) > 2.0:
        issues.append(Issue(
            code="NON_UNIFORM_WALLS",
            severity=Severity.WARNING,
            message=(
                f"Wall ratio {t_max / t_min:.1f}:1 ({t_min:.1f}–{t_max:.1f}mm) "
                f"causes warping in {process.value}."
            ),
            process=process,
            measured_value=t_max / t_min,
            required_value=2.0,
            fix_suggestion=f"Aim for uniform {ideal_wall}mm. Use ribs, not solid. {cite}",
        ))
    return issues


# ──────────────────────────────────────────────────────────────
# Undercuts (CNC / molding)
# ──────────────────────────────────────────────────────────────
def check_undercuts_from_z(
    ctx: GeometryContext,
    process: ProcessType,
    *,
    severity: Severity = Severity.ERROR,
    cite: str = "",
) -> list[Issue]:
    """Faces unreachable from +Z direction (3-axis CNC, mold pull)."""
    bottom_z = float(ctx.info.bounding_box.min_z)
    height = float(ctx.info.bounding_box.max_z - bottom_z)
    margin = height * 0.05

    downward = ctx.normals[:, 2] < -0.1
    not_bottom = ctx.centroids[:, 2] > (bottom_z + margin)
    undercut_mask = downward & not_bottom
    uc_faces = np.where(undercut_mask)[0]
    if len(uc_faces) == 0:
        return []
    pct = len(uc_faces) / max(len(ctx.centroids), 1) * 100
    return [Issue(
        code="UNDERCUT",
        severity=severity,
        message=f"{len(uc_faces)} faces ({pct:.1f}%) are undercuts for {process.value}.",
        process=process,
        affected_faces=uc_faces[:100].tolist(),
        fix_suggestion=f"Remove undercuts or plan multi-setup machining. {cite}",
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
        affected_faces=uc_faces[:100].tolist(),
        fix_suggestion=f"Redesign to eliminate undercuts or add slides. {cite}",
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
        severity=Severity.WARNING,
        message=(
            f"{sharp_count} sharp concave edges — tool radius {min_radius_mm}mm "
            f"cannot reach. Applies to {process.value}."
        ),
        process=process,
        required_value=min_radius_mm,
        fix_suggestion=f"Add fillets >= {min_radius_mm}mm to internal corners. {cite}",
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
    sharp = ctx.dihedral_angles_rad < np.radians(120)
    count = int(np.sum(sharp))
    if count < 5:
        return []
    return [Issue(
        code="MISSING_FILLETS",
        severity=Severity.WARNING,
        message=(
            f"{count} sharp internal corners need >= {min_fillet_mm}mm fillets "
            f"for {process.value} flow and stress distribution."
        ),
        process=process,
        required_value=min_fillet_mm,
        fix_suggestion=f"Add {min_fillet_mm}mm+ fillets. {cite}",
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
        severity=Severity.WARNING,
        message=(
            f"V/SA ratio {compactness:.1f}mm — bulky sections cause shrinkage "
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
    try:
        inertia = ctx.mesh.moment_inertia
        eig = np.linalg.eigvalsh(inertia)
        eig = np.sort(eig)
        if eig[0] <= 0:
            return []
        # Two eigenvalues should be approximately equal for rotational symmetry
        ratio_01 = eig[0] / eig[1] if eig[1] > 0 else 0
        ratio_12 = eig[1] / eig[2] if eig[2] > 0 else 0
        is_symmetric = (abs(1.0 - ratio_01) < tolerance) or (abs(1.0 - ratio_12) < tolerance)
        if not is_symmetric:
            return [Issue(
                code="NOT_ROTATIONALLY_SYMMETRIC",
                severity=Severity.ERROR,
                message=(
                    f"Part lacks rotational symmetry (eigenvalue ratios: "
                    f"{ratio_01:.2f}, {ratio_12:.2f}). Required for {process.value}."
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
    ld = length / diameter
    if ld <= max_ld:
        return []
    return [Issue(
        code="HIGH_LD_RATIO",
        severity=Severity.WARNING,
        message=(
            f"L/D ratio {ld:.1f}:1 exceeds {max_ld}:1 — deflection risk "
            f"on {process.value}. Steady rest recommended."
        ),
        process=process,
        measured_value=ld,
        required_value=max_ld,
        fix_suggestion="Reduce L/D or plan steady rest / tailstock support.",
    )]


# ──────────────────────────────────────────────────────────────
# Prismatic / 2.5D check (wire EDM / sheet metal)
# ──────────────────────────────────────────────────────────────
def check_prismatic(
    ctx: GeometryContext,
    process: ProcessType,
    *,
    cite: str = "",
) -> list[Issue]:
    """Test if part is approximately a 2D profile extruded along Z."""
    normals = ctx.normals
    # Prismatic = all faces are either horizontal (|n_z| > 0.95) or
    # vertical (|n_z| < 0.05). Anything else is non-prismatic.
    horiz = np.abs(normals[:, 2]) > 0.95
    vert = np.abs(normals[:, 2]) < 0.05
    prismatic_faces = horiz | vert
    pct = np.mean(prismatic_faces) * 100
    if pct > 85:
        return []
    return [Issue(
        code="NOT_PRISMATIC",
        severity=Severity.ERROR,
        message=(
            f"Only {pct:.0f}% of faces are prismatic (horizontal or vertical). "
            f"{process.value} requires a 2.5D extruded profile."
        ),
        process=process,
        measured_value=pct,
        required_value=85.0,
        fix_suggestion=f"Redesign as a 2D profile extruded along Z. {cite}",
    )]


# ──────────────────────────────────────────────────────────────
# Sheet metal thickness (single gauge)
# ──────────────────────────────────────────────────────────────
def check_sheet_gauge(
    ctx: GeometryContext,
    process: ProcessType,
) -> list[Issue]:
    issues: list[Issue] = []
    dims = sorted(ctx.info.bounding_box.dimensions)
    t = dims[0]
    if t < 0.3:
        issues.append(Issue(
            code="TOO_THIN_SHEET", severity=Severity.ERROR,
            message=f"Thickness {t:.2f}mm below 0.5mm min gauge.",
            process=process, measured_value=t, required_value=0.5,
            fix_suggestion="Increase to >= 0.5mm.",
        ))
    elif t > 8.0:
        issues.append(Issue(
            code="TOO_THICK_SHEET", severity=Severity.WARNING,
            message=f"Thickness {t:.1f}mm exceeds sheet range (0.5–6mm).",
            process=process, measured_value=t,
            fix_suggestion="Use plate CNC machining for thick stock.",
        ))
    closest = min(STANDARD_GAUGES, key=lambda g: abs(g - t))
    if abs(closest - t) > 0.1 and 0.5 <= t <= 6.0:
        issues.append(Issue(
            code="NON_STANDARD_GAUGE", severity=Severity.INFO,
            message=f"Thickness {t:.2f}mm — nearest standard: {closest}mm.",
            process=process, measured_value=t,
            fix_suggestion=f"Use {closest}mm standard gauge for cost savings.",
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
    if len(ctx.dihedral_angles_rad) == 0:
        return []
    very_sharp = ctx.dihedral_angles_rad < np.radians(90)
    count = int(np.sum(very_sharp))
    if count == 0:
        return []
    return [Issue(
        code="SHARP_BEND", severity=Severity.ERROR,
        message=(
            f"{count} bends < 90° — bend radius must be >= material thickness. "
            f"DIN 6935."
        ),
        process=process,
        fix_suggestion=f"Increase bend radius to >= 1x material thickness. {cite}",
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
        main = max(ctx.bodies, key=lambda m: m.volume if m.is_watertight else 0)
        for sub in ctx.bodies:
            if sub is main or not sub.is_watertight or sub.volume <= 0:
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
                severity=Severity.WARNING,
                message=(
                    f"Hole depth/diameter {ratio:.1f}:1 exceeds {max_ratio}:1 "
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
