"""Deterministic, internally authored CAD fixtures for costing regression tests.

The production test suite used to depend on a private archive of third-party STL
files whose per-model redistribution licenses were not recorded.  That made the
tests impossible to reproduce in CI and unsafe to vendor.  This module generates
an equivalent *calibration* suite from primitives at test/run time instead:

* every recipe is authored in this repository and opens no sockets;
* the envelopes span tiny through large, flat/boxy/rotational geometry;
* thin datum struts lock each audited packing envelope; and
* one intentionally open shell proves invalid geometry is never costed.

These fixtures are model-regression coupons, not supplier parts and not ground
truth.  Real-part/supplier-quote validation remains a separate opt-in harness.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import trimesh


CALIBRATION_FIXTURE_VERSION = "costing-calibration-v2"
INVALID_FIXTURE_NAME = "cv_cal_invalid_open_shell.stl"


@dataclass(frozen=True)
class CalibrationRecipe:
    filename: str
    kind: str
    volume_mm3: float
    bbox_mm: tuple[float, float, float]
    core_primary_mm: float
    core_secondary_mm: float

    @property
    def tier(self) -> str:
        volume_cm3 = self.volume_mm3 / 1000.0
        if volume_cm3 < 5:
            return "tiny"
        if volume_cm3 < 30:
            return "small"
        if volume_cm3 < 150:
            return "medium"
        return "large"

    @property
    def shape(self) -> str:
        if self.kind == "annulus":
            return "rotational"
        return "flat" if min(self.bbox_mm) / max(self.bbox_mm) < 0.30 else "boxy"


# The volume and envelope targets preserve the coverage buckets of the original
# private benchmark without reproducing any third-party surface geometry.
CALIBRATION_RECIPES = (
    CalibrationRecipe(
        "cv_cal_medium_flat_mount.stl",
        "box",
        66_790.0,
        (160.0, 62.05, 32.57),
        160.0,
        42.235,
    ),
    CalibrationRecipe(
        "cv_cal_tiny_rotational_adapter.stl",
        "annulus",
        2_811.6,
        (39.9364, 34.0, 22.178),
        34.0,
        22.178,
    ),
    CalibrationRecipe(
        "cv_cal_tiny_rotational_ring.stl",
        "annulus",
        1_192.94,
        (25.7394, 23.25, 11.046),
        23.25,
        11.046,
    ),
    CalibrationRecipe(
        "cv_cal_large_flat_enclosure.stl",
        "box",
        280_172.8,
        (353.781, 160.68, 104.714),
        353.781,
        150.0,
    ),
    CalibrationRecipe(
        "cv_cal_large_rotational_flange.stl",
        "annulus",
        248_713.9,
        (142.616, 132.94, 35.56),
        132.94,
        35.56,
    ),
    CalibrationRecipe(
        "cv_cal_medium_boxy_spacer.stl",
        "box",
        61_212.2,
        (127.0, 100.0, 63.743),
        127.0,
        100.0,
    ),
    CalibrationRecipe(
        "cv_cal_medium_rotational_bracket.stl",
        "annulus",
        37_433.3,
        (118.182, 97.99, 63.45),
        80.0,
        63.45,
    ),
    CalibrationRecipe(
        "cv_cal_small_boxy_bracket.stl",
        "box",
        22_046.6,
        (120.57, 80.0, 38.45),
        120.57,
        64.0,
    ),
    CalibrationRecipe(
        "cv_cal_small_flat_housing.stl",
        "box",
        5_424.2,
        (55.5, 45.0, 9.75),
        55.5,
        30.0,
    ),
    CalibrationRecipe(
        "cv_cal_small_rotational_sensor.stl",
        "annulus",
        5_308.6,
        (34.0, 34.0, 27.3),
        34.0,
        27.3,
    ),
    CalibrationRecipe(
        "cv_cal_tiny_boxy_cover.stl",
        "box",
        3_281.8,
        (43.863, 20.27, 14.5),
        43.863,
        15.0,
    ),
    CalibrationRecipe(
        "cv_cal_tiny_flat_gasket.stl",
        "box",
        179.53,
        (39.9368, 34.0, 0.6),
        39.9368,
        8.7,
    ),
)

CALIBRATION_FILENAMES = tuple(recipe.filename for recipe in CALIBRATION_RECIPES)


def _box_core(recipe: CalibrationRecipe) -> trimesh.Trimesh:
    length = recipe.core_primary_mm
    width = recipe.core_secondary_mm
    thickness = recipe.volume_mm3 / (length * width)
    return trimesh.creation.box(extents=(length, width, thickness))


def _annulus_core(recipe: CalibrationRecipe) -> trimesh.Trimesh:
    outer_radius = recipe.core_primary_mm / 2.0
    height = recipe.core_secondary_mm
    inner_sq = outer_radius**2 - recipe.volume_mm3 / (math.pi * height)
    if inner_sq <= 0:
        raise ValueError(f"invalid annulus recipe: {recipe.filename}")
    return trimesh.creation.annulus(
        r_min=math.sqrt(inner_sq),
        r_max=outer_radius,
        height=height,
        sections=64,
    )


def _with_envelope_datums(
    core: trimesh.Trimesh, recipe: CalibrationRecipe
) -> trimesh.Trimesh:
    """Union a thin XYZ datum cross into ``core`` to lock its packing envelope."""
    datum_thickness = min(1.5, min(recipe.bbox_mm))
    rods_volume = datum_thickness**2 * sum(recipe.bbox_mm)
    scale = ((recipe.volume_mm3 - rods_volume) / core.volume) ** (1.0 / 3.0)
    core.apply_scale(scale)

    # Keep the authored body inside the target envelope after the volume tweak.
    limits = [
        target / current if current else 1.0
        for target, current in zip(recipe.bbox_mm, core.extents)
    ]
    if min(limits) < 1.0:
        core.apply_scale(min(limits) * 0.999999)

    datums: list[trimesh.Trimesh] = []
    for axis, length in enumerate(recipe.bbox_mm):
        extents = [datum_thickness, datum_thickness, datum_thickness]
        extents[axis] = length
        datums.append(trimesh.creation.box(extents=extents))

    # manifold3d is pinned through trimesh[easy] in the production lock.  The
    # union leaves one connected, watertight body instead of overlapping shells.
    result = trimesh.boolean.union([core, *datums], engine="manifold")
    if result is None or not result.is_watertight or len(result.split()) != 1:
        raise RuntimeError(f"failed to build calibration fixture: {recipe.filename}")
    return result


def _build_fixture(recipe: CalibrationRecipe) -> trimesh.Trimesh:
    if recipe.kind == "box":
        core = _box_core(recipe)
    elif recipe.kind == "annulus":
        core = _annulus_core(recipe)
    else:  # pragma: no cover - recipe table is static and reviewed
        raise ValueError(f"unknown calibration geometry kind: {recipe.kind}")
    return _with_envelope_datums(core, recipe)


def _build_invalid_fixture() -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=(30.0, 20.0, 8.0))
    mesh.faces = mesh.faces[:-1]
    mesh.remove_unreferenced_vertices()
    if mesh.is_watertight:  # pragma: no cover - invariant guard
        raise RuntimeError("invalid calibration fixture unexpectedly became watertight")
    return mesh


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cache_is_current(destination: Path) -> bool:
    manifest_path = destination / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    if manifest.get("version") != CALIBRATION_FIXTURE_VERSION:
        return False
    expected = set(CALIBRATION_FILENAMES) | {INVALID_FIXTURE_NAME}
    recorded = manifest.get("sha256") or {}
    return set(recorded) == expected and all(
        (destination / name).is_file()
        and _sha256(destination / name) == recorded[name]
        for name in expected
    )


def ensure_calibration_fixtures(cache_root: Path) -> Path:
    """Materialize the deterministic suite under ``cache_root`` and return it."""
    destination = cache_root / CALIBRATION_FIXTURE_VERSION
    if _cache_is_current(destination):
        return destination

    destination.mkdir(parents=True, exist_ok=True)
    meshes = {
        recipe.filename: _build_fixture(recipe) for recipe in CALIBRATION_RECIPES
    }
    meshes[INVALID_FIXTURE_NAME] = _build_invalid_fixture()

    hashes: dict[str, str] = {}
    for name, mesh in meshes.items():
        target = destination / name
        temporary = destination / f".{name}.{os.getpid()}.tmp"
        payload = mesh.export(file_type="stl")
        if not isinstance(payload, bytes):  # pragma: no cover - STL exporter contract
            raise TypeError(f"STL exporter returned {type(payload).__name__}")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
        hashes[name] = _sha256(target)

    manifest = {
        "version": CALIBRATION_FIXTURE_VERSION,
        "origin": "internally-authored deterministic primitives",
        "external_assets": False,
        "ground_truth": False,
        "sha256": hashes,
    }
    temporary_manifest = destination / f".manifest.{os.getpid()}.tmp"
    temporary_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_manifest, destination / "manifest.json")
    return destination
