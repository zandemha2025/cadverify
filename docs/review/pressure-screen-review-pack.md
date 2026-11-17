# For review by a practicing pressure-mechanical engineer

**Status: UNREVIEWED BY A PRACTITIONER.** Everything below ships with that
marker until this review lands and objections are incorporated. Review time:
~20 minutes.

## What we built

An opt-in wall screen on uploaded geometry (`POST /api/v1/validate?rated_pressure_bar=…&material_grade=…`):
it joins three measured quantities (a roundness-verified revolution axis
with OD; the largest coaxial bore; the ray-cast minimum wall, with its
proved upper bound) with the caller's declared pressure and grade, computes
the ASME VIII-1 UG-27(c) required thickness, and compares. It appears in
the response as one issue: PASS (info, with the margin), FAIL (error), or a
loud decline with the reason.

## The exact rules we encoded (challenge any of them)

1. **t_circ = P·R/(S·E − 0.6P)** and **t_long = P·R/(2SE + 0.4P)** — UG-27(c)(1)/(c)(2), verbatim.
2. **E = 0.70 assumed** — UW-12, Type 1 butt joint, no radiography. We know
   nothing about an uploaded part's joints, so we take the none-RT value and
   SAY SO in every message. We never upgrade E.
3. **S = min(2/3·Sy, Su/3.5)** — the Section II-D *basis*, computed from the
   material file's declared room-temperature properties. Not a II-D table
   lookup; **no temperature derating** (we say so).
4. **Validity domain t ≤ 0.5R or P ≤ 0.385·S·E** — outside it we DECLINE
   (Appendix 1-1 not implemented), never extrapolate.
5. Decline conditions: no verified revolution axis; no coaxial bore;
   no declared strength for the grade; wall unmeasurable; thick-wall outside
   domain.

## What our independent FEA says (please check our reading)

scikit-fem (axisymmetric weak form), three cylinders at t/R = 0.05/0.10/0.25:
FEA matches exact Lamé to **−0.08% or better**. The clause's own working
stress runs **+4%/+8%/+20% above FEA membrane** at those ratios, and
**+1.4%…+5.4% above the exact inner-wall maximum** — i.e., UG-27(c)(1)
itself accepts slightly more stress than continuum truth at the inner wall,
which we attribute to the clause's 0.6P term and the S margins. Full table:
`docs/pressure-screen-fea-verification.md`.

## Questions we want answered

1. Is E = 0.70-none-RT the right ASSUMED value for a screen with zero joint
   knowledge, or should a screen refuse without a declared joint category?
2. Is our reading of the +1.4%…+5.4% clause-vs-Lamé gap correct and
   acceptable to state publicly, or are we misreading the clause's intent?
3. For the decline paths: any you would turn into a computed answer
   (e.g., should we implement Appendix 1-1 for the thick-wall domain)?
4. Wording: does "geometry screen, not a certification" plus the E/S basis
   sentence give a practicing engineer exactly the right expectations?
5. Anything a fabricator would misread and act on dangerously?

## Worked sample you can check by hand

Tube OD 100 / bore 80 (wall 10, R = 40), 316L (Sy 220 / Su 550 → S = 146.7),
P = 100 bar (10 MPa): t_circ = 400/(102.67−6) = **4.14 mm** → PASS with
10.0 mm measured (2.42×). At 300 bar: t_req = 1200/84.69 = **14.17 mm** →
FAIL against the same wall. Hand-check those two against your UG-27 form.

*Reply inline here, or annotate `backend/src/analysis/pressure_screen.py`;
objections become test cases.*
