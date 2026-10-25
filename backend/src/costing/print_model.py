"""Slicer-calibrated print time and material for filament (FDM) and resin (SLA).

The cost model used to charge a print by its solid volume (V ÷ a deposition
rate, the whole volume as material) at the lowest height an enclosing box can
take, without support. A slicer prints a shell and sparse infill, layer by
layer, with support under what overhangs; a resin printer exposes a whole
layer at a time. These estimators are fitted to PrusaSlicer 2.7.2's own output
on a reference set of real and generated parts in their six face-down
orientations, and validated on parts held out of the fit (the reference data,
scripts and fit are kept with the calibration; ``CALIBRATION`` records the
held-out error). They read the part as checked (+Z up: the file's own axes, or
the orientation a check was turned to), so the price follows the orientation
like the findings do.

Filament (FDM), per part
  filament  f = shell + infill·(V − shell),  shell = min(V, w·A)
  support   s = a·A_need + b·C_need   (``support_regions``: bridges excluded)
  time      per plate of n parts, from the part's cross-section at each layer (perimeter P,
            area S; the band r·P inside the perimeter is solid, the rest infill):
              work_i  = n·(c_r·min(S_i, r·P_i) + c_s·(S_i − min(S_i, r·P_i)))
              layer_i = max(work_i, min(T_min, k·work_i)) + c_L   (slowed to the minimum
                        layer time, by at most k×: the minimum print speed)
              plate   = c0 + Σ layer_i + n·(c_f·A_flat + t_a·A_need + t_c·C_need); per part ÷ n
            (support: interface layers under the area, a sparse body down the column)
Resin (SLA, whole-layer exposure), per part
  time      per plate: t0 + t_layer·ceil((h + lift) / layer), ÷ n
  resin     V + p·P + u·C   (the pad and supports; each part on a plate has its own pad)

V volume, A area, A_wall wall area (faces within 60° of vertical), A_flat the rest
(top and bottom skins), h height, F footprint, A_need / C_need area and column
(footprint × drop) under the faces needing support, C the column under every
overhanging face, P the pad: the part's outline seen from above, grown by the
pad margin (it was the box footprint F, which overstated round, hollow and
open-frame parts by up to 2.5×).
Calibrated estimates, not quotes: a shop's own slicer settings, materials and
machines differ.
"""
from __future__ import annotations

import hashlib
import math
import threading
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import cast

import numpy as np

# Filled from the calibration fit (scripts/fit.py → fits.json); see CALIBRATION.
FDM = {
    "printer": "Original Prusa MK4 Input Shaper, 0.4 mm nozzle ('0.20mm SPEED @MK4IS 0.4', Generic PLA)",
    "layer_mm": 0.2,
    "shell_cm3_per_cm2": 0.09112,
    "infill": 0.1475,
    "support_cm3_per_cm2": 0.0711,
    "support_cm3_per_cm3_column": 0.1415,
    "c0_s": 16.06,
    "ring_mm": 1.268,
    "c_ring_s_per_mm2": 0.02637,
    "c_inside_s_per_mm2": 0.00608,
    "c_flat_s_per_mm2": 0.03973,
    "min_layer_s": 8.557,
    "max_slowdown": 5.067,
    "c_layer_s": 0.2005,
    "support_s_per_cm2": 35.7,
    "support_s_per_cm3_column": 7.056,
}
RESIN = {
    "printer": "Original Prusa SL1S SPEED ('0.05 Normal @SL1S', Prusament Resin Tough)",
    "layer_mm": 0.05,
    "lift_mm": 6.0,
    "t0_s": 181.9,
    "t_layer_s": 4.75,
    # The pad follows the part's outline from above grown by pad_margin_mm, not its box
    # (refit 2026-10-22 on the same split; held-out resin median 5.5% → 1.2%, plates 25.8% → 6.6%).
    "pad_ml_per_cm2": 0.1826,
    "pad_margin_mm": 2.0,
    "support_ml_per_cm3_column": 0.0752,
}
# Held-out error against the slicer (parts the fit never saw, every calibration coupon among
# them): n placements, median and 90th-percentile |error| in %. One part on the plate; FDM
# support with every overhang supported.
CALIBRATION: dict = {
    "fdm_time_no_supports": {"n": 165, "median_abs_pct": 4.9, "p90_abs_pct": 22.0},
    "fdm_time_supported": {"n": 103, "median_abs_pct": 5.3, "p90_abs_pct": 16.3},
    "fdm_filament": {"n": 165, "median_abs_pct": 3.6, "p90_abs_pct": 10.6},
    "fdm_support": {"n": 118, "median_abs_pct": 8.4, "p90_abs_pct": 59.2},
    "resin_time": {"n": 18, "median_abs_pct": 0.0, "p90_abs_pct": 0.0},
    "resin": {"n": 22, "median_abs_pct": 1.2, "p90_abs_pct": 2.9},
}
CALIBRATION_NOTE = "slicer-calibrated estimate, not a quote"
CALIBRATED_AGAINST = ("calibrated against PrusaSlicer 2.7.2 (MK4 IS; CoreXY profile with Bambu X1C motion "
                      "limits, approximate; SL1S), 62 parts × 6 orientations")


