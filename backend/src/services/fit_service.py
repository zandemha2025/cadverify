"""Two-part context-of-use geometry checks.

All reported collision and clearance values come from the submitted triangle
meshes in one shared coordinate frame. No visual overlap or bounding-box proxy
is promoted to a geometry result.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import base64
import time
from typing import Any

import numpy as np
import trimesh
from scipy.spatial import cKDTree


class FitGeometryError(ValueError):
    """The submitted pair cannot support an honest fit measurement."""


def context_fit_enabled() -> bool:
    return os.getenv("CONTEXT_FIT_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _sample_budget() -> int:
    try:
        return max(100, min(50_000, int(os.getenv("FIT_CLEARANCE_SAMPLES", "10000"))))
    except ValueError:
        return 10_000


def _max_pair_faces() -> int:
    """Hard admission bound before boolean or proximity allocates from faces."""
    try:
        return max(1_000, min(2_000_000, int(os.getenv("FIT_MAX_PAIR_FACES", "150000"))))
    except ValueError:
        return 150_000


def _require_volume_mesh(mesh: trimesh.Trimesh, label: str) -> None:
    if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
        raise FitGeometryError(f"{label} has no triangle geometry.")
    bounds = np.asarray(mesh.bounds, dtype=float)
    if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
        raise FitGeometryError(f"{label} has non-finite geometry and cannot be measured.")
    if not mesh.is_watertight:
        raise FitGeometryError(
            f"{label} is not watertight, so collision volume is withheld. Repair the shell and retry."
        )
    if not mesh.is_winding_consistent:
        raise FitGeometryError(
            f"{label} has inconsistent face winding, so collision volume is withheld. Repair the shell and retry."
        )
    # Volume/centroid are safe only after watertightness; trimesh mass properties
    # divide by volume and can emit a fatal RuntimeWarning on open flat shells.
    volume = abs(float(mesh.volume))
    centroid = np.asarray(mesh.center_mass, dtype=float)
    scale = max(float(np.linalg.norm(bounds[1] - bounds[0])), 1.0)
    if not np.isfinite(volume) or volume <= max(1e-12, scale ** 3 * 1e-12):
        raise FitGeometryError(f"{label} has near-zero enclosed volume, so fit measurements are withheld.")
    if not np.all(np.isfinite(centroid)):
        raise FitGeometryError(f"{label} has a non-finite volume centroid and cannot be measured.")


def _sample_surface(mesh: trimesh.Trimesh, count: int) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic index-spread sample of triangle centers (not area weighted)."""
    n = len(mesh.faces)
    take = min(n, count)
    idx = np.linspace(0, n - 1, take, dtype=np.int64)
    return np.asarray(mesh.triangles_center[idx], dtype=float), idx


def _proximity_target(mesh: trimesh.Trimesh, budget: int = 25_000) -> tuple[trimesh.Trimesh, np.ndarray]:
    """Bound point-to-triangle memory while retaining a source-face locator map."""
    if len(mesh.faces) <= budget:
        return mesh, np.arange(len(mesh.faces), dtype=np.int64)
    selected = np.linspace(0, len(mesh.faces) - 1, budget, dtype=np.int64)
    triangles = np.asarray(mesh.triangles[selected], dtype=float)
    proxy = trimesh.Trimesh(vertices=triangles.reshape(-1, 3), faces=np.arange(len(triangles) * 3).reshape(-1, 3), process=False)
    return proxy, selected


def _closest(source: trimesh.Trimesh, target: trimesh.Trimesh, count: int):
    points, source_faces = _sample_surface(source, count)
    proxy, target_map = _proximity_target(target)
    closest_chunks: list[np.ndarray] = []
    distance_chunks: list[np.ndarray] = []
    face_chunks: list[np.ndarray] = []
    try:
        for start in range(0, len(points), 256):
            near, distance, target_faces = trimesh.proximity.closest_point(proxy, points[start:start + 256])
            closest_chunks.append(np.asarray(near, dtype=float))
            distance_chunks.append(np.asarray(distance, dtype=float))
            face_chunks.append(target_map[np.asarray(target_faces, dtype=np.int64)])
    except MemoryError as exc:
        raise FitGeometryError("Surface clearance exceeded the bounded memory budget; reduce mesh tessellation and retry.") from exc
    closest = np.concatenate(closest_chunks)
    distance = np.concatenate(distance_chunks)
    target_faces = np.concatenate(face_chunks)
    valid = np.isfinite(distance)
    if not np.any(valid):
        raise FitGeometryError("Surface clearance could not be measured on this pair.")
    return points[valid], closest[valid], distance[valid], source_faces[valid], np.asarray(target_faces)[valid]


