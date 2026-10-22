"""CNC 5-Axis Milling."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.profiles.envelopes import common_envelope
from src.analysis.processes.checks import (
    check_build_volume,
    check_fixture_surfaces,
    check_hole_depth_ratio,
    check_internal_radii,
    check_sealed_voids,
    check_setup_access,
    check_wall_thickness,
)


@register
class CNC5AxisAnalyzer:
    process = ProcessType.CNC_5AXIS
    standards = [
        "DMG MORI DMU 50 specifications",
        "Sandvik Coromant Machining Guide (2024)",
        "ASME Y14.5-2018",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_sealed_voids(ctx, self.process))
        i.extend(check_setup_access(ctx, self.process,
                 cite="Verify tool and holder clearance through the planned 5-axis motion."))
        i.extend(check_internal_radii(ctx, 0.5, self.process,
                 cite="Sandvik: 1mm end mill → 0.5mm radius min."))
        i.extend(check_wall_thickness(ctx, 0.8, self.process))
        i.extend(check_hole_depth_ratio(ctx, 15.0, self.process))
        i.extend(check_build_volume(ctx, common_envelope(self.process), self.process,
                 cite="Common size; e.g. a 500 mm-class 5-axis mill."))
        i.extend(check_fixture_surfaces(ctx, 10.0, self.process))
        return i
