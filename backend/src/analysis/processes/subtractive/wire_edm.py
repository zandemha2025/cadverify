"""Wire EDM — Electrical Discharge Machining."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_build_volume,
    check_prismatic,
    check_small_features,
)


@register
class WireEDMAnalyzer:
    process = ProcessType.WIRE_EDM
    standards = [
        "Sodick ALC600G specifications",
        "Mitsubishi Electric wire EDM design guide",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_prismatic(ctx, self.process,
                 cite="Wire EDM cuts a 2D profile extruded in Z."))
        i.extend(check_small_features(ctx, 0.125, self.process,
                 cite="0.25mm wire → 0.125mm min internal radius."))
        i.extend(check_build_volume(ctx, (600, 400, 350), self.process,
                 cite="Sodick ALC600G."))
        i.extend(self._check_conductivity_hint(ctx))
        return i

    def _check_conductivity_hint(self, ctx: GeometryContext) -> list[Issue]:
        return [Issue(
            code="CONDUCTIVITY_REQUIRED",
            severity=Severity.INFO,
            message="Wire EDM requires electrically conductive material.",
            process=self.process,
            fix_suggestion="Verify material is conductive (metals only). Ceramics / polymers cannot be wire-EDM'd.",
        )]
