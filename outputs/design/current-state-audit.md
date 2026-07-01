# CadVerify — Current-State Audit (the honest "Frankenstein" diagnosis)

**Scope:** `frontend/src` — every route under `app/`, every component, and the styling system.
**Method:** Read of all 28 page/component files + Tailwind/CSS config + Next build route manifest (`.next/server/app-paths-manifest.json`, `.next/app-path-routes-manifest.json`).
**Stack confirmed:** Next.js `16.2.3` (App Router) + React `19.2.4` + TypeScript + Three.js (`@react-three/fiber` / `drei`). Styling is **Tailwind v4** via `@tailwindcss/postcss` (CSS-first config — there is **no `tailwind.config.js`**; tokens live in `frontend/src/app/globals.css`). Toasts via `sonner`. Errors via `@sentry/nextjs`.

> One-line verdict: The product is **four+ separately-authored mini-apps stapled to one Next.js tree**. Each surface re-invents its own header, container width, button color, radius, and status-color vocabulary. There is **no shell, no design-token layer, and no shared UI primitive**. The CAD cost surface (`/cost`) is genuinely polished; almost nothing else matches it.

---

## 1. Page & Route Inventory

### 1a. The routing is duplicated into two parallel URL namespaces

Every authenticated surface exists at **two URLs**: a bare path (`/cost`) and a legacy `/dashboard/*` path (`/dashboard/cost`). The `app/dashboard/*` files are **one-line re-export shims** to the canonical `app/(dashboard)/*` route group:

```
frontend/src/app/dashboard/cost/page.tsx
  → export { default } from "../../(dashboard)/cost/page";
```

| URL (canonical) | Source file | Legacy duplicate URL | Shell / layout | In nav? |
|---|---|---|---|---|
| `/` | `app/page.tsx` **AND** `app/(dashboard)/page.tsx` | — | **COLLISION** (see §3) | "Dashboard" |
| `/cost` | `app/(dashboard)/cost/page.tsx` | `/dashboard/cost` | `(dashboard)/layout.tsx` | yes |
| `/batch` | `app/(dashboard)/batch/page.tsx` | `/dashboard/batch` | `(dashboard)/layout.tsx` | yes |
| `/batch/[id]` | `app/(dashboard)/batch/[id]/page.tsx` | `/dashboard/batch/[id]` | `(dashboard)/layout.tsx` | no |
| `/reconstruct` | `app/(dashboard)/reconstruct/page.tsx` | `/dashboard/reconstruct` | `(dashboard)/layout.tsx` | "Image to 3D" |
| `/analyses/[id]` | `app/(dashboard)/analyses/[id]/page.tsx` | `/dashboard/analyses/[id]` | `(dashboard)/layout.tsx` | no |
| `/keys` | `app/(dashboard)/keys/page.tsx` | `/dashboard/keys` | `(dashboard)/layout.tsx` | **no** (URL-only) |
| `/dashboard/analyses` | `app/dashboard/analyses/page.tsx` → re-exports `(dashboard)/page` | — | `(dashboard)/layout.tsx` | no (2nd copy of the quota dashboard) |
| `/label` | `app/label/page.tsx` | — | **none** (own full-screen `<main>`) | **no** |
| `/docs` | `app/docs/page.tsx` | — | **own bespoke header** | no |
| `/signup` | `app/(auth)/signup/page.tsx` | `/auth/signup` (redirect shim) | none (centered card) | no |
| `/magic/verify` | `app/(auth)/magic/verify/page.tsx` | — | server redirect only | no |
| `/s/[shortId]` | `app/s/[shortId]/page.tsx` | — | **own minimal public layout** | no (public share) |
| `/scalar` | `app/scalar/route.ts` | — | redirect to backend `/docs` | "API Docs" link |
| `/` (unauth) | `app/page.tsx` `LandingPage` | — | **own bespoke header** | n/a |

Root files: `app/layout.tsx` (root HTML + fonts + Toaster), `app/globals.css` (tokens), `app/error.tsx` + `app/global-error.tsx` (root error boundaries), `app/(dashboard)/error.tsx` (dashboard error boundary).

### 1b. Distinct "screen archetypes" (each looks like a different app)

