# RESUME — Autonomous Orchestration Loop (live)

**Updated 2026-07-04 by Fable (orchestrator).** Directive: full autonomous — Fable orchestrates, subagents build, Fable gates every merge. Continue the loop.

## Current state
- `dev == e0bc64d` (+ Phase C in flight, see below). **`prod == 1b8a174` — STILL PENDING founder promotion** (permission layer blocks `git push . dev:prod`; founder must say "promote it" or add a Bash allow-rule). dev is now MANY gates ahead of prod.
- Suite baseline on dev: **1188 passed / 24 env-only (CADVERIFY_PARTS_DIR corpus: costing_gates 16 + costing_accuracy 8) / 36 skipped.**
- GitHub live + current: origin/dev == local dev. Push `origin dev` after every gate.

## THE THESIS (founder, 2026-07-04) — governs everything now
**CadVerify = makeability VERIFICATION engine.** Can this part be made — on YOUR machines, in materials that survive ITS environment, in how long, at physical RESOURCE cost (owned→marginal, not-owned→acquire)? Market/should-cost price is deliberately secondary ("the red-headed stepchild"). Moats: ground-truth flywheel, owned-equipment marginal costing, system of record. Canonical: `PLATFORM-DNA.md` (repo root) + `outputs/fable-product-strategy.md` §0.5. The Zoox/validation gate is REFRAMED: machine-time/throughput accuracy + operator's own historical data, not shop-quote benchmarking.

## Landed 2026-07-04 (merge 308b919, then docs)
The 41-commit cloud "verification-thesis" branch, gated here (4-lens adversarial: honesty PASS high — flag-off served numbers byte-identical; isolation FAIL→FIXED same-day: /api/v1/machines route collision → machine-inventory remounted at `/api/v1/machine-inventory`, auth-guard now scans ALL routers, cursor 400, env-gate nested-compliance flags defused, honesty-literal test guards; correctness PASS — migrations 0012→0022 cycle clean; no-stub PASS). Contents: machine-inventory model+CRUD+CSV, makeability.py capability/environment engine (PURE, no live consumer until Phase C), W4 governed rate/shop/material libraries + governance flow, W3.5 declared part-context + annualized portfolio, tolerance input, metal-AM/forging/casting/wire-EDM/owned-equipment cost models, oil-&-gas alloy pack, IGES, part-summary scale projection + backfill script, uncertainty ensemble + analogy k-NN (opt-in flags default OFF), Prometheus /metrics, ZIP-DoS fix. **Deploy notes: run `backend/scripts/backfill_part_summaries.py` once per deploy; new flags RATE/SHOP/MATERIAL_LIBRARY_ENABLED, COST_ENSEMBLE_ENABLED, METRICS_ENABLED (all default off); new dep prometheus-client; local venv is py3.9 (CI/Docker 3.12) — keep `from __future__ import annotations`.**
Known accepted notes: batch cost path persists unconditionally (FK need); governance allows self-approve (v1 default — flag before enterprise sale); 5-axis defers to router; force gates need declared force.

## IN FLIGHT
- **Phase C rebuild** (workflow `wf_65edc648-081`): wire verify_part into eligible_processes/cost_breakdown/estimate//validate/cost, machine-specific marginal rate, verdict block on the decision report. Crux: byte-identity-when-unused. The cloud built this once (c13364b) but NEVER PUSHED — worktree lost; rebuilt from `outputs/impl/machine-inventory-verification-spec.md` §10. Builder + 3 verifiers (byte-identity/honesty, isolation, correctness). Gate on return: any FAIL → focused fix agent → re-verify → merge --no-ff → full suite → push origin dev.

## NEXT UP (in order)
1. Gate + merge Phase C.
2. **Phase D**: part_summaries `in_house_makeable` + projection-hook maintenance + scaled triage rollup breakdown + **capability-investment ranking** ("which ONE machine acquisition unlocks the most parts") — spec §10 Phase D; also feeds the design's Triage drill-down.
3. **Design-zip integration**: founder is running Claude Design against `outputs/design/claude-design-audit-2026-07-04.md` (full-coverage audit of all 15 files: verdict map, 9 honesty bugs, salvage index, per-page re-thesis list). When the zip arrives: land on a `design/` branch, wire to the real backend (machine-inventory CRUD, /validate/cost verdict block from Phase C, portfolio/triage, records=cost-decisions, part-context programs, calibration) behind `NEXT_PUBLIC_*` flags, tsc+tests+both builds, adversarial verify, gate. Remember the package.json test-script UNION gotcha.
4. prod promotion (founder) → regenerate validation packet from merged prod under the verification thesis (machine-hours accuracy + operator data; Zoox agenda add: part-in-context rung 2 vs 3).
5. E-now wave 2 leftovers · W4 governance self-approve flag · portfolio-savings at full scale · streaming ingest.

## Design track
`PLATFORM-DNA.md` = the binding thesis for design. `DESIGN-MISSION.md` = register + inventory (register split pending founder: dark cinematic site / light editorial product / kill the TSX "third identity"). Newest on-thesis product design: `Product - Verify.dc.html` in the Claude Design project (light, interactive verdict). Audit: `outputs/design/claude-design-audit-2026-07-04.md`.

## Gating protocol (unchanged)
Feature branch off dev → opus builder (worktree under `<scratchpad>/wt/`) → 3+ adversarial verifiers (distinct lenses) → any FAIL routes back with the exact defect → merge --no-ff → full suite (accept ONLY the 24 env fails) → push origin dev (+prod when unblocked). Builders never merge/push. No fabricated numbers; validated only from measured residuals; DEFAULT + `[assumption, not shop-validated]` on every new magnitude.
