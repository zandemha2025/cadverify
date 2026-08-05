---
title: "DFM from first principles — the rules that transfer, and why"
domain: foundations
audience: "Design and manufacturing engineers; the copilot's reasoning backbone"
sources: [boothroyd_dfma, asm_handbook, iso_2768, shop_practice_machining]
provenance: DEFAULT
---

# DFM from first principles

Most DFM material is a list of numbers with no explanation, which makes it
impossible to apply to a case the list did not anticipate. This document is the
opposite: the small number of principles the numbers come from.

If you only remember one thing: **DFM is not a checklist of radii. It is process
selection, part-count reduction, and the discipline of spending tolerance only
where function requires it.** Those three decisions dwarf every geometric detail.

---

## Principle 1 — Cost is decided in design and spent in manufacturing

The design phase is a small share of programme cost and commits the large
majority of it. By the time a supplier quotes, nearly every cost driver is
already fixed: the process family, the tooling, the setup count, the tolerance
distribution, the material.

The practical consequence: **cost-reduction effort applied after release is
applied at the least effective moment.** A DFM engine's real value is not
finding a cheaper supplier — it is telling the designer, while the geometry is
still soft, which decision is the expensive one.

## Principle 2 — The cheapest part is the one that does not exist

Deleting a part deletes its tooling, its inspection, its inventory, its supply
chain, its fasteners and its assembly time. No amount of geometric optimisation
on a part matches deleting it. The classic test — does it move relative to its
neighbour, must it be a different material, must it be separable for assembly or
service? — is still the highest-leverage question in the whole discipline.

This is why DFA usually finds more savings than DFM, and why an engine that only
scores single parts is answering the second question first.

## Principle 3 — Uniform section, everywhere, in everything

The most transferable rule across all 21 processes, because every family
punishes non-uniformity by its own mechanism:

- **Moulding and casting** — thick sections cool last with no feed, so they sink,
  void, or tear. Cycle time scales roughly with the square of wall thickness.
- **Machining** — a thin region next to a thick one deflects differently under
  the same cutting load, so the thin one ends up thinner than modelled and wavy.
- **Powder-bed AM** — cross-sectional area change alters the local thermal mass,
  which changes residual stress and distortion.
- **Sheet metal** — non-uniform thickness means it is not a sheet-metal part at
  all, and the whole cost model is wrong.

Casting adds a twist: uniform is good, but **tapering toward the feeder is
better**, because solidification needs somewhere to run to.

## Principle 4 — Tolerance is the most expensive thing on a drawing

Per character typed, nothing else comes close. Halving a tolerance typically:
moves the part to a slower process or a better machine, adds an operation, adds
inspection, and adds scrap. Often all four.

The discipline:

1. Identify the features that carry a fit, a seal, a load path or an alignment.
2. Tolerance those, from the function, with a real stack-up.
3. Give everything else the general tolerance class and mean it.

The failure mode is a blanket tolerance in the title block, applied to a hundred
and eighty dimensions because it felt safe. It is invisible in the geometry, it
is the largest avoidable cost on most machined parts, and it is one of the few
DFM defects that a purely geometric analysis will never find.

**The companion rule:** never specify a tolerance the measurement system cannot
resolve. A characteristic whose tolerance is tight relative to gage capability
fails MSA no matter how well it is made — a design defect discovered at PPAP,
months late.

## Principle 5 — Design for the tool's access, not for the shape you want

Every process has a direction it works from:

- 3-axis milling sees from +Z, one setup at a time.
- Moulding and casting release along the draw.
- Powder-bed AM builds upward, layer on layer.
- Wire EDM cuts a straight line through the stock.
- Press-brake bending needs the flange to span the die.

Geometry that contradicts the direction is not slightly harder — it needs a
*different process*, an *extra setup*, or a *side action*. These are step
changes in cost, not gradual ones. The cost surface in manufacturing is a
staircase, and DFM is largely the art of staying on a tread.

## Principle 6 — Every setup is a new coordinate system

Features machined in different setups cannot hold tight position relative to
each other, because between them sits a re-fixturing and a re-datum. Two
features that must be precisely related must be made in the same setup — this is
a *design* requirement expressed as a *process* constraint, and it belongs in
the datum scheme.

On low and medium volumes, setup count frequently dominates machined-part cost.
A cost model built only from cutting time systematically under-quotes prismatic
parts and over-rewards changes that reduce cutting time without reducing setups.

## Principle 7 — Standard beats custom, always

Standard tooling, standard stock sizes, standard fasteners, standard threads,
standard tolerance classes. A custom tool has a lead time, a minimum order, a
re-order risk, and a single point of failure. A standard end mill is on the shelf
in every shop on earth.

The cheapest radius is the one matching a tool the shop already owns. The
cheapest hole is a drill size. The cheapest thread is a tapped standard thread,
not a modelled helix.

## Principle 8 — Design for inspection, or you have not designed it

If a characteristic cannot be measured, it cannot be accepted, and the
requirement is decorative. Ask, at design time:

- Can a probe or gage physically reach it?
- Does the datum scheme match how the part will actually be fixtured for
  measurement? (If not, every inspection result is invalid regardless of machine
  accuracy.)
- Is there any method that can see an internal feature — CT, UT, RT — at the
  wall thickness and defect size that matter?

An internal lattice with no feasible inspection method is not a clever design.
It is an un-acceptable one, and it will be discovered at first article.

## Principle 9 — The material must survive the environment before it is a candidate

Environment gates material; material gates process. Doing this in the wrong
order produces a beautifully optimised part in an alloy that cracks in service.
A cheaper alloy that fails sour service is not cheaper — it is a well.

## Principle 10 — Be honest about what you do not know

An assumption presented with the confidence of a measurement is worse than no
number, because it destroys trust in the measurements too. Label defaults as
defaults, show the range where sources disagree, and withhold a number rather
than invent one. In this platform that is the product thesis; in engineering
generally it is just competence.

---

## The order to apply all this

1. **Function** — what must this part actually do?
2. **Part count** — must it exist at all, separately?
3. **Environment** — what world must it survive?
4. **Process family** — given volume, material and geometry.
5. **Gross geometry** — uniform section, draft, access direction, holdability.
6. **Tolerance and finish** — only where function demands.
7. **Features** — radii, holes, threads, to standard tooling.
8. **Inspection and evidence** — can it be measured, and can it be proven?

Working out of order is the most common way an experienced engineer still
produces an expensive part: beautiful features on a part that should have been
two parts, in a process that should have been a different one.
