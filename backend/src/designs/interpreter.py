"""Deterministic natural-language prefill for the safe template contract.

This is intentionally not an LLM and never generates geometry directly. It
extracts explicit millimetre dimensions for the allowlisted first-release
templates, reports missing information, and requires the user to review the
result before the ordinary create/revision endpoint can persist or generate it.
"""
from __future__ import annotations

import re
from typing import Any, cast

from pydantic import ValidationError

from src.designs.schema import validate_design_plan

MAX_PROMPT_CHARS = 500
_NUMBER = r"(\d+(?:\.\d+)?)"


def _number_after(text: str, names: tuple[str, ...]) -> float | None:
    joined = "|".join(re.escape(name) for name in names)
    patterns = (
        rf"(?:{joined})\s*(?:of|is|=|:)?\s*{_NUMBER}\s*(?:mm|millimet(?:er|re)s?)?",
        rf"{_NUMBER}\s*(?:mm|millimet(?:er|re)s?)?\s*(?:{joined})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            values = [group for group in match.groups() if group is not None]
            return float(values[-1])
    return None


def _dimension_sequence(text: str) -> list[float]:
    match = re.search(
        rf"{_NUMBER}\s*(?:mm)?\s*[x×]\s*{_NUMBER}"
        rf"(?:\s*(?:mm)?\s*[x×]\s*{_NUMBER})?"
        rf"(?:\s*(?:mm)?\s*[x×]\s*{_NUMBER})?\s*(?:mm)?",
        text,
    )
    if not match:
        return []
    return [float(value) for value in match.groups() if value is not None]


def _kind(text: str) -> str | None:
    if any(word in text for word in ("enclosure", "open box", "tray", "housing")):
        return "enclosure"
    if any(word in text for word in ("l bracket", "l-bracket", "angle bracket", "bracket")):
        return "bracket"
    if any(word in text for word in ("plate", "mounting plate", "flat bar")):
        return "plate"
    return None


def _hole_diameter(text: str) -> float | None:
    patterns = (
        rf"(?:four|4)\s+(?:corner\s+)?{_NUMBER}\s*mm(?:\s+(?:diameter|dia))?(?:\s+corner)?\s+holes?",
        rf"(?:four|4)\s+(?:corner\s+)?holes?\s*(?:of|at|with)?\s*{_NUMBER}\s*mm",
        rf"holes?\s*(?:of|at|with)?\s*{_NUMBER}\s*mm\s*(?:diameter|dia)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def interpret_design_prompt(raw_prompt: str) -> dict[str, Any]:
    prompt = " ".join(raw_prompt.strip().split())
    if not prompt:
        return {
            "status": "needs_input",
            "kind": None,
            "missing_fields": ["shape", "dimensions"],
            "message": "Describe a plate, L bracket, or open enclosure with millimetre dimensions.",
            "prefill": {},
        }
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"Description must be {MAX_PROMPT_CHARS} characters or fewer")
    text = prompt.lower().replace("–", "-").replace("—", "-")
    if re.search(r"\b(inches?|inch|in\.|centimet(?:er|re)s?|cm)\b", text):
        return {
            "status": "needs_input",
            "kind": _kind(text),
            "missing_fields": ["millimetre_dimensions"],
            "message": "This release accepts millimetres only. Convert the dimensions to mm and try again.",
            "prefill": {},
        }

    kind = _kind(text)
    if kind is None:
        return {
            "status": "needs_input",
            "kind": None,
            "missing_fields": ["shape"],
            "message": "Choose a supported starting shape: plate, L bracket, or open enclosure.",
            "prefill": {},
        }

    sequence = _dimension_sequence(text)
    width = _number_after(text, ("width", "wide"))
    depth = _number_after(text, ("depth", "deep", "length", "long"))
    height = _number_after(text, ("height", "high"))
    thickness = _number_after(text, ("thickness", "thick"))
    wall = _number_after(text, ("wall thickness", "wall", "walls"))

    if width is None and sequence:
        width = sequence[0]
    if depth is None and len(sequence) >= 2:
        depth = sequence[1]
    if kind == "plate":
        if thickness is None and len(sequence) >= 3:
            thickness = sequence[2]
    else:
        if height is None and len(sequence) >= 3:
            height = sequence[2]
        if kind == "bracket" and thickness is None and len(sequence) >= 4:
            thickness = sequence[3]
        if kind == "enclosure" and wall is None and len(sequence) >= 4:
            wall = sequence[3]

    prefill: dict[str, Any] = {
        key: value
        for key, value in {
            "width_mm": width,
            "depth_mm": depth,
            "height_mm": height,
            "thickness_mm": thickness,
            "wall_thickness_mm": wall,
        }.items()
        if value is not None
    }
    required = {
        "plate": ("width_mm", "depth_mm", "thickness_mm"),
        "bracket": ("width_mm", "depth_mm", "height_mm", "thickness_mm"),
        "enclosure": ("width_mm", "depth_mm", "height_mm", "wall_thickness_mm"),
    }[kind]
    missing = [field for field in required if field not in prefill]

    hole_diameter = _hole_diameter(text) if kind == "plate" else None
    mentions_holes = kind == "plate" and "hole" in text and "no holes" not in text
    if mentions_holes and hole_diameter is None:
        missing.append("hole_diameter_mm")
    if missing:
        return {
            "status": "needs_input",
            "kind": kind,
            "missing_fields": missing,
            "message": "I found the shape, but need: "
            + ", ".join(field.replace("_mm", "").replace("_", " ") for field in missing)
            + ".",
            "prefill": prefill,
        }

    assumptions = ["All extracted dimensions are millimetres; review them before generation."]
    if kind == "plate":
        plate_width = cast(float, width)
        plate_depth = cast(float, depth)
        plate_thickness = cast(float, thickness)
        holes: list[dict[str, float]] = []
        if hole_diameter is not None:
            inset = max(
                hole_diameter / 2.0 + 3.0,
                min(plate_width, plate_depth) * 0.12,
            )
            x = plate_width / 2.0 - inset
            y = plate_depth / 2.0 - inset
            holes = [
                {"x_mm": -x, "y_mm": -y, "diameter_mm": hole_diameter},
                {"x_mm": x, "y_mm": -y, "diameter_mm": hole_diameter},
                {"x_mm": x, "y_mm": y, "diameter_mm": hole_diameter},
                {"x_mm": -x, "y_mm": y, "diameter_mm": hole_diameter},
            ]
            assumptions.append(
                f"Four corner holes use a {inset:.2f} mm edge inset; adjust if needed."
            )
        plan_value = {
            "kind": "plate",
            "width_mm": plate_width,
            "depth_mm": plate_depth,
            "thickness_mm": plate_thickness,
            "holes": holes,
        }
        name = f"Plate {plate_width:g} × {plate_depth:g} × {plate_thickness:g} mm"
    elif kind == "bracket":
        bracket_width = cast(float, width)
        bracket_depth = cast(float, depth)
        bracket_height = cast(float, height)
        bracket_thickness = cast(float, thickness)
        plan_value = {
            "kind": "bracket",
            "width_mm": bracket_width,
            "depth_mm": bracket_depth,
            "height_mm": bracket_height,
            "thickness_mm": bracket_thickness,
        }
        name = f"L bracket {bracket_width:g} × {bracket_depth:g} × {bracket_height:g} mm"
    else:
        enclosure_width = cast(float, width)
        enclosure_depth = cast(float, depth)
        enclosure_height = cast(float, height)
        enclosure_wall = cast(float, wall)
        plan_value = {
            "kind": "enclosure",
            "width_mm": enclosure_width,
            "depth_mm": enclosure_depth,
            "height_mm": enclosure_height,
            "wall_thickness_mm": enclosure_wall,
        }
        name = (
            f"Open enclosure {enclosure_width:g} × {enclosure_depth:g} × "
            f"{enclosure_height:g} mm"
        )

    try:
        plan = validate_design_plan(plan_value)
    except ValidationError as exc:
        return {
            "status": "needs_input",
            "kind": kind,
            "missing_fields": [],
            "message": f"Those dimensions do not form a safe {kind}: {exc.errors()[0]['msg'] if hasattr(exc, 'errors') else 'review the dimensions'}.",
            "prefill": prefill,
        }
    return {
        "status": "ready",
        "kind": kind,
        "name": name,
        "plan": plan.model_dump(mode="json"),
        "assumptions": assumptions,
        "message": "Safe dimensions extracted. Review the fields, then generate.",
    }
