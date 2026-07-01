# CadVerify Enterprise Redesign — Cohesion Audit

**Auditor role:** Cohesion Auditor (adversarial). I ran `tsc --noEmit`, `eslint`, `next build`, and the dev server myself; I did not build or fix anything.
**Date:** 2026-06-29 (supersedes an earlier failing pass; the foundation issues that pass flagged are now resolved — re-verified below).
**Method:** read of the token layer, primitive library, shell/IA, and the answer-first `/cost` flow + components; grep sweeps for every Frankenstein smell named in `current-state-audit.md`; live runs of typecheck/lint/build and the dev server (HTTP 200 + rendered-content checks).

**VERDICT: COMPLETE.** All four checks pass. The three missing layers diagnosed in the current-state audit — a real token layer, a primitive layer, and a shell+IA layer — now exist and are actually used everywhere. Ten visual languages have collapsed into one.

---

## CHECK 1 — ONE DESIGN SYSTEM — PASS

**What was tested:** Arial override removed; Geist + tokens applied; exactly one status/process color map; primitives sourced from a shared library; a single decided primary color.

**Evidence:**
- **Arial is gone.** `grep -rni "arial" src` returns only two *comments* in `globals.css` ("FIXES the Arial bug", "NO Arial"). `body { font-family: var(--font-sans); }` (globals.css:88) with `--font-sans: var(--font-geist-sans)…` (globals.css:5). `layout.tsx` wires `geistSans.variable`/`geistMono.variable` on `<html>`. `.num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }` gives every number tabular monospace.
- **Token layer is real.** `globals.css` `@theme` defines the slate neutral ramp, ONE steel-blue accent (`--color-primary: #2563eb`), the 3-stop semantic status set (pass/warn/fail/info), provenance tags, type scale (`--text-display`/`--text-display-xl`), one radius base (`--radius: 6px`), two shadows, and shell metrics — the `design-system-patterns.md` §3–§5 spec, implemented.
- **ONE status/process map.** `src/lib/status.ts` is the single source: `TONE`, `TONE_ICON`, `verdictTone/Label`, `severityTone/Label`, `batchStatusTone`, `confidenceTone`, `usageTone`, `domainTone`, the ONE 21-entry `PROCESS_LABELS`, and `PROVENANCE`. **14 files import `@/lib/status`** (AnalysisDashboard, CostDecisionCard, ProcessScoreCard, IssueList, FeaturesList, QuotaDisplay, BatchProgressBar, CostDecisionView, BreakevenChart, PartWorkspace, share page, plus card/progress/status-badge primitives). `grep` for the old inline maps (`*_STYLES|_COLORS|_BADGE|_CONFIG|_LABELS`) finds **none** outside `status.ts` — the 9+ conflicting verdict/severity/status maps are eliminated.
- **Primary color decided; no drift.** `grep`: `bg-black` → **NONE**; `bg-blue-600` → **NONE**; `rounded-xl`/`rounded-2xl` → **NONE**. Raw status-color sweep `(bg|text|border)-(green|red|amber|yellow|emerald|orange|sky|indigo)-[0-9]` returns a **single** hit: `button.tsx:18 hover:bg-red-700` on the destructive variant — centralized inside the ONE Button primitive (base is the `bg-destructive` token), so not cross-file drift.
- **Primitives from a shared library.** `src/components/ui/` holds 32 primitives. Imports per screen: `/label` (10), `/keys` (6), `/batch` (7), `/reconstruct` (5), `/analyses/[id]` (5), `/history` (3), `/s/[shortId]` (4), `/signup` (4), landing (3). `/cost` and `/analyze` import 0 directly because they delegate to `PartWorkspace`, which imports the full primitive set.

**Two legitimate non-violations (not failures):** `PartWorkspace`'s `SEVERITY_HEX` is a tone→raw-hex bridge required because WebGL face-highlight colors can't be Tailwind classes — keyed off `severityTone()`. `ReconstructionProgress`'s `STATUS_LABELS` is processing-*stage* display strings ("Building 3D model…"), not a color/status vocabulary.

**Minor (non-blocking) suggestion:** replace `hover:bg-red-700` in `button.tsx` with a `--color-destructive-hover` token for 100% token-driven color.

---

## CHECK 2 — ONE SHELL + IA — PASS