1. **Marketing landing** (`app/page.tsx` → `LandingPage`): white sticky header, hero, demo dropzone, "How it works" 3-step, footer. `max-w-7xl`/`max-w-3xl`. Buttons `rounded-lg` `bg-blue-600`.
2. **localStorage "Dashboard"** (`app/page.tsx` → `Dashboard`, shown when `localStorage.cadverify_api_key` exists): a *second, different* white header with a `RulePackSelector` and single-file upload → `AnalysisDashboard`. **This is not the same screen as `(dashboard)/page.tsx`.**
3. **Quota/History dashboard** (`app/(dashboard)/page.tsx`): `max-w-3xl` text-link nav, `QuotaDisplay` + `AnalysisHistoryTable`. `text-2xl font-semibold` heading.
4. **Cost decision tool** (`app/(dashboard)/cost/page.tsx` + `CostDecisionCard.tsx`): the **most polished** surface — sticky options rail, glass-box driver breakdown with provenance tags, recommendation table. `rounded-xl` cards.
5. **Wizard** (`app/(dashboard)/reconstruct/page.tsx`): `upload → processing → preview` step machine, `rounded-md` bordered sections, spinner.
6. **Labeling workstation** (`app/label/page.tsx`): full-bleed `bg-gray-50` 70/30 split, keyboard-driven, ontology buttons, its own header — **no app nav at all**.
7. **Batch ops** (`app/(dashboard)/batch/*`): upload form + status table with status pills + polling progress bar.
8. **API keys / settings** (`app/(dashboard)/keys/page.tsx`): server component, `bg-black` buttons, `rounded` (no suffix) — visually unlike every other surface.
9. **Public share** (`app/s/[shortId]/page.tsx`): server-rendered read-only report, `bg-black` CTAs, its own verdict palette.
10. **Docs** (`app/docs/page.tsx`): dark code blocks, its own header.

Ten archetypes, ten visual languages.

---

## 2. Component Inventory

There is **no `components/ui` primitives layer**. Every "Button", "Card", "Badge", "StatCard", "Modal", "DropZone", and color map is re-declared inline per file.

