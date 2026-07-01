# Harness Log — CadVerify

## Cycle 1 — START (2026-06-28)

**CYCLE GOAL:** honest teardown of the current engine on the repo's real parts + a precisely named
wedge + the locked cost-data source-of-truth decision + a V0 decision layer demoable on those real
parts — i.e. produce the thing that goes in front of the Zoox validator.

**Orchestrator env probe (de-risk before fleet launch):**
- venv OK (Python 3.9; trimesh/numpy/scipy/pymeshfix/fastapi/sqlalchemy import). cadquery absent — not needed (parts are STL).
- Engine verified to run end-to-end on 3 real parts (21 analyzers registered).
- Confirmed toy cost model (`cost_per_cm³ × max(volume_cm³,1)`), and real credibility bugs: vol=0/non-watertight part → confident `pass` + fabricated cost; plastic ECU mount → Inconel-718 CNC-turning rec; matmul divide-by-zero/overflow warnings.
- 107 real parts extracted from `ecu_automotive_batch2.zip`.

**Fleet:** Wave 1 [Teardown ∥ Strategist] → Wave 2 [Architect] → Wave 3 [Builder] → Wave 4 [Validation-Auditor]. Auditor may emit `AUDIT FAILED` → route back to Builder (≤2 repairs).

**Mapping note:** `/outputs/` → `<repo>/outputs/`. This run executes Cycle 1 only and stops at the human-validation gate (Cycle 2 depends on it). No commits.

Status: workflow launched (background).

## Cost-Truth Engine — START (2026-06-29)

**User directive:** supersede generic "decision-layer V1" priority. Make cost a per-shop, glass-box,
SELF-MEASURING source of truth — collapse controllable error (defaults/routing/cycle-time), bind the
irreducible bucket to a shop, and PROVE the residual on held-out real data. Bar: "for YOUR shop, $X ±Y%,
validated within ±Y% across N real parts, every driver editable."
**Honesty guardrail (enforced):** no real ground-truth cost data exists yet → ground-truth loop is built
+ proven with CLEARLY-LABELED STAND-IN data; real ±X% stays PENDING the Zoox session; no fabricated
accuracy claims; held-out (no overfitting); every cost carries drivers + a confidence interval.
**Fleet:** Wave1 [Error-Decomposition] → Wave2 [Calibration ∥ Routing+Physics] → Wave3 [Ground-Truth Loop]
→ Wave4 [Validation-Auditor + Zoox calibration protocol] (≤2 repairs). Workflow w8thuo3n0 (background).
**Note:** also surfaced a live routing bug from user testing — a 170×242×3mm flat panel led with MJF
instead of sheet-metal; routing builder must fix.

## Cost-Truth Engine — END (2026-06-29)

**Fleet result:** 5 agents COMPLETE. Audit PASSED, **0 repairs**. ~870k tokens, 345 tool calls, ~83 min.

**Buckets attacked (orchestrator-verified live):**
- Bucket 1 (default rates, measured ±44–47% + margin=0 low-bias) → **KILLED by per-shop calibration.** Verified: same ECU part $44.13 (generic) → $110.49 (Midwest) → $35.29 (Shenzhen); 19 rates tagged SHOP + sourced; Σ=unit holds. New: `shop_profile.py`, `Provenance.SHOP`, `--shop`, profiles in `backend/data/shop_profiles/`.
- Bucket 2 (routing) → **FIXED.** Root-cause bug: `check_bends` used dihedral<90° but the angle is between-normals (0°=flat), so EVERY part hard-failed sheet-metal → invisible route. Now thin flat parts route to sheet_metal (verified: 0.6mm gasket → "GEOMETRIC ROUTING → sheet_metal 0.85" + reasoning; sheet_metal now costable). Positive geometric router added.
- Bucket 3 (cycle-time constants) → **deliberately NOT rebalanced** (would overfit stand-in refs; belongs to real Zoox cycle data). Honest scope call.
- Bucket 4 (irreducible) → characterized; ground-truth loop measures residual on held-out data.

