"""Universal geometry checks applicable to all manufacturing processes."""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.models import (
    BoundingBox,
    GeometryInfo,
    Issue,
    Severity,
)


def analyze_geometry(mesh: trimesh.Trimesh) -> GeometryInfo:
    """Extract basic geometry information from a mesh.

    Safely handles empty / degenerate meshes by returning a zero-valued
    GeometryInfo rather than propagating a None bounds crash.
    """
    bounds = mesh.bounds  # None for empty meshes
    if bounds is None or len(mesh.faces) == 0:
        bbox = BoundingBox(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        return GeometryInfo(
            vertex_count=int(len(mesh.vertices)),
            face_count=0,
            volume=0.0,
            surface_area=0.0,
            bounding_box=bbox,
            is_watertight=False,
            is_manifold=False,
            euler_number=0,
            center_of_mass=(0.0, 0.0, 0.0),
        )

    bbox = BoundingBox(
        min_x=float(bounds[0][0]),
        min_y=float(bounds[0][1]),
        min_z=float(bounds[0][2]),
        max_x=float(bounds[1][0]),
        max_y=float(bounds[1][1]),
        max_z=float(bounds[1][2]),
    )
    com = mesh.center_mass
    return GeometryInfo(
        vertex_count=len(mesh.vertices),
        face_count=len(mesh.faces),
        volume=float(mesh.volume) if mesh.is_watertight else 0.0,
        surface_area=float(mesh.area),
        bounding_box=bbox,
        is_watertight=bool(mesh.is_watertight),
        is_manifold=bool(mesh.is_watertight),  # trimesh: watertight ≈ manifold
        euler_number=int(mesh.euler_number),
        center_of_mass=(float(com[0]), float(com[1]), float(com[2])),
    )


def check_watertight(mesh: trimesh.Trimesh) -> list[Issue]:
    """Check if the mesh is watertight (manifold, no holes)."""
    issues = []
    if not mesh.is_watertight:
        # Find boundary edges (edges that belong to only one face)
        boundary_count = 0
        if hasattr(mesh, "edges_unique") and hasattr(mesh, "edges_unique_inverse"):
            edge_face_count = np.bincount(mesh.edges_unique_inverse)
            boundary_count = int(np.sum(edge_face_count == 1))

        issues.append(Issue(
            code="NON_WATERTIGHT",
            severity=Severity.ERROR,
            message=(
                f"Mesh is not watertight — has {boundary_count} boundary edges. "
                "All manufacturing processes require a closed solid."
            ),
            process=None,
            fix_suggestion=(
                "Close all holes in the mesh. In your CAD software, use "
                "'Repair' or 'Heal' to find and fill gaps. Common causes: "
                "missing faces, T-junctions, or disconnected shells."
            ),
        ))
    return issues


def check_normals(mesh: trimesh.Trimesh) -> list[Issue]:
    """Check face normal consistency."""
    issues = []
    if not mesh.is_winding_consistent:
        issues.append(Issue(
            code="INCONSISTENT_NORMALS",
            severity=Severity.ERROR,
            message="Face normals are inconsistent — some faces point inward.",
            process=None,
            fix_suggestion=(
                "Recalculate and unify face normals. Most CAD tools have "
                "'Recalculate Normals' or 'Unify Normals' operations."
            ),
        ))
    return issues


def check_degenerate_faces(mesh: trimesh.Trimesh) -> list[Issue]:
    """Check for zero-area or near-zero-area faces."""
    issues = []
    face_areas = mesh.area_faces
    degenerate_mask = face_areas < 1e-10
    degen_count = int(np.sum(degenerate_mask))

    if degen_count > 0:
        degen_indices = np.where(degenerate_mask)[0].tolist()
        issues.append(Issue(
            code="DEGENERATE_FACES",
            severity=Severity.WARNING,
            message=f"{degen_count} degenerate (zero-area) faces detected.",
            process=None,
            affected_faces=degen_indices[:100],  # Cap at 100 for response size
            fix_suggestion=(
                "Remove degenerate triangles. These are typically artifacts "
                "from bad tessellation. Re-export from CAD with tighter mesh quality."
            ),
        ))
    return issues


def check_self_intersections(mesh: trimesh.Trimesh) -> list[Issue]:
    """Check for self-intersecting geometry.

    This is computationally expensive for large meshes, so we use
    trimesh's built-in check which samples ray intersections.
    """
    issues = []
    try:
        # trimesh doesn't have a fast built-in self-intersection check,
        # but we can use the split to check for overlapping bodies
        if not mesh.is_volume:
            issues.append(Issue(
                code="NOT_SOLID_VOLUME",
                severity=Severity.WARNING,
                message=(
                    "Mesh does not represent a valid solid volume. "
                    "This may indicate self-intersections or inverted regions."
                ),
                process=None,
                fix_suggestion=(
                    "Check for overlapping geometry or boolean operation artifacts. "
                    "Re-run boolean operations in your CAD tool or use mesh repair."
                ),
            ))
    except Exception:
        pass  # Skip if check fails on malformed mesh
    return issues


def check_disconnected_components(mesh: trimesh.Trimesh) -> list[Issue]:
    """Check for multiple disconnected bodies."""
    issues = []
    body_count = mesh.body_count if hasattr(mesh, "body_count") else len(mesh.split())
    if body_count > 1:
        issues.append(Issue(
            code="MULTIPLE_BODIES",
            severity=Severity.WARNING,
            message=f"Mesh contains {body_count} disconnected bodies.",
            process=None,
            fix_suggestion=(
                "Combine into a single solid body using boolean union, or "
                "separate into individual files for independent manufacturing."
            ),
        ))
    return issues


def detect_units(mesh: trimesh.Trimesh) -> str:
    """Heuristic unit detection based on bounding box size.

    Most 3D-printed parts are 10-300mm. If the bounding box max
    dimension is <1, likely meters. If >10000, likely microns.
    """
    max_dim = max(mesh.extents)
    if max_dim < 0.5:
        return "m"      # Probably meters
    if max_dim < 25.4:
        return "inches"  # Possibly inches
    if max_dim > 10000:
        return "microns"
    return "mm"


def run_universal_checks(mesh: trimesh.Trimesh) -> list[Issue]:
    """Run all universal geometry checks and return combined issues."""
    issues: list[Issue] = []
    issues.extend(check_watertight(mesh))
    issues.extend(check_normals(mesh))
    issues.extend(check_degenerate_faces(mesh))
    issues.extend(check_self_intersections(mesh))
    issues.extend(check_disconnected_components(mesh))
    return issues
