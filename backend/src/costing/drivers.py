"""MEASURED geometry drivers (spec §3).

Everything in GeoDrivers is extracted from the CAD — never assumed. These feed
the cost model's material mass, stock removal, cooling-time and routing logic.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np

from src.costing.routing import is_rotational


def bbox_billet_enabled() -> bool:
    """E-now #1 off-switch. Default ON (bounding-box billet for CNC milling).

    CADVERIFY_BBOX_BILLET=0 recovers the legacy convex-hull billet so the old
    material mass + rough-machining volume come back byte-for-byte."""
    return os.getenv("CADVERIFY_BBOX_BILLET", "1") != "0"


@dataclass
class GeoDrivers:
    volume_cm3: float
    surface_area_cm2: float
    bbox_mm: tuple            # sorted ascending (d0 <= d1 <= d2)
    bbox_volume_cm3: float
    hull_volume_cm3: float
    nominal_wall_mm: float    # 2*V/A — molding cooling proxy (±50%)
    face_count: int
    max_bbox_mm: float
    is_valid: bool
    rotational: bool
    rot_axis_len_mm: float
    rot_cross_dia_mm: float
    # ---- sheet / fabrication drivers (MEASURED) -------------------------
    sheet_gauge_mm: float = 0.0       # thinnest bbox extent = sheet gauge proxy
    planar_aspect: float = 0.0        # mid_dim / gauge — flatness of the part
    outline_perimeter_mm: float = 0.0 # laser/punch cut length (outer + cutouts)
    bend_count: int = 0               # distinct planar fold lines (0 = flat blank)
    sheet_like: bool = False          # geometry reads as a constant-gauge flat sheet

    # ---- derived (MEASURED) ---------------------------------------------
    def mass_kg(self, density_g_cm3: float) -> float:
        """Part mass: CAD volume × material density."""
        return self.volume_cm3 * density_g_cm3 / 1000.0

    def stock_mass_kg(self, density_g_cm3: float, stock_allowance: float) -> float:
        """Legacy CNC billet mass: convex-hull volume × oversize × density. Kept
        for CNC turning (round-bar stock) and as the byte-identical fallback when
        the bbox-billet fix is switched off."""
        return self.hull_volume_cm3 * stock_allowance * density_g_cm3 / 1000.0

    def mass_source(self, density_g_cm3: float, material_name: str) -> str:
        return (f"CAD volume {self.volume_cm3:.2f} cm³ × {material_name} density "
                f"{density_g_cm3:.2f} g/cm³")

    def stock_source(self, density_g_cm3: float, stock_allowance: float,
                     material_name: str) -> str:
        return (f"hull volume {self.hull_volume_cm3:.2f} cm³ × {stock_allowance:.2f} "
                f"stock allowance × {material_name} density {density_g_cm3:.2f} g/cm³")

    # ---- CNC-milling billet (E-now #1): rectangular block from the bbox ------
    def billet_volume_cm3(self, stock_allowance: float) -> float:
        """CNC-milling raw-stock (billet) volume you actually buy: the bounding
        box × oversize. A pocketed/non-convex part is sawn from a solid
        rectangular block, NOT a hull-shaped blank — hull volume understates the
        block by up to ~2.6× on non-convex geometry. Off-switch recovers hull."""
        v = self.bbox_volume_cm3 if bbox_billet_enabled() else self.hull_volume_cm3
        return v * stock_allowance

    def billet_mass_kg(self, density_g_cm3: float, stock_allowance: float) -> float:
        return self.billet_volume_cm3(stock_allowance) * density_g_cm3 / 1000.0

    def billet_source(self, density_g_cm3: float, stock_allowance: float,
                      material_name: str) -> str:
        if not bbox_billet_enabled():
            return self.stock_source(density_g_cm3, stock_allowance, material_name)
        return (f"bounding-box billet {self.bbox_volume_cm3:.2f} cm³ × "
                f"{stock_allowance:.2f} stock allowance × {material_name} density "
                f"{density_g_cm3:.2f} g/cm³ [assumption, not shop-validated]")


def parts_per_build(proc, bbox_mm, rates) -> int:
    """Build-plate nesting count (weaknesses #1, #2; R2 serial XY nesting).

    build_job (powder-bed/DLP): VOLUMETRIC fit — how many part bounding boxes
    (each grown by part-spacing on every axis) pack into the machine envelope at
    the process packing_density (unchanged).

    serial (FDM/SLA): AREAL (XY-footprint) fit — parts laid FLAT in one layer on
    the plate (smallest bbox dim = build height, the two largest = footprint).
    Real service bureaus nest many parts in X-Y on one build plate (just not
    stacked in Z like powder bed); count = xy_packing_density × plate_area ÷
    part footprint. DEFAULT-driven, fully-traceable, overridable (not a true
    packer).
    """
    dd = sorted(bbox_mm)                          # ascending: dd[0]=height, dd[1],dd[2]=footprint
    s = rates.part_spacing(proc)
    if rates.nesting_mode(proc) == "serial":
        X, Y, _Z = rates.build_env(proc)
        plate_area = X * Y                                       # mm^2
        footprint = (dd[1] + s) * (dd[2] + s)                   # mm^2 (laid flat, height = dd[0])
        if footprint <= 0:
            return 1
        n = int(rates.xy_packing_density(proc) * plate_area / footprint)
        return max(1, n)
    # build_job: volumetric (unchanged)
    X, Y, Z = rates.build_env(proc)
    part_vol_cm3 = ((dd[0] + s) * (dd[1] + s) * (dd[2] + s)) / 1000.0
    env_vol_cm3 = (X * Y * Z) / 1000.0
    if part_vol_cm3 <= 0:
        return 1
    n = int(rates.packing_density(proc) * env_vol_cm3 / part_vol_cm3)
    return max(1, n)


# Sheet-metal gauge ceiling (mm). Above this the thinnest extent is treated as a
# wall/web, not a sheet gauge — heavy plate routes to machining, not fab.
SHEET_GAUGE_MAX_MM = 6.0


def _bend_count(mesh) -> int:
    """Distinct planar fold lines (sheet-metal bend count).

    Counts distinct UNDIRECTED orientations among the part's broad planar facets
    (>=8% of total area each), clustering parallel/antiparallel faces onto one
    axis. A flat blank has a single axis (top+bottom) -> 0 bends; an L-bracket
    has two axes -> 1 bend; a U-channel three -> 2. Defaults to 0 on any failure
    (a flat blank is the safe assumption for a sheet candidate).
    """
    try:
        fa = np.asarray(mesh.facets_area, dtype=np.float64)
        fn = np.asarray(mesh.facets_normal, dtype=np.float64)
        if len(fa) == 0:
            return 0
        total = float(fa.sum())
        if total <= 0:
            return 0
        big = fn[fa > 0.08 * total]
        axes: list = []
        for n in big:
            norm = float(np.linalg.norm(n))
            if norm <= 0:
                continue
            u = n / norm
            if not any(abs(float(u @ a)) > 0.95 for a in axes):
                axes.append(u)
        return max(0, len(axes) - 1)
    except Exception:
        return 0


def _sheet_geometry(volume_mm3, surface_area_mm2, dims):
    """Sheet gauge, planar aspect, cut perimeter, and the sheet-like predicate.

    gauge t   = thinnest bbox extent (the stock thickness when laid flat).
    blank A   = V / t  (developed flat area; exact for a constant-thickness plate).
    perimeter = rim_area / t where rim_area = SA - 2*blank  (the thickness-walls
                swept by the cut path: outer outline + every hole/cutout edge),
                floored at the bbox-rectangle perimeter. This is the MEASURED
                laser/punch cut length — not a magic constant.
    sheet_like = constant thin gauge (t<=6mm, wall~=t) AND broadly planar
                 (mid extent >= 4x gauge). Distinguishes a flat sheet from a
                 deep thin-walled box (whose thin extent is NOT the wall).
    """
    t = max(dims[0], 1e-6)
    wall = (2.0 * volume_mm3 / surface_area_mm2) if surface_area_mm2 > 0 else t
    blank_area = volume_mm3 / t
    rim_area = max(0.0, surface_area_mm2 - 2.0 * blank_area)
    rim_perim = rim_area / t
    bbox_perim = 2.0 * (dims[1] + dims[2])
    perimeter = max(bbox_perim, rim_perim)
    planar_aspect = dims[1] / t if t > 0 else 0.0
    sheet_like = bool(
        wall <= SHEET_GAUGE_MAX_MM
        and dims[0] <= SHEET_GAUGE_MAX_MM + 2.0      # thin extent is in/near gauge range
        and dims[0] <= 2.2 * wall                    # thin extent IS the wall (a plate, not a deep shell)
        and dims[1] >= 4.0 * dims[0]                 # broadly planar, not a stick/block
    )
    return dims[0], planar_aspect, perimeter, sheet_like


def extract_drivers(geometry, mesh, features=None) -> GeoDrivers:
    volume_cm3 = (geometry.volume or 0.0) / 1000.0
    area_cm2 = (geometry.surface_area or 0.0) / 100.0
    dims = sorted(float(d) for d in geometry.bounding_box.dimensions)
    bbox_volume_cm3 = (dims[0] * dims[1] * dims[2]) / 1000.0

    # hull volume guard: convex_hull can fail on degenerate meshes -> bbox fallback
    try:
        hull_volume_cm3 = float(mesh.convex_hull.volume) / 1000.0
        if not math.isfinite(hull_volume_cm3) or hull_volume_cm3 <= 0:
            hull_volume_cm3 = bbox_volume_cm3
    except Exception:
        hull_volume_cm3 = bbox_volume_cm3

    # nominal wall = 2*V/A (mm). Plate/cooling proxy. Guard zero area.
    if geometry.surface_area and geometry.surface_area > 0:
        nominal_wall_mm = 2.0 * (geometry.volume or 0.0) / geometry.surface_area
    else:
        nominal_wall_mm = 0.0

    rotational, axis_len, cross_dia = is_rotational(geometry, mesh)
    is_valid = bool((geometry.volume or 0.0) > 0.0 and geometry.is_watertight)

    sheet_gauge_mm, planar_aspect, outline_perimeter_mm, sheet_like = _sheet_geometry(
        geometry.volume or 0.0, geometry.surface_area or 0.0, dims)
    bend_count = _bend_count(mesh)
    # A rotational solid is a turned/spun part, not a flat blank.
    sheet_like = sheet_like and not rotational

    return GeoDrivers(
        volume_cm3=volume_cm3,
        surface_area_cm2=area_cm2,
        bbox_mm=tuple(round(d, 2) for d in dims),
        bbox_volume_cm3=bbox_volume_cm3,
        hull_volume_cm3=hull_volume_cm3,
        nominal_wall_mm=nominal_wall_mm,
        face_count=int(geometry.face_count or 0),
        max_bbox_mm=dims[2],
        is_valid=is_valid,
        rotational=rotational,
        rot_axis_len_mm=axis_len,
        rot_cross_dia_mm=cross_dia,
        sheet_gauge_mm=round(sheet_gauge_mm, 3),
        planar_aspect=round(planar_aspect, 2),
        outline_perimeter_mm=round(outline_perimeter_mm, 2),
        bend_count=int(bend_count),
        sheet_like=sheet_like,
    )
