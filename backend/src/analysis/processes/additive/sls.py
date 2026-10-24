"""SLS — Selective Laser Sintering (powder bed fusion, polymer)."""

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
class SLSAnalyzer:
    process = ProcessType.SLS
    standards = [
        "EOS PA12 material data sheet",
        "HP MJF Design Guide §4 (powder removal)",
        "ISO/ASTM 52910:2018",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 0.7, self.process,
                 cite="EOS PA12: 0.7mm min wall."))
        # SLS is self-supporting — no overhang check (threshold 90°).
        i.extend(check_small_features(ctx, 0.3, self.process,
                 cite="EOS P 396: 0.3mm min feature."))
        i.extend(check_build_volume(ctx, (340, 340, 600), self.process,
                 cite="EOS P 396."))
        i.extend(check_aspect_ratio(ctx, 10.0, self.process))
        i.extend(check_trapped_volumes(ctx, self.process, min_drain_mm=3.5,
                 cite="3.5mm escape holes for PA12 powder removal."))
        return i
