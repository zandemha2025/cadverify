"""DED — Directed Energy Deposition (laser / wire feed)."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_build_volume,
    check_overhangs,
    check_wall_thickness,
)


@register
class DEDAnalyzer:
    process = ProcessType.DED
    standards = [
        "ASTM F3187 — DED process specification",
        "NIST AM Bench — DED parameter guidelines",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 1.5, self.process,
                 cite="DED bead width ~2-4mm; 1.5mm min wall."))
        i.extend(check_overhangs(ctx, 60.0, self.process,
                 cite="Multi-axis DED: 60° threshold."))
        i.extend(check_build_volume(ctx, (1500, 1500, 1500), self.process,
                 cite="Large-format DED systems."))
        i.extend(self._check_machining_allowance(ctx))
        return i

    def _check_machining_allowance(self, ctx: GeometryContext) -> list[Issue]:
        """DED always requires post-machining for final tolerance."""
        return [Issue(
            code="MACHINING_ALLOWANCE",
            severity=Severity.INFO,
            message=(
                "DED produces near-net shapes (Ra 15-40µm). "
                "Add 2-5mm machining stock on all critical surfaces."
            ),
            process=self.process,
            fix_suggestion=(
                "Design with 2-5mm extra material on tolerance surfaces. "
                "Plan hybrid DED + CNC workflow. ASTM F3187 §7."
            ),
        )]
