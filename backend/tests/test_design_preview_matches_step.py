"""A Design Studio preview STL gets the same findings as the STEP it came with.

The preview was meshed at a fixed size with no curvature sizing, so a 6 mm
hole in a 100 mm plate came out with ~11 facets zigzagging across the 3 mm
plate, leaning 11 degrees: molding read them as undercuts and milling as
sharp inside corners, while the STEP of the same plate (meshed with holes at
least 12 facets round) had neither.
"""
import importlib.util
import re

import pytest

pytestmark = pytest.mark.skipif(importlib.util.find_spec("gmsh") is None, reason="gmsh is not installed")

PLAN = {"kind": "plate", "width_mm": 100.0, "depth_mm": 60.0, "thickness_mm": 3.0,
        "holes": [{"x_mm": -35.0, "y_mm": 0.0, "diameter_mm": 6.0}, {"x_mm": 35.0, "y_mm": 0.0, "diameter_mm": 6.0}]}


def _findings(data: bytes, filename: str) -> dict[str, set[str]]:
    from src.api.routes import _parse_mesh, _run_cost_engine_ctx

    mesh, _ = _parse_mesh(data, filename)
    result, _m, _ctx = _run_cost_engine_ctx(mesh, filename)
    return {s.process.value: {i.code for i in s.issues if not re.search(r"_PRECISION$", i.code)}
            for s in result.process_scores}


def test_the_holed_plate_preview_reads_like_its_step():
    from src.designs.generator import generate_design_artifacts

    art = generate_design_artifacts(PLAN, timeout_seconds=60.0)
    stl = _findings(art.stl_bytes, "plate.stl")
    step = _findings(art.step_bytes, "plate.step")
    assert "UNDERCUT_MOLDING" not in stl["injection_molding"]
    assert stl == step