def _tight_zone(a: trimesh.Trimesh, b: trimesh.Trimesh, minimum: float, count: int) -> dict[str, Any]:
    a_points, b_near, a_dist, a_faces, b_faces = _closest(a, b, count)
    b_points, a_near, b_dist, b_src_faces, a_dst_faces = _closest(b, a, count)
    band = max(0.05, minimum * 0.10)
    a_mask = a_dist <= minimum + band
    b_mask = b_dist <= minimum + band
    centers = np.concatenate([
        (a_points[a_mask] + b_near[a_mask]) * 0.5,
        (b_points[b_mask] + a_near[b_mask]) * 0.5,
    ])
    return {
        "band_mm": round(float(band), 6),
        "region_center": np.mean(centers, axis=0).round(6).tolist() if len(centers) else None,
        "part_a_faces": sorted({int(v) for v in np.concatenate([a_faces[a_mask], a_dst_faces[b_mask]])}),
        "part_b_faces": sorted({int(v) for v in np.concatenate([b_faces[a_mask], b_src_faces[b_mask]])}),
        "sample_count": int(len(a_dist) + len(b_dist)),
    }


def _max_region_mesh_faces() -> int:
    try:
        return max(100, min(250_000, int(os.getenv("FIT_REGION_MESH_MAX_FACES", "150000"))))
    except ValueError:
        return 150_000


def _collision(a: trimesh.Trimesh, b: trimesh.Trimesh) -> tuple[float, dict[str, Any] | None]:
    try:
        intersection = trimesh.boolean.intersection([a, b], engine="manifold")
    except BaseException as exc:
        raise FitGeometryError(
            "Exact collision boolean failed; collision is withheld rather than estimated."
        ) from exc
    if intersection is None or len(intersection.faces) == 0:
        return 0.0, None
    volume = abs(float(intersection.volume))
    bounds = np.asarray(intersection.bounds, dtype=float)
    shell_scale = max(float(np.linalg.norm(bounds[1] - bounds[0])), 1.0)
    if not np.isfinite(volume):
        raise FitGeometryError("Collision volume was non-finite and is withheld.")
    if volume <= max(1e-12, shell_scale ** 3 * 1e-12):
        return 0.0, None
    vertices = np.asarray(intersection.vertices, dtype=float)
    center = np.asarray(intersection.centroid, dtype=float)
    # Face references identify submitted-mesh faces nearest the real intersection
    # boundary. They are locators, not a claim that a whole source triangle is inside.
    a_tree = cKDTree(np.asarray(a.triangles_center, dtype=float))
    b_tree = cKDTree(np.asarray(b.triangles_center, dtype=float))
    _, a_faces = a_tree.query(vertices, k=1)
    _, b_faces = b_tree.query(vertices, k=1)
    face_count = int(len(intersection.faces))
    if face_count <= _max_region_mesh_faces():
        payload = bytes(intersection.export(file_type="glb"))
        render_geometry = {
            "available": True,
            "media_type": "model/gltf-binary",
            "encoding": "base64",
            "data": base64.b64encode(payload).decode("ascii"),
            "face_count": face_count,
            "exact_intersection_shell": True,
        }
    else:
        render_geometry = {
            "available": False,
            "face_count": face_count,
            "reason": "intersection shell exceeds the bounded response budget; use centroid anchor only",
            "exact_intersection_shell": False,
        }
    return volume, {
        "region_center": center.round(6).tolist(),
        "bounds": np.asarray(intersection.bounds, dtype=float).round(6).tolist(),
        "part_a_faces": sorted({int(v) for v in np.atleast_1d(a_faces)}),
        "part_b_faces": sorted({int(v) for v in np.atleast_1d(b_faces)}),
        "intersection_faces": face_count,
        "render_geometry": render_geometry,
    }


