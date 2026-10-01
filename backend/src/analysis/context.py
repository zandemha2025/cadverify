"""Shared geometry context for all process analyzers.

Builds *once* per request and is reused by every ProcessAnalyzer. This replaces
the old pattern where every analyzer re-ran its own ray cast / normal / edge
analysis — which made /validate O(processes x faces) and produced duplicated,
inconsistent measurements.

Design contract:
    * Everything expensive lives here. Analyzers must not call mesh.ray.* again.
    * All fields are numpy arrays or plain Python objects so the context is
      pickle-friendly for worker execution.
    * Failure to compute any single field degrades to a safe default
      (np.inf for thickness, empty arrays for topology) — a malformed mesh
      never breaks the analysis; it just produces higher-uncertainty issues.
"""

from __future__ import annotations

import os
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any

import logging

import numpy as np
import trimesh
from scipy.spatial import ConvexHull, KDTree

from src.analysis.models import FeatureSegment, GeometryInfo

logger = logging.getLogger("cadverify.context")


def _raycast_sample_threshold() -> int:
    """Face count above which the *sampled* (bounded) wall-thickness path runs.

    Env var: RAYCAST_SAMPLE_THRESHOLD (default 5000).

    The un-sampled full-ray path calls ``mesh.ray.intersects_location(...,
    multiple_hits=True)`` for every face at once. With no fast ray backend
    installed (pyembree/embreex absent) trimesh falls back to the pure-Python
    ``RayMeshIntersector``, whose peak memory scales with rays × candidate
    triangles — a 37k-face part measured ~19 GB. The old default of 50000 meant
    the entire dangerous 10k–50k-face zone (most real CAD) ran that un-bounded
    path. Lowering the default to 5000 routes those meshes onto the sampled
    KDTree path, whose ray count is capped at ~5000. Still env-overridable.
    """
    try:
        return max(1, int(os.getenv("RAYCAST_SAMPLE_THRESHOLD", "5000")))
    except Exception:
        return 5000


def _wall_thickness_ray_batch() -> int:
    """Upper cap on rays cast per ``intersects_location`` call. Env: WALL_THICKNESS_RAY_BATCH.

    The pure-Python ray backend materialises (rays × candidate-triangle) arrays
    *per call*, so casting all rays at once spikes to gigabytes. This is the
    *maximum* batch; the effective batch is shrunk further for high-face meshes
    via the ray×face budget below. Default 512 keeps per-batch Python overhead
    negligible on ordinary CAD (small meshes, few candidates per ray).
    """
    try:
        return max(1, int(os.getenv("WALL_THICKNESS_RAY_BATCH", "512")))
    except Exception:
        return 512


def _wall_thickness_ray_budget() -> int:
    """Target rays×faces product per ray-cast call. Env: WALL_THICKNESS_RAY_BUDGET.

    Worst-case candidate-triangle count per ray is ~n_faces (a hollow sphere,
    where the broad phase can prune nothing). The pure-Python intersector's
    peak memory tracks rays × candidates, so we bound (batch × n_faces) to a
    fixed budget: the batch auto-shrinks as face count grows, keeping peak RSS
    flat from a 10k realistic part up to the decimation cap. Empirically ~1.2M
    holds an 82k-face hollow sphere (pathological worst case) to a few hundred MB
    (measured ~0.5 GB) versus ~14 GB for the old single-call path. Default 1_200_000.
    """
    try:
        return max(1000, int(os.getenv("WALL_THICKNESS_RAY_BUDGET", "1200000")))
    except Exception:
        return 1_200_000


def _max_analysis_faces() -> int:
    """Face cap above which the mesh is decimated before analysis.

    Env: MAX_ANALYSIS_FACES (default 250000). Bounds *every* O(faces) operation
    in the engine (ray cast, adjacency, facets, split, feature detection) for
    pathological uploads, not just wall thickness. The cap is deliberately
    conservative so typical CAD parts — and the 209k-face large-mesh regression
    — are never touched. Decimation is recorded honestly in ``ctx.metadata``.
    """
    try:
        return max(1000, int(os.getenv("MAX_ANALYSIS_FACES", "250000")))
    except Exception:
        return 250000


if TYPE_CHECKING:  # avoid circular import at runtime
    from src.analysis.features.base import Feature


