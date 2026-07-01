# CadVerify — Real-Expert Validation Packet (the queue)

These items **cannot be self-certified by the build team.** Correctness of cost/routing
numbers, n=0 accuracy, SOC2, and "looks like real software with real users" are
real-expert / real-data gates. The code-level remediation of F1/F2/F3/F5 is verified and
closed (see `teardown-verify.md`); what remains here is **judgment we are not entitled to
make.** Nothing below is marked "done" by us.

**Primary expert:** **Zoox Head of Manufacturing** (cost/routing correctness on his real
parts). Secondary gates (F4/F6/F7) noted at the end with their proper owners.

---

## Q-F2 — Is the routing (process choice) right? — Zoox Head of Manufacturing

**What we proved ourselves (structure, not correctness):** routing never headlines a
process the engine's own DFM hard-fails (0 violations / 105 real automotive parts); the
rotational decision uses the *same* inertia-eigenvalue test as the DFM gate at the same
0.15 tolerance, so routing and DFM can't contradict.

**What only he can say:** whether the *named* process is the one a real shop would pick.

**What to show him (on HIS parts — bring 5–10 real Zoox parts, mixed archetypes):**
- For each part: the **Routing & DFM** tab — the archetype + recommended process + the
  measured drivers that decided it (e.g. "axisymmetric cross-section: axis 21mm × Ø21mm →
  CNC turning"), beside the DFM matrix (per-process pass/issues/fail with named blockers).
- The five archetype buckets we route to: `sheet_panel→sheet_metal`,
  `rotational→cnc_turning`, `thin_wall_enclosure→injection_molding/MJF`,
  `prismatic_block→CNC`, `bulk_solid→MJF/CNC`.
- A deliberate counter-example: a printed-for-3DP cover where injection molding DFM-fails
  for draft — show that we headline the **DFM-clean** make-as-is process and surface the
  molding route only as the *at-volume "if redesigned"* crossover.

**Exactly what to ask:**
1. "For each of these parts, is the headlined process the one you'd actually quote? Where
   would you route it differently, and on what feature?"
2. "Is the rotational/turning call right — are any of these *not* turnable in practice
   (workholding, L/D, interrupted cut) even though they're axisymmetric?"
3. "Is 'cost the molding route but flag it design-for-process' the right behavior, or
   should we hard-drop processes that fail DFM as-modeled?"

**Pass bar:** he agrees the process call is defensible on ≥80% of his parts, and flags no
case where we'd recommend something a shop would reject outright.

---

## Q-F1 — Are the per-shop numbers in the right range? — Zoox Head of Manufacturing

**What we proved ourselves:** the number is shop-calibrated and moves with the profile
(object.stl qty10: generic $7.50 / Midwest $14.14 / Shenzhen $5.68), the override loop
re-costs ($14.14 → $33.52 on labor 52→150), Σ line-items = unit_cost, every driver is
provenance-tagged (SHOP/DEFAULT/USER) with a verbatim source string, and the band is an
honest ±40–60% "assumption-based, not yet validated."

**What only he can say:** whether those dollars are in the right ballpark for a real shop.

**What to show him:**
- The **Glass Box** tab on a real part: every cost driver expanded to its source string
  (material = volume × density × $/kg × scrap; machine = cycle-time × rate ÷ utilization ×
  overhead; labor; setup; amortized tooling), with SHOP-bound rates tagged and DEFAULT
  gaps visible.
- The **make-vs-buy crossover** chart: make-now process below N units, tool up above N,
  with the crossover quantity and the "if redesigned for molding" caveat.
- The **same part under two shop profiles** (Midwest US vs Shenzhen CN) so he sees the
  calibration actually re-prices labor/machine/material, not just relabels.

**Exactly what to ask:**
1. "On a part you've recently quoted, is our unit cost within your ±X%? Which driver is
   off, and by how much?" (This is also the **F4 / n=0 → real-±X%** data-collection step.)
2. "Are the *rates* we defaulted (machine $/hr, utilization, overhead, scrap, MRR cycle-
   time models) sane for your equipment? Which should be SHOP-bound, not DEFAULT?"
3. "Is the crossover quantity (make-vs-buy direction) right — that's the decision we claim
   is robust to the ±40–60% absolute-cost band?"

**Pass bar:** unit cost within his stated tolerance on real quoted parts (feeds the
validated confidence band), and the crossover direction matches his intuition.

**How to capture it:** run his parts through the authed product (or the CLI `--shop`),
export the glass-box report, and record his real quote per part → this is the held-out
ground truth that converts the hatched "assumption band" into a solid "validated on N of
your parts" interval. **Do not print any accuracy figure until this exists.**

---

## Remaining real-expert / real-data gates (out of scope for code)

- **F4 — n=0 → real ±X% accuracy.** We currently state an *assumption* band (±40–60%) and
  explicitly label it "not yet validated, no ground truth yet." Closing this requires the
  **Zoox real-quote session above**: real costs on held-out parts → a measured error band.
  Owner: Zoox Head of Manufacturing (data) + cost team (fit). **Not closeable in code.**
- **F6 — SOC2.** Security/compliance posture (the product advertises an ITAR/AS9100/CAD-as-
  IP local path) needs a real **SOC2 audit** by a qualified auditor. Owner: security/
  compliance. **Not closeable in code.**
- **F7 — "looks like and works like real software" with real target users.** Needs a
  **usability/credibility pass with real buyers / cost engineers** (the named senior bar),
  not a self-review. Owner: design + real target users. **Not closeable in code.**

---

## One-line status for the queue

| Item | Self-verified | Queued to | Gate |
|------|---------------|-----------|------|
| F2 routing process correctness | structure (0/105 contradictions) | Zoox Head of Mfg | is the process right? |
| F1 per-shop number correctness | number moves + invariants | Zoox Head of Mfg | is the cost in range? |
| F4 n=0 → real ±X% | honest assumption band only | Zoox real-quote session | measured accuracy |
| F6 SOC2 | n/a | external auditor | compliance |
| F7 real-software credibility | n/a | real target users | usability/trust |