def _calibration(time_key: str, material_key: str, material: str) -> str:
    t, m = CALIBRATION.get(time_key), CALIBRATION.get(material_key)
    if not t or not m:
        return CALIBRATED_AGAINST
    return (f"{CALIBRATED_AGAINST}, held-out median error {t['median_abs_pct']:.1f}% on time and "
            f"{m['median_abs_pct']:.1f}% on {material}")


@dataclass(frozen=True)
class PrintFeatures:
    """What a print estimate reads from the part as placed (+Z up)."""

    volume_cm3: float
    area_cm2: float
    wall_cm2: float
    height_mm: float
    x_mm: float
    y_mm: float
    footprint_cm2: float
    fdm_need_cm2: float
    fdm_column_cm3: float
    fdm_bridges: int
    resin_column_cm3: float
    outline_xy: tuple = field(default=(), repr=False, compare=False)
    # Cross-sections at FDM layer mid-heights (every ``layer_step``-th layer): perimeter mm, area mm².
    layer_perimeter_mm: tuple = field(default=(), repr=False, compare=False)
    layer_area_mm2: tuple = field(default=(), repr=False, compare=False)
    # The resin pad's area, cm²: the outline from above grown by RESIN["pad_margin_mm"]
    # (``pad_area_cm2``). 0 => not measured: the box footprint grown by the margin.
    pad_cm2: float = 0.0


LAYER_SAMPLES = 400  # cross-sections read per part at most; more layers are sampled evenly


def layer_profile(mesh, layer_mm: float = 0.2, cap: int = LAYER_SAMPLES) -> tuple[np.ndarray, np.ndarray]:
    """Perimeter (mm) and area (mm²) of the part's cross-section at layer mid-heights.

    Every face crossing a plane gives one segment; the segment is oriented by
    the face normal (material on its left), so the shoelace sum over a plane's
    segments is the enclosed area, holes subtracted. At most ``cap`` layers are
    read, evenly spaced; the arrays stand for all of them in order.
    """
    v = np.asarray(mesh.vertices, dtype=np.float64)
    fa = np.asarray(mesh.faces, dtype=np.int64)
    if not len(fa):
        return np.zeros(0), np.zeros(0)
    nrm = np.asarray(mesh.face_normals, dtype=np.float64)
    lo, hi = float(v[:, 2].min()), float(v[:, 2].max())
    layers = max(1, math.ceil(round((hi - lo) / layer_mm, 6)))
    picks = np.unique(np.linspace(0, layers - 1, min(layers, cap)).round().astype(int))
    zs = lo + (picks + 0.5) * layer_mm
    zs = np.minimum(zs, lo + (hi - lo) * (1 - 1e-9))
    tri = v[fa]
    tz = tri[:, :, 2]
    i0 = np.searchsorted(zs, tz.min(1), side="left")
    i1 = np.searchsorted(zs, tz.max(1), side="left")
    cnt = np.maximum(i1 - i0, 0)
    hit = np.nonzero(cnt)[0]
    cnt = cnt[hit]
    face = np.repeat(hit, cnt)
    plane = np.repeat(i0[hit], cnt) + (np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt))
    z = zs[plane]
    a, b, c = tri[face, 0], tri[face, 1], tri[face, 2]
    points, crossed = [], []
    for p, q in ((a, b), (b, c), (c, a)):
        dz = q[:, 2] - p[:, 2]
        ok = ((p[:, 2] <= z) & (q[:, 2] > z)) | ((q[:, 2] <= z) & (p[:, 2] > z))
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(ok, (z - p[:, 2]) / np.where(dz == 0, 1.0, dz), 0.0)
        points.append(p[:, :2] + (q[:, :2] - p[:, :2]) * t[:, None])
        crossed.append(ok)
    crossed = np.stack(crossed, 1)
    two = crossed.sum(1) == 2
    points = np.stack(points, 1)[two]
    crossed, face, plane = crossed[two], face[two], plane[two]
    rows = np.arange(len(points))
    s0 = points[rows, np.argmax(crossed, 1)]
    s1 = points[rows, 2 - np.argmax(crossed[:, ::-1], 1)]
    d = s1 - s0
    flip = (d[:, 0] * -nrm[face, 1] + d[:, 1] * nrm[face, 0]) < 0
    p0 = np.where(flip[:, None], s1, s0)
    p1 = np.where(flip[:, None], s0, s1)
    perimeter = np.bincount(plane, weights=np.hypot(d[:, 0], d[:, 1]), minlength=len(zs))
    area = np.bincount(plane, weights=0.5 * (p0[:, 0] * p1[:, 1] - p1[:, 0] * p0[:, 1]), minlength=len(zs))
    return perimeter, np.maximum(area, 0.0)


SHADOW_CELLS = 1024  # grid cells along the longer side of the part's box, for the sampled shadow


