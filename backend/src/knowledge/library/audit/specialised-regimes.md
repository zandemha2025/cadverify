---
title: "Specialised regimes — nuclear, pressure, rail, marine, structural, export, hygienic"
domain: audit
audience: "Engineers entering a regulated sector they have not worked in before"
sources: [asme_nqa1, eu_ped, en_15085, iris_22163, marine_class, aws_d1_1_en_1090, itar_ear, hygienic_design]
provenance: DEFAULT
---

# Specialised regimes

The four big regimes — oil & gas, aerospace, medical, automotive — are covered in
[Industry regimes](industry-regimes.md). These seven are narrower, and each one
has a characteristic trap that catches competent engineers arriving from
elsewhere.

---

## Nuclear — NQA-1 and 10 CFR 50 Appendix B

**Afraid of:** a release, decades from now, traced to a decision nobody recorded.

The strictest regime in commercial manufacturing and the one with the longest
memory. Records are retained for the plant's life and read by people who cannot
ask anyone a question, so everything must be self-explanatory on paper.

**The trap:** *nothing is accepted on a supplier's word.* Engineers arriving from
aerospace assume a certificate of conformance is evidence. Under NQA-1, a
commercially procured item entering safety-related service requires
**commercial-grade dedication** — the buyer identifies the item's critical
characteristics and verifies them independently on the received part. That is an
engineering activity, and the critical characteristics come from the design.

Three more that surprise people:

- **Independent design verification.** Self-checked calculations are a finding.
  So is a reviewer who reports to the designer.
- **Cobalt is a design constraint.** Trace cobalt in stainless and in hardfacing
  activates to Co-60 under neutron flux and dominates plant dose rates for
  decades. Specifying low-cobalt material is a design decision, not a
  procurement preference.
- **Design for remote handling.** Once activated, a component may never be
  touched by hand again.

---

## Pressure equipment — EU PED versus ASME

**Afraid of:** a pressure release into a public space.

**The trap:** *ASME and PED look interchangeable and are not.* A vessel built to
ASME BPVC is not automatically PED-compliant, and the difference is not the
calculation — it is the **material approval route**. PED requires a harmonised
specification, a European Approval for Materials, or a Particular Material
Appraisal. An ASME-approved grade with no European route is not approved, even
though it is the same steel.

Two more:

- **Category is derived from fluid group as well as pressure and volume.**
  Assessing on pressure alone can put you in the wrong conformity module, without
  the notified body you needed.
- **Minimum wall means minimum after tolerance.** Machining tolerance, corrosion
  allowance and forming thinning all subtract from nominal. Tolerance the wall
  unilaterally from the calculated minimum, never bilaterally around a nominal.

If the equipment will sell into both markets, design for both from the start.
Requalifying afterwards is expensive and sometimes impossible.

---

## Rail — EN 15085 and IRIS

**Afraid of:** a structural weld failure at speed, and a fleet that cannot be
supported for thirty years.

**The trap:** *the weld performance class is a design decision, and blanket
classes are wrong in both directions.* Each weld gets a class from its safety and
stress category, and that class drives the examination extent. A single blanket
class over-inspects most of the vehicle while under-inspecting the joints that
matter. Assign classes from the actual load path.

Also: specifying a high weld class narrows the qualified supply base, because the
fabricator's EN 15085-2 certification level must cover the classes actually
performed. Know that before releasing.

The long-life angle is real engineering, not paperwork. **Obsolescence
management** over thirty years means the model and definition quality *is* the
re-manufacture route. An unmaintainable CAD model is an obsolescence risk with a
cost attached.

---

## Marine and offshore — classification societies

**Afraid of:** a failure at sea, where help is far away.

**The trap:** *a surveyor attends in person.* This is unusual among these regimes
and it changes the shape of the work. Survey and witness hold points are agreed
in advance, and an operation performed without the surveyor present may have to
be repeated — or the item rejected. The manufacturing **sequence** becomes part
of the approval, so hold points belong in planning rather than in expediting.

The other trap is **approved works**. Class approval attaches to the source as
well as the composition. Chemically identical material from a works without class
approval is not acceptable, and the discovery point is the surveyor, after the
part exists.

Design consequence worth noting: permanent marking must survive machining,
coating and installation. Traceability is broken at the last step more often than
at the first.

---

## Structural steelwork — AWS D1.1 and EN 1090

**Afraid of:** a building or bridge, inspected by sampling rather than
exhaustively.

**The trap:** *the execution class is the designer's to set, and it is routinely
left blank.* EXC1–EXC4 drives tolerance, inspection extent, traceability and
welder qualification. Unstated, the fabricator reasonably defaults to the lowest
and inspects accordingly. That is a design omission showing up as a fabrication
one.

Two practical points:

- **Identify critical welds explicitly.** A blanket inspection percentage lets
  the fabricator choose which welds get examined, and they will not choose yours.
- **Distortion is designed, not corrected.** Symmetric joints and balanced
  welding sequences cost nothing. Heat straightening afterwards alters material
  properties invisibly and often goes unrecorded.

---

## Export control — ITAR and EAR

**Afraid of:** controlled technology reaching a foreign government.

**The trap, and it is the most important one in this document:** *a CAD model is
technical data.* Transferring it to a foreign person is an export — including by
granting read access to a server, or by sending it out for a quote. No physical
part has to move. This is the regime engineers break by accident, doing entirely
ordinary work, continuously and silently.

Four places it happens:

1. **Controlled models on a general engineering share** that foreign-national
   employees can open. This is a deemed export, occurring every day.
2. **Quoting packages sent overseas** before any licence exists. Quoting is a
   transfer.
3. **Cloud tools** with foreign administrators or no data-residency guarantee.
4. **No classification determination made at all**, on the assumption that a
   commercial-looking part is uncontrolled.

Penalties here are criminal and personal as well as corporate. For a platform
that processes customer geometry, this is an **architecture requirement**:
classification has to be a machine-readable attribute enforced at the data layer,
travelling with every derived file.

---

## Hygienic equipment — food, beverage, pharmaceutical

**Afraid of:** contamination reaching a consumer.

**The trap:** *the findings are about geometry.* Almost uniquely among audits,
the inspector runs a hand along a weld, looks for a crevice, checks whether the
vessel drains, and looks for threads on a product-contact surface. Material
declarations matter, but **the shape is the hazard**.

What they check, in order:

- Does every product-contact surface **drain**? No horizontal ledges, no
  un-drained low points.
- Any **crevices, dead legs or lap joints**? Continuous full-penetration welds
  ground smooth; dead legs within the permitted length-to-diameter limit.
- **Product-contact surface roughness**, verified on the finished surface
  *including welds* — which are the rough part, and the part usually never
  measured.
- **Exposed threads or standard fasteners** on product contact.
- **Cleanability validated on the worst-case geometry actually present**, not on
  a simplified test article.

The best design lever is deletion: identify the hardest-to-clean feature at
design time and remove it. Note also that as-built additive surfaces are
generally unacceptable on product contact without machining or polishing —
porosity is harbourage.

---

## The pattern

Every one of these regimes has the same shape: a fear, an evidence requirement
that follows from the fear, and a trap that catches people whose habits came from
a different fear.

What transfers between them is the discipline — configuration control,
traceability, change impact assessment, contemporaneous records. What does not
transfer is the evidence itself, or the assumptions. The most expensive mistakes
in this document are all made by *competent* engineers applying a correct habit
from the wrong industry.
