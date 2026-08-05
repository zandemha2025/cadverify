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

    @model_validator(mode="after")
    def holes_fit_inside_plate(self) -> "PlatePlan":
        for hole in self.holes:
            radius = hole.diameter_mm / 2.0
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
                ) / 2.0 + 0.5
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

    @model_validator(mode="after")
    def walls_fit_enclosure(self) -> "EnclosurePlan":
        wall = self.wall_thickness_mm
        if wall * 4.0 >= min(self.width_mm, self.depth_mm):
            raise ValueError("wall thickness leaves no usable enclosure interior")
        if wall * 2.0 >= self.height_mm:
            raise ValueError("wall thickness must be less than half the enclosure height")
        return self


DesignPlan = Annotated[
    Union[PlatePlan, BracketPlan, EnclosurePlan],
    Field(discriminator="kind"),
]

_ADAPTER = TypeAdapter(DesignPlan)


def validate_design_plan(value: object) -> DesignPlan:
    """Validate an untrusted request, database value, or future AI response."""
    return _ADAPTER.validate_python(value)