def analyze_fit(mesh_a: trimesh.Trimesh, mesh_b: trimesh.Trimesh) -> dict[str, Any]:
    """Measure exact intersection and sampled surface clearance in a shared frame."""
    _require_volume_mesh(mesh_a, "part_a")
    _require_volume_mesh(mesh_b, "part_b")
    pair_faces = int(len(mesh_a.faces) + len(mesh_b.faces))
    max_faces = _max_pair_faces()
    if pair_faces > max_faces:
        raise FitGeometryError(
            f"Pair has {pair_faces} triangle faces, above the {max_faces} fit-check limit. Reduce tessellation and retry."
        )
    pair_start = time.perf_counter()
    collision_start = time.perf_counter()
    volume, collision_region = _collision(mesh_a, mesh_b)
    collision_ms = (time.perf_counter() - collision_start) * 1000
    count = _sample_budget()
    clearance_start = time.perf_counter()
    _, _, da, _, _ = _closest(mesh_a, mesh_b, count)
    _, _, db, _, _ = _closest(mesh_b, mesh_a, count)
    minimum = float(min(np.min(da), np.min(db)))
    # Interpenetrating solids have no positive clearance even though nearest
    # surface samples measure penetration-boundary separation.
    clearance = 0.0 if volume > 1e-9 else minimum
    tight_zone = _tight_zone(mesh_a, mesh_b, minimum, count)
    clearance_ms = (time.perf_counter() - clearance_start) * 1000
    pair_ms = (time.perf_counter() - pair_start) * 1000
    limits = [
        "Clearance is sampled on submitted tessellation and is not an analytic B-rep tolerance result.",
        "Shared-frame seating assumes both files were exported in the same assembly coordinate frame.",
    ]
    if len(mesh_a.faces) > 25_000 or len(mesh_b.faces) > 25_000:
        limits.append(
            "The true tightest spot may be smaller than the closest measured gap; a 25,000-face proxy was sampled."
        )
    return {
        "coordinate_frame": "shared_source_frame",
        "seating": {"method": "shared_source_frame", "transform_applied": False},
        "collision": {
            "intersects": bool(volume > 1e-9),
            "volume_mm3": round(volume, 6),
            "method": "manifold3d_boolean_intersection",
            "region": collision_region,
        },
        "clearance": {
            "closest_sampled_gap_mm": round(clearance, 6),
            "method": "bidirectional_sampled_point_to_triangle",
            "tight_zone": tight_zone,
        },
        "timing_ms": {
            "collision_boolean": round(collision_ms, 3),
            "sampled_clearance": round(clearance_ms, 3),
            "pair_total": round(pair_ms, 3),
        },
        "limits": limits,
    }


def parse_supplementary_mesh(data: bytes, filename: str) -> trimesh.Trimesh:
    """Parse fit-only OBJ/3MF bytes after a small structural gate.

    The canonical parser remains the source for STL/STEP/IGES. This helper adds
    the two mesh exchange formats needed by the pair endpoint without widening
    every manufacturing-analysis route.
    """
    from io import BytesIO
    from pathlib import Path

    suffix = Path(filename).suffix.lower()
    if suffix == ".obj":
        head = data[:8192].decode("utf-8", errors="ignore")
        if not any(line.lstrip().startswith(("v ", "f ")) for line in head.splitlines()):
            raise FitGeometryError("part is not a structurally valid OBJ mesh.")
        kind = "obj"
    elif suffix == ".3mf":
        if not data.startswith(b"PK"):
            raise FitGeometryError("part is not a structurally valid 3MF package.")
        kind = "3mf"
    else:
        raise FitGeometryError(f"Unsupported fit file type: {suffix or 'none'}.")
    try:
        loaded = trimesh.load(BytesIO(data), file_type=kind, force="scene")
        if isinstance(loaded, trimesh.Scene):
            mesh = loaded.to_mesh()
        else:
            mesh = loaded
    except Exception as exc:
        raise FitGeometryError(f"Could not parse {suffix} mesh.") from exc
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise FitGeometryError(f"{suffix} contained no triangle geometry.")
    return mesh