@dataclass(frozen=True)
class SampledShadow:
    """The part's shadow from above on a square grid of ``pitch`` mm cells, as runs of covered
    cells: in grid row ``row[i]``, the cells ``first[i]``..``last[i]`` (runs may overlap)."""

    row: np.ndarray
    first: np.ndarray
    last: np.ndarray
    nx: int
    ny: int
    pitch: float

    def area_mm2(self) -> float:
        """The covered cells' area: the runs' union, row by row (no grid is built)."""
        order = np.lexsort((self.first, self.row))
        offset = self.row[order] * (self.nx + 2)  # rows apart, so one running maximum serves all
        a, b = self.first[order] + offset, self.last[order] + offset
        reach = np.concatenate(([-1], np.maximum.accumulate(b)[:-1]))
        cells = int(np.maximum(0, b - np.maximum(reach, a - 1)).sum())
        return cells * self.pitch * self.pitch

    def covered(self) -> np.ndarray:
        width = self.nx + 1
        size = self.ny * width
        edges = (np.bincount(self.row * width + self.first, minlength=size)
                 - np.bincount(self.row * width + self.last + 1, minlength=size))
        return np.cumsum(edges.reshape(self.ny, width), axis=1)[:, :self.nx] > 0

    def grown_area_mm2(self, margin_mm: float) -> float:
        """Area of the shadow grown by ``margin_mm``: the cells whose centre lies within the margin
        of a covered cell's centre, plus half a cell (the shadow's edge lies on average half a cell
        past its outermost covered centres)."""
        from scipy.ndimage import distance_transform_edt

        border = int(math.ceil(margin_mm / self.pitch)) + 2
        # distances only (no indices requested): an array, whatever the stub's union says
        dist = cast(np.ndarray, distance_transform_edt(~np.pad(self.covered(), border))) * self.pitch
        return float(np.count_nonzero(dist <= margin_mm + 0.5 * self.pitch)) * self.pitch * self.pitch


def shadow_grid(mesh, cells: int = SHADOW_CELLS) -> SampledShadow | None:
    """The part's shadow from above sampled on a square grid, ``cells`` along its box's longer side.

    A cell is covered when its centre lies in the top-down projection of some face, edges
    included. Every face counts, whichever way it points, so the part upside down or turned
    end for end casts the same shadow. Each face is read row by row, so the work is the rows
    each face spans, not its area. None for a mesh with no face that casts a shadow, or one too
    thin to cover a cell's centre.
    """
    v = np.asarray(mesh.vertices, dtype=np.float64)[:, :2]
    fa = np.asarray(mesh.faces, dtype=np.int64)
    if not len(fa):
        return None
    tri = v[fa]
    e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    lo, hi = tri.reshape(-1, 2).min(0), tri.reshape(-1, 2).max(0)
    span = float((hi - lo).max())
    if not span > 0:
        return None
    tri = tri[np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) > 1e-12 * span * span]  # edge-on faces cast none
    if not len(tri):
        return None
    pitch = span / cells
    nx, ny = (int(math.floor(float(d) / pitch)) + 1 for d in (hi - lo))
    # Each face's corners from lowest to highest y: the long edge 0-2 spans every row the face
    # does; below corner 1 the other side is edge 0-1, from it edge 1-2.
    tri = np.take_along_axis(tri, np.argsort(tri[:, :, 1], axis=1)[:, :, None], axis=1)
    (x0, y0), (x1, y1), (x2, y2) = (tri[:, k].T for k in range(3))

    def slope(xa, ya, xb, yb):
        dy = yb - ya
        return np.where(dy > 0, (xb - xa) / np.where(dy > 0, dy, 1.0), 0.0)

    s02, s01, s12 = slope(x0, y0, x2, y2), slope(x0, y0, x1, y1), slope(x1, y1, x2, y2)
    r0 = np.ceil((y0 - lo[1]) / pitch - 0.5).astype(np.int64)
    r1 = np.minimum(np.floor((y2 - lo[1]) / pitch - 0.5).astype(np.int64), ny - 1)
    cnt = np.maximum(r1 - r0 + 1, 0)
    face = np.repeat(np.arange(len(tri)), cnt)
    row = np.repeat(r0, cnt) + (np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt))
    yc = lo[1] + (row + 0.5) * pitch
    xa = x0[face] + (yc - y0[face]) * s02[face]
    low = yc < y1[face]
    xb = np.where(low, x0[face] + (yc - y0[face]) * s01[face], x1[face] + (yc - y1[face]) * s12[face])
    c0 = np.ceil((np.minimum(xa, xb) - lo[0]) / pitch - 0.5).astype(np.int64)
    c1 = np.minimum(np.floor((np.maximum(xa, xb) - lo[0]) / pitch - 0.5).astype(np.int64), nx - 1)
    run = c1 >= c0
    if not run.any():  # thinner than a cell everywhere: nothing to check the outline against
        return None
    return SampledShadow(row[run], np.maximum(c0[run], 0), c1[run], nx, ny, pitch)


