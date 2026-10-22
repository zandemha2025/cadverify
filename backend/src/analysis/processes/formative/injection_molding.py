"""Injection Molding — the money maker."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.serialization import format_measurement
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_draft_angles,
    check_undercuts_molding,
    check_wall_uniformity,
)
from src.analysis.features.base import FeatureKind


@register
class InjectionMoldingAnalyzer:
    process = ProcessType.INJECTION_MOLDING
    standards = [
        "Protolabs Injection Molding Design Guide (2024)",
        "DFMPro — IM rules engine",
        "GE Plastics Design Guide — wall thickness",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_draft_angles(ctx, 1.0, self.process,
                 cite="Protolabs: 1° min external, 2° internal."))
        i.extend(check_wall_uniformity(ctx, 0.5, 6.0, 2.5, self.process,
                 cite="GE Plastics: 0.5–6mm, ideal 2.5mm for ABS."))
        i.extend(check_undercuts_molding(ctx, self.process,
                 cite="Side actions add $5–15K tooling."))
        i.extend(self._check_rib_rules(ctx))
        i.extend(self._check_boss_rules(ctx))
        return i

    def _check_rib_rules(self, ctx: GeometryContext) -> list[Issue]:
        """Ribs: thickness <= 0.6x the wall they stand on, height <= 3x that wall.

        Only for ribs the geometry shows (``ctx.ribs``), with their measured
        sizes; a part without ribs gets no rib guidance.
        """
        issues: list[Issue] = []
        for rib in ctx.ribs:
            base = rib["base_thickness_mm"]
            if base is None or base <= 0:
                continue
            thick = rib["thickness_mm"] / base
            tall = rib["height_mm"] / base
            if thick <= 0.6 and tall <= 3.0:
                continue
            where = ", ".join(f"{c:.0f}" for c in rib["center"])
            problems = []
            if thick > 0.6:
                problems.append(f"{format_measurement(rib['thickness_mm'])}mm thick ({thick:.2f}x the wall; guide <= 0.6x)")
            if tall > 3.0:
                problems.append(f"{format_measurement(rib['height_mm'])}mm tall ({tall:.1f}x the wall; guide <= 3x)")
            issues.append(Issue(
                code="RIB_RULES_CHECK",
                severity=Severity.INFO,
                message=(
                    f"Rib at ({where}) on a {format_measurement(base)}mm wall is " + " and ".join(problems) + "."
                ),
                process=self.process,
                region_center=rib["center"],
                fix_suggestion="Thin the rib to <= 0.6x the wall (sink marks) and keep it <= 3x the wall tall. Protolabs IM guide §4.3.",
            ))
            break
        return issues

    def _check_boss_rules(self, ctx: GeometryContext) -> list[Issue]:
        bosses = [f for f in ctx.features if f.kind == FeatureKind.CYLINDER_BOSS]
        if not bosses:
            return []
        issues: list[Issue] = []
        for b in bosses:
            if b.radius and b.radius < 1.5:
                issues.append(Issue(
                    code="THIN_BOSS",
                    measurement_unit="mm",
                    severity=Severity.WARNING,
                    measured_value=b.radius * 2,
                    message=(
                        f"Boss at ({b.centroid[0]:.0f}, {b.centroid[1]:.0f}, "
                        f"{b.centroid[2]:.0f}) has {b.radius * 2:.1f}mm OD — "
                        "wall may be too thin for molding."
                    ),
                    process=self.process,
                    region_center=b.centroid,
                    fix_suggestion="Boss OD should be >= 2x ID. Add gussets.",
                ))
        return issues
