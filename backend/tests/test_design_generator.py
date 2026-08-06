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
