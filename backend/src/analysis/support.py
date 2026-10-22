"""Where a printed part needs support, and how much: bridging-aware.

``check_overhangs`` marks every face that overhangs past a process's limit.
A printer doesn't support all of them: a flat span between two pieces of the
part below it is printed as a bridge, strand by strand from one anchor to the
other. This module splits the marked faces into connected regions and keeps a
region off the support list when it is a bridge:

* the region is flat (its faces within ~18° of facing straight down), and
* in some direction, at least ``COVERED`` of the region lies on lines whose
  two ends both rest on an anchor: an edge where the part continues below the
  region (a wall or pillar it spans between), and
* the longest such span is within the printer class's bridge limit
  (``BRIDGE_LIMITS_MM``). A longer span sags, so it needs support.

The limit comes from published guidance, not from the slicer: PrusaSlicer
bridges a span of any length by default ("don't support bridges"), and in the
calibration set it left 19–123 mm spans unsupported that the guidance below
supports. Below the limit the rule and PrusaSlicer agree.

What remains needs support. For each remaining face the support column is
its footprint on the plate times the drop to the part or plate below (a ray
cast straight down). ``SupportEstimate`` carries the area and the column
volume; a calibration against sliced parts turns them into support material.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

COVERED = 0.9          # share of a region on anchored lines for it to count as a bridge
FLAT_NZ = -0.95        # a bridge region's mean normal: within ~18° of straight down
DIRECTIONS = 12        # directions tried for the bridge lines (every 15°)
LINES = 48             # lines across the region per direction
RAY_CAP = 4000         # rays without Embree; more faces are sampled by a fixed stride

# The longest flat span a printer lays as a bridge without support, per printer class.
# Desktop FDM (Prusa MK4, Bambu X1C class), from published guidance:
#   * Bambu Studio and OrcaSlicer, "Max bridge length: max length of bridges that don't
#     need support", default 10 mm (src/libslic3r/PrintConfig.cpp, max_bridge_length;
#     github.com/bambulab/BambuStudio, github.com/SoftFever/OrcaSlicer). Bambu's own X1C
#     system profiles set it to 0: every bridge is supported when supports are on.
#   * Protolabs Network (Hubs), "How to design parts for FDM 3D printing": "sagging or
#     marks from support material are to some extent always present unless the bridge is
#     less than 5mm" (hubs.com/knowledge-base/how-design-parts-fdm-3d-printing).
#   * Prusa knowledge base, "Modeling with 3D printing in mind": "short horizontal bridges
#     can be printed without supports", no length given (help.prusa3d.com/article/
#     modeling-with-3d-printing-in-mind_164135). PrusaSlicer has no length limit.
# So a span up to 5 mm bridges cleanly, 5–10 mm bridges but can sag a little, and over
# 10 mm needs support. Resin and metal printers don't bridge (``bridging=False``).
BRIDGE_LIMITS_MM: dict[str, dict] = {
    "fdm": {"clean": 5.0, "max": 10.0, "class": "desktop FDM (Prusa MK4, Bambu X1C class)"},
}
FDM_BRIDGE_CLEAN_MM = BRIDGE_LIMITS_MM["fdm"]["clean"]
FDM_BRIDGE_MAX_MM = BRIDGE_LIMITS_MM["fdm"]["max"]


@dataclass
class Region:
    faces: np.ndarray
    area_mm2: float
    footprint_mm2: float
    column_mm3: float
    flat: bool
    bridge: bool = False
    span_mm: float | None = None      # longest anchored span, when it is a bridge candidate
    covered: float = 0.0              # share of the region on anchored lines (best direction)
    too_long: bool = False            # anchored like a bridge, but longer than the limit


@dataclass
class SupportEstimate:
    """Support for one process limit, the mesh as placed (+Z up)."""

    area_mm2: float = 0.0             # faces needing support (bridges excluded)
    column_mm3: float = 0.0           # footprint × drop under them
    faces: int = 0
    marked_area_mm2: float = 0.0      # every face the overhang rule marks
    marked_column_mm3: float = 0.0
    bridge_area_mm2: float = 0.0      # marked, but printed as bridges
    bridges: int = 0
    longest_bridge_mm: float = 0.0
    sagging_bridges: int = 0          # bridges longer than the clean limit (they can sag a little)
    long_spans: int = 0               # spans anchored at both ends but over the limit: supported
    longest_long_span_mm: float = 0.0
    sampled: bool = False
    regions: list[Region] = field(default_factory=list)


def _drops(mesh: trimesh.Trimesh, faces: np.ndarray, centroids, normals, eps: float) -> tuple[np.ndarray, bool]:
    """Drop from each face to the part below it, else to the plate."""
    plate = float(mesh.bounds[0][2])
    drop = np.maximum(centroids[faces, 2] - plate, 0.0)
    if not len(faces):
        return drop, False
    fast = "embree" in type(mesh.ray).__module__
    cast = np.arange(len(faces))
    if not fast and len(cast) > RAY_CAP:
        cast = cast[np.linspace(0, len(cast) - 1, RAY_CAP).astype(int)]
    batch = 65536 if fast else 256
    hit_any = np.zeros(len(faces), dtype=bool)
    for start in range(0, len(cast), batch):
        sel = cast[start:start + batch]
        f = faces[sel]
        origins = centroids[f] + normals[f] * eps
        try:
            loc, rays, _ = mesh.ray.intersects_location(origins, np.tile([0.0, 0.0, -1.0], (len(f), 1)),
                                                        multiple_hits=False)
        except Exception:
            continue
        if len(rays):
            below = np.maximum(origins[rays, 2] - loc[:, 2], 0.0) + eps
            drop[sel[rays]] = np.minimum(drop[sel[rays]], below)
            hit_any[sel[rays]] = True
    sampled = len(cast) < len(faces)
    if sampled:
        # Faces not cast take the area-weighted mean ratio of their sampled neighbours in order.
        mask = np.zeros(len(faces), dtype=bool)
        mask[cast] = True
        order = np.arange(len(faces))
        nearest = cast[np.clip(np.searchsorted(cast, order), 0, len(cast) - 1)]
        drop[~mask] = drop[nearest[~mask]]
    return drop, sampled


def _anchor_segments(mesh: trimesh.Trimesh, region: np.ndarray, centroids, tol: float) -> np.ndarray:
    """Boundary edges of the region where the part continues below it (2D segments)."""
    adj = mesh.face_adjacency
    edges = mesh.face_adjacency_edges
    inside = np.zeros(len(mesh.faces), dtype=bool)
    inside[region] = True
    a_in, b_in = inside[adj[:, 0]], inside[adj[:, 1]]
    boundary = a_in ^ b_in
    other = np.where(a_in, adj[:, 1], adj[:, 0])[boundary]
    e = edges[boundary]
    v = mesh.vertices
    mid_z = (v[e[:, 0], 2] + v[e[:, 1], 2]) / 2
    down = centroids[other, 2] < mid_z - tol
    seg = np.stack([v[e[down, 0], :2], v[e[down, 1], :2]], axis=1)
    return seg


def _outline(mesh: trimesh.Trimesh, faces: np.ndarray):
    """The region seen from below, as a polygon with holes, from its boundary loops."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    sub = mesh.submesh([faces], append=True, repair=False)
    try:
        loops = sub.outline()
        flat = trimesh.path.Path2D(entities=loops.entities, vertices=np.asarray(loops.vertices)[:, :2])
        polys = [p for p in flat.polygons_full if p is not None and p.area > 0]
        if polys:
            return unary_union(polys)
    except Exception:
        pass
    # Fallback: the union of its triangles (slow on very fine meshes).
    tris = mesh.vertices[mesh.faces[faces]][:, :, :2]
    u, w = tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    doubled = np.abs(u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0])
    polys = [Polygon(t) for t, a in zip(tris, doubled) if a > 1e-12]
    return unary_union(polys) if polys else None


