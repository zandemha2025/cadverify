# PLATFORM DNA — what CadVerify IS (design to this)

**Updated 2026-07-04 (founder's verification thesis). This file SUPERSEDES any framing — in DESIGN-MISSION.md or anywhere else — that leads with should-cost, price, specimens, or ceremony. Where documents disagree, this one wins.**

## The thesis in one sentence
CadVerify is a **makeability VERIFICATION engine**: drop in a part, declare the world it must survive, and a deterministic engine answers — *can this be made, on your machines, in materials valid for that environment, in how long, and at what physical resource cost* — with every number carrying provenance.

## The question hierarchy (the product IS these questions, in this order)
1. **Can it be made at all?** Geometry against process physics — printing, CNC, casting, forging, any capacity.
2. **Can YOU make it?** Against your declared **machine inventory** (each machine: type, build envelope, materials, rate, throughput). The answer is specific: "Yes — on your Machine X" or "No — exceeds the envelope of every machine you own; you'd need ≥ Y build volume."
3. **In what materials?** Only those that **survive the part's environment** — pressure, temperature, corrosion/sour service, medium. Environment-invalid materials are filtered out, visibly ("makeable — but your requested aluminum fails sour service; these NACE-compliant alloys pass").
4. **How long / what resources?** Machine or print hours, material mass.
5. **What does it cost in RESOURCES?** Material mass × price, hours × *your own* rate; machine owned → **marginal cost**; not owned → acquisition consideration. **NOT a market price.** "What a shop would charge" is deliberately secondary — the founder's words: the red-headed stepchild.
6. **At inventory scale:** the same verification over thousands-to-millions of parts, triaged into honest buckets (makeable in-house / makeable outside / needs new capability / not makeable).

## The moats (make these visible and beloved)
1. **The ground-truth flywheel** — reality comes back (real hours, real outcomes), bands flip from dashed-assumption to solid-measured. `validated` means *measured*, never asserted. This is the Hallmark moment.
2. **Owned-equipment marginal costing** — the customer's own machines as first-class, designed objects. Nobody else answers "on *your* equipment."
3. **System of record** — every verification is a keepable, shareable, provenance-carrying artifact; the org's make-vs-buy memory.

## The DNA strands (unchanged, non-negotiable)
- **Deterministic + conversational (CUI):** you *talk* to the engine; every answer is an engine-computed artifact; the copilot structurally cannot hallucinate numbers. The UI never offers a question the engine can't compute.
- **Provenance on every number:** MEASURED / SHOP / USER / DEFAULT chips; tap any number, see its source.
- **Honesty as craft:** `validated: false` designed beautifully; withheld numbers instead of fake ones; honest empty states; assumptions labeled `[assumption, not shop-validated]`.
- **The part as hero object**, in its world: program → assembly → **environment** (the environment declaration is part of part-in-context — the spec is where verification starts).
- **Register:** light & editorial; beauty from geometry, motion, light — a modern platform, not material metaphors.

## Why "Every part enters as a specimen — measured, routed, and staged before a dollar is computed" is WRONG
It makes the dollar the destination and the part a museum piece. Wrong on both counts: the dollar (price) is secondary, and the part isn't here to be admired — it's here to be **interrogated against reality**. The correct north star:

> **"Every part arrives with a question: can this be made — on your machines, in materials that survive its world — and what will it really take?"**

The drama of this product is not pricing ceremony. It is **the verdict**: watching a deterministic engine walk a part through envelope fit, environment-valid materials, process physics, hours, and resource cost — and answer with receipts.

## The hero loop (design this flow)
**Drop the part → declare its world** (environment + program context, or inherit it) → **the Verdict** (capability-match walk: envelope ✓/✗ per machine, material set filtered by environment, feasible processes, time) → **resource cost** (hours + mass + ownership: marginal vs acquire) → **decide** (make in-house / make outside / acquire capability / redesign) → **send back reality** → the engine sharpens (the Hallmark).

## Signature-moment deltas vs DESIGN-MISSION.md (that file's inventory still applies; re-aim it)
- The #1 moment is now **The Verdict** — the verification walk, not the cost decision card. The should-cost card becomes one artifact *inside* the verdict.
- Add **Your Machines** — the org's machine inventory as a designed surface (each machine a real object with envelope, materials, rate; the thing verdicts point at).
- Add **The Environment Door** — declaring the world the part lives in (pressure/temp/medium/sour service) as a first-class, beautiful input moment; it drives everything downstream.
- Add **Triage at Scale** — the whole-inventory board: an Aramco-scale catalog collapsing into honest makeability buckets you can drill.
- Keep: the part hero stage, the context zoom-out, the Crossover, the Hallmark, honest states, the catalog, the portfolio (now annualized via declared volumes).
