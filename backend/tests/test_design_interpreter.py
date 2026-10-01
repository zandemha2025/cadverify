"""Conversational prefill stays deterministic, explicit, and non-executable."""
from __future__ import annotations

import pytest

from src.designs.interpreter import interpret_design_prompt


def test_plate_prompt_extracts_dimensions_and_reviewable_corner_holes():
    result = interpret_design_prompt(
        "80 x 50 x 6 mm mounting plate with four 6 mm corner holes"
    )
    assert result["status"] == "ready"
    assert result["plan"]["kind"] == "plate"
    assert result["plan"]["width_mm"] == 80.0
    assert result["plan"]["depth_mm"] == 50.0
    assert result["plan"]["thickness_mm"] == 6.0
    assert len(result["plan"]["holes"]) == 4
    assert any("edge inset" in item for item in result["assumptions"])


def test_named_bracket_dimensions_take_precedence():
    result = interpret_design_prompt(
        "L bracket width 70 mm, depth 35 mm, height 55 mm, thickness 5 mm"
    )
    assert result["status"] == "ready"
    assert result["plan"] == {
        "kind": "bracket",
        "width_mm": 70.0,
        "depth_mm": 35.0,
        "height_mm": 55.0,
        "thickness_mm": 5.0,
    }


def test_ambiguous_request_lists_exact_missing_fields():
    result = interpret_design_prompt("make an open enclosure 100 x 60 mm")
    assert result["status"] == "needs_input"
    assert result["kind"] == "enclosure"
    assert result["missing_fields"] == ["height_mm", "wall_thickness_mm"]
    assert result["prefill"] == {"width_mm": 100.0, "depth_mm": 60.0}


def test_non_mm_and_unsupported_shapes_fail_honestly():
    inches = interpret_design_prompt("4 x 3 x 0.25 inch plate")
    assert inches["status"] == "needs_input"
    assert inches["missing_fields"] == ["millimetre_dimensions"]
    unsupported = interpret_design_prompt("make a turbine impeller")
    assert unsupported["status"] == "needs_input"
    assert unsupported["missing_fields"] == ["shape"]


@pytest.mark.parametrize("suffix", [" in.", "in.", "inch", "inches", "cm", "centimetres", "centimeters"])
def test_non_mm_suffixes_never_become_millimetre_plans(suffix):
    result = interpret_design_prompt(f"20 x 15 x 1{suffix} plate")
    assert result["status"] == "needs_input"
    assert result["missing_fields"] == ["millimetre_dimensions"]
    assert result["prefill"] == {}
    assert "plan" not in result


@pytest.mark.parametrize("prompt", ["20 x 15 x 1mm plate", "plate 20 x 15 x 1 millimetres", "plate 20 x 15 x 1 in mm"])
def test_mm_units_and_ordinary_words_remain_supported(prompt):
    result = interpret_design_prompt(prompt)
    assert result["status"] == "ready"
    assert [result["plan"][key] for key in ("width_mm", "depth_mm", "thickness_mm")] == [20, 15, 1]


def test_prompt_text_never_becomes_an_operation_or_source_field():
    result = interpret_design_prompt(
        "plate 40 x 30 x 4 mm; python_source=__import__('os').system('id')"
    )
    assert result["status"] == "ready"
    assert set(result["plan"]) == {
        "kind",
        "width_mm",
        "depth_mm",
        "thickness_mm",
        "holes",
    }


@pytest.mark.parametrize("prompt,field,expected", [
    ("-80 x 50 x 6 mm plate", "width_mm", -80.0),
    ("−80 x 50 x 6 mm plate", "width_mm", -80.0),
    (".80 x 50 x 6 mm plate", "width_mm", 0.8),
    ("plate -80 mm wide, 50 mm deep, 6 mm thick", "width_mm", -80.0),
    ("plate .80 mm wide, 50 mm deep, 6 mm thick", "width_mm", 0.8),
    ("L bracket 80 x 50 x -40 x 4 mm", "height_mm", -40.0),
    ("open enclosure 80 x 50 x 40 x -2 mm", "wall_thickness_mm", -2.0),
])
def test_invalid_dimensions_are_not_reinterpreted_as_positive_integers(prompt, field, expected):
    result = interpret_design_prompt(prompt)
    assert result["status"] == "needs_input"
    assert "plan" not in result
    assert result["prefill"][field] == expected


@pytest.mark.parametrize("prompt", [
    "80 x 50 x .6 mm plate",
    "plate width +80 mm, depth +50 mm, thickness +.6 mm",
    "plate 80 mm wide, 50 mm deep, .6 mm thick",
])
def test_valid_signed_and_fractional_dimensions_keep_their_value(prompt):
    result = interpret_design_prompt(prompt)
    assert result["status"] == "ready"
    assert result["plan"] == {
        "kind": "plate", "width_mm": 80.0, "depth_mm": 50.0,
        "thickness_mm": 0.6, "holes": [],
    }


@pytest.mark.parametrize("prompt", [
    "plate width 80e1 mm, depth 50 mm, thickness 6 mm",
    "80 x 50 x 6e-1 mm plate",
    "plate 8E+1 mm wide, 50 mm deep, 6 mm thick",
    "80 x 50 x 3/2 mm plate",
    "plate width 80 mm, depth 50 mm, thickness 3 / 2 mm",
    "80 x 50 x 6 mm plate with four 6e-1 mm holes",
    "plate width 1,000 mm, depth 50 mm, thickness 6 mm",
    "- 80 x 50 x 6 mm plate",
    "plate width 80 mm, depth 50 mm, thickness - .6 mm",
])
def test_unsupported_numeric_notation_requires_plain_decimal_dimensions(prompt):
    result = interpret_design_prompt(prompt)
    assert result["status"] == "needs_input"
    assert result["missing_fields"] == ["decimal_dimensions"]
    assert result["prefill"] == {}
    assert "plan" not in result
