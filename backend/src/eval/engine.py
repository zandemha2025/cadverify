"""Canonical engine-routing wrapper (spec §1.1).

The **only** sanctioned way the eval obtains the engine's routing pick. Replicates
``validate_demo`` in ``backend/src/api/routes.py`` verbatim, including the two
load-bearing gotchas:

1. ``rank_processes()`` only *sorts* ``process_scores``; it leaves
   ``result.best_process = None``. The caller must set
   ``best_process = ranked[0].process`` when ``ranked[0].score > 0`` else ``None``.
2. ``analyze_geometry`` sets ``volume = 0.0`` when the mesh is not watertight.

``geometry_pass`` exposes the cheap half (geometry + context + features) used by
both routing and the similarity feature vector, so a part is analyzed once.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np
import trimesh

# Import for side effect: populates the @register analyzer registry.
import src.analysis.processes  # noqa: F401
from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.features.base import Feature
from src.analysis.models import AnalysisResult, GeometryInfo, ProcessScore, ProcessType
from src.analysis.processes import base as pbase
from src.analysis.processes.base import get_analyzer
from src.eval.ontology import family_of
from src.matcher.profile_matcher import rank_processes, score_process


@dataclass
class GeometryPass:
    """The cheap, shared analysis half (no per-process scoring)."""

    mesh: trimesh.Trimesh
    geometry: GeometryInfo
    ctx: GeometryContext
    features: list[Feature]


@dataclass
class Routing:
    """The engine's routing decision for one part."""

    filename: str
    geometry: GeometryInfo
    ctx: GeometryContext
    features: list[Feature]
    result: AnalysisResult
    ranked: list[ProcessScore]
    best_process: Optional[ProcessType]
    engine_family: str  # family_of(best_process); "no_route" when best_process is None
    top3: list[tuple[str, float]]  # [(process_value, score), ...] highest first


def geometry_pass(mesh: trimesh.Trimesh) -> GeometryPass:
    """Run analyze_geometry -> GeometryContext.build -> detect_features once.

    This is the shared front half of the canonical sequence. Degenerate-mesh
    numpy warnings (divide-by-zero in normal matmuls) are suppressed: the engine
    already degrades safely on bad meshes and we don't want noise in the report.
    """
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        geometry = analyze_geometry(mesh)
        ctx = GeometryContext.build(mesh, geometry)
        # ctx.mesh == mesh unless build() decimated an oversize mesh; detect on
        # ctx.mesh so feature indices align with the context per-face arrays.
        features = detect_features(ctx.mesh)
        ctx.features = features
    return GeometryPass(mesh=mesh, geometry=geometry, ctx=ctx, features=features)


def route_mesh(mesh: trimesh.Trimesh, filename: str = "part.stl") -> Routing:
    """Run the full canonical routing sequence and return the engine's pick.

    Mirrors ``validate_demo``: scores every registered analyzer, ranks, then sets
    ``best_process`` only when the top score is > 0 (else ``None`` == no route).
    """
    gp = geometry_pass(mesh)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        universal = run_universal_checks(mesh)
        scores: list[ProcessScore] = []
        for proc in pbase._REGISTRY:
            analyzer = get_analyzer(proc)
            if analyzer is None:
                continue
            try:
                issues = analyzer.analyze(gp.ctx)
            except Exception:  # pragma: no cover - defensive, mirrors routes.py
                continue
            scores.append(score_process(issues, gp.geometry, proc))

    result = AnalysisResult(
        filename=filename,
        file_type="stl",
        geometry=gp.geometry,
        segments=gp.ctx.segments,
        universal_issues=universal,
        process_scores=scores,
    )
    ranked = rank_processes(result)
    # CRITICAL (spec §1.1): rank_processes only sorts; it does NOT set best_process.
    best = ranked[0].process if ranked and ranked[0].score > 0 else None
    result.best_process = best

    top3 = [(ps.process.value, ps.score) for ps in ranked[:3]]
    return Routing(
        filename=filename,
        geometry=gp.geometry,
        ctx=gp.ctx,
        features=gp.features,
        result=result,
        ranked=ranked,
        best_process=best,
        engine_family=family_of(best),
        top3=top3,
    )
