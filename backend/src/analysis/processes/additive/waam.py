"""WAAM — Wire Arc Additive Manufacturing (large-format)."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_build_volume,
    check_overhangs,
    check_wall_thickness,
)


@register
class WAAMAnalyzer:
    process = ProcessType.WAAM
    standards = [
        "AWS D1.1 — Structural Welding Code",
        "Lincoln Electric WAAM guidelines",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 2.0, self.process,
                 cite="WAAM bead width 4-8mm; 2mm min wall."))
        i.extend(check_overhangs(ctx, 60.0, self.process,
                 cite="Multi-axis WAAM: 60° practical limit."))
        i.extend(check_build_volume(ctx, (5000, 3000, 3000), self.process,
                 cite="Large-format WAAM — up to 5m."))
        i.append(Issue(
            code="MACHINING_ALLOWANCE",
            severity=Severity.INFO,
            message=(
                "WAAM is near-net; all surfaces need 3-5mm post-machining "
                "stock. Plan hybrid WAAM + CNC."
            ),
            process=self.process,
            fix_suggestion="Add 3-5mm stock on tolerance surfaces.",
        ))
        return i
