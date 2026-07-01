# Screen Builder A — Hero Flow (Analyze + Cost decision)

**Author:** Screen Builder A
**Date:** 2026-06-29
**Status:** DONE — `npm run build` + `npx tsc --noEmit` GREEN; `npm run lint` 0 errors;
dev server boots on :3000 and `/cost` + `/analyze` render 200.
**Scope:** the flagship "least friction to the answer" experience — rebuilt on the
foundation's shell + primitives + single status map (USED, not re-rolled). No
backend/ or data/ changes. No git commit.

---

## 0. Proof the gate is green (real output)

```
$ npm run build                 # Next.js 16.2.3 (Turbopack)
✓ Compiled successfully in 2.6s
  Running TypeScript ... Finished TypeScript in 2.2s
✓ Generating static pages (14/14)
Route (app): / · /analyze · /cost · /history · /batch · /label · /reconstruct
             /docs · /analyses/[id] · /batch/[id] · /keys · /signup · /magic/verify
             /s/[shortId] · /scalar · /_not-found

$ npx tsc --noEmit
TSC_GREEN

$ npm run lint
✖ 2 problems (0 errors, 2 warnings)   # both PRE-EXISTING (ModelViewer unused prop;
                                       # data-table TanStack React-Compiler note) — not mine

$ npm run dev                   # boots on :3000
/ 200 · /cost 200 · /analyze 200 · /history 200 · /batch 200 · /label 200
# /cost + /analyze cold-start render the workspace (verified markers:
# "Should-cost & make-vs-buy", "Drag and drop or click to upload", "Costing options");
# dev log clean (no runtime errors).
```

The local demo flow is preserved: `hasApiKey() ? costEstimate : costEstimateDemo`
and the `CostGeometryInvalidError` repair path are intact; the 3D viewer still renders.

---

## 1. The big move — ONE part-as-object workspace (kills the Analyze/Cost silo)

The locked direction says *part-as-an-object with tabs (Analyze · Cost · Tolerances ·
Share)* and *answer-first*. The Frankenstein app had `/analyze` and `/cost` as two
separate single-purpose pages. I unified them into one component —
**`components/workspace/PartWorkspace.tsx`** — used by both routes:

- `app/(app)/cost/page.tsx` → `<PartWorkspace defaultTab="cost" />`
- `app/(app)/analyze/page.tsx` → `<PartWorkspace defaultTab="analyze" />`

**A single CAD drop runs BOTH the should-cost decision and the DFM analysis in
parallel**, then the part opens to the four tabs sharing one upload (exactly the
contract the foundation's `PartTabs` primitive was waiting for). Demo-capable: no key
→ public `/validate/demo` + `/validate/cost/demo` (CAD never leaves the machine);
with a key → the authed routes. Errors are handled independently per tab (e.g. a part
that busts the demo triangle ceiling still shows the cost answer).

**Layout:** a persistent left **3D part rail** (sticky) + geometry facts, with the
active tab's content on the right — so "the part as an object" is literally always on
screen while the tabs change the lens. Cold start is friendly (no empty-form): a
centered dropzone + value prop + a collapsed, pre-filled "Costing options" disclosure
(sensible defaults → zero friction).

## 2. The ANSWER is the hero (Cost tab) — `components/cost/CostDecisionView.tsx`

Above the fold, before any table: **"Make by {process}"** with a DFM-ready/needs-redesign
status pill, three big mono stats (**$/unit · lead-time days · at-quantity**), and the
make-vs-buy sentence ("Make below ~N units with X; tool up with Y above it"). The
single hero number (cost/unit) is the one place the steel-blue accent lands.

## 3. Make-vs-buy breakeven chart + live quantity slider (the thing no comp nails)

- **`lib/breakeven.ts`** (pure, unit-tested below) derives a continuous cost/unit curve
  per process — `unit(q) = fixedAmort/q + variablePerUnit` — fit from the report's OWN
  reported unit costs, so the curve passes exactly through the numbers shown in the
  glass-box breakdown (no invented figures). With the default two costed quantities the
  fit is exact.
- **`components/cost/BreakevenChart.tsx`** (Recharts): $/unit vs quantity on a log x-axis,
  one curve per costed process, the engine **crossover marked**, and a live reference
  line at the slider quantity. Colour discipline held: **accent = the currently-recommended
  process (thick), neutral slate = alternatives** — status colours stay reserved for status.
- The **quantity slider** re-costs *instantly client-side* (from the fitted curves) and
  **live-flips the recommended process** + the hero numbers + the chart emphasis. Changing
  material/region/complexity/cavities/quantities re-hits the API via "Re-cost with these
  inputs" (one click away). Verified flip with a synthetic report:
  `qty 100 → cnc_3axis $52.42 … qty 5000 → injection_molding $20.00` (FLIP across crossover ≈ 484: PASS).

## 4. Glass-box breakdown — progressive disclosure, Σ=unit intact

`CostDecisionCard.tsx` was refactored onto the primitives (Card / Badge / StatusBadge /
Table) and the single `lib/status` source (`procLabel`, `PROVENANCE`). The duplicate
21-entry `PROCESS_LABELS` map and the per-file `PROVENANCE_STYLES` map are **gone** (now
sourced from `lib/status`). It is now the **collapsed "View full cost breakdown"** body
(one click away): provenance-tagged drivers (MEASURED/USER/DEFAULT), the visible
**Σ line-items == unit-cost** coherence check, per-process should-cost, lead time, and
provenance-tagged assumptions. The repair card (`CostGeometryInvalidCard`) is refactored too.

## 5. Viewer-first DFM with two-way geometry↔issue linking (Analyze tab)

- `AnalysisDashboard.tsx` refactored onto primitives; its inline `VERDICT_STYLES`,
  `PROCESS_LABELS`, `CITATION_COLORS`, `SeverityBadge` are replaced by `lib/status` +
  `StatusBadge` + `Badge`. Issues are regrouped into **Required / Advisory / Notes**
  (named, not opaque scores).
- `IssueList.tsx` refactored: clickable issue rows. **Click an issue → its faces light up
  on the 3D part** (ghosting the rest; highlight colour follows severity tone: red=Required,
  amber=Advisory). **Click a face on the 3D part → the matching issue is selected** and
  scrolled into view — true two-way linking. Implemented via a small additive extension to
  the shared `CadViewer` primitive (`onFaceClick`, `highlightColor` — backward-compatible;
  the `label`/`reconstruct` callers are unaffected).
- A shared `flattenIssues(result)` (in `IssueList.tsx`) is the single index used by both the
  renderer and the workspace's face→issue mapping (no divergence).
- `ProcessScoreCard.tsx` and `FeaturesList.tsx` refactored onto primitives + tone map
  (the rainbow `KIND_CONFIG` / `VERDICT_COLORS` are gone).

Because `AnalysisDashboard` is shared, the refactor (additive optional props only) also
flows cohesion into `/analyses/[id]`, the landing demo, and `RepairComparison` for free —
without changing their `{ result }` API.

## 6. Tolerances & Share tabs (cohesive, honest stubs)

The part-as-object needs all four tabs to cohere, but Tolerances/Share deep features are
out of this builder's hero-flow scope, so they are tasteful, on-primitive panels (not
dead tabs):
- **Tolerances:** surfaces the mesh-derived dimensional features we DO have (hole radii,
  depths) + an `EmptyState` that honestly frames full GD&T stack-up as needing B-rep STEP.
