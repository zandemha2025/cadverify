"""Industry-specific rule packs — overlay objects that tighten DFM checks.

A RulePack does NOT replace the process analyzer. It post-processes the
analyzer's output to:
    1. Escalate severity (WARNING → ERROR) for safety-critical applications
    2. Tighten thresholds (if measured_value < stricter limit → ERROR)
    3. Inject mandatory issues (HIP required, traceability, etc.)
    4. Append standards citations to fix suggestions

Usage in routes.py:
    pack = get_rule_pack("aerospace")
    if pack:
        proc_issues = pack.apply(proc_issues, process)
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

from src.analysis.models import Issue, ProcessType, Severity


_SEVERITY_ORDER = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}


@dataclass
class RuleOverride:
    """One rule tightening or severity escalation."""

    issue_code: Optional[str] = None       # None = match all issue codes
    process: Optional[ProcessType] = None  # None = match all processes
    escalate_to: Optional[Severity] = None
    stricter_value: Optional[float] = None  # if measured_value < this → ERROR
    citation: Optional[str] = None          # appended to fix_suggestion


@dataclass
class RulePack:
    name: str
    version: str
    description: str
    overrides: list[RuleOverride] = field(default_factory=list)
    mandatory_issues: list[Issue] = field(default_factory=list)

    def apply(
        self,
        issues: list[Issue],
        process: ProcessType,
    ) -> list[Issue]:
        """Post-process analyzer output with industry overlays."""
        result = [deepcopy(i) for i in issues]

        for ov in self.overrides:
            if ov.process is not None and ov.process != process:
                continue
            for issue in result:
                if ov.issue_code is not None and issue.code != ov.issue_code:
                    continue
                if ov.escalate_to is not None:
                    if _SEVERITY_ORDER.get(ov.escalate_to, 0) > _SEVERITY_ORDER.get(issue.severity, 0):
                        issue.severity = ov.escalate_to
                if ov.stricter_value is not None and issue.measured_value is not None:
                    if issue.measured_value < ov.stricter_value:
                        issue.severity = Severity.ERROR
                        issue.required_value = ov.stricter_value
                if ov.citation:
                    tag = f"\n[{self.name}] {ov.citation}"
                    if issue.fix_suggestion:
                        issue.fix_suggestion += tag
                    else:
                        issue.fix_suggestion = tag.strip()

        for mi in self.mandatory_issues:
            if mi.process is None or mi.process == process:
                result.append(deepcopy(mi))

        return result


_PACKS: dict[str, RulePack] = {}


def register_pack(pack: RulePack) -> RulePack:
    _PACKS[pack.name.lower()] = pack
    return pack


def get_rule_pack(name: str) -> Optional[RulePack]:
    return _PACKS.get(name.lower())


def available_rule_packs() -> list[str]:
    return list(_PACKS.keys())


# Import all packs to trigger registration
from src.analysis.rules import aerospace as _  # noqa: F401, E402
from src.analysis.rules import automotive as __  # noqa: F401, E402
from src.analysis.rules import oil_gas as ___  # noqa: F401, E402
from src.analysis.rules import medical as ____  # noqa: F401, E402
