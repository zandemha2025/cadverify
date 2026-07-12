"""Security and geometry-boundary tests for the non-executable design plan."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.designs.schema import validate_design_plan


def test_plate_plan_accepts_bounded_through_holes():
    plan = validate_design_plan(
        {
            "kind": "plate",
            "width_mm": 80.0,
            "depth_mm": 50.0,
            "thickness_mm": 6.0,
            "holes": [
                {"x_mm": -25.0, "y_mm": -12.0, "diameter_mm": 6.0},
                {"x_mm": 25.0, "y_mm": 12.0, "diameter_mm": 6.0},
            ],
        }
    )
    assert plan.kind == "plate"
    assert len(plan.holes) == 2


def test_plan_rejects_unknown_or_executable_fields():
    with pytest.raises(ValidationError):
        validate_design_plan(
            {
                "kind": "plate",
                "width_mm": 80.0,
                "depth_mm": 50.0,
                "thickness_mm": 6.0,
                "holes": [],
                "python_source": "__import__('os').system('id')",
            }
        )


def test_plate_rejects_hole_outside_material():
    with pytest.raises(ValidationError, match="edge margin"):
        validate_design_plan(
            {
                "kind": "plate",
                "width_mm": 40.0,
                "depth_mm": 40.0,
                "thickness_mm": 4.0,
                "holes": [{"x_mm": 19.0, "y_mm": 0.0, "diameter_mm": 4.0}],
            }
        )


def test_plate_rejects_overlapping_holes():
    with pytest.raises(ValidationError, match="holes overlap"):
        validate_design_plan(
            {
                "kind": "plate",
                "width_mm": 60.0,
                "depth_mm": 40.0,
                "thickness_mm": 4.0,
                "holes": [
                    {"x_mm": 0.0, "y_mm": 0.0, "diameter_mm": 8.0},
                    {"x_mm": 5.0, "y_mm": 0.0, "diameter_mm": 8.0},
                ],
            }
        )


@pytest.mark.parametrize(
    "plan",
    [
        {
            "kind": "bracket",
            "width_mm": 40.0,
            "depth_mm": 30.0,
            "height_mm": 50.0,
            "thickness_mm": 25.0,
        },
        {
            "kind": "enclosure",
            "width_mm": 40.0,
            "depth_mm": 40.0,
            "height_mm": 20.0,
            "wall_thickness_mm": 11.0,
        },
    ],
)
def test_cross_field_dimensions_fail_closed(plan):
    with pytest.raises(ValidationError):
        validate_design_plan(plan)
