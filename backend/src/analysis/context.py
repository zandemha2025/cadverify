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

import math
import os
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from itertools import permutations, product
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


# trimesh's closest_point measures every point against every triangle out to the
# point's nearest vertex, all at once (about 350 bytes a pair). From inside a
# finely meshed round pin that is the whole pin for every point: 48 interior
# points of an 8,288-sided pin took 193 MB. Points are grouped so that one call
# measures at most this many pairs (about 70 MB).
_NEAREST_PAIRS_PER_CALL = 200_000


def _closest_points_bounded(mesh: trimesh.Trimesh, points: np.ndarray):
    """``mesh.nearest.on_surface(points)``: (closest points, distances, triangle ids), bounded.

    trimesh's own query (``closest_point``), called on groups of points whose candidate
    triangles (the faces whose boxes reach the box around each point out to its
    nearest vertex, as trimesh finds them) total at most
    ``_NEAREST_PAIRS_PER_CALL``. Each point's answer depends only on its own
    candidates, so every answer is exactly trimesh's.
    """
    points = np.asarray(points, dtype=np.float64)
    n, faces = len(points), len(mesh.faces)
    if n == 0 or n * faces <= _NEAREST_PAIRS_PER_CALL:
        return mesh.nearest.on_surface(points)
    # The counts only group the points (any grouping gives the same answers), so
    # the mesh's cached vertex tree serves, unreferenced vertices and all.
    reach = mesh.kdtree.query(points)[0] + trimesh.tol.merge
    step = max(1, _NEAREST_PAIRS_PER_CALL // faces)  # at most this many pairs of ids at once
    counts = np.empty(n, dtype=np.int64)
    try:
        for s in range(0, n, step):
            r = reach[s:s + step, None]
            _ids, c = mesh.triangles_tree.intersection_v(np.ascontiguousarray(points[s:s + step] - r),
                                                         np.ascontiguousarray(points[s:s + step] + r))
            counts[s:s + step] = c
    except Exception:  # an rtree without the batch call: assume every face is a candidate
        counts[:] = faces
    total = np.cumsum(counts)
    pieces = []
    start = 0
    while start < n:
        done = int(total[start - 1]) if start else 0
        end = max(start + 1, int(np.searchsorted(total, done + _NEAREST_PAIRS_PER_CALL, side="right")))
        pieces.append(mesh.nearest.on_surface(points[start:end]))
        start = end
    return tuple(np.concatenate([piece[k] for piece in pieces]) for k in range(3))


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


def enclosing_box_dimensions(mesh: trimesh.Trimesh) -> tuple[tuple[float, ...], str]:
    """An enclosing stock/build candidate, padded for source-coordinate error."""
    blank = np.sort(mesh.extents)
    basis = "file-axis fallback"
    error = float(mesh.metadata.get("coordinate_error", 0.0))
    if not np.isfinite(error) or error < 0:
        raise ValueError("Invalid source coordinate uncertainty")
    try:
        # ponytail: bounded stock candidates, not a certified minimum or setup.
        # Large hulls avoid trimesh's quadratic oriented-bound projection arrays.
        if len(mesh.convex_hull.vertices) <= 2048:
            _, candidate = trimesh.bounds.oriented_bounds(mesh)
            candidate_basis = "oriented candidate"
        else:
            axes = mesh.principal_inertia_transform[:3, :3]
            candidate = np.ptp((mesh.vertices - mesh.bounds.mean(axis=0)) @ axes.T, axis=0)
            candidate_basis = "principal-axis candidate"
        if np.all(np.isfinite(candidate)) and np.all(candidate > 0):
            blank = np.sort(candidate)
            basis = candidate_basis
    except Exception:
        pass  # The uploaded-axis box remains an enclosing, labeled fallback.
    return tuple(float(d) + 2 * error for d in blank), basis


def enclosing_cylinder_dimensions(mesh, features=None):
    """Measured axial length and enclosing diameter, padded for source error."""
    from src.analysis.features.base import turning_dimensions

    # ponytail: reuse the detected revolution axis; not a minimum-cylinder search.
    measured = turning_dimensions(mesh, features)
    if measured is None:
        return None
    error = float(mesh.metadata.get("coordinate_error", 0.0))
    if not np.isfinite(error) or error < 0:
        raise ValueError("Invalid source coordinate uncertainty")
    # Both radial and axial endpoint displacement is bounded by sqrt(3)*error.
    return tuple(d + 2 * np.sqrt(3) * error for d in measured[:2])


def fitting_box_dimensions(box, envelope, cylinder=None) -> tuple[float, ...] | None:
    """A proved enclosing-box placement, expressed in the machine's XYZ axes.

    Preserve existing axis-permutation setups; otherwise reuse the continuous
    2D bed-fit check on each box face, then try body-diagonal placements.
    A measured cylindrical enclosure can establish a fit missed by the box.
    None means no setup was established, not a proof of non-fit.
    """
    if len(box) != 3 or len(envelope) != 3 or any(
        not np.isfinite(v) or v <= 0 for v in (*box, *envelope)
    ):
        return None
    fits = lambda d: all(v <= limit + 1e-9 for v, limit in zip(d, envelope))
    height_order = lambda d: (d[2], d[0], d[1])
    direct = [d for d in permutations(box) if fits(d)]
    if direct:
        return min(direct, key=height_order)
    candidates = []
    for dims in permutations(box):
        for fixed in range(3):
            if dims[fixed] > envelope[fixed] + 1e-9:
                continue
            i, j = [axis for axis in range(3) if axis != fixed]
            a, b = dims[i], dims[j]
            plane = sheet_envelope_dimensions(((0, 0), (a, 0), (a, b), (0, b)),
                                              (envelope[i], envelope[j]))
            candidate = list(dims)
            candidate[i], candidate[j] = plane if envelope[i] <= envelope[j] else plane[::-1]
            if fits(candidate):
                candidates.append(tuple(candidate))
    if candidates:
        return min(candidates, key=height_order)
    # ponytail: six constructive 3D placements, not a global orientation search.
    # Align the longest box edge with the chamber diagonal. Each orthonormal
    # frame proves an enclosing XYZ box; the two cross-section edges may swap.
    along = np.array(envelope, dtype=float)
    along /= np.max(along)
    along /= np.linalg.norm(along)
    small, middle, long = sorted(box)
    for axis in np.eye(3):
        across = np.cross(along, axis)
        norm = np.linalg.norm(across)
        if norm == 0:
            continue
        across /= norm
        up = np.cross(along, across)
        frame = np.column_stack((across, up, along))
        for cross_section in ((small, middle), (middle, small)):
            candidate = tuple(float(d) for d in np.abs(frame) @ (*cross_section, long))
            if fits(candidate):
                candidates.append(candidate)
    if candidates:
        return min(candidates, key=height_order)
    if cylinder is not None and len(cylinder) == 2 and all(np.isfinite(v) and v > 0 for v in cylinder):
        length, diameter = cylinder
        # For unit cylinder axis u, each extent is L*|u_i| + D*sqrt(1-u_i²).
        # Its concavity leaves at most two allowed intervals per component.
        # Work in squared components: the only coupling is sx + sy + sz = 1.
        radius = np.hypot(length, diameter)
        axial, radial = length / radius, diameter / radius
        intervals = []
        for cap in envelope:
            allowed = []
            if cap >= radius:
                allowed = [(0.0, 1.0)]
            else:
                ratio = cap / radius
                root = np.sqrt(max(0.0, 1 - ratio**2))
                if cap >= diameter:
                    allowed.append((0.0, max(0.0, axial * ratio - radial * root)**2))
                if cap >= length:
                    allowed.append((min(1.0, axial * ratio + radial * root)**2, 1.0))
            intervals.append(allowed)
        for (lx, hx), (ly, hy), (lz, hz) in product(*intervals):
            zlow, zhigh = max(lz, 1 - hx - hy), min(hz, 1 - lx - ly)
            if zlow > zhigh + 1e-14:
                continue
            # The extent is concave in each squared component too: minimum
            # build height, then X/Y, occurs at these feasible endpoints.
            for z in (zlow, zhigh):
                for x in (max(lx, 1 - z - hy), min(hx, 1 - z - ly)):
                    squared = np.clip((x, 1 - z - x, z), 0, 1)
                    squared /= squared.sum()
                    candidate = tuple(float(d) for d in
                                      length * np.sqrt(squared) + diameter * np.sqrt(1 - squared))
                    if fits(candidate):
                        candidates.append(candidate)
    return min(candidates, key=height_order, default=None)


def minimum_width_lower_bound(mesh: trimesh.Trimesh) -> float:
    """A sphere inside the convex hull bounds the part's width in every direction."""
    try:
        hull = mesh.convex_hull
        if not hull.is_volume:
            return 0.0
        # ponytail: sphere at the hull centroid; not the exact minimum caliper width.
        distances = np.einsum("ij,ij->i", hull.triangles_center - hull.center_mass, hull.face_normals)
        diameter = 2 * float(distances.min())
        return max(0.0, diameter) if np.isfinite(diameter) else 0.0
    except Exception:
        logger.warning("Minimum-width bound unavailable", exc_info=True)
        return 0.0


def envelope_nonfit_bound(box, envelope, minimum_width=0.0, precision=0.0):
    """Necessary geometric bounds; never infer non-fit from a failed box search.

    box is a tight measured projection, without source-error padding. A source
    coordinate error of precision/2 per axis moves a vertex by at most sqrt(3)
    times that amount; allow both ends of every measured span.
    """
    if len(box) != 3 or len(envelope) != 3 or any(
        not np.isfinite(v) or v <= 0 for v in (*box, *envelope)
    ):
        return None
    error = np.sqrt(3) * precision
    for axis, need, have, part, space in (
        ("minimum_width_mm", minimum_width - error, min(envelope), "wide at its narrowest", "shortest side of the work area"),
        ("diameter_mm", max(box) - error, np.linalg.norm(envelope), "corner to corner", "work-area diagonal"),
    ):
        if need > have:
            # A part's narrowest width can't exceed the box's shortest side, and its
            # span can't exceed the diagonal, in any orientation. The part figure is
            # rounded down and the space figure up, so the sentence never overstates.
            shown_need = math.floor(need * 10) / 10
            shown_have = math.ceil(have * 10) / 10
            human = (f"Part is at least {shown_need:g}mm {part} > the {shown_have:g}mm {space}, "
                     "so it fits in no orientation.")
            return axis, float(need), float(have), human
    return None


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
    # Faces whose own inward ray was cast (the rest copy a nearby sample).
    wall_thickness_sampled: np.ndarray | None = None
    edge_length_precision: np.ndarray | None = None
    edge_topology_stable: bool = True

    @cached_property
    def enclosing_box(self):
        return enclosing_box_dimensions(self.mesh)

    @cached_property
    def minimum_width_bound(self):
        return minimum_width_lower_bound(self.mesh)

    @cached_property
    def enclosing_cylinder(self):
        return enclosing_cylinder_dimensions(self.mesh, self.features)

    @cached_property
    def flat_sheet_geometry(self):
        return flat_sheet_geometry(self.mesh)

    @cached_property
    def sealed_voids(self) -> list[dict[str, Any]]:
        """Sealed internal voids: closed shells nested inside the material.

        Each is ``{"volume_mm3", "center", "bounds", "shell"}`` of the void's own shell
        (``shell_nesting_depths``: an odd nesting depth). No opening reaches
        it, so nothing outside the part can touch its surface.
        """
        depths = shell_nesting_depths(self.bodies)
        if depths is None:
            return []
        voids = []
        for body, volume, depth in zip(self.bodies, self.body_volumes, depths):
            if depth % 2 == 1 and volume > 0:
                voids.append({
                    "volume_mm3": float(volume),
                    "center": tuple(float(c) for c in np.asarray(body.bounds).mean(axis=0)),
                    "bounds": np.asarray(body.bounds, dtype=np.float64),
                    "shell": body,
                })
        return voids

    @cached_property
    def ribs(self) -> list[dict[str, Any]]:
        """Thin plates standing out from the rest of the part along one edge.

        A plate is two flat faces facing away from each other, a thickness
        ``t`` apart, overlapping face to face. It is a rib (or a fin, flange,
        bracket leg) when it joins the rest of the part along one straight
        root (concave edges in a line) and is free on its other edges; its
        height is how far it reaches from that root. A flat plate on its own
        joins nothing and is not a rib; a box wall joined on three sides is a
        wall, not a rib, and an L corner (bracket legs) is a corner: a rib
        stands on a face that carries on past both of its sides. Each entry: ``thickness_mm``, ``height_mm``,
        ``base_thickness_mm`` (the plate it stands on, when that is a measured
        plate too, else None) and ``center``.
        """
        if self.metadata.get("decimation", {}).get("succeeded"):
            return []
        try:
            return detect_ribs(self.mesh, self.facet_groups, self.face_areas, self.normals,
                               wall_thickness_tolerance(self.mesh, self.scale_eps)
                               + 2.0 * float(self.mesh.metadata.get("coordinate_error", 0.0)),
                               wall_thickness=self.wall_thickness)
        except Exception:
            logger.warning("Rib detection failed", exc_info=True)
            return []

    @cached_property
    def angle_error_deg(self) -> np.ndarray | None:
        """Per-face normal uncertainty from source rounding, degrees (None: exact)."""
        return rounding_angle_error_deg(self.mesh)

    @cached_property
    def inside_corners(self) -> "InsideCorners":
        """Inside corners a rotating cutter leaves rounded (see ``inside_corners``)."""
        try:
            return inside_corners(self.mesh, self.normals, self.face_adjacency,
                                  self.dihedral_angles_rad, self.concave_mask,
                                  self.facet_groups, self.scale_eps)
        except Exception:
            logger.warning("Inside-corner measurement failed", exc_info=True)
            return InsideCorners(0, 0.0, np.empty(0, dtype=np.int64))

    @cached_property
    def rounded_inside_corners(self) -> list[dict[str, Any]]:
        """Rounded inside corners between walls (see ``rounded_inside_corners``); needs ``features``."""
        try:
            return rounded_inside_corners(self.mesh, self.features, self.normals, self.centroids,
                                          self.face_adjacency, self.scale_eps)
        except Exception:
            logger.warning("Rounded inside-corner measurement failed", exc_info=True)
            return []

    @cached_property
    def wall_draft(self) -> "WallDraft":
        """Side walls, their draft and which face the inside of the part (see ``wall_draft``)."""
        try:
            return wall_draft(self.mesh, self.normals, self.face_areas, self.centroids,
                              self.face_adjacency, self.dihedral_angles_rad,
                              self.angle_error_deg, self.scale_eps)
        except Exception:
            logger.warning("Wall draft measurement failed; reading the triangles alone", exc_info=True)
            faces, draft = _sidewalls_of(self.normals)
            return WallDraft(faces, draft, np.full(len(faces), DRAFT_TOL_DEG), np.zeros(len(faces), bool),
                             np.full(len(faces), -1, dtype=np.int64), False, 0)

    @cached_property
    def cad_face_ids(self) -> np.ndarray | None:
        """The B-rep face of each triangle, when the STEP/IGES mesher kept it."""
        return cad_face_ids(self.mesh)

    @cached_property
    def straight_profile_geometry(self):
        """Verify extrusion geometry without treating the file's Z as the wire axis."""
        if self.metadata.get("decimation", {}).get("succeeded") or not self.mesh.is_volume:
            return None
        if self.flat_sheet_geometry is not None:
            return self.flat_sheet_geometry
        normals = self.mesh.face_normals
        first = int(np.argmax(self.mesh.area_faces))
        second = int(np.argmin(np.abs(normals @ normals[first])))
        # An extrusion's normals are axial or transverse. If neither of two
        # independent normals is axial, their cross product is. Choose an
        # actual face so the existing source-normal precision bound still holds.
        axis = np.cross(normals[first], normals[second])
        third = int(np.argmax(np.abs(normals @ axis)))
        for face in dict.fromkeys((first, second, third)):
            measured = flat_sheet_geometry(self.mesh, normal_face=face)
            if measured is not None:
                return measured
        return None

    @cached_property
    def convex_support_planes(self):
        """Certify every source triangle against an outward hull support plane.

        Local adjacency alone cannot prove convexity. Matching the source normal
        only nominates a plane; all three vertices must lie on that global plane.
        This avoids one nearest-surface search per triangle on dense planar CAD.
        Coordinates are centered and work is batched to retain the memory bound.
        """
        mesh = self.mesh
        if (self.metadata.get("decimation", {}).get("succeeded")
                or mesh.metadata.get("coordinate_error", 0.0) != 0
                or not mesh.is_volume or mesh.body_count != 1
                or np.any(self.face_areas <= 0)
                or not np.all(np.linalg.norm(self.normals, axis=1) > .99)):
            return None
        tol = wall_thickness_tolerance(mesh, self.scale_eps)
        projections = mesh.face_adjacency_projections
        if len(projections) and np.all(np.isfinite(projections) & (projections <= tol)):
            try:
                hull = mesh.convex_hull
                normals = hull.face_normals
                center = mesh.bounds.mean(axis=0)
                origins = hull.triangles[:, 0] - center
                tree = KDTree(normals)
                batch = _wall_thickness_ray_batch()
                for start in range(0, len(mesh.faces), batch):
                    delta, face = tree.query(self.normals[start:start + batch])
                    if not np.all(np.isfinite(delta) & (delta <= 1e-7)):
                        break
                    offsets = mesh.triangles[start:start + batch] - center - origins[face, None, :]
                    distances = np.einsum("nvi,ni->nv", offsets, normals[face])
                    if not np.all(np.abs(distances) <= tol):
                        break
                else:
                    return origins, normals
            except Exception:
                logger.warning("Convex setup verification failed", exc_info=True)
        return None

    def _rounding_tolerances(self) -> tuple[float, np.ndarray]:
        """Distance tolerance and per-face normal uncertainty from source rounding.

        A binary STL stores float32 coordinates (``coordinate_error``, a few
        nanometres on a 30 mm part). Convexity and setup proofs allow for that
        rounding instead of refusing every binary STL, so an STL and a STEP of
        the same simple part get the same answer.
        """
        mesh = self.mesh
        error = float(mesh.metadata.get("coordinate_error", 0.0))
        tol = wall_thickness_tolerance(mesh, self.scale_eps)
        if not error or not np.isfinite(error):
            return tol, np.zeros(len(self.normals))
        # A vertex moves <= error; a plane through three rounded vertices also
        # tilts. The allowance is capped at _ROUNDING_TILT_CAP (one part per
        # million): a sliver whose rounding tilt is larger keeps the strict
        # test and can only read as "not verified", never as a false proof.
        normal_error = np.minimum(_normal_precision(mesh, error), _ROUNDING_TILT_CAP)
        return tol + 2.0 * error + self.bbox_diag * _ROUNDING_TILT_CAP, normal_error

    @cached_property
    def undercut_free_geometry(self) -> bool:
        """Positive geometry evidence with reorientation; not a toolpath/fixture check."""
        mesh = self.mesh
        if (self.metadata.get("decimation", {}).get("succeeded")
                or not mesh.is_volume or mesh.body_count != 1
                or np.any(self.face_areas <= 0)
                or not np.all(np.linalg.norm(self.normals, axis=1) > .99)):
            return False
        tol, normal_error = self._rounding_tolerances()
        if self.convex_support_planes is not None:
            return True
        if self.straight_profile_geometry is not None:
            return True
        vertices = np.asarray(mesh.vertices) - mesh.bounds.mean(axis=0)
        # ponytail: eight dominant planar faces bound this setup search; leave
        # other orientations unverified until explicit CAM setup axes exist.
        facets = sorted(self.facet_groups, key=lambda f: -float(self.face_areas[f].sum()))[:8]
        for facet in facets:
            reference = int(facet[np.argmax(self.face_areas[facet])])
            normal = self.normals[reference]
            for axis in (normal, -normal):
                # A wall square to the axis within source rounding is not a downward face.
                downward = self.normals @ axis < -1e-7 - normal_error - normal_error[reference]
                heights = vertices @ axis
                # Only the actual planar base is exempt. A percentage band
                # near the bottom can contain a real pocket or closed cavity.
                above = downward & ~np.all(heights[mesh.faces] <= heights.min() + tol, axis=1)
                # Nor is a facet of a round wall leaning by tessellation alone.
                if above.any() and np.all(np.abs(self.normals[above] @ axis) <= _TESSELLATED_LEAN_SIN):
                    above[above] = ~self._tessellation_lean(np.flatnonzero(above), axis)
                if not above.any():
                    return True
        return False

    @cached_property
    def _smooth_adjacency(self) -> tuple[np.ndarray, np.ndarray]:
        """(rows of face_adjacency turning at most 30 degrees, every adjacency's edge length)."""
        edges = np.asarray(self.mesh.face_adjacency_edges)
        vertices = np.asarray(self.mesh.vertices)
        lengths = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1) if len(edges) else np.empty(0)
        smooth = np.flatnonzero(self.dihedral_angles_rad <= math.radians(30.0)) if len(edges) else np.empty(0, dtype=int)
        return smooth, lengths

    def _tessellation_lean(self, faces: np.ndarray, axis: np.ndarray) -> np.ndarray:
        """Which of ``faces`` (leaning down from ``axis``) lean by tessellation only.

        A round wall's facets lean both ways, so over the whole wall they cancel:
        the wall's area times its normal along the axis sums to its projected
        area, which is zero for a straight bore or a turned diameter (up to the
        sliver between its two rim polygons) and the ring between the rims for
        a taper. A face qualifies when it leans less than
        ``_TESSELLATED_LEAN_SIN`` and belongs to a smooth side-wall surface
        (faces within that lean, joined across edges turning at most 30
        degrees) whose projected area is no more negative than its boundary
        length times a thousandth of the part's diagonal. A taper overhanging
        its rim by more than that, or a ledge, stays a downward face.
        """
        if not len(faces):
            return np.zeros(0, dtype=bool)
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components

        along = self.normals @ axis
        wall = np.abs(along) <= _TESSELLATED_LEAN_SIN
        if not wall[faces].any():
            return np.zeros(len(faces), dtype=bool)
        adjacency = self.face_adjacency
        smooth, lengths = self._smooth_adjacency
        a, b = adjacency[smooth, 0], adjacency[smooth, 1]
        joined = wall[a] & wall[b]
        n = len(self.normals)
        graph = coo_matrix((np.ones(int(joined.sum())), (a[joined], b[joined])), shape=(n, n))
        _count, label = connected_components(graph, directed=False)
        net = np.bincount(label[wall], weights=(self.face_areas * along)[wall], minlength=_count)
        # Boundary of each wall surface: adjacencies leaving it (another surface or a non-wall face).
        ea, eb = adjacency[:, 0], adjacency[:, 1]
        leaves = (label[ea] != label[eb]) | (wall[ea] != wall[eb])
        rim = (np.bincount(label[ea[leaves & wall[ea]]], weights=lengths[leaves & wall[ea]], minlength=_count)
               + np.bincount(label[eb[leaves & wall[eb]]], weights=lengths[leaves & wall[eb]], minlength=_count))
        allowed = rim * self.bbox_diag * _TESSELLATED_LEAN_OF_PART
        return wall[faces] & (net[label[faces]] >= -allowed[label[faces]])

    @cached_property
    def z_release_blocked(self) -> np.ndarray | None:
        """Faces a two-part mold opening along Z cannot release (bool per face).

        A face tilted more than 10° from vertical is formed by the mold half on
        the side it faces: an upward face by the half that lifts away along +Z,
        a downward face by the half that drops along -Z. That half can only
        leave if a vertical ray from the face in its direction clears the part.
        A floor inside an open cavity sees out of the opening and passes; the
        underside of an inward lip, the inside of a side hole and the walls of
        a groove are shadowed and fail. Faces within 10° of vertical are side
        walls, judged by the draft check (the same 80–100° band).

        Rays are vertical, so they are cheap with the Embree backend. Without
        it (pure-Python rays, ~0.4 ms each) a mesh with more than
        ``RAYCAST_SAMPLE_THRESHOLD`` faces to cast in one direction is not
        guessed from a sample, because a face's answer does not carry to its
        neighbours (a hole's floor sits next to an open top). ``None`` then, and
        when a ray batch fails, so callers never read "unknown" as a release.
        """
        count = len(self.normals)
        blocked = np.zeros(count, dtype=bool)
        if count == 0:
            return blocked
        mesh = self.mesh
        points = _wall_sample_points(mesh)
        eps = max(self.scale_eps, 2.0 * float(mesh.metadata.get("coordinate_error", 0.0)))
        fast = "embree" in type(mesh.ray).__module__
        for faces, pull in ((np.flatnonzero(self.angles_from_up_deg <= 80.0), 1.0),
                            (np.flatnonzero(self.angles_from_up_deg >= 100.0), -1.0)):
            if len(faces) == 0:
                continue
            if not fast and len(faces) > _raycast_sample_threshold():
                logger.info("Z-release check skipped: %d rays without Embree", len(faces))
                return None
            hits = np.zeros(len(faces), dtype=bool)
            batch = 65536 if fast else _wall_thickness_ray_batch()
            for start in range(0, len(faces), batch):
                chosen = faces[start:start + batch]
                origins = points[chosen] + self.normals[chosen] * eps
                directions = np.tile([0.0, 0.0, pull], (len(chosen), 1))
                try:
                    hits[start:start + batch] = mesh.ray.intersects_any(origins, directions)
                except Exception:
                    logger.warning("Z-release ray batch failed", exc_info=True)
                    return None
            blocked[faces] = hits
        return blocked

    @cached_property
    def bent_sheet(self) -> "BentSheet | None":
        """A constant-gauge sheet bent along parallel lines, when it isn't flat."""
        if self.metadata.get("decimation", {}).get("succeeded") or self.flat_sheet_geometry is not None:
            return None
        return bent_sheet_geometry(self.mesh)

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
                p, distance, face = _closest_points_bounded(self.mesh, facet_points[start:start + batch])
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
            planes = self.convex_support_planes
            if planes is not None:
                # A certified convex solid is the intersection of these inward
                # half-spaces. For an interior point the minimum plane clearance
                # is exactly its nearest-boundary distance (the largest ball
                # centered there), without contains/nearest triangle searches.
                origins, normals = planes
                offsets = np.einsum("ij,ij->i", origins, normals)
                points = points - self.mesh.bounds.mean(axis=0)
                plane_batch = max(1, min(_wall_thickness_ray_batch(),
                    _wall_thickness_ray_budget() // len(normals)))
                best = 0.0
                for start in range(0, len(points), plane_batch):
                    clearance = offsets[None, :] - np.einsum(
                        "pi,fi->pf", points[start:start + plane_batch], normals)
                    inside = np.all(clearance > tol, axis=1)
                    if np.any(inside):
                        best = max(best, float(clearance[inside].min(axis=1).max()) * 2)
                return best if np.isfinite(best) and best > tol else None
            # Distance to any actual triangle bounds nearest-surface distance
            # from above. Try the most promising samples first, then skip only
            # those that cannot improve the measured maximum.
            _, nearest = KDTree(self.centroids).query(points)
            surface = trimesh.triangles.closest_point(self.mesh.triangles[nearest], points)
            upper = np.linalg.norm(points - surface, axis=1)
            order = np.argsort(-upper)
            points, upper = points[order], upper[order]
            best = 0.0
            for start in range(0, len(points), batch):
                candidates = points[start:start + batch]
                candidates = candidates[upper[start:start + batch] + tol > best / 2]
                if not len(candidates):
                    break
                # Concavities, cavities and separate bodies must not turn an
                # exterior clearance into material thickness.
                candidates = candidates[self.mesh.contains(candidates)]
                if len(candidates):
                    _, distance, _ = _closest_points_bounded(self.mesh, candidates)
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
        wall_sampled = _wall_sampled_mask(mesh, len(centroids))

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
            wall_thickness_sampled=wall_sampled,
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


_RIB_MAX_FACETS = 400       # largest flat faces considered for plates
_RIB_PARALLEL_COS = 0.9995   # opposite plate faces within ~1.8 degrees of parallel
_RIB_MAX_PAIRS = 2000        # face pairs outlined at most (each is a polygon overlap)


def detect_ribs(mesh: trimesh.Trimesh, facet_groups: list[np.ndarray], face_areas: np.ndarray,
                normals: np.ndarray, tol: float,
                wall_thickness: np.ndarray | None = None) -> list[dict[str, Any]]:
    """Measured ribs; see ``GeometryContext.ribs`` for the definition."""
    import shapely
    from shapely.geometry import LineString, MultiLineString, Point

    if not mesh.is_watertight or not len(facet_groups):
        return []
    facets = sorted(facet_groups, key=lambda f: -float(face_areas[f].sum()))[:_RIB_MAX_FACETS]
    total = float(face_areas.sum()) or 1.0
    facets = [f for f in facets if float(face_areas[f].sum()) >= 1e-4 * total]
    if len(facets) < 2:
        return []
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    center = vertices.mean(axis=0)
    triangles = np.asarray(mesh.faces)
    # Mesh edges as sorted vertex pairs, looked up by one integer key.
    n_vertices = np.int64(len(vertices))
    adjacency_edges = np.sort(np.asarray(mesh.face_adjacency_edges, dtype=np.int64), axis=1)
    adjacency_keys = adjacency_edges[:, 0] * n_vertices + adjacency_edges[:, 1]
    key_order = np.argsort(adjacency_keys)
    sorted_keys = adjacency_keys[key_order]
    sharp = np.asarray(mesh.face_adjacency_angles) > np.radians(30.0)
    convex_flags = np.asarray(mesh.face_adjacency_convex, dtype=bool)
    adjacency_faces = np.asarray(mesh.face_adjacency, dtype=np.int64)
    face_facet = np.full(len(triangles), -1, dtype=np.int64)
    for index, facet in enumerate(facets):
        face_facet[facet] = index

    info = []
    for index, facet in enumerate(facets):
        normal = normals[int(facet[np.argmax(face_areas[facet])])]
        offset = float(np.mean((vertices[triangles[facet]].reshape(-1, 3) - center) @ normal))
        # Boundary edges: edges used once within the facet.
        edges = np.sort(np.concatenate([triangles[facet][:, [0, 1]], triangles[facet][:, [1, 2]],
                                        triangles[facet][:, [2, 0]]]), axis=1)
        unique, counts = np.unique(edges, axis=0, return_counts=True)
        boundary = unique[counts == 1]
        # Each boundary edge's mesh adjacency: sharp and concave (a root),
        # sharp and convex (a free edge), or neither (smooth, not counted).
        keys = boundary[:, 0] * n_vertices + boundary[:, 1]
        slot = np.clip(np.searchsorted(sorted_keys, keys), 0, max(len(sorted_keys) - 1, 0))
        found = len(sorted_keys) > 0
        match = (sorted_keys[slot] == keys) if found else np.zeros(len(keys), dtype=bool)
        adjacency = key_order[slot]
        is_sharp = match & sharp[adjacency] if found else match
        concave = is_sharp & ~convex_flags[adjacency] if found else match
        info.append((normal, offset, boundary, concave, is_sharp & ~concave, adjacency))

    def frame(normal):
        u = np.cross(normal, [1.0, 0.0, 0.0])
        if np.linalg.norm(u) < 0.5:
            u = np.cross(normal, [0.0, 1.0, 0.0])
        u /= np.linalg.norm(u)
        return u, np.cross(normal, u)

    polygons: dict[tuple[int, int], Any] = {}

    def outline(index, owner):
        """Facet ``index`` drawn in the plane frame of facet ``owner``, from its boundary edges."""
        key = (index, owner)
        if key not in polygons:
            u, v = frame(info[owner][0])
            pts = vertices[info[index][2]] - center
            segments = np.stack([pts @ u, pts @ v], axis=-1)
            polygons[key] = shapely.build_area(shapely.multilinestrings(segments)).buffer(0)
        return polygons[key]

    def extent(index, owner):
        u, v = frame(info[owner][0])
        pts = vertices[np.unique(triangles[facets[index]])] - center
        return np.array([(pts @ u).min(), (pts @ v).min(), (pts @ u).max(), (pts @ v).max()])

    plates = []
    for i in range(len(facets)):
        n_i, d_i = info[i][:2]
        for j in range(i + 1, len(facets)):
            n_j, d_j = info[j][:2]
            if float(n_i @ n_j) > -_RIB_PARALLEL_COS:
                continue
            thickness = d_i + d_j  # n_j ~ -n_i: plane i at d_i, plane j at -d_j along n_i
            if thickness <= tol:
                continue
            if wall_thickness is not None:
                # Material all the way across: the face's own wall rays reach
                # the opposite face (not a fin farther along, past a gap).
                readings = wall_thickness[facets[i]]
                readings = readings[np.isfinite(readings)]
                if len(readings) and float(np.median(np.abs(readings - thickness))) > max(0.02 * thickness, 10 * tol):
                    continue
            # Face to face at all: their outlines' boxes must overlap.
            a, b = extent(i, i), extent(j, i)
            if a[0] >= b[2] or b[0] >= a[2] or a[1] >= b[3] or b[1] >= a[3]:
                continue
            plates.append((i, j, thickness))
    if len(plates) > _RIB_MAX_PAIRS:
        logger.info("Rib detection skipped: %d facing face pairs", len(plates))
        return []

    ribs = []
    plate_of_facet: dict[int, float] = {}
    measured = []
    for i, j, thickness in plates:
        u, v = frame(info[i][0])
        shared = outline(i, i).intersection(outline(j, i))
        if shared.is_empty or shared.area < 0.5 * min(outline(i, i).area, outline(j, i).area):
            continue
        # A plate is wider than it is thick in every direction; two opposite
        # facet strips of a tessellated cylinder face each other across its
        # diameter but are slivers, not a plate.
        box = np.asarray(shapely.minimum_rotated_rectangle(shared).exterior.coords)[:4]
        sides = np.linalg.norm(np.diff(np.vstack([box, box[:1]]), axis=0), axis=1)
        if len(sides) < 2 or float(sides.min()) < thickness:
            continue
        plate_of_facet[i] = min(plate_of_facet.get(i, np.inf), thickness)
        plate_of_facet[j] = min(plate_of_facet.get(j, np.inf), thickness)
        measured.append((i, j, thickness, shared, u, v))

    for i, j, thickness, shared, u, v in measured:
        roots, free = [], 0
        rooted = set()
        neighbours = set()
        for k in (i, j):
            _normal, _offset, boundary, concave, convex, adjacency = info[k]
            free += int(convex.sum())
            if concave.any():
                rooted.add(k)
                roots.extend(boundary[concave].tolist())
                neighbours.update(int(f) for f in face_facet[adjacency_faces[adjacency[concave]].reshape(-1)])
        # A rib stands on a face that carries on past both of its sides (a T):
        # both of its faces meet that face in a concave edge. A free plate has
        # no root (a web); an L (bracket legs, a cap on a post) roots only one
        # face and is a corner, not a rib; no free edge means it is enclosed.
        if rooted != {i, j} or not free:
            continue
        points = vertices[np.asarray(roots).reshape(-1)] - center
        root2d = np.stack([points @ u, points @ v], axis=-1)
        # One straight root: the root points lie along a line (within the thickness).
        spread = root2d - root2d.mean(axis=0)
        _, singular, axes = np.linalg.svd(spread, full_matrices=False)
        across = np.abs(spread @ axes[1]) if len(singular) > 1 else np.zeros(len(spread))
        if float(across.max(initial=0.0)) > max(thickness, tol):
            continue
        root_line = MultiLineString([LineString(root2d[k:k + 2]) for k in range(0, len(root2d), 2)])
        coords = [c for poly in getattr(shared, "geoms", [shared]) for c in poly.exterior.coords]
        height = max(root_line.distance(Point(c)) for c in coords)
        if height < 2.0 * thickness:
            continue  # a stub, not a plate standing out
        base = [plate_of_facet[k] for k in neighbours if k >= 0 and k not in (i, j) and k in plate_of_facet]
        middle = shared.representative_point()
        anchor = center + info[i][0] * (info[i][1] - thickness / 2.0) + u * middle.x + v * middle.y
        ribs.append({
            "thickness_mm": float(thickness),
            "height_mm": float(height),
            "base_thickness_mm": float(min(base)) if base else None,
            "center": tuple(float(c) for c in anchor),
        })
    ribs.sort(key=lambda r: -r["height_mm"] / r["thickness_mm"])
    return ribs


_MAX_NESTING_SHELLS = 64
# Largest normal tilt (radians) a convexity or setup proof forgives as source
# rounding: 1 µm over a metre, far below any machined feature.
_ROUNDING_TILT_CAP = 1e-6
# The facets of a tessellated round wall (a bore, a turned diameter) lean off
# square to its axis: a facet between nodes at different heights and angles
# cuts the chord, a few degrees either way in a STEP mesh. Such a wall is a
# wall for the setup proof (GeometryContext._tessellation_lean); a taper or a
# ledge that really overhangs is not.
_TESSELLATED_LEAN_SIN = math.sin(math.radians(15.0))
_TESSELLATED_LEAN_OF_PART = 1e-3


def shell_nesting_depths(bodies: list[trimesh.Trimesh]) -> list[int] | None:
    """How many of the other closed shells enclose each shell.

    A solid with a sealed internal void is one body bounded by two shells: its
    outer skin (depth 0) and the skin of the void inside it (depth 1). An island
    sitting loose inside that void is depth 2, a void inside the island depth 3,
    and so on: even depths are the outer skins of bodies, odd depths are sealed
    voids. Decided by containment, not by face winding, so a void shell exported
    with outward-facing triangles is still read as a void.

    None when there is nothing to nest (one shell), when a shell is open (inside
    and outside are then undefined), or past ``_MAX_NESTING_SHELLS`` shells.
    """
    if len(bodies) < 2 or len(bodies) > _MAX_NESTING_SHELLS:
        return None
    try:
        if not all(body.is_watertight and len(body.faces) for body in bodies):
            return None
        probes = [np.asarray(body.vertices[int(body.faces[0][0])], dtype=np.float64) for body in bodies]
        bounds = [np.asarray(body.bounds, dtype=np.float64) for body in bodies]
        depths = []
        for i, probe in enumerate(probes):
            depth = 0
            for j, other in enumerate(bodies):
                if j == i or np.any(probe < bounds[j][0]) or np.any(probe > bounds[j][1]):
                    continue
                if bool(other.contains([probe])[0]):
                    depth += 1
            depths.append(depth)
        return depths
    except Exception:
        logger.warning("Shell nesting could not be measured", exc_info=True)
        return None


def solid_body_count(mesh: trimesh.Trimesh) -> int:
    """Separate solid bodies, not counting the shells of sealed internal voids."""
    count = int(mesh.body_count) if len(mesh.faces) else 0
    if count <= 1 or count > _MAX_NESTING_SHELLS:
        return count
    depths = shell_nesting_depths(list(mesh.split(only_watertight=False)))
    if depths is None:
        return count
    return sum(1 for depth in depths if depth % 2 == 0)


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


# An angle check (overhang) forgives at most this much source rounding: a
# sliver whose rounded normal is less certain keeps the strict test.
_ROUNDING_ANGLE_CAP_DEG = 0.1


def rounding_angle_error_deg(mesh: trimesh.Trimesh) -> np.ndarray | None:
    """How far each face's direction can be off from source-coordinate rounding.

    A binary STL rounds every coordinate to float32; moving a part 1 m away
    from the origin rounds it ~100x coarser, which tilts a small triangle by a
    few thousandths of a degree. Degrees per face, capped at
    ``_ROUNDING_ANGLE_CAP_DEG``; None for a mesh without rounding.
    """
    error = float((mesh.metadata or {}).get("coordinate_error", 0.0))
    if not error or not np.isfinite(error) or len(mesh.faces) == 0:
        return None
    return np.minimum(np.degrees(_normal_precision(mesh, error)), _ROUNDING_ANGLE_CAP_DEG)


def _normal_precision(mesh: trimesh.Trimesh, error: float) -> np.ndarray:
    """Euclidean unit-normal change when each triangle vertex moves <= error."""
    if not error:
        return np.zeros(len(mesh.faces))
    edges = mesh.triangles[:, 1:] - mesh.triangles[:, :1]
    cross_error = 2 * error * np.linalg.norm(edges, axis=2).sum(axis=1) + 4 * error**2
    cross_length = 2 * mesh.area_faces
    return np.minimum(2., 2 * cross_error / np.maximum(cross_length - cross_error, 1e-300))


# Facets of a tessellated round hole or curved cut-out lean off square to the
# caps (a few degrees in a STEP tessellation, ~11° in a coarse STL with nodes
# along the wall). Up to this lean they still read as a wall through the gauge,
# provided the solid stays a straight extrusion (``_straight_through``).
_TESSELLATED_WALL_SIN = math.sin(math.radians(15.0))
_STRAIGHT_THROUGH_REL = 1e-3
# A node on a tessellated arc sits at most one sagitta off the chord between its
# neighbours: tan(pi / 2n) / 2 of the chord for an n-segment circle, 0.134 at
# n = 6. Wall nodes farther than this from the cap outline aren't tessellation.
_SAGITTA_PER_CHORD = 0.15


def _straight_through(mesh, caps, heights, low, high, gauge, tol, normal, leaning) -> bool:
    """A straight extrusion, read through tessellation error.

    Both caps the same area, volume = cap area × gauge (each within 0.1%), and
    every node part-way up a leaning wall within one arc sagitta of the cap
    outline when projected onto it. A draft, chamfer, fillet or bulge moves the
    cap areas, the volume or the wall nodes.
    """
    face_heights = heights[mesh.faces].mean(axis=1)
    low_caps = caps & (np.abs(face_heights - low) <= tol)
    area_low = float(mesh.area_faces[low_caps].sum())
    area_high = float(mesh.area_faces[caps & (np.abs(face_heights - high) <= tol)].sum())
    area = max(area_low, area_high)
    if area <= 0 or abs(area_low - area_high) > _STRAIGHT_THROUGH_REL * area:
        return False
    volume = _finite_body_volume(mesh)
    if not (volume > 0 and abs(volume - area * gauge) <= _STRAIGHT_THROUGH_REL * volume):
        return False
    nodes = np.unique(mesh.faces[leaning])
    nodes = nodes[(np.abs(heights[nodes] - low) > tol) & (np.abs(heights[nodes] - high) > tol)]
    if not len(nodes):
        return True
    edges = np.sort(mesh.faces[low_caps][:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    outline = unique[counts == 1]
    if not len(outline):
        return False
    rotation = np.asarray(trimesh.geometry.align_vectors(normal, [0., 0., 1.]))[:3, :3]
    flat = (np.asarray(mesh.vertices) @ rotation.T)[:, :2]
    start, end = flat[outline[:, 0]], flat[outline[:, 1]]
    k = min(8, len(outline))
    _, near = KDTree((start + end) / 2).query(flat[nodes], k=k)
    near = np.asarray(near).reshape(len(nodes), k)
    a, b = start[near], end[near]
    ab = b - a
    length2 = np.maximum((ab * ab).sum(axis=2), 1e-30)
    point = flat[nodes][:, None, :]
    t = np.clip(((point - a) * ab).sum(axis=2) / length2, 0.0, 1.0)
    distance = np.linalg.norm(a + t[..., None] * ab - point, axis=2)
    allowed = _SAGITTA_PER_CHORD * np.sqrt(length2) + tol
    return bool(np.all((distance <= allowed).any(axis=1)))


# ── Inside corners a rotating cutter can't make sharp ─────────────────────
# A concave edge whose face normals turn by more than this is a sharp inside
# edge (src.fixes.brep_fixes.SHARP_CONCAVE_DEG rounds the same edges).
_SHARP_TURN = math.radians(30.0)
# The facets of a tessellated curve (a round hole, a boss) meet at concave
# edges too: 360/n degrees apart for an n-sided hole, 30-35 degrees between
# the facets of a 6 mm hole in a coarse STL. A facet with two or more concave
# edges turning between 5 and 50 degrees is part of a curved surface, not a
# corner: an octagon or finer reads as round, a hexagon as six corners.
_CURVE_FACET_TURN = (math.radians(5.0), math.radians(50.0))
# A flat-ended cutter coming straight down onto a face (its floor) cuts the
# corner sharp when the other face stands square to that floor or leans back
# from it; a face leaning over the floor by more than this is an undercut.
_FLOOR_SQUARE = math.sin(math.radians(5.0))
# Edges of one corner run in one direction (within this) and share vertices.
_CORNER_RUN_COS = math.cos(math.radians(20.0))


@dataclass(frozen=True)
class InsideCorners:
    """Inside corners where a milling cutter leaves its own radius."""
    corners: int           # separate corners: runs of connected edges in one direction
    length_mm: float       # their total length along the edge
    edges: np.ndarray      # rows of face_adjacency on those corners
    # Each corner's length along its edge: how deep the cutter that leaves the
    # corner's radius has to reach (a pocket's corner runs its full depth).
    lengths_mm: tuple[float, ...] = ()

    @property
    def deepest_mm(self) -> float:
        return max(self.lengths_mm, default=0.0)


def inside_corners(mesh: trimesh.Trimesh, normals: np.ndarray, adjacency: np.ndarray,
                   turn: np.ndarray, concave: np.ndarray, facet_groups, eps: float) -> InsideCorners:
    """Inside corners a rotating cutter leaves rounded, whatever the tessellation.

    A milling cutter is round: where two walls meet along its axis it leaves its
    radius in the corner. The same corner comes out sharp when one of its faces
    can be the floor of the cut: the flat end of the cutter comes straight down
    onto that face, with the other face square to it or leaning back (the foot
    of an L bracket's upright, the underside of a bridge, round a boss, an open
    step cut from its side). A sharp concave edge counts only when neither face
    can be that floor: the corners of a pocket or the inside of a box. A face
    can be the floor when a ray from it, just beside the edge, leaves the part
    along its normal (the part is re-fixtured for each such face).

    Counted in corners (connected runs of edges in one direction) and their
    length, so a STEP tessellated finely along an edge and an STL with one
    triangle edge per corner give the same answer.
    """
    empty = InsideCorners(0, 0.0, np.empty(0, dtype=np.int64))
    count = len(adjacency)
    if count == 0 or len(turn) != count or len(concave) != count:
        return empty
    sharp = concave & (turn > _SHARP_TURN)
    if not sharp.any():
        return empty
    n_faces = len(mesh.faces)
    # 1. Facets of tessellated curves, counted per planar facet (a strip of a
    #    coarse cylinder is often two coplanar triangles).
    group = np.arange(n_faces)
    for gid, faces in enumerate(facet_groups):
        group[np.asarray(faces, dtype=int)] = n_faces + gid
    ga, gb = group[adjacency[:, 0]], group[adjacency[:, 1]]
    low, high = _CURVE_FACET_TURN
    curve_like = concave & (turn > low) & (turn <= high) & (ga != gb)
    per_group = np.zeros(n_faces + len(facet_groups), dtype=np.int64)
    np.add.at(per_group, ga[curve_like], 1)
    np.add.at(per_group, gb[curve_like], 1)
    on_curve = curve_like & (per_group[ga] >= 2) & (per_group[gb] >= 2)
    candidates = np.flatnonzero(sharp & ~on_curve)
    if not len(candidates):
        return empty
    # 2. Can either face be the floor of a cut?
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    edge_vertices = np.asarray(mesh.face_adjacency_edges)[candidates]
    p0, p1 = vertices[edge_vertices[:, 0]], vertices[edge_vertices[:, 1]]
    middle = (p0 + p1) / 2.0
    run = p1 - p0
    length = np.linalg.norm(run, axis=1)
    direction = run / np.maximum(length, 1e-300)[:, None]
    floor_ok = np.zeros(len(candidates), dtype=bool)
    origins, rays, owners = [], [], []
    for side in (0, 1):
        floor = adjacency[candidates, side]
        other = adjacency[candidates, 1 - side]
        square = np.einsum("ij,ij->i", normals[floor], normals[other]) >= -_FLOOR_SQUARE
        corners_of = np.asarray(mesh.faces)[floor]
        third = np.where((corners_of != edge_vertices[:, :1]) & (corners_of != edge_vertices[:, 1:]),
                         corners_of, -1).max(axis=1)
        inward = vertices[np.maximum(third, 0)] - middle
        inward -= np.einsum("ij,ij->i", inward, direction)[:, None] * direction
        reach = np.linalg.norm(inward, axis=1)
        usable = square & (third >= 0) & (reach > 0)
        step = np.minimum(0.25 * reach, 0.5) / np.maximum(reach, 1e-300)
        origin = middle + inward * step[:, None] + normals[floor] * eps
        origins.append(origin[usable])
        rays.append(normals[floor][usable])
        owners.append(np.flatnonzero(usable))
    origins_all = np.vstack(origins)
    if len(origins_all):
        blocked = np.asarray(mesh.ray.intersects_any(origins_all, np.vstack(rays)), dtype=bool)
        floor_ok[np.concatenate(owners)[~blocked]] = True
    need = ~floor_ok & (length > 0)
    if not need.any():
        return empty
    # 3. Corners: edges sharing a vertex and running the same way.
    rows = np.flatnonzero(need)
    ends = edge_vertices[rows]
    incidence = np.concatenate([np.stack([ends[:, 0], np.arange(len(rows))], axis=1),
                                np.stack([ends[:, 1], np.arange(len(rows))], axis=1)])
    incidence = incidence[np.argsort(incidence[:, 0], kind="stable")]
    same = incidence[1:, 0] == incidence[:-1, 0]
    first = np.r_[True, ~same]
    leader = np.maximum.accumulate(np.where(first, np.arange(len(incidence)), 0))
    a, b = incidence[leader, 1], incidence[:, 1]
    keep = (a != b) & (np.abs(np.einsum("ij,ij->i", direction[rows][a], direction[rows][b])) >= _CORNER_RUN_COS)
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    graph = coo_matrix((np.ones(int(keep.sum())), (a[keep], b[keep])), shape=(len(rows), len(rows)))
    n_corners, labels = connected_components(graph, directed=False)
    per_corner = np.bincount(labels, weights=length[rows], minlength=n_corners)
    return InsideCorners(int(n_corners), float(length[rows].sum()), candidates[rows],
                         tuple(float(v) for v in per_corner))


def rounded_inside_corners(mesh: trimesh.Trimesh, features, normals: np.ndarray, centroids: np.ndarray,
                           adjacency: np.ndarray, eps: float) -> list[dict[str, Any]]:
    """Concave fillets a milling cutter's side cuts: neither face they blend can be a floor.

    The same rule as ``inside_corners`` for a sharp corner: a fillet along a
    pocket's floor is cut by the tip of a ball or bull-nose cutter coming down
    onto the floor, so its radius says nothing about reach; a fillet in a
    pocket's vertical corner is the cutter's own radius, and the cutter has to
    reach the corner's full length. Each: ``radius_mm``, ``depth_mm`` (its
    length along the corner), ``center``, ``faces``.
    """
    from src.analysis.features.base import FeatureKind
    from src.parsers.step_mesher import CAD_FACE_SHAPES_KEY

    if not len(adjacency):
        return []
    n = len(normals)
    a, b = adjacency[:, 0], adjacency[:, 1]
    candidates: list[tuple[np.ndarray, float, float]] = []   # (faces, radius, length)
    ids = cad_face_ids(mesh)
    shapes = (mesh.metadata or {}).get(CAD_FACE_SHAPES_KEY) if ids is not None else None
    if shapes:
        # STEP/IGES: the B-rep names its cylinders, their radius, arc and length. A
        # corner rounds less than a half turn; a bore (or its half) doesn't count.
        concave = ~np.asarray(mesh.face_adjacency_convex, dtype=bool)
        same = ids[a] == ids[b]
        for index, shape in enumerate(shapes):
            if not shape or shape["arc_deg"] >= 170.0:
                continue
            faces = np.flatnonzero(ids == index)
            inner = same & (ids[a] == index)
            if not len(faces) or not inner.any() or concave[inner].mean() < 0.5:
                continue
            candidates.append((faces, float(shape["radius_mm"]), float(shape["length_mm"])))
    else:
        for f in features or ():
            meta = f.metadata or {}
            if (f.kind == FeatureKind.FILLET and f.radius and f.radius > 0 and meta.get("convex") is False
                    and meta.get("axial_length_mm")):
                candidates.append((np.asarray(f.face_indices, dtype=np.int64), float(f.radius),
                                   float(meta["axial_length_mm"])))
    origins, rays, owner = [], [], []
    for index, (faces, _radius, _length) in enumerate(candidates):
        own = normals[faces]
        axis = np.linalg.svd(own, full_matrices=False)[2][-1]  # a cylinder's normals are square to its axis
        mine = np.zeros(n, dtype=bool)
        mine[faces] = True
        edge = mine[a] ^ mine[b]
        flank = np.unique(np.where(mine[a[edge]], b[edge], a[edge]))
        # The faces it blends, across its sides (not the floor or top at its ends).
        flank = flank[np.abs(normals[flank] @ axis) < 0.3]
        if len(flank) < 2:
            continue
        first = normals[flank[0]]
        other = normals[flank[int(np.argmin(normals[flank] @ first))]]
        side = (normals[flank] @ first) >= (normals[flank] @ other)
        centre = centroids[faces].mean(axis=0)
        for group in (flank[side], flank[~side]):
            if not len(group):
                continue
            k = group[int(np.argmin(np.linalg.norm(centroids[group] - centre, axis=1)))]
            origins.append(centroids[k] + normals[k] * eps)
            rays.append(normals[k])
            owner.append(index)
    if not origins:
        return []
    escaped = ~np.asarray(mesh.ray.intersects_any(np.asarray(origins), np.asarray(rays)), dtype=bool)
    floor = np.zeros(len(candidates), dtype=bool)
    floor[np.asarray(owner)[escaped]] = True
    seen = np.zeros(len(candidates), dtype=bool)
    seen[np.asarray(owner)] = True
    return [{"radius_mm": radius, "depth_mm": length,
             "center": tuple(float(c) for c in centroids[faces].mean(axis=0)), "faces": faces.tolist()}
            for (faces, radius, length), is_floor, ok in zip(candidates, floor, seen) if ok and not is_floor]


# ── Draft ────────────────────────────────────────────────────────────────────
# A wall reading within this of a rule meets it. A face a CAD tool drew at
# exactly 3.000° reads 2.999999999° from the file's floating-point coordinates;
# no CAD tool shows or takes a draft finer than a thousandth of a degree.
DRAFT_TOL_DEG = 1e-3
# Neighbouring triangles turning less than this are facets of one smooth surface
# (a tessellated cone or bore: 30° between the facets of a 12-sided STL hole);
# more is an edge between faces.
_SMOOTH_TURN = math.radians(35.0)
# Telling inside walls from outside ones: rays from the largest triangles of each
# smooth wall surface, on the largest surfaces (the rest read as outside walls).
_WALL_SIDE_RAYS = 3
_WALL_SIDE_PATCHES = 500


@dataclass(frozen=True)
class WallDraft:
    """Side walls (80–100° from +Z) and the draft each carries.

    ``draft`` is ``|90° - angle from +Z|`` of the B-rep surface's own normal when
    the STEP/IGES mesher kept it (``exact``), else of the triangle. ``slack`` is
    how far below the surface's true draft that reading can sit: the float noise
    of the file's coordinates, an STL's rounding, and on a tessellated curved
    surface the facets' own lean (a cone's facet through two of its generators
    leans ``atan(tan(draft) × cos(turn / 2))``, under its true draft). A wall
    meets a rule when ``draft + slack`` reaches it: tessellation never fails a
    correct model. ``inside`` marks walls that face the part across a gap (the
    inside of a box, a bore, a slot): the core of a mould sits there and the
    part shrinks onto it, which is why molding and casting rules ask more draft
    of them.
    """
    faces: np.ndarray
    draft: np.ndarray
    slack: np.ndarray
    inside: np.ndarray
    patch: np.ndarray       # the smooth surface (B-rep face when known) of each wall triangle
    exact: bool
    cad_faces: int          # B-rep faces in the solid; 0 when not known


def _sidewalls_of(normals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    with np.errstate(all="ignore"):
        angles = np.degrees(np.arccos(np.clip(np.asarray(normals, dtype=np.float64)[:, 2], -1.0, 1.0)))
    faces = np.where((angles > 80) & (angles < 100))[0]
    return faces, np.abs(90.0 - angles[faces])


def cad_face_ids(mesh: trimesh.Trimesh) -> np.ndarray | None:
    """Each triangle's B-rep face (STEP/IGES mesher), or None when not kept or not aligned."""
    from src.parsers.step_mesher import CAD_FACES_KEY

    ids = (mesh.metadata or {}).get(CAD_FACES_KEY)
    if ids is None or len(ids) != len(mesh.faces):
        return None
    return np.asarray(ids, dtype=np.int64)


def cad_face_normals(mesh: trimesh.Trimesh) -> np.ndarray | None:
    """The B-rep surface's own unit normal at each triangle, or None."""
    from src.parsers.step_mesher import CAD_NORMALS_KEY

    normals = (mesh.metadata or {}).get(CAD_NORMALS_KEY)
    if normals is None or len(normals) != len(mesh.faces):
        return None
    out = np.asarray(normals, dtype=np.float64)
    return out if out.ndim == 2 and out.shape[1] == 3 and np.all(np.isfinite(out)) else None


def cad_face_count(mesh: trimesh.Trimesh) -> int:
    from src.parsers.step_mesher import CAD_FACE_COUNT_KEY

    if cad_face_ids(mesh) is None:
        return 0
    try:
        return int((mesh.metadata or {}).get(CAD_FACE_COUNT_KEY) or 0)
    except (TypeError, ValueError):
        return 0


def wall_draft(mesh: trimesh.Trimesh, normals: np.ndarray, areas: np.ndarray, centroids: np.ndarray,
               adjacency: np.ndarray, dihedral: np.ndarray, angle_error: np.ndarray | None,
               eps: float) -> WallDraft:
    """Side walls, their draft and inside/outside (see ``WallDraft``)."""
    n = len(normals)
    ids = cad_face_ids(mesh)
    exact_normals = cad_face_normals(mesh)
    exact = exact_normals is not None
    faces, draft = _sidewalls_of(exact_normals if exact else normals)
    slack = np.full(len(faces), DRAFT_TOL_DEG)
    adjacency = np.asarray(adjacency, dtype=np.int64).reshape(-1, 2)
    dihedral = np.asarray(dihedral, dtype=np.float64)
    smooth = (dihedral <= _SMOOTH_TURN) if len(dihedral) == len(adjacency) else np.zeros(len(adjacency), bool)
    if not exact and len(faces):
        if angle_error is not None and len(angle_error) == n:
            slack += np.asarray(angle_error, dtype=np.float64)[faces]
        turn = np.zeros(n)
        bent = smooth & (dihedral > 1e-9)
        np.maximum.at(turn, adjacency[bent, 0], dihedral[bent])
        np.maximum.at(turn, adjacency[bent, 1], dihedral[bent])
        t = turn[faces]
        curved = t > 0
        if curved.any():
            with np.errstate(all="ignore"):
                high = np.degrees(np.arctan(np.tan(np.radians(draft[curved])) / np.cos(t[curved] / 2.0)))
            slack[curved] += np.maximum(np.nan_to_num(high - draft[curved]), 0.0)
    if ids is not None:
        patch_of = ids
    else:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components

        side = np.zeros(n, dtype=bool)
        side[faces] = True
        keep = smooth & side[adjacency[:, 0]] & side[adjacency[:, 1]] if len(adjacency) else np.zeros(0, bool)
        graph = coo_matrix((np.ones(int(keep.sum())), (adjacency[keep, 0], adjacency[keep, 1])), shape=(n, n))
        _count, patch_of = connected_components(graph, directed=False)
        patch_of = np.asarray(patch_of, dtype=np.int64)
    patch = patch_of[faces] if len(faces) else np.empty(0, dtype=np.int64)
    inside = _inside_walls(mesh, faces, patch, normals, areas, centroids, eps)
    return WallDraft(faces, draft, slack, inside, patch, exact, cad_face_count(mesh))


def _inside_walls(mesh, faces, patch, normals, areas, centroids, eps) -> np.ndarray:
    """Walls that face the part across a gap: a ray out across the pull axis hits it again.

    Decided per smooth wall surface by the triangles nearest its middle (most of
    them), so a face's few odd triangles, or a ray grazing out past the rim,
    can't split it. The ray runs level (the wall's direction without its lean
    along +Z), across the gap the core fills. Outside walls when the shell isn't
    closed (its normals can't be trusted to point out).
    """
    inside = np.zeros(len(faces), dtype=bool)
    if not len(faces) or not mesh.is_watertight:
        return inside
    labels, local = np.unique(patch, return_inverse=True)
    wall_area = np.asarray(areas, dtype=np.float64)[faces]
    weight = np.bincount(local, weights=wall_area)
    chosen = np.argsort(-weight)[:_WALL_SIDE_PATCHES]
    wanted = np.zeros(len(labels), dtype=bool)
    wanted[chosen] = True
    at = np.asarray(centroids, dtype=np.float64)[faces]
    middle = np.stack([np.bincount(local, weights=wall_area * at[:, k]) for k in range(3)], axis=1)
    middle /= np.maximum(weight, 1e-300)[:, None]
    off = np.linalg.norm(at - middle[local], axis=1)
    order = np.lexsort((off, local))
    run = local[order]
    first = np.r_[True, run[1:] != run[:-1]]
    rank = np.arange(len(order)) - np.maximum.accumulate(np.where(first, np.arange(len(order)), 0))
    pick = order[(rank < _WALL_SIDE_RAYS) & wanted[run]]
    if not len(pick):
        return inside
    tri = faces[pick]
    direction = np.asarray(normals, dtype=np.float64)[tri].copy()
    direction[:, 2] = 0.0
    level = np.linalg.norm(direction, axis=1)
    keep = level > 1e-9
    pick, tri, direction = pick[keep], tri[keep], direction[keep] / level[keep][:, None]
    if not len(pick):
        return inside
    origin = np.asarray(centroids, dtype=np.float64)[tri] + direction * eps
    if _fast_rays(mesh):
        batch = _EMBREE_RAY_BATCH
    else:
        batch = max(1, _wall_thickness_ray_budget() // max(len(mesh.faces), 1))
    hits = np.zeros(len(tri), dtype=bool)
    for start in range(0, len(tri), batch):
        stop = start + batch
        hits[start:stop] = np.asarray(mesh.ray.intersects_any(origin[start:stop], direction[start:stop]), dtype=bool)
    votes = np.bincount(local[pick], weights=hits.astype(float), minlength=len(labels))
    cast = np.bincount(local[pick], minlength=len(labels))
    return (votes * 2 > cast)[local]


@dataclass(frozen=True)
class BentSheet:
    """A constant-gauge sheet bent along parallel lines (an L bracket, a channel).

    ``developed_mm`` is the blank length along the bends at mid-thickness, so the
    flat blank is ``width_mm`` × ``developed_mm`` × ``gauge_mm``.
    """
    gauge_mm: float
    width_mm: float            # along the bend lines
    developed_mm: float        # flat length across the bends, at mid-thickness
    bends: int
    min_inside_radius_mm: float
    precision_mm: float


def _profile_bends(polygon, gauge: float) -> tuple[int, float]:
    """Bends in a strip profile: one run of inward (concave) corners per bend.

    Returns (bend count, smallest inside radius; 0 for a sharp corner)."""
    from shapely.geometry.polygon import orient

    ring = orient(polygon.simplify(gauge / 20.0), sign=1.0).exterior
    pts = np.asarray(ring.coords)[:-1]
    if len(pts) < 4:
        return 0, 0.0
    d_in = pts - np.roll(pts, 1, axis=0)
    d_out = np.roll(pts, -1, axis=0) - pts
    turn = np.arctan2(d_in[:, 0] * d_out[:, 1] - d_in[:, 1] * d_out[:, 0], (d_in * d_out).sum(axis=1))
    seg = np.linalg.norm(d_out, axis=1)
    concave = turn < -np.radians(5.0)
    if not concave.any():
        return 0, 0.0
    # A bend is a run of inward corners joined by short chords (one corner if
    # sharp, a tessellated arc if radiused); a straight flange between two
    # inward corners (a channel's base) ends the run.
    start = int(np.argmin(concave))  # begin the cyclic scan on a convex corner
    order = [int(i) for i in np.roll(np.arange(len(pts)), -start)]
    runs: list[list[int]] = []
    previous = None
    for i in order:
        if concave[i]:
            joined = previous is not None and concave[previous] and seg[previous] <= 1.5 * gauge
            if joined:
                runs[-1].append(i)
            else:
                runs.append([i])
        previous = i
    radii = []
    for run in runs:
        theta = float(-turn[run].sum())
        if len(run) == 1 or theta <= 0:
            radii.append(0.0)
        else:
            arc = float(sum(seg[i] for i in run[:-1]))
            radii.append(arc / (theta * (len(run) - 1) / len(run)))
    return len(runs), (min(radii) if radii else 0.0)


def bent_sheet_geometry(mesh: trimesh.Trimesh) -> BentSheet | None:
    """A sheet of one gauge bent along parallel lines, read as the straight
    extrusion of its strip profile along the bend lines.

    The profile (the cap at one end of that extrusion) must be a single strip of
    constant thickness: area A and perimeter P give the thickness t from
    P = 2A/t + 2t, and the profile must collapse when shrunk by just over t/2
    (nothing thicker than t) but not at just under it. Flanges with holes or
    cut-outs aren't extrusions along the bends and return None.
    """
    try:
        if not mesh.is_volume or mesh.body_count != 1 or len(mesh.faces) > 200_000:
            return None
        normals = mesh.face_normals
        # The bend lines run along one of the part's plane directions; try the
        # face of each of the largest planar regions (one per direction).
        candidates, seen = [], []
        facets = sorted(zip(mesh.facets_area, mesh.facets), key=lambda fa: -fa[0])[:24] if len(mesh.facets) else []
        for _area, facet in facets:
            n = normals[int(facet[0])]
            if any(abs(float(n @ m)) > 1 - 1e-6 for m in seen):
                continue
            seen.append(n)
            candidates.append(int(facet[0]))
        for face in candidates[:6]:
            bent = _bent_along(mesh, face)
            if bent is not None:
                return bent
        return None
    except Exception:
        logger.warning("Bent sheet measurement failed", exc_info=True)
        return None


def _bent_along(mesh: trimesh.Trimesh, face: int) -> "BentSheet | None":
    """The bent-sheet reading with the bend lines along ``face``'s normal."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    normals = mesh.face_normals
    normal = normals[face]
    extrusion = flat_sheet_geometry(mesh, normal_face=face)
    vertices = np.asarray(mesh.vertices) - mesh.bounds.mean(axis=0)
    heights = vertices @ normal
    low, high = float(heights.min()), float(heights.max())
    if extrusion is not None:
        (width, _, _), _hull, precision = extrusion
    else:
        # Not a straight extrusion along the bend lines: maybe a bent sheet with
        # holes or cut-outs through it (checked below, once the strip is known).
        width, precision = high - low, 2.0 * float(mesh.metadata.get("coordinate_error", 0.0))
    tol = max(1e-4, 1e-6 * float(np.linalg.norm(mesh.extents))) + precision
    rotation = np.asarray(trimesh.geometry.align_vectors(normal, [0., 0., 1.]))[:3, :3]
    flat = (vertices @ rotation.T)[:, :2]
    aligned = np.abs(normals @ normal) > 1 - 1e-6
    caps = aligned & np.all(np.abs(heights[mesh.faces] - low) <= tol, axis=1)
    if not caps.any():
        return None
    profile = unary_union([Polygon(flat[f]) for f in mesh.faces[caps]]).buffer(0)
    if extrusion is None:
        top = aligned & np.all(np.abs(heights[mesh.faces] - high) <= tol, axis=1)
        if not top.any():
            return None
        profile = unary_union([profile, unary_union([Polygon(flat[f]) for f in mesh.faces[top]]).buffer(0)]).buffer(0)
    if profile.geom_type != "Polygon" or len(profile.interiors):
        return None
    area, perimeter = float(profile.area), float(profile.length)
    disc = perimeter ** 2 - 16.0 * area
    if area <= 0 or disc <= 0:
        return None
    gauge = (perimeter - np.sqrt(disc)) / 4.0
    developed = area / gauge
    if not (gauge > 0 and developed >= 4 * gauge and width >= 2 * gauge):
        return None
    # Nothing in the profile thicker than the strip: the widest circle in a
    # sharp bend's corner is 2 - √2 ≈ 0.59 of the gauge across, so shrinking
    # by 0.625 × the gauge must leave nothing, and by 0.45 × must leave the strip.
    if not profile.buffer(-0.625 * gauge).is_empty or profile.buffer(-0.45 * gauge).is_empty:
        return None
    bends, radius = _profile_bends(profile, gauge)
    if bends == 0:
        return None  # a flat strip is a flat sheet; flat_sheet_geometry reads it
    if extrusion is None and not _cut_through_strip(mesh, normal, rotation, low, high, profile, gauge, tol):
        return None
    return BentSheet(float(gauge), float(width), float(developed), int(bends), float(radius), float(precision))


_STRIP_SECTIONS = 24


def _cut_through_strip(mesh, normal, rotation, low, high, profile, gauge, tol) -> bool:
    """The part is the strip ``profile`` swept along ``normal``, less cut-outs through the sheet.

    Holes in a flange, slots and notches are cut straight through the sheet,
    so every section across the bend lines is the strip with pieces taken out
    across its gauge: inside the strip, each piece still the full gauge thick
    (a blind pocket or a boss leaves a thinner or a thicker piece), and the
    whole strip somewhere along it. Sections at ``_STRIP_SECTIONS`` heights;
    every vertex must lie in the swept strip too.
    """
    from shapely import contains_xy
    from shapely.ops import unary_union

    center = mesh.bounds.mean(axis=0)
    flat_all = ((np.asarray(mesh.vertices) - center) @ rotation.T)[:, :2]
    if not np.all(contains_xy(profile.buffer(tol + 1e-3 * gauge), flat_all[:, 0], flat_all[:, 1])):
        return False
    full = False
    for t in np.linspace(0.0, 1.0, _STRIP_SECTIONS + 2)[1:-1]:
        origin = center + normal * (low + t * (high - low))
        try:
            lines = trimesh.intersections.mesh_plane(mesh, normal, origin)
        except Exception:
            return False
        if not len(lines):
            return False
        segments = ((np.asarray(lines) - center) @ rotation.T)[:, :, :2]
        try:
            polygons = trimesh.load_path(segments).polygons_full
        except Exception:
            return False
        section = unary_union([p for p in polygons if p is not None and p.area > 0])
        if section.is_empty:
            return False
        if section.difference(profile.buffer(tol + 1e-3 * gauge)).area > 1e-3 * profile.area:
            return False
        edge = profile.exterior.buffer(tol + 1e-3 * gauge)
        for piece in getattr(section, "geoms", [section]):
            if (piece.geom_type != "Polygon" or len(piece.interiors) or piece.buffer(-0.45 * gauge).is_empty
                    or not piece.buffer(-0.625 * gauge).is_empty):
                return False
            # Where the piece leaves the strip's outline it was cut straight
            # across the sheet: one gauge from side to side (a pocket's floor
            # runs along the sheet instead).
            cut = piece.exterior.difference(edge)
            lines = [line for line in getattr(cut, "geoms", [cut]) if not line.is_empty and line.length > 0]
            if not lines:
                continue
            # One cut end may come back in pieces (a tessellated hole wall grazes
            # the outline): the lines within a tenth of a gauge are one end.
            ends = unary_union([line.buffer(0.1 * gauge) for line in lines])
            for blob in getattr(ends, "geoms", [ends]):
                inside = [line for line in lines if blob.intersects(line)]
                total = sum(line.length for line in inside)
                if total < 0.05 * gauge:
                    continue
                points = np.vstack([np.asarray(line.coords) for line in inside])
                if len(points) > 3:
                    points = points[ConvexHull(points).vertices] if np.ptp(points, axis=0).min() > 0 else points
                span = float(np.max(np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)))
                if total > 1.5 * gauge or span < 0.9 * gauge:
                    return False
        full = full or section.area >= (1.0 - 1e-3) * profile.area
    return full


def flat_sheet_dimensions(mesh: trimesh.Trimesh) -> tuple[float, float, float] | None:
    measured = flat_sheet_geometry(mesh)
    return measured[0] if measured is not None else None


def flat_sheet_geometry(mesh: trimesh.Trimesh, *, normal_face: int | None = None) -> tuple[tuple[float, float, float], np.ndarray, float] | None:
    """Gauge and in-plane blank extents of a verified straight, flat extrusion.

    Opposing caps must bound all vertices; every other surface must run through
    the gauge. This rejects bosses, pockets, bent sheets and open/multiple bodies
    instead of calling their overall envelope a measured material thickness.
    """
    try:
        if not mesh.is_volume or mesh.body_count != 1:
            return None
        largest_face = normal_face
        if largest_face is None:
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
        leaning = ~(caps | (alignment <= angular_tol))
        if gauge <= tol + precision or np.any(alignment[leaning] > _TESSELLATED_WALL_SIN):
            return None
        cap_heights = heights[mesh.faces[caps]]
        if not np.all((np.abs(cap_heights - low) <= tol + precision) | (np.abs(cap_heights - high) <= tol + precision)):
            return None
        if np.any(leaning) and not _straight_through(mesh, caps, heights, low, high, gauge, tol + precision,
                                                     normal, leaning):
            return None
        rotation = np.asarray(trimesh.geometry.align_vectors(normal, [0., 0., 1.]))[:3, :3]
        # A tessellated curved wall has nodes along its whole height, every one
        # of them on the outline (tens of thousands on a STEP cylinder); the caps
        # carry the outline itself, so measure the blank from their vertices.
        outline_vertices = vertices[np.unique(mesh.faces[caps])] if np.any(leaning) else vertices
        footprint = (outline_vertices @ rotation.T)[:, :2]
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


def _wall_sample_points(mesh: trimesh.Trimesh, *, reversed_order: bool = False) -> np.ndarray:
    if mesh.metadata.get("coordinate_error"):
        # Symmetric CAD centroid rays often hit an export diagonal exactly.
        # A fixed interior barycentric point avoids that common ambiguous hit.
        weights = [1 / 6, 1 / 3, 1 / 2] if reversed_order else [1 / 2, 1 / 3, 1 / 6]
        return np.einsum("ijk,j->ik", mesh.triangles, weights)
    return np.asarray(mesh.triangles_center)


def _fast_rays(mesh: trimesh.Trimesh) -> bool:
    """True when rays run on Embree (production installs embreex via trimesh[easy])."""
    try:
        return "embree" in type(mesh.ray).__module__
    except Exception:
        return False


# Rays per call on Embree: its memory is a few hits per ray, not rays x triangles.
_EMBREE_RAY_BATCH = 16384
# A wall's far side faces back along the ray; a first hit on a face turned more
# than 75 degrees from the ray is a ray slipping out past an edge.
_GRAZING_COS = float(np.cos(np.radians(75.0)))


def _wall_sample_threshold(mesh: trimesh.Trimesh) -> int:
    threshold = _raycast_sample_threshold()
    if _fast_rays(mesh):
        # Embree casts every face of an analysed mesh in about a second
        # (127k faces: 1.2 s), so nothing is left to a nearby sample's value.
        threshold = max(threshold, _max_analysis_faces())
    return threshold


def _wall_sampled_mask(mesh: trimesh.Trimesh, n: int) -> np.ndarray:
    """Faces whose own inward ray ``_compute_wall_thickness`` casts."""
    if n <= _wall_sample_threshold(mesh):
        return np.ones(n, dtype=bool)
    mask = np.zeros(n, dtype=bool)
    mask[np.arange(0, n, max(1, n // 5000))] = True
    return mask


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

    if n > _wall_sample_threshold(mesh):
        return _compute_wall_thickness_sampled(mesh, normals, centroids, eps, n, upper_bounds)

    # Below threshold we cast one ray per face — but in memory-bounded batches,
    # so even here peak RSS is capped instead of spiking to gigabytes.
    origins = centroids + normals * eps  # do not step past a thin opposite wall
    directions = -normals
    source_face_idx = np.arange(n, dtype=np.int64)
    out = _cast_inward_rays_batched(mesh, origins, directions, eps, source_face_idx, upper_bounds=upper_bounds)
    if mesh.metadata.get("coordinate_error") and _fast_rays(mesh):
        # The off-centre sample point follows the order of the triangle's
        # vertices, and mirroring a part reverses that order: one point gave a
        # mirrored 46-degree trap a 1.98 mm wall where the original read 2.95 mm.
        # Measuring from the point and its reversed twin and keeping the
        # thinner (proved first) reading gives a mirrored file the same walls.
        twin = _wall_sample_points(mesh, reversed_order=True)
        twin_upper = np.full(n, np.inf) if upper_bounds is not None else None
        other = _cast_inward_rays_batched(mesh, twin + normals * eps, directions, eps, source_face_idx,
                                          source_points=twin, upper_bounds=twin_upper)
        _keep_better_reading(out, upper_bounds, other, twin_upper)
    _remeasure_unread_faces(mesh, normals, eps, np.flatnonzero(~np.isfinite(out)), out, upper_bounds)
    return out


# Three more points on a face, one toward each corner. As a set they don't
# depend on the order of the triangle's vertices, so a mirrored file (which
# reverses that order) re-measures from the same points.
_REMEASURE_WEIGHTS = ((2 / 3, 1 / 6, 1 / 6), (1 / 6, 2 / 3, 1 / 6), (1 / 6, 1 / 6, 2 / 3))


def _keep_better_reading(out, upper, other, other_upper) -> None:
    """Keep, per face, the thinner reading of two, a proved one before an unproved one."""
    if upper is None:
        np.minimum(out, other, out=out)
        return
    proved, other_proved = np.isfinite(upper), np.isfinite(other_upper)
    take = np.where(proved | other_proved, other_proved & (~proved | (other_upper < upper)), other < out)
    out[take] = other[take]
    upper[take] = other_upper[take]


def _remeasure_unread_faces(mesh, normals, eps, faces, out, upper_bounds) -> None:
    """Cast again, from three other points, the faces whose ray gave no reading.

    A ray whose first hit is a face it runs almost along is dropped (it slipped
    out past an edge, see ``_GRAZING_COS``). On a curved wall the angle changes
    with where the ray meets it, so a ray that met a bore near its tangent line
    grazes only within a few hundredths of a millimetre of it: on a finely meshed
    STEP of a 10 mm block with a 1 mm bore, 628 small flat facets whose centre lay
    in that band read nothing, and the part got a "faces gave no reading" note its
    coarser STL never had. From another point on the same facet the ray meets the
    bore at a steeper angle, or misses it, and reads the wall. A facet that
    slipped out past an edge runs along the same plane from every point (one
    direction, one exit face), so it still reads nothing, as it should.
    """
    if len(faces) == 0:
        return
    triangles = mesh.triangles[faces]
    face_normals = normals[faces]
    best = np.full(len(faces), np.inf)
    best_upper = np.full(len(faces), np.inf) if upper_bounds is not None else None
    for weights in _REMEASURE_WEIGHTS:
        points = np.einsum("ijk,j->ik", triangles, weights)
        upper = np.full(len(faces), np.inf) if upper_bounds is not None else None
        reading = _cast_inward_rays_batched(mesh, points + face_normals * eps, -face_normals, eps,
                                            np.asarray(faces, dtype=np.int64), source_points=points,
                                            upper_bounds=upper)
        _keep_better_reading(best, best_upper, reading, upper)
    out[faces] = best
    if upper_bounds is not None:
        upper_bounds[faces] = best_upper


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
    if _fast_rays(mesh):
        batch = max(batch, _EMBREE_RAY_BATCH)
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
            # A ray that leaves through a face it runs almost along started at
            # an edge and slipped out through the next face (a facet beside a
            # hole's rim, tilted by tessellation, exits the floor 0.78 mm away
            # from a 4.5 mm wall). That distance is not a wall: the face is
            # left unmeasured rather than read as thin.
            rays_v = idx_ray[valid]
            order = np.lexsort((dists[valid], rays_v))
            _, first_hit = np.unique(rays_v[order], return_index=True)
            nearest = np.flatnonzero(valid)[order[first_hit]]
            cosine = np.einsum("ij,ij->i", b_directions[idx_ray[nearest]], mesh.face_normals[idx_tri[nearest]])
            grazing = idx_ray[nearest][np.abs(cosine) < _GRAZING_COS]
            if len(grazing):
                valid &= ~np.isin(idx_ray, grazing)
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
    thickness[sample_idx] = sampled_thickness
    _remeasure_unread_faces(mesh, normals, eps, sample_idx[~np.isfinite(sampled_thickness)],
                            thickness, upper_bounds)
    sampled_thickness = thickness[sample_idx]
    if not np.any(np.isfinite(sampled_thickness)):
        return thickness

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
    for key in ("coordinate_error", "placed_up_in_file", "source_format"):
        if key in mesh.metadata:
            reduced.metadata[key] = mesh.metadata[key]
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
