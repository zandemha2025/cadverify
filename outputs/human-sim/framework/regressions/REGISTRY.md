# CadVerify — Human-Sim Regression Registry (Phase 8)

Every confirmed bug becomes a permanent scenario. Each future human-sim run replays
these in addition to new flows. Grows only. `status`: open | fixed | honest-gate.

## Format
`id · discovered · persona/flow · severity · repro → expected vs actual · fixing-commit · replay-assertion · status`

---

## Historical finds (this session, pre-framework — fixed, now regression-guarded)

- **R01** · periodic-surface STEP parse (`nist_ctc_04`) → generic 400 · engine · fixed (gmsh retry ladder) · replay: the part parses or fails with an honest message · **fixed**
- **R02** · mesher rung-0 grind >60s → 504 end-to-end though unit tests passed · engine · fixed (per-rung wall-clock cap) · replay: cold large periodic part returns < budget · **fixed**
- **R03** · preview-mesh 504 on cold large periodic part (burst re-parse) · W1 · fixed (single-flight parse dedup) · **fixed**
- **R04** · best_process material-BLIND (resin for a metal part) · W1/W3 · fixed (material-aware rank_processes) · replay: metal part never routes to a resin process · **fixed**
- **R05** · COTS fix engine-only, not rendered · W3 · fixed (COTS card in assembly panel) · **fixed**
- **R06** · fab fallback mis-models fasteners (nut as sheet-metal, bolt as aluminium) · W3 · fixed (drop machined figure for COTS + honest note) · **fixed**
- **R07** · ≈M16 bolt threading into ≈M12 nut in one joint (mate incoherence) · W3 · fixed (mate reconciliation, commit c6db722) · replay: bolt & nut in a joint share one nominal · **fixed — LIVE re-verified in the baseline (≈M12 both)**
- **R08** · perf pre-warm must NEVER change the answer · W1 · guard (commit be820c2) · replay: cube.step cost/geometry fingerprint is byte-identical with PARSE_POOL_PREWARM on vs off, and no rung/cap/cache is touched · **fixed — invariance is the regression assertion; latency is a floor, not a bug**
- **R09** · DFM "Process physics" ROUTE PICK badged the geometry-blind /validate best_process (DLP Resin) for a STEEL part, contradicting the CNC-3-Axis cost panel on the same screen · W1/W3 (live re-score) · fixed (commit ffbff76: reconcile pick to cost.decision.make_now_process / routing.recommended_process when a material is declared; geometry pick relabeled "GEOMETRY PICK") · replay: a steel part never shows a resin ROUTE PICK; the physics pick agrees with the make-now route · **fixed**
- **R10** · status/provenance accents used as small mono labels were sub-AA (amber "issues" #b07818 3.79:1, measured-blue #3b7bb8 4.13:1) · a11y (live re-score) · fixed (commit ffbff76: hue-preserving darken to ≥4.5:1 on both surfaces + tokens.test.ts guard) · replay: every opaque accent clears AA 4.5:1 on #f6f6f7 and #ffffff · **fixed**

## Repair status (2026-07-10 re-score — each verified on screen)
- **F1 → FIXED ✅** identity revision now grounds (72% MEDIUM card → Confirm → saved; torus still no-match). Commit ca05219.
- **F3 → FIXED ✅** input focus ring now `2px solid #6ba6f4`. Commit 73802ab.
- **F4 → FIXED ✅** .txt leads with "Unsupported file type" (minor residual toast noted). Commit e29588e.
- **F5 → FIXED ✅** cost-driver qty reconciles to headline $8.68. Commit 73802ab.
- **F2 → PARTIAL ⚠️ (OPEN, HONEST-FLOOR CHARACTERIZED)** redundant 2s identity pass removed (commit 2c32b2a); pre-warm the spawn pool at boot (commit be820c2) removes the first-request startup tax: first cold /validate/cost 6.66s→5.94s (~0.72s, ~11%), fingerprint byte-identical. Remaining cold verify ~5.9s / assembly 34–58s is real mesh COMPUTE (~3.7s) + costing (~2s) — proven load-bearing: coarser tessellation zeroes NIST volume / breaks watertightness, and gmsh threading perturbs curved parts, so BOTH move the cost answer and are FORBIDDEN. Pre-warm is the only answer-preserving win. This is an honest engineering floor, not a defect: the latency is the price of a MEASURED (not estimated) cost. **Product MIN is bound here (Performance).**

Product overall: 70 → **72** (bound by Performance; Security 75 unexercised is next).

## Live re-score (2026-07-10, commit 6d7547d — real stack, Playwright + vision)
Confirmed the two prior score-cappers on screen and replayed the registry:
- **Accessibility → 4/5.** Both prior caps resolved live: visible cobalt focus ring on
  the auth inputs; neutral muted ink composites ≈4.3–5.3:1. Remaining cap was small
  non-neutral accent labels below AA (amber ≈3.79:1, blue ≈4.1:1) → **fixed R10** (all
  accents now ≥4.5:1, guarded).
- **Performance → 3/5 (honest floor).** Cold cube 11.7s / warm 4.4s / steel 7.9s
  (submit→cost, spanning chained /validate + /validate/cost); pre-warm confirmed active.
  Multi-second cold is the measured-cost floor, not a defect (R08).
- **Regression replay:** F3 PASS · F4 PASS · F5 PASS · **R04 residual found on screen**
  (physics ROUTE PICK showed resin for steel) → **fixed R09**.
- MIN moved off the two caps; next honest bind is the R09/R10 trust+a11y residuals
  (now fixed) then Security (unexercised). Re-score evidence in `outputs/human-sim/rescore/`.

## Baseline run finds (2026-07-09) — open

- **F1** · 2026-07-09 · P2 / W11 identity revision · **major** · repro: onboard `bracket_A.stl`+`identity.csv`, then Verify `bracket_A_rev.stl` (a genuine revision) → expected: an IdentityCard "Looks like your Mounting bracket L · PN-BRK-001 → Confirm"; actual: NO card, "none confident enough to suggest". The flagship parts-master journey can't complete at the baseline confidence threshold. No-fabrication guarantee holds (torus correctly no-match). · fix: tune recall + add an honest low-confidence "closest in your library — confirm?" affordance, keep the no-fabrication rule · **open**
- **F2** · 2026-07-09 · P1/P5 / W1+W3 · **major** · repro: verify `cube.step` → 13.3–22.1s; AS1 assembly → 34s (page-load itself fine ~1.5s) → expected: interactive latency; actual: pervasive multi-second waits taxing every hero-loop touch · fix: profile the `/validate/cost` path (identity retrieval added a full geometry pass; cold gmsh; cache warmth) · **open**
- **F3** · 2026-07-09 · a11y / W12 · **minor** · repro: tab to email/password inputs → expected: visible focus ring (WCAG 2.4.7); actual: `outline:none` + no box-shadow, no visible focus indicator on text inputs (links/buttons OK) · fix: add a visible `:focus-visible` style to inputs · **open**
- **F4** · 2026-07-09 · error-copy / W1 · **polish** · repro: upload a `.txt` → expected: lead with ".txt unsupported"; actual: leads with a misleading "geometry contains a surface" clause before the real reason · fix: reorder the error message · **open**
- **F5** · 2026-07-09 · data-copy / W1 · **polish** · repro: cost drivers panel → expected: driver qty matches the headline qty; actual: drivers read "@qty 100 = $8.72" while headline is "@qty 10,000 = $8.68" · fix: align the driver qty label with the selected qty · **open**
