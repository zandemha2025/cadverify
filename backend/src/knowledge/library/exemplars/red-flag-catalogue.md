---
title: "The red-flag catalogue — what bad looks like, and the tell"
domain: exemplars
audience: "Reviewers, and anyone building detectors"
sources: [boothroyd_dfma, iso_2768, sandvik_machining, nace_mr0175, asme_y14_41, iso_astm_52911]
provenance: DEFAULT
---

# The red-flag catalogue

The machine-readable version of this lives in `packs/red_flags.yaml`, where each
entry carries an observable `signal` so it can become a detector. This document
is the reading version: why each one matters, and how experienced reviewers
actually spot it.

**How to use it:** these are the things an experienced reviewer notices in the
first five minutes, before any analysis runs. Most of them are visible in a
glance at the model tree, the title block, or the bounding box — not in the
geometry.

---

## The five-minute scan

An experienced reviewer opening an unfamiliar part checks, in roughly this
order:

1. **Bounding box against the part class.** Is the size plausible? A factor near
   25.4 means a unit error, and it passes every geometric check because the
   geometry is internally consistent.
2. **Is it a closed solid?** Volume positive, manifold, no naked edges. If not,
   every number that follows is fiction.
3. **The tolerance distribution.** One tight number and a general class is
   healthy. A hundred and eighty tight numbers is the most expensive thing on the
   definition.
4. **The datum scheme.** Are datum features physical? Do they correspond to how
   the part mounts?
5. **The feature tree.** Errors? Suppressed features? A feature count wildly out
   of proportion to the geometry?
6. **How would you hold it?** If no answer is obvious, the fixturing cost is real
   and unmodelled.
7. **How many faces have features?** That is roughly the setup count, and on
   prismatic parts setup count predicts cost better than feature count.

---

## Geometry flags

**Zero-radius internal corners.** No rotating cutter makes them. The part gets
quietly re-radiused by the shop — changing geometry you designed — or it needs
EDM as a separate operation. *Tell: internal corner radius exactly zero, or below
the smallest practical tool.*

**Deep narrow features.** Tool deflection grows with the cube of unsupported
length and chip evacuation collapses. Geometrically legal, economically absurd.
*Tell: pocket depth over 4× the largest tool that fits the corner, or hole depth
over 10× diameter.*

**Zero draft on a moulded or cast part.** The part shrinks onto the core and
grips it. The most common reason a moulded design fails first shots, and tool
rework costs weeks. *Tell: faces near-parallel to the identified draw axis.*

**Thick section with no feed path.** Freezes last with nothing to feed it, so it
cavitates — reliably in the most highly stressed section. *Tell: local inscribed
sphere well above the part's modal wall, not adjacent to a feed location.*

**Enclosed volume with no evacuation.** Trapped powder in AM (dead mass,
contamination, invisible from outside), trapped resin in SLA (cures later and
swells the part), an unremovable core in casting. *Tell: a closed internal shell
with no connectivity to the exterior.*

**Nothing to hold it by.** A fixturing project before it is a machining job, and
the most reliably under-quoted geometry there is. *Tell: no planar face above an
area threshold, no parallel pair suitable for a vice.*

---

## Definition flags

**Blanket tight tolerance.** The largest avoidable cost on most machined parts,
and completely invisible in the geometry. *Tell: the ratio of tightly-toleranced
characteristics to total approaching 1.0, with no spread in the distribution.*

**Datum features that are not features.** An inspector cannot touch a centreline.
Also ambiguous, since several features may share it. *Tell: datum references that
do not resolve to a physical face, bore or width.*

**A datum scheme that does not match the assembly.** The most expensive class of
GD&T error, because it invalidates all downstream measurement while everything
appears to work. *Tell: datum surfaces carrying no mating interface in the
assembly context.*

**Mixed or unstated tolerancing standard.** ASME Rule #1 and ISO independency
give different acceptance outcomes on the same annotation. Both parties read the
same document correctly and disagree. *Tell: no governing standard **and edition**
declared.*

