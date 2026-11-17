"""The UG-27 pressure wall screen — clause-anchored math and honest declines.

Known answers are hand-checked against ASME VIII-1 UG-27(c):
  t_circ = P·R/(S·E − 0.6P), t_long = P·R/(2SE + 0.4P), E = 0.70 (UW-12,
  un-radiographed butt joint assumed), S on the Section II-D basis
  (lesser of 2/3·Sy and Su/3.5) from the material file's declared
  room-temperature properties.
"""
from __future__ import annotations

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.pressure_screen import (
    JOINT_EFFICIENCY_ASSUMED,
    PressureScreenInput,
    allowable_stress_mpa,
    run_pressure_screen,
    ug27_required_thickness_mm,
)

# 316L as declared in profiles/materials/ss_316l.yaml (room temperature).
SS316L_YIELD = 220.0
SS316L_TENSILE = 550.0
# Section II-D basis: S = min(2/3·220, 550/3.5) = min(146.67, 157.14) = 146.67.
SS316L_S = 2.0 / 3.0 * SS316L_YIELD


def _tube_mesh(outer_diameter_mm: float, inner_diameter_mm: float,
               height_mm: float) -> trimesh.Trimesh:
    """A watertight straight tube via exact boolean difference, so OD, bore
    and wall are known by construction (faceting aside)."""
    outer = trimesh.creation.cylinder(radius=outer_diameter_mm / 2.0,
                                      height=height_mm, sections=96)
    bore = trimesh.creation.cylinder(radius=inner_diameter_mm / 2.0,
                                     height=height_mm * 1.5, sections=96)
    mesh = trimesh.boolean.difference([outer, bore])
    assert mesh.is_watertight
    return mesh


def _ctx_for(mesh: trimesh.Trimesh) -> GeometryContext:
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_features(ctx.mesh)
    return ctx


def _screen_input(bar: float, grade: str = "316L",
                  yield_mpa: float | None = SS316L_YIELD,
                  tensile_mpa: float | None = SS316L_TENSILE) -> PressureScreenInput:
    return PressureScreenInput(
        rated_pressure_bar=bar, material_grade=grade,
        yield_mpa=yield_mpa, tensile_mpa=tensile_mpa,
    )


# ---------------------------------------------------------------------------
# The arithmetic, clause by clause
# ---------------------------------------------------------------------------

class TestClauseArithmetic:
    def test_allowable_uses_the_ii_d_basis_lesser_of_two_thirds_yield_and_uts_over_3_5(self):
        s, words = allowable_stress_mpa(SS316L_YIELD, SS316L_TENSILE)
        assert s == pytest.approx(SS316L_S, rel=1e-3)
        assert "2/3·Sy" in words and "Su/3.5" in words
        assert "not a table lookup" in words  # the honesty is in the basis words

    def test_allowable_falls_to_uts_leg_when_yield_is_high(self):
        # 4140 (415/655): min(276.7, 187.1) = 187.1 — the UTS leg governs.
        s, _ = allowable_stress_mpa(415.0, 655.0)
        assert s == pytest.approx(655.0 / 3.5, rel=1e-3)

    def test_allowable_declines_without_any_strength(self):
        s, why = allowable_stress_mpa(None, None)
        assert s is None and "no declared" in why

    def test_ug27_circumferential_matches_hand_computation(self):
        # P=10 MPa, R=50mm, S=146.67, E=0.70:
        # t = 10·50 / (146.67·0.70 − 0.6·10) = 500 / 96.67 = 5.172mm
        t_circ, t_long = ug27_required_thickness_mm(10.0, 50.0, SS316L_S, 0.70)
        assert t_circ == pytest.approx(5.172, rel=1e-3)
        # UG-27(c)(2): t = 500 / (2·102.669 + 0.4·10) = 500/209.338 = 2.3885mm — hoop governs.
        assert t_long == pytest.approx(2.3885, rel=1e-3)
        assert t_circ > t_long

    def test_joint_efficiency_is_the_uw12_unradiographed_value(self):
        assert JOINT_EFFICIENCY_ASSUMED == 0.70


# ---------------------------------------------------------------------------
# The screen on known-answer geometry
# ---------------------------------------------------------------------------