# trimesh's projection outlines each connected run of faces facing one way (its boundary,
# traced with a graph search per run), then unions the outlines two at a time. A finely meshed
# round wall alternates faces tipped a hair up and a hair down, each its own run: a 9 KB tube
# (1 mm wall, 202,754 faces) has 96,884 runs and took 117 s each way; a filleted 30 mm cube
# 12,079 runs and 17 s. Past this many runs, each run of up to _OUTLINE_RUN_FACES faces whose
# boundary is one simple loop is traced for all of them at once (the same loop, so the same
# polygon), other runs as trimesh does, and the outlines are unioned at once by GEOS
# (shapely.union_all): the tube in 9 s, its outline's area the same to 1e-13. Fewer runs keep
# trimesh's own path, so those parts' outlines are unchanged to the bit.
_OUTLINE_RUNS_AT_ONCE = 256
_OUTLINE_RUN_FACES = 64


def _run_loops(mesh, runs: list, vertices_2d: np.ndarray):
    """Polygons for the runs whose boundary is one simple loop, traced for all runs at once,
    and the indexes of the runs left to trimesh's own tracing (bigger, several loops, a vertex
    the boundary passes twice, or a loop that isn't a valid polygon)."""
    import shapely

    sizes = np.fromiter(map(len, runs), dtype=np.int64, count=len(runs))
    small = np.flatnonzero(sizes <= _OUTLINE_RUN_FACES)
    left = list(np.flatnonzero(sizes > _OUTLINE_RUN_FACES))
    if not len(small):
        return [], left
    tri = mesh.faces[np.concatenate([runs[i] for i in small])]
    owner = np.repeat(np.repeat(np.arange(len(small)), sizes[small]), 3)
    starts, ends = tri.reshape(-1), np.roll(tri, -1, axis=1).reshape(-1)
    # A boundary edge is one a run's faces use once (trimesh: group_rows(require_count=1)).
    edge = np.column_stack((owner, np.minimum(starts, ends), np.maximum(starts, ends)))
    _, inverse, counts = np.unique(edge, axis=0, return_inverse=True, return_counts=True)
    keep = counts[inverse.reshape(-1)] == 1
    starts, ends, owner = starts[keep], ends[keep], owner[keep]
    if not len(owner):
        return [], left + list(small)
    count_v = np.int64(len(mesh.vertices))
    bad = np.zeros(len(small), dtype=bool)
    # The boundary edge leaving each edge's end, in the same run; a vertex left twice is a pinch.
    start_key = owner * count_v + starts
    order = np.argsort(start_key, kind="stable")
    sorted_key = start_key[order]
    pinched = sorted_key[1:] == sorted_key[:-1]
    bad[owner[order[1:][pinched]]] = True
    where = np.minimum(np.searchsorted(sorted_key, owner * count_v + ends), len(sorted_key) - 1)
    found = sorted_key[where] == owner * count_v + ends
    bad[owner[~found]] = True
    following = order[where]
    # Walk each run's loop from its first boundary edge: it must close after all of them.
    loop_len = np.bincount(owner, minlength=len(small))
    bad |= loop_len < 3
    first = np.minimum(np.searchsorted(owner, np.arange(len(small))), len(owner) - 1)
    walk = [first]
    for _ in range(int(loop_len.max()) - 1):
        walk.append(following[walk[-1]])
    walk = np.asarray(walk)  # (steps, runs)
    step = np.arange(len(walk))[:, None]
    inside = step < loop_len[None, :]
    bad |= np.any((walk == first[None, :]) & inside & (step > 0), axis=0)
    bad |= following[walk[np.maximum(loop_len - 1, 0), np.arange(len(small))]] != first
    good = np.flatnonzero(~bad)
    rings_at = walk[:, good].T[inside[:, good].T]
    ring_id = np.repeat(np.arange(len(good)), loop_len[good])
    # one polygon per ring index: an object array, not the scalar Polygon the stub names
    polygons = cast(np.ndarray, shapely.polygons(shapely.linearrings(vertices_2d[starts[rings_at]], indices=ring_id)))
    valid = shapely.is_valid(polygons)
    left.extend(small[np.flatnonzero(bad)])
    left.extend(small[good[~valid]])
    return list(polygons[valid]), left


def _projected(mesh, up: float):
    """``trimesh.path.polygons.projected(mesh, normal=[0, 0, up])`` (its defaults), its runs
    traced and unioned at once when there are more than ``_OUTLINE_RUNS_AT_ONCE``."""
    import shapely
    from trimesh import geometry, graph, grouping
    from trimesh.path.polygons import edges_to_polygons, projected
    from trimesh.transformations import transform_points

    normal = np.array([0.0, 0.0, up])
    # The faces and runs trimesh picks (ignore_sign=True, tol_dot=1e-10).
    dot_face = np.dot(normal, mesh.face_normals.T)
    front, back = dot_face > 1e-10, dot_face < -1e-10
    count = np.array([front.sum(), back.sum()])
    side = [front, back][count.argmax() if count.min() == 0 else count.argmin()]
    adjacency = mesh.face_adjacency[side[mesh.face_adjacency].all(axis=1)]
    runs = graph.connected_components(adjacency, nodes=np.nonzero(side)[0])
    if len(runs) <= _OUTLINE_RUNS_AT_ONCE:
        return projected(mesh, normal=normal)
    vertices_2d = transform_points(mesh.vertices, geometry.plane_transform(origin=None, normal=normal))[:, :2]
    polygons, left = _run_loops(mesh, runs, vertices_2d)
    edges = mesh.edges_sorted.reshape((-1, 6))
    for index in left:
        edge = edges[runs[index]].reshape((-1, 2))
        polygons.extend(edges_to_polygons(edges=edge[grouping.group_rows(edge, require_count=1)],
                                          vertices=vertices_2d))
    if not polygons:
        return None
    padding = 1e-5 * float(np.ptp(vertices_2d, axis=0).max())
    return shapely.union_all(polygons).buffer(padding).buffer(-padding)


