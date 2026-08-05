---
title: "Manufacturing 101 — the three families and how to choose between them"
domain: foundations
audience: "Engineer competent elsewhere, new to process selection"
sources: [boothroyd_dfma, asm_handbook, iso_astm_52900, machinerys_handbook]
provenance: DEFAULT
---

# Manufacturing 101

Every one of the 21 processes this engine models belongs to one of three
families, defined by what happens to the material.

| Family | What happens | The cost you pay | The cost you avoid |
|---|---|---|---|
| **Subtractive** | Start with more material than you need; remove the rest | Time per unit, and the material you threw away | Tooling — a machined part needs no mould |
| **Formative** | Force material into a shape and hold it there while it sets | Tooling, up front, before the first good part | Time per unit — cycles are seconds |
| **Additive** | Build the shape up from nothing, layer by layer | Time per unit, and qualification burden | Tooling *and* the geometry constraints of the other two |

Almost every real manufacturing argument reduces to where the crossover between
these three sits for a given part at a given volume. That is why the crossover
chart is a signature artifact of this product and not a decoration.

---

## The physics, family by family

### Subtractive — a rigid tool pushes material off a rigid workpiece

Everything that matters follows from that sentence.

- The tool is **rigid and finite**, so an internal corner carries the tool's
  radius. Sharp internal corners do not exist in milling.
- The tool is **cantilevered**, so it deflects, and deflection grows roughly with
  the cube of unsupported length. This is why depth-to-diameter ratios dominate
  machining DFM.
- The tool **approaches from a direction**, so anything hidden from that
  direction needs another setup, and every setup adds a re-datum and a
  tolerance stack.
- The **workpiece must be held**, rigidly, against cutting forces — and a part
  with nothing to grip is a fixturing problem that no geometry check reports.
- **Chips must leave**. Most deep-hole and deep-pocket limits are chip-evacuation
  limits wearing a geometry costume.

Where it wins: tight tolerance, excellent surface finish, any material you can
buy as stock, no tooling, and a first part next week. Where it loses: high
volume against a mould, and buy-to-fly ratio on expensive alloys.

### Formative — material flows into a cavity and freezes there

- **Flow needs a path.** Thin sections resist flow; the melt front cools as it
  travels and eventually stops. This bounds how far you can fill at what wall.
- **Freezing shrinks.** Every formative process shrinks on cooling, and shrinkage
  is only uniform if the section is. Non-uniform section is the root cause of
  sink, voids, warp and hot tears — one physical mechanism with four names.
- **The part must come out.** Hence draft on every face parallel to the draw, and
  side actions for anything that cannot release along it.
- **Tooling is the product.** The mould or die is a precision machined object,
  often more complex than the part. Its cost is fixed and its lead time is long,
  so formative processes are a volume bet.

Where it wins: volume, decisively — the marginal cost of a moulded part is
pennies. Where it loses: anything below the volume that amortises the tool, and
anything that needs a change after the tool is cut.

### Additive — the process makes the material as it makes the shape

This is the sentence people miss, and every AM surprise follows from it.

- There is **no bulk material with known properties**. Properties come out of
  the thermal history of the build: orientation, scan strategy, layer thickness,
  and where on the plate the part sat.
- **Anisotropy is structural**, not a defect. In powder bed and FDM alike, the
  build direction is the weak axis.
- **Each layer needs support beneath it**, which is why overhang angle governs
  geometry and why supports are a design output, not a slicer detail.
- **Residual stress accumulates** as each layer contracts against a rigid
  substrate, and in stiff flat parts it can exceed yield.
- **Surface is as-built and rough**, worse on down-skins, so any functional
  interface needs machining stock modelled in.

Where it wins: internal complexity that no other process can make, part
consolidation, lead time without tooling, and buy-to-fly on expensive alloys.
Where it loses: simple parts (machining wins decisively), volume (moulding wins
decisively), and anywhere the qualification burden exceeds the benefit.

---

## Choosing: the questions in order

Ask them in this sequence, because each one can end the conversation.

**1. Can it be made at all?**
Is the geometry expressible in *any* process? Non-manifold geometry, enclosed
voids with no evacuation, features smaller than any tool or melt pool — these
fail everywhere.

**2. Can it be made by a process you can reach?**
Envelope first: does the part fit the machine? Then material: does the process
run the alloy you need? A perfect process you cannot access is not an answer.

**3. Does the material survive the service environment?**
Environment gates material before cost gates anything. A cheaper alloy that
cracks in sour service is not cheaper. See
[Materials and service environments](materials-and-service-environments.md).

**4. What volume?**
This is where the three families actually compete, and where the answer usually
flips. A hundred parts and a hundred thousand parts are different questions with
different correct answers and the same geometry.

**5. What tolerance and finish does function actually require?**
Not what the drawing says — what the function needs. Most parts have two or
three features that matter and thirty that do not.

**6. What must be proven, to whom?**
A pressure-containing part at API 6A PSL-3 and a visually identical bracket are
not the same manufacturing problem. Qualification burden is often larger than
part cost and is decided entirely at design time.

---

## Volume, honestly

Rough bands, not thresholds — they move with part size, material and tolerance,
and every one of them should be replaced by the customer's own data the moment
it exists.

| Volume | Usually wins | Because |
|---|---|---|
| 1–10 | Additive, or machining from stock | No tooling to amortise; lead time dominates |
| 10–500 | Machining; investment or sand casting for complex shapes | Soft tooling starts to pay; setup amortises |
| 500–10,000 | Casting, sheet metal, machining with dedicated fixtures | Hard tooling begins to pay |
| 10,000+ | Injection moulding, die casting, forging, progressive-die stamping | Tooling amortises to nothing; cycle time is everything |

The crossover is what matters, not the band. Two processes with different fixed
and marginal costs cross at exactly one quantity, and that quantity is
computable. Telling someone *where* the decision flips is far more useful than
telling them which side of it they are on today.

---

## What experienced people actually do first

- **Ask what it mates with before looking at the part.** The assembly determines
  the datum scheme, which determines which tolerances are real.
- **Ask about volume and life before proposing a process.** A process
  recommendation without a volume is not a recommendation.
- **Ask what happens if it fails.** Consequence class sets the entire
  qualification burden and often the material.
- **Look for the one feature that decides the routing.** Most parts have exactly
  one — an internal undercut, a sealing surface tolerance, a wall thickness. Find
  it and the rest of the analysis follows.
- **Count setups, not features.** On prismatic parts, setup count predicts cost
  better than feature count does.
- **Distrust a part that has no obvious way to be held.** It is the most reliably
  under-quoted geometry there is.
