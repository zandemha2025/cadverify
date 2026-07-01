# CadVerify — Design-System Spec (buildable, zero-ambiguity)

**Author:** Design-System Architect.
**Status:** AUTHORITATIVE BUILD SPEC. Expands the LOCKED `design-direction.md`; it does **not** re-decide it.
**Audience:** the Foundation builder + two Screen builders. They ship from this **with zero design decisions**.
**Stack (verified):** Next.js 16.2.3 App Router · React 19.2.4 · TypeScript · Tailwind v4 (CSS-first `@theme`, **no** `tailwind.config.js`) · Three.js/R3F · sonner · Sentry. Frontend root: `/Users/nazeem/Desktop/developer/cadverify/frontend`.

> **Next 16 caveat (load-bearing):** this is NOT the Next.js in your training data. Before writing routing/layout code, read `node_modules/next/dist/docs/01-app/**`. Confirmed facts used below: route groups `(x)` add **no** URL segment; two routes resolving to the same path is a hard error (this is the `/` collision); request-time redirects come from `next.config.ts` `redirects()` or `proxy.ts` (renamed from `middleware.ts`) — and `proxy.ts` **cannot read `localStorage`**, so auth gating is **client-side** (§5.6).

---

## 0. The cohesion law (the Auditor enforces — violating any line fails the cycle)

1. **One of each primitive.** Every button/card/badge/table/input/select/tabs/dialog/toast/empty/skeleton/spinner/dropzone/viewer comes from `components/ui/*` (§4). No inline `<button className="bg-blue-600…">`, no inline cards, no per-file dialogs. If you need a variant, add it to the primitive's `cva` — never re-roll.
2. **One status/process source.** All verdict/severity/status/process colors+labels come from `lib/status.ts` (§3). The 9+ existing maps are deleted. No new color map may be declared in a component.
3. **One token layer.** Color/type/space/radius/shadow come from the `@theme` in `globals.css` (§2) via semantic utilities (`bg-card`, `text-foreground`, `border-border`, `bg-primary`, `text-pass`…). No raw hex in components. Numbers use `font-mono tabular-nums`.
4. **One shell, one route tree.** Every authed surface lives inside the single `(app)` shell (§5). No second nav, no `max-w-3xl` document column, no per-page header chrome (except the public landing/docs/share, which still consume tokens).
5. **No Arial.** The `body { font-family: Arial }` override is deleted (§2.4). UI = Geist Sans, numbers = Geist Mono.
6. **Don't break the build or the demo.** `npm run build` and `npx tsc --noEmit` stay green; `/cost` and `/analyze` still run their **demo** routes with no API key (`hasApiKey()` switch, §6.4 / §5.6); the 3D viewers still render. Frontend only — never touch `backend/` or `data/`. No git commit.

---

## 1. Pinned stack decisions (no further deliberation)

| Decision | PINNED |
|---|---|
| Component primitives | **Hand-vendored shadcn/ui source on Radix** — copy the canonical shadcn component source into `components/ui/*`, do **NOT** run `npx shadcn init`. Rationale: `shadcn init` rewrites `globals.css`/config and assumes its own token block; on our Tailwind-v4 CSS-first `@theme` + Next 16 + custom token layer it would clobber §2 and is network-fragile in CI. We use the *same owned code* shadcn would emit, placed by hand, themed by our tokens. |
| Class utility | `cn()` = `clsx` + `tailwind-merge` at `lib/utils.ts`. |
| Variants | `class-variance-authority` (`cva`). |
| Icons | `lucide-react` (single stroke family). |
| Data tables | `@tanstack/react-table` (headless) + our `components/ui/table.tsx` skin + `components/ui/data-table.tsx` wrapper. |
| Charts | **Recharts** (`recharts`) for the breakeven curve (§6.2). One chart lib only. |
| Toasts | **sonner** (already installed) — keep the single `<Toaster>` in `app/layout.tsx`. |
| 3D | Keep `@react-three/fiber` + `drei`. Merge the two viewers into ONE `components/ui/cad-viewer.tsx` (§4.7). |
| Dark mode | **Out of scope for v1.** Ship light only. Author tokens so a future `.dark` block can override the same semantic vars (§2.6) — but do not wire a toggle now. Remove the dead `@media (prefers-color-scheme: dark)` block. |

**Exact deps the Foundation builder adds** (pin majors; let npm resolve patches):
```
npm i class-variance-authority clsx tailwind-merge lucide-react @tanstack/react-table recharts \
  @radix-ui/react-slot @radix-ui/react-tabs @radix-ui/react-dialog @radix-ui/react-select \
  @radix-ui/react-tooltip @radix-ui/react-label @radix-ui/react-slider @radix-ui/react-dropdown-menu
```
(Checkbox/Switch/Popover Radix packages may be added if a screen needs them; none required for v1.)

---

## 2. TOKENS — `frontend/src/app/globals.css` (replace the file entirely)

Tailwind v4 reads colors/sizes from `@theme` as CSS variables; **any color in `@theme --color-*` becomes a utility** (`--color-pass` → `bg-pass`/`text-pass`/`border-pass`). Values are hex for unambiguous copy-paste (OKLCH equivalents are fine but not required).

### 2.1 Full file (authoritative — write this verbatim, then verify `npm run build`)

