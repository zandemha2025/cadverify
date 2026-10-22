"""Score manufacturing processes against geometry analysis results."""

from __future__ import annotations

from src.analysis.models import (
    AnalysisResult,
    FeatureSegment,
    GeometryInfo,
    Issue,
    ProcessScore,
    ProcessType,
    Severity,
)
from typing import Optional

from src.profiles.database import (
    get_materials_for_process,
    get_machines_for_process,
    processes_for_material_class,
)


def is_measurement_caveat(issue: Issue) -> bool:
    """A note on how precisely this file lets ScaleCAD measure (binary STL
    coordinate rounding, a STEP tessellation), not a problem with the part.

    The same part as STL and as STEP gets different caveats, so they must not
    move a score or the geometry pick (M13: the pick flipped between formats
    on nine parts because an STL-only caveat cost one process 0.1)."""
    return issue.code.endswith("_PRECISION")


def _design_warnings(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == Severity.WARNING and not is_measurement_caveat(i)]


def score_process(
    issues: list[Issue],
    geometry: GeometryInfo,
    process: ProcessType,
) -> ProcessScore:
    """Score how suitable a process is based on analysis issues.

    Errors fail the process; each design warning costs 0.1. Measurement
    caveats (``is_measurement_caveat``) still show, and still make the verdict
    "issues", but cost nothing."""
    errors = [i for i in issues if i.severity == Severity.ERROR]
    warnings = [i for i in issues if i.severity == Severity.WARNING]
    design_warnings = _design_warnings(issues)

    if errors:
        score = 0.0
        verdict = "fail"
    elif warnings:
        # Deduct 0.1 per design warning, minimum 0.3
        score = max(0.3, 1.0 - len(design_warnings) * 0.1)
        verdict = "issues"
    else:
        score = 1.0
        verdict = "pass"

    # Boost score for processes that are a natural fit
    score = _apply_geometry_affinity(score, geometry, process)

    # Find best material and machine
    materials = get_materials_for_process(process)
    machines = get_machines_for_process(process)

    best_material = materials[0].name if materials else None
    best_machine = machines[0].name if machines else None

    # Estimate relative cost factor
    cost_factor = _estimate_cost_factor(geometry, process)

    return ProcessScore(
        process=process,
        score=round(score, 2),
        verdict=verdict,
        issues=issues,
        recommended_material=best_material,
        recommended_machine=best_machine,
        estimated_cost_factor=cost_factor,
    )


def _apply_geometry_affinity(
    base_score: float,
    geometry: GeometryInfo,
    process: ProcessType,
) -> float:
    """Adjust score based on how well the geometry suits the process."""
    score = base_score
    dims = geometry.bounding_box.dimensions
    volume = geometry.volume
    max_dim = max(dims)

    # Small, detailed parts → boost SLA/DLP
    if max_dim < 100 and process in (ProcessType.SLA, ProcessType.DLP):
        score = min(1.0, score + 0.1)

    # Large parts → boost large-format processes
    if max_dim > 500:
        if process in (ProcessType.DED, ProcessType.WAAM, ProcessType.SAND_CASTING):
            score = min(1.0, score + 0.1)
        elif process in (ProcessType.SLA, ProcessType.DLP):
            score = max(0, score - 0.2)

    # High volume-to-SA ratio (bulky) → boost CNC (remove material is fine)
    if geometry.surface_area > 0:
        compactness = volume / geometry.surface_area
        if compactness > 10 and process in (ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS):
            score = min(1.0, score + 0.05)

    # No boost from the triangle count: the same part has 12 triangles as an
    # STL and tens of thousands once its STEP is tessellated, so a face-count
    # rule ranked CNC differently by file format, not by shape.
    return score


def _estimate_cost_factor(
    geometry: GeometryInfo,
    process: ProcessType,
) -> float:
    """Estimate relative cost factor (1.0 = baseline FDM PLA).

    This is a rough guide — real costs depend on material, machine time,
    post-processing, and quantity.
    """
    volume_cm3 = geometry.volume / 1000  # mm³ to cm³

    # Cost per cm³ multiplier (very approximate)
    cost_per_cm3 = {
        ProcessType.FDM: 0.05,
        ProcessType.SLA: 0.15,
        ProcessType.DLP: 0.12,
        ProcessType.SLS: 0.20,
        ProcessType.MJF: 0.18,
        ProcessType.DMLS: 2.0,
        ProcessType.SLM: 2.0,
        ProcessType.EBM: 2.5,
        ProcessType.BINDER_JET: 0.8,
        ProcessType.DED: 1.5,
        ProcessType.WAAM: 1.0,
        ProcessType.CNC_3AXIS: 0.10,
        ProcessType.CNC_5AXIS: 0.25,
        ProcessType.CNC_TURNING: 0.08,
        ProcessType.WIRE_EDM: 0.50,
        ProcessType.INJECTION_MOLDING: 0.02,  # Per part at volume
        ProcessType.DIE_CASTING: 0.03,
        ProcessType.INVESTMENT_CASTING: 0.30,
        ProcessType.SAND_CASTING: 0.05,
        ProcessType.SHEET_METAL: 0.03,
        ProcessType.FORGING: 0.04,
    }

    base_cost = cost_per_cm3.get(process, 0.1)
    return round(base_cost * max(volume_cm3, 1.0), 2)


