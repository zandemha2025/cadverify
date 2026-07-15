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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import logging

import numpy as np
import trimesh
from scipy.spatial import KDTree

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
    edge_lengths: np.ndarray         # (E,) float
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

        wall_thickness = _compute_wall_thickness(mesh, normals, centroids, scale_eps)

        edge_lengths = _safe_attr(mesh, "edges_unique_length", default=np.empty(0))
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

        try:
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
            edge_lengths=np.asarray(edge_lengths, dtype=np.float64),
            dihedral_angles_rad=np.asarray(dihedral, dtype=np.float64),
            face_adjacency=np.asarray(adjacency, dtype=np.int64),
            concave_mask=concave_mask,
            bodies=bodies,
            body_volumes=body_volumes,
            facet_groups=facet_groups,
            metadata={"decimation": decimation} if decimation else {},
        )


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
def _compute_wall_thickness(
    mesh: trimesh.Trimesh,
    normals: np.ndarray,
    centroids: np.ndarray,
    eps: float,
) -> np.ndarray:
    """Measure per-face wall thickness via inward ray cast.

    For each face, fires one ray from slightly-inside the surface along -normal.
    The nearest valid hit (not the source face itself) is the wall thickness.
    Old code did this with a Python per-face loop; this version uses
    np.minimum.at to scatter-min distances back to their source rays, which is
    strictly vectorized and correctly handles the multi-hit case.

    Returns an array of length N_faces. Uncomputable faces get np.inf, which
    analyzers interpret as 'unknown' rather than 'thick'.
    """
    n = len(centroids)
    thickness = np.full(n, np.inf, dtype=np.float64)
    if n == 0:
        return thickness

    threshold = _raycast_sample_threshold()
    if n > threshold:
        return _compute_wall_thickness_sampled(mesh, normals, centroids, eps, n)

    # Below threshold we cast one ray per face — but in memory-bounded batches,
    # so even here peak RSS is capped instead of spiking to gigabytes.
    origins = centroids - normals * eps  # start just inside the surface
    directions = -normals
    source_face_idx = np.arange(n, dtype=np.int64)
    return _cast_inward_rays_batched(mesh, origins, directions, eps, source_face_idx)


def _cast_inward_rays_batched(
    mesh: trimesh.Trimesh,
    origins: np.ndarray,
    directions: np.ndarray,
    eps: float,
    source_face_idx: np.ndarray,
) -> np.ndarray:
    """Cast inward rays in memory-bounded batches; return per-ray min thickness.

    ``source_face_idx[i]`` is the mesh-face index ray ``i`` originates from,
    used to drop self-hits. Returns an array of length ``len(origins)`` with the
    nearest non-self hit distance per ray (``np.inf`` where none).

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

        # distance from each hit to its (batch-local) source ray origin
        dists = np.linalg.norm(locs - b_origins[idx_ray], axis=1)

        # Exclude self-hits (source face reports itself) and numerical noise
        # right at the origin (< 2*eps).
        valid = (idx_tri != b_source[idx_ray]) & (dists > 2.0 * eps)
        if np.any(valid):
            np.minimum.at(out, start + idx_ray[valid], dists[valid])

    return out


def _compute_wall_thickness_sampled(
    mesh: trimesh.Trimesh,
    normals: np.ndarray,
    centroids: np.ndarray,
    eps: float,
    n: int,
) -> np.ndarray:
    """Sampled wall thickness: ray-cast ~5000 faces (batched), propagate via KDTree."""
    thickness = np.full(n, np.inf, dtype=np.float64)
    stride = max(1, n // 5000)
    sample_idx = np.arange(0, n, stride)

    origins = centroids[sample_idx] - normals[sample_idx] * eps
    directions = -normals[sample_idx]

    # Reuse the memory-bounded batched caster. `sample_idx` doubles as the
    # per-ray source-face index used to drop self-hits.
    sampled_thickness = _cast_inward_rays_batched(
        mesh, origins, directions, eps, sample_idx
    )
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
