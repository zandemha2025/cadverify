# Pressure screen — independent FEA verification (UG-27)

**Scope:** the shipped pressure screen encodes ASME BPVC Section VIII
Division 1, UG-27(c)(1)/(c)(2) required-thickness formulas verbatim. This
document verifies, with an independent finite-element analysis, that (a) the
FEA used for verification is itself correct (against the exact Lamé
solution), and (b) where the code's clause formula sits relative to
continuum-mechanics truth across the domain the screen allows. It also states
the screen's boundary — this is a screen, not a certification — and the
assumptions every run carries.

**Boundary copy (rides in every screen message):** *Geometry screen per ASME
VIII-1 UG-27 — not a certification. E = 0.70 assumed (UW-12, un-radiographed
butt joint). Allowable computed on the Section II-D basis from declared
room-temperature properties; no temperature derating.*

## Method

Three open-ended pressurized cylinders (internal pressure 10 MPa, steel
E = 200 GPa, ν = 0.3) at t/R = 0.05, 0.10, 0.25 — spanning thin to well
inside UG-27's t ≤ 0.5R validity domain — solved with
[scikit-fem](https://github.com/kinnala/scikit-fem) (independent open-source
FE assembly/solver) using the standard axisymmetric linear-elastic weak form
(`εθ = u_r/r`, ring-weighted 2πr, pressure traction on the bore; axial rigid
motion suppressed at one end so the ends stay open, isolating hoop action).

Reproduce: `python3 scripts/fea/verify_ug27_fea.py --json out.json`
(computed results committed at `scripts/fea/ug27_fea_results.json`;
`backend/tests/test_pressure_screen.py::test_fea_verification_matches_lame`
runs the same solves in CI and fails if the self-check degrades).

## Results

| t/R | FEA σθ inner (MPa) | Lamé σθ inner (MPa) | Δ FEA vs Lamé | FEA membrane (MPa) | Lamé P·a/t | UG-27(c)(1) working stress (MPa) | Δ UG-27 vs FEA membrane | Δ UG-27 vs Lamé inner max |
|-----|--------------------|--------------------|---------------|--------------------|------------|-----------------------------------|------------------------|---------------------------|
| 0.05 | 205.09 | 205.12 | **−0.01%** | 200.00 | 200.00 | 208.00 | +4.0% | +1.4% |
| 0.10 | 105.21 | 105.24 | **−0.03%** | 100.00 | 100.00 | 108.00 | +8.0% | +2.6% |
| 0.25 | 45.52 | 45.56 | **−0.08%** | 39.99 | 40.00 | 48.00 | +20.0% | +5.4% |

"UG-27(c)(1) working stress" = the stress at which the clause accepts the
wall, rearranged from t = P·R/(S·E − 0.6P) with E = 1 (E is a joint-quality
matter, not a membrane-stress matter).

## Reading the table (the honest part)

1. **The FEA is verified:** inner-wall hoop stress matches the exact Lamé
   solution to **0.08% or better** on all three geometries. Any future
   disagreement beyond 2% fails the CI test — a mesh/formulation problem
   rather than a formula question.

2. **The encoded clause is exact to the clause:** unit tests hand-check the
   shipped `ug27_required_thickness_mm` against the UG-27(c)(1)/(c)(2)
   arithmetic digit-for-digit (clause values, not fitted ones).

3. **The clause itself sits above continuum truth, by design of the code:**
   the UG-27(c)(1) working stress exceeds the FEA through-wall **membrane**
   hoop stress by **+4% at t/R = 0.05, +8% at 0.10, +20% at 0.25**, and
   exceeds even the exact **inner-wall maximum** by +1.4% to +5.4% over the
   same range. This is a property of the ASME clause (its 0.6P term and
   mean-radius form), not of our encoding; the code deems it acceptable
   because S already carries the Section II-D margin. We quantify it here
   because a screen that hides which side of truth its formula sits on is
   not honest. **Published agreement tolerance: the screen's required
   thickness equals the clause value exactly; the clause's own working
   stress runs +1.4% to +5.4% above the Lamé inner-wall maximum across
   t/R = 0.05–0.25.**

4. **What would change the answer:** the assumed E = 0.70 (a radiographed
   joint rises per UW-12, thinning the required wall), a temperature-derated
   allowable (no derating here), and corroded/minimum-conditions wall (the
   screen reads the uploaded geometry's measured minimum, which is neither).

## Practitioner review status

**Unreviewed by a practitioner.** This screen and its verification table are
drafted for review by a practicing pressure-mechanical engineer; their
objections are to be incorporated before any representation beyond "screen".