- **Share:** a frictionless "Copy decision summary" (the make-vs-buy answer + per-qty
  $/unit + crossover + DFM verdict, to clipboard with a toast) + an `EmptyState` noting
  persisted shareable links/PDF come from saved analyses (API key). No backend share
  plumbing invented.

---

## 7. Files

**New**
- `components/workspace/PartWorkspace.tsx` — the unified part-as-object workspace.
- `components/cost/CostDecisionView.tsx` — answer hero + slider + chart + disclosures.
- `components/cost/BreakevenChart.tsx` — Recharts make-vs-buy curves.
- `components/cost/CostOptionsForm.tsx` — costing inputs on Field/Input/Select primitives
  (+ `validateQty`, `DEFAULT_COST_OPTIONS`).
- `lib/breakeven.ts` — pure curve-fit / recommend / slider-mapping logic.

**Refactored onto primitives + `lib/status` (single source)**
- `CostDecisionCard.tsx`, `AnalysisDashboard.tsx`, `IssueList.tsx`, `ProcessScoreCard.tsx`,
  `FeaturesList.tsx`.
- `components/ui/cad-viewer.tsx` — additive `onFaceClick` + `highlightColor` (shared primitive).

**Rewritten to the workspace**
- `app/(app)/cost/page.tsx`, `app/(app)/analyze/page.tsx`.

**Cohesion check:** the hero flow now uses ONLY the shared app shell + shared primitives +
the single `lib/status` map. No inline buttons/cards/badges, no per-file colour maps, no
second `PROCESS_LABELS`/provenance map, no Arial, no `max-w-3xl`. The accent lands only on
the one hero number, the recommended curve, active nav/tab, and focus rings.

---

## 8. Honest caveats

- The **loaded** workspace (chart/slider/issue-highlight) needs the backend on :8000 to
  return cost/DFM reports; it is not running in this environment. I verified: (a) the
  cold-start renders 200 with a clean dev log on both routes, (b) the build/tsc/lint gate
  is green, and (c) the breakeven derivation + live-flip + slider math against a synthetic
  report (curve fit reproduces reported unit costs exactly; recommendation flips across the
  crossover; pos↔qty round-trips). Visual confirmation of the chart/3D-highlight with a
  real part should be done once the backend is up.
- Tolerances/Share are deliberate stubs (see §6) for a later builder; flagged so they are
  not mistaken for finished features.
- The two remaining lint warnings (`ModelViewer` unused prop; `data-table` TanStack note)
  are pre-existing and were documented by the Foundation Builder.
```
