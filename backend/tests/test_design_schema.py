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


# ── Draft angle (plate and open enclosure) ────────────────────
_ENCLOSURE = {
    "kind": "enclosure",
    "width_mm": 120.0,
    "depth_mm": 80.0,
    "height_mm": 40.0,
    "wall_thickness_mm": 1.0,
}
_PLATE = {
    "kind": "plate",
    "width_mm": 80.0,
    "depth_mm": 50.0,
    "thickness_mm": 6.0,
    "holes": [{"x_mm": -30.0, "y_mm": -15.0, "diameter_mm": 6.0}],
}


@pytest.mark.parametrize("legacy", [_ENCLOSURE, _PLATE])
def test_saved_plans_without_draft_load_and_store_unchanged(legacy):
    plan = validate_design_plan(dict(legacy))
    assert plan.draft_angle_deg == 0.0
    assert plan.model_dump(mode="json") == legacy
    zero = validate_design_plan({**legacy, "draft_angle_deg": 0})
    assert zero.model_dump(mode="json") == legacy  # 0 is today's plan, byte for byte


@pytest.mark.parametrize("legacy", [_ENCLOSURE, _PLATE])
def test_draft_is_stored_when_set(legacy):
    plan = validate_design_plan({**legacy, "draft_angle_deg": 1.5})
    assert plan.model_dump(mode="json") == {**legacy, "draft_angle_deg": 1.5}
    assert validate_design_plan({**legacy, "draft_angle_deg": 2}).draft_angle_deg == 2.0


@pytest.mark.parametrize("value", [-0.5, 10.5, float("nan"), float("inf"), "1.5", True, None])
def test_draft_is_bounded_to_ten_degrees(value):
    with pytest.raises(ValidationError):
        validate_design_plan({**_ENCLOSURE, "draft_angle_deg": value})


def test_bracket_has_no_draft_setting():
    with pytest.raises(ValidationError, match="draft_angle_deg"):
        validate_design_plan(
            {
                "kind": "bracket",
                "width_mm": 70.0,
                "depth_mm": 35.0,
                "height_mm": 55.0,
                "thickness_mm": 5.0,
                "draft_angle_deg": 1.5,
            }
        )


def test_enclosure_draft_must_leave_an_interior_at_the_base():
    tall = {**_ENCLOSURE, "width_mm": 40.0, "depth_mm": 30.0, "height_mm": 200.0, "wall_thickness_mm": 2.0}
    validate_design_plan(tall)
    validate_design_plan({**tall, "draft_angle_deg": 2.0})
    with pytest.raises(ValidationError, match="no usable interior at the base"):
        validate_design_plan({**tall, "draft_angle_deg": 10.0})


def test_plate_draft_margins_are_checked_at_the_top_face():
    near_edge = {
        "kind": "plate",
        "width_mm": 40.0,
        "depth_mm": 40.0,
        "thickness_mm": 20.0,
        "holes": [{"x_mm": 14.0, "y_mm": 0.0, "diameter_mm": 4.0}],
    }
    validate_design_plan(near_edge)
    validate_design_plan({**near_edge, "draft_angle_deg": 2.0})
    with pytest.raises(ValidationError, match="edge margin"):
        validate_design_plan({**near_edge, "draft_angle_deg": 5.0})
    pair = {**near_edge, "holes": [{"x_mm": -3.0, "y_mm": 0.0, "diameter_mm": 4.0}, {"x_mm": 3.0, "y_mm": 0.0, "diameter_mm": 4.0}]}
    validate_design_plan(pair)
    with pytest.raises(ValidationError, match="holes overlap"):
        validate_design_plan({**pair, "draft_angle_deg": 3.0})
    with pytest.raises(ValidationError, match="top face"):
        validate_design_plan({"kind": "plate", "width_mm": 20.0, "depth_mm": 20.0, "thickness_mm": 100.0, "draft_angle_deg": 10.0})
