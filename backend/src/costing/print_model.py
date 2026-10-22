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
from collections import OrderedDict
from dataclasses import dataclass, field

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


def pad_area_cm2(mesh, margin_mm: float | None = None) -> float:
    """Area (cm²) of the resin pad under ``mesh`` as placed: its outline seen from above (the
    union of every face's shadow), grown by the pad margin with square corners. A mesh whose
    outline can't be read gets its box footprint grown by the same margin."""
    w = RESIN["pad_margin_mm"] if margin_mm is None else float(margin_mm)
    try:
        from trimesh.path.polygons import projected

        shadow = projected(mesh, normal=[0.0, 0.0, 1.0])
    except Exception:
        shadow = None
    if shadow is None or shadow.is_empty or not shadow.area > 0:
        ext = mesh.extents
        return float((ext[0] + 2 * w) * (ext[1] + 2 * w)) / 100.0
    return float(shadow.buffer(w, join_style="mitre").area) / 100.0


_cache: "OrderedDict[str, PrintFeatures]" = OrderedDict()
_lock = threading.Lock()
_CACHE_ENTRIES = 32


def _key(mesh) -> str:
    v = np.ascontiguousarray(mesh.vertices, dtype=np.float64)
    f = np.ascontiguousarray(mesh.faces, dtype=np.int64)
    return hashlib.sha1(v.tobytes() + f.tobytes()).hexdigest()


def placed_features(mesh) -> PrintFeatures:
    """Features of the mesh as placed; memoized by its exact coordinates (a re-price reuses them).

    Support is read on the analysis-bounded mesh (the check's own decimation of
    very large meshes); volume, area and extents on the mesh itself.
    """
    from scipy.spatial import ConvexHull

    from src.analysis.context import _maybe_decimate
    from src.analysis.orientation import OVERHANG_LIMIT_DEG, placed_measures
    from src.analysis.support import support_regions

    key = _key(mesh)
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    nz = np.asarray(mesh.face_normals)[:, 2]
    areas = np.asarray(mesh.area_faces)
    lo, hi = mesh.bounds
    ext = hi - lo
    bounded, _ = _maybe_decimate(mesh)
    m = placed_measures(bounded)
    fdm = support_regions(bounded, OVERHANG_LIMIT_DEG["fdm"], measures=m)
    resin = support_regions(bounded, OVERHANG_LIMIT_DEG["sla"], measures=m, bridging=False)
    perimeter, area = layer_profile(bounded, FDM["layer_mm"])
    try:
        xy = np.asarray(mesh.vertices)[:, :2]
        outline = tuple(map(tuple, xy[ConvexHull(xy).vertices].round(6)))
    except Exception:
        outline = ()
    out = PrintFeatures(
        volume_cm3=float(mesh.volume) / 1000.0, area_cm2=float(mesh.area) / 100.0,
        wall_cm2=float(areas[np.abs(nz) < 0.5].sum()) / 100.0, height_mm=float(ext[2]),
        x_mm=float(ext[0]), y_mm=float(ext[1]), footprint_cm2=float(ext[0] * ext[1]) / 100.0,
        fdm_need_cm2=fdm.area_mm2 / 100.0, fdm_column_cm3=fdm.column_mm3 / 1000.0, fdm_bridges=fdm.bridges,
        resin_column_cm3=resin.column_mm3 / 1000.0, outline_xy=outline,
        layer_perimeter_mm=tuple(perimeter.round(4)), layer_area_mm2=tuple(area.round(4)),
        pad_cm2=pad_area_cm2(bounded),
    )
    with _lock:
        _cache[key] = out
        while len(_cache) > _CACHE_ENTRIES:
            _cache.popitem(last=False)
    return out


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


def alternates(mesh) -> list[tuple[str, PrintFeatures]]:
    """The part laid on each other side of its box (as checked), lowest first."""
    from src.analysis.orientation import Orientation, rotation_down

    out = []
    for name, d in _SIDES:
        placed = Orientation.of(rotation_down(d)).apply(mesh)
        words = "upside down" if name == "+Z" else f"on its {name} side (as checked)"
        out.append((words, placed_features(placed)))
    return sorted(out, key=lambda w: (round(w[1].height_mm, 6), w[0]))


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
    for words, g in alternates(mesh):
        n = plate_capacity(g, envelope, spacing_mm, packing)
        if n:
            return estimate(g, n), (
                f"as checked it doesn't fit the {X:g} × {Y:g} × {Z:g} mm work area standing "
                f"({f.height_mm:.0f} mm tall on {f.x_mm:.0f} × {f.y_mm:.0f} mm); priced laid {words}, "
                f"{g.height_mm:.0f} mm tall; {nest}")
    return None
