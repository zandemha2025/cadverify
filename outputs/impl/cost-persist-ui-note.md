# Cost-decision persist — frontend impl note (Phase 2 gap #3, builder 4B)

Branch: `feat/cost-persist-ui` (worktree `cadverify-wt-ui`, off `dev` which carries
the Phase-2 backend). Framework: Next.js 16.2.3 App Router, session-authed via the
same-origin proxy (`/api/proxy/* → backend /api/v1/*`).

## What this closes

The flagship should-cost decision (the LivingInstrument cost surface) had ZERO
save/export/download/share affordance — the only PdfDownloadButton/ShareButton/
ShareModal were wired to the DFM `/analyses/[id]` surface. The backend now
persists + exports + shares + compares the decision; this surfaces all of it in
the product, with the SAME honest confidence labeling ("assumption-based, not yet
validated" / "not a validated quote") carried onto every saved/exported/shared
artifact.

## Surfaces that gained save / export / share / compare

1. **LivingInstrument cost surface** (`components/instrument/LivingInstrument.tsx`)
   — new **`CostArtifactBar`** (`components/instrument/CostArtifactBar.tsx`) mounts
   inside the decision panel once the authed cost route has persisted the decision
   (`report.saved`, gated by `NEXT_PUBLIC_COST_PERSIST_UI`, default ON). It shows
   "Saved to cost history" + an open link, and buttons for **Open in history /
   PDF / JSON / CSV / Share** — each hitting a real cost-decision endpoint. Share
   reuses the existing `ShareModal`.
2. **Cost history detail** (`app/(app)/cost-decisions/[id]/page.tsx`) — header
   actions reuse the **extended** `ShareButton` (`kind="cost"`) + `PdfDownloadButton`
   (`kind="cost"`) plus JSON/CSV export buttons, exactly as `/analyses/[id]` does.
3. **Public cost share** (`app/s/cost/[shortId]/page.tsx`) — read-only, sanitized,
   `robots: noindex`; no owner actions.

## New API client functions (`src/lib/api.ts`)

Added `saved?: {id,url}` to `CostReport`, plus typed functions + interfaces
matching the backend contract (`cost-persist-note.md`):

- `fetchCostDecisions({cursor,limit,process,createdAfter,createdBefore})` → `CostDecisionsPage`
- `fetchCostDecision(id)` → `CostDecisionDetail` (`result` = verbatim report_to_dict)
- `downloadCostPdf(id, filename)` / `exportCostJson(id, filename)` / `exportCostCsv(id, filename)`
  (blob download via a shared `triggerBlobDownload` helper; PDF names `<stem>-cost-report.pdf`)
- `shareCostDecision(id)` → `{share_url, share_short_id}` / `unshareCostDecision(id)`
- `fetchSharedCostDecision(shortId)` → `SharedCostDecision` (public, mirrors
  `fetchSharedAnalysis`, hits `/s/cost/{shortId}`)
- `compareCostDecisions(idA, idB)` → `CostComparison`

New interfaces: `CostDecisionSummary`, `CostDecisionsPage`, `CostDecisionDetail`,
`SharedCostDecision`, `CostComparison` (+ `CostCompareSummary`, `CostCompareUnitRow`),
`CostShareResult`. Reads go through `apiClient`; the public fetch mirrors the
existing analysis public fetch (bypasses the proxy, uses `browserOrBackendUrl`).

## Pure logic + unit tests

`src/lib/cost-decision.ts` (no React) holds the honesty-critical logic:

- **`recommendationForQty` / `redesignedForQty` / `recommendedQuantities`** — the
  STRING-KEY reader. Persisted `result_json.decision.recommendation` /
  `if_redesigned` keys round-trip through JSONB as STRINGS ("50","5000"); the
  scrubber/charts speak numbers. These normalize both directions (`String(qty)`
  plus a numeric-equality fallback) so a saved decision re-renders identically to
  a live one — never a missing figure because `"50" !== 50`.
- **`formatUnitCostDelta` / `cheaperSide`** — the compare-diff formatter: signs
  and labels `delta_usd`/`delta_pct` (B relative to A), returns `"—"` (never a
  fabricated number) when a side lacks an estimate, and picks the cheaper side.
- **`costPersistUiEnabled()`** — `NEXT_PUBLIC_COST_PERSIST_UI`, default ON, only
  explicit `0`/`false` opts out.

`src/lib/cost-decision.test.ts` — 10 tests on the repo's `node --test` runner
(same pattern as `dfm-scope.test.ts`): string-key + int-key reads, unknown/null
guards, redesigned null-preservation, sorted quantities, delta signing, the "—"
no-fake-number case, `cheaperSide` a/b/equal/na, and the flag default. Wired into
`package.json`'s `test` script alongside `dfm-scope.test.ts`.

## Cost history + public share + compare views

- **List** `app/(app)/cost-decisions/page.tsx` + `components/CostDecisionHistoryTable.tsx`
  (mirrors `AnalysisHistoryTable`: cursor pagination, Load more, row → detail,
  Shared badge, empty state). Header links to Compare.
- **Detail** `app/(app)/cost-decisions/[id]/page.tsx` (mirrors `analyses/[id]`,
  client `use(params)`), renders **`SavedCostDecisionView`** (`components/cost/`):
  make-vs-buy headline + honest `ConfidenceInterval` + reuses `CostDecisionCard`
  for the full glass-box breakdown (recommendation-by-qty, provenance drivers,
  Σ=unit-cost, assumptions). `CostDecisionCard` already reads `dec.recommendation[String(q)]`.
- **Public** `app/s/cost/[shortId]/page.tsx` (Server Component mirroring
  `s/[shortId]`): `generateMetadata` with `robots noindex`; renders the decision,
  honest confidence band (verbatim), geometry, recommendation-by-qty (via the
  string-key reader), and provenance-tagged assumptions. No owner PII (backend
  pre-sanitized).
- **Compare** `app/(app)/cost-decisions/compare/page.tsx`: two `Select` pickers
  over the user's saved decisions → `compareCostDecisions` → side-by-side summary
  cards + a "recommended unit cost by quantity" table with cheaper-side highlight
  and signed deltas via the pure formatter. (Avoids `useSearchParams` so no
  Suspense-boundary build gap.)
- **Nav**: command palette (`components/ui/command-palette.tsx`) gains "Cost
  history" (`/cost-decisions`, PiggyBank) and "Compare cost decisions"
  (`/cost-decisions/compare`, GitCompareArrows), exactly as DFM History is
  surfaced. Also tightened the `current`-highlight match to exact-segment so
  `/cost` and `/cost-decisions` don't both light up.

## Reuse / extension (not reinvention)

- `PdfDownloadButton` — added `kind?: "dfm"|"cost"` (default dfm); cost calls
  `downloadCostPdf`.
- `ShareButton` — added `kind?: "analysis"|"cost"` (default analysis); cost calls
  `shareCostDecision`/`unshareCostDecision`.
- `ShareModal` — added `kind` for cost-flavored, honesty-preserving copy
  ("Not a validated quote — an explainable should-cost estimate").
- Existing `CostDecisionCard`, glass-box `DecisionHeadline`/`ConfidenceInterval`,
  `Card`/`Table`/`Select`/`StatusBadge`, and `lib/status`/`lib/cost-views` reused
  as-is.

## Honesty labeling preserved

- New `components/cost/CostHonestyNote.tsx` (presentational, server-safe) renders
  on the history list, detail, compare, and public pages: "explainable
  should-cost… assumption-based, not yet validated… not a validated quote."
- The instrument `CostArtifactBar` states the saved/exported/shared copies keep
  the provenance tags and the "assumption-based, not yet validated" band.
- Confidence is rendered from the engine's own `validated`/`label`/`basis`
  verbatim (via `ConfidenceInterval` and the public page's inline band) — never a
  fabricated ±X% and never a "validated"/certified stamp on an assumption band.
- The `ShareModal` cost copy and the public page footer both say "not a validated
  quote."

## How tested (commands + results)

Run from `frontend/`:

- `npx tsc --noEmit` → **clean** (TSC_OK).
- `npm test` → **17 passed / 0 failed** (7 dfm-scope + 10 cost-decision).
- `npx eslint <changed files>` → **0 errors** (removed the one pre-existing unused
  `Sun` import I touched in command-palette; test-file "ignored" notice is
  expected, same as dfm-scope.test.ts).
- `npx next build` (default Turbopack) **panics** in this worktree with
  `Symlink [project]/node_modules is invalid, it points out of the filesystem
  root` — `frontend/node_modules` is a cross-filesystem symlink to
  `/Users/.../cadverify/frontend/node_modules`; this is an environment constraint
  of the isolated worktree and reproduces on baseline (independent of these
  changes). `npx next build --webpack` → **exit 0, compiled + TypeScript OK**, and
  registers all four new routes: `/cost-decisions`, `/cost-decisions/[id]`,
  `/cost-decisions/compare`, `/s/cost/[shortId]`. (The known cad-viewer.tsx lint
  issue was not touched.)

## Acceptance

From the cost surface a user can SAVE (auto-persisted; artifact bar surfaces it +
open link), EXPORT PDF/JSON/CSV, SHARE a public link, see it in cost HISTORY, open
the read-only public share page, and COMPARE two decisions — all against real
endpoints, with honest "not yet validated" labeling intact.
