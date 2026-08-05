---
title: "The auditor playbook — how expert auditors actually think"
domain: audit
audience: "Designers who will be audited; engineers building audit-aware tooling"
sources: [as9100, api_q1, iso_13485, iatf_16949, aiag_ppap]
provenance: DEFAULT
---

# The auditor playbook

## The mental model

An auditor is **not** checking whether the part is good. They are checking
whether you can **demonstrate** the part is good, by a route that does not depend
on anyone's memory.

This is the thing engineers find hardest to internalise. A perfect part with no
traceable basis for believing it is perfect is a finding. A mediocre part with
complete, honest evidence is not.

The recurring question is **"show me"**, and the recurring answer that fails is
"we always do it that way."

---

## How a good auditor works

**They pull a thread, they do not walk a list.** A checklist audit finds
checklist problems. A good auditor picks one real part and follows it end to
end — from the customer requirement, through the design record, the released
definition, the purchase order, the material certificate, the traveller, the
inspection records, the special-process certificates, to the shipped part and
its certificate of conformance. Every handoff is a chance for the chain to break.

**They start where evidence is created, not where it is stored.** Not the quality
manual — the shop floor, the operator's instruction, the actual gage, the actual
record being filled in right now.

**They ask the same question twice, of different people.** Consistency between the
procedure, the trainer's account and the operator's practice is the real subject
of the audit.

**They look for the gap between the system and the practice.** Where the
documented process and the actual process differ, one of them is wrong, and both
are a finding.

**They are drawn to the seams.** Sub-suppliers, subcontracted machining, an
outsourced special process, a rush job, a change made under schedule pressure.
Chains break at handoffs.

**They read dates.** A certificate that expired, a calibration overdue, a
qualification predating a process change, a document revision older than the
change it should reflect.

---

## The findings that recur, everywhere

Ranked by how often they appear and how much they cost:

1. **Configuration ambiguity.** Which revision was manufactured? A supplier
   working from an uncontrolled copy is the single most common serious finding
   across every industry.
2. **Traceability broken at a handoff.** Heat number lost at a subcontract
   machining step; powder lot not recorded; a distributor certificate that cannot
   be traced to a mill.
3. **Qualification silently invalidated.** A "minor" change — geometry, material,
   supplier, process parameter — with no impact assessment against what the
   qualification actually covered.
4. **Records that do not reconcile.** The DFMEA, PFMEA and control plan disagree
   about which characteristics matter. Four documents authored independently.
5. **Evidence created after the fact.** Inspection records filled in from memory
   at the end of a shift. Almost always visible in the handwriting, the timing,
   or the implausible consistency of the numbers.
6. **Calibration and accreditation lapses.** In-date certificates that do not
   cover the scope actually performed.
7. **Uncontrolled documents at the point of use.** The operator working from a
   printout of a superseded revision.
8. **Corrective actions that address the symptom.** "Retrained the operator" for
   a systemic process failure — an auditor reads this as evidence that root-cause
   analysis is not happening.

---

## What an auditor asks about *design*

These are the ones a CAD or DFM decision can actually influence, and the reason a
verification platform is an audit-preparation tool whether or not it is sold as
one.

**"Where did this number come from?"** — every specified value needs a traceable
basis: a calculation, a standard clause, a test, or a documented decision.
"Inherited from the previous part" is a finding when nobody checked whether the
basis still applies.

**"How do you know the process can hold this?"** — capability data, a qualified
process, or 100% inspection with a capable gage. A tolerance tighter than the
process, backed by sorting, is invisible on the drawing and expensive forever.

**"Show me the measurement system for this characteristic."** — a gage that
resolves the tolerance, calibrated, with an MSA. A characteristic tighter than
any available gage is a design defect discovered very late.

**"Which characteristics are critical, and how does the shop know?"** —
criticality communicated only by tight tolerance means the shop treats every
tight dimension as critical, or none of them.

**"What changed, and who assessed the impact?"** — every change on a released
item, with an assessment covering fit, function, qualification, tooling and
documentation.

**"How is this inspected in its delivered condition?"** — NDE performed before
final machining examines a part that no longer exists.

---

## What good evidence looks like

- **Contemporaneous.** Recorded when the thing happened, not reconstructed.
- **Attributable.** Who did it, on what equipment, to which procedure revision.
- **Complete.** Including the results that were not good, and what was done about
  them. A record with no nonconformances in three years is not reassuring; it is
  suspicious.
- **Traceable in both directions.** From the part back to the heat and the
  procedure; from the heat and the procedure forward to every part.
- **Legible and available.** Evidence that cannot be found during the audit does
  not exist during the audit.
- **Honest about uncertainty.** A stated assumption is defensible. An assumption
  presented as a measurement is a finding waiting to be made.

---

## The severity ladder

**Observation** — noted, no corrective action demanded. A weakness that has not
yet caused a problem.

**Minor** — a lapse in an otherwise effective control. One record missing, one
lapsed calibration. Corrective action required; certification not at risk.

**Major** — the control is absent or ineffective, or product acceptance is at
risk. A systemic breakdown, or a single failure with product consequence.
Certification is at risk, and a customer will often stop shipments.

The distinction that surprises people: **a single instance can be a major** if it
shows the control does not exist, and **a repeated instance can stay minor** if
the control exists and was followed imperfectly. Auditors judge the system, not
the count.

---

## Preparing, honestly

The genuine preparation is not a document scramble in the fortnight before. It
is:

- Being able to **pick any part and walk its thread** yourself, without warning.
- Having **impact assessments** on file for every change to a qualified item.
- Keeping **evidence contemporaneous** as a habit rather than a policy.
- Knowing **which of your characteristics are critical** and being able to show
  where each one is controlled.
- Being able to **produce the basis for any number** on any released definition.

A platform that keeps provenance on every number, versions every verification,
and records what changed between revisions is doing a meaningful part of that
work as a by-product. That is not the reason to build it, but it is the reason
quality organisations will care about it.
