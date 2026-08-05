---
title: "CAD data management — revision, release and change control"
domain: cad
audience: "Anyone responsible for which model is the real one"
sources: [as9100, iso_13485, iatf_16949, asme_y14_41]
provenance: DEFAULT
---

# CAD data management

The question every audit eventually reduces to: **which revision was
manufactured, and can you prove it?**

---

## The vocabulary, used precisely

**Working / in-work** — the designer's copy. Changes freely. Authoritative for
nothing.

**Released** — checked, approved, frozen. The only geometry manufacturing may
use. Changing it requires a new revision.

**Revision** — a change to a released item, after release. Tracked, approved,
with a reason.

**Version** — a save point in the working state. Many versions per revision.

**Derived artifact** — anything generated *from* the released model: a STEP
export, a drawing PDF, a mesh, a CAM programme, an inspection plan. Never
authoritative, always traceable to its source revision.

**Effectivity** — from which serial, date or lot a revision applies. The thing
people forget, and the reason "we fixed that months ago" and "we have thirty in
the field with the old geometry" are both true.

**ECR / ECO / ECN** — request, order, notice. Propose, approve, communicate.

---

## The single most common finding

> Parts manufactured from an uncontrolled model copy. The released revision and
> the manufactured revision differ, and nobody can say when they diverged.

It happens the same way every time: a STEP file emailed to a supplier, or a model
copied to a shared drive, or a "quick" CAM update made against a local copy. The
released model then moves on. Nothing in the process was designed to notice.

The defence is structural, not procedural: **derived artifacts must carry their
source revision, and be checkable against it.** A hash and a revision stamp on
every export turns a silent divergence into a detectable one.

---

## What good looks like

- **One system of record** for released geometry. Not a folder. Not email.
- **Check-in / check-out** or equivalent, so two people cannot edit the same item
  into two different truths.
- **Immutable releases.** A released revision is never edited; it is superseded.
- **Every derived artifact traceable** to the revision it came from, by hash and
  by stamp.
- **Change orders carry an impact assessment** — fit, function, qualification,
  tooling, inspection, documentation, and parts in the field.
- **Effectivity recorded** on every change.
- **Where-used visibility**, so the impact of changing a part is known before it
  is changed rather than discovered afterwards.
- **A geometric diff between revisions**, not just a text description. "Increased
  boss height" and the actual volumetric delta are different amounts of
  information.

## What bad looks like

- **`bracket_v3_final_REV2_USE_THIS.sldprt`.** The filename is the version
  control system, and it is a bad one.
- **Released models editable in place.**
- **Suppliers working from files with no revision reference.**
- **Changes with no impact assessment** — the "it's just a fillet" change that
  invalidated a qualification, a fixture, or a first article.
- **No effectivity**, so nobody knows which units have which geometry.
- **CAM programmes and inspection plans with no link to the model revision they
  were made from**, so a geometry change silently leaves them stale.
- **The drawing and the model on different revision streams.**

---

## Change impact: what a change can invalidate

This is the list an experienced change board runs through, and the one an audit
will test:

| Change | Can invalidate |
|---|---|
| Geometry | First article, fixtures, CAM, inspection plan, tooling, mass properties, analysis |
| Material | Qualification, biocompatibility evaluation, corrosion basis, weld procedure, mechanical properties |
| Tolerance | Process capability, gage suitability, MSA, control plan |
| Supplier or source | Special-process accreditation, material traceability, PPAP or FAI status |
| Process parameter | AM or heat-treat qualification, PPAP, special-process approval |
| Surface finish or coating | Fatigue basis, corrosion basis, biocompatibility, fit |

The recurring pattern in real findings: a change assessed as "minor" against
*form and fit*, without anyone checking what it did to *qualification*. In
regulated industries the qualification consequence is usually the expensive one,
and it is invisible to a geometric diff.

---

## Where PLM and PDM sit

**PDM** manages CAD files: check-in/out, revisions, where-used, derived outputs.

**PLM** manages the product: BOM, change process, requirements, quality records,
supplier data, effectivity — with PDM inside it.

Most organisations have PDM and believe they have PLM. The tell is where the
change impact assessment lives. If it lives in a spreadsheet or an email thread,
the change process is not managed, however good the file vault is.

---

## What this means for a verification platform

Every verification is a claim about a specific geometry at a specific moment. To
be worth keeping, it must record **which** geometry:

- **Hash the analysed geometry.** The verification is about those exact bytes.
- **Capture the declared revision** as USER provenance — the user's claim, not a
  fact the engine verified.
- **Detect re-analysis of changed geometry** and say what changed, geometrically,
  not just that something did.
- **Keep verifications immutable.** A verification of revision B is not updated
  when revision C appears; a new one is created and the two are comparable.
- **Make the history the artifact.** "This part was verified at revision A, B and
  D; here is what moved between them, and here is which decisions were made on
  which" is the system-of-record value the platform claims — and it is only true
  if revisions are first-class from the start.

An analysis that cannot say which geometry it analysed is an opinion with a
timestamp.
