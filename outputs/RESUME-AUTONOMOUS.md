# RESUME — Autonomous Orchestration Loop (live)

**Written 2026-07-03 by Fable (orchestrator).** Directive: **full autonomous** — Fable orchestrates, subagents build, Fable gates every merge, routes back failures, keeps the pipeline full, does NOT stop to ask the user between beats. Continue the loop.

## Current prod
- `prod == dev == 8b7529e`. Backend suite: **768 passed, 24 failed (ENV-ONLY), 13 skipped**. The 24 are `test_costing_gates`+`test_costing_accuracy` failing ONLY because `CADVERIFY_PARTS_DIR` is unset (missing STL corpus) — NOT regressions. Verify after any merge: `git diff <base>..dev --stat -- backend/src/costing backend/src/analysis` empty ⇒ the 24 aren't yours. Frontend behind `NEXT_PUBLIC_STAGE_UI` (flag-off byte-identical).

## Landed today (all adversarially verified, honesty bugs caught+fixed)
Sprint 0 · W1 tenancy steps 1–3 (org/team/membership, RBAC superadmin split, route threading w/ PROVEN cross-tenant isolation) · Findings-API deepening · Frontend v1 FE-1..FE-5 (three doors, part hero on real data) · E-now wave 1 (cost credibility, DEFAULT-tagged, validated=False) · W1 Catalog API (`backend/src/api/catalog.py`, org-scoped read surface).

## IN FLIGHT (gate when it notifies)
1. **feat/w5-plumbing** — route-back IN PROGRESS (agent `a258cec94d4e9699d`). Original build FAILED verify: served "measured-residual" band centered on UNCORRECTED baseline while residuals measured on CORRECTED predictions → validated band excluded true cost 0/11. Fix: apply persisted `calibration.factor_for(process)` to the point estimate feeding `confidence_interval` (estimate.py:306-308 via routes.py:715-720 / groundtruth_service load_served_residual_model which was discarding the factor) → verifier confirmed coverage → 11/11; + a NEW coverage test (must fail pre-fix, pass post). validated stays False w/o real ground truth (byte-identical). GATE when it returns: re-verify coverage crux + byte-identical-no-groundtruth + no new failures beyond the 24 env.

## DONE since last handoff (already merged to prod-line dev)
- **feat/findings-fe-bind** MERGED (68f0bb8) — cost-blocker locate wired into live path.
- **feat/catalog-ui** MERGED (042bfe3) — catalog grid on real /catalog endpoint. (frontend verify in flight bzyj4ffwp; ff prod when green.)

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
