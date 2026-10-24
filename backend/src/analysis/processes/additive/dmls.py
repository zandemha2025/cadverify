"""DMLS — Direct Metal Laser Sintering (metal PBF)."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_build_volume,
    check_overhangs,
    check_residual_stress,
    check_small_features,
    check_trapped_volumes,
    check_wall_thickness,
)


@register
class DMLSAnalyzer:
    process = ProcessType.DMLS
    standards = [
        "EOS M 400-4 specifications",
        "AMS 7003 — Laser PBF of metals",
        "Boeing BAC5673 — AM Ti-6Al-4V",
        "ASTM F3301 — PBF Ti-6Al-4V",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 0.4, self.process,
                 cite="EOS Ti/Inconel data sheets: 0.4mm min."))
        i.extend(check_overhangs(ctx, 45.0, self.process,
                 cite="EOS DMLS best practice: 45° support threshold."))
        i.extend(check_small_features(ctx, 0.15, self.process,
                 cite="EOS M 400-4: 40µm layer, ~150µm feature."))
        i.extend(check_build_volume(ctx, (400, 400, 400), self.process,
                 cite="EOS M 400-4."))
        i.extend(check_trapped_volumes(ctx, self.process, min_drain_mm=5.0,
                 cite="Metal powder: 5mm+ drain holes."))
        i.extend(check_residual_stress(ctx, self.process,
                 cite="AMS 7003: HIP/stress-relief mandatory for Ti."))
        return i
