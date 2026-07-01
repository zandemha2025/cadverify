# Cycle 1 — Synthesis & Next Steps

**Date:** 2026-06-28 · **Cycle result:** COMPLETE, audit PASSED (0 repairs) · **Orchestrator independently verified.**

## (a) What was built — and does it meet its bar?

**Built:** a self-contained, read-only `backend/src/costing/` package (11 modules + CLI + 2 test files)
that sits on top of the untouched DFM engine and emits a **glass-box decision card**: itemized
should-cost per process, lead-time range, quantity crossover, and make-vs-buy direction — on the
repo's real automotive parts.

**Independently verified by the orchestrator (not just self-reported):**
- ✅ Runs on real parts in <0.5s; every dollar is provenance-tagged (MEASURED/USER/DEFAULT) with the
  arithmetic shown; `Σ line_items == unit_cost` printed and enforced.
- ✅ **The headline teardown bug is dead** — the broken MAF adapter (vol=0, non-watertight) returns
  `GEOMETRY INVALID — No cost produced` instead of the old confident "sls pass cost=0.2".
- ✅ Routing is sane — CNC material is Delrin (not Inconel 718); turning does not appear on the flat
  bracket; no superalloy on any polymer part.
- ✅ Real crossover + make-vs-buy decision ("make by FDM ≤ ~583 units; tool injection molding above").
- ⏳ Gate suite (17 tests) re-run independently to confirm the builder/auditor's "17/17".

**Meets its bar?** Yes for an **honest V0**: it never dresses a guess as a fact. It does NOT claim
absolute should-cost accuracy and shouldn't be demoed as if it does. The validation packet
(`validation-packet.md`) is built to read the weaknesses aloud *before* the live run.

## (b) Top 3 next actions (in order)

1. **HUMAN GATE — demo V0 to the Zoox Head of Manufacturing** using `validation-packet.md` (5-beat
   script + weakness list + 10 questions). This is the Cycle-1 exit gate; its outcome defines Cycle 2.
   **Do not build past it.**
2. **(Optional, ~1 short cycle before the demo) fix the one clarity bug** that will read as
   contradictory to a sharp manufacturing person: the headline says "make by FDM ≤ 583" while the
   low-qty per-process recommendation is a *different* process (CNC). Make the headline "make-now"
   process equal the actual low-qty winner. This is cosmetic-but-important; everything else is
   defensible as a stated-band estimate.
3. **Capture the validator's answers** to the 10 questions — especially the CASTOR autopsy and the
   willingness-to-pay / "is this aPriori's job already?" questions — as the Cycle 2 input.

## (c) Next cycle's focus (from remaining [buildable], AFTER the gate)

Cycle 2 is **gated on the demo outcome**. Assuming a "keep going" signal, the highest-leverage
[buildable] items — and the auditor's prioritized weakness fixes — are:
- **Decision V1 accuracy structure:** AM build-plate nesting factor (today AM cost assumes one
  isolated build → small parts over-costed), per-process minimum-charge floor, region multiplier
  split (labor vs material vs tooling), batch-amortized post-process labor.
- **Accuracy-validation harness:** check V0 outputs against real quotes / known machining costs and
  document the actual error bands (turn "±40–60% stated" into "measured vs ground truth").
- **CAD ingestion robustness:** STEP/IGES at buyer fidelity (cadquery/OCP), path to native CAD.
- **Output/report + API:** wire `POST /validate/cost` (stubbed, unrouted in V0).

## Honest bottom line

V0 is a **real, demoable, defensible-as-an-honest-V0 decision layer** — the missing CASTOR/3D-Spark
half, built on the existing engine, with the worst credibility bug fixed. It is **not** a validated
should-cost product; absolute dollars are ±40–60% and a few line-item structures (AM nesting) are
known-rough. That's exactly why the next step is a human who builds cars for a living, not more code.
