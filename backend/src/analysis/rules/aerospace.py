"""Aerospace rule pack — AS9100, Boeing BAC5673, FAA PMA, AMS, Nadcap.

Tightens tolerances for flight-critical and structural components.
All overrides cite a published standard section.
"""

from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.rules import RuleOverride, RulePack, register_pack

AEROSPACE = register_pack(RulePack(
    name="aerospace",
    version="1.0.0",
    description="AS9100 Rev D + Boeing BAC5673 + AMS + Nadcap compliance overlays",
    overrides=[
        # ── Metal AM: tighter walls, mandatory HIP ──
        RuleOverride(
            issue_code="THIN_WALL",
            process=ProcessType.DMLS,
            stricter_value=0.6,
            citation="Boeing BAC5673 §4.3: 0.6mm min wall for flight hardware Ti-6Al-4V.",
        ),
        RuleOverride(
            issue_code="THIN_WALL",
            process=ProcessType.SLM,
            stricter_value=0.6,
            citation="AMS 7003 §5.1: 0.6mm min wall for PBF metals.",
        ),
        RuleOverride(
            issue_code="RESIDUAL_STRESS_RISK",
            process=ProcessType.DMLS,
            escalate_to=Severity.ERROR,
            citation="AMS 7003: HIP mandatory for all PBF Ti flight parts. Curl = scrap.",
        ),
        RuleOverride(
            issue_code="RESIDUAL_STRESS_RISK",
            process=ProcessType.SLM,
            escalate_to=Severity.ERROR,
            citation="AMS 7003: HIP mandatory. Non-conformance = MRB review.",
        ),
        # ── Overhangs stricter for metal AM ──
        RuleOverride(
            issue_code="OVERHANG",
            process=ProcessType.DMLS,
            stricter_value=35.0,  # tighter than default 45°
            escalate_to=Severity.ERROR,
            citation="Boeing BAC5673 §5.2: 35° max overhang for Ti-6Al-4V without support.",
        ),
        # ── CNC: all warnings escalate to errors for flight parts ──
        RuleOverride(
            issue_code="SHARP_INTERNAL_CORNERS",
            process=ProcessType.CNC_3AXIS,
            escalate_to=Severity.ERROR,
            citation="ASME Y14.5-2018: stress concentrations are flight-safety critical.",
        ),
        RuleOverride(
            issue_code="SHARP_INTERNAL_CORNERS",
            process=ProcessType.CNC_5AXIS,
            escalate_to=Severity.ERROR,
            citation="ASME Y14.5-2018: stress risers disallowed on structural parts.",
        ),
        # ── Casting: tighter acceptance ──
        RuleOverride(
            issue_code="MISSING_FILLETS",
            process=ProcessType.INVESTMENT_CASTING,
            escalate_to=Severity.ERROR,
            citation="AMS 2175 Class 1: sharp corners cause hot tears in flight castings.",
        ),
        RuleOverride(
            issue_code="SHRINKAGE_RISK",
            process=ProcessType.INVESTMENT_CASTING,
            escalate_to=Severity.ERROR,
            citation="AMS 2175 Class 1: porosity in structural castings = reject.",
        ),
        # ── Universal: all NON_WATERTIGHT are errors (already default, reinforce) ──
        RuleOverride(
            issue_code="NON_WATERTIGHT",
            escalate_to=Severity.ERROR,
            citation="AS9100 §8.5.1: non-conforming geometry cannot enter production.",
        ),
        # ── Forging: grain flow matters ──
        RuleOverride(
            issue_code="UNDERCUT",
            process=ProcessType.FORGING,
            escalate_to=Severity.ERROR,
            citation="AMS 2175: undercuts disrupt grain flow in aerospace forgings.",
        ),
    ],
    mandatory_issues=[
        Issue(
            code="TRACEABILITY_REQUIRED",
            severity=Severity.INFO,
            message="AS9100 §8.5.2: lot/serial traceability required for all aerospace parts.",
            process=None,
            fix_suggestion="Ensure material certification, heat lot, and process records are maintained.",
        ),
        Issue(
            code="SPECIAL_PROCESSES",
            severity=Severity.INFO,
            message="Nadcap accreditation required for heat treat, NDT, welding, and surface treatment.",
            process=None,
            fix_suggestion="Verify all special processes are performed at Nadcap-accredited facilities.",
        ),
        Issue(
            code="FIRST_ARTICLE_INSPECTION",
            severity=Severity.INFO,
            message="AS9102: First Article Inspection Report (FAIR) required before production.",
            process=None,
            fix_suggestion="Plan FAIR per AS9102 Rev C — all characteristics, material certs, process approvals.",
        ),
    ],
))