def _checked_outline(mesh, up: float, sampled):
    """trimesh's exact top-down outline of ``mesh`` (seen from above, ``up`` = 1, or from below,
    -1: the same shadow mirrored), or None when it is empty or disagrees with the sampled shadow
    by more than the grid's own resolution (one cell along the outline)."""
    try:
        outline = _projected(mesh, up)
    except Exception:
        return None
    if outline is None or outline.is_empty or not outline.area > 0:
        return None
    if sampled is not None and abs(float(outline.area) - sampled.area_mm2()) > float(outline.length) * sampled.pitch:
        return None
    return outline


def pad_area_cm2(mesh, margin_mm: float | None = None) -> float:
    """Area (cm²) of the resin pad under ``mesh`` as placed: its outline seen from above (the
    union of every face's shadow), grown by the pad margin with square corners. A mesh whose
    outline can't be read gets its box footprint grown by the same margin.

    The outline is trimesh's exact projection, checked against the shadow sampled on a grid
    (``shadow_grid``), so it reads the same whichever way up the part lies:
    * The projection traces each connected run of faces facing one way, and on a folded or
      decimated surface it can drop runs: the same solid read 14.3 cm² with one end down and
      51.7 cm² with the other. Where it disagrees with the grid by more than one cell along the
      outline, the sampled shadow is grown by the margin instead (round corners, within about a
      cell along the pad's edge of the exact pad).
    * Its outline can carry a sliver too thin to see in the area, which square corners turn into
      a spike of up to 5x the margin (+10% on one corpus part, one way up only). Where square
      corners add more than a rectangle's four would, the outline seen from below (the same
      shadow, traced from the other faces) is grown too, and a pad smaller by over 0.1% kept.
      When that outline fails its own check, corners sharper than square are bevelled.
    """
    w = RESIN["pad_margin_mm"] if margin_mm is None else float(margin_mm)
    try:
        sampled = shadow_grid(mesh)
    except Exception:
        sampled = None
    outline = _checked_outline(mesh, 1.0, sampled)
    if outline is None:
        if sampled is not None:
            return sampled.grown_area_mm2(w) / 100.0
        ext = mesh.extents
        return float((ext[0] + 2 * w) * (ext[1] + 2 * w)) / 100.0
    pad = float(outline.buffer(w, join_style="mitre").area)
    if pad - float(outline.buffer(w).area) > (4.0 - math.pi) * w * w + 1e-9:
        below = _checked_outline(mesh, -1.0, sampled)
        if below is not None:
            other = float(below.buffer(w, join_style="mitre").area)
            if other < pad * (1.0 - 1e-3):
                pad = other
        else:
            pad = float(outline.buffer(w, join_style="mitre", mitre_limit=math.sqrt(2.0) + 1e-6).area)
    return pad / 100.0


_cache: "OrderedDict[str, PrintFeatures]" = OrderedDict()
_lock = threading.Lock()
_CACHE_ENTRIES = 32
# The other ways down of a part (``_ways_down``) and the full features of those measured, by the
# part's key: a price reads them once per quantity and process (the make-vs-buy crossover alone
# asks dozens of times).
_alternates: "OrderedDict[str, tuple]" = OrderedDict()
_ALTERNATES_ENTRIES = 8
# The analysis-bounded copy of a part over the face cap (its vertices, faces and metadata), by the
# part's key, so the part is decimated once per price: its other ways down turn this copy instead
# of decimating each turned copy again. Arrays only (a few MB each), not the mesh and its caches.
_bounded: "OrderedDict[str, tuple]" = OrderedDict()
_BOUNDED_ENTRIES = 2
# The key of a mesh object already hashed, while it lives and its arrays are unchanged
# (trimesh's own hash of the data, cached until they change): id → (weakref, trimesh hash, key).
_keys: "OrderedDict[int, tuple]" = OrderedDict()
_KEYS_ENTRIES = 64


def _key(mesh) -> str:
    """SHA-1 of the mesh's exact vertices and faces; hashed once per trimesh object while unchanged."""
    import trimesh

    fast = None
    if isinstance(mesh, trimesh.Trimesh):
        fast = hash(mesh)  # xxh3 of the data arrays, recomputed by trimesh only after they change
        seen = _keys.get(id(mesh))
        if seen is not None and seen[0]() is mesh and seen[1] == fast:
            return seen[2]
    v = np.ascontiguousarray(mesh.vertices, dtype=np.float64)
    f = np.ascontiguousarray(mesh.faces, dtype=np.int64)
    key = hashlib.sha1(v.tobytes() + f.tobytes()).hexdigest()
    if fast is not None:
        _remember(_keys, id(mesh), (weakref.ref(mesh), fast, key), _KEYS_ENTRIES)
    return key


