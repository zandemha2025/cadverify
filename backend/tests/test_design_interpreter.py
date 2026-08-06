"""Conversational prefill stays deterministic, explicit, and non-executable."""
from __future__ import annotations

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
