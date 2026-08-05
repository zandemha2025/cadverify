---
title: "Industry regimes — what each one actually demands"
domain: audit
audience: "Engineers working across industries, or entering a new one"
sources: [api_6a, api_q1, nace_mr0175, as9100, as9102, nadcap, iso_13485, fda_820, iatf_16949, aiag_ppap, iso_astm_52910]
provenance: DEFAULT
---

# Industry regimes

Four regimes dominate high-consequence manufacturing. They share a QMS ancestor
(ISO 9001) and diverge sharply in what they consider proof — because they are
afraid of different things.

| Regime | Core standards | Afraid of | Proof is |
|---|---|---|---|
| **Oil & gas** | API 6A, API Q1, NACE MR0175/ISO 15156, ASME BPVC | A pressure release, a sour-service crack | Material traceability + NDE + hydrostatic test |
| **Aerospace** | AS9100D, AS9102, AS9145, NADCAP | A fatigue failure in flight | Configuration control + FAI + special-process accreditation |
| **Medical** | ISO 13485, 21 CFR 820, ISO 10993 | Harm to a patient | Design-control traceability + validation |
| **Automotive** | IATF 16949, AIAG PPAP, AIAG-VDA FMEA | A defect at a million units | Process capability at rate |

The most useful thing to understand about all four: **the fear determines the
evidence.** Once you know what a regime is afraid of, you can predict what its
auditor will ask without reading the standard.

---

## Oil & gas — API 6A and NACE

**The mental model is a leak path.** Every question traces back to: can pressure
get out, and would we know before it did?

**The PSL ladder** is a ladder of *evidence*, not of metal quality:

- **PSL-1** — baseline design, materials, hydrostatic testing.
- **PSL-2** — adds mandatory traceability through production, plus surface NDE
  (MT/PT) and hardness testing.
- **PSL-3** — extends testing and hydrostatic hold duration.
- **PSL-4** — full heat traceability, low-temperature impact testing, 100% NDE of
  pressure-containing welds, hardness survey, gas seat testing, full dimensional
  inspection, and a certified QMS.

PSL-3 is typical for wellhead and tree equipment at major operators; PSL-4
appears on high-pressure subsea duty.

**What the auditor opens first:** material certificates traced to heat number,
then hardness surveys for sour service, then NDE coverage, then hydro test
records — meeting in the middle.

**The three findings that recur:**

1. *"NACE compliant"* asserted with no environment attached. Compliance is a
   property of the material **in its environment**, qualified within stated limits
   of H₂S partial pressure, chloride, pH, temperature and elemental sulphur.
2. **Hardness surveyed on base metal only.** The heat-affected zone is where
   sulphide stress cracking initiates. Surveying only the base metal measures the
   safe part.
3. **Volumetric NDE performed before final machining**, so the examined condition
   is not the delivered condition. API 6A requires it after all welding, PWHT and
   machining.

**Design levers:** design for inspectability (UT access, couplant path, film
access), design for the hydrostatic test (port access, venting, fixture), keep
hardness within the sour-service ceiling by material and heat-treat choice rather
than by hoping, and never treat a forging and a machined billet as
interchangeable — the grain-flow argument is the whole point of the forging.

---

## Aerospace — AS9100, AS9102 and NADCAP

**The mental model is configuration plus fatigue.** Nothing is verified until it
is recorded against a ballooned characteristic, and nothing is trustworthy unless
you can prove exactly which definition it was made from.

**AS9102 first article** — every characteristic on the drawing or model
ballooned, numbered, measured and recorded on Forms 1–3, with the means of
inspection stated and material and special-process certifications attached.
Re-triggered by design change, process change, source change, or a long
production gap.

**NADCAP** accredits **special processes** — heat treat, NDT, chemical
processing, welding, coatings, materials testing, AM — where conformity cannot be
verified by inspecting the finished part. AS9100 does not require NADCAP; most
primes require it by flow-down, and the trap is a certificate that is current but
does not cover the specific scope actually performed.

**The three findings that recur:**

1. **Characteristics on the model but not on the balloon map** — typically
   PMI-carried tolerances that the extraction missed. The number-one FAI defect
   in MBD workflows, and the reason semantic PMI and characteristic counting
   matter so much.
2. **A STEP file emailed to a supplier and manufactured**, while the released
   native model moved on.
3. **Special-process certificates in date but out of scope.**

**Design levers:** extract characteristics from the model itself rather than from
a derived drawing; designate key characteristics explicitly instead of implying
them with tight tolerance; avoid geometry that creates un-inspectable FOD traps;
and treat unqualified material substitution as a design change, not a purchasing
decision.

