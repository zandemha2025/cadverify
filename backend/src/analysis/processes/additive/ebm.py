"""EBM — Electron Beam Melting (metal PBF, vacuum)."""

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
class EBMAnalyzer:
    process = ProcessType.EBM
    standards = [
        "Arcam Q20plus specifications (GE Additive)",
        "ASTM F3001 — EBM Ti-6Al-4V",
        "ISO 5832-3 — Ti surgical implants",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 0.7, self.process,
                 cite="Arcam: 0.7mm min — larger melt pool than SLM."))
        i.extend(check_overhangs(ctx, 50.0, self.process,
                 cite="Arcam: 50° threshold (pre-heat reduces curl)."))
        i.extend(check_small_features(ctx, 0.3, self.process,
                 cite="Arcam Q20: ~200µm beam, 300µm feature."))
        i.extend(check_build_volume(ctx, (350, 380, 380), self.process,
                 cite="Arcam Q20plus."))
        i.extend(check_trapped_volumes(ctx, self.process, min_drain_mm=5.0))
        return i
