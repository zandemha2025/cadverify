# RESUME — Autonomous Orchestration Loop (live)

**Written 2026-07-03 by Fable (orchestrator).** Directive: **full autonomous** — Fable orchestrates, subagents build, Fable gates every merge, routes back failures, keeps the pipeline full, does NOT stop to ask the user between beats. Continue the loop.

## Current prod
- `prod == dev == 8b7529e`. Backend suite: **768 passed, 24 failed (ENV-ONLY), 13 skipped**. The 24 are `test_costing_gates`+`test_costing_accuracy` failing ONLY because `CADVERIFY_PARTS_DIR` is unset (missing STL corpus) — NOT regressions. Verify after any merge: `git diff <base>..dev --stat -- backend/src/costing backend/src/analysis` empty ⇒ the 24 aren't yours. Frontend behind `NEXT_PUBLIC_STAGE_UI` (flag-off byte-identical).

## Landed today (all adversarially verified, honesty bugs caught+fixed)
Sprint 0 · W1 tenancy steps 1–3 (org/team/membership, RBAC superadmin split, route threading w/ PROVEN cross-tenant isolation) · Findings-API deepening · Frontend v1 FE-1..FE-5 (three doors, part hero on real data) · E-now wave 1 (cost credibility, DEFAULT-tagged, validated=False) · W1 Catalog API (`backend/src/api/catalog.py`, org-scoped read surface).

## IN FLIGHT
- Nothing building right now — all launched work is merged to prod.

## NEXT UP (launch first thing, then gate)
1. **W3 portfolio cost** — batch-cost job type + portfolio roll-up (savings ranking) over the org-scoped catalog. Current batch pipeline is DFM-only (`backend/src/jobs/batch_tasks.py` calls `run_analysis`, never cost). Reuse the arq worker + webhook infra + the groundtruth per-part×qty loop pattern. This makes the FE portfolio door's honest "coming" savings state real. Builder + 2 verifiers, isolation lens (org-scoped).
2. Then: **E-now freeze checkpoint** → regenerate the Zoox validation packet from merged prod (engine credible + flywheel persists = both G3 prereqs met) → founder schedules the Zoox session. Then W4 governed libraries.

## DONE this session (all merged to prod `0ba3aaf`)
- **feat/findings-fe-bind** (68f0bb8) · **feat/catalog-ui** (042bfe3, 168/0 fe) · **feat/w5-plumbing** (0ba3aaf) — flywheel persists; band-incoherence bug (validated band excluded truth 0/17) fixed w/ calibration-factor point correction + coverage regression test; validated=True ONLY from real residuals, byte-identical when none. E-now wave1 + W1 Catalog API also prod.

## RECURRING GOTCHA — package.json merge conflict
Every frontend branch conflicts on `frontend/package.json` "test" script (each adds `--test src/lib/X.test.ts` files). Resolve by UNION of the `--test` file list (keep all test files from both sides), rebuild ONE test line, validate JSON. A crude regex once leaked a branch-name past the closing quote → JSON invalid → npm blows up. After resolving: `python3 -c "import json;json.load(open('frontend/package.json'))"` before committing.

## Gating protocol (unchanged discipline)
Read both verdicts per branch. Double-PASS → merge `--no-ff` to dev. Any FAIL (esp. honesty/isolation) → dispatch a focused fix agent with the EXACT defect, re-verify crux, then merge. After merges: full backend suite (accept only the 24 env fails) → `git push . dev:prod`. Frontend merges: tsc+npm test+both --webpack builds green.

## Forward queue (launch next batches autonomously, keep pipeline full)
- **E-now freeze checkpoint** → regenerate the Zoox packet from merged prod (long-horizon-plan §5) → G3 Zoox session is then founder-schedulable.
- **W3 portfolio cost** (batch-cost job type + portfolio roll-up) — the FE portfolio door's real backend.
- **W1 Catalog UI** already in batch-2; next FE: bind portfolio door to real aggregates.
- Deeper E-now waves (tolerance input surface — L, Zoox-gated coefficients).
- Non-blocking: pre-existing `/history` fabricated-type bug (disclosed by FE-3); W4 governed libraries.

## Key facts
- Merges stay with the orchestrator; builders never merge/push. Worktrees under `<scratchpad>/wt/`.
- Every numeric cost change: DEFAULT/USER provenance + `[assumption, not shop-validated]` + `validated=False`. No self-certified magnitudes.
- The discipline's whole value: 7+ honesty/isolation defects caught by adversarial verifiers this run, every one fixed before merge. Never merge on a fabrication.
- Memory has the corpus-test gotcha + build discipline + orchestrator-model-split.