def _remember(store: OrderedDict, key, value, entries: int) -> None:
    with _lock:
        store[key] = value
        store.move_to_end(key)
        while len(store) > entries:
            store.popitem(last=False)


def _bounded_mesh(mesh, key: str):
    """The analysis-bounded copy of ``mesh`` (the check's own decimation over the face cap), or
    ``mesh`` itself under the cap; decimated once per key while it is remembered."""
    import trimesh

    from src.analysis.context import _max_analysis_faces, _maybe_decimate

    if len(mesh.faces) <= _max_analysis_faces():
        return mesh
    with _lock:
        hit = _bounded.get(key)
        if hit is not None:
            _bounded.move_to_end(key)
    if hit is not None:
        if hit[0] is None:  # decimation didn't reduce it: the mesh itself, as _maybe_decimate keeps it
            return mesh
        vertices, faces, metadata = hit
        out = trimesh.Trimesh(vertices=vertices.copy(), faces=faces.copy(), process=False)
        out.metadata.update(metadata)
        return out
    bounded, _ = _maybe_decimate(mesh)
    kept = ((None, None, None) if bounded is mesh else
            (np.array(bounded.vertices, dtype=np.float64), np.array(bounded.faces, dtype=np.int64),
             dict(bounded.metadata or {})))
    _remember(_bounded, key, kept, _BOUNDED_ENTRIES)
    return bounded


def placed_features(mesh) -> PrintFeatures:
    """Features of the mesh as placed; memoized by its exact coordinates (a re-price reuses them).

    Support is read on the analysis-bounded mesh (the check's own decimation of
    very large meshes); volume, area and extents on the mesh itself.
    """
    key = _key(mesh)
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    out = _measure(mesh, _bounded_mesh(mesh, key))
    _remember(_cache, key, out, _CACHE_ENTRIES)
    return out


def _measure(mesh, bounded, volume_cm3: float | None = None, area_cm2: float | None = None) -> PrintFeatures:
    """Features of ``mesh`` as placed, support and cross-sections read on ``bounded`` (the
    analysis-bounded copy placed the same way, or ``mesh`` itself). ``volume_cm3`` and ``area_cm2``,
    the same in every orientation, may come from the part as checked."""
    from scipy.spatial import ConvexHull

    from src.analysis.orientation import OVERHANG_LIMIT_DEG, placed_measures
    from src.analysis.support import support_regions

    nz = np.asarray(mesh.face_normals)[:, 2]
    areas = np.asarray(mesh.area_faces)
    lo, hi = mesh.bounds
    ext = hi - lo
    m = placed_measures(bounded)
    fdm = support_regions(bounded, OVERHANG_LIMIT_DEG["fdm"], measures=m)
    resin = support_regions(bounded, OVERHANG_LIMIT_DEG["sla"], measures=m, bridging=False)
    perimeter, area = layer_profile(bounded, FDM["layer_mm"])
    try:
        xy = np.asarray(mesh.vertices)[:, :2]
        outline = tuple(map(tuple, xy[ConvexHull(xy).vertices].round(6)))
    except Exception:
        outline = ()
    return PrintFeatures(
        volume_cm3=float(mesh.volume) / 1000.0 if volume_cm3 is None else volume_cm3,
        area_cm2=float(mesh.area) / 100.0 if area_cm2 is None else area_cm2,
        wall_cm2=float(areas[np.abs(nz) < 0.5].sum()) / 100.0, height_mm=float(ext[2]),
        x_mm=float(ext[0]), y_mm=float(ext[1]), footprint_cm2=float(ext[0] * ext[1]) / 100.0,
        fdm_need_cm2=fdm.area_mm2 / 100.0, fdm_column_cm3=fdm.column_mm3 / 1000.0, fdm_bridges=fdm.bridges,
        resin_column_cm3=resin.column_mm3 / 1000.0, outline_xy=outline,
        layer_perimeter_mm=tuple(perimeter.round(4)), layer_area_mm2=tuple(area.round(4)),
        pad_cm2=pad_area_cm2(bounded),
    )


def plate_capacity(f: PrintFeatures, envelope, spacing_mm: float, packing: float) -> int:
    """Parts of this footprint on one plate, standing as placed (any turn on the plate); 0 if it doesn't fit.

    The same serial XY nest the cost model used (areal packing, bounded by a
    spaced grid), on the placed footprint instead of an enclosing box's
    lowest placement.
    """
    X, Y, Z = (float(v) for v in envelope)
    if f.height_mm > Z + 1e-9:
        return 0
    s = float(spacing_mm)
    grid = 0
    for a, b in ((f.x_mm, f.y_mm), (f.y_mm, f.x_mm)):
        if a <= X + 1e-9 and b <= Y + 1e-9:
            grid = max(grid, math.floor((X + s + 1e-9) / (a + s)) * math.floor((Y + s + 1e-9) / (b + s)))
    if grid == 0:
        # Turned on the plate: one part, if its outline fits at some angle.
        from src.analysis.context import sheet_envelope_dimensions

        if len(f.outline_xy) < 3:
            return 0
        try:
            short, long = sheet_envelope_dimensions(np.asarray(f.outline_xy, dtype=float), (X, Y))
        except Exception:
            return 0
        return 1 if short <= min(X, Y) + 1e-9 and long <= max(X, Y) + 1e-9 else 0
    dense = int(packing * X * Y / ((f.x_mm + s) * (f.y_mm + s)))
    return min(grid, max(1, dense))


