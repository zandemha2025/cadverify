"""Medical device rule pack — ISO 13485, FDA 21 CFR 820, ISO 5832, ASTM F standards.

Focused on biocompatibility, implant-grade materials, and regulatory traceability.
"""

from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.rules import RuleOverride, RulePack, register_pack

MEDICAL = register_pack(RulePack(
    name="medical",
    version="1.0.0",
    description="ISO 13485:2016 + FDA 21 CFR 820 + ISO 5832 + ASTM F136/F1472 overlays",
    overrides=[
        # ── Metal AM for implants: strictest tier ──
        RuleOverride(
            issue_code="THIN_WALL",
            process=ProcessType.DMLS,
            stricter_value=0.5,
            citation="ASTM F3301 §5.2: 0.5mm min wall for load-bearing implants.",
        ),
        RuleOverride(
            issue_code="THIN_WALL",
            process=ProcessType.EBM,
            stricter_value=0.8,
            citation="ASTM F3001 §5.1: 0.8mm min wall for EBM Ti-6Al-4V ELI implants.",
        ),
        RuleOverride(
            issue_code="RESIDUAL_STRESS_RISK",
            process=ProcessType.DMLS,
            escalate_to=Severity.ERROR,
            citation="ASTM F3301: HIP at 920°C/100MPa mandatory for all implant-grade PBF Ti.",
        ),
        RuleOverride(
            issue_code="RESIDUAL_STRESS_RISK",
            process=ProcessType.SLM,
            escalate_to=Severity.ERROR,
            citation="ASTM F3301: stress relief + HIP mandatory before clinical use.",
        ),
        RuleOverride(
            issue_code="TRAPPED_VOLUME",
            process=ProcessType.DMLS,
            escalate_to=Severity.ERROR,
            citation="FDA Guidance for AM Medical Devices (2017): trapped powder = bioburden risk.",
        ),
        RuleOverride(
            issue_code="TRAPPED_VOLUME",
            process=ProcessType.EBM,
            escalate_to=Severity.ERROR,
            citation="FDA: un-removed powder in implant cavities = surgical complication.",
        ),
        # ── CNC implant machining ──
        RuleOverride(
            issue_code="SHARP_INTERNAL_CORNERS",
            process=ProcessType.CNC_5AXIS,
            escalate_to=Severity.ERROR,
            citation="ISO 5832-3 §6: stress risers on implants cause fatigue fracture in vivo.",
        ),
        # ── Casting: porosity = fatigue initiation for implants ──
        RuleOverride(
            issue_code="SHRINKAGE_RISK",
            process=ProcessType.INVESTMENT_CASTING,
            escalate_to=Severity.ERROR,
            citation="ASTM F75: CoCr casting porosity limits for surgical implants.",
        ),
        # ── Injection molding: biocompatible material validation ──
        RuleOverride(
            issue_code="NON_UNIFORM_WALLS",
            process=ProcessType.INJECTION_MOLDING,
            escalate_to=Severity.ERROR,
            citation="ISO 10993-1: wall variation affects sterilization penetration (EtO, gamma).",
        ),
    ],
    mandatory_issues=[
        Issue(
            code="BIOCOMPATIBILITY_REQUIRED",
            severity=Severity.WARNING,
            message=(
                "ISO 10993-1: biocompatibility testing required for all patient-contacting devices. "
                "Test matrix depends on contact duration and tissue type."
            ),
            process=None,
            fix_suggestion=(
                "Select ISO 10993-1 test matrix based on device classification. "
                "Common implant alloys: Ti-6Al-4V ELI (ASTM F136), CoCrMo (ASTM F75/F1537), "
                "UHMWPE (ASTM F648). Verify material is the ELI/surgical grade."
            ),
        ),
        Issue(
            code="DESIGN_HISTORY_FILE",
            severity=Severity.INFO,
            message="FDA 21 CFR 820.30: Design History File (DHF) and Design Transfer required.",
            process=None,
            fix_suggestion="Maintain DHF per ISO 13485 §7.3 with design inputs, outputs, V&V records.",
        ),
        Issue(
            code="STERILIZATION_VALIDATION",
            severity=Severity.INFO,
            message="ISO 11135/11137: sterilization method must be validated for the device geometry.",
            process=None,
            fix_suggestion=(
                "Verify geometry allows sterilant penetration (EtO: no sealed cavities; "
                "gamma: material compatibility; autoclave: no heat-sensitive features)."
            ),
        ),
        Issue(
            code="UDI_MARKING",
            severity=Severity.INFO,
            message="FDA 21 CFR 801.20: Unique Device Identification (UDI) marking required on device or packaging.",
            process=None,
            fix_suggestion="Plan surface area for UDI mark (laser etch on metal, label on packaging).",
        ),
    ],
))
