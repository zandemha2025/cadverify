# DFM-UX — FRAGILE-1: scope the DFM flag headline to the recommended route

Branch: `feat/dfm-scope-flags`

## The finding (FRAGILE-1 — the #1 demo trust-killer)

The DFM headline ("58 flags · 11 critical") was the UNION of DFM issues across
ALL 21 process analyzers — including the 8 casting/molding/forging processes
that always fail on a printed part — deduped only by `code|message`. That count
sat next to a "make this as-is" recommendation whose RECOMMENDED process (MJF)
is DFM-clean (0 errors / 0 warnings). A real engineer reads "11 critical" beside
a clean recommendation and concludes the tool is noise.

Root cause: the DFM panel never scoped to the recommended/costed process(es) —
`flattenIssues()` merged `universal_issues` + every `process_scores[].issues`.

## What changed

### New pure, unit-tested module — `frontend/src/lib/dfm-scope.ts`
The scoping logic (previously `flattenIssues` inline in `IssueList.tsx`) now
lives in a React-free module so it can be tested without rendering:

- `flattenIssues(result)` — the legacy full union (unchanged behavior; moved here).
- `flattenScopedIssues(result, processes)` — universal issues + ONLY the given
  processes' issues.
- `severityCounts(issues)` — `{ total, critical, advisory, info }`
  (error/critical/fail → critical, warning → advisory, else → info).
- **`scopedDfmSummary(result, recommendedProcess, shortlist?)`** — the pure core:
  returns the scoped issue set + `counts` (headline), the full `all` set +
  `allCounts` (matrix), `candidateProcessCount`, `recommendedProcess`.
- **`partitionDfmByRoute(result, recommendedProcess, shortlist?)`** — splits the
  full matrix into `{ route, extra }` by issue identity while keeping the
  CANONICAL keys from `flattenIssues`, so the 3D two-way highlight linking (which
  looks a selected key up in the full flatten) stays coherent across surfaces.
- **`dfmScopedFlagsEnabled()`** — the feature flag (see below).

`frontend/src/components/IssueList.tsx` now re-exports `flattenIssues` /
`IndexedIssue` from the module (zero churn for existing importers:
AnalysisDashboard, LivingInstrument, PartWorkspace).

### Headline scoped — `frontend/src/components/instrument/LivingInstrument.tsx`
This is THE demo path (the floating "DFM flags" panel).
- The collapsed strip headline now reflects the route the part is actually made
  by: `recProcess` (the scrubbed recommendation), falling back to the DFM
  engine's own `best_process` before cost lands, plus part-level
  `universal_issues` (which always count). It reads e.g.
  **"No flags on MJF"** or **"3 flags · 1 critical on MJF"**, with a
  de-emphasized **"· 58 across all 4 candidate processes"** when off-route flags
  exist.
- Expanded: the recommended-route rows show first under
  "On recommended route · MJF"; the off-route flags sit behind an honest,
  de-emphasized expander **"Show N flags on other candidate processes"** →
  "Only on processes the part is not routed to". Nothing is hidden; the full
  matrix is one click away and clearly labeled as across-all-candidates.
- Face-click / hover highlighting still resolves against the full set; clicking a
  highlighted off-route face auto-opens the candidates section.

### Consistency — `frontend/src/components/AnalysisDashboard.tsx`
Scopes its "Manufacturability issues" list to `result.best_process` the same way
(honest "on recommended route · X" label + expandable "N issues only on other
candidate processes"). Used by `analyses/[id]`, `RepairComparison`, and the
workspace "Per-process DFM audit". Keys stay canonical so workspace 3D linking
is unaffected.

## Surfaces audited

| Surface | Summed-across-processes critical headline? | Action |
|---|---|---|
| `instrument/LivingInstrument.tsx` | YES — the exact FRAGILE-1 headline | **Fixed** (scoped) |
| `AnalysisDashboard.tsx` | No headline count, but listed the union | **Fixed** (scoped list + honest expander) |
| `app/s/[shortId]/page.tsx` (public share) | No — Issues section already uses `universal_issues` only | No change needed (already scoped) |
| PDF (`backend/src/services/pdf_service.py` + `templates/pdf/analysis_report.html`) | No scary headline — a full Issues *table* (union), verdict is backend-driven | Out of scope for the headline fix; left as the full audit table |

Verification: the literal string `critical` appears in the frontend ONLY in
`LivingInstrument.tsx` (and the shared `severityTone` map) — there was no other
summed-critical headline to fix.

## Feature flag

`NEXT_PUBLIC_DFM_SCOPED_FLAGS` — the corrected scoped behavior is **ON by
default** (this is a demo-path fix). Set it to `0` / `false` / `off` / `no` to
fall back to the legacy union headline. Any other value (including unset) stays
scoped. No half-done toggle: both branches are fully wired.

## How it closes FRAGILE-1 — bracket before/after

- **Before (union):** `58 flags · 11 critical` in the headline — contradicting the
  DFM-clean MJF recommendation.
- **After (scoped to MJF):** the headline reflects the MJF route + part-level
  issues → **0 critical** (MJF is clean). Reads "No flags on MJF" (or the real
  part-level flags if any), with a de-emphasized "· 58 across all candidate
  processes" and the full per-process matrix behind an honestly-labeled expander.

The scary 11-critical number can no longer appear next to a clean recommendation.

## How it was tested

- **Unit test** `frontend/src/lib/dfm-scope.test.ts` — runs on the repo's
  zero-dependency runner (`node --test` + native TS type-stripping, Node ≥ 22.6;
  no vitest/jest added). Proves: (a) a clean recommended process → 0 critical in
  the headline even when other processes error; (b) part-level/universal issues
  still count; (c) the full matrix count is still available; (d) route/extra
  partition is correct with unique keys and no double-counting of shared issues;
  (e) the flag defaults ON.
  - Command: `npm test` (frontend/) → **7 passed / 0 failed**.
- `npx tsc --noEmit` → exit 0.
- `npx next build` → compiled + typechecked + all 18 routes generated OK.
- `npx eslint <the 4 changed files>` → clean (0 problems). (The one repo-wide
  lint error is pre-existing in the untouched `ui/cad-viewer.tsx`.)

### Test infra notes
- `package.json`: added `"test": "node --disable-warning=... --test src/lib/dfm-scope.test.ts"`.
- `tsconfig.json` `exclude` + `eslint.config.mjs` `globalIgnores`: added
  `**/*.test.ts` — the test uses an explicit `.ts` import extension (required by
  node's type-stripping, rejected by the app's `bundler` tsconfig), so the tests
  run via `npm test` rather than through the app build. The tested module itself
  (`dfm-scope.ts`) is fully typechecked and linted as normal app code.