@dataclass(frozen=True)
class PrintEstimate:
    hours_per_part: float
    material_cm3: float      # filament or resin per part, support included
    support_cm3: float
    layers: int
    parts_per_plate: int
    source: str              # the time, with every term
    material_source: str     # the material, with every term


def fdm_estimate(f: PrintFeatures, parts_per_plate: int = 1, cal: dict | None = None) -> PrintEstimate:
    c = cal or FDM
    n = max(1, int(parts_per_plate))
    V, A = f.volume_cm3, f.area_cm2
    shell = min(V, c["shell_cm3_per_cm2"] * A)
    filament = shell + c["infill"] * (V - shell)
    support = c["support_cm3_per_cm2"] * f.fdm_need_cm2 + c["support_cm3_per_cm3_column"] * f.fdm_column_cm3
    layers = max(1, math.ceil(round(f.height_mm / c["layer_mm"], 6)))
    P = np.asarray(f.layer_perimeter_mm, dtype=np.float64)
    Ar = np.asarray(f.layer_area_mm2, dtype=np.float64)
    if not len(P):  # no cross-sections read: a prism of the part's mean section
        Ar = np.array([V * 1000.0 / max(f.height_mm, 1e-9)])
        P = np.array([2.0 * math.sqrt(math.pi * Ar[0])])
    # Each layer of the plate: n cross-sections laid (the perimeter band solid, the inside at
    # infill), slowed toward the minimum layer time by at most k×, plus the layer change.
    ring = np.minimum(Ar, c["ring_mm"] * P)
    work = n * (c["c_ring_s_per_mm2"] * ring + c["c_inside_s_per_mm2"] * (Ar - ring))
    per_layer = np.maximum(work, np.minimum(c["min_layer_s"], c["max_slowdown"] * work)) + c["c_layer_s"]
    slowed = float(np.mean(per_layer - c["c_layer_s"] > work + 1e-9))
    flat_mm2 = max(A - f.wall_cm2, 0.0) * 100.0
    support_s = c["support_s_per_cm2"] * f.fdm_need_cm2 + c["support_s_per_cm3_column"] * f.fdm_column_cm3
    plate_s = c["c0_s"] + float(per_layer.mean()) * layers + n * (c["c_flat_s_per_mm2"] * flat_mm2 + support_s)
    hours = plate_s / n / 3600.0
    bridges = (f"; {f.fdm_bridges} flat span{'s' if f.fdm_bridges != 1 else ''} bridged without support"
               if f.fdm_bridges else "")
    material_source = (f"filament {filament:.2f} cm³ (shell {shell:.2f} + {c['infill']:.0%} infill of the "
                       f"other {V - shell:.2f} of {V:.2f} cm³)"
                       + (f" + support {support:.2f} cm³ (under {f.fdm_need_cm2:.1f} cm² needing it)" if support > 0
                          else " + no support")
                       + bridges)
    source = (f"{CALIBRATION_NOTE}, {_calibration('fdm_time_supported' if support > 0 else 'fdm_time_no_supports', 'fdm_filament', 'filament')}; "
              f"layer times from the slicer fit on the {c['printer']}: {layers} layers of {c['layer_mm']:g} mm "
              f"({f.height_mm:.1f} mm tall as checked), {filament + support:.2f} cm³ laid; "
              f"{n} per plate: {plate_s / 3600:.3f} hr per plate"
              + (f" ({slowed:.0%} of layers slowed to the minimum layer time)" if slowed >= 0.005 else "")
              + f" ÷ {n} = {hours:.3f} hr per part")
    return PrintEstimate(hours, filament + support, support, layers, n, source, material_source)


def resin_estimate(f: PrintFeatures, parts_per_plate: int = 1, cal: dict | None = None) -> PrintEstimate:
    c = cal or RESIN
    n = max(1, int(parts_per_plate))
    layers = max(1, math.ceil(round((f.height_mm + c["lift_mm"]) / c["layer_mm"], 6)))
    plate_s = c["t0_s"] + c["t_layer_s"] * layers
    hours = plate_s / n / 3600.0
    w = c.get("pad_margin_mm", 0.0)
    pad_cm2 = f.pad_cm2 if f.pad_cm2 > 0 else (f.x_mm + 2 * w) * (f.y_mm + 2 * w) / 100.0
    support = c["pad_ml_per_cm2"] * pad_cm2 + c["support_ml_per_cm3_column"] * f.resin_column_cm3
    resin = f.volume_cm3 + support
    material_source = (f"resin {f.volume_cm3:.2f} cm³ part + {support:.2f} cm³ supports and pad "
                       f"(pad {pad_cm2:.1f} cm², the part's outline and {w:g} mm around it; supports under "
                       f"{f.resin_column_cm3:.1f} cm³ of overhang)")
    source = (f"{CALIBRATION_NOTE}, {_calibration('resin_time', 'resin', 'resin')}; "
              f"layer times from the slicer fit on the {c['printer']}: {layers} layers of {c['layer_mm']:g} mm "
              f"({f.height_mm:.1f} mm tall as checked + {c['lift_mm']:g} mm supports and pad), every layer "
              f"exposed at once: {plate_s / 3600:.3f} hr per plate ÷ {n} per plate = {hours:.3f} hr per part")
    return PrintEstimate(hours, resin, support, layers, n, source, material_source)


