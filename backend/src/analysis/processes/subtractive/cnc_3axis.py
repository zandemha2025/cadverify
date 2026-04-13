"""CNC 3-Axis Milling."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_build_volume,
    check_fixture_surfaces,
    check_hole_depth_ratio,
    check_internal_radii,
    check_undercuts_from_z,
    check_wall_thickness,
)


@register
class CNC3AxisAnalyzer:
    process = ProcessType.CNC_3AXIS
    standards = [
        "Sandvik Coromant Machining Guide (2024)",
        "ASME Y14.5-2018 — GD&T",
        "Haas VF-2 specifications",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_undercuts_from_z(ctx, self.process,
                 cite="3-axis: tool access from +Z only."))
        i.extend(check_internal_radii(ctx, 0.5, self.process,
                 cite="Sandvik: smallest end mill 1mm Ø → 0.5mm radius."))
        i.extend(check_wall_thickness(ctx, 0.8, self.process,
                 cite="Thin walls vibrate; 0.8mm min metals."))
        i.extend(check_hole_depth_ratio(ctx, 10.0, self.process))
        i.extend(check_build_volume(ctx, (762, 406, 508), self.process,
                 cite="Haas VF-2 (30x16x20 in)."))
        i.extend(check_fixture_surfaces(ctx, 15.0, self.process))
        return i