### Shared components (`frontend/src/components/`)
| File | Role | Notable styling / smell |
|---|---|---|
| `AnalysisDashboard.tsx` | DFM results renderer (verdict banner, geometry stat grid, features, issues, process cards, fixes, citations) | Owns `VERDICT_STYLES` + a **21-entry `PROCESS_LABELS` map** (duplicated, see Cost). High quality. |
| `CostDecisionCard.tsx` | **North-star** glass-box cost/make-vs-buy card | Its own copy of `PROCESS_LABELS`; provenance tag system (MEASURED/USER/DEFAULT). Best-designed file in the repo. |
| `ProcessScoreCard.tsx` | Per-process suitability card w/ score bar | Own `VERDICT_COLORS` map (3rd verdict palette). `rounded-xl`. |
| `IssueList.tsx` | Severity-coded issue rows + citation parser | Own `SEVERITY_ICON` + `CITATION_COLORS` maps. `rounded-lg`. |
| `FeaturesList.tsx` | Detected-feature groups (hole/pocket/…) | Own 11-entry `KIND_CONFIG` color map; ASCII "icons" (`O`,`U`,`=`). `rounded-lg`/`rounded-md`. |
| `AnalysisHistoryTable.tsx` | Paginated history table | Own `VERDICT_BADGE` map (4th verdict palette); rows route to **`/dashboard/analyses/[id]`** (legacy URL). |
| `QuotaDisplay.tsx` | Rate-limit progress bars | Own `usageColor` thresholds (green/yellow/red). |
| `ModelViewer.tsx` | **Viewer #1** — STL from `File` (R3F) | `rounded-xl`, gradient bg, blue `#6b8cce` material, studio env. |
| `FileDropZone.tsx` | CAD dropzone | **`rounded-2xl`** (only file in repo using it), upload SVG. |
| `RulePackSelector.tsx` | Dropdown w/ pack badges | Own `PACK_COLORS` map; `rounded-lg` trigger, `rounded-xl` menu. |
| `ShareButton.tsx` / `ShareModal.tsx` | Share toggle + link modal | Modal CTA is **`bg-black`**; `rounded-md`/`rounded-lg`. |
| `RevealOnceModal.tsx` | One-time API-key reveal | **`bg-black`** button, `bg-neutral-*` grays (everything else uses `gray-*`). |
| `RepairButton.tsx` | Mesh-repair trigger | Outline-blue button (`border border-blue-600`) — yet another button style. |
| `RepairComparison.tsx` | Before/after analysis | `bg-green-600` download button (5th button color). Reuses `AnalysisDashboard`. |
| `PdfDownloadButton.tsx` | PDF export | Gray outline + `shadow-sm` (only component using shadow on a button). |
| `batch/BatchUploadForm.tsx` | ZIP/S3 batch upload form | Own dropzone (`rounded-xl`) **duplicating `FileDropZone`**; focus-ring inputs found nowhere else. |
| `batch/BatchItemsTable.tsx` | Batch item rows | Own status color map. |
| `batch/BatchProgressBar.tsx` | Polling progress + ETA | Own `STATUS_COLORS` map (duplicate of `batch/page.tsx`'s `STATUS_BADGES`). |

### Route-local components
| File | Role | Smell |
|---|---|---|
| `(dashboard)/reconstruct/components/MeshCanvas.tsx` | **Viewer #2** — STL from URL (R3F) | ~90% duplicate of `ModelViewer.tsx` minus the `File` plumbing. |
| `(dashboard)/reconstruct/components/MeshPreview.tsx` | 70/30 result layout | `bg-blue-600` CTA. |
| `(dashboard)/reconstruct/components/ImageUploader.tsx` | Multi-image dropzone | **3rd dropzone implementation**; `rounded-lg`; remove-buttons use `bg-black/60`. |
| `(dashboard)/reconstruct/components/ReconstructionProgress.tsx` | Polling spinner + estimated bar | Own spinner (4-px blue ring) ≠ landing/cost spinner (2-px). |
| `(dashboard)/reconstruct/components/ConfidenceBadge.tsx` | High/med/low badge | Own level palette. |
| `label/CorpusViewer.tsx` | STL viewer for labeler | **Imports `MeshCanvas` from the reconstruct route** — a cross-surface dependency on another feature's internal component. |

### Lib
`lib/api.ts` (main client, reads `localStorage.cadverify_api_key`), `lib/api/batch.ts`, `lib/api-base.ts` (origin resolution), `lib/ontology.ts` (6-button label ontology), `lib/stl-validation.ts`.

---

## 3. Cohesion Diagnosis — concretely *where* it's Frankenstein

### A. There is no navigation shell — and the one nav that exists is broken
`app/(dashboard)/layout.tsx` is the *only* nav, and it is a 30-line strip:
```
NAV_ITEMS = [ Dashboard "/", Cost "/cost", Batch "/batch", Image to 3D "/reconstruct" ]
<div className="mx-auto max-w-3xl ...">  // 768px — far too narrow for an enterprise data tool
  <nav> plain text links, no logo, no active state, no user/account menu </nav>
```
Breakages:
- **No active-route highlighting**, no logo/wordmark, no account/org/sign-out, no env/key indicator.
- **`max-w-3xl` (768px)** clamps every authed page — the cost driver table, batch table, and history table are all squeezed; the marketing landing meanwhile uses `max-w-7xl` (1280px). Container width is inconsistent across the app: `max-w-7xl ×4`, `max-w-4xl ×4`, `max-w-3xl ×3`, `max-w-2xl ×3`, plus `md/sm/xs`.
- **Keys, Analyses/History, Label, Docs are absent from the nav.** `/keys` is reachable only by typing the URL or via the post-magic-link redirect. `/label` has zero path back into the app.
- The nav links to bare URLs (`/cost`), but `AnalysisHistoryTable` links to `/dashboard/analyses/[id]`, so a user ping-pongs between the two URL namespaces mid-session.

### B. Root route collision: `/` resolves to two different pages
Both `app/page.tsx` and `app/(dashboard)/page.tsx` compile to path **`/`** (verified in `.next/app-path-routes-manifest.json`: `"/(dashboard)/page": "/"` **and** `"/page": "/"`). These render completely different screens (marketing/localStorage-dashboard vs quota/history dashboard). The nav's "Dashboard" link points at `/`, so its destination is ambiguous/unstable. This is a genuine App-Router parallel-page conflict, not just a style issue.

### C. Two different "dashboards" that share a name but nothing else
- `app/page.tsx`'s `Dashboard()` = white header + `RulePackSelector` + single-upload → `AnalysisDashboard`.
- `app/(dashboard)/page.tsx` = `QuotaDisplay` + `AnalysisHistoryTable`.
They have different headers, different widths, different type scales, and no link between them. A user has no mental model of "the dashboard."

### D. Authentication is client-only and detected three different ways
Auth = presence of `localStorage.cadverify_api_key`. It is checked via raw `localStorage.getItem` in `app/page.tsx:405` and `lib/api.ts:197`, and via a `hasApiKey()` helper in `cost/page.tsx`. There is no auth context/provider, no route protection — `(dashboard)` pages render regardless; data calls just fail. The landing↔dashboard swap in `app/page.tsx` runs in a `useState` initializer (SSR returns `false`), causing a guaranteed hydration/flash.

### E. Typography: the global font is unset boilerplate
`app/layout.tsx` loads Geist Sans/Mono and exposes `--font-geist-*`, and `globals.css` maps them to `--font-sans`/`--font-mono` — **but `globals.css:25` then hard-codes `body { font-family: Arial, Helvetica, sans-serif; }`**, overriding Geist. The app effectively renders in **Arial**. No font utility (`font-sans`) is applied anywhere. `globals.css` is otherwise the untouched Next starter (only `--background`/`--foreground`, plus a `prefers-color-scheme: dark` block that nothing else honors — every screen hard-codes `bg-white`/`bg-gray-50`, so dark mode would half-apply and break contrast).

There is **no type scale**: headings are ad-hoc per page — `text-4xl` (landing hero), `text-3xl` (docs/dashboard-empty), `text-2xl` (cost/batch/keys), `text-xl` (landing header/label), `text-lg` (section headers). No shared heading component or token.

### F. Color & status vocabulary is re-declared 9+ times with drift
Independent verdict/severity/status color maps live in: `AnalysisDashboard.tsx`, `ProcessScoreCard.tsx`, `AnalysisHistoryTable.tsx`, `IssueList.tsx`, `FeaturesList.tsx`, `s/[shortId]/page.tsx`, `batch/page.tsx`, `batch/BatchProgressBar.tsx`, `reconstruct/.../ReconstructionProgress.tsx`. They disagree:
- Verdict labels: `AnalysisDashboard` & share page say **"Manufacturable / Issues Found / Not Manufacturable"**; `AnalysisHistoryTable` says **"Pass / Issues / Fail"**; `ProcessScoreCard` shows **"PASS / ISSUES / FAIL"**. Same concept, three vocabularies.
- Grays: almost everything uses `gray-*`, but `keys/page.tsx` + `RevealOnceModal` use `neutral-*`.
- **Primary action color is not decided.** `bg-blue-600` in 13 files; `bg-black` in 6 (`keys`, `signup`, `ShareModal`, `RevealOnceModal`, share-page CTAs, image-remove); plus outline-blue (`RepairButton`) and `bg-green-600` (`RepairComparison`). An enterprise buyer sees blue here, black there, on adjacent screens.
- `PROCESS_LABELS` (the 21-process display-name map) is **copy-pasted** in `AnalysisDashboard.tsx` and `CostDecisionCard.tsx` (the latter even comments "kept in sync with…", i.e. manual sync).

### G. Radius / spacing drift (no scale)
Border-radius counts across the codebase: **`rounded-md ×74`, `rounded-lg ×27`, `rounded` ×27, `rounded-full ×25`, `rounded-xl ×24`, `rounded-2xl ×1`.** Cards are `rounded-xl` on the cost/analysis surfaces but `rounded-md` on dashboard/batch/reconstruct sections; the CAD dropzone is the lone `rounded-2xl`; keys/signup use bare `rounded`. Section padding is equally ad-hoc (`p-3`/`p-4`/`p-5`/`p-6`/`p-8`/`p-12`). There is no spacing or radius token.

### H. Duplicated / one-off components
- **Three dropzones**: `FileDropZone.tsx`, `batch/BatchUploadForm.tsx` (inline), `reconstruct/.../ImageUploader.tsx` — three different paddings, radii, drag-state styles, and icons.
- **Two STL viewers**: `ModelViewer.tsx` (File) and `reconstruct/.../MeshCanvas.tsx` (URL) — near-identical R3F setups; the label tool reaches across surfaces to reuse `MeshCanvas`.
- **Two modals** (`ShareModal`, `RevealOnceModal`) re-implement the same `fixed inset-0 ... bg-black/40` dialog pattern independently (no `<Modal>` primitive).
- **Two spinners** (2-px ring on landing/cost vs 4-px ring in `ReconstructionProgress`).
- **Two status-pill maps for batch** (`batch/page.tsx` `STATUS_BADGES` vs `BatchProgressBar` `STATUS_COLORS`).

### I. Mismatched interaction patterns across the core surfaces
| Concern | `/` Dashboard | `/cost` | `/reconstruct` | `/label` | `/batch` |
|---|---|---|---|---|---|
| Upload UX | full-page dropzone | options-first then dropzone | multi-image grid + submit btn | (pre-seeded corpus) | ZIP/S3 form |
| Layout on result | 2-col sticky viewer | 2-col sticky options rail | 70/30 result | 70/30 viewer | table |
| Progress feedback | inline 2-px spinner | inline 2-px spinner | dedicated step + 4-px spinner + bar | none | polling bar + ETA |
| "Start over" copy | "New Analysis" | "New part" | "Start New Reconstruction" | "Reload queue" | n/a |
| Error display | red box | red box (2 variants) | red box + "Try Again" | red bar | toast only |
| Nav back | header | header | in-page button | none | `← Back to batches` |

Four core surfaces, four different upload/result/error idioms and four different "reset" labels.

### J. Empty / loading / error state gaps
- **Inconsistent loading**: skeleton/`animate-pulse` (`batch`, `BatchProgressBar`), spinners (landing/cost/reconstruct), plain "Loading…" text (`/label`, `analyses/[id]`, viewers). No shared `<Spinner>`/`<Skeleton>`.
- **Inconsistent errors**: inline red banners (≥3 visually different variants), `toast.error` only (`batch` create), a Sentry-wired retry boundary (`(dashboard)/error.tsx`), and silent swallow (`batch/page.tsx` catch → empty table with no message; `RulePackSelector` returns `null` on error).
- **Empty states** exist but are bare one-liners ("No analyses yet…", "No parts in the corpus queue…") with no illustration, CTA hierarchy, or consistent styling.
- **No global 404 design** (`/_not-found` is the framework default).
- Hydration flash on `app/page.tsx` auth swap (state initializer pattern).

---

## 4. Reusable / Salvageable vs Needs-Rework

### Keep as the quality bar / extract upward (salvageable)
- **`CostDecisionCard.tsx`** — the north star. Its provenance-tag system, decision-first hierarchy, recommendation table, and Σ-coherence check are exactly the "glass-box, transparent" positioning. Use it to derive the shared **Card / Badge / StatCard / Table / SectionHeader** primitives.
- **`AnalysisDashboard.tsx`** — solid information design; a sibling to the cost card. Promote its verdict banner + geometry stat grid into shared components.
- **3D viewers** (`ModelViewer` + `MeshCanvas`) — keep the R3F approach; **merge into one `<CadViewer src={File|url}>`**.
- **Data plumbing** — `lib/api.ts`, `lib/api/batch.ts`, `lib/api-base.ts`, `lib/ontology.ts` are clean and presentation-agnostic; untouched by a redesign.
- **Polling components** (`BatchProgressBar`, `ReconstructionProgress`) — logic is good; restyle only.
- **`/s/[shortId]` server share page** — good SSR/OG-meta structure; reskin to the design system.

### Rework / unify
- **Routing**: delete the `app/dashboard/*` re-export shims; resolve the `/` collision (landing vs dashboard); pick ONE URL namespace; single source of truth for "analysis detail" links.
- **Shell**: build one `AppShell` (logo, primary nav incl. Label/History/Keys/Docs, active state, account menu, consistent max-width) and put **every authed surface** in it — including `/label`, which is currently orphaned.
- **Tokens**: introduce a real token layer in `globals.css` (Tailwind v4 `@theme`) for color (incl. ONE primary + ONE status palette), type scale, spacing, radius; **delete the `Arial` body override** and actually apply Geist (or chosen brand font).
- **Primitives**: create `components/ui/{Button,Card,Badge,StatCard,Table,DropZone,Modal,Spinner,Skeleton,EmptyState,PageHeader}` and replace the inline re-declarations.
- **De-duplicate**: 3 dropzones → 1; 9 status-color maps → 1 status module; 2 `PROCESS_LABELS` → 1 shared map; 2 modals → 1; verdict vocabulary → 1 canonical label set.
- **Auth**: single source of truth (context/provider) + consistent gating; remove the hydration-flashing landing/dashboard swap.
- **States**: standardize loading (one spinner + one skeleton), errors (one banner + toast policy), and empty states (one `EmptyState` with CTA).

---

## 5. Current Information Architecture (how a user moves today) + breakages

```
                         (unauth)                         (auth = localStorage.cadverify_api_key present)
  ┌────────────────────────────────────────┐      ┌──────────────────────────────────────────────────┐
  │  /  app/page.tsx → LandingPage          │      │  /  app/page.tsx → Dashboard (white hdr+RulePack) │
  │   header: Docs | Get API Key            │      │   …and ALSO /  (dashboard)/page (Quota+History)   │  ← ROUTE COLLISION
  │   hero → demo dropzone → AnalysisDash    │      │   nav strip: Dashboard | Cost | Batch | Image→3D  │
  │   footer: API Docs(/scalar) Quickstart   │      └───────────────┬──────────────────────────────────┘
  └───────────┬──────────────────────────────┘                     │ (nav links → bare URLs)
              │ Get API Key                                          ├── /cost      → CostDecisionCard
              ▼                                                      ├── /batch     → /batch/[id] (← Back to batches)
  /signup (Google or magic link) ── magic ──▶ /magic/verify ──▶ /dashboard/keys   ├── /reconstruct → /analyses/[id] (bare)
              │                                  (backend 303)        │                  └── Quota+History → /dashboard/analyses/[id] (legacy)
              ▼                                                       │
  /docs (own header) ── /scalar (→ backend docs)         /keys  (NOT in nav; URL-only)
                                                          /label (NOT in nav; NO shell; no way back)
                                                          /s/[shortId] (public; own layout; bg-black CTAs → "/")
```

**IA breakages (concrete):**
1. **`/` is ambiguous** — collides between landing/localStorage-dashboard (`app/page.tsx`) and quota dashboard (`app/(dashboard)/page.tsx`). "Dashboard" in the nav has no stable destination.
2. **Dual URL namespace** — every authed surface is reachable at `/x` and `/dashboard/x`; internal links mix the two (`AnalysisHistoryTable` → `/dashboard/analyses/[id]`; analysis "Back to dashboard" → `/dashboard`; reconstruct → `/analyses/[id]`). Users cross namespaces silently; back-button history is muddy.
3. **Orphaned surfaces** — `/label`, `/keys`, the history/analyses list, and `/docs` are not in the nav. `/label` (a strategically important ground-truth surface for the AV/automotive story) has **no shell and no link back** into the product; you must know the URL.
4. **Two competing dashboards** with the same name and no link between them.
5. **No global wayfinding** — no breadcrumbs, no logo-home, no active state, no account/org switcher, no "where am I." A Head of Manufacturing landing on `/cost` cannot discover `/batch`, `/label`, or history without guessing.
6. **Auth is invisible & flashing** — no signed-in indicator, no sign-out, client-only gating, and a hydration flash on `/`.
7. **`/docs` and the landing each carry their own header**, so the top-of-page chrome changes shape as you move between public surfaces.

---

### Bottom line for the synthesis step
The skeleton (data layer, routes, the two analysis/cost cards, the R3F viewer) is sound and worth keeping. What makes it read as a Frankenstein is the **absence of three layers**: (1) a **token layer** (one font that actually applies, one primary color, one status palette, one type/spacing/radius scale), (2) a **primitive layer** (Button/Card/Badge/Table/DropZone/Modal/Spinner/EmptyState/PageHeader), and (3) a **shell + IA layer** (one nav that includes every surface, one URL namespace, a resolved `/`, and consistent cross-links). Adding those three layers — and deleting the `dashboard/*` shims, the `Arial` override, the duplicate dropzones/viewers/color-maps — converts ten visual languages into one product without rewriting the working internals.