---

## Medical — ISO 13485, FDA QMSR, ISO 10993

**The mental model is a chain, and the auditor pulls on it.** Every design output
traces to a design input; every verification to an output; every validation to a
user need. A break anywhere is the finding, regardless of how good the device is.

Note the regulatory context: the FDA's Quality System Regulation has been
harmonised with ISO 13485 as the QMSR, effective February 2026 — so a device
organisation now works from one substantially aligned framework rather than two.

**The three findings that recur:**

1. **Geometry with no design input behind it** — it exists because a previous
   device had it, and nobody recorded why.
2. **Verification and validation conflated.** Verification shows outputs meet
   inputs. Validation shows the device meets user needs in actual or simulated
   use. Doing the first thoroughly and assuming the second is a major finding.
3. **Biocompatibility argued from the raw alloy certificate**, ignoring
   manufacturing residues. ISO 10993 evaluates the **finished, cleaned,
   sterilised device**, which makes cleanability a geometry problem.

**Design levers:** attach requirement IDs to features so geometry carries its
justification; design for cleanability (no blind crevices, no trapped AM powder,
everything drainable); identify the worst-case cleanable feature at design time;
and surface which qualifications a change puts at risk, because a supplier
process change can invalidate a biological evaluation without touching the alloy.

---

## Automotive — IATF 16949, APQP and PPAP

**The mental model is capability at rate.** One good part proves nothing; the
question is whether the process makes a million of them.

**PPAP** is the 18-element evidence package submitted at the end of APQP, at a
submission level (1–5) the customer sets. It includes design records, change
documents, DFMEA and PFMEA, process flow, control plan, MSA, dimensional results,
material and performance test results, initial process studies, laboratory
documentation, appearance approval, sample and master parts, checking aids,
customer-specific requirements, and the Part Submission Warrant.

**The three findings that recur:**

1. **The chain does not reconcile.** Every special characteristic in the DFMEA
   must appear in the PFMEA and be controlled in the control plan, with the same
   identifiers throughout. Four documents authored independently is the single
   most common PPAP rejection.
2. **Capability from a soft-tool sample run** presented as production capability.
3. **Gage R&R failing because the tolerance is too tight for any available gage**
   — a design defect surfacing at PPAP, months after the tolerance was typed.

Also worth knowing: the AIAG-VDA FMEA handbook replaced RPN ranking with Action
Priority. A DFMEA still ranked by RPN is a finding at most OEMs.

**Design levers:** designate special characteristics once, in the model, and let
every downstream document inherit them; compare designed tolerance against
realistic process capability *before* the tool is cut; and remember that
cavity-to-cavity variation on a multi-cavity tool is a tooling design decision
made long before PPAP measures it.

---

## Additive manufacturing across all four

AM cuts across the regimes and none of them has fully absorbed it, because AM
breaks the assumption every regime is built on: that the material and the shape
are separate things with separate qualifications.

The common demands, wherever you are:

- **A frozen process** — machine, alloy and powder specification, layer thickness,
  beam parameters, scan strategy, atmosphere, plate temperature. A silent
  firmware update after qualification, with no requalification, is a major
  finding.
- **Powder lifecycle control** — blending rules, sieving, oxygen and moisture
  control, lot traceability, reuse limits. Powder lot is material traceability;
  treat it as a heat number.
- **Controlled, recorded orientation and plate position**, because properties
  vary with both.
- **Witness coupons from the same build**, tested per build.
- **Post-processing records**, including HIP parameters where fatigue or pressure
  duty requires it.
- **A feasible volumetric inspection method** at the wall thickness and defect
  size that matter.

Industry-specific: API 6A has no general AM qualification path, so AM in the
pressure boundary needs a purchaser-agreed basis plus HIP and full NDE. Aerospace
routes AM through NADCAP and prime-specific qualification. Medical adds powder
residue to the biological evaluation.

---

## What transfers between regimes, and what does not

**Transfers:** configuration control, traceability, change impact assessment,
calibration, contemporaneous records, root-cause discipline. An organisation good
at these is good everywhere.

**Does not transfer:** the specific evidence. An AS9102 FAI is not a PPAP. A NADCAP
certificate means nothing to an API auditor. A PSL rating means nothing to the
FDA.

The mistake organisations make entering a new industry is assuming their QMS
covers it because it is certified. The QMS covers the *habits*. The evidence has
to be rebuilt, and the design decisions that make the evidence cheap or expensive
are made long before anyone sees the standard.
