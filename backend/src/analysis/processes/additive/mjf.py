"""MJF — Multi Jet Fusion (HP)."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_aspect_ratio,
    check_build_volume,
    check_small_features,
    check_trapped_volumes,
    check_wall_thickness,
)


@register
class MJFAnalyzer:
    process = ProcessType.MJF
    standards = [
        "HP MJF Design Guide v5.0 (2024)",
        "HP Jet Fusion 5200 specifications",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 0.5, self.process,
                 cite="HP MJF DG §3.1: 0.5mm min wall for PA12."))
        # MJF is self-supporting — no overhang check.
        i.extend(check_small_features(ctx, 0.2, self.process,
                 cite="HP MJF DG §3.2: 0.2mm min feature."))
        i.extend(check_build_volume(ctx, (380, 284, 380), self.process,
                 cite="HP Jet Fusion 5200."))
        i.extend(check_aspect_ratio(ctx, 10.0, self.process))
        i.extend(check_trapped_volumes(ctx, self.process, min_drain_mm=5.0,
                 cite="HP MJF DG §4.2: 5mm escape holes."))
        return i