```css
@import "tailwindcss";

@theme {
  /* ----- Fonts (FIXES the Arial bug) ----- */
  --font-sans: var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-geist-mono), ui-monospace, "SF Mono", monospace;

  /* ----- Neutral ramp = slate (cool, reads "engineering/CAD") ----- */
  --color-neutral-0:   #ffffff;
  --color-neutral-50:  #f8fafc;
  --color-neutral-100: #f1f5f9;
  --color-neutral-200: #e2e8f0;
  --color-neutral-300: #cbd5e1;
  --color-neutral-400: #94a3b8;
  --color-neutral-500: #64748b;
  --color-neutral-600: #475569;
  --color-neutral-700: #334155;
  --color-neutral-800: #1e293b;
  --color-neutral-900: #0f172a;
  --color-neutral-950: #020617;

  /* ----- Accent = steel/technical BLUE (LOCKED: not indigo, not loud) ----- */
  --color-primary-50:  #eff6ff;
  --color-primary-100: #dbeafe;
  --color-primary-200: #bfdbfe;
  --color-primary-300: #93c5fd;
  --color-primary-400: #60a5fa;
  --color-primary-500: #3b82f6;
  --color-primary-600: #2563eb;  /* PRIMARY: buttons, active nav, links, focus ring, the ONE hero number */
  --color-primary-700: #1d4ed8;  /* hover/pressed */
  --color-primary-800: #1e40af;

  /* ----- Semantic status (3 stops each: solid / subtle-bg / border) ----- */
  --color-pass:    #059669;  --color-pass-bg:    #ecfdf5;  --color-pass-border:    #a7f3d0;
  --color-warn:    #d97706;  --color-warn-bg:    #fffbeb;  --color-warn-border:    #fde68a;
  --color-fail:    #dc2626;  --color-fail-bg:    #fef2f2;  --color-fail-border:    #fecaca;
  --color-info:    #0284c7;  --color-info-bg:    #f0f9ff;  --color-info-border:    #bae6fd;

  /* ----- Semantic surface/text aliases (what components actually use) ----- */
  --color-canvas:            #f8fafc;  /* app background behind cards */
  --color-background:        #ffffff;  /* alias kept for any boilerplate ref */
  --color-card:              #ffffff;
  --color-card-foreground:   #0f172a;
  --color-muted:             #f1f5f9;  /* table header, inset, nested panel */
  --color-muted-foreground:  #475569;
  --color-foreground:        #0f172a;  /* primary text */
  --color-secondary:         #f1f5f9;  /* secondary button bg */
  --color-secondary-foreground: #0f172a;
  --color-border:            #e2e8f0;  /* hairline 1px */
  --color-border-strong:     #cbd5e1;  /* inputs, emphasized dividers */
  --color-input:             #cbd5e1;
  --color-ring:              #2563eb;  /* focus ring */
  --color-primary-foreground: #ffffff;
  --color-destructive:       #dc2626;
  --color-destructive-foreground: #ffffff;

  /* ----- Provenance (glass-box tags — single source for CostDecisionCard) ----- */
  --color-prov-measured:    #1d4ed8;  --color-prov-measured-bg: #eff6ff;  --color-prov-measured-border: #bfdbfe;
  --color-prov-user:        #059669;  --color-prov-user-bg:     #ecfdf5;  --color-prov-user-border:     #a7f3d0;
  --color-prov-default:     #475569;  --color-prov-default-bg:  #f1f5f9;  --color-prov-default-border:  #e2e8f0;

  /* ----- Type scale: custom hero sizes; rest uses built-in xs/sm/base/lg/xl/2xl ----- */
  --text-display:    1.75rem;  /* 28px — hero metric (unit cost / lead time) */
  --text-display--line-height: 2.25rem;
  --text-display-xl: 2rem;     /* 32px — marketing / empty-state only */
  --text-display-xl--line-height: 2.5rem;

  /* ----- Radius: ONE base (LOCKED ~6-8px). 6px everywhere; full for pills/dots ----- */
  --radius-sm: 4px;   /* badges, small chips */
  --radius:    6px;   /* DEFAULT — buttons, inputs, cards, menus, dialogs */
  --radius-lg: 8px;   /* large panels/modals only */

  /* ----- Shadows: flat-with-borders; only two ----- */
  --shadow-sm: 0 1px 2px 0 rgb(15 23 42 / 0.06);
  --shadow-md: 0 4px 12px -2px rgb(15 23 42 / 0.12);

  /* ----- Shell metrics ----- */
  --sidebar-w: 256px;
  --sidebar-rail-w: 64px;
  --topbar-h: 56px;
}

/* base layer */
body {
  background: var(--color-canvas);
  color: var(--color-foreground);
  font-family: var(--font-sans);   /* NO Arial */
}

/* numbers: any element tagged .num or a <td>/<dd> with the class gets tabular mono */
.num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
```

### 2.2 Type scale — role → utility recipe (single source; components use these strings)
| Role | Utilities | Use |
|---|---|---|
| `caption` | `text-xs leading-4 text-muted-foreground` | badge text, table meta, helper |
| `body-sm` | `text-sm leading-[18px]` | table cells, secondary copy |
| `body` | `text-sm leading-5` | default body |
| `body-lg` | `text-base leading-6` | lead paragraph |
| `eyebrow` | `text-xs font-semibold uppercase tracking-wide text-muted-foreground` | section eyebrow / label |
| `h-card` | `text-base font-semibold leading-[22px] text-foreground` | card title |
| `h-page` | `text-xl font-semibold leading-7 text-foreground` | page title |
| `h-display` | `text-display font-semibold num text-foreground` | the ONE hero number per card |
| `h-display-xl` | `text-display-xl font-semibold` | marketing / empty hero |

