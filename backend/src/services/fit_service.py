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
from scipy.spatial._ckdtree import cKDTree


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
    """Hard bound on collision faces after removing redundant tessellation."""
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


# Candidate triangles per sampled point in the first pass of ``_nearest_on``.
_NEAREST_K = 8


def _nearest_on(target: trimesh.Trimesh, points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exact closest point on ``target``'s triangles for each point: (closest, distance, face).

    A k-d tree over triangle centres proposes the nearest few triangles; the
    point-to-triangle distance to them is exact. A triangle left out has its
    centre at least the k-th centre's distance away, so it can only be closer
    when that distance minus its own radius (centre to farthest corner) is
    under the best found: those points are checked again against every
    triangle that close. Every face of the target counts (de-27: the 25,000
    triangles sampled through trimesh's r-tree took 44 s a pass on a 247,114
    triangle enclosure and could miss the tightest spot).
    """
    tri = np.asarray(target.triangles, dtype=np.float64)
    n = len(tri)
    centres = tri.mean(axis=1)
    radius = np.sqrt(((tri - centres[:, None, :]) ** 2).sum(axis=2)).max(axis=1)
    tree = cKDTree(centres)
    k = min(_NEAREST_K, n)
    centre_d, idx = tree.query(points, k=k)
    if k == 1:
        centre_d, idx = centre_d[:, None], idx[:, None]

    def best_of(pts: np.ndarray, cand: np.ndarray):
        flat = trimesh.triangles.closest_point(tri[cand.reshape(-1)], np.repeat(pts, cand.shape[1], axis=0))
        dist = np.linalg.norm(flat - np.repeat(pts, cand.shape[1], axis=0), axis=1).reshape(cand.shape)
        j = np.argmin(dist, axis=1)
        rows = np.arange(len(pts))
        return flat.reshape(cand.shape[0], cand.shape[1], 3)[rows, j], dist[rows, j], cand[rows, j]

    closest, distance, faces = best_of(points, idx)
    if n > k:
        unsure = np.flatnonzero(distance > centre_d[:, -1] - radius.max())
        for i in unsure:
            near = np.asarray(tree.query_ball_point(points[i], float(distance[i] + radius.max())), dtype=np.int64)
            near = near[np.linalg.norm(centres[near] - points[i], axis=1) - radius[near] < distance[i]]
            if len(near):
                c, d, f = best_of(points[i:i + 1], near[None, :])
                if d[0] < distance[i]:
                    closest[i], distance[i], faces[i] = c[0], d[0], f[0]
    return closest, distance, faces


def _closest(source: trimesh.Trimesh, target: trimesh.Trimesh, count: int):
    points, source_faces = _sample_surface(source, count)
    closest_chunks: list[np.ndarray] = []
    distance_chunks: list[np.ndarray] = []
    face_chunks: list[np.ndarray] = []
    try:
        for start in range(0, len(points), 4096):
            near, distance, target_faces = _nearest_on(target, points[start:start + 4096])
            closest_chunks.append(np.asarray(near, dtype=float))
            distance_chunks.append(np.asarray(distance, dtype=float))
            face_chunks.append(np.asarray(target_faces, dtype=np.int64))
    except MemoryError as exc:
        raise FitGeometryError("Surface clearance exceeded the bounded memory budget; reduce mesh tessellation and retry.") from exc
    closest = np.concatenate(closest_chunks)
    distance = np.concatenate(distance_chunks)
    target_faces = np.concatenate(face_chunks)
    valid = np.isfinite(distance)
    if not np.any(valid):
        raise FitGeometryError("Surface clearance could not be measured on this pair.")
    return points[valid], closest[valid], distance[valid], source_faces[valid], np.asarray(target_faces)[valid]


def _tight_zone(a_side: tuple, b_side: tuple, minimum: float) -> dict[str, Any]:
    """Where the pair is tightest, from the two sampled closest-point passes the gap came from."""
    a_points, b_near, a_dist, a_faces, b_faces = a_side
    b_points, a_near, b_dist, b_src_faces, a_dst_faces = b_side
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
        from manifold3d import Error, Manifold, Mesh64

        pair_faces = len(a.faces) + len(b.faces)
        max_faces = _max_pair_faces()
        # Keep source precision even for small meshes far from assembly origin.
        solids = [Manifold(Mesh64(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float64),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint64),
        )) for mesh in (a, b)]
        if pair_faces > max_faces:
            # Preserve the source meshes for clearance and face locators. Remove
            # redundant tessellation only at the kernel's native tolerance;
            # never increase that tolerance to make a complex pair fit the cap.
            solids = [solid.simplify(0) for solid in solids]
        if any(solid.status() != Error.NoError or solid.is_empty() for solid in solids):
            raise FitGeometryError("Collision geometry could not be prepared; measurements are withheld.")
        if sum(solid.num_tri() for solid in solids) > max_faces:
            raise FitGeometryError(
                f"Pair has {pair_faces} triangle faces, above the {max_faces} fit-check limit even after removing redundant triangles. Reduce tessellation and retry."
            )
        overlap = solids[0] ^ solids[1]
        if overlap.status() != Error.NoError:
            raise FitGeometryError("Exact collision boolean failed; measurements are withheld.")
        shell = overlap.to_mesh64()
        intersection = trimesh.Trimesh(vertices=shell.vert_properties, faces=shell.tri_verts, process=False)
    except FitGeometryError:
        raise
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
        payload = intersection.export(file_type="glb")
        if not isinstance(payload, bytes):
            raise FitGeometryError("Collision shell could not be exported; measurements are withheld.")
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
    pair_start = time.perf_counter()
    collision_start = time.perf_counter()
    volume, collision_region = _collision(mesh_a, mesh_b)
    collision_ms = (time.perf_counter() - collision_start) * 1000
    count = _sample_budget()
    clearance_start = time.perf_counter()
    # One sampled closest-point pass each way serves the gap and the tight zone (de-27: the
    # zone ran both passes again, the slowest part of a fit check, for the same answer).
    a_side = _closest(mesh_a, mesh_b, count)
    b_side = _closest(mesh_b, mesh_a, count)
    minimum = float(min(np.min(a_side[2]), np.min(b_side[2])))
    # Interpenetrating solids have no positive clearance even though nearest
    # surface samples measure penetration-boundary separation.
    clearance = 0.0 if volume > 1e-9 else minimum
    tight_zone = _tight_zone(a_side, b_side, minimum)
    clearance_ms = (time.perf_counter() - clearance_start) * 1000
    pair_ms = (time.perf_counter() - pair_start) * 1000
    limits = [
        "Clearance is sampled on submitted tessellation and is not an analytic B-rep tolerance result.",
    ]
    if len(mesh_a.faces) + len(mesh_b.faces) > _max_pair_faces():
        limits.append(
            "Collision uses the submitted shell with redundant triangles removed at the geometry kernel's native numerical tolerance; clearance and face locators retain the submitted meshes."
        )
    limits.append(
        "The gap is measured from points sampled on each surface to the other's nearest triangle (every "
        "triangle counts), so the true tightest spot may be a little smaller than the closest measured gap."
    )
    return {
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


def parse_supplementary_mesh(data: bytes, filename: str, *, max_expanded_bytes: int = 100 * 1024 * 1024) -> trimesh.Trimesh:
    """Parse OBJ/3MF fit/preview bytes after a bounded structural gate.

    The canonical parser remains the source for STL/STEP/IGES. This helper adds
    the two mesh exchange formats needed by the pair endpoint without widening
    every manufacturing-analysis route.
    """
    from io import BytesIO
    from pathlib import Path
    from zipfile import BadZipFile, ZipFile

    suffix = Path(filename).suffix.lower()
    if suffix == ".obj":
        head = data[:8192].decode("utf-8", errors="ignore")
        if not any(line.lstrip().startswith(("v ", "f ")) for line in head.splitlines()):
            raise FitGeometryError("part is not a structurally valid OBJ mesh.")
        kind = "obj"
    elif suffix == ".3mf":
        if not data.startswith(b"PK"):
            raise FitGeometryError("part is not a structurally valid 3MF package.")
        try:
            with ZipFile(BytesIO(data)) as archive:
                if sum(info.file_size for info in archive.infolist()) > max_expanded_bytes:
                    raise FitGeometryError("3MF expanded package exceeds the upload limit; reduce its contents and retry.")
        except BadZipFile as exc:
            raise FitGeometryError("part is not a structurally valid 3MF package.") from exc
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
    if kind == "3mf":
        if mesh.units not in {"micron", "millimeter", "millimeters", "centimeter", "inch", "foot", "meter"}:
            raise FitGeometryError("3MF units are unsupported; re-export with standard length units.")
        # Convert after baking instance transforms so translations scale too.
        mesh.convert_units("mm", guess=False)
    return mesh