class TestScreenOnTubes:
    OD, ID = 100.0, 80.0          # wall 10mm, R (bore radius) 40mm

    def test_100_bar_passes_with_the_computed_margin(self):
        # P=10 MPa, R=40: t_req = 400/(102.67−6) = 4.14mm << 10mm wall.
        ctx = _ctx_for(_tube_mesh(self.OD, self.ID, 40.0))
        issues = run_pressure_screen(ctx, _screen_input(100.0))
        assert len(issues) == 1
        issue = issues[0]
        assert issue.code == "PRESSURE_SCREEN_PASS"
        assert issue.severity.value == "info"
        assert issue.required_value == pytest.approx(4.14, rel=5e-3)
        assert issue.measured_value == pytest.approx(10.0, rel=0.05)
        assert issue.citation is not None
        assert issue.citation.clause == "UG-27(c)(1)"
        assert issue.citation.standard == "ASME BPVC Section VIII Division 1"
        labels = {b["label"] for b in issue.breakdown}
        assert {"bore_radius_R_mm", "required_t_circumferential_mm",
                "required_t_longitudinal_mm", "allowable_S_mpa",
                "joint_efficiency_E", "measured_min_wall_mm"} <= labels
        # The boundary copy rides in the message, always.
        assert "not a certification" in issue.message
        assert "UW-12" in issue.message

    def test_300_bar_fails_against_the_same_wall(self):
        # P=30 MPa, R=40: t_req = 1200/(102.67−18) = 14.17mm > 10mm wall.
        ctx = _ctx_for(_tube_mesh(self.OD, self.ID, 40.0))
        issues = run_pressure_screen(ctx, _screen_input(300.0))
        assert issues[0].code == "PRESSURE_SCREEN_FAIL"
        assert issues[0].severity.value == "error"
        assert issues[0].required_value == pytest.approx(14.17, rel=5e-3)
        assert "certified vessel calculation" in (issues[0].fix_suggestion or "")

    def test_thick_wall_outside_ug27_domain_declines_instead_of_extrapolating(self):
        # OD 100 / ID 20: nominal wall 40mm > 0.5R = 10mm, and 500 bar
        # (50 MPa) > 0.385·S·E = 39.5 MPa — outside UG-27(c) validity.
        ctx = _ctx_for(_tube_mesh(100.0, 20.0, 40.0))
        issues = run_pressure_screen(ctx, _screen_input(500.0))
        assert issues[0].code == "PRESSURE_SCREEN_UNAVAILABLE"
        assert "Appendix 1-1" in issues[0].message

    def test_non_cylinder_declines_no_verified_axis(self):
        ctx = _ctx_for(trimesh.creation.box(extents=(60, 60, 30)))
        issues = run_pressure_screen(ctx, _screen_input(50.0))
        assert issues[0].code == "PRESSURE_SCREEN_UNAVAILABLE"
        assert "revolution axis" in issues[0].message

    def test_solid_rod_declines_no_bore(self):
        ctx = _ctx_for(trimesh.creation.cylinder(radius=30, height=40, sections=96))
        issues = run_pressure_screen(ctx, _screen_input(50.0))
        assert issues[0].code == "PRESSURE_SCREEN_UNAVAILABLE"
        assert "bore" in issues[0].message

    def test_grade_without_strength_declines_naming_the_grade(self):
        ctx = _ctxFor = _ctx_for(_tube_mesh(self.OD, self.ID, 40.0))
        issues = run_pressure_screen(
            ctx, _screen_input(100.0, grade="unobtainium",
                               yield_mpa=None, tensile_mpa=None))
        assert issues[0].code == "PRESSURE_SCREEN_UNAVAILABLE"
        assert "unobtainium" in issues[0].message
        assert "no declared yield or tensile" in issues[0].message


# ---------------------------------------------------------------------------
# Independent FEA cross-check (scikit-fem): the verification table in
# docs/pressure-screen-fea-verification.md must stay true in CI. Skipped when
# scikit-fem is unavailable (it is a test-only dependency).
# ---------------------------------------------------------------------------

class TestFEAVerification:
    def test_fea_verification_matches_lame_and_published_tolerances(self):
        # Plain import, not importorskip: skfem 12's cold import through
        # importlib.import_module trips a circular-init quirk that a plain
        # statement import does not (verified both ways in this repo's venv).
        try:
            import skfem  # noqa: F401
        except ImportError:
            pytest.skip("scikit-fem not installed (test-only dependency)")
        import sys as _sys
        from pathlib import Path as _Path

        repo = _Path(__file__).resolve().parents[2]
        _sys.path.insert(0, str(repo / "scripts" / "fea"))
        try:
            from verify_ug27_fea import GEOMETRIES, lame_hoop_inner, solve_cylinder
        finally:
            _sys.path.remove(str(repo / "scripts" / "fea"))

        for _label, a, t in GEOMETRIES:
            res = solve_cylinder(a, a + t)
            # (a) The FEA itself: inner-wall hoop vs exact Lamé, within 0.5%
            # (observed: -0.01..-0.08%; 2% would indicate a mesh problem).
            lame = lame_hoop_inner(10.0, a, a + t)
            assert res["fea_inner_hoop_mpa"] == pytest.approx(lame, rel=0.005)
            # (b) The published UG-27-vs-FEA deltas: the clause's working
            # stress sits above membrane by exactly 100·0.8·t/a percent
            # (algebra of P(R/t+0.3) over P·a/t with R = a + t/2) — the docs
            # table's +4.0/+8.0/+20.0 at t/R = 0.05/0.10/0.25.
            ug27_err = 100.0 * (res["ug27_working_mpa"]
                                - res["fea_membrane_hoop_mpa"]) / res["fea_membrane_hoop_mpa"]
            assert ug27_err == pytest.approx(100.0 * 0.8 * t / a, abs=0.5)