_PROCESS_ORDER = {p: i for i, p in enumerate(ProcessType)}
_VERDICT_ORDER = {"pass": 0, "issues": 1, "fail": 2}


def _rank_verdict(s: ProcessScore) -> int:
    if s.verdict == "issues" and not any(
        i.severity in (Severity.ERROR, Severity.WARNING) and not is_measurement_caveat(i)
        for i in s.issues
    ):
        return _VERDICT_ORDER["pass"]
    return _VERDICT_ORDER.get(s.verdict, 3)


def _rank_key(s: ProcessScore):
    return (-s.score, _rank_verdict(s), _PROCESS_ORDER.get(s.process, len(_PROCESS_ORDER)))


def rank_processes(
    analysis: AnalysisResult,
    material_class: Optional[str] = None,
) -> list[ProcessScore]:
    """Rank scored processes by suitability (highest DFM score first).

    When ``material_class`` is given AND at least one scored process is
    compatible with that class, the ranking is RESTRICTED to material-compatible
    processes — so a metal part can never surface a resin/SLS/binder-jet process
    as "best" (that is material-blind noise: those processes win purely because
    they have the fewest geometric DFM constraints). Compatibility is the
    authoritative ``processes_for_material_class`` set, the same source costing's
    ``select_material`` uses, so the DFM headline and the cost route agree by
    construction.

    ``material_class=None`` (or an unknown class, or a class no scored process
    can be made in) => unfiltered geometry ranking, byte-identical to before —
    the honest behaviour when material is not declared.
    """
    # Tie-break equal scores by verdict: a clean "pass" must outrank an
    # equally-scored "issues"/"fail" process — otherwise an affinity-boosted
    # process with open issues can surface as "best" over a clean sibling.
    # Ties break on the verdict without measurement caveats, then on the fixed
    # process order, so the pick never depends on which caveats a file format
    # raised or on the order the scores arrived in.
    scores = sorted(analysis.process_scores, key=_rank_key)
    if not material_class:
        return scores
    compatible = processes_for_material_class(material_class)
    if not compatible:
        return scores
    filtered = [s for s in scores if s.process in compatible]
    # Only apply the filter when it leaves SOMETHING to rank; if no scored process
    # is makeable in this class (e.g. a narrowed ?processes= run), fall back to the
    # unfiltered ranking rather than claiming "no best process".
    return filtered if filtered else scores


def best_process_for_material(
    analysis: AnalysisResult,
    material_class: Optional[str] = None,
    prefer: Optional[list[str]] = None,
) -> Optional[ProcessType]:
    """The single "best process" to surface, material-aware and cost-coherent.

    1. Rank processes, restricted to those makeable in ``material_class`` (Fix 1
       — never a resin process for a metal part).
    2. Among the processes tied at the TOP score, prefer one named in ``prefer``
       (Fix 2 — pass the cost make-now process and/or the geometric routing pick
       so the DFM "best" AGREES with the dollar make-now whenever that route is
       itself among the most-manufacturable; otherwise they read as sane siblings
       of the same material family, never a contradiction).

    Returns None when no ranked process clears score > 0 (mirrors the historical
    ``ranked[0].score > 0`` rule — a hard-failed part has no positive best).
    """
    ranked = rank_processes(analysis, material_class)
    if not ranked or ranked[0].score <= 0:
        return None
    top_score = ranked[0].score
    top = [s for s in ranked if s.score == top_score]
    if prefer:
        # First mention wins, and anything not named sorts after every named one
        # (["cnc_turning", "cnc_turning"] used to rank turning level with the rest).
        prefer_order: dict[str, int] = {}
        for i, v in enumerate(prefer):
            prefer_order.setdefault(v, i)
        top.sort(key=lambda s: prefer_order.get(s.process.value, len(prefer)))
    return top[0].process
