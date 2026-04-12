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
from src.profiles.database import get_materials_for_process, get_machines_for_process


def score_process(
    issues: list[Issue],
    geometry: GeometryInfo,
    process: ProcessType,
) -> ProcessScore:
    """Score how suitable a process is based on analysis issues."""
    errors = [i for i in issues if i.severity == Severity.ERROR]
    warnings = [i for i in issues if i.severity == Severity.WARNING]

    if errors:
        score = 0.0
        verdict = "fail"
    elif warnings:
        # Deduct 0.1 per warning, minimum 0.3
        score = max(0.3, 1.0 - len(warnings) * 0.1)
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

    # Simple geometry (low face count) → CNC and molding are efficient
    if geometry.face_count < 500:
        if process in (ProcessType.CNC_3AXIS, ProcessType.INJECTION_MOLDING):
            score = min(1.0, score + 0.05)

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


def rank_processes(
    analysis: AnalysisResult,
) -> list[ProcessScore]:
    """Rank all scored processes by suitability."""
    scores = sorted(analysis.process_scores, key=lambda s: s.score, reverse=True)
    return scores
