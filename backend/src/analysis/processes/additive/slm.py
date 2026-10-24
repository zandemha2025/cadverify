"""SLM — Selective Laser Melting (metal PBF, full melt)."""

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
class SLMAnalyzer:
    process = ProcessType.SLM
    standards = [
        "SLM Solutions SLM 500 specifications",
        "AMS 7003 — Laser PBF of metals",
        "ASTM F3301 — PBF Ti-6Al-4V",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 0.4, self.process,
                 cite="SLM Solutions: 0.4mm min for Ti/Inconel."))
        i.extend(check_overhangs(ctx, 45.0, self.process,
                 cite="SLM 45° support threshold."))
        i.extend(check_small_features(ctx, 0.15, self.process,
                 cite="SLM 500: ~90µm beam, 150µm feature."))
        i.extend(check_build_volume(ctx, (500, 280, 365), self.process,
                 cite="SLM 500."))
        i.extend(check_trapped_volumes(ctx, self.process, min_drain_mm=5.0))
        i.extend(check_residual_stress(ctx, self.process,
                 cite="Stress relief required per AMS 7003."))
        return i