**Ground-truth loop (auditor-verified):** held-out 8.3% ≈ tuning 7.0% (no overfit), zero leakage, calibration uplift 25.8%→8.3% on unseen parts; **real claimed accuracy = null/PENDING** (n_real=0; stand-in clearly labeled). Per-estimate confidence intervals added. New: `groundtruth.py`, `confidence.py`. 22 GT tests.

**Tests:** cost-truth subset 96 pass (38 verified by orchestrator). Full backend 537 pass / **1 fail** / 5 skip — the 1 failure is an UNRELATED stale frontend test (asserts `app/auth/signup` path moved by the redesign), not a cost-truth regression.

**Deliverable:** `outputs/zoox-calibration-protocol.md` — the 5-step session that produces the FIRST REAL ±Y%.

**Honest residuals → follow-ups:** (a) cycle-time tuning needs real data (Zoox); (b) geometric-route vs cost-cheapest make_now can diverge on borderline parts (both surfaced); (c) `--shop` CLI wants name/path not slug (minor); (d) the cost-truth features (shop profiles, geometric routing, CIs) are backend/CLI — NOT yet surfaced in the web UI; (e) costing tree still untracked in git.

**STOP:** apparatus built + controllable error attacked; real validated accuracy now gated on the Zoox calibration session (data, not code). Handoff updated.

## Cycle 1 — END (2026-06-28)

**Fleet result:** all 5 agents COMPLETE. Audit PASSED with **0 repairs**. ~500k tokens, 130 tool calls, ~44 min.

**Orchestrator independent verification (did not trust self-report):**
- Ran `src.costing.cli` on the ECU mount → real itemized, provenance-tagged decision card; `Σ line_items == unit_cost` printed; crossover ≈583 units; CNC material = Delrin (not Inconel). ✅
- Ran it on the broken MAF adapter (vol=0) → `GEOMETRY INVALID — No cost produced`. **Headline teardown bug confirmed dead.** ✅
- Re-ran gate suite independently → **17 passed in 168s** (exit 0). ✅

