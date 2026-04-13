"""Automotive rule pack — IATF 16949, VDA 6.3, Toyota TPS.

Focused on high-volume production quality, PPAP, and process capability.
"""

from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.rules import RuleOverride, RulePack, register_pack

AUTOMOTIVE = register_pack(RulePack(
    name="automotive",
    version="1.0.0",
    description="IATF 16949 + VDA 6.3 + OEM-specific overlays (Toyota, BMW, VW)",
    overrides=[
        # ── Injection molding: tighten wall uniformity (cosmetic + structural) ──
        RuleOverride(
            issue_code="NON_UNIFORM_WALLS",
            process=ProcessType.INJECTION_MOLDING,
            escalate_to=Severity.ERROR,
            citation="IATF 16949 §8.3.3.1: design must ensure Cpk >= 1.33. Non-uniform walls cause sink marks = cosmetic reject.",
        ),
        RuleOverride(
            issue_code="INSUFFICIENT_DRAFT",
            process=ProcessType.INJECTION_MOLDING,
            escalate_to=Severity.ERROR,
            citation="VDA 6.3 P4: tooling qualification requires mold-release validation. Insufficient draft = tooling rework.",
        ),
        # ── Die casting: porosity is critical for structural auto parts ──
        RuleOverride(
            issue_code="THICK_WALL",
            process=ProcessType.DIE_CASTING,
            escalate_to=Severity.ERROR,
            citation="ASTM E505: porosity from thick sections fails X-ray in structural castings (subframes, nodes).",
        ),
        # ── Sheet metal: tighter bend rules for body panels ──
        RuleOverride(
            issue_code="SHARP_BEND",
            process=ProcessType.SHEET_METAL,
            escalate_to=Severity.ERROR,
            citation="VDA 239-100: springback on AHSS requires >= 1.5x thickness bend radius.",
        ),
        # ── FDM/AM: only for prototyping, flag if design targets production ──
        RuleOverride(
            issue_code="OVERHANG",
            process=ProcessType.FDM,
            citation="IATF 16949 §8.3.4.4: AM parts require separate PPAP if used in production.",
        ),
        # ── CNC: tight tolerances expected ──
        RuleOverride(
            issue_code="NO_FIXTURE_SURFACES",
            process=ProcessType.CNC_3AXIS,
            escalate_to=Severity.ERROR,
            citation="Toyota TPS: fixture stability = first-pass quality. No datum = scrap risk.",
        ),
    ],
    mandatory_issues=[
        Issue(
            code="PPAP_REQUIRED",
            severity=Severity.INFO,
            message="IATF 16949 §8.3.4.4: Production Part Approval Process (PPAP) required before SOP.",
            process=None,
            fix_suggestion="Prepare PPAP Level 3 submission: control plan, PFMEA, MSA, dimensional report, material certs.",
        ),
        Issue(
            code="CONTROL_PLAN_REQUIRED",
            severity=Severity.INFO,
            message="IATF 16949 §8.5.1.1: Control plan required for all production processes.",
            process=None,
            fix_suggestion="Develop control plan per AIAG APQP with key characteristics identified.",
        ),
    ],
))
