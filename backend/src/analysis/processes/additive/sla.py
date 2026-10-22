"""SLA — Stereolithography (vat photopolymerization)."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_build_volume,
    check_overhangs,
    cup_faces,
    check_small_features,
    check_trapped_volumes,
    check_wall_thickness,
)

import numpy as np


@register
class SLAAnalyzer:
    process = ProcessType.SLA
    standards = [
        "Formlabs Design Guide — Orientation & Supports (2024)",
        "ISO/ASTM 52910:2018",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_wall_thickness(ctx, 0.4, self.process,
                 cite="Formlabs Form 4: 0.3mm min, 0.4mm recommended."))
        i.extend(check_overhangs(ctx, 19.0, self.process,
                 cite="Formlabs: 19° from horizontal without support."))
        i.extend(check_small_features(ctx, 0.05, self.process,
                 cite="25µm XY resolution on Form 4."))
        i.extend(check_build_volume(ctx, (200, 125, 210), self.process,
                 cite="Formlabs Form 4."))
        i.extend(check_trapped_volumes(ctx, self.process, min_drain_mm=3.5,
                 cite="Formlabs: 3.5mm drain holes for hollowed parts."))
        i.extend(self._check_cupping(ctx))
        return i

    def _check_cupping(self, ctx: GeometryContext) -> list[Issue]:
        """A cup open toward the tank holds resin against the film: suction on every peel.

        Only roofs of real cups count (``cup_faces``); the face a solid stands
        on is on the build plate, not a cup.
        """
        faces = cup_faces(ctx.mesh, normals=ctx.normals, centroids=ctx.centroids, bbox_diag=ctx.bbox_diag)
        if len(faces) == 0:
            return []
        cup_area = float(ctx.face_areas[faces].sum())
        total = float(ctx.info.surface_area) or 1.0
        max_share_pct = 10.0
        if cup_area / total < max_share_pct / 100:
            return []
        return [Issue(
            code="CUPPING_RISK",
            measurement_unit="percent",
            severity=Severity.WARNING,
            measured_value=cup_area / total * 100,
            required_value=max_share_pct,
            message=(
                f"A cavity opens toward the resin tank ({cup_area:.0f}mm² of roof, "
                f"{cup_area / total * 100:.0f}% of the surface): resin cupping / suction risk during peel."
            ),
            process=self.process,
            affected_faces=faces.tolist(),
            region_center=_center(ctx, faces),
            fix_suggestion="Turn the part so the cavity opens upward, tilt it 10-15°, or add a vent hole through the cup's roof.",
        )]


def _center(ctx: GeometryContext, faces: np.ndarray):
    c = ctx.centroids[faces[:50]].mean(axis=0)
    return (float(c[0]), float(c[1]), float(c[2]))
