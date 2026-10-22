"""FDM / FFF — Fused Deposition Modeling."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_aspect_ratio,
    check_build_volume,
    check_overhangs,
    check_sealed_voids_fdm,
    check_small_features,
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
        # The wall floor follows the nozzle: a standard 0.4 mm nozzle lays a
        # 0.6 mm wall reliably; below two of its perimeters (0.8 mm) the wall
        # prints but is weak. A printer's own nozzle is checked against the
        # thinnest wall in machine fit (makeability, nozzle_dia_mm).
        i.extend(check_wall_thickness(ctx, 0.6, self.process,
                 cite="1.5x a standard 0.4mm nozzle, its thinnest reliable wall. Stratasys DFM §3.",
                 warn_below_mm=0.8,
                 warn_note="A 0.4mm nozzle prints it as one or two perimeters: check strength."))
        # Flat spans between walls print as bridges (PrusaSlicer's default).
        i.extend(check_overhangs(ctx, 45.0, self.process,
                 cite="ISO/ASTM 52910:2018 §5.3.", bridges=True))
        i.extend(check_small_features(ctx, 0.4, self.process,
                 cite="Nozzle diameter. Stratasys DFM §3.2."))
        i.extend(check_build_volume(ctx, (300, 300, 350), self.process,
                 cite="Bambu Lab X1C / Prusa MK4."))
        i.extend(check_aspect_ratio(ctx, 8.0, self.process))
        # Extrusion leaves a sealed void empty: no loose powder or resin to drain.
        i.extend(check_sealed_voids_fdm(ctx, self.process, max_overhang_deg=45.0))
        return i
