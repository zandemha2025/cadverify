---
title: "Subtractive machining — milling, turning and EDM"
domain: processes
audience: "Designers routing to CNC; reviewers checking a machined part"
sources: [sandvik_machining, machinerys_handbook, shop_practice_machining, asm_handbook, iso_286]
provenance: DEFAULT
---

# Subtractive machining

Covers `cnc_3axis`, `cnc_5axis`, `cnc_turning`, `wire_edm`.

## The physics in one paragraph

A rigid, rotating, finite-diameter tool is pushed into a rigidly held workpiece
and shears material away as chips. Every design rule that follows comes from one
of four facts: the tool has a **radius**, it is **cantilevered** so it deflects,
it approaches from a **direction**, and the **chips must leave**.

---

## What good looks like

- **Two setups, maybe three.** Features grouped onto as few faces as possible,
  with the datum scheme carried consistently across the flip.
- **Internal radii sized to real tools**, generously — above the tool radius, not
  equal to it, and consistent across the part so one tool does many corners.
- **A clear, deliberate workholding plan.** A flat pad, a pair of parallel faces,
  or a designed sacrificial tab that gets machined off in the last operation.
- **Two or three tight features and the rest at a general class**, with the tight
  ones on the same datum reference frame and, ideally, in the same setup.
- **Standard everything** — drill sizes, thread sizes, stock thicknesses. A hole
  at Ø6.0 costs less than a hole at Ø6.13 for reasons that have nothing to do
  with geometry.
- **Chamfers and radii that a deburring operator can reach.**
- **Wall heights within about 15× thickness**, and pockets within about 3× the
  diameter of the tool that fits their corners.

## What bad looks like

- **Sharp internal corners.** No rotating cutter makes them. The part is either
  quietly re-radiused by the shop — changing geometry you designed — or it needs
  EDM, a separate process with its own setup and price.
- **Deep narrow pockets.** A 40 mm deep pocket with R1.5 corners forces a 3 mm
  tool at 13:1 reach. Geometrically legal; economically absurd.
- **Features on five faces.** Each new face is a setup, a fixture, a re-datum,
  and a tolerance stack. Setup count usually predicts cost better than feature
  count.
- **Blanket tight tolerance.** The largest avoidable cost on most machined parts,
  and invisible in the geometry.
- **Nothing to hold it by.** A topology-optimised bracket with no planar face is
  a fixturing project before it is a machining job.
- **Tolerances between features made in different setups.** Physically hard, and
  usually not what the function needed anyway.
- **Modelled thread helices** instead of a callout. Slower to process, sometimes
  wrong, and never how a shop makes a thread.
- **Deep holes with position tolerances.** Drills wander; a deep hole with ⌖0.1
  is two problems, not one.

## Expert heuristics

**Count the setups first.** Before looking at any feature, work out how many
orientations the part must be presented in. That number, times fixturing effort,
usually dominates the estimate.

**Find the one feature that decides the routing.** Most parts have exactly one —
an internal undercut forcing 5-axis, a bore tolerance forcing a grind, a wall
thinness forcing a wire-EDM finish. Everything else follows from it.

**Radii bigger than you think.** A larger internal radius admits a larger tool,
which is stiffer, cuts faster, and leaves a better finish. It is one of the very
few changes that improves cost, quality *and* lead time at once.

**Check reach with the holder, not the tool.** Collisions in real shops are
holder collisions. A tool that reaches on paper and a holder that fouls the part
is a re-quote.

**Look at the stock, not the part.** Gross mass drives material cost, and on
titanium or nickel alloys it can dominate everything else. Ask what billet this
comes out of.

**Assume the shop will change what it cannot make.** Under time pressure,
un-makeable details get quietly adjusted. A DFM finding surfaced before release
is a conversation; the same finding discovered at first article is a
nonconformance.

## Turning specifics

The workpiece, not the tool, is the flexible element. Beyond about 3× diameter
unsupported it needs a tailstock; beyond about 8× a steady rest or a
sliding-head machine. A slender bar bows away from the insert, producing a
barrel-shaped diameter that springs back — the measured error is not where the
tool was.

Design in: relief grooves at shoulders (a tool cannot make a sharp internal
corner at a shoulder any more than a mill can), consistent radii so one insert
does the whole profile, and a way to hold the second end.

## Wire EDM specifics

The wire is a straight line. Wire EDM produces **ruled surfaces** — profiles
straight or tapered through the stock. It cannot produce a blind pocket floor,
and every internal profile needs a start hole.

Where it is the right answer: sharp internal corners, very thin walls that would
chatter under a cutter, and hard materials **after** heat treatment — cutting
hardened tool steel is where EDM earns its cost.

The thing that gets missed: every EDM cut leaves a **recast layer** — resolidified
metal with tensile residual stress and micro-cracks. On a fatigue-loaded or
sour-service surface that layer is a crack starter. Critical surfaces need skim
passes and often removal of the recast layer entirely. It is a surface-integrity
requirement that never appears in the geometry and is a classic aerospace and
oil-and-gas audit question.

## Tolerance reality

Rough guidance, to be replaced by the shop's own capability the moment it
exists:

| Feature | Routine | Tight (costs more) | Hard (another process) |
|---|---|---|---|
| Linear, milled | ±0.1 mm | ±0.025 mm | ±0.01 mm |
| Bore diameter | H8 | H7 | H6 and below → grind or hone |
| Flatness over 100 mm | 0.05 mm | 0.02 mm | 0.005 mm → grind or lap |
| Surface finish | Ra 1.6–3.2 µm | Ra 0.8 µm | Ra 0.4 µm and below → grind/polish |

Two rules of thumb worth more than the table: tolerances **between setups** are
roughly one class worse than tolerances within a setup, and any tolerance
requiring a process the shop does not own is not a tolerance, it is a
subcontract.

## What an auditor asks about a machined part

- Which setup made which characteristic, and how is that traceable?
- Is the CMM datum scheme the same as the functional datum scheme?
- For sour service: was hardness surveyed on base metal, weld **and** HAZ?
- If EDM was used on a critical surface, what happened to the recast layer?
- Cutting fluid and cleanliness — especially for medical and vacuum
  applications, where residues are part of the acceptance argument.
