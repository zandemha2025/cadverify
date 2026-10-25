"""Generate actionable fix suggestions based on detected issues."""

from __future__ import annotations

from src.analysis.serialization import serialize_issue
from src.analysis.models import (
    AnalysisResult,
    Issue,
    ProcessType,
    Severity,
)


# Cross-process fix suggestions: when a check stops one process, name the
# processes whose own version of that check passed on THIS part. The engine's
# rules decide, not hand-written text: "Consider SLA (min 0.3mm)" was shown
# while the SLA wall check failed anything under 0.4 mm (M18). A tuple lists
# the processes worth naming; a string is advice that names no other process.
PT = ProcessType
ALTERNATIVE_PROCESS_MAP: dict[str, dict[ProcessType, tuple[ProcessType, ...] | str]] = {
    "THIN_WALL": {
        PT.FDM: (PT.SLA, PT.DLP, PT.MJF, PT.DMLS),
        PT.SLS: (PT.SLA, PT.DLP),
        PT.MJF: (PT.SLA, PT.DLP),
    },
    "OVERHANG": {
        PT.FDM: (PT.SLS, PT.MJF),
        PT.DMLS: (PT.EBM,),
        PT.SLM: (PT.EBM,),
    },
    "UNDERCUT": {
        PT.CNC_3AXIS: (PT.CNC_5AXIS,),
        PT.INJECTION_MOLDING: "Add side actions to the mold, or redesign the undercut away.",
    },
    "INSUFFICIENT_DRAFT": {
        PT.INJECTION_MOLDING: "Add 1-3° draft to all vertical walls. Machining and printing need no draft.",
    },
    "EXCEEDS_BUILD_VOLUME": {
        PT.FDM: (PT.SLS, PT.MJF),
        PT.SLA: (PT.FDM, PT.SLS, PT.MJF),
        PT.DMLS: (PT.DED, PT.WAAM),
        PT.SLM: (PT.DED, PT.WAAM),
    },
}

# What each check is called in "... pass their wall checks on this part".
_CHECK_NOUN = {
    "THIN_WALL": "wall check",
    "OVERHANG": "overhang check",
    "UNDERCUT": "undercut check",
    "EXCEEDS_BUILD_VOLUME": "size check",
}


def _passed_same_check(analysis: AnalysisResult, code: str, candidates) -> list:
    """Candidates the engine checked on this part that raised no ``code`` at all."""
    # A size check that couldn't confirm a fit didn't pass either.
    same = {code, "BUILD_ENVELOPE_UNVERIFIED"} if code == "EXCEEDS_BUILD_VOLUME" else {code}
    by_process = {ps.process: ps for ps in analysis.process_scores}
    return [p for p in candidates
            if p in by_process and not any(i.code in same for i in by_process[p].issues)]


def alternative_for(analysis: AnalysisResult, code: str, process: ProcessType) -> str | None:
    """The "Alternative: ..." text for ``code`` raised on ``process``, or None."""
    from src.analysis.process_names import join_labels

    rule = ALTERNATIVE_PROCESS_MAP.get(code, {}).get(process)
    if rule is None:
        return None
    if isinstance(rule, str):
        return rule
    passed = _passed_same_check(analysis, code, rule)
    if not passed:
        return None
    noun = _CHECK_NOUN.get(code, "check")
    if len(passed) == 1:
        return f"{join_labels(passed)} passes its {noun} on this part."
    return f"{join_labels(passed)} pass their {noun}s on this part."


def enhance_suggestions(analysis: AnalysisResult) -> AnalysisResult:
    """Enhance fix suggestions with cross-process alternatives.

    Modifies issues in-place to add process-switching suggestions
    when appropriate.
    """
    for ps in analysis.process_scores:
        for issue in ps.issues:
            alt_suggestion = alternative_for(analysis, issue.code, ps.process)
            if alt_suggestion and issue.fix_suggestion and "\n\nAlternative: " not in issue.fix_suggestion:
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

        evidence = serialize_issue(issue)
        fixes.append({
            "code": issue.code,
            "severity": issue.severity.value,
            "message": issue.message,
            "process": process.value if process else "all",
            "fix": issue.fix_suggestion,
            "measured_value": evidence.get("measured_value"),
            "required_value": evidence.get("required_value"),
            **({"measurement_unit": evidence["measurement_unit"]} if "measurement_unit" in evidence else {}),
        })

    return fixes
