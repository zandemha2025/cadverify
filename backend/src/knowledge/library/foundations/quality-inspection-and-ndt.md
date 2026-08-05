---
title: "Quality, inspection and NDT — how a part gets believed"
domain: foundations
audience: "Designers who must make their parts provable"
sources: [as9102, aiag_msa, asme_bpvc_ix, api_6a, iatf_16949]
provenance: DEFAULT
---

# Quality, inspection and NDT

A part is not accepted because it is good. It is accepted because someone
demonstrated it is good, by a method agreed in advance, and recorded it. Design
decides how hard that will be — and design usually makes that decision without
noticing.

---

## Dimensional inspection

**CMM (coordinate measuring machine)** — the workhorse for prismatic parts.
Accurate, slow, and utterly dependent on the datum scheme. If the CMM setup does
not mirror the functional datum structure on the definition, every result is
invalid regardless of machine accuracy.

**Structured light and laser scanning** — fast, full-surface, ideal for freeform
and castings, and the natural way to inspect profile tolerances. Lower point
accuracy than a CMM and struggles with shiny, dark or deep features.

**CT (computed tomography)** — the only practical way to inspect internal
geometry and internal porosity together. Increasingly the acceptance method for
metal AM. Resolution falls with part size and material density, so there is a
real limit on how big and how dense a part you can meaningfully CT.

**Hard gauging** — go/no-go, functional gauges. Fast, cheap, robust on the shop
floor, and the natural partner to MMC-modified position tolerances, because the
gauge *is* the boundary the tolerance describes.

### Measurement systems analysis — the design trap

Gage R&R quantifies how much of the observed variation is the measurement
system. The rule that bites designers: **a tolerance tight relative to gage
capability fails MSA no matter how well the part is made.** A rough working
guide is that measurement variation should consume no more than about 10% of
the tolerance, with 10–30% conditionally acceptable.

The failure looks like a metrology problem and is a design problem. It is
discovered at PPAP, months after the tolerance was typed, when it is expensive
to change.

---

## Non-destructive examination

Each method sees a different defect population. Choosing one is choosing what
you are willing to miss.

| Method | Finds | Misses | Design consequence |
|---|---|---|---|
| **VT** visual | Surface, gross | Anything subsurface | Needs access and lighting |
| **PT** dye penetrant | Surface-breaking, any non-porous material | Subsurface; unusable on porous surfaces | Surface must be finished enough to be clean |
| **MT** magnetic particle | Surface and slightly subsurface, ferromagnetic only | Non-ferrous entirely | Geometry must allow field orientation both ways |
| **UT** ultrasonic | Volumetric, planar defects especially | Needs coupling, geometry, and a known thickness | Needs a scannable surface and a back wall |
| **RT** radiographic | Volumetric, volumetric defects especially | Tight planar cracks aligned wrongly to the beam | Needs film/detector access on the far side |
| **CT** computed tomography | Volumetric plus geometry | Limited by size and density | The AM answer, within its size envelope |
| **ET** eddy current | Surface and near-surface, conductive | Depth limited | Good for tube and bore inspection |

Three things designers routinely get wrong:

- **UT and RT find different defects.** UT is better at planar defects
  perpendicular to the beam; RT is better at volumetric ones. Codes often let you
  choose, and the choice is not neutral.
- **Inspection must happen in the delivered condition.** API 6A requires
  volumetric NDE of pressure-containing welds **after** all welding, PWHT and
  machining — examining before final machining examines a part that no longer
  exists.
- **Geometry can make a part un-inspectable.** Thick sections, complex
  intersections, internal lattices and enclosed cavities can defeat every
  available method. If nothing can see it, do not put a critical feature there.
  This is a design constraint, not an inspection problem.

---

## Special processes

A **special process** is one whose result cannot be fully verified by inspecting
the finished product: heat treatment, welding, NDT, chemical processing,
coatings, and additive manufacturing. You cannot look at a heat-treated part and
see whether the cycle was right.

Because verification is impossible after the fact, control moves upstream: a
qualified procedure, a qualified operator, a calibrated and surveyed furnace or
machine, and records. In aerospace that is NADCAP accreditation via prime
flow-down; in pressure work it is ASME Section IX weld procedure and welder
qualification (WPS, PQR, WPQ).

**Design consequence:** specifying a special process commits the supply chain to
finding an accredited source for that specific scope. A coating callout that
nobody in the approved supply base holds accreditation for is a schedule problem
disguised as a note on a drawing.

---

## The evidence packages, and which is which

**FAI — First Article Inspection (AS9102, aerospace).** Every characteristic on
the drawing or model is ballooned, numbered, measured, and recorded on Forms 1–3
with the means of inspection stated, plus material and special-process
certifications. Verifies *one part against the definition*. Triggered again by
design change, process change, source change, or a long production gap.

**PPAP — Production Part Approval Process (AIAG, automotive).** An 18-element
package proving the *process* can make conforming parts *at rate*: design
records, change documents, DFMEA and PFMEA, process flow, control plan, MSA,
dimensional results, material and performance test results, initial process
studies, qualified laboratory documentation, appearance approval, sample and
master parts, checking aids, customer-specific requirements, and the Part
Submission Warrant.

The distinction that matters: **FAI verifies a part; PPAP verifies a process.**
Low-rate aerospace cares about the first; high-volume automotive about the
second. AS9145 brings APQP/PPAP discipline into aerospace, so the boundary is
blurring — but the underlying question each answers is still different.

### The chain a PPAP auditor pulls on

DFMEA → process flow → PFMEA → control plan. Every special characteristic
identified in the DFMEA must appear in the PFMEA and be controlled in the control
plan, **with the same identifiers throughout**. Four documents authored
independently that disagree about which characteristics matter is the single most
common PPAP rejection — and it is a documentation failure with a design root
cause: characteristics designated informally, by tight tolerance, instead of
explicitly.

---

## Process capability

**Cp** compares specification width to process spread. **Cpk** also penalises an
off-centre mean. **Ppk** uses overall long-term variation and is what PPAP
initial studies report.

Two honest cautions:

- Capability computed from a short run on soft tooling is not production
  capability, and presenting it as such is a finding.
- Capability assumes a stable process. On an unstable one the number is
  arithmetic without meaning.

For design, the useful move is upstream: **compare the tolerance you are about to
specify against the process's known capability before you specify it.** That
comparison is cheap in CAD and ruinous at PPAP.

---

## Designing for provability

A short checklist that repays itself:

1. Can every specified characteristic be reached by some instrument?
2. Does the datum scheme match how the part will actually be fixtured to
   measure it?
3. Is any characteristic tighter than the available gage can resolve?
4. Are the critical ones designated explicitly, or only implied by tight
   tolerance?
5. Is there a feasible NDE method for every internal region that matters, at
   the wall thickness and defect size that matter?
6. Does every special process on the definition have an accredited source in
   the actual supply base?
7. Will the part be inspectable **in its delivered condition**, after every
   operation that changes it?

Each "no" is a cost, a schedule risk, or an audit finding — decided in CAD,
discovered much later.
