"""Tolerance analysis service — orchestrates AP242 parse -> GD&T extract -> validate.

Pipeline: parse STEP AP242 -> extract GD&T tolerances -> validate against
process capability tables -> produce ToleranceReport with achievability verdicts.
"""

from __future__ import annotations

import logging
from typing import Any

from src.analysis.capabilities.loader import validate_tolerance
from src.analysis.models import ProcessType
from src.analysis.tolerance_models import (
    AchievabilityVerdict,
    ToleranceAchievability,
    ToleranceEntry,
    ToleranceReport,
)

logger = logging.getLogger("cadverify.tolerance_service")


def analyze_tolerances(
    file_bytes: bytes,
    filename: str,
    target_processes: list[ProcessType],
) -> ToleranceReport:
    """Run full tolerance analysis pipeline on a STEP file.

    Orchestrates: AP242 parse -> GD&T extraction -> capability validation
    -> summary score calculation.

    Args:
        file_bytes: Raw STEP file bytes.
        filename: Original filename for extension detection.
        target_processes: Manufacturing processes to evaluate against.

    Returns:
        ToleranceReport with extraction results and achievability verdicts.
    """
    from src.parsers.step_ap242_parser import is_ap242_supported, parse_ap242_from_bytes
    from src.parsers.gdt_extractor import extract_gdt, extract_surface_finish

    # Gate: OCP XDE availability
    if not is_ap242_supported():
        logger.info("AP242 not supported — returning empty tolerance report")
        return ToleranceReport(
            has_pmi=False,
            pmi_note="AP242 parsing not available (OCP XDE modules missing)",
        )

    # Parse AP242 document
    ap242_doc = parse_ap242_from_bytes(file_bytes, filename)

    # Gate: PMI presence
    if not ap242_doc.has_pmi:
        logger.info("No PMI found in %s", filename)
        return ToleranceReport(
            has_pmi=False,
            pmi_note="No GD&T annotations found in STEP file; analysis based on geometry only.",
        )

    # Extract GD&T tolerances
    tolerances, warnings = extract_gdt(ap242_doc)

    if not tolerances and warnings:
        logger.warning("GD&T extraction yielded no tolerances with %d warnings", len(warnings))
        return ToleranceReport(
            has_pmi=True,
            pmi_note=f"{len(warnings)} annotation(s) could not be extracted: {'; '.join(warnings)}",
        )

    # Merge surface finish annotations into matching ToleranceEntry objects
    surface_finishes = extract_surface_finish(ap242_doc)
    if surface_finishes:
        _merge_surface_finish(tolerances, surface_finishes)

    # Validate each tolerance against each target process
    achievability: list[ToleranceAchievability] = []
    for tol in tolerances:
        for proc in target_processes:
            verdict_str, cap_min, margin = validate_tolerance(
                tol.value_mm, proc, tol.tolerance_type.value
            )
            try:
                verdict = AchievabilityVerdict(verdict_str)
            except ValueError:
                # "unknown" is not in the enum — treat as not_achievable for scoring
                verdict = AchievabilityVerdict.NOT_ACHIEVABLE

            achievability.append(
                ToleranceAchievability(
                    tolerance_id=tol.tolerance_id,
                    process=proc,
                    verdict=verdict,
                    process_capability_mm=cap_min,
                    margin_mm=margin,
                )
            )

    # Calculate summary score: best process's % of achievable tolerances
    summary_score = _calculate_summary_score(tolerances, achievability, target_processes)

    # Build pmi_note from warnings
    pmi_note: str | None = None
    if warnings:
        pmi_note = f"{len(warnings)} annotation(s) could not be extracted: {'; '.join(warnings)}"

    logger.info(
        "Tolerance analysis for %s: %d tolerances, %d processes, score=%.1f",
        filename,
        len(tolerances),
        len(target_processes),
        summary_score,
    )

    return ToleranceReport(
        has_pmi=True,
        pmi_note=pmi_note,
        tolerances=tolerances,
        achievability=achievability,
        summary_score=summary_score,
    )


def _merge_surface_finish(
    tolerances: list[ToleranceEntry],
    surface_finishes: list[tuple[str, float]],
) -> None:
    """Merge surface finish Ra values into matching tolerance entries.

    Simple heuristic: assign surface finish values to tolerance entries
    in order. If more entries than finishes, remaining entries get no Ra.
    """
    for i, (desc, ra_um) in enumerate(surface_finishes):
        if i < len(tolerances):
            tolerances[i].surface_finish_ra_um = ra_um


def _calculate_summary_score(
    tolerances: list[ToleranceEntry],
    achievability: list[ToleranceAchievability],
    target_processes: list[ProcessType],
) -> float:
    """Calculate summary score as % of tolerances achievable by best process.

    For each process, count how many tolerances have "achievable" verdict.
    Return the best process's score as a percentage (0-100).
    """
    if not tolerances:
        return 0.0

    total = len(tolerances)
    best_score = 0.0

    for proc in target_processes:
        proc_results = [a for a in achievability if a.process == proc]
        achievable_count = sum(
            1 for a in proc_results if a.verdict == AchievabilityVerdict.ACHIEVABLE
        )
        score = (achievable_count / total) * 100
        if score > best_score:
            best_score = score

    return round(best_score, 1)


def tolerance_report_to_dict(report: ToleranceReport) -> dict[str, Any]:
    """Serialize a ToleranceReport to a JSON-compatible dict.

    Groups achievability by tolerance_id, then by process for structured
    response output.

    Args:
        report: Complete tolerance analysis report.

    Returns:
        Dict with has_pmi, summary_score, entries, and optional pmi_note.
    """
    result: dict[str, Any] = {
        "has_pmi": report.has_pmi,
        "summary_score": report.summary_score,
    }

    if report.pmi_note:
        result["pmi_note"] = report.pmi_note

    entries: list[dict[str, Any]] = []
    for tol in report.tolerances:
        # Group achievability for this tolerance
        tol_achievability = [
            a for a in report.achievability if a.tolerance_id == tol.tolerance_id
        ]

        process_verdicts: list[dict[str, Any]] = []
        for a in tol_achievability:
            process_verdicts.append({
                "process": a.process.value,
                "verdict": a.verdict.value,
                "process_capability_mm": a.process_capability_mm,
                "margin_mm": round(a.margin_mm, 4),
            })

        entry: dict[str, Any] = {
            "tolerance_id": tol.tolerance_id,
            "tolerance_type": tol.tolerance_type.value,
            "value_mm": tol.value_mm,
            "datum_refs": tol.datum_refs,
            "feature_description": tol.feature_description,
            "process_verdicts": process_verdicts,
        }

        if tol.surface_finish_ra_um is not None:
            entry["surface_finish_ra_um"] = tol.surface_finish_ra_um

        if tol.upper_deviation is not None:
            entry["upper_deviation"] = tol.upper_deviation
        if tol.lower_deviation is not None:
            entry["lower_deviation"] = tol.lower_deviation

        entries.append(entry)

    result["entries"] = entries
    return result
