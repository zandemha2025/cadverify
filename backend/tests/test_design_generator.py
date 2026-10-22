"""Real-kernel smoke tests for the isolated Design Studio generator."""
from __future__ import annotations

import importlib.util

import pytest

from src.designs.generator import generate_design_artifacts

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("gmsh") is None,
    reason="gmsh is not installed",
)


def test_generator_emits_real_step_and_stl_for_plate():
    result = generate_design_artifacts(
        {
            "kind": "plate",
            "width_mm": 50.0,
            "depth_mm": 30.0,
            "thickness_mm": 4.0,
            "holes": [{"x_mm": 0.0, "y_mm": 0.0, "diameter_mm": 5.0}],
        },
        timeout_seconds=20.0,
    )
    assert b"ISO-10303-21" in result.step_bytes[:256]
    assert result.stl_bytes.startswith(b"solid")
    assert result.metadata["bbox_mm"] == [50.0, 30.0, 4.0]
    assert result.metadata["volume_cm3"] > 0
    assert result.metadata["surface_elements"] > 0
    assert result.metadata["engine"] == "proofshape-occ-v1"


# ── Draft angle ───────────────────────────────────────────────
import io  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

_ENCLOSURE = {
    "kind": "enclosure",
    "width_mm": 120.0,
    "depth_mm": 80.0,
    "height_mm": 40.0,
    "wall_thickness_mm": 1.0,
}


def _solid(stl_bytes: bytes) -> trimesh.Trimesh:
    mesh = trimesh.load(io.BytesIO(stl_bytes), file_type="stl")
    assert mesh.is_watertight and mesh.is_volume and mesh.body_count == 1
    return mesh


def _faces(step_bytes: bytes, kind: bytes) -> int:
    return len(re.findall(rb"=\s*" + kind + rb"\(", step_bytes))


def _tapered_volume(half_x: float, half_y: float, length: float, tan: float) -> float:
    """Integral of a rectangle shrinking by ``tan`` per mm on each side."""
    return 4.0 * (half_x * half_y * length - (half_x + half_y) * tan * length**2 / 2.0 + tan**2 * length**3 / 3.0)


def test_zero_draft_enclosure_is_todays_geometry():
    plain = generate_design_artifacts(_ENCLOSURE, timeout_seconds=30.0)
    zero = generate_design_artifacts({**_ENCLOSURE, "draft_angle_deg": 0.0}, timeout_seconds=30.0)
    assert plain.stl_bytes == zero.stl_bytes
    assert plain.metadata == zero.metadata
    assert plain.metadata["bbox_mm"] == [120.0, 80.0, 40.0]
    assert plain.metadata["volume_cm3"] == 25.044  # 120·80·40 − 118·78·39 mm³


def test_drafted_enclosure_tapers_inside_and_out_and_keeps_the_wall():
    from src.analysis.base_analyzer import analyze_geometry
    from src.analysis.context import GeometryContext
    from src.analysis.features import detect_all
    from src.analysis.models import ProcessType
    from src.analysis.processes.checks import check_draft_angles

    angle = 1.5
    result = generate_design_artifacts({**_ENCLOSURE, "draft_angle_deg": angle}, timeout_seconds=30.0)
    tan, cos = math.tan(math.radians(angle)), math.cos(math.radians(angle))
    # The open rim keeps the stated 120 × 80; the walls lean in toward the base.
    assert result.metadata["bbox_mm"] == [120.0, 80.0, 40.0]
    offset = 1.0 / cos
    expected = _tapered_volume(60.0, 40.0, 40.0, tan) - _tapered_volume(60.0 - offset, 40.0 - offset, 39.0, tan)
    assert result.metadata["volume_cm3"] == pytest.approx(expected / 1000.0, abs=2e-6)
    # Real planes in the STEP export, not lofted B-splines.
    assert _faces(result.step_bytes, b"ADVANCED_FACE") == 11
    assert _faces(result.step_bytes, b"PLANE") == 11
    assert b"B_SPLINE_SURFACE" not in result.step_bytes

    mesh = _solid(result.stl_bytes)
    lo, hi = mesh.bounds
    assert np.allclose(hi - lo, [120.0, 80.0, 40.0], atol=1e-4)
    base = mesh.vertices[np.abs(mesh.vertices[:, 2]) < 1e-6]
    assert np.ptp(base[:, 0]) == pytest.approx(120.0 - 2 * 40.0 * tan, abs=1e-4)
    # Wall thickness measured square to each leaning wall: outside plane to inside plane.
    for outward in ((cos, 0.0, -math.sin(math.radians(angle))), (0.0, cos, -math.sin(math.radians(angle)))):
        n = np.array(outward)
        outer = np.abs(mesh.face_normals @ n - 1.0) < 1e-6
        inner = np.abs(mesh.face_normals @ -n - 1.0) < 1e-6
        assert outer.any() and inner.any()
        d_out, d_in = mesh.triangles_center[outer] @ n, mesh.triangles_center[inner] @ n
        assert np.ptp(d_out) < 1e-4 and np.ptp(d_in) < 1e-4
        assert d_out.mean() - d_in.mean() == pytest.approx(1.0, abs=1e-4)

    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_all(ctx.mesh)
    assert check_draft_angles(ctx, 1.0, ProcessType.INJECTION_MOLDING) == []
    (sand,) = check_draft_angles(ctx, 3.0, ProcessType.SAND_CASTING)
    assert sand.measured_value == 1.5