**Rules:** max 2 weights (400/600). Headings never pure black — use `text-foreground` (#0f172a). Numbers in tables/cost = `.num` (mono+tabular), right-aligned. Base UI size = 14px (`text-sm`), NOT 16 — this is the productive-app tell.

### 2.3 Spacing & density (8px grid)
- Card padding `p-6` (24); compact card `p-4` (16); section gap `space-y-6`; page top `py-8`.
- Control heights: default `h-9` (36px), small `h-8` (32px), large `h-11` (44px).
- Table rows: **comfortable (default) 44px** (`h-11`, `py-2.5`), compact 36px (`h-9`, `py-1.5`); ≥16px (`px-4`) cell side padding. Density is a prop on `DataTable` (§4.4), default comfortable.

### 2.4 The Arial fix (explicit)
Delete `body { font-family: Arial, Helvetica, sans-serif }` and the `--background/--foreground:#171717` + `prefers-color-scheme: dark` boilerplate. `app/layout.tsx` already loads Geist via `--font-geist-sans/-mono` and sets them on `<html>`; §2.1's `--font-sans` now actually applies. Verify: computed `body` font-family resolves to Geist, not Arial.

### 2.5 Container width (kills the 768px document)
App content region is fluid; inner content capped at `max-w-screen-2xl` (1536px) with `px-6 lg:px-8` gutters. **No `max-w-3xl` on authed pages.** The marketing landing may keep `max-w-7xl`.

### 2.6 Dark-mode hook (author, don't wire)
Keep all surface/text tokens as `--color-*` semantic aliases (done above) so a future `.dark { --color-canvas:#020617; --color-card:#0f172a; --color-foreground:#f1f5f9; … }` flips the app. Do not add the class or toggle in v1.

---

## 3. The SINGLE status/process module — `frontend/src/lib/status.ts` (NEW)

This file replaces **all** of these existing maps (delete each at its source as you migrate the component):
`AnalysisDashboard` `VERDICT_STYLES`+`PROCESS_LABELS`+`CITATION_COLORS`+`SEVERITY` · `CostDecisionCard` `PROCESS_LABELS`+`PROVENANCE_STYLES` · `AnalysisHistoryTable` `VERDICT_BADGE` · `s/[shortId]` `VERDICT_STYLES`+`SEVERITY_STYLES` · `batch/page` `STATUS_BADGES` · `batch/BatchProgressBar` `STATUS_COLORS` · `batch/BatchItemsTable` (its map) · `ProcessScoreCard` `VERDICT_COLORS` · `IssueList` `SEVERITY_ICON`+`CITATION_COLORS` · `FeaturesList` `KIND_CONFIG` · `RulePackSelector` `PACK_COLORS` · `QuotaDisplay` `usageColor` · `reconstruct/ConfidenceBadge` + `ReconstructionProgress` level maps.

### 3.1 Canonical vocabulary (ONE label set — ends the "Pass/Issues/Fail" vs "Manufacturable/…" drift)
| Domain value(s) | tone | Label (default) | Long label (banner) |
|---|---|---|---|
| `pass` | `pass` | **Pass** | Manufacturable |
| `issues` / `warning` | `warn` | **Advisory** | Issues found |
| `fail` / `error` | `fail` | **Required** | Not manufacturable |
| `info` | `info` | **Info** | — |
| `unknown` | `neutral` | **Unknown** | — |

> Two-tier DFM severity (Protolabs pattern, locked by direction): **Required** (red, must-fix, maps `fail`/`error`) vs **Advisory** (amber, maps `issues`/`warning`). Use these words in the issue list and 3D highlights. The numeric `dfm_score` is shown only as supporting detail, never as the headline.

### 3.2 Module contract (implement exactly this surface)
```ts
export type Tone = "pass" | "warn" | "fail" | "info" | "neutral";

// tone -> the four token-driven class bundles (single source; primitives consume these)
export const TONE: Record<Tone, { solid: string; bg: string; border: string; fg: string; dot: string }> = {
  pass:    { solid: "bg-pass text-white",  bg: "bg-pass-bg",  border: "border-pass-border",  fg: "text-pass",  dot: "bg-pass" },
  warn:    { solid: "bg-warn text-white",  bg: "bg-warn-bg",  border: "border-warn-border",  fg: "text-warn",  dot: "bg-warn" },
  fail:    { solid: "bg-fail text-white",  bg: "bg-fail-bg",  border: "border-fail-border",  fg: "text-fail",  dot: "bg-fail" },
  info:    { solid: "bg-info text-white",  bg: "bg-info-bg",  border: "border-info-border",  fg: "text-info",  dot: "bg-info" },
  neutral: { solid: "bg-neutral-500 text-white", bg: "bg-muted", border: "border-border", fg: "text-muted-foreground", dot: "bg-neutral-400" },
};

// verdict/severity/batch-status/confidence -> {tone,label,Icon}
export function verdictTone(v: "pass"|"issues"|"fail"|"unknown"|string): Tone;     // issues->warn, fail->fail
export function verdictLabel(v: string, long?: boolean): string;                    // §3.1
export function severityTone(s: "error"|"warning"|"info"|string): Tone;            // error->fail, warning->warn
export function batchStatusTone(s: string): Tone;  // pending/cancelled->neutral, extracting->warn, processing->info, completed->pass, failed->fail
export function confidenceTone(level: "high"|"medium"|"low"): Tone;                // high->pass, medium->warn, low->fail
export function usageTone(used: number, limit: number): Tone;                       // <0.7->pass, <0.9->warn, else fail

// the ONE process display-name map (21 entries — copy from CostDecisionCard/AnalysisDashboard, then delete both)
export const PROCESS_LABELS: Record<string,string>;  // fdm:"FDM / FFF", cnc_3axis:"CNC 3-Axis", injection_molding:"Injection Molding", ...
export function procLabel(p: string): string;        // PROCESS_LABELS[p] ?? p

// provenance (glass-box) -> token class bundle (replaces CostDecisionCard PROVENANCE_STYLES)
export const PROVENANCE: Record<"MEASURED"|"USER"|"DEFAULT", string>; // measured->prov-measured-*, user->prov-user-*, default->prov-default-*

// rule-pack / citation domain tints (replaces RulePackBadge + CITATION_COLORS): aerospace->info, automotive->pass, oil_gas->warn, medical->neutral(purple not in palette -> use info)
export function domainTone(name: string): Tone;
```
Icons (lucide): `pass`→`CheckCircle2`, `warn`→`AlertTriangle`, `fail`→`XCircle`, `info`→`Info`, `neutral`→`Circle`. **Status is never color-only** — `StatusBadge` always renders icon + label (§4.3).

---

## 4. COMPONENT LIBRARY — `frontend/src/components/ui/*`

All under `components/ui/`. Each is the vendored shadcn source unless marked CADVERIFY. All consume §2 tokens + §3. Existing feature components (`CostDecisionCard`, `AnalysisDashboard`, `IssueList`, …) are **recomposed onto these** (§7).

### 4.0 `lib/utils.ts`
```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export const cn = (...i: ClassValue[]) => twMerge(clsx(i));
```

### 4.1 `button.tsx` (shadcn Button + cva)
- **Variants:** `primary` (`bg-primary text-primary-foreground hover:bg-primary-700`), `secondary` (`bg-card border border-border hover:bg-muted`), `ghost` (`hover:bg-muted`), `destructive` (`bg-destructive text-destructive-foreground hover:bg-red-700`), `link` (`text-primary underline-offset-4 hover:underline`).
- **Sizes:** `sm h-8 px-3 text-xs`, `md h-9 px-4 text-sm` (default), `lg h-11 px-6 text-sm`, `icon h-9 w-9`.
- **States:** focus → `focus-visible:ring-2 ring-ring ring-offset-2`; disabled → `opacity-50 pointer-events-none`; **loading** → `loading?:boolean` prop renders leading `<Loader2 className="animate-spin"/>` + `aria-busy`, disables. `asChild` via `@radix-ui/react-slot`.
- Radius: `rounded-[var(--radius)]`. **This is the ONLY button.** Deletes every `bg-blue-600`/`bg-black`/`bg-green-600`/outline-blue button across the app (13+ blue, 6 black, …).

### 4.2 `card.tsx` (CADVERIFY, derived from CostDecisionCard's idiom)
`Card` (`rounded-[var(--radius)] border border-border bg-card`), `CardHeader`, `CardTitle` (`h-card`), `CardDescription` (`caption`), `CardContent` (`p-6`, compact `p-4`), `CardFooter`. Variant `tone?: Tone` tints header strip (`TONE[tone].bg` + `border`) for decision/alert cards. **MetricCard** sub-export: `label` (eyebrow) + `value` (`h-display .num`) + optional `delta`/`unit`/`hint` — for the KPI row (unit cost, lead time, process, confidence).

### 4.3 `badge.tsx` / `status-badge.tsx` (CADVERIFY)
- `Badge` cva: `variant` = `neutral|outline|primary` + `size sm|md`, `rounded-sm`.
- **`StatusBadge`** (the consolidator): props `{ tone?: Tone, verdict?, severity?, status?, confidence?, label?, icon?: boolean }`. Resolves tone+label+Icon via §3, renders `TONE[tone].bg TONE[tone].fg TONE[tone].border` + leading lucide icon + label. **Every verdict/severity/batch-status/confidence pill in the app is this** (replaces 6+ pill maps). Icon defaults on; `icon={false}` for dense table cells (still shows a colored `dot` + label so it's never color-only).

### 4.4 `table.tsx` + `data-table.tsx`
- `table.tsx`: shadcn `Table/TableHeader/TableBody/TableRow/TableHead/TableCell` skin — sticky header `bg-muted`, `border-b border-border`, hover `hover:bg-muted/60`, numeric cells `text-right num`.
- `data-table.tsx` (CADVERIFY, TanStack): props `{ columns, data, density?: "compact"|"comfortable", onRowClick?, emptyState, loading? }`. Sortable headers, optional pagination, right-aligned numeric columns (mono), density via row-height class. Used by **History, Batch list, Batch items, Keys** (replaces the 4 hand-rolled `<table>`s). Loading → `TableSkeleton` rows; empty → `EmptyState`.

### 4.5 Inputs
- `input.tsx`, `textarea.tsx`: `h-9 rounded-[var(--radius)] border border-input bg-card px-3 text-sm focus-visible:ring-2 ring-ring`; error variant `border-fail`. Label above via `label.tsx` (Radix), helper/error below (`caption`, error `text-fail`).
- `select.tsx`: Radix Select skin (trigger `h-9`, content `bg-card border shadow-md rounded-[var(--radius)]`). Replaces the raw `<select>`s in `/cost` OptionsForm, history filter, `RulePackSelector`.
- `slider.tsx`: Radix Slider — track `bg-muted`, range `bg-primary`, thumb `border-primary`. **Required for the quantity slider (§6.3).**
- `field.tsx` (CADVERIFY tiny helper): `{label, htmlFor, error, hint, children}` → consistent label/control/error stack. `NumberField` variant: mono value + unit suffix.

### 4.6 Overlays & feedback
- `tabs.tsx`: Radix Tabs, **underline** style (active `border-b-2 border-primary text-foreground`, inactive `text-muted-foreground`). Used by the part workspace (§5.5) and any in-object view switch.
- `dialog.tsx` + `alert-dialog.tsx`: Radix Dialog — overlay `bg-neutral-900/40`, content `bg-card rounded-lg shadow-md`. **Replaces both `ShareModal` and `RevealOnceModal`** (the two hand-rolled `fixed inset-0` modals). `AlertDialog` for destructive confirm (revoke key).
- `tooltip.tsx` + `popover.tsx`: Radix — the **glass-box "why?"** affordance. Any derived number may wrap in `<WhyTooltip inputs={…}>` showing provenance/assumptions (mono). Contract, not ad-hoc.
- `toast`: keep sonner `<Toaster position="top-right" richColors closeButton>` in `app/layout.tsx`. Policy: transient confirms/errors → toast; structural errors → `ErrorState` card (§4.8).
- `skeleton.tsx`: `bg-muted animate-pulse rounded-[var(--radius)]`; presets `TableSkeleton`, `CardSkeleton`. **Skeletons over spinners** for content load.
- `spinner.tsx`: ONE spinner (`Loader2 animate-spin text-primary`), sizes sm/md — the only spinner (kills the 2px-vs-4px split). Use only for button-loading and short inline waits.
- `progress.tsx` + `progress-steps.tsx` (CADVERIFY): bar (`bg-muted` track, `bg-primary` fill) + staged stepper ("Parsing geometry → Checking manufacturability → Costing") for long jobs — restyle `BatchProgressBar`/`ReconstructionProgress` onto these (logic kept).

### 4.7 `cad-viewer.tsx` (CADVERIFY — merges `ModelViewer` + reconstruct `MeshCanvas`)
ONE R3F viewer. Props: `{ file?: File | null, src?: string, highlightFaces?: number[], ghostUnhighlighted?: boolean, className?: string }`. Loads STL from `File` (objectURL) **or** `src` URL. Keep current camera-fit/lighting/material (`#6b8cce`, studio env, grid). Frame chrome consumes tokens (`rounded-[var(--radius)] border border-border`, `bg-muted` empty state). `highlightFaces` recolors those face indices (`fail` tone) and, when `ghostUnhighlighted`, drops the rest to low opacity — the "spotlight the problem geometry" mode. `label/CorpusViewer` and `/cost`/`/analyze`/reconstruct all use this; delete `ModelViewer.tsx` + `reconstruct/components/MeshCanvas.tsx`.

### 4.8 States primitives (the four-state matrix — every data surface implements all four)
- `empty-state.tsx`: `{icon, title, description, action?}` — icon + one line + ONE primary CTA. Replaces every bare "No analyses yet…" string. Sells the next step.
- `error-state.tsx`: `{title, message, onRetry?}` — inline `fail`-tinted card + retry. Replaces the ≥3 ad-hoc red banners (`ErrorBanner` in `/cost`, the dashboard red boxes, reconstruct "Try Again", label red bar).
- `dropzone.tsx` (CADVERIFY — merges `FileDropZone` + `batch/BatchUploadForm` inner + reconstruct `ImageUploader`): `{ accept, multiple?, onFiles, isLoading, hint }`. ONE dashed-border drag target (`rounded-[var(--radius)] border-2 border-dashed border-border-strong`, drag → `border-primary bg-primary-50`), upload icon, accepted-types hint, disabled/loading. Kills the 3 dropzones (incl. the lone `rounded-2xl`).

### 4.9 Shell components (CADVERIFY — §5)
`app-shell.tsx`, `sidebar.tsx`, `topbar.tsx`, `nav-item.tsx`, `page-header.tsx`, `part-tabs.tsx`, `require-key.tsx`, `auth-provider.tsx`.

---

## 5. APP SHELL + IA (the one route tree)

### 5.1 The route fix — exact file operations (resolves the `/` collision + kills the shim tree)

**DELETE (the legacy `dashboard/*` shim tree — 9 files + the auth shim):**
```
src/app/dashboard/analyses/[id]/page.tsx
src/app/dashboard/analyses/page.tsx
src/app/dashboard/batch/[id]/page.tsx
src/app/dashboard/batch/page.tsx
src/app/dashboard/cost/page.tsx
src/app/dashboard/keys/page.tsx
src/app/dashboard/layout.tsx
src/app/dashboard/page.tsx
src/app/dashboard/reconstruct/page.tsx
src/app/auth/signup/page.tsx          (shim → keep canonical /signup)
```
Add `redirects()` in `next.config.ts` so old bookmarks/emails don't 404 (these run server-side at request time — fine, no auth needed):
```ts
async redirects() {
  return [
    { source: "/dashboard", destination: "/history", permanent: true },
    { source: "/dashboard/analyses", destination: "/history", permanent: true },
    { source: "/dashboard/analyses/:id", destination: "/analyses/:id", permanent: true },
    { source: "/dashboard/cost", destination: "/cost", permanent: true },
    { source: "/dashboard/batch/:path*", destination: "/batch/:path*", permanent: true },
    { source: "/dashboard/keys", destination: "/keys", permanent: true },
    { source: "/dashboard/reconstruct", destination: "/reconstruct", permanent: true },
    { source: "/auth/signup", destination: "/signup", permanent: true },
  ];
}
```

**RESOLVE the `/` collision:** today `app/page.tsx` (landing) **and** `app/(dashboard)/page.tsx` (quota dashboard) both compile to `/` → hard error. Fix:
1. `app/page.tsx` stays the **sole** owner of `/` = the **public marketing landing** (keep its demo dropzone — frictionless try). Strip its auth-swap (`Home()` no longer renders `Dashboard()`); make it static + an auth-aware CTA (§5.6). This removes the hydration flash.
2. **Rename route group `(dashboard)` → `(app)`** (cosmetic URL-wise; signals "this is THE shell"; drops the de-emphasized word "dashboard"). Its `layout.tsx` becomes the `AppShell`.
3. **Delete `(app)/page.tsx`** (the old quota dashboard that sat at `/`). Move its content to **new `(app)/history/page.tsx`** (QuotaDisplay + AnalysisHistoryTable).
4. **Move the authed Analyze working surface out of `app/page.tsx`** into **new `(app)/analyze/page.tsx`** (the `Dashboard()` upload→`AnalysisDashboard` flow, recomposed).
5. **Move `app/label/` → `app/(app)/label/`** so the orphaned labeler enters the shell (it currently has no nav and no way back).

**Resulting tree (one namespace, no collision):**
```
app/
  layout.tsx                         root: <html> fonts + <AuthProvider> + <Toaster>
  page.tsx                           "/"  PUBLIC landing (sole / owner)
  (auth)/signup/page.tsx             "/signup"   (+ magic/verify)
  docs/page.tsx                      "/docs"     public, tokenized (keep its own slim header)
  s/[shortId]/page.tsx               "/s/:id"    public share, tokenized
  scalar/route.ts                    "/scalar"
  (app)/
    layout.tsx                       AppShell (sidebar + topbar)  — wraps ALL below
    analyze/page.tsx                 "/analyze"   NEW — Analyze working surface (part workspace, Analyze tab)
    cost/page.tsx                    "/cost"      the hero (part workspace, Cost tab)
    batch/page.tsx, batch/[id]/page.tsx
    history/page.tsx                 NEW — quota + analyses table (was (dashboard)/page.tsx)
    analyses/[id]/page.tsx
    reconstruct/...                  (route kept; not a top-level nav item — §5.4)
    label/page.tsx + CorpusViewer.tsx
    keys/page.tsx + actions.ts
    error.tsx
```

### 5.2 `AppShell` = `(app)/layout.tsx`
```
┌ Sidebar 256px ─┬ Topbar 56px ───────────────────────────────────┐
│  Wordmark       │  breadcrumb (left) · spacer · key/conn indicator │
│  [nav groups]   │                       · account menu (right)     │
│                 ├──────────────────────────────────────────────────┤
│  ─────          │  <main> content region:                          │
│  footer:        │   px-6 lg:px-8 py-8, inner max-w-screen-2xl       │
│  account · ⚙    │   {children}                                      │
└─────────────────┴──────────────────────────────────────────────────┘
```
- Layout: `flex min-h-screen`; sidebar `bg-card border-r border-border`; main `bg-canvas flex-1`. Collapsible to `--sidebar-rail-w` (icon rail) — persist collapse in `localStorage` (`cv_sidebar_collapsed`). No `max-w-3xl` anywhere.
- Topbar `h-[var(--topbar-h)] bg-card border-b border-border`.

### 5.3 Sidebar nav (LOCKED set: Analyze · Cost · Batch · History · Label · API · Docs), grouped
```
[ CadVerify ]                          (wordmark → "/")
ANALYZE
  • Analyze        /analyze    icon ScanLine     (default authed landing)
  • Cost           /cost       icon Calculator
  • Batch          /batch      icon Layers
LIBRARY
  • History        /history    icon History
  • Parts (Label)  /label      icon Tags
DEVELOP
  • API keys       /keys       icon KeyRound
  • API docs       /docs       icon BookOpen
── footer ──
  • account menu (avatar, email, Sign out)   • collapse toggle
```
- `nav-item.tsx`: active state via `usePathname()` — active = `bg-primary-50 text-primary-700 border-l-2 border-primary` (left accent), inactive `text-muted-foreground hover:bg-muted hover:text-foreground`. Active match: exact for `/analyze`,`/cost`,`/history`,`/keys`; `startsWith` for `/batch`,`/analyses`,`/label`,`/docs`.
- "API docs" links to `/docs` (the SPA docs); the Scalar/backend reference is a secondary link inside `/docs`.

### 5.4 Reconstruct placement (resolve the silo)
`/reconstruct` stays routable but is **not** a top-level nav item (it's an input method, per competitor-ux). Surface it as a secondary action on `/analyze` ("Start from photos → Image-to-3D"). Its result still routes to `/analyses/[id]`.

### 5.5 Part-as-object tab model (`part-tabs.tsx` + the workspace)
Locked: a part opens to tabs **Analyze · Cost · Tolerances · Share**. Realize as ONE client workspace so a single upload serves DFM **and** cost (a `File` cannot cross a route boundary — so tabs are **client state**, not route nav).

- `(app)/analyze/page.tsx` renders `<PartWorkspace defaultTab="analyze" />`.
- `(app)/cost/page.tsx` renders `<PartWorkspace defaultTab="cost" />` (deep-link starts on Cost).
- `PartWorkspace` (Screen Builder A owns it) holds `{ file, costReport, analysisResult }` in state, one `<Dropzone>` and one `<CadViewer>`, and a `<PartTabs>` header:
  - **Analyze** → DFM (`validateFile` authed / `/validate/demo` no-key) → `AnalysisDashboard` (recomposed) + viewer with linked issues.
  - **Cost** → should-cost (`hasApiKey() ? costEstimate : costEstimateDemo`) → the answer-first cost screen (§6).
  - **Tolerances** → `EmptyState` "Coming soon — GD&T tolerances" (stub; present so the object model is whole).
  - **Share** → the share action surface (toggle public + copy link via `dialog.tsx`); for an unsaved local part show "Sign in to save & share" (`RequireKey`-style inline).
  - Sidebar "Analyze" and "Cost" are **entry points**; switching tabs inside the workspace never re-uploads or loses the file. Each tab lazily computes its result on first activation (and on explicit "re-run/re-cost").

> Pragmatic note for the builder: the DFM run and the cost run are independent backend calls on the same `File`; cache each result in workspace state keyed by `(file, options)` so tab-switching is instant and a changed option re-runs only that tab.

### 5.6 Auth: ONE source of truth + tiered protection (preserve the demo)
- **`auth-provider.tsx`** (client context in root `app/layout.tsx`): reads `localStorage.cadverify_api_key` once after mount (NOT in a `useState` initializer — that caused the SSR/hydration flash). Exposes `{ hasKey, mounted, signOut() }` (`signOut` clears the key + `router.refresh()`). The data layer (`lib/api.ts` `authHeaders()`/`hasApiKey()`) is UNCHANGED — the provider is the React-render source of truth; `lib/api` remains the request source of truth.
- **Two protection tiers** (this is how "route-protect authed pages" coexists with "preserve frictionless local /cost"):
  - **Demo-capable (NEVER gate):** `/analyze`, `/cost` (+ landing demo). With no key they call the public `*/demo` routes; with a key, the authed routes — exactly today's `/cost` behavior, now also on `/analyze`. Show a subtle topbar pill "Local demo · no key" linking to `/signup`.
  - **Key-required (gate):** `/history`, `/analyses/[id]`, `/batch`, `/batch/[id]`, `/keys`, `/reconstruct`. Wrap their page bodies in **`<RequireKey>`**: if `!hasKey` (after `mounted`), render an `EmptyState` ("Connect an API key to view history/run batches" → CTA `/signup`) instead of firing calls that 401. `/label` is ungated (localhost corpus tool; it surfaces its own backend-unreachable `ErrorState`).
- `proxy.ts`/`next.config` cannot read the localStorage key, so **all gating is client-side** via `RequireKey` (documented Next-16 constraint).

---

## 6. THE ANSWER-FIRST COST SCREEN — `/cost` (CadVerify's signature)

Refactor `CostDecisionCard.tsx` onto primitives and lead with the decision. Data type = `CostReport` (mirror of backend `report_to_dict`; see `lib/api.ts` lines 525-626). **Preserve** the `hasApiKey() ? costEstimate(file,opts) : costEstimateDemo(file,opts)` switch and the `CostGeometryInvalidError` → repair-card path verbatim.

### 6.1 Layout (above-the-fold answer first, glass-box one tab below)
```
PageHeader:  "Bracket-rev3.step"  [StatusBadge make-now]   actions: [New part] [Share] [PDF]
PartTabs:    Analyze · ▸Cost · Tolerances · Share
────────────────────────────────────────────────────────────────────────
HERO (full width, airy):  the ANSWER sentence (h-display) — e.g.
   "Make by CNC 3-Axis ≤ 740 units · $44.13/unit · 6–10 days — mold wins above 740."
   from decision.note + recommendation; the headline number in primary-600.
KPI ROW (MetricCard ×4):  [Unit cost @qty]  [Lead time]  [Make-now process]  [Crossover qty]
────────────────────────────────────────────────────────────────────────
2-col:  LEFT (sticky)                          RIGHT
   <CadViewer file>                            BREAKEVEN CHART (§6.2) + quantity slider (§6.3)
   filename (mono)                             Recommendation-by-quantity Table (DataTable)
   <OptionsForm> (Select/NumberField)          Process-options cards
   [Re-cost] (Button loading)
────────────────────────────────────────────────────────────────────────
GLASS-BOX (below / "Cost drivers" sub-tab):  provenance-tagged driver breakdown
   + Σ line-items = unit-cost coherence check + lead-time detail + assumptions chips
```
- Loading → `progress-steps` ("Parsing geometry → Costing across processes"). Geometry-invalid → `CostGeometryInvalidCard` recomposed onto `Card tone="fail"` + `EmptyState`/repair link. Demo vs authed is invisible to the user except the topbar pill.

### 6.2 The make-vs-buy breakeven chart (Recharts — the thing no comp nails)
**Data shape (derive client-side from `CostReport`; do NOT need a new endpoint).** Each `CostEstimate` carries `process`, `quantity`, `unit_cost_usd`, **`fixed_cost_usd`, `variable_cost_usd`** — so unit cost as a function of quantity is the standard amortization model:
```
unitCost(process, q) = fixed_cost_usd / q + variable_cost_usd
```
Build one curve per distinct process from its fixed/variable split:
```ts
// 1) group estimates by process; take fixed F, variable V for each process.
// 2) If a process has estimates at >1 quantity with INCONSISTENT F/V, fit instead:
//    from two points (q1,u1),(q2,u2):  F = (u1-u2)/(1/q1 - 1/q2);  V = u1 - F/q1.
// 3) sample q over a log range [1 .. qMax] (qMax = max(report.quantities)*4, capped 1e6),
//    ~60 points; series[p][i] = { q, [p]: F/q + V }.
type Pt = { q: number } & Record<string /*process*/, number>;
```
Render: Recharts `<LineChart>`, **X = quantity (log scale)**, **Y = $/unit**, one `<Line>` per process (≤4 most-relevant: make-now + tooling + up to 2 others; color make-now = `primary-600`, tooling = `neutral-600`, others muted). Mark the crossover with a `<ReferenceLine x={decision.crossover_qty}>` labeled "crossover ≈ N units". Tooltip = mono `$/unit` per process at hovered q. Legend uses `procLabel`. Y/X ticks mono. `≤3-4 series`, no pie, semantic-restrained colors (cohesion law).

### 6.3 Quantity slider (live-flips the recommendation — the "aha")
- `components/ui/slider.tsx` under the chart, **log-scaled** over the same `[1 .. qMax]` domain. Value `q` shown as a mono readout + a `<ReferenceLine x={q}>` vertical marker tracking the thumb on the chart.
- On drag, compute `recommended = argmin_p unitCost(p, q)`; update the **HERO sentence + KPI MetricCards live** (unit cost @q, recommended process, "make vs mold" verdict flips at the crossover). Debounce paint to rAF; pure client math (no network). Default q = the smallest tested quantity (`report.quantities[0]`).
- This single interaction is the product's signature — it must feel instant and update the hero, not a buried widget.

### 6.4 Glass-box breakdown (recompose, don't redesign)
Keep `CostDecisionCard`'s existing structure (driver list with `ProvenanceTag`, the visible `Σ line-items = unit_cost` coherence check, lead-time block, assumptions chips) but: tags → `PROVENANCE` from `lib/status.ts`; process names → `procLabel`; cards → `Card`; the "MAKE NOW" pill → `StatusBadge`; numbers → `.num`. Place it below the fold on `/cost` (or behind a "Cost drivers" segmented sub-view) — present for trust, out of the way of the answer. Each derived number may carry a `WhyTooltip` (§4.6).

### 6.5 Viewer-with-linked-issues (the Analyze tab; cost tab is preview-only)
On the **Analyze** tab, `AnalysisDashboard`'s `IssueList` rows link to geometry: clicking an issue sets `<CadViewer highlightFaces={issue.affected_faces_sample} ghostUnhighlighted>`; issues grouped **Required (fail) vs Advisory (warn)** with measured value + threshold + fix + "show on model" (per competitor-ux). One-way list→model highlight is the v1 must; model→list raycast is optional/advisory. On `/cost`, the viewer is a plain preview (no linking required).

---

## 7. FILE-BY-FILE BUILD PLAN

### 7.A FOUNDATION BUILDER — tokens + primitives + shell + routing (do first; the gate for A & B)
**Order (each step ends with `npx tsc --noEmit` + `npm run build` green):**
1. **Tokens:** rewrite `src/app/globals.css` per §2.1; verify Geist (not Arial) renders. Add `lib/utils.ts` (§4.0). `npm i` the §1 deps.
2. **Status module:** create `lib/status.ts` (§3) with the full 21-entry `PROCESS_LABELS`, `TONE`, all resolver fns, `PROVENANCE`. (Don't delete the old per-file maps yet — that happens as each component migrates in 7.B/7.C, but `lib/status.ts` is the only place new ones may exist.)
3. **Primitives:** vendor `components/ui/{button,card,badge,status-badge,table,data-table,input,textarea,select,label,slider,field,tabs,dialog,alert-dialog,tooltip,popover,skeleton,spinner,progress,progress-steps,empty-state,error-state,dropzone,cad-viewer}.tsx` per §4. `cad-viewer` merges `ModelViewer`+`MeshCanvas` (keep R3F internals); do NOT delete the originals until A/C migrate their importers (then delete).
4. **Shell + routing:** `components/ui/{app-shell,sidebar,topbar,nav-item,page-header,part-tabs,auth-provider,require-key}.tsx` (§4.9/§5). Add `<AuthProvider>` to root `app/layout.tsx`. Perform the §5.1 route surgery: delete the 10 shim files; add `next.config.ts` `redirects()`; rename `(dashboard)`→`(app)`; make `(app)/layout.tsx` the AppShell; create `(app)/history/page.tsx` (moved quota dashboard) and `(app)/analyze/page.tsx` (placeholder that renders `PartWorkspace` — A fills it); move `app/label`→`app/(app)/label`; strip the auth-swap from `app/page.tsx` and add the auth-aware CTA.
**Acceptance (Foundation):** build+typecheck green; `/`, `/analyze`, `/cost`, `/history`, `/batch`, `/keys`, `/label`, `/reconstruct` all resolve, render inside the shell (except `/`), no `/` collision, no `/dashboard/*` route (old URLs 308-redirect); sidebar shows the 7-item grouped nav with correct active state; no Arial; zero new color maps outside `lib/status.ts`; `npm run dev` boots on :3000.

### 7.B SCREEN BUILDER A — Analyze + Cost hero flow (the signature)
**Files:**
- `components/ui/part-workspace.tsx` (NEW) — the §5.5 workspace (file/viewer/tabs/state).
- `(app)/analyze/page.tsx` — `<PartWorkspace defaultTab="analyze"/>`.
- `(app)/cost/page.tsx` — `<PartWorkspace defaultTab="cost"/>`; preserve the demo switch + `CostGeometryInvalidError` path.
- `components/CostDecisionCard.tsx` — recompose onto `Card/StatusBadge/Table/MetricCard`; tags→`PROVENANCE`, names→`procLabel`, numbers→`.num`; **delete** its local `PROCESS_LABELS`/`PROVENANCE_STYLES`.
- `components/CostBreakevenChart.tsx` (NEW) — §6.2 Recharts curve + crossover line.
- `components/QuantitySlider.tsx` (NEW) — §6.3 (or inline in the cost view) using `ui/slider`.
- `components/AnalysisDashboard.tsx` + `IssueList.tsx` + `FeaturesList.tsx` + `ProcessScoreCard.tsx` — recompose onto primitives; **delete** their local verdict/severity/citation/kind/process maps in favor of `lib/status.ts`; wire IssueList→`CadViewer` highlight (§6.5).
- Delete `ModelViewer.tsx` + `reconstruct/components/MeshCanvas.tsx` once `CadViewer` is in (and update `CorpusViewer` import).
**Acceptance (A):** drop a CAD file on `/cost` → hero answer sentence + KPI row above the fold; breakeven chart renders ≥2 process curves with the crossover marked; dragging the quantity slider **live-flips** the recommended process + updates the hero/KPIs with no network call; glass-box driver breakdown present below with the Σ-coherence check and provenance tags from the single source; `/analyze` shows DFM with Required/Advisory grouping and issue→geometry highlight; **demo flow works with no API key** on both tabs; the geometry-invalid repair path still renders; build+typecheck green.

### 7.C SCREEN BUILDER B — Label, History, Batch, Keys, Reconstruct, Share, Docs, public share
**Files (recompose onto primitives + shell; logic preserved):**
- `(app)/history/page.tsx` + `components/AnalysisHistoryTable.tsx` + `QuotaDisplay.tsx` — `DataTable` (sortable, density, mono numerics), `StatusBadge` verdicts, `EmptyState`; **rows link to `/analyses/[id]`** (not the dead `/dashboard/analyses/[id]`); wrap page in `RequireKey`; quota bars use `usageTone`. Delete `VERDICT_BADGE`/`usageColor`.
- `(app)/analyses/[id]/page.tsx` — `PageHeader` (breadcrumb `History / filename`, Share/PDF/Repair actions), `AnalysisDashboard`; "Back to dashboard" → History; `RequireKey`.
- `(app)/batch/page.tsx` + `batch/[id]/page.tsx` + `batch/{BatchUploadForm,BatchItemsTable,BatchProgressBar}.tsx` — `Dropzone`, `DataTable`, `StatusBadge` via `batchStatusTone`, `progress`/`progress-steps`; `EmptyState`/`ErrorState` (no silent-empty catch); `RequireKey`. Delete `STATUS_BADGES`/`STATUS_COLORS`.
- `(app)/keys/page.tsx` (+ `actions.ts` untouched) — `DataTable`/list onto `Card`, `Button` (no `bg-black`), `AlertDialog` for Revoke confirm, `RevealOnceModal`→`Dialog`; `neutral-*`→token grays; `RequireKey`.
- `(app)/reconstruct/*` — `Dropzone` (merged), `progress-steps`, `ConfidenceBadge`→`StatusBadge` via `confidenceTone`; `EmptyState`/`ErrorState`; `RequireKey` (soft); result→`/analyses/[id]`.
- `(app)/label/page.tsx` + `CorpusViewer.tsx` — into the shell; `Button`/`Card`/`field`/`StatusBadge`; viewer→`CadViewer`; keep keyboard ontology + localhost-corpus behavior; `ErrorState` for backend-unreachable.
- `components/{ShareButton,ShareModal,RevealOnceModal,PdfDownloadButton,RepairButton,RepairComparison,RulePackSelector}.tsx` — onto `Button`/`Dialog`/`Select`/`StatusBadge`; delete `PACK_COLORS`.
- `app/page.tsx` (landing) — tokenize (Button/Card), static + auth-aware CTA (§5.6), keep demo dropzone (`Dropzone`+`CadViewer`+`AnalysisDashboard`).
- `app/docs/page.tsx` + `s/[shortId]/page.tsx` — reskin to tokens + primitives (server components: use token utility classes, `StatusBadge` is client — keep share page's verdict as token-classed spans or a tiny client badge); delete their local `VERDICT_STYLES`/`SEVERITY_STYLES`; `bg-black` CTAs→`Button`.
**Acceptance (B):** every listed surface renders inside the shell (landing/docs/share excepted) with shared primitives only; zero per-file color maps remain (all via `lib/status.ts`); all data tables use `DataTable` with mono right-aligned numerics + empty/loading/error states; no `bg-black`/`bg-blue-600`/`rounded-2xl`/`max-w-3xl`/Arial anywhere; key-required pages gate via `RequireKey`; `/label` is reachable from the sidebar and back; build+typecheck+lint green.

### 7.D Cross-cutting acceptance (the Auditor's checklist)
- `grep` shows **0** inline `bg-blue-600|bg-black|bg-green-600|rounded-2xl|max-w-3xl|font-family: *Arial` in `src/` (outside `globals.css`/comments).
- **One** declaration of `PROCESS_LABELS` (in `lib/status.ts`); **one** verdict label vocabulary; **one** button/card/badge/table/dialog/dropzone/spinner/viewer.
- `npm run build` ✅, `npx tsc --noEmit` ✅, `npm run lint` ✅; `npm run dev` serves :3000; `/cost` + `/analyze` demo flows work with no key; 3D viewers render.

---

## 8. What is explicitly OUT of scope for v1 (so builders don't gold-plate)
Dark-mode toggle; command palette (⌘K); ViewCube/section/measure viewer tools; density-persistence per-user; org/tenant switcher; Tolerances tab content (stub only); model→list raycast highlight; SOC2/trust pages. Author tokens/shell so these slot in later, but do not build them now.

---

*Sources expanded (LOCKED, not re-decided): outputs/design/{design-direction, current-state-audit, competitor-ux, design-system-patterns}.md. Grounded in: lib/api.ts CostReport/CostEstimate types, CostDecisionCard, AnalysisDashboard, the (dashboard) route group, and node_modules/next/dist/docs (route-groups, redirecting).*
```