@dataclass
class GeometryContext:
    """Precomputed, shared geometry state handed to every ProcessAnalyzer."""

    mesh: trimesh.Trimesh
    info: GeometryInfo

    # Scale
    bbox_diag: float
    scale_eps: float  # ray-cast offset; scale-aware to avoid sub-mm drift

    # Per-face arrays (length = N_faces)
    normals: np.ndarray              # (N, 3) float
    centroids: np.ndarray            # (N, 3) float
    face_areas: np.ndarray           # (N,)   float
    angles_from_up_deg: np.ndarray   # (N,)   float — angle between face normal and +Z
    wall_thickness: np.ndarray       # (N,)   float — inward ray cast, inf on failure

    # Per-edge arrays
    edge_lengths: np.ndarray         # physical sharp-edge spans / closed-rim widths
    dihedral_angles_rad: np.ndarray  # (A,) float — from face_adjacency_angles
    face_adjacency: np.ndarray       # (A, 2) int  — from face_adjacency
    concave_mask: np.ndarray         # (A,) bool   — ~face_adjacency_convex

    # Topology
    bodies: list[trimesh.Trimesh]
    body_volumes: list[float]
    facet_groups: list[np.ndarray]   # from mesh.facets — coplanar face clusters

    # Feature / segmentation outputs (populated by downstream steps)
    features: list["Feature"] = field(default_factory=list)
    segments: list[FeatureSegment] = field(default_factory=list)

    # Room for extensions (symmetry axis, SAM-3D labels, ...)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Upper bounds apply only to persistent, directly cast hits. They are not
    # two-sided intervals: a perturbed ray can encounter another surface first.
    wall_thickness_upper: np.ndarray | None = None
    edge_length_precision: np.ndarray | None = None
    edge_topology_stable: bool = True

    @cached_property
    def flat_sheet_geometry(self):
        return flat_sheet_geometry(self.mesh)

    @property
    def flat_sheet_dimensions(self) -> tuple[float, float, float] | None:
        measured = self.flat_sheet_geometry
        return measured[0] if measured is not None else None

    @property
    def sheet_precision(self) -> float:
        measured = self.flat_sheet_geometry
        return measured[2] if measured is not None else 0.0

    @cached_property
    def maximum_inscribed_diameter(self) -> float | None:
        """Largest *observed* interior sphere, shared by molding/casting checks.

        A normal chord across a plate edge measures its length, not its wall.
        Nearest-surface distance at an interior point instead bounds a sphere
        that actually fits in material. This is a sampled lower bound on the
        largest thick section, not certification of unsampled geometry.
        """
        try:
            if not self.mesh.is_volume:
                return None
            n = len(self.centroids)
            # Reuse only the faces actually ray-cast, never interpolated values.
            stride = max(1, n // 5000) if n > _raycast_sample_threshold() else 1
            ids = np.arange(0, n, stride)
            ids = ids[::max(1, (len(ids) + 4999) // 5000)]
            ids = ids[np.isfinite(self.wall_thickness[ids])]
            points = _wall_sample_points(self.mesh)[ids] - self.normals[ids] * self.wall_thickness[ids, None] / 2
            batch = min(_wall_thickness_ray_batch(), max(8, _wall_thickness_ray_budget() // n))
            tol = wall_thickness_tolerance(self.mesh, self.scale_eps)
            # Facet centers recover broad planar sections even on coarse CAD
            # triangulations. A concave facet's centroid can lie in a hole;
            # accept it only when it lies on the actual surface.
            # ponytail: capped surface samples can miss small sections; use an
            # adaptive medial-axis solver if certified global maxima are needed.
            facets = self.facet_groups[::max(1, (len(self.facet_groups) + 4999) // 5000)]
            facet_points = np.asarray([
                np.average(self.centroids[f], axis=0, weights=self.face_areas[f])
                for f in facets if self.face_areas[f].sum() > 0
            ])
            extra = []
            for start in range(0, len(facet_points), batch):
                p, distance, face = self.mesh.nearest.on_surface(facet_points[start:start + batch])
                valid = distance <= tol
                p, face = p[valid], face[valid]
                directions = -self.normals[face]
                chord = _cast_inward_rays_batched(
                    self.mesh, p - directions * self.scale_eps, directions,
                    self.scale_eps, face, source_points=p,
                )
                finite = np.isfinite(chord)
                extra.extend(p[finite] + directions[finite] * chord[finite, None] / 2)
            if extra:
                points = np.vstack([points, extra])
            points = np.unique(np.vstack([points, self.mesh.center_mass]), axis=0)
            best = 0.0
            for start in range(0, len(points), batch):
                candidates = points[start:start + batch]
                # Concavities, cavities and separate bodies must not turn an
                # exterior clearance into material thickness.
                candidates = candidates[self.mesh.contains(candidates)]
                if len(candidates):
                    _, distance, _ = self.mesh.nearest.on_surface(candidates)
                    best = max(best, float(distance.max()) * 2)
            return best if np.isfinite(best) and best > tol else None
        except Exception:
            logger.warning("Maximum wall thickness measurement failed", exc_info=True)
            return None

    # ──────────────────────────────────────────────────────────
    # Builder
    # ──────────────────────────────────────────────────────────
    @classmethod
    def build(cls, mesh: trimesh.Trimesh, info: GeometryInfo) -> "GeometryContext":
        # Bound the whole engine: decimate pathologically large meshes before
        # any O(faces) work. `info` intentionally keeps the ORIGINAL part's
        # volume/area/watertightness (analyze_geometry ran on the raw mesh);
        # only the per-face analysis arrays below run on the bounded mesh. The
        # swap is recorded in metadata["decimation"], which
        # ``base_analyzer.decimation_issue`` reads to emit a user-visible
        # DECIMATED_MESH warning in the analysis response (no silent lying).
        mesh, decimation = _maybe_decimate(mesh)

        extents = mesh.extents
        if extents is None or len(mesh.faces) == 0:
            bbox_diag = 0.0
        else:
            bbox_diag = float(np.linalg.norm(np.asarray(extents, dtype=np.float64)))
        # Scale-aware epsilon clamped to handle sub-mm features (micro parts)
        # and multi-meter assemblies without drifting the ray-cast origin
        # either below numerical noise or past thin walls.
        scale_eps = max(1e-4, min(bbox_diag * 1e-4, 0.1))

        normals = np.asarray(mesh.face_normals, dtype=np.float64)
        centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
        face_areas = np.asarray(mesh.area_faces, dtype=np.float64)

        # Suppress cosmetic divide-by-zero/overflow RuntimeWarnings from the
        # matmul over degenerate/decimated normals; the clipped result is clean.
        with np.errstate(all="ignore"):
            cos_z = np.clip(normals @ np.array([0.0, 0.0, 1.0]), -1.0, 1.0)
            angles_from_up_deg = np.degrees(np.arccos(cos_z))

        wall_upper = np.full(len(centroids), np.inf)
        wall_thickness = _compute_wall_thickness(mesh, normals, centroids, scale_eps, wall_upper)

        edge_lengths, edge_precision, edge_stable = manufacturing_edge_measurements(mesh)
        if decimation and decimation.get("succeeded"):
            wall_upper[:] = np.inf
            edge_precision[:] = np.inf
        adjacency = _safe_attr(mesh, "face_adjacency", default=np.empty((0, 2), dtype=int))
        dihedral = _safe_attr(mesh, "face_adjacency_angles", default=np.empty(0))
        try:
            convex = np.asarray(mesh.face_adjacency_convex, dtype=bool)
            concave_mask = ~convex
        except Exception:
            logger.warning(
                "face_adjacency_convex failed (n_adj=%d); defaulting to all-convex",
                len(dihedral),
                exc_info=True,
            )
            concave_mask = np.zeros(len(dihedral), dtype=bool)

        split_skipped: dict[str, Any] | None = None
        try:
            n_components = _count_connected_components(mesh)
            cap = _max_split_bodies()
            if n_components > cap:
                # Unmerged triangle soup (or pathological fragment counts) makes
                # trimesh.split construct one Trimesh per face: 200k faces took
                # ~35s and ~200k live objects, timing out /validate and
                # OOM-restarting the batch worker. Per-body volumes are all 0.0
                # on non-watertight soup anyway, so collapse to a single body
                # and record the skip honestly in metadata.
                split_skipped = {"components": int(n_components), "cap": cap}
                logger.warning(
                    "mesh.split skipped: %d connected components exceed cap %d; "
                    "treating as single body",
                    n_components,
                    cap,
                )
                bodies = [mesh]
            else:
                bodies = list(mesh.split(only_watertight=False))
        except Exception:
            logger.warning(
                "mesh.split failed (n_faces=%d); treating as single body",
                len(mesh.faces),
                exc_info=True,
            )
            bodies = [mesh]
        body_volumes = [_finite_body_volume(body) for body in bodies]

        try:
            facet_groups = [np.asarray(f, dtype=int) for f in mesh.facets]
        except Exception:
            logger.warning(
                "mesh.facets extraction failed (n_faces=%d); no facet groups",
                len(mesh.faces),
                exc_info=True,
            )
            facet_groups = []

        return cls(
            mesh=mesh,
            info=info,
            bbox_diag=bbox_diag,
            scale_eps=scale_eps,
            normals=normals,
            centroids=centroids,
            face_areas=face_areas,
            angles_from_up_deg=angles_from_up_deg,
            wall_thickness=wall_thickness,
            wall_thickness_upper=wall_upper,
            edge_lengths=np.asarray(edge_lengths, dtype=np.float64),
            edge_length_precision=edge_precision,
            edge_topology_stable=edge_stable and not bool(decimation and decimation.get("succeeded")),
            dihedral_angles_rad=np.asarray(dihedral, dtype=np.float64),
            face_adjacency=np.asarray(adjacency, dtype=np.int64),
            concave_mask=concave_mask,
            bodies=bodies,
            body_volumes=body_volumes,
            facet_groups=facet_groups,
            metadata={
                k: v
                for k, v in {
                    "decimation": decimation,
                    "body_split_skipped": split_skipped,
                }.items()
                if v
            },
        )


def analysis_mesh_hash(mesh: trimesh.Trimesh) -> str:
    """Identity of face order and coordinates at the GLB's float32 precision."""
    return hashlib.sha256(np.asarray(mesh.triangles, dtype="<f4").tobytes()).hexdigest()


def manufacturing_edge_lengths(mesh: trimesh.Trimesh) -> np.ndarray:
    return manufacturing_edge_measurements(mesh)[0]


def manufacturing_edge_measurements(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray, bool]:
    """Measure geometric boundaries, never the edges of the export triangles.

    Join subdivision segments until a junction or a real corner. A smooth
    closed rim contributes its in-plane width (e.g. bore diameter), not its
    individual tessellation chords. The work is linear in boundary size.
    """
    angles = np.asarray(mesh.face_adjacency_angles)
    edges = np.asarray(mesh.face_adjacency_edges)[angles > np.radians(30)]
    error = float(mesh.metadata.get("coordinate_error", 0.0))
    # Both selected AND omitted adjacencies must stay on the same side of the
    # sharp-edge threshold; otherwise chain membership itself is uncertain.
    stable = True
    if error:
        normal_error = _normal_precision(mesh, error)
        angle_error = 2 * np.arcsin(np.minimum(1., normal_error / 2))
        stable = bool(np.all(np.abs(angles - np.radians(30)) >
                             angle_error[mesh.face_adjacency].sum(axis=1)))
    if len(edges) == 0:
        return np.empty(0), np.empty(0), stable
    vertices = np.asarray(mesh.vertices)
    neighbors: dict[int, list[int]] = defaultdict(list)
    for index, (a, b) in enumerate(edges):
        neighbors[int(a)].append(index)
        neighbors[int(b)].append(index)

    breaks = set()
    for vertex, incident in neighbors.items():
        if len(incident) != 2:
            breaks.add(vertex)
            continue
        ends = [int(edges[i].sum()) - vertex for i in incident]
        directions = vertices[ends] - vertices[vertex]
        lengths = np.linalg.norm(directions, axis=1)
        if error:
            # Unit-vector change for a segment whose endpoints each move <= e.
            direction_error = np.minimum(2., 4 * error / np.maximum(lengths - 2 * error, 1e-300))
            cosine = float(np.dot(*directions) / max(float(np.prod(lengths)), 1e-300))
            stable &= abs(cosine + np.cos(np.radians(30))) > direction_error.sum()
        if np.any(lengths <= 1e-12) or np.dot(*directions) > -np.cos(np.radians(30)) * np.prod(lengths):
            breaks.add(vertex)

    visited: set[int] = set()
    sizes = []
    precisions = []
    # Start open chains at their ends; the remaining components are closed rims.
    for start in [*breaks, *neighbors]:
        for first in neighbors[start]:
            if first in visited:
                continue
            path = [start]
            vertex, edge = start, first
            while edge not in visited:
                visited.add(edge)
                vertex = int(edges[edge].sum()) - vertex
                path.append(vertex)
                if vertex == start or vertex in breaks:
                    break
                edge = next(i for i in neighbors[vertex] if i != edge)
            points = vertices[path]
            precision = 2 * error * (len(path) - 1) if stable else float("inf")
            if path[-1] == start:
                # ponytail: planar rim width; freeform openings need B-rep
                # feature measurements before claiming full feature coverage.
                points = points[:-1]
                centered = points - points.mean(axis=0)
                _, singular, axes = np.linalg.svd(centered, full_matrices=False)
                if len(singular) < 2 or singular[1] <= 1e-12:
                    continue
                size = float(np.ptp(centered @ axes[:2].T, axis=0).min())
                # PCA axes can jump at repeated singular values. Do not claim
                # a coordinate-rounding bound for this heuristic rim width.
                if error:
                    precision = float("inf")
            else:
                size = float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())
            if np.isfinite(size) and size > 1e-12:
                sizes.append(size)
                precisions.append(precision)
    return np.asarray(sizes, dtype=np.float64), np.asarray(precisions, dtype=np.float64), bool(stable)


def _max_split_bodies() -> int:
    """Cap on connected components passed to trimesh.split.

    Env var: MAX_SPLIT_BODIES (default 512). Beyond the cap the context treats
    the mesh as one body and records body_split_skipped in metadata.
    """
    try:
        value = int(os.getenv("MAX_SPLIT_BODIES", "512"))
    except ValueError:
        return 512
    return value if value > 0 else 512


def _count_connected_components(mesh: trimesh.Trimesh) -> int:
    """Count face-graph components WITHOUT building submeshes (cheap labels)."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components as _csgraph_cc

    n_faces = len(mesh.faces)
    if n_faces == 0:
        return 0
    adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64)
    if adjacency.size == 0:
        return n_faces
    graph = csr_matrix(
        (np.ones(len(adjacency)), (adjacency[:, 0], adjacency[:, 1])),
        shape=(n_faces, n_faces),
    )
    n_components, _ = _csgraph_cc(graph, directed=False)
    return int(n_components)


def _finite_body_volume(mesh: trimesh.Trimesh) -> float:
    """Return absolute volume without trimesh's zero-volume center division.

    Some CAD imports split into topologically watertight sub-shells whose
    signed tetrahedral volume cancels to zero. ``Trimesh.volume`` first derives
    a center of mass and divides by that zero volume, emitting NaN warnings
    before a caller can reject the shell. Cavity/core checks only need a finite
    ordering value, so integrate volume directly and classify zero or non-finite
    shells as non-volumetric.
    """
    if not mesh.is_watertight or len(mesh.faces) == 0:
        return 0.0
    try:
        triangles = np.asarray(mesh.triangles, dtype=np.float64)
        bounds = np.asarray(mesh.bounds, dtype=np.float64)
        if triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or bounds.shape != (2, 3):
            return 0.0
        shifted = triangles - bounds.mean(axis=0)
        with np.errstate(all="ignore"):
            six_volume = np.einsum(
                "ij,ij->i",
                shifted[:, 0],
                np.cross(shifted[:, 1], shifted[:, 2]),
            ).sum()
        volume = abs(float(six_volume)) / 6.0
        return volume if np.isfinite(volume) and volume > 1e-12 else 0.0
    except Exception:
        return 0.0


# ──────────────────────────────────────────────────────────────
# Vectorized wall-thickness ray cast
# ──────────────────────────────────────────────────────────────
def wall_thickness_tolerance(mesh: trimesh.Trimesh, eps: float) -> float:
    """Numerical distance tolerance, including translated CAD coordinates."""
    bounds = mesh.bounds
    magnitude = float(np.abs(bounds).max()) if bounds is not None else 0.0
    return max(eps * 1e-6, float(np.spacing(magnitude)) * 8)


def _normal_precision(mesh: trimesh.Trimesh, error: float) -> np.ndarray:
    """Euclidean unit-normal change when each triangle vertex moves <= error."""
    if not error:
        return np.zeros(len(mesh.faces))
    edges = mesh.triangles[:, 1:] - mesh.triangles[:, :1]
    cross_error = 2 * error * np.linalg.norm(edges, axis=2).sum(axis=1) + 4 * error**2
    cross_length = 2 * mesh.area_faces
    return np.minimum(2., 2 * cross_error / np.maximum(cross_length - cross_error, 1e-300))


def flat_sheet_dimensions(mesh: trimesh.Trimesh) -> tuple[float, float, float] | None:
    measured = flat_sheet_geometry(mesh)
    return measured[0] if measured is not None else None


def flat_sheet_geometry(mesh: trimesh.Trimesh) -> tuple[tuple[float, float, float], np.ndarray, float] | None:
    """Gauge and in-plane blank extents of a verified straight, flat extrusion.

    Opposing caps must bound all vertices; every other surface must run through
    the gauge. This rejects bosses, pockets, bent sheets and open/multiple bodies
    instead of calling their overall envelope a measured material thickness.
    """
    try:
        if not mesh.is_volume or mesh.body_count != 1:
            return None
        largest_face = int(np.argmax(mesh.area_faces))
        if len(mesh.facets_area) and mesh.facets_area.max() > mesh.area_faces[largest_face]:
            facet = mesh.facets[int(np.argmax(mesh.facets_area))]
            largest_face = int(facet[np.argmax(mesh.area_faces[facet])])
        normal = mesh.face_normals[largest_face]
        vertices = np.asarray(mesh.vertices) - mesh.bounds.mean(axis=0)
        heights = vertices @ normal
        low, high = float(heights.min()), float(heights.max())
        gauge = high - low
        eps = max(1e-4, min(float(np.linalg.norm(mesh.extents)) * 1e-4, .1))
        tol = wall_thickness_tolerance(mesh, eps)
        error = float(mesh.metadata.get("coordinate_error", 0.0))
        if not np.isfinite(error) or error < 0:
            return None
        # If each vertex moves at most e, either triangle edge moves at most
        # 2e. Bound its cross-product change, then the unit-normal change.
        normal_error = _normal_precision(mesh, error)
        precision = 2 * error + float(np.linalg.norm(mesh.extents)) * normal_error[largest_face]
        angular_tol = 1e-7 + normal_error + normal_error[largest_face]
        if np.any(angular_tol >= np.sqrt(.5)):
            return None  # Cap and rim directions cannot be distinguished.
        alignment = np.abs(mesh.face_normals @ normal)
        caps = np.linalg.norm(np.cross(mesh.face_normals, normal), axis=1) <= angular_tol
        if gauge <= tol + precision or not np.all(caps | (alignment <= angular_tol)):
            return None
        cap_heights = heights[mesh.faces[caps]]
        if not np.all((np.abs(cap_heights - low) <= tol + precision) | (np.abs(cap_heights - high) <= tol + precision)):
            return None
        rotation = np.asarray(trimesh.geometry.align_vectors(normal, [0., 0., 1.]))[:3, :3]
        footprint = (vertices @ rotation.T)[:, :2]
        hull = footprint[ConvexHull(footprint).vertices]
        edges = np.roll(hull, -1, axis=0) - hull
        lengths = np.linalg.norm(edges, axis=1)
        directions = edges[lengths > tol] / lengths[lengths > tol, None]
        # Same hull-edge projections as trimesh.oriented_bounds_2D, bounded in
        # memory and with a stable minimum-perimeter tie break for equal areas.
        # ponytail: quadratic hull scan; use rotating calipers if very detailed
        # curved flat outlines make this a measured bottleneck.
        batch = max(1, min(512, _wall_thickness_ray_budget() // len(hull)))
        rectangles = []
        for start in range(0, len(directions), batch):
            axes = directions[start:start + batch]
            widths = np.ptp(axes @ hull.T, axis=1)
            heights_2d = np.ptp((axes[:, ::-1] * [-1, 1]) @ hull.T, axis=1)
            rectangles.extend(zip(widths, heights_2d))
        extents = np.sort(np.asarray(rectangles), axis=1)
        areas = np.prod(extents, axis=1)
        area_tol = tol * float(np.linalg.norm(np.ptp(hull, axis=0))) * 4
        candidates = extents[areas <= areas.min() + area_tol]
        widths = candidates[int(np.argmin(candidates.sum(axis=1)))]
        if not np.all(np.isfinite(widths)) or widths[0] <= tol:
            return None
        return (gauge, float(widths[0]), float(widths[1])), hull, float(precision)
    except Exception:
        logger.warning("Flat sheet measurement failed", exc_info=True)
        return None


def sheet_envelope_dimensions(outline, envelope) -> tuple[float, float]:
    """Best in-plane orientation for a particular rectangular machine bed.

    Between hull-edge angles the four supporting vertices stay fixed. Each
    span is a positive sinusoid (concave); the maximum normalized span can
    minimize only at an interval endpoint or where the two spans cross.
    Checking both bed-axis assignments therefore covers every orientation.
    """
    hull = np.asarray(outline, dtype=np.float64)
    edges = np.roll(hull, -1, axis=0) - hull
    angles = np.unique(np.r_[0., np.mod(np.arctan2(edges[:, 1], edges[:, 0]), np.pi / 2), np.pi / 2])
    mids = (angles[1:] + angles[:-1]) / 2
    candidates = list(angles)
    batch = max(1, min(512, _wall_thickness_ray_budget() // len(hull)))
    for start in range(0, len(mids), batch):
        theta = mids[start:start + batch]
        u = np.column_stack([np.cos(theta), np.sin(theta)])
        v = u[:, ::-1] * [-1, 1]
        x, y = u @ hull.T, v @ hull.T
        dx = hull[x.argmax(axis=1)] - hull[x.argmin(axis=1)]
        dy = hull[y.argmax(axis=1)] - hull[y.argmin(axis=1)]
        for width, height in (envelope, envelope[::-1]):
            a = dx[:, 0] / width - dy[:, 1] / height
            b = dx[:, 1] / width + dy[:, 0] / height
            roots = np.mod(np.arctan2(-a, b), np.pi)
            inside = (roots >= angles[start:start + len(theta)]) & (roots <= angles[start + 1:start + len(theta) + 1])
            candidates.extend(roots[inside])
    best, best_ratio = (float("inf"), float("inf")), float("inf")
    for start in range(0, len(candidates), batch):
        theta = np.asarray(candidates[start:start + batch])
        u = np.column_stack([np.cos(theta), np.sin(theta)])
        dims = np.sort(np.column_stack([np.ptp(u @ hull.T, axis=1),
                                        np.ptp((u[:, ::-1] * [-1, 1]) @ hull.T, axis=1)]), axis=1)
        ratios = (dims / np.sort(envelope)).max(axis=1)
        i = int(ratios.argmin())
        if ratios[i] < best_ratio:
            best, best_ratio = (float(dims[i, 0]), float(dims[i, 1])), float(ratios[i])
    return best


def _wall_sample_points(mesh: trimesh.Trimesh) -> np.ndarray:
    if mesh.metadata.get("coordinate_error"):
        # Symmetric CAD centroid rays often hit an export diagonal exactly.
        # A fixed interior barycentric point avoids that common ambiguous hit.
        return np.einsum("ijk,j->ik", mesh.triangles, [1 / 2, 1 / 3, 1 / 6])
    return np.asarray(mesh.triangles_center)


def _compute_wall_thickness(
    mesh: trimesh.Trimesh,
    normals: np.ndarray,
    centroids: np.ndarray,
    eps: float,
    upper_bounds: np.ndarray | None = None,
) -> np.ndarray:
    """Measure per-face wall thickness via inward ray cast.

    For each face, fires one ray from slightly outside the surface along -normal.
    With source rounding, prefer the persistent hit having the smallest upper
    bound and retain its actual distance. Otherwise retain the nearest valid
    hit. A finite raw value without a finite bound is an uncertain estimate.

    Returns an array of length N_faces. Uncomputable faces get np.inf, which
    analyzers interpret as 'unknown' rather than 'thick'.
    """
    centroids = _wall_sample_points(mesh)
    n = len(centroids)
    thickness = np.full(n, np.inf, dtype=np.float64)
    if n == 0:
        return thickness

    threshold = _raycast_sample_threshold()
    if n > threshold:
        return _compute_wall_thickness_sampled(mesh, normals, centroids, eps, n, upper_bounds)

    # Below threshold we cast one ray per face — but in memory-bounded batches,
    # so even here peak RSS is capped instead of spiking to gigabytes.
    origins = centroids + normals * eps  # do not step past a thin opposite wall
    directions = -normals
    source_face_idx = np.arange(n, dtype=np.int64)
    return _cast_inward_rays_batched(mesh, origins, directions, eps, source_face_idx, upper_bounds=upper_bounds)


def _cast_inward_rays_batched(
    mesh: trimesh.Trimesh,
    origins: np.ndarray,
    directions: np.ndarray,
    eps: float,
    source_face_idx: np.ndarray,
    *,
    source_points: np.ndarray | None = None,
    upper_bounds: np.ndarray | None = None,
) -> np.ndarray:
    """Cast inward rays in memory-bounded batches; return per-ray hit distances.

    ``source_face_idx[i]`` is the mesh-face index ray ``i`` originates from,
    used to drop self-hits. Returns an array of length ``len(origins)`` with the
    inward distance from the original face, not the offset ray origin (``np.inf``
    where none). When requested, upper_bounds selects a persistent hit and the
    returned distance stays paired with that hit, even if a closer hit is uncertain.

    The pure-Python ``RayMeshIntersector`` allocates (rays × candidate-triangle)
    intermediates *per call*. Casting only ``WALL_THICKNESS_RAY_BATCH`` rays at a
    time — and scatter-min'ing results into the output as we go — caps the
    working set to a small multiple of one batch, independent of face count.
    """
    m = len(origins)
    out = np.full(m, np.inf, dtype=np.float64)
    if m == 0:
        return out

    # Adaptive batch: cap (rays × faces) to the budget so peak RSS stays flat
    # regardless of face count, then clamp to a sane [8, max] range.
    n_faces = max(1, len(mesh.faces))
    max_batch = _wall_thickness_ray_batch()
    budget = _wall_thickness_ray_budget()
    batch = int(min(max_batch, max(8, budget // n_faces)))
    # Reject numerical self-hits without discarding walls thinner than the
    # scale-dependent ray offset. Account for translated CAD coordinates too.
    surface_tol = wall_thickness_tolerance(mesh, eps)
    error = float(mesh.metadata.get("coordinate_error", 0.0))
    normal_error = _normal_precision(mesh, error) if upper_bounds is not None else np.empty(0)
    samples = _wall_sample_points(mesh) if source_points is None else source_points
    for start in range(0, m, batch):
        stop = min(start + batch, m)
        b_origins = origins[start:stop]
        b_directions = directions[start:stop]
        b_source = source_face_idx[start:stop]
        try:
            locs, idx_ray, idx_tri = mesh.ray.intersects_location(
                ray_origins=b_origins,
                ray_directions=b_directions,
                multiple_hits=True,
            )
        except Exception:
            logger.warning(
                "wall-thickness ray batch [%d:%d] failed (eps=%.3g)",
                start, stop, eps, exc_info=True,
            )
            continue
        if len(locs) == 0:
            continue

        # Measure from the actual surface; the offset must not bias thickness.
        # Signed projection also excludes any hit outside the source surface.
        reference = samples[b_source] if source_points is None else samples[start:stop]
        offsets = locs - reference[idx_ray]
        dists = np.einsum("ij,ij->i", offsets, b_directions[idx_ray])
        valid = (idx_tri != b_source[idx_ray]) & (dists > surface_tol)
        if np.any(valid):
            np.minimum.at(out, start + idx_ray[valid], dists[valid])
            if upper_bounds is not None:
                rays, targets, distances = idx_ray[valid], idx_tri[valid], dists[valid]
                if not error:
                    np.minimum.at(upper_bounds, start + rays, distances)
                    continue
                source_error = normal_error[b_source[rays]]
                denominator = (np.abs(np.einsum("ij,ij->i", b_directions[rays], mesh.face_normals[targets]))
                               - source_error - normal_error[targets])
                bound = np.full(len(rays), np.inf)
                positive = denominator > 0
                bound[positive] = (2 * error + distances[positive] * source_error[positive]) / denominator[positive]
                triangles = mesh.triangles[targets]
                edges = np.roll(triangles, -1, axis=1) - triangles
                edge_distance = np.linalg.norm(np.cross(edges, locs[valid, None] - triangles), axis=2)
                edge_distance /= np.maximum(np.linalg.norm(edges, axis=2), 1e-300)
                # A corresponding plane hit must stay forward and inside its
                # triangle. A new nearer hit can only make the wall thinner.
                persistent = ((distances > bound + surface_tol) &
                              (edge_distance.min(axis=1) > 2 * error + distances * source_error + bound))
                candidates = np.flatnonzero(persistent)
                order = candidates[np.lexsort(((distances + bound)[candidates], rays[candidates]))]
                _, first = np.unique(rays[order], return_index=True)
                chosen = order[first]
                # Keep the measured chord paired with the hit that supplies
                # the bound, even when a closer hit is ambiguous.
                upper_bounds[start + rays[chosen]] = (distances + bound)[chosen]
                out[start + rays[chosen]] = distances[chosen]

    return out


def _compute_wall_thickness_sampled(
    mesh: trimesh.Trimesh,
    normals: np.ndarray,
    centroids: np.ndarray,
    eps: float,
    n: int,
    upper_bounds: np.ndarray | None = None,
) -> np.ndarray:
    """Sampled wall thickness: ray-cast ~5000 faces (batched), propagate via KDTree."""
    centroids = _wall_sample_points(mesh)
    thickness = np.full(n, np.inf, dtype=np.float64)
    stride = max(1, n // 5000)
    sample_idx = np.arange(0, n, stride)

    origins = centroids[sample_idx] + normals[sample_idx] * eps
    directions = -normals[sample_idx]

    # Reuse the memory-bounded batched caster. `sample_idx` doubles as the
    # per-ray source-face index used to drop self-hits.
    sampled_upper = np.full(len(sample_idx), np.inf) if upper_bounds is not None else None
    sampled_thickness = _cast_inward_rays_batched(
        mesh, origins, directions, eps, sample_idx, upper_bounds=sampled_upper
    )
    if upper_bounds is not None:
        upper_bounds[sample_idx] = sampled_upper
    if not np.any(np.isfinite(sampled_thickness)):
        return thickness

    # Assign sampled values
    thickness[sample_idx] = sampled_thickness

    # Propagate to unsampled faces via KDTree nearest-neighbor
    unsampled_mask = np.ones(n, dtype=bool)
    unsampled_mask[sample_idx] = False
    unsampled_idx = np.where(unsampled_mask)[0]

    if len(unsampled_idx) > 0 and np.any(np.isfinite(sampled_thickness)):
        finite_mask = np.isfinite(sampled_thickness)
        if np.any(finite_mask):
            finite_sample_idx = sample_idx[finite_mask]
            tree = KDTree(centroids[finite_sample_idx])
            _, nn_idx = tree.query(centroids[unsampled_idx], k=1)
            thickness[unsampled_idx] = thickness[finite_sample_idx[nn_idx]]

    logger.info(
        "Sampled wall thickness: %d/%d faces ray-cast, %d propagated via KDTree",
        len(sample_idx), n, len(unsampled_idx),
    )
    return thickness


# ──────────────────────────────────────────────────────────────
# Ingest decimation (bounds every O(faces) op, not just wall thickness)
# ──────────────────────────────────────────────────────────────
def _maybe_decimate(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, dict | None]:
    """Decimate meshes over MAX_ANALYSIS_FACES so the engine stays memory-bounded.

    Returns ``(mesh, decimation_info)``. ``decimation_info`` is ``None`` when the
    mesh is under the cap (the common case — typical parts are untouched); when
    decimation runs it is a dict recording the original / analysis face counts
    and the strategy, so results can be honestly labelled as computed on an
    approximated mesh. Never raises: on any failure it falls back to the
    original mesh (the wall-thickness path is independently bounded).
    """
    try:
        n = len(mesh.faces)
    except Exception:
        return mesh, None

    cap = _max_analysis_faces()
    if n <= cap:
        return mesh, None

    reduced, strategy = _decimate_to(mesh, cap)
    if reduced is None or len(reduced.faces) == 0 or len(reduced.faces) >= n:
        logger.warning(
            "Decimation did not reduce faces (%d, strategy=%s); keeping original "
            "mesh — analysis remains bounded via sampled/batched ray casts.",
            n, strategy,
        )
        return mesh, {
            "attempted": True,
            "succeeded": False,
            "original_faces": int(n),
            "analysis_faces": int(n),
            "strategy": strategy,
        }

    logger.info(
        "Decimated mesh for analysis: %d -> %d faces via %s "
        "(MAX_ANALYSIS_FACES=%d). Wall-thickness/draft numbers are computed on "
        "the approximation; a DECIMATED_MESH warning is surfaced to the user "
        "via base_analyzer.decimation_issue.",
        n, len(reduced.faces), strategy, cap,
    )
    if "coordinate_error" in mesh.metadata:
        reduced.metadata["coordinate_error"] = mesh.metadata["coordinate_error"]
    return reduced, {
        "attempted": True,
        "succeeded": True,
        "original_faces": int(n),
        "analysis_faces": int(len(reduced.faces)),
        "strategy": strategy,
    }


def _decimate_to(mesh: trimesh.Trimesh, target: int) -> tuple[trimesh.Trimesh | None, str]:
    """Reduce ``mesh`` to roughly ``target`` faces. Returns ``(mesh|None, strategy)``.

    Prefers trimesh's quadric decimation (highest quality) when its optional
    backend (``fast_simplification``) is installed; otherwise falls back to a
    dependency-free uniform grid vertex-clustering decimation.
    """
    # 1. Preferred: quadric decimation (graceful no-op if backend absent).
    try:
        d = mesh.simplify_quadric_decimation(face_count=int(target))
        if d is not None and 0 < len(d.faces) <= int(target * 1.2):
            return d, "quadric"
    except Exception:
        pass

    # 2. Fallback: uniform grid vertex clustering (numpy-only).
    try:
        d = _vertex_cluster_decimate(mesh, int(target))
        if d is not None and len(d.faces) > 0:
            return d, "vertex_cluster"
    except Exception:
        logger.warning("vertex-cluster decimation failed", exc_info=True)

    return None, "none"


def _vertex_cluster_decimate(
    mesh: trimesh.Trimesh, target: int, max_iter: int = 6
) -> trimesh.Trimesh | None:
    """Dependency-free uniform decimation via grid vertex clustering.

    Snaps vertices onto a uniform grid, merges each cell to its centroid, drops
    faces that collapse to a degenerate triangle, and rebuilds. Face count is
    driven by the grid resolution; we iterate resolution downward until the
    result is at/under ``target``. Deterministic and O(V log V) in memory.
    """
    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = np.asarray(mesh.faces, dtype=np.int64)
    if len(v) == 0 or len(f) == 0:
        return None

    lo = v.min(axis=0)
    span = float((v.max(axis=0) - lo).max())
    if span <= 0:
        return None

    n_faces = len(f)
    # face count scales ~ resolution**2 for a surface; seed from that and adjust.
    resolution = max(4, int(round(np.sqrt(max(1, target) / 3.0))))
    best: trimesh.Trimesh | None = None

    for _ in range(max_iter):
        cell = span / resolution
        grid = np.floor((v - lo) / cell).astype(np.int64)
        _, inv = np.unique(grid, axis=0, return_inverse=True)
        inv = inv.ravel()

        reps = np.zeros((inv.max() + 1, 3), dtype=np.float64)
        counts = np.zeros(inv.max() + 1, dtype=np.float64)
        np.add.at(reps, inv, v)
        np.add.at(counts, inv, 1.0)
        reps /= counts[:, None]

        nf = inv[f]
        good = (
            (nf[:, 0] != nf[:, 1])
            & (nf[:, 1] != nf[:, 2])
            & (nf[:, 0] != nf[:, 2])
        )
        nf = nf[good]
        if len(nf) == 0:
            resolution = int(resolution * 1.5) + 1
            continue

        candidate = trimesh.Trimesh(vertices=reps, faces=nf, process=True)
        best = candidate
        cf = len(candidate.faces)
        if 0 < cf <= target:
            return candidate
        if cf >= n_faces:  # not coarse enough to help — coarsen harder
            resolution = max(4, int(resolution * 0.6))
            continue
        # over target but reducing: nudge resolution toward the target (~res**2)
        resolution = max(4, int(resolution * np.sqrt(target / max(cf, 1)) * 0.9))

    return best


def _safe_attr(obj: Any, name: str, default):
    try:
        return getattr(obj, name)
    except Exception:
        logger.warning("getattr %s failed", name, exc_info=True)
        return default