def test_drafted_plate_keeps_its_bottom_face_and_opens_the_holes_upward():
    angle, thickness, radius = 2.0, 6.0, 3.0
    holes = [{"x_mm": -30.0, "y_mm": -15.0, "diameter_mm": 6.0}, {"x_mm": 30.0, "y_mm": 15.0, "diameter_mm": 6.0}]
    plan = {"kind": "plate", "width_mm": 80.0, "depth_mm": 50.0, "thickness_mm": thickness, "holes": holes, "draft_angle_deg": angle}
    result = generate_design_artifacts(plan, timeout_seconds=30.0)
    tan = math.tan(math.radians(angle))
    assert result.metadata["bbox_mm"] == [80.0, 50.0, 6.0]
    top = radius + thickness * tan
    block = _tapered_volume(40.0, 25.0, thickness, tan)
    cones = 2 * math.pi * thickness / 3.0 * (radius**2 + radius * top + top**2)
    assert result.metadata["volume_cm3"] == pytest.approx((block - cones) / 1000.0, abs=2e-6)
    assert _faces(result.step_bytes, b"CONICAL_SURFACE") == 2
    assert _faces(result.step_bytes, b"PLANE") == 6
    assert b"B_SPLINE_SURFACE" not in result.step_bytes

    mesh = _solid(result.stl_bytes)
    v = mesh.vertices
    near = np.hypot(v[:, 0] + 30.0, v[:, 1] + 15.0) < 5.0
    bottom = near & (np.abs(v[:, 2]) < 1e-6)
    upper = near & (np.abs(v[:, 2] - thickness) < 1e-6)
    # Face nodes sit on or outside each rim, so the nearest is the rim itself.
    # The stated diameter holds at the bottom face (the narrowest point).
    assert np.hypot(v[bottom, 0] + 30.0, v[bottom, 1] + 15.0).min() == pytest.approx(radius, abs=1e-3)
    assert np.hypot(v[upper, 0] + 30.0, v[upper, 1] + 15.0).min() == pytest.approx(top, abs=1e-3)


@pytest.mark.parametrize("plan", [
    {"kind": "plate", "width_mm": 80.0, "depth_mm": 50.0, "thickness_mm": 6.0, "draft_angle_deg": 2.0},
    {"kind": "plate", "width_mm": 80.0, "depth_mm": 50.0, "thickness_mm": 6.0, "draft_angle_deg": 2.0,
     "holes": [{"x_mm": -30.0, "y_mm": -15.0, "diameter_mm": 6.0}]},
    {**_ENCLOSURE, "draft_angle_deg": 3.0},
    {"kind": "bracket", "width_mm": 40.0, "depth_mm": 30.0, "height_mm": 40.0, "thickness_mm": 3.0},
])
def test_preview_stl_reads_as_the_same_valid_solid_as_the_step(plan):
    """W15: the preview of a drafted plate came out with inward-wound faces
    (INCONSISTENT_NORMALS → geometry invalid) while its STEP was a valid solid."""
    from src.analysis.base_analyzer import run_universal_checks
    from src.api import routes

    result = generate_design_artifacts(plan, timeout_seconds=30.0)
    verdicts = {}
    for name, data in (("preview.stl", result.stl_bytes), ("model.step", result.step_bytes)):
        mesh, _ = routes._parse_mesh(data, name)
        assert mesh.is_winding_consistent and mesh.is_volume, name
        verdicts[name] = sorted(i.code for i in run_universal_checks(mesh) if i.severity.value == "error")
    assert verdicts == {"preview.stl": [], "model.step": []}
