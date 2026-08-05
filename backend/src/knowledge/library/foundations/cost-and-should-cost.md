---
title: "Cost and should-cost — what a credible estimate is made of"
domain: foundations
audience: "Anyone building, reading or defending a cost number"
sources: [boothroyd_dfma, machinerys_handbook, iatf_16949]
provenance: DEFAULT
---

# Cost and should-cost

## Three different questions people call "cost"

Conflating them is the single most common source of bad manufacturing
decisions.

1. **Should-cost** — a bottom-up engineering estimate of what a part *ought* to
   cost given a process, material, volume and set of rates. An independent
   benchmark used to interrogate a quote.
2. **Marginal cost on owned equipment** — the incremental resources consumed to
   make one more part on a machine you already own: material, consumables,
   energy, and the labour actually spent. Excludes the sunk capital.
3. **Market price** — what a supplier will actually charge, which includes their
   capital recovery, overhead, margin, current utilisation, and their opinion of
   you as a customer.

These answer different questions and **must never be compared directly**. A
supplier quote against a marginal cost is a rigged comparison — one includes
capital recovery and margin, the other does not. Make-versus-buy done that way
always says "make", and is always wrong about why.

---

## The anatomy of a should-cost

```
  material cost           = gross mass × price per kg          (gross, not net)
+ conversion cost         = cycle time × machine+labour rate
+ setup cost              = setup time × rate ÷ lot size       (amortised)
+ tooling amortisation    = tooling cost ÷ programme volume
+ secondary operations    = heat treat, finishing, NDE, assembly
+ scrap and yield loss    = the above ÷ first-pass yield
+ overhead and margin     = if you are modelling a price, not a resource cost
```

Five places this goes wrong in practice:

**Gross versus net material.** You buy the billet, not the part. On aerospace
machined parts the buy-to-fly ratio is routinely 10:1 or worse, and on expensive
alloys the removed material dominates every other term. A model that prices net
mass under-quotes machining catastrophically and biases every process comparison
toward subtractive.

**Setup ignored.** On low and medium volumes setup frequently dominates. A model
built from cutting time alone systematically under-quotes prismatic parts, and
worse, it rewards design changes that reduce cutting time without reducing
setups — the wrong optimisation, confidently recommended.

**Lot size versus annual volume.** They are different numbers and they enter the
model differently. Setup amortises over the **lot**; tooling amortises over the
**programme**. Using annual volume for both makes small-lot production look far
cheaper than it is.

**Form pricing on material.** The same alloy costs multiples more as powder than
as wrought — Inconel 625 is roughly 45 $/kg wrought and roughly 380 $/kg as
powder. Any AM-versus-machining comparison that prices "Inconel 625" without
specifying the form is wrong before it starts.

**Learning ignored, or applied to everything.** Unit conversion cost falls with
cumulative quantity as operators, fixtures and parameters improve — a Wright
curve, typically around 90% per doubling on attended conversion work. It applies
to labour and machine-attended time. **Material never learns.** Applying a
learning curve to material cost is a straightforward modelling error that makes
high volumes look impossibly cheap.

---

## Where cost actually lives, by process

**Machining** — setups, then material (gross), then cycle time, then tolerance.
Tolerance enters twice: once by forcing slower passes and better machines, and
again through inspection and scrap.

**Injection moulding** — tooling, overwhelmingly, until volume amortises it; then
cycle time, which scales roughly with the square of wall thickness. The largest
single tooling driver is **side actions**: each undercut requiring a slide or
lifter adds tool cost, cycle time and a maintenance failure mode. Deleting one
undercut can be worth more than every other design change combined.

**Casting** — pattern or die tooling, yield (risers and gates are metal you melt
and do not ship), and the machining operations the casting tolerance forces.
Cast parts are usually costed wrongly because the machining afterwards is not
counted as part of the casting decision.

**Metal AM** — build time, which scales with the number of layers (part height)
and the area exposed per layer, plus powder at powder prices, plus post-processing
that people forget: stress relief, plate removal, support removal (often manual),
HIP, machining of interfaces, and inspection. **Post-processing routinely exceeds
the print cost**, and it is the term missing from most AM business cases.

**Sheet metal** — the number of bends and the number of tool changes, not the
area. Nesting yield matters on volume. Tolerance across multiple bends stacks
fast, and a tolerance the brake cannot hold silently converts the part to a
machined one.

**Forging** — die cost and die life, material utilisation (flash is scrap), and
the machining afterwards. Forging buys grain flow and integrity; if the
application does not need those, it is an expensive way to make a blank.

---

## What makes an estimate credible

An estimate is credible when a hostile reviewer can trace every number to its
source and reproduce the result. Concretely:

- **Every input carries provenance.** Measured, shop-validated, user-declared, or
  a default — labelled, distinguishably.
- **Assumptions are visible and named.** "Cycle time from a feature-based model
  at 80% spindle utilisation" is defensible. "Cycle time: 14 minutes" is not.
- **Ranges where the input is uncertain**, and a stated basis for the range.
- **Sensitivity is shown.** Which input, moved by 10%, moves the answer most?
  That is where the estimate's real risk lives, and it is usually one or two
  terms.
- **The comparison is like-for-like.** Same volume, same lot size, same tolerance,
  same scope of secondary operations, same inclusion or exclusion of margin.
- **Nothing is called validated until reality confirms it.** An estimate that
  claims the authority of a measurement it has not made is worse than a wide
  honest range.

---

## The crossover is the answer, not the number

Two processes with different fixed and marginal costs cross at exactly one
quantity, and it is computable:

```
  q* = (fixed_A − fixed_B) / (marginal_B − marginal_A)
```

Telling someone *where the decision flips* is far more useful than telling them
which side of it they are on today, because it survives the volume changing —
which it always does. It also makes the estimate falsifiable in a way a single
number is not: a stakeholder can argue with a crossover quantity productively.

Two honesty rules on crossover:

- If unit cost is itself quantity-dependent (learning curves, lot-size steps),
  the naive formula is wrong. Solve for the actual crossing of the two curves.
- If the curves do not cross in a plausible volume range, **say so** rather than
  extrapolating to a crossover at 4 million units that nobody will ever build.

---

## The questions to ask any cost model

1. Gross or net material mass?
2. Are setups counted, and from what — the geometry, or a guess?
3. What lot size, and is it the same one used to amortise setup?
4. What is the material *form*, and is it priced as that form?
5. What secondary operations are in scope, and which were assumed away?
6. What is the first-pass yield assumption, and where did it come from?
7. Does this include margin? Is the thing it is being compared against on the
   same basis?
8. Which single input, if wrong by 10%, changes the answer most — and how
   confident are we in that one?

A model that cannot answer these is not a should-cost. It is an opinion with
decimal places.
