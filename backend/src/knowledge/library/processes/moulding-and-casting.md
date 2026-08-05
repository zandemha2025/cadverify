---
title: "Moulding and casting — injection, die, investment and sand"
domain: processes
audience: "Designers routing to a tooled process; reviewers checking tooling cost"
sources: [shop_practice_moulding, nadca_standards, sfsa_casting, boothroyd_dfma, asm_handbook]
provenance: DEFAULT
---

# Moulding and casting

Covers `injection_molding`, `die_casting`, `investment_casting`, `sand_casting`.

## The physics in one paragraph

Molten material flows into a cavity, freezes, and is removed. Three consequences
govern everything: **flow needs a path** (thin sections resist it and the front
eventually stops), **freezing shrinks** (and shrinkage is only uniform if the
section is), and **the part must come out** (hence draft, and side actions for
anything that will not release along the draw).

The fourth, commercial, consequence: **the tool is the product**. It is a
precision machined object, often more complex than the part, with a long lead
time and a fixed cost. Every formative decision is a volume bet.

---

## Injection moulding

### What good looks like

- **A single uniform nominal wall**, roughly 1.5–4 mm for engineering
  thermoplastics, held everywhere function permits.
- **Stiffness from ribs, not thickness.** Ribs at 50–65% of nominal wall, base
  fillets at 0.25–0.5× nominal wall, spacing at least 2× nominal wall.
- **Draft on every face parallel to the draw** — start at 1° per 25 mm of draw,
  more on internal faces, and about 1.5° extra per 0.025 mm of texture depth.
- **Cored bosses supported by gussets**, standing slightly off the floor, never
  solid cylinders on a thin wall.
- **Features shut off through the wall** so they release in the draw, rather than
  demanding a slide.
- **Gate location considered at design time**, because it decides flow length,
  weld-line position and where the cosmetic blemish lands.
- **Generous radii everywhere.** Sharp corners are stress concentrators in the
  part and hot spots in the tool.

### What bad looks like

- **Zero draft.** The part shrinks onto the core and grips it; ejection scuffs,
  whitens or sticks it. The most common reason a moulded design fails first
  shots, and tool rework costs weeks, not just money.
- **A solid 8 mm boss on a 2.5 mm floor.** Sink on the show face, a void in the
  core, and a long cycle.
- **Ribs as thick as the wall** behind a Class-A surface — a visible sink line
  the tool cannot fix.
- **Four side actions on a low-volume part** to preserve a cosmetic detail.
- **A 6 mm wall "to make it strong".** Cycle time scales roughly with the square
  of wall thickness, and the thick core voids anyway.
- **Tolerances that ignore shrinkage variation.** Shrinkage varies with material
  lot, moisture, hold pressure and cycle; a tolerance tighter than that variation
  is a sorting operation.

### The heuristic that matters most

**Tool complexity, not part complexity, drives moulding cost.** A snap feature
moved so it shuts off through the wall can delete a slide, and with it a
five-figure tooling line item and a recurring maintenance failure mode. This is
where DFM analysis earns its keep, because the geometry looks completely
harmless.

---

## Die casting

Thin, uniform, drafted — more strictly than injection moulding, because metal
fills and freezes far faster.

- Typical wall 1.5–3 mm in aluminium; roughly 1° external draft and 2° internal
  as a starting point.
- **Thick sections trap gas.** The metal front folds over entrapped air, giving
  subsurface porosity that shows up only when the part is machined into or
  pressure tested — a very expensive discovery point.
- Consequently: **do not put a pressure-tight or heavily-machined feature in a
  thick die-cast section.** If it must be pressure-tight, consider impregnation,
  or a different process.
- Parting line, ejector pin positions and gate location are visible on the part
  and should be agreed, not discovered.

---

## Casting (investment and sand)

### The central rule: design a path for solidification

Liquid metal shrinks as it freezes and must be fed from somewhere. Section sizes
should increase monotonically **toward the riser**, so metal freezes progressively
from the thin extremities back to the feeder.

Any thick region isolated behind a thin one freezes last with no feed path and
forms a shrinkage cavity — reliably in the heaviest section, which is usually the
most highly stressed one.

This gives casting its own twist on uniform wall: uniform is good, **tapering
toward the feeder is better**.

### Hot spots hide at junctions

The inscribed-circle diameter at a junction is larger than in either adjoining
member, so the junction has more mass per unit surface area and freezes last. An
X junction of four 10 mm ribs behaves thermally like a ~14 mm section. Cavities
and hot tears form exactly there.

The fix is cheap and structural: **stagger crossing ribs** so one X becomes two
Ts, radius the intersections, and core out heavy junctions.

### Cores must be supportable and removable

A core is a fragile object surrounded by liquid metal and buoyant in it. Every
cored passage needs core prints to locate it and a route for the core material to
come out. A long, slender, single-print core floats and shifts, producing
eccentric walls that pass a visual inspection and fail a wall-thickness
ultrasonic check.

### Tolerance and machining stock

Casting tolerance is coarse — around ±1 mm class for sand casting, tighter for
investment. The correct pattern is: **tolerance as-cast surfaces to the casting
class, and add machining stock to the functional surfaces.**

A drawing that applies machined tolerances to as-cast surfaces is unbuildable as
drawn. The foundry will either quote a large premium or quietly plan a machining
operation nobody priced — which is why cast parts are so often costed wrongly:
the machining afterwards is not counted as part of the casting decision.

### Investment vs sand, honestly

**Investment casting** buys much better surface finish and tolerance, thinner
walls, and finer detail. It costs more per part, needs wax tooling, and has a
size ceiling. It is the right answer for complex, near-net, moderate-size parts
in difficult alloys.

**Sand casting** handles size, is cheap in tooling, and takes almost any alloy.
It gives coarse surface and tolerance and needs generous draft (2–3°) and section.
It is the right answer for large, heavy, geometrically forgiving parts.

---

## What an auditor asks about a cast or moulded part

- **Porosity and its acceptance criteria.** Which class, by what method, against
  which standard? In pressure work under API 6A, radiographic examination is
  required and porosity from shrinkage is a reject.
- **Where is the parting line**, and does the drawing acknowledge the mismatch
  and flash allowance at it?
- **Was the pattern or tool qualified**, and how is pattern wear monitored over
  time?
- **Traceability of the heat**, especially for pressure-containing castings.
- **Machining datums on an as-cast part** — how is a coarse-tolerance casting
  located repeatably for machining? This is a real design question and a common
  source of yield loss.
- **For die castings intended to be pressure-tight**: what is the porosity
  control, and is impregnation part of the accepted process or a rescue?