**Tolerance tighter than the process can hold.** The part is unbuildable as
drawn; the supplier quotes a premium, adds an unpriced operation, or ships on
concessions. *Tell: specified tolerance below the capability entry for the routed
process.*

**Ra with no basis, or beyond process capability.** Ra without a cut-off is not a
specification, and an as-built AM or as-cast surface cannot reach a fine Ra
without a finishing operation nobody priced. *Tell: finish callout lacking
cut-off, or below the process's achievable Ra.*

---

## Model flags

**Open or non-manifold shell.** Volume, mass, wall thickness and every derived
cost are undefined. *Tell: boundary edges present, edges shared by more than two
faces, volume undefined or negative.*

**Coarse tessellation presented as the part.** Measurements are wrong by the
chordal error and small features vanish entirely. A verdict computed on a
decimated mesh is a verdict about the mesh. *Tell: chordal deviation large
relative to feature size.*

**Unit ambiguity.** STL carries no units. A 25.4× error passes every geometric
check and every derived cost is wrong by 25.4³ on material. *Tell: overall
dimensions implausible for the part class by a factor near 25.4.*

**A model that cannot be edited.** Every change becomes a remodel and every
revision risks silent geometry drift. This is a cost forecast that lives entirely
in the file, not the shape. *Tell: rebuild errors, feature count far above the
geometric complexity, external references to dead geometry, suppressed features
doing load-bearing work.*

**PMI that did not survive the exchange.** Characteristics stop existing between
two systems, so they never reach the balloon map and are never inspected. The
number-one MBD first-article defect. *Tell: semantic PMI count in the received
file below the source; AP203/AP214 used where semantic PMI was required.*

---

## Compliance flags

**"NACE compliant" with no environment.** Compliance is a property of the material
**in its environment**, qualified within stated limits. Storing it as a boolean is
the most common documentation defect in the industry, and an auditor will go
straight at it. *Tell: a sour-service declaration carrying a compliance flag but
no environmental parameters.*

**Hardness surveyed on base metal only.** The HAZ is where sulphide stress
cracking initiates. Surveying the base metal measures the safe part. *Tell: a
welded sour-service part with hardness evidence not covering weld and HAZ.*

**A change that quietly invalidated a qualification.** Qualification attaches to a
specific configuration and process. The part is documented as qualified and is
not. *Tell: a geometry or process delta on a part carrying a qualification flag,
with no linked requalification record.*

---

## Economic flags

**Additive chosen for a part that does not need it.** Metal AM cost is dominated
by build time and powder, both scaling with volume; for simple geometry machining
wins decisively, and AM adds qualification burden the part never needed. *Tell:
low geometric complexity, no internal channels, no consolidation, and a
subtractive route within envelope.*

**Cost estimated from cycle time alone.** Setup frequently dominates at low and
medium volume. A model that ignores it under-quotes prismatic parts consistently
and rewards the wrong design changes. *Tell: a cost model with no setup term, or
a setup count of one on a part with features on many faces.*

**Geometry that contradicts its declared process.** The routing and the cost model
are wrong together. *Tell: geometry violating the defining constraint of the
declared process family — a "sheet metal" part with a machined boss, a "casting"
with zero draft, a "turned" part with off-axis features.*

**An assumption presented as a validated number.** The failure this whole platform
exists to prevent. Once a default is indistinguishable from a measurement, every
number becomes untrustworthy — including the good ones. *Tell: a number whose
provenance chain terminates in a literature default but is not labelled as such.*

---

## The meta-flag

The most reliable signal that something is wrong is **a number with no story**.

If nobody can say where a tolerance, a wall thickness, a material choice or a
cost figure came from, it is either inherited without review, guessed, or copied
from a part whose situation no longer applies. All three are defects, and all
three are invisible to a purely geometric analysis.

This is why provenance is not a UI feature. It is the detector for the largest
class of defect in the field.
