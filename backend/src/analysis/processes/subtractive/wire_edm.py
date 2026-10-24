"""Wire EDM — Electrical Discharge Machining."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.profiles.envelopes import common_envelope
from src.analysis.processes.checks import (
    check_build_volume,
    check_prismatic,
    check_sealed_voids,
    check_small_features,
    check_wire_reach,
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
        # A sealed void already rules the wire out; the blind-face proof would repeat it.
        i.extend(check_sealed_voids(ctx, self.process) or check_wire_reach(ctx, self.process))
        i.extend(check_prismatic(ctx, self.process,
                 cite="Sodick ALC600G specifications (taper and multi-axis options)."))
        i.extend(check_small_features(ctx, 0.125, self.process,
                 cite="0.25mm wire → 0.125mm min internal radius."))
        i.extend(check_build_volume(ctx, common_envelope(self.process), self.process,
                 cite="Common size; e.g. Sodick ALC600G."))
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
