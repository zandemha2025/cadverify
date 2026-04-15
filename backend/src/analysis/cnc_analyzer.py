"""CNC machining specific checks.

Covers 3-axis milling, 5-axis milling, turning, and wire EDM.
"""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.constants import (
    MAX_POCKET_DEPTH_RATIO,
    MAX_WORKPIECE,
    STANDARD_TOOL_DIAMETERS,
)
from src.analysis.models import (
    FeatureSegment,
    GeometryInfo,
    Issue,
    ProcessType,
    Severity,
)


def check_undercuts(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Detect undercuts — faces not accessible from above (Z+ direction).

    For 3-axis CNC, any face whose normal has a negative Z component
    and isn't on the bottom of the part is an undercut.
    """
    issues = []
    if process not in (ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS):
        return issues

    normals = mesh.face_normals
    centroids = mesh.triangles_center

    # Faces pointing downward (normal Z < -0.1) that aren't on the bottom plane
    bottom_z = mesh.bounds[0][2]
    bottom_margin = (mesh.bounds[1][2] - bottom_z) * 0.05

    downward_mask = normals[:, 2] < -0.1
    not_bottom_mask = centroids[:, 2] > (bottom_z + bottom_margin)
    undercut_mask = downward_mask & not_bottom_mask

    undercut_faces = np.where(undercut_mask)[0].tolist()

    if undercut_faces:
        pct = len(undercut_faces) / len(normals) * 100

        if process == ProcessType.CNC_3AXIS:
            severity = Severity.ERROR
            msg_extra = "3-axis CNC cannot reach undercut areas without flipping the part."
        else:
            severity = Severity.WARNING
            msg_extra = "5-axis CNC may reach these but verify tool clearance."

        issues.append(Issue(
            code="UNDERCUT",
            severity=severity,
            message=(
                f"{len(undercut_faces)} faces ({pct:.1f}%) are undercuts. "
                + msg_extra
            ),
            process=process,
            affected_faces=undercut_faces[:100],
            fix_suggestion=(
                "Remove undercuts by redesigning with straight pull directions, "
                "or plan for a multi-setup machining operation (flip the part). "
                "5-axis CNC can handle moderate undercuts."
            ),
        ))
    return issues


def check_internal_radii(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Check that internal corners can be machined with available tooling.

    Internal corners must have a radius >= half the smallest tool diameter.
    Sharp internal corners are impossible to machine.
    """
    issues = []
    if process not in (ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS):
        return issues

    min_tool_radius = min(STANDARD_TOOL_DIAMETERS) / 2  # 0.5mm

    # Approximate: find edges where both adjacent faces form a concave angle
    # This is a simplified check — real machining analysis would use CAM simulation
    edges = mesh.edges_unique
    edge_lengths = mesh.edges_unique_length

    # Find very short edges that might indicate sharp internal corners
    sharp_edges = np.where(edge_lengths < min_tool_radius)[0]

    if len(sharp_edges) > 10:  # Only flag if significant
        issues.append(Issue(
            code="SHARP_INTERNAL_CORNERS",
            severity=Severity.WARNING,
            message=(
                f"Detected {len(sharp_edges)} edges with radius below "
                f"{min_tool_radius}mm (smallest available tool: "
                f"{min(STANDARD_TOOL_DIAMETERS)}mm end mill). "
                "Sharp internal corners cannot be machined."
            ),
            process=process,
            required_value=min_tool_radius,
            fix_suggestion=(
                f"Add fillets of at least {min_tool_radius}mm radius to "
                f"all internal corners. For tighter radii, consider wire EDM."
            ),
        ))
    return issues


def check_pocket_depth(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    process: ProcessType,
) -> list[Issue]:
    """Check pocket depth-to-width ratios.

    Deep narrow pockets cause tool deflection and chatter.
    """
    issues = []
    max_ratio = MAX_POCKET_DEPTH_RATIO.get(process)
    if max_ratio is None:
        return issues

    # Simplified check: use bounding box aspect ratio as a proxy
    # for pocket-like features (real analysis needs feature recognition)
    dims = sorted(geometry.bounding_box.dimensions)
    if dims[0] > 0 and dims[2] / dims[0] > max_ratio:
        issues.append(Issue(
            code="DEEP_FEATURES",
            severity=Severity.WARNING,
            message=(
                f"Part dimensions suggest deep features "
                f"(ratio {dims[2] / dims[0]:.1f}:1 exceeds {max_ratio}:1 limit). "
                "Deep pockets cause tool deflection and poor surface finish."
            ),
            process=process,
            measured_value=dims[2] / dims[0],
            required_value=max_ratio,
            fix_suggestion=(
                "Reduce pocket depth, widen narrow features, or use specialized "
                "long-reach tooling. Step-down machining strategies can help."
            ),
        ))
    return issues


def check_thin_walls_cnc(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Check for thin walls that vibrate during machining."""
    issues = []
    # Min wall for CNC: typically 1mm for metals, 1.5mm for plastics
    min_wall = 1.0 if process in (ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS) else 1.5

    # Use same ray-casting approach as additive but with CNC thresholds
    centroids = mesh.triangles_center
    normals = mesh.face_normals

    ray_origins = centroids + normals * 0.001
    ray_directions = -normals

    try:
        locations, index_ray, index_tri = mesh.ray.intersects_location(
            ray_origins=ray_origins,
            ray_directions=ray_directions,
        )
    except Exception:
        return issues

    if len(locations) == 0:
        return issues

    thin_count = 0
    min_measured = float("inf")

    for i in range(len(centroids)):
        mask = index_ray == i
        if not np.any(mask):
            continue
        hits = locations[mask]
        distances = np.linalg.norm(hits - ray_origins[i], axis=1)
        thickness = float(np.min(distances))
        if thickness < min_measured:
            min_measured = thickness
        if thickness < min_wall:
            thin_count += 1

    if thin_count > 0:
        pct = thin_count / len(centroids) * 100
        if pct > 5:
            issues.append(Issue(
                code="THIN_WALL_CNC",
                severity=Severity.WARNING,
                message=(
                    f"{thin_count} faces ({pct:.1f}%) have wall thickness below "
                    f"{min_wall}mm. Thin walls vibrate during CNC machining, "
                    f"causing chatter and poor surface finish."
                ),
                process=process,
                measured_value=min_measured,
                required_value=min_wall,
                fix_suggestion=(
                    f"Increase wall thickness to {min_wall}mm+ or add ribs/gussets "
                    "for support. Reduce cutting speed and depth of cut for thin sections."
                ),
            ))
    return issues


def check_workpiece_size(
    geometry: GeometryInfo,
    process: ProcessType,
) -> list[Issue]:
    """Check if part fits within typical CNC machine work envelopes."""
    issues = []
    max_dims = MAX_WORKPIECE.get(process)
    if max_dims is None:
        return issues

    dims = geometry.bounding_box.dimensions
    exceeds = []
    for dim, limit, axis in zip(dims, max_dims, ("X", "Y", "Z")):
        if dim > limit:
            exceeds.append(f"{axis}: {dim:.0f}mm > {limit}mm")

    if exceeds:
        issues.append(Issue(
            code="EXCEEDS_WORKPIECE",
            severity=Severity.ERROR,
            message=(
                f"Part exceeds typical work envelope for {process.value}: "
                + ", ".join(exceeds)
            ),
            process=process,
            fix_suggestion="Scale down, split into sections, or use a larger machine.",
        ))
    return issues


def check_fixture_surfaces(
    mesh: trimesh.Trimesh,
    process: ProcessType,
) -> list[Issue]:
    """Check for flat datum surfaces suitable for workholding."""
    issues = []
    if process not in (ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS):
        return issues

    normals = mesh.face_normals
    face_areas = mesh.area_faces
    total_area = mesh.area

    # Find faces that are roughly flat (normal aligned with an axis)
    flat_threshold = 0.98  # cos(~11°)
    flat_mask = np.zeros(len(normals), dtype=bool)

    for axis in ([0, 0, 1], [0, 0, -1], [0, 1, 0], [0, -1, 0], [1, 0, 0], [-1, 0, 0]):
        alignment = np.abs(np.dot(normals, axis))
        flat_mask |= alignment > flat_threshold

    flat_area = float(np.sum(face_areas[flat_mask]))
    flat_pct = flat_area / total_area * 100

    if flat_pct < 10:
        issues.append(Issue(
            code="NO_FIXTURE_SURFACES",
            severity=Severity.WARNING,
            message=(
                f"Only {flat_pct:.1f}% of surface area is flat — may be "
                "difficult to fixture for CNC machining."
            ),
            process=process,
            fix_suggestion=(
                "Add flat datum surfaces or mounting tabs for workholding. "
                "Custom fixtures or soft jaws may be needed for organic shapes."
            ),
        ))
    return issues


CNC_PROCESSES = [
    ProcessType.CNC_3AXIS,
    ProcessType.CNC_5AXIS,
    ProcessType.CNC_TURNING,
    ProcessType.WIRE_EDM,
]


def run_cnc_checks(
    mesh: trimesh.Trimesh,
    geometry: GeometryInfo,
    process: ProcessType,
    segments: list[FeatureSegment] | None = None,
) -> list[Issue]:
    """Run all CNC machining checks for a given process."""
    issues: list[Issue] = []
    issues.extend(check_undercuts(mesh, process))
    issues.extend(check_internal_radii(mesh, process))
    issues.extend(check_pocket_depth(mesh, geometry, process))
    issues.extend(check_thin_walls_cnc(mesh, process))
    issues.extend(check_workpiece_size(geometry, process))
    issues.extend(check_fixture_surfaces(mesh, process))
    return issues
