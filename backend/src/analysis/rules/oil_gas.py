"""Oil & Gas rule pack — API 6A, NACE MR0175, ASME BPVC, API 5L.

Focused on pressure containment, sour service, and subsea integrity.
"""

from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.rules import RuleOverride, RulePack, register_pack

OIL_GAS = register_pack(RulePack(
    name="oil_gas",
    version="1.0.0",
    description="API 6A + NACE MR0175/ISO 15156 + ASME BPVC + API 5L compliance overlays",
    overrides=[
        # ── Forging: API 6A material classes ──
        RuleOverride(
            issue_code="INSUFFICIENT_DRAFT",
            process=ProcessType.FORGING,
            escalate_to=Severity.ERROR,
            citation="API 6A §5.2: forging draft must allow complete die fill for pressure-containing parts.",
        ),
        RuleOverride(
            issue_code="MISSING_FILLETS",
            process=ProcessType.FORGING,
            escalate_to=Severity.ERROR,
            citation="API 6A §5.3: stress concentrations at fillets cause fatigue failure in wellhead equipment.",
        ),
        RuleOverride(
            issue_code="HIGH_RIB_RATIO",
            process=ProcessType.FORGING,
            escalate_to=Severity.ERROR,
            citation="API 6A: rib defects in pressure-containing forgings = reject.",
        ),
        # ── Casting: tighter for pressure containment ──
        RuleOverride(
            issue_code="SHRINKAGE_RISK",
            process=ProcessType.SAND_CASTING,
            escalate_to=Severity.ERROR,
            citation="API 6A §6.2: radiographic examination required; porosity from shrinkage = reject.",
        ),
        RuleOverride(
            issue_code="SHRINKAGE_RISK",
            process=ProcessType.INVESTMENT_CASTING,
            escalate_to=Severity.ERROR,
            citation="API 6A PSL-3: zero porosity allowed in pressure-containing castings.",
        ),
        RuleOverride(
            issue_code="FRAGILE_CORE",
            process=ProcessType.SAND_CASTING,
            escalate_to=Severity.ERROR,
            citation="API 6A: core failure = internal void = pressure leak path.",
        ),
        # ── CNC: wall thickness critical for pressure vessels ──
        RuleOverride(
            issue_code="THIN_WALL",
            process=ProcessType.CNC_3AXIS,
            escalate_to=Severity.ERROR,
            citation="ASME BPVC §VIII Div.1: minimum wall per pressure calculation. No tolerance on thin walls.",
        ),
        RuleOverride(
            issue_code="THIN_WALL",
            process=ProcessType.CNC_5AXIS,
            escalate_to=Severity.ERROR,
            citation="ASME BPVC §VIII: wall thickness is pressure-rated. Under-machining = reject.",
        ),
        # ── Metal AM: not yet API-qualified for most applications ──
        RuleOverride(
            issue_code="RESIDUAL_STRESS_RISK",
            process=ProcessType.DMLS,
            escalate_to=Severity.ERROR,
            citation="API 6A has no AM qualification path yet. HIP + full NDE mandatory for any AM trial.",
        ),
        # ── Universal: non-manifold = pressure leak ──
        RuleOverride(
            issue_code="NON_WATERTIGHT",
            escalate_to=Severity.ERROR,
            citation="API 6A §7.4.9: hydrostatic test will fail on non-solid geometry.",
        ),
    ],
    mandatory_issues=[
        Issue(
            code="NACE_MR0175_CHECK",
            severity=Severity.WARNING,
            message=(
                "NACE MR0175/ISO 15156: if sour service (H₂S), material hardness "
                "must be ≤ 22 HRC and alloy must be listed in Table A.1/A.2."
            ),
            process=None,
            fix_suggestion=(
                "Verify material is NACE MR0175 compliant. Common compliant alloys: "
                "AISI 4130 (Q&T ≤ 22 HRC), Inconel 625/825, Duplex 2205, 25Cr. "
                "Non-compliant: most martensitic SS, high-strength carbon steels > 22 HRC."
            ),
        ),
        Issue(
            code="HYDROSTATIC_TEST",
            severity=Severity.INFO,
            message="API 6A §7.4.9: all pressure-containing parts require hydrostatic test at 1.5x rated WP.",
            process=None,
            fix_suggestion="Design must allow test port access. Plan hydro test fixture and procedure.",
        ),
        Issue(
            code="API_PSL_LEVEL",
            severity=Severity.INFO,
            message=(
                "API 6A PSL levels (1-4) progressively tighten inspection and documentation. "
                "PSL-3 required for most Aramco wellhead/tree equipment."
            ),
            process=None,
            fix_suggestion="Confirm required PSL level with customer. PSL-3/4 requires 100% NDE + material traceability.",
        ),
    ],
))
