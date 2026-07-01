# Verify — Item 1: Scope DFM flags to recommended process (DFM audit FRAGILE-1)

**Verdict: CLOSED + PRODUCTION-WORTHY → MERGED to prod.**
Branch `feat/dfm-scope-flags` (builder commit 446191b). 3 independent adversarial verifiers, all high-confidence PASS.

## The finding (closed)
The DFM headline was the UNION of issues across all 21 process analyzers ("58 flags / 11 critical"), contradicting a DFM-clean recommended route (MJF = 0). Now the headline is scoped to the recommended route (`recProcess` from the cost engine; `best_process` as pre-cost fallback) + part-level `universal_issues`, with the full 21-process matrix reachable behind an honestly-labeled expander. Flag `NEXT_PUBLIC_DFM_SCOPED_FLAGS` (default ON).

## Evidence
- **Process-name identity (the highest-risk failure mode) — PROVEN.** DFM `process_scores[].process`, `best_process`, and cost `make_now_process`/`estimates[].process`/`routing.recommended_process` all serialize from the **same `ProcessType` enum** (`src.analysis.models`) as `.value` strings. Verified end-to-end with backend `.venv` on 3 watertight meshes across 3 routes (mjf, cnc_turning, sheet_metal): every cost-recommended string ∈ the DFM `process_scores` set. Guaranteed structurally (same `_REGISTRY`), not just sampled. So scoping never silently degrades to universal-only for the cost case.
- **Nothing real hidden — CONFIRMED.** `flattenScopedIssues` unconditionally counts `universal_issues`; a genuine ERROR on the recommended route → "critical" in the headline (5 extra adversarial tests authored + passed: route-unique error surfaces, best_process fallback error surfaces, empty-route universal error counts, shared-issue no double-count).
- **Regression gate (run independently by 2 verifiers):** `npm test` → 7/7 pass; `npx tsc --noEmit` → exit 0; `next build` compiles. Diff scope = frontend/ + outputs/ only (no backend/cost/analysis touched); backend suite unaffected.

## Non-blocking notes (tracked, not fixing now)
1. Cross-endpoint coupling is implicit: identity holds because the demo path calls `/validate` with no `processes`/`rule_pack` narrowing (full registry). If a future caller narrows the DFM process set while cost recommends outside it, scoping would degrade to universal-only. **Not exercised today; no guard.** → future-proofing item.
2. Pre-cost + null `best_process` → universal-only headline (designed, honest fallback).
3. Legacy union still reachable via `NEXT_PUBLIC_DFM_SCOPED_FLAGS=0` (acceptable, honestly gated).

Merged: feat/dfm-scope-flags → dev → prod.
