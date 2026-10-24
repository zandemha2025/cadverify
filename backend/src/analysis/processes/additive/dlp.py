"""DLP — Digital Light Processing (vat photopolymerization)."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_build_volume,
    check_overhangs,
    check_small_features,
    check_trapped_volumes,
    check_wall_thickness,
)


@register
class DLPAnalyzer:
    process = ProcessType.DLP
    standards = [
        "Carbon DLS Design Guide (2024)",
        "Elegoo Saturn 4 Ultra specifications",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 0.3, self.process,
                 cite="Carbon M2: 0.3mm min."))
        i.extend(check_overhangs(ctx, 30.0, self.process,
                 cite="DLP typically 30° from vertical."))
        i.extend(check_small_features(ctx, 0.05, self.process,
                 cite="19µm pixel on Elegoo Saturn 4 Ultra."))
        i.extend(check_build_volume(ctx, (218, 123, 250), self.process,
                 cite="Elegoo Saturn 4 Ultra."))
        i.extend(check_trapped_volumes(ctx, self.process, min_drain_mm=3.5))
        return i
