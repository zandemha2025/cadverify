"""Generate actionable fix suggestions based on detected issues."""

from __future__ import annotations

from src.analysis.models import (
    AnalysisResult,
    Issue,
    ProcessType,
    Severity,
)


# Cross-process fix suggestions: when an issue blocks one process,
# suggest alternative processes that don't have that constraint.
ALTERNATIVE_PROCESS_MAP = {
    "THIN_WALL": {
        ProcessType.FDM: "Consider SLA (min 0.3mm) or DMLS (min 0.4mm) for thinner walls.",
        ProcessType.SLS: "Consider SLA/DLP for finer wall resolution.",
    },
    "OVERHANG": {
        ProcessType.FDM: "SLS/MJF are self-supporting (no overhang limits). Or redesign with <45° angles.",
        ProcessType.DMLS: "Consider redesigning overhangs or switching to EBM (50° threshold).",
    },
    "UNDERCUT": {
        ProcessType.CNC_3AXIS: "Switch to 5-axis CNC, or redesign to eliminate undercuts.",
        ProcessType.INJECTION_MOLDING: "Add side actions to the mold, or redesign geometry.",
    },
    "INSUFFICIENT_DRAFT": {
        ProcessType.INJECTION_MOLDING: "Add 1-3° draft to all vertical walls. No draft needed for CNC or additive.",
    },
    "EXCEEDS_BUILD_VOLUME": {
        ProcessType.FDM: "Use BigRep (1m³) or split into multiple parts.",
        ProcessType.SLA: "Switch to FDM/SLS for larger build volumes.",
        ProcessType.DMLS: "Consider DED/WAAM for large metal parts (up to 5m).",
    },
}


def enhance_suggestions(analysis: AnalysisResult) -> AnalysisResult:
    """Enhance fix suggestions with cross-process alternatives.

    Modifies issues in-place to add process-switching suggestions
    when appropriate.
    """
    for ps in analysis.process_scores:
        for issue in ps.issues:
            alt_map = ALTERNATIVE_PROCESS_MAP.get(issue.code, {})
            alt_suggestion = alt_map.get(ps.process)
            if alt_suggestion and issue.fix_suggestion:
                issue.fix_suggestion += f"\n\nAlternative: {alt_suggestion}"

    return analysis


def get_priority_fixes(analysis: AnalysisResult) -> list[dict]:
    """Get fixes prioritized by impact — errors first, then warnings.

    Returns a flat list of fixes across all processes, deduplicated.
    """
    seen_codes: set[str] = set()
    fixes: list[dict] = []

    # Collect all issues across processes
    all_issues: list[tuple[Issue, ProcessType | None]] = []

    for issue in analysis.universal_issues:
        all_issues.append((issue, None))
    for ps in analysis.process_scores:
        for issue in ps.issues:
            all_issues.append((issue, ps.process))

    # Sort: errors first, then warnings, then info
    severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    all_issues.sort(key=lambda x: severity_order.get(x[0].severity, 3))

    for issue, process in all_issues:
        # Deduplicate by code (keep first = highest severity)
        if issue.code in seen_codes:
            continue
        seen_codes.add(issue.code)

        fixes.append({
            "code": issue.code,
            "severity": issue.severity.value,
            "message": issue.message,
            "process": process.value if process else "all",
            "fix": issue.fix_suggestion,
            "measured_value": issue.measured_value,
            "required_value": issue.required_value,
        })

    return fixes