def _bridge(mesh: trimesh.Trimesh, faces: np.ndarray, centroids, tol: float) -> tuple[float, float]:
    """(covered share, longest anchored span) of a flat region over the best direction."""
    from shapely.geometry import LineString, MultiLineString, Point

    shape = _outline(mesh, faces)
    if shape is None or shape.is_empty or shape.area <= 0:
        return 0.0, 0.0
    seg = _anchor_segments(mesh, faces, centroids, tol)
    if not len(seg):
        return 0.0, 0.0
    anchors = MultiLineString([tuple(map(tuple, s)) for s in seg]).buffer(max(tol, 0.3))
    minx, miny, maxx, maxy = shape.bounds
    centre = np.array([(minx + maxx) / 2, (miny + maxy) / 2])
    reach = float(np.hypot(maxx - minx, maxy - miny)) + 1.0
    best, best_span = 0.0, 0.0
    for k in range(DIRECTIONS):
        th = np.pi * k / DIRECTIONS
        d = np.array([np.cos(th), np.sin(th)])
        n = np.array([-d[1], d[0]])
        total = covered = span = 0.0
        for s in np.linspace(-reach / 2, reach / 2, LINES):
            p = centre + n * s
            line = LineString([tuple(p - d * reach), tuple(p + d * reach)])
            cut = shape.intersection(line)
            parts = getattr(cut, "geoms", [cut])
            for piece in parts:
                if piece.is_empty or piece.length <= 0:
                    continue
                total += piece.length
                a, b = piece.coords[0], piece.coords[-1]
                if anchors.contains(Point(a)) and anchors.contains(Point(b)):
                    covered += piece.length
                    span = max(span, piece.length)
        if total > 0 and covered / total > best:
            best, best_span = covered / total, span
    return best, best_span


