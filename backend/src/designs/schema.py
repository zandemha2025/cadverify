"""Strict operation-plan contract for ProofShape Design Studio.

The plan is data, never source code. Every value is bounded before it reaches
OpenCASCADE, and ``extra='forbid'`` prevents an AI or client from smuggling an
unreviewed operation into the generator. Future conversational generation must
produce this same contract; it will never produce executable Python.
"""
from __future__ import annotations

import math
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class StrictPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# Templates whose side walls release along +Z and can take a draft angle.
DRAFT_TEMPLATES = frozenset({"plate", "enclosure"})
MAX_DRAFT_DEG = 10.0


def _draft_field():
    """Optional draft in degrees. 0 is today's straight-walled geometry and is
    left out of the stored plan, so saved designs keep their exact JSON."""
    return Field(
        default=0.0,
        ge=0.0,
        le=MAX_DRAFT_DEG,
        allow_inf_nan=False,
        exclude_if=lambda value: value == 0,
    )


def draft_run(height_mm: float, draft_angle_deg: float) -> float:
    """Horizontal lean of a side wall of ``height_mm`` drafted ``draft_angle_deg``."""
    return height_mm * math.tan(math.radians(draft_angle_deg))


class Hole(StrictPlan):
    """A through-hole whose centre is measured from the part centre in mm."""

    x_mm: float = Field(ge=-500.0, le=500.0)
    y_mm: float = Field(ge=-500.0, le=500.0)
    diameter_mm: float = Field(ge=1.0, le=100.0)


class PlatePlan(StrictPlan):
    kind: Literal["plate"]
    width_mm: float = Field(ge=10.0, le=1000.0)
    depth_mm: float = Field(ge=10.0, le=1000.0)
    thickness_mm: float = Field(ge=0.5, le=100.0)
    holes: list[Hole] = Field(default_factory=list, max_length=32)
    # Width, depth and hole diameters hold at the bottom face. With draft the
    # edges lean in and the holes open up toward the top face, so the part
    # releases upward (+Z) from a mold.
    draft_angle_deg: float = _draft_field()

    @model_validator(mode="after")
    def holes_fit_inside_plate(self) -> "PlatePlan":
        # At the top face each edge sits ``run`` further in and each hole is
        # ``run`` wider in radius, so edge margins and the gaps between holes
        # shrink by ``2 * run``; check them there, where they are smallest.
        run = draft_run(self.thickness_mm, self.draft_angle_deg)
        if run > 0 and 4.0 * run >= min(self.width_mm, self.depth_mm):
            raise ValueError(
                "draft would shrink the plate's top face below half its width or depth"
            )
        for hole in self.holes:
            radius = hole.diameter_mm / 2.0 + 2.0 * run
            # One millimetre of material around every hole is the minimum safe
            # boundary for this template. Manufacturing validation may demand
            # more for the selected process; this only guarantees valid geometry.
            if abs(hole.x_mm) + radius + 1.0 > self.width_mm / 2.0:
                raise ValueError("hole exceeds the plate width or edge margin")
            if abs(hole.y_mm) + radius + 1.0 > self.depth_mm / 2.0:
                raise ValueError("hole exceeds the plate depth or edge margin")
        for index, left in enumerate(self.holes):
            for right in self.holes[index + 1 :]:
                centre_distance = math.hypot(
                    left.x_mm - right.x_mm,
                    left.y_mm - right.y_mm,
                )
                minimum_distance = (
                    left.diameter_mm + right.diameter_mm
                ) / 2.0 + 2.0 * run + 0.5
                if centre_distance < minimum_distance:
                    raise ValueError(
                        "holes overlap or leave less than 0.5 mm between edges"
                    )
        return self


class BracketPlan(StrictPlan):
    kind: Literal["bracket"]
    width_mm: float = Field(ge=10.0, le=1000.0)
    depth_mm: float = Field(ge=10.0, le=1000.0)
    height_mm: float = Field(ge=10.0, le=1000.0)
    thickness_mm: float = Field(ge=0.5, le=100.0)

    @model_validator(mode="after")
    def wall_fits_bracket(self) -> "BracketPlan":
        if self.thickness_mm * 2.0 >= min(self.width_mm, self.height_mm):
            raise ValueError("bracket thickness must be less than half its width and height")
        return self


class EnclosurePlan(StrictPlan):
    kind: Literal["enclosure"]
    width_mm: float = Field(ge=20.0, le=1000.0)
    depth_mm: float = Field(ge=20.0, le=1000.0)
    height_mm: float = Field(ge=10.0, le=1000.0)
    wall_thickness_mm: float = Field(ge=0.5, le=50.0)
    # Width and depth hold at the open rim. With draft the four walls lean in
    # toward the base, inside and out, so the wall stays wall_thickness_mm
    # thick (measured square to the wall) and the part releases along +Z.
    draft_angle_deg: float = _draft_field()

    @model_validator(mode="after")
    def walls_fit_enclosure(self) -> "EnclosurePlan":
        wall = self.wall_thickness_mm
        if wall * 4.0 >= min(self.width_mm, self.depth_mm):
            raise ValueError("wall thickness leaves no usable enclosure interior")
        if wall * 2.0 >= self.height_mm:
            raise ValueError("wall thickness must be less than half the enclosure height")
        if self.draft_angle_deg > 0:
            # The inside is narrowest on the floor; keep it wider than two walls,
            # the same rule as the straight enclosure above.
            floor = min(self.width_mm, self.depth_mm) - 2.0 * (
                draft_run(self.height_mm - wall, self.draft_angle_deg)
                + wall / math.cos(math.radians(self.draft_angle_deg))
            )
            if floor <= 2.0 * wall:
                raise ValueError("draft and wall thickness leave no usable interior at the base")
        return self


DesignPlan = Annotated[
    Union[PlatePlan, BracketPlan, EnclosurePlan],
    Field(discriminator="kind"),
]

_ADAPTER = TypeAdapter(DesignPlan)


def validate_design_plan(value: object) -> DesignPlan:
    """Validate an untrusted request, database value, or future AI response."""
    return _ADAPTER.validate_python(value)
