"""Binder Jetting — binder + powder, sintered post-process."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_build_volume,
    check_small_features,
    check_wall_thickness,
)


@register
class BinderJettingAnalyzer:
    process = ProcessType.BINDER_JET
    standards = [
        "ExOne S-Max Pro specifications",
        "Desktop Metal Shop System Design Guide",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 1.0, self.process,
                 cite="Green part: 1mm min wall; 0.8mm post-sinter."))
        # Self-supporting — no overhang check.
        i.extend(check_small_features(ctx, 0.5, self.process,
                 cite="Desktop Metal: 0.5mm min feature."))
        i.extend(check_build_volume(ctx, (800, 500, 400), self.process,
                 cite="ExOne S-Max Pro."))
        i.extend(self._check_sintering_shrinkage(ctx))
        return i

    def _check_sintering_shrinkage(self, ctx: GeometryContext) -> list[Issue]:
        """All binder jet parts shrink ~15-20% during sintering."""
        return [Issue(
            code="SINTERING_SHRINKAGE",
            severity=Severity.INFO,
            message=(
                "Binder jetting parts shrink 15-20% during sintering. "
                "Ensure CAD model is scaled to compensate."
            ),
            process=self.process,
            fix_suggestion=(
                "Scale model 1.18–1.22x to compensate for sintering shrinkage. "
                "Desktop Metal Studio pre-compensates automatically."
            ),
        )]