**Criteria moved:** [buildable] "honest teardown" → DONE; [buildable] "V0 decision layer demoable on real parts" → DONE.
**Backlog closed:** toy-cost replacement (glass-box itemized cost), broken-geometry G1 gate, sane routing (no Inconel-on-plastic / no turning-on-bracket).
**New backlog → Cycle 2 (deferred behind gate):** decision-sentence coherence fix (#7, top), AM build-nesting, min-charge floor, region-multiplier split, tooling cavity/complexity, accuracy-validation harness.
**Gate routed:** Human validation — Zoox Head of Manufacturing demo. Artifact: `outputs/validation-packet.md`.

**PROGRESS CHECK:** moved ≥1 criterion (2) AND closed real backlog (3 items) → PASS, not a STALL.
**LOOP decision:** Cycle-1 exit gate is HUMAN. Special rule = do not build past V0 until validator sees it. → **STOP. Hand off for Zoox demo. Awaiting outcome to set Cycle 2.**

## Cycle 2 — START (2026-06-28)

**User directive:** "continue on until it's bug-free and fully production working." → lifts the Cycle-1
"don't build past the gate" hold; drive [buildable] backlog autonomously, no per-decision check-ins.
Honest ceiling restated to user: external [gate] items (human cost-engineer accuracy sign-off,
security/export/procurement) cannot be closed by code → bundled into a FINAL HANDOFF at the end.

**CYCLE GOAL:** harden V0 → V1 — fix all 8 auditor weaknesses (esp. #7 decision-sentence coherence,
#2 AM build-nesting, #3 min-charge floor, #4 region-multiplier split, #5 tooling model) + build an
accuracy-validation harness producing MEASURED per-process error bands vs local independent ground truth.
**Fleet:** Wave1 [V1 Fix-Spec Architect] → Wave2 [Builder] → Wave3 [Accuracy Harness] → Wave4 [Validation-Auditor] (≤2 repairs). Workflow launched (background, wfq9tt2cc).

**Planned subsequent cycles (autonomous):** C3 CAD ingestion robustness (STEP/IGES — may BLOCK on cadquery/OCP env; report honestly) + report/API wiring (POST /validate/cost); C4 productionization (reliability, observability, tests, CAD-as-IP, error handling). Then FINAL HANDOFF (DONE-PENDING-GATES).

## Cycle 2 — END (2026-06-28)

**Fleet result:** 4 agents COMPLETE. Audit PASSED, **0 repairs**. ~664k tokens, 160 tool calls, ~82 min. Tests 17 → **36**.

**All 8 V0 weaknesses fixed** (verified by auditor + orchestrator spot-check):
coherence (#7), AM build-nesting (#1/#2), min-charge floor (#3), region split (#4), tooling cavity/complexity (#5), DFM-fail headline (#6), per-lot setup (#8).

**Orchestrator independent verification:** ran CLI on ECU mount → headline "Make by mjf $44.13 at qty 50" **==** "@ qty 50 → mjf $44.13 (recommended)" — coherence bug confirmed dead; DFM-fail processes demoted to "cheaper if redesigned." Broken MAF → still GEOMETRY_INVALID. `test_costing_model.py` → 12 passed. ✅

**Accuracy harness (honest, not a rubber stamp):** 202 comparisons vs independent local references, 82% in-band. CNC 100% in-band, IM 100%, nested powder-bed good. **Reported FAIL on its own ±60% bar for serial AM (FDM +75%, SLA +61% high)** rather than hiding it.

**Criteria moved:** [buildable] "Decision V1" → largely DONE (coherent, traceable, weaknesses fixed). [buildable] "Accuracy-validation harness w/ documented error bands" → DONE (measured, honest).
**New residuals → Cycle 3:** (R1) high-qty AM lead-time is absurd (mjf @ qty 5000 = 744–1382 days, single-machine serial assumption); (R2) serial-AM (FDM/SLA) cost +60–75% high — no build-plate nesting on serial processes. (R3, → handoff) bands-not-quotes: real accuracy needs supplier quotes (external/gated).

## Cycle 3 — START (2026-06-28)

**CYCLE GOAL:** "Service + residual correctness" — (1) fix R1 high-qty AM lead-time (realistic parallel-capacity model, no multi-year nonsense) and R2 serial-AM cost bias (legitimate build-plate XY nesting for FDM/SLA; bureaus nest on the bed), re-run accuracy harness to confirm FDM/SLA lands in band; (2) wire the decision layer into the API as `POST /validate/cost` with auth/kill-switch/structured errors + an endpoint test.
**Fleet:** Wave1 [Architect] → Wave2 [Builder: costing residuals + accuracy re-run] → Wave3 [Builder: API endpoint] → Wave4 [Validation-Auditor] (≤2 repairs). Workflow launching (background).

## Cycle 3 — END (2026-06-28)

**Fleet result:** 4 agents COMPLETE. Audit PASSED, **0 repairs**. ~652k tokens, 234 tool calls, ~56 min. Tests 36 → **48**.
**Orchestrator independent verification:** ECU mjf @ qty 5000 lead time 744–1382 d → **55–103 d** (capacity "6 machines × 22 hr/day [DEFAULT]" shown inline); `test_cost_api.py` → **8 passed**; network probe → outbound HTTPS works (github/printables/huggingface 200). ✅
**Criteria moved:** R1 (AM lead-time) + R2 (serial-AM cost bias) FIXED; accuracy C2 FAIL→PASS, Overall PASS. [buildable] "Output/report + API" → DONE (`POST /api/v1/validate/cost`, auth+kill-switch+structured errors, no DB persistence, zero egress).

## Cycle 4 — START (2026-06-28)

**User direction:** build a ground-truth LABELING system; tool lives in the existing frontend (Three.js viewer); corpus = not the 107 hobbyist parts but "everything" → gather a large DIVERSE corpus autonomously ("full ontology"). "Fully autonomous from your end."
**Honest reframe (told to user):** corpus = real, openly-licensed, provenance-logged parts (HF datasets/Thingi10K/ABC), bounded (~hundreds–low-thousands, diversity-balanced), NO synthetic/fabricated parts; manufacturing-method labels are HUMAN-applied via the tool (auto-labeling = circular, forbidden); network verified available.
**New [buildable] criterion added:** "Process-routing ground-truth: labeling tool + diverse corpus + routing-accuracy/similarity eval harness." (Producing real labels = a human gate, like the Zoox demo.)
**CYCLE GOAL:** (1) gather a diverse provenance-tracked corpus; (2) `/label` frontend route reusing the Three.js viewer + local label store + backend corpus endpoints; (3) routing-accuracy + k-NN similarity eval harness (smoke-tested; real metrics gated on human labels).
**Fleet:** Wave1 [Architect] → Wave2 [Corpus-Gatherer ∥ Frontend-Labeler] → Wave3 [Eval+Similarity Harness] → Wave4 [Validation-Auditor] (≤2 repairs). Workflow launching (background).

## Cycle 4 — END (2026-06-28)

**Fleet result:** 5 agents COMPLETE. Audit PASSED, **0 repairs**. ~574k tokens, 275 tool calls, ~114 min.
**Orchestrator independent verification:** 667 STL == 667 manifest records (2.6 GB); random parts `sha256(content)==filename` (real, not fabricated); `data/labels.jsonl` ABSENT (0 auto/human labels — circularity avoided); only 6 `SMOKE_SEED` rows (tagged "NOT ground truth") in a separate file; eval `--smoke` runs and prints "human-label gate 0/30 NOT MET — provisional"; `/label` route + `CorpusViewer` + `backend/src/eval/*` present. ✅
**Honest residual (gatherer):** corpus leans additive — openly-licensed molded/cast meshes essentially unavailable without gated datasets (ABC=401, STEP needs cadquery, GrabCAD login). Reported, not hidden.
**Criteria moved:** NEW [buildable] "process-routing ground-truth system" → DONE (tool+corpus+eval). Real routing-accuracy metrics → **human-labeling gate** (≥30 labels).

## Cycle 5 — START (2026-06-28)

**CYCLE GOAL (productionization):** (A) CAD ingestion robustness — honest STEP→mesh attempt via **gmsh** (cadquery/OCP unavailable; BLOCK honestly if gmsh won't install), wired into the parse path + tested on a real open STEP file; (B) **frontend cost-decision surface** — render the `POST /validate/cost` decision in the existing dashboard (processes, $/lead-time, crossover, make-vs-buy, driver breakdown, overrides) so the moat is demoable in-product; (C) **observability + reliability hardening** on the new endpoints (structlog/request-id, error paths, caps/timeouts) + full-suite green.
**Fleet:** Wave1 [Architect] → Wave2 [STEP-Ingestion ∥ Frontend-Cost-UI] → Wave3 [Hardening/Observability + full suite] → Wave4 [Validation-Auditor] (≤2 repairs). Workflow launching (background).
**After C5:** FINAL HANDOFF (DONE-PENDING-GATES).

## Cycle 5 — END (2026-06-29)

**Fleet result:** 5 agents COMPLETE. Audit PASSED, **0 repairs**. ~549k tokens, 230 tool calls, ~54 min. Backend suite 48 → **500 passed / 5 env-gated skips**.
**STEP ingestion NOT blocked (better than expected):** gmsh 4.15.2 installs; real LGPL `eight_cyl.stp` → 24524-face watertight mesh → coherent cost decision. Wired into `_parse_mesh` (off-loop, 504-bounded, `_GMSH_LOCK`). B-rep/GD&T still gated (cadquery/OCP) — honest handoff.
**Orchestrator independent verification:** ran `step_to_trimesh_from_bytes` + engine + `estimate_decision` on the real STEP file → mesh 24524 faces / watertight / 1175cm³ → decision computed; `/cost` route + `CostDecisionCard.tsx` present; auditor's `npm run build` green + 500 tests confirmed. ✅
**Criteria moved:** CAD ingestion → DONE (mesh-level); Productionization → DONE.

## RUN COMPLETE — DONE-PENDING-GATES (2026-06-29)

All `[buildable]` DoD items met or honestly bounded across 5 audited cycles. Remaining items are all `[gate]` (human/third-party). **FINAL HANDOFF written to `outputs/FINAL-HANDOFF.md`** (9 gates: Zoox demo G1, human labeling G2, cost-accuracy-vs-quotes G3, non-additive corpus G4, STEP B-rep G5, security/SOC2 G6, export/residency G7, on-prem/encryption G8, procurement/pricing G9). Loop stops per harness STOP condition: not a STALL (every cycle moved criteria + closed backlog), not CAP (5/6). Honest finish line reached.