_SIDES = (("−X", (-1.0, 0.0, 0.0)), ("+X", (1.0, 0.0, 0.0)), ("−Y", (0.0, -1.0, 0.0)),
          ("+Y", (0.0, 1.0, 0.0)), ("+Z", (0.0, 0.0, 1.0)))


@dataclass(frozen=True)
class _Placement:
    """A way down of the part: what the plate nest reads (``plate_capacity``)."""

    height_mm: float
    x_mm: float
    y_mm: float
    outline_xy: tuple = field(default=(), repr=False, compare=False)


def _side_turn(side: int):
    from src.analysis.orientation import Orientation, rotation_down

    return Orientation.of(rotation_down(_SIDES[side][1]))


def _ways_down(mesh, key: str) -> tuple:
    """(ways, features): each other side as (words, placement, side), lowest first, and the full
    features of the sides measured so far. Memoized by the part's key."""
    from scipy.spatial import ConvexHull

    with _lock:
        hit = _alternates.get(key)
        if hit is not None:
            _alternates.move_to_end(key)
            return hit
    ways = []
    for side, (name, _) in enumerate(_SIDES):
        placed = _side_turn(side).apply(mesh)
        lo, hi = placed.bounds
        ext = hi - lo
        try:
            xy = np.asarray(placed.vertices)[:, :2]
            outline = tuple(map(tuple, xy[ConvexHull(xy).vertices].round(6)))
        except Exception:
            outline = ()
        words = "upside down" if name == "+Z" else f"on its {name} side (as checked)"
        ways.append((words, _Placement(float(ext[2]), float(ext[0]), float(ext[1]), outline), side))
    ways.sort(key=lambda w: (round(w[1].height_mm, 6), w[0]))
    entry = (tuple(ways), {})
    _remember(_alternates, key, entry, _ALTERNATES_ENTRIES)
    return entry


def _side_features(mesh, key: str, measured: dict, side: int) -> PrintFeatures:
    """Full features of the part laid on ``side``. A part over the face cap is decimated once:
    the turn (an exact quarter or half turn) is applied to that bounded copy rather than
    decimating the turned part again. Volume and area are the part's own as checked."""
    with _lock:
        hit = measured.get(side)
    if hit is not None:
        return hit
    bounded = _bounded_mesh(mesh, key)
    base = placed_features(mesh)
    turn = _side_turn(side)
    placed = turn.apply(mesh)
    out = _measure(placed, placed if bounded is mesh else turn.apply(bounded), base.volume_cm3, base.area_cm2)
    with _lock:
        measured[side] = out
    return out


def alternates(mesh) -> list[tuple[str, PrintFeatures]]:
    """The part laid on each other side of its box (as checked), lowest first."""
    key = _key(mesh)
    ways, measured = _ways_down(mesh, key)
    return [(words, _side_features(mesh, key, measured, side)) for words, _, side in ways]


def plan(process: str, drivers, envelope, spacing_mm: float, packing: float) -> tuple[PrintEstimate, str] | None:
    """The estimate for ``process`` ("fdm" or "sla") standing as checked, else laid the lowest way that fits.

    Returns (estimate, placement words) or None when no way down fits the work area.
    """
    estimate = fdm_estimate if process == "fdm" else resin_estimate
    f = drivers.print_features
    n = plate_capacity(f, envelope, spacing_mm, packing)
    X, Y, Z = (float(v) for v in envelope)
    # de-23: the plate is the work area being priced (the process's typical one, or the
    # owned printer's), not the calibration printer's bed; say so rather than imply it.
    nest = (f"parts per plate from an XY nest: a spaced grid on the {X:g} × {Y:g} mm plate of the "
            f"{X:g} × {Y:g} × {Z:g} mm work area priced, at {packing:g} areal packing "
            "(an assumption, not a nesting plan)")
    if n:
        return estimate(f, n), f"standing as checked; {nest}"
    mesh = getattr(drivers, "print_mesh", None)
    if mesh is None:
        return None
    # The nest reads only each way's height and outline; only the way priced is measured in full.
    key = _key(mesh)
    ways, measured = _ways_down(mesh, key)
    for words, way, side in ways:
        n = plate_capacity(way, envelope, spacing_mm, packing)
        if n:
            g = _side_features(mesh, key, measured, side)
            return estimate(g, n), (
                f"as checked it doesn't fit the {X:g} × {Y:g} × {Z:g} mm work area standing "
                f"({f.height_mm:.0f} mm tall on {f.x_mm:.0f} × {f.y_mm:.0f} mm); priced laid {words}, "
                f"{g.height_mm:.0f} mm tall; {nest}")
    return None
