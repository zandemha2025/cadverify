"""MEASURED geometry drivers (spec §3).

Everything in GeoDrivers is extracted from the CAD — never assumed. These feed
the cost model's material mass, stock removal, cooling-time and routing logic.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np
import trimesh

from src.analysis.constants import SHEET_GAUGE_MAX_MM
from src.analysis.context import enclosing_box_dimensions, flat_sheet_geometry, wall_thickness_tolerance, minimum_width_lower_bound
from src.analysis.context import fitting_box_dimensions as build_orientation
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
    sheet_gauge_mm: float = 0.0       # distance between verified parallel sheet caps
    planar_aspect: float = 0.0        # mid_dim / gauge — flatness of the part
    outline_perimeter_mm: float = 0.0 # laser/punch cut length (outer + cutouts)
    bend_count: int = 0               # verified flat blanks have no bends
    sheet_like: bool = False          # geometry reads as a constant-gauge flat sheet
    sheet_blank_mm: tuple | None = None  # gauge, short side, long side in the sheet plane
    sheet_tolerance_mm: float = 0.0   # numeric transform noise, not manufacturing allowance
    sheet_precision_mm: float = 0.0   # source coordinate rounding, not a fit allowance
    sheet_outline_xy: tuple = ()      # convex outline in the measured sheet plane
    billet_bbox_mm: tuple | None = None  # enclosing oriented stock candidate, not a certified minimum
    billet_basis: str = "file-axis fallback"
    bbox_precision_mm: float = 0.0  # enclosing-dimension uncertainty, both sides
    minimum_width_bound_mm: float = 0.0  # hull-sphere diameter, before source-error allowance

    # ---- derived (MEASURED) ---------------------------------------------
    def mass_kg(self, density_g_cm3: float) -> float:
        """Part mass: CAD volume × material density."""
        return self.volume_cm3 * density_g_cm3 / 1000.0

    def stock_mass_kg(self, density_g_cm3: float, stock_allowance: float) -> float:
        """CNC-turning round-stock mass, including the declared oversize."""
        return self.turning_stock_volume_cm3(stock_allowance) * density_g_cm3 / 1000.0

    def turning_stock_volume_cm3(self, stock_allowance: float) -> float:
        """Enclosing round bar × volume allowance, shared by material and roughing."""
        # ponytail: solid round bar; tube/near-net stock needs an explicit stock declaration.
        return math.pi * (self.rot_cross_dia_mm / 2) ** 2 * self.rot_axis_len_mm / 1000 * stock_allowance

    def mass_source(self, density_g_cm3: float, material_name: str) -> str:
        return (f"CAD volume {self.volume_cm3:.2f} cm³ × {material_name} density "
                f"{density_g_cm3:.2f} g/cm³")

    def stock_source(self, density_g_cm3: float, stock_allowance: float,
                     material_name: str) -> str:
        return (f"bounding cylinder Ø{self.rot_cross_dia_mm:.2f} × {self.rot_axis_len_mm:.2f} mm "
                f"× {stock_allowance:.2f} stock allowance = {self.turning_stock_volume_cm3(stock_allowance):.2f} cm³ "
                f"× {material_name} density {density_g_cm3:.2f} g/cm³ [assumption, not shop-validated]")

    # ---- Milling / wire-EDM billet: enclosing rectangular stock ------
    def billet_volume_cm3(self, stock_allowance: float) -> float:
        """CNC-milling raw-stock (billet) volume you actually buy: the bounding
        oriented candidate box × oversize. A pocketed/non-convex part is sawn from a solid
        rectangular block, NOT a hull-shaped blank — hull volume understates the
        required rectangular stock. Off-switch recovers hull."""
        box = math.prod(self.billet_bbox_mm) / 1000 if self.billet_bbox_mm else self.bbox_volume_cm3
        v = box if bbox_billet_enabled() else self.hull_volume_cm3
        return v * stock_allowance

    def billet_mass_kg(self, density_g_cm3: float, stock_allowance: float) -> float:
        return self.billet_volume_cm3(stock_allowance) * density_g_cm3 / 1000.0

    def billet_source(self, density_g_cm3: float, stock_allowance: float,
                      material_name: str) -> str:
        if not bbox_billet_enabled():
            return (f"hull volume {self.hull_volume_cm3:.2f} cm³ × {stock_allowance:.2f} "
                    f"stock allowance × {material_name} density {density_g_cm3:.2f} g/cm³")
        basis = self.billet_basis
        if self.billet_bbox_mm:
            basis += " " + "×".join(f"{d:.4g}" for d in self.billet_bbox_mm) + " mm"
        basis += "; minimum not certified"
        return (f"bounding-box billet {self.billet_volume_cm3(1):.2f} cm³ ({basis}) × "
                f"{stock_allowance:.2f} stock allowance × {material_name} density "
                f"{density_g_cm3:.2f} g/cm³ [assumption, not shop-validated]")


def parts_per_build(proc, bbox_mm, rates, envelope=None) -> int:
    """Build-plate nesting count (weaknesses #1, #2; R2 serial XY nesting).

    build_job (powder-bed/DLP): VOLUMETRIC fit — how many part bounding boxes
    (each grown by part-spacing on every axis) pack into the machine envelope at
    the process packing_density (unchanged).

    serial (FDM/SLA): AREAL (XY-footprint) fit — one layer on the plate, using
    an established enclosing-box placement (axis swaps, then diagonal fallback).
    Real service bureaus nest many parts in X-Y on one build plate (just not
    stacked in Z like powder bed). Both density estimates are bounded by a
    spaced grid in that orientation. No fitting box yields zero, not one.
    """
    envelope = rates.build_env(proc) if envelope is None else envelope
    dims = build_orientation(bbox_mm, envelope)
    if dims is None:
        return 0
    s = rates.part_spacing(proc)
    # A density fraction alone cannot prove that even two boxes fit. Bound it
    # by an actual spaced grid in the same orientation used for build height.
    grid = [math.floor((lim + s + 1e-9) / (d + s)) for d, lim in zip(dims, envelope)]
    if rates.nesting_mode(proc) == "serial":
        X, Y, _Z = envelope
        plate_area = X * Y                                       # mm^2
        footprint = (dims[0] + s) * (dims[1] + s)
        n = int(rates.xy_packing_density(proc) * plate_area / footprint)
        return min(grid[0] * grid[1], max(1, n))
    X, Y, Z = envelope
    part_vol_cm3 = math.prod(d + s for d in dims) / 1000.0
    env_vol_cm3 = (X * Y * Z) / 1000.0
    n = int(rates.packing_density(proc) * env_vol_cm3 / part_vol_cm3)
    return min(math.prod(grid), max(1, n))


def _sheet_geometry(volume_mm3, surface_area_mm2, dims, tolerance=0.0):
    """Sheet gauge, planar aspect, cut perimeter, and the sheet-like predicate.

    gauge t   = verified separation of the sheet's parallel caps.
    blank A   = V / t  (developed flat area; exact for a constant-thickness plate).
    perimeter = rim_area / t where rim_area = SA - 2*blank  (the thickness-walls
                swept by the cut path: outer outline + every hole/cutout edge),
                without counting unused rectangular stock as a cut. This is the MEASURED
                laser/punch cut length — not a magic constant.
    sheet_like = constant thin gauge (t<=6mm, wall~=t) AND broadly planar
                 (mid extent >= 4x gauge). Distinguishes a flat sheet from a
                 deep thin-walled box (whose thin extent is NOT the wall).
    """
    if dims is None:
        return 0.0, 0.0, 0.0, False
    t = max(dims[0], 1e-6)
    wall = (2.0 * volume_mm3 / surface_area_mm2) if surface_area_mm2 > 0 else t
    blank_area = volume_mm3 / t
    rim_area = max(0.0, surface_area_mm2 - 2.0 * blank_area)
    rim_perim = rim_area / t
    perimeter = rim_perim
    planar_aspect = dims[1] / t if t > 0 else 0.0
    sheet_like = bool(
        wall <= SHEET_GAUGE_MAX_MM + tolerance
        and dims[0] <= SHEET_GAUGE_MAX_MM + 2.0 + tolerance
        and dims[0] <= 2.2 * wall + 3.2 * tolerance
        and dims[1] + 5.0 * tolerance >= 4.0 * dims[0]
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

    rotational, axis_len, cross_dia = is_rotational(geometry, mesh, features)
    is_valid = bool((geometry.volume or 0.0) > 0.0 and geometry.is_watertight)

    sheet_geometry = flat_sheet_geometry(mesh)
    sheet_blank_mm = sheet_geometry[0] if sheet_geometry is not None else None
    sheet_tolerance_mm = wall_thickness_tolerance(
        mesh, max(1e-4, min(float(np.linalg.norm(dims)) * 1e-4, .1)))
    sheet_precision_mm = sheet_geometry[2] if sheet_geometry is not None else 0.0
    sheet_gauge_mm, planar_aspect, outline_perimeter_mm, sheet_like = _sheet_geometry(
        geometry.volume or 0.0, geometry.surface_area or 0.0, sheet_blank_mm,
        sheet_tolerance_mm + sheet_precision_mm)
    # A rotational solid is a turned/spun part, not a flat blank.
    sheet_like = sheet_like and not rotational

    billet_bbox_mm, billet_basis = enclosing_box_dimensions(mesh)

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
        sheet_gauge_mm=sheet_gauge_mm,
        planar_aspect=round(planar_aspect, 2),
        outline_perimeter_mm=round(outline_perimeter_mm, 2),
        bend_count=0,  # Only verified flat blanks are sheet-costable; no bends.
        sheet_like=sheet_like,
        sheet_blank_mm=sheet_blank_mm,
        sheet_tolerance_mm=sheet_tolerance_mm,
        sheet_precision_mm=sheet_precision_mm,
        sheet_outline_xy=(tuple(map(tuple, sheet_geometry[1])) if sheet_geometry is not None else ()),
        billet_bbox_mm=billet_bbox_mm,
        billet_basis=billet_basis,
        bbox_precision_mm=2 * float(mesh.metadata.get("coordinate_error", 0.0)),
        minimum_width_bound_mm=minimum_width_lower_bound(mesh),
    )
