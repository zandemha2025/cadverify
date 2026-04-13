"""FDM / FFF — Fused Deposition Modeling."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_aspect_ratio,
    check_build_volume,
    check_overhangs,
    check_small_features,
    check_trapped_volumes,
    check_wall_thickness,
)


@register
class FDMAnalyzer:
    process = ProcessType.FDM
    standards = [
        "ISO/ASTM 52910:2018 — AM design guidelines",
        "Stratasys FDM Design Guide v2.0",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 0.8, self.process,
                 cite="2x nozzle diameter (0.4mm). Stratasys DFM §3."))
        i.extend(check_overhangs(ctx, 45.0, self.process,
                 cite="ISO/ASTM 52910:2018 §5.3."))
        i.extend(check_small_features(ctx, 0.4, self.process,
                 cite="Nozzle diameter. Stratasys DFM §3.2."))
        i.extend(check_build_volume(ctx, (300, 300, 350), self.process,
                 cite="Bambu Lab X1C / Prusa MK4."))
        i.extend(check_aspect_ratio(ctx, 8.0, self.process))
        i.extend(check_trapped_volumes(ctx, self.process, min_drain_mm=3.0))
        return i
