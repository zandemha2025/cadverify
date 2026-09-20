"""SLA — Stereolithography (vat photopolymerization)."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_build_volume,
    check_overhangs,
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
        i.extend(check_overhangs(
            ctx,
            19.0,
            self.process,
            min_angle_from_horizontal_deg=19.0,
            cite="Formlabs: 19° from horizontal without support.",
        ))
        i.extend(check_small_features(ctx, 0.05, self.process,
                 cite="25µm XY resolution on Form 4."))
        i.extend(check_build_volume(ctx, (200, 125, 210), self.process,
                 cite="Formlabs Form 4."))
        i.extend(check_trapped_volumes(ctx, self.process, min_drain_mm=3.5,
                 cite="Formlabs: 3.5mm drain holes for hollowed parts."))
        i.extend(self._check_cupping(ctx))
        return i

    def _check_cupping(self, ctx: GeometryContext) -> list[Issue]:
        """Concave downward-facing pockets trap resin during peel (suction cup)."""
        down_mask = ctx.normals[:, 2] < -0.8  # nearly downward

        # A flat exterior base is not a suction cup. Require the downward
        # region to touch at least one concave adjacency edge, which is direct
        # mesh evidence of a pocket/cavity boundary. This keeps sealed concave
        # ceilings detectable while rejecting solid cubes and compliant
        # open/drained cups whose only downward area is an exterior floor.
        pocket_faces = np.zeros(len(ctx.normals), dtype=bool)
        if len(ctx.face_adjacency) == len(ctx.concave_mask):
            concave_pairs = ctx.face_adjacency[ctx.concave_mask]
            if len(concave_pairs):
                pocket_faces[np.unique(concave_pairs)] = True
        down_faces = np.where(down_mask & pocket_faces)[0]
        if len(down_faces) == 0:
            return []
        down_area = float(ctx.face_areas[down_faces].sum())
        total = float(ctx.info.surface_area) or 1.0
        if down_area / total < 0.10:
            return []
        return [Issue(
            code="CUPPING_RISK",
            severity=Severity.WARNING,
            message=(
                f"Large downward-facing area ({down_area:.0f}mm², "
                f"{down_area / total * 100:.0f}%) — resin cupping / suction risk during peel."
            ),
            process=self.process,
            fix_suggestion="Add drain holes, tilt part 10-15°, or orient concave side up.",
        )]