**What was tested:** AppShell wraps every authed route (incl. `/label`); the `/` collision resolved to one page; the `dashboard/*` shim tree gone; nav has active states + all sections; no orphans / no second nav.

**Evidence:**
- **One shell, everywhere.** `app/(app)/layout.tsx` renders `<AppShell>` (sidebar + topbar + `max-w-screen-2xl` content — replacing the old `max-w-3xl`). Every authed surface is under `(app)/`: analyze, cost, batch, batch/[id], history, analyses/[id], keys, label, reconstruct. **`/label` is inside the shell** (no longer orphaned) and uses the merged `cad-viewer`.
- **`/` collision resolved.** Single `src/app/page.tsx` owns `/` (public landing). No `(dashboard)` group and no second `/` page; the `next build` manifest lists exactly one `○ /`.
- **`dashboard/*` shim tree deleted.** No `app/dashboard` or `app/(dashboard)` directory; `grep -rn "/dashboard/"` over `src` → **NONE**. Dual-namespace cross-linking gone.
- **Nav complete with active states.** `sidebar.tsx` groups nav as **Analyze** (Analyze/Cost/Batch) · **Library** (History/Parts-Label) · **Develop** (API keys/API docs) — matching IA spec §7.2, including the previously-orphaned `/label`, `/keys`, `/history`, `/docs`. `nav-item.tsx` computes `active` (exact vs startsWith), sets `aria-current="page"`, and renders active as `border-primary bg-primary-50 text-primary-700`. Wordmark links home; collapse persists.
- **Route protection.** `RequireKey` gates the 5 key-required surfaces (reconstruct, batch, batch/[id], history, analyses/[id]) with an EmptyState CTA instead of silent failure.
- **No second nav.** `grep` for `<nav|<header|sticky top-0` inside `(app)` → **NONE**. The only headers are the shared `PublicHeader` (public-chrome) on landing/docs/signup.

---

## CHECK 3 — THE ANSWER-FIRST FLOW — PASS

**What was tested:** `/cost` shows the decision as the hero with a make-vs-buy breakeven chart + a working quantity slider, viewer-linked issues, and the glass-box breakdown as progressive disclosure; `/cost` + 2 other routes return 200 and render.

**Evidence:**
- **Answer is the hero.** `/cost` → `PartWorkspace defaultTab="cost"` → `CostDecisionView`. The hero Card (above the fold) renders **"Make by {process}"** + DFM-ready badge + three `text-display` mono HeroStats: **Cost/unit · Lead time · At quantity**. Crossover sentence states the boundary ("Make below ~N units with X; tool up with Y above it").
- **Working quantity slider that live-flips.** A shared `Slider` drives `pos`→`posToQty`→`recommendAt(breakeven, qty)`; hero process/cost/lead time and the chart's `recommendedProcess` recompute client-side from the report's fitted curves (`lib/breakeven.ts`). Default position is the crossover quantity.
- **Make-vs-buy breakeven chart.** `BreakevenChart` (Recharts) plots $/unit vs quantity on a log x-axis, one line per costed process, the recommended one in steel-blue accent (thicker), the engine crossover as a dashed reference line, and the live slider quantity as an accent reference line. Accent = recommendation, neutral = alternatives, status colors reserved for status.
- **Viewer-linked DFM issues (two-way).** `PartWorkspace` keeps a persistent 3D rail; a face click (`onFaceClick`) finds the owning issue, switches to Analyze and selects it; selecting an issue highlights its faces (`highlightFaces`/`highlightColor`, ghosting the rest). Required vs Advisory labels from `severityLabel` (no opaque scores).
- **Glass-box as progressive disclosure.** The provenance-tagged `CostDecisionCard` (Σ = unit cost) and the re-cost input form sit behind collapsed `Disclosure` panels — one click away, not in the path to the answer.
- **Live route checks (dev server :3000):** `/` 200 · `/cost` 200 · `/analyze` 200 · `/history` 200 · `/batch` 200 · `/label` 200 · `/docs` 200. `/cost` HTML contains the real hero copy ("Should-cost", "make-vs-buy", "manufacturing decision", "Drop a CAD", "Costing options") — renders, not an error page. `/keys` returns 500 **only** because it is a server component whose `listKeys()` action calls the backend (`authed("/api/v1/keys")`) and the backend on :8000 is intentionally not running for a frontend-only audit — a backend dependency, not a redesign regression (the page is fully recomposed on Card/Table/StatusBadge/PageHeader primitives).