def support_regions(mesh: trimesh.Trimesh, limit_deg: float, *, bridge_limit_mm: float | None = FDM_BRIDGE_MAX_MM,
                    keep_regions: bool = False, measures: dict | None = None,
                    columns: bool = True, bridging: bool = True) -> SupportEstimate:
    """Support for one process limit on a placed mesh (+Z up), bridging-aware.

    ``bridge_limit_mm``: the longest span bridged without support (desktop FDM's
    published 10 mm by default; None: any length, as PrusaSlicer does).
    ``measures``: the per-face arrays already built for this mesh
    (``placed_measures`` keys: angles, centroids, areas, normals, bbox_diag),
    so a check marks exactly the faces its context marks. ``columns=False``
    skips the drop under each face (no ray casts; the column volumes are 0):
    a check only needs which faces bridge. ``bridging=False``: every marked
    face needs support (resin and metal printers don't bridge).
    """
    from trimesh.graph import connected_components

    from src.analysis.orientation import placed_measures
    from src.analysis.processes.checks import overhang_faces

    out = SupportEstimate()
    if len(mesh.faces) == 0:
        return out
    m = measures if measures is not None else placed_measures(mesh)
    angles, centroids, areas, normals = m["angles"], m["centroids"], m["areas"], m["normals"]
    diag = float(m["bbox_diag"])
    tol = max(0.1, diag * 1e-3)
    marked = overhang_faces(angles, centroids, diag, limit_deg)
    if not len(marked):
        return out
    eps = max(1e-4, min(diag * 1e-4, 0.1))
    if columns:
        drop, sampled = _drops(mesh, marked, centroids, normals, eps)
    else:
        drop, sampled = np.zeros(len(marked)), False
    footprint = areas[marked] * np.abs(normals[marked, 2])
    column = footprint * drop
    index = {int(f): i for i, f in enumerate(marked)}
    mask = np.zeros(len(areas), dtype=bool)
    mask[marked] = True
    adj = mesh.face_adjacency
    keep = mask[adj[:, 0]] & mask[adj[:, 1]]
    out.sampled = sampled
    out.marked_area_mm2 = float(areas[marked].sum())
    out.marked_column_mm3 = float(column.sum())
    for comp in connected_components(adj[keep], nodes=marked, min_len=1):
        faces = np.asarray(sorted(comp), dtype=int)
        rows = np.array([index[int(f)] for f in faces])
        flat = float(np.average(normals[faces, 2], weights=areas[faces])) < FLAT_NZ
        reg = Region(faces=faces, area_mm2=float(areas[faces].sum()), footprint_mm2=float(footprint[rows].sum()),
                     column_mm3=float(column[rows].sum()), flat=flat)
        if flat and bridging:
            reg.covered, reg.span_mm = _bridge(mesh, faces, centroids, tol)
            anchored = reg.covered >= COVERED
            reg.bridge = anchored and (bridge_limit_mm is None or reg.span_mm <= bridge_limit_mm)
            reg.too_long = anchored and not reg.bridge
        if reg.bridge:
            out.bridges += 1
            out.bridge_area_mm2 += reg.area_mm2
            out.longest_bridge_mm = max(out.longest_bridge_mm, reg.span_mm or 0.0)
            out.sagging_bridges += int((reg.span_mm or 0.0) > FDM_BRIDGE_CLEAN_MM)
        else:
            if reg.too_long:
                out.long_spans += 1
                out.longest_long_span_mm = max(out.longest_long_span_mm, reg.span_mm or 0.0)
            out.area_mm2 += reg.area_mm2
            out.column_mm3 += reg.column_mm3
            out.faces += len(faces)
        if keep_regions:
            out.regions.append(reg)
    return out