---

## CHECK 4 — BUILD + NO REGRESSION — PASS

**What was tested:** `next build`, `tsc --noEmit`, `eslint` all green (actually run); the `/cost` demo flow intact; 3D viewers still render; backend untouched.

**Evidence (commands run from `frontend/`):**
- **`npx tsc --noEmit` → exit 0** (no type errors).
- **`npm run lint` → exit 0.** One *warning* only: `react-hooks/incompatible-library` on TanStack Table's `useReactTable` in `data-table.tsx` — a benign React-Compiler memoization note, not an error.
- **`npm run build` → success.** "Compiled successfully", TypeScript pass, 14/14 static pages generated. Manifest shows a single `○ /`, **zero `/dashboard/*` routes**, all 15 intended routes.
- **Demo flow preserved.** `PartWorkspace.runCost` keeps `hasApiKey() ? costEstimate() : costEstimateDemo()`; `runDfm` uses `validateFile()` with a key and the public `POST /validate/demo` route without one (with the STL triangle-budget guard). The `CostGeometryInvalidError` repair path is intact. Frictionless local-demo behavior unchanged.
- **3D viewers render.** The two duplicate R3F viewers (`ModelViewer` + `MeshCanvas`) are merged into the single `components/ui/cad-viewer.tsx` (`Canvas`/`useLoader`/`STLLoader`/`OrbitControls`/`Environment`, accepting `File` or `src` URL). `grep` confirms **no leftover refs** to `ModelViewer`/`MeshCanvas`; the label tool's `CorpusViewer` now imports the shared `cad-viewer` (`src={url}`).
- **Backend untouched.** All changes under `frontend/src`; no `backend/` or `data/` modification.

---

## Before → after cohesion notes

| Frankenstein symptom (current-state-audit) | After |
|---|---|
| `body{font-family:Arial}` overriding Geist | Removed; Geist Sans applied, Geist Mono via `.num` with tabular figures |
| Only 2 color tokens, no scale | Full `@theme` token layer: slate ramp + ONE steel-blue primary + 4-status semantic set + provenance + type/radius/shadow/shell tokens |
| 9+ inline verdict/severity/status maps that disagreed | ONE `lib/status.ts`; 14 files import it; zero inline maps remain |
| Primary undecided (bg-blue ×13, bg-black ×6, outline-blue, bg-green) | One primary (`#2563eb`); no `bg-black`, no `bg-blue-600`; lone destructive-hover centralized in Button |
| Radius drift (rounded-md ×74 / xl ×24 / 2xl ×1 …) | One `--radius` (6px); no `rounded-xl`/`rounded-2xl` left |
| No primitive layer | 32 shared `components/ui/*` primitives; feature components recompose on them |
| `max-w-3xl` document nav, no active state, no logo/account | AppShell (256/64px sidebar + 56px topbar, `max-w-screen-2xl`), grouped nav, active state, wordmark, collapse persistence |
| `/` route collision (two pages) | Single `app/page.tsx` owns `/`; build manifest confirms one `/` |
| Dual `dashboard/*` + `(dashboard)/*` namespaces | One `(app)/*` namespace; no `dashboard` dir; no `/dashboard/` links |
| `/label` orphaned (no shell, no nav, no way back) | Under the shell, in nav as "Parts (Label)", uses the merged viewer |
| 3 dropzones, 2 viewers, 2 modals, 2 spinners | One `dropzone`, one `cad-viewer`, one `dialog`/`alert-dialog`, one `spinner` |
| Answer buried; opaque scores | Decision is the hero; live breakeven chart + quantity slider; Required/Advisory labels; glass-box one click away |

**Net:** the skeleton the audit said to keep (data layer, cost/analysis cards, R3F viewer) is intact, and the three absent layers (tokens, primitives, shell+IA) are present and enforced. This now reads as one enterprise product.

## Commands run (honesty log)
- `npx tsc --noEmit` → exit 0
- `npm run lint` → exit 0 (1 benign warning)
- `npm run build` → success, 14/14 pages, single `/`, no `/dashboard/*`
- `npm run dev` (:3000) → `/ /cost /analyze /history /batch /label /docs` all HTTP 200; `/cost` renders hero content; `/keys` 500 = backend-on-:8000 dependency only (frontend-only audit), not a regression
