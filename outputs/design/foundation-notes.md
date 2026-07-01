# CadVerify — Foundation Builder Notes

**Author:** Foundation Builder (cohesion backbone)
**Date:** 2026-06-29
**Status:** DONE — build + typecheck + lint GREEN; dev server boots on :3000.
**Scope:** tokens, primitive library, single status/process map, AppShell, route surgery + protection. Feature screens were NOT restyled (that is Screen Builders A & B) — they only render inside the shell.

---

## 0. Proof the gate is green (real output)

```
$ npm run build                 # Next.js 16.2.3 (Turbopack)
✓ Compiled successfully in 2.2s
  Running TypeScript ... Finished TypeScript in 1896ms
✓ Generating static pages (14/14)
Route (app)
┌ ○ /                 ├ ○ /analyze    ├ ○ /cost     ├ ○ /history
├ ○ /batch            ├ ƒ /batch/[id] ├ ƒ /analyses/[id]
├ ƒ /keys             ├ ○ /label      ├ ○ /reconstruct
├ ○ /docs  ├ ƒ /signup ├ ƒ /magic/verify ├ ƒ /s/[shortId] ├ ƒ /scalar ├ ○ /_not-found

$ npx tsc --noEmit              # against freshly-generated .next/types
TSC_GREEN

$ npm run lint                  # eslint
✖ 4 problems (0 errors, 4 warnings)   # all pre-existing/benign (see §7)

$ npm run dev                   # boots on :3000; route status codes:
/ 200 · /analyze 200 · /cost 200 · /history 200 · /batch 200 · /label 200
/reconstruct 200 · /docs 200 · /signup 200 · /dashboard/cost 308→200 (redirect works)
/keys 500  ← pre-existing: server component fetches backend /api/v1/keys; backend not running here (runs separately on :8000). Not a regression.
```

There is exactly ONE owner of `/` (the public landing). No `/dashboard/*` route exists. No `(app)` page resolves to `/`. The `/` parallel-page collision is gone (verified in the build route manifest above).

---

## 1. Tokens — `src/app/globals.css` (rewritten verbatim per spec §2.1)

- **Arial bug fixed.** Deleted `body { font-family: Arial, Helvetica, sans-serif }` and the Next-starter `--background/--foreground:#171717` + `@media (prefers-color-scheme: dark)` boilerplate. `body` now uses `font-family: var(--font-sans)` → Geist Sans (loaded by `app/layout.tsx`). Verified: no `Arial` anywhere in `src/` except two explanatory comments.
- **Full `@theme` token set** implemented: slate neutral ramp (`--color-neutral-0..950`), steel-blue primary (`--color-primary-50..800`), the four semantic statuses with solid/bg/border stops (`pass/warn/fail/info`), surface/text aliases (`canvas/card/muted/foreground/border/ring/...`), provenance tags (`prov-measured/user/default`), the `display`/`display-xl` hero type sizes, radius scale (`--radius-sm:4 / --radius:6 / --radius-lg:8`), two shadows, and shell metrics (`--sidebar-w`, `--sidebar-rail-w`, `--topbar-h`).
- **One necessary expansion (not a re-decision):** added a bare `--color-primary: #2563eb` alias. Spec §4.1 uses `bg-primary`/`text-primary`/`border-primary`/`border-l-2 border-primary`, but §2.1's verbatim block only defined `--color-primary-600`; without the bare alias those utilities would silently no-op (transparent buttons). `--color-primary` == primary-600 (the LOCKED accent). Everything else is verbatim.
- The token layer is **purely additive** over Tailwind's default palette (no `--color-*: initial` reset), so existing feature components that still use `bg-gray-50`/`bg-blue-600`/`text-red-700` keep rendering until Screen Builders A/B migrate them. That is why the build stays green with zero screen rewrites.
- `lib/utils.ts` adds `cn()` (clsx + tailwind-merge).

## 2. Single status/process source — `src/lib/status.ts` (NEW)

One module exporting: `Tone`, the `TONE` class-bundle map, `TONE_ICON` (lucide per tone), resolvers `verdictTone/Label`, `severityTone/Label`, `batchStatusTone`, `confidenceTone`, `usageTone`, `domainTone`, the **single 21-entry `PROCESS_LABELS`** + `procLabel()`, and `PROVENANCE`. Canonical vocabulary is single-sourced (Pass / Advisory / Required; long banner forms Manufacturable / Issues found / Not manufacturable). All token-driven (no raw hex). Per spec §7.A step 2 the old per-file maps are NOT deleted yet — they die as each feature component migrates in 7.B/7.C; `lib/status.ts` is now the only place a new map may live.

## 3. Primitive library — `src/components/ui/*` (31 files)

`button` · `card` (+`MetricCard`) · `badge` · `status-badge` · `table` · `data-table` (TanStack) · `input` · `textarea` · `label` · `select` · `slider` · `field` · `tabs` · `dialog` · `alert-dialog` · `tooltip` · `skeleton` (+`TableSkeleton`/`CardSkeleton`) · `spinner` · `progress` (+`ProgressSteps`) · `empty-state` · `error-state` · `dropzone` · `cad-viewer` · plus shell pieces `app-shell` · `sidebar` · `topbar` · `nav-item` · `page-header` · `part-tabs` · `auth-provider` · `require-key`.

- Hand-vendored shadcn-style source on Radix (NOT `npx shadcn init` — would clobber the Tailwind-v4 `@theme`). Variants via `cva`; icons via `lucide-react`.
- `cad-viewer.tsx` **merges** `ModelViewer` (File) + reconstruct `MeshCanvas` (URL) into ONE viewer (`{file?, src?, highlightFaces?, ghostUnhighlighted?}`), keeping the original R3F camera-fit/lighting/`#6b8cce` material; adds per-face highlight via vertex colors. `label/CorpusViewer` already switched to it (removing its cross-surface import of the reconstruct internal). The originals (`ModelViewer.tsx`, reconstruct `MeshCanvas.tsx`) are KEPT until Screen Builders A/C migrate their remaining importers, per spec §7.A step 3.
- `popover`/`checkbox`/`switch` Radix packages were not needed for v1 and not installed (spec §1 permits adding later). `alert-dialog` is composed on the single `dialog` primitive (a confirm dialog) instead of pulling a separate Radix package.

**Deps added:** `class-variance-authority clsx tailwind-merge lucide-react @tanstack/react-table recharts @radix-ui/react-slot @radix-ui/react-tabs @radix-ui/react-dialog @radix-ui/react-select @radix-ui/react-tooltip @radix-ui/react-label @radix-ui/react-slider @radix-ui/react-dropdown-menu`.

## 4. AppShell — `(app)/layout.tsx` → `<AppShell>`

Sidebar (256px, collapsible to a 64px rail, collapse persisted in `localStorage cv_sidebar_collapsed`) + Topbar (56px) + fluid `<main>` content region capped at `max-w-screen-2xl` with `px-6 lg:px-8 py-8` gutters. **No `max-w-3xl` anywhere in the shell.** Sidebar nav is the LOCKED grouped set with active state via `usePathname()` (left-accent + tinted bg):

```
ANALYZE  Analyze /analyze · Cost /cost · Batch /batch
LIBRARY  History /history · Parts (Label) /label
DEVELOP  API keys /keys · API docs /docs
```

Topbar has a breadcrumb (left), a "Local demo · no key" pill when no key, and a Radix dropdown account menu (API keys, Sign out). Verified rendering: `/analyze` returns the full shell (all 7 nav items + wordmark); `/` does not.

## 5. Routing fix (spec §5.1) — the collision + the shim tree

- **Renamed** route group `(dashboard)` → `(app)` (the shell namespace).
- **Deleted** the 9-file legacy `app/dashboard/*` shim tree + the `app/auth/signup` redirect shim.
- **Resolved the `/` collision:** deleted `(app)/page.tsx` (the old quota dashboard that sat at `/`); `app/page.tsx` is now the sole owner of `/`. Its content moved to **new `(app)/history/page.tsx`** (QuotaDisplay + AnalysisHistoryTable, gated).
- **New `(app)/analyze/page.tsx`** holds the authed upload→DFM working surface (moved out of `app/page.tsx`'s old `Dashboard()`), demo-capable. (Screen Builder A replaces it with `PartWorkspace`.)
- **Moved** `app/label/` → `app/(app)/label/` so the orphaned labeler enters the shell with a way back.
- **`app/page.tsx`** stripped of the auth-swap (`useState` initializer that caused the SSR/hydration flash). `Home()` now renders only the public `LandingPage`; the primary CTA is auth-aware (`Open app → /analyze` when a key exists, else `Get API Key`) without flashing.
- **`next.config.ts` `redirects()`** added so old bookmarks/emails 308 to the new namespace (`/dashboard → /history`, `/dashboard/analyses/:id → /analyses/:id`, `/dashboard/cost → /cost`, `/dashboard/batch/:path* → /batch/:path*`, `/dashboard/keys → /keys`, `/dashboard/reconstruct → /reconstruct`, `/auth/signup → /signup`). Verified `/dashboard/cost` → 308 → 200.
- Internal cross-namespace links repointed: `AnalysisHistoryTable` rows → `/analyses/:id` and `/history`; `analyses/[id]` "Back" → `/history`; `magic/verify` fallback → `/keys`.

## 6. Auth + route protection (spec §5.6)

- **`auth-provider.tsx`** added to root `app/layout.tsx`: a client context reading `localStorage.cadverify_api_key` AFTER mount (`{hasKey, mounted, signOut, refresh}`). `lib/api.ts` (`authHeaders`/`hasApiKey`) is UNCHANGED and remains the request source of truth. No `useState` initializer → no hydration flash.
- **Two tiers:**
  - **Demo-capable, never gated:** `/analyze`, `/cost`, the landing demo. With no key they hit the public `*/demo` routes; with a key, the authed routes. The `/cost` `hasApiKey() ? costEstimate : costEstimateDemo` switch and the `CostGeometryInvalidError` repair path are PRESERVED verbatim. `/analyze` now mirrors the same demo fallback.
  - **Key-required, gated by `<RequireKey>`:** `/history`, `/analyses/[id]`, `/batch`, `/batch/[id]`, `/reconstruct`. Each page's body is wrapped via a hoisted inner-component pattern so its data-fetching effects only mount once the key check passes (no 401 storms). Gating is client-side (proxy/next.config cannot read localStorage — documented Next-16 constraint).
  - **`/keys` is intentionally NOT wrapped in `RequireKey`.** It is a server component authenticated by the server-side `dash_session` cookie (the magic-link / Google flow), which is independent of the localStorage API key. Gating it by localStorage would lock out magic-link users who have a valid session but no local key. The server action (`listKeys`) already enforces auth.
  - `/label` is ungated (localhost corpus tool).

## 7. Known follow-ups / honest caveats

- **`/keys` 500 without backend:** expected — server-side fetch to `/api/v1/keys` needs the backend (:8000) + a `dash_session` cookie. Renders 200 with both. Not a regression (the keys page code is unchanged by me).
- **`cv_mint_once` reveal-once cookie path:** the magic-link key-reveal modal reads/clears a backend-set `cv_mint_once` cookie that was historically pathed to `/dashboard/keys`. With the route now at `/keys`, the modal's clear paths were updated to `/keys` + `/`, but the cookie's *Set-Cookie path is set by the backend* (which is out of scope to touch). If the hosted reveal flow relies on `path=/dashboard/keys`, the backend should set it to `/keys` (or `/`). Flagged for the backend owner; does not affect the build, the local demo, or the typecheck.
- **Lint:** 0 errors, 4 warnings — all pre-existing or benign: `ImageUploader` `<img>`, `ModelViewer` unused `highlightFaces`, `ShareButton` unused `handleCopyLink` (all pre-existing feature code Screen Builders touch later), and a React-Compiler "skip memoizing" note on `data-table`'s `useReactTable` (standard for TanStack Table; not an error).
- **Cohesion is backbone-only by design.** 19 feature files still use legacy `bg-blue-600`/`bg-black`/`rounded-2xl`/`max-w-3xl` and their old per-file color maps. Migrating them onto the primitives + `lib/status.ts` is explicitly Screen Builders A (7.B) and B (7.C); my mandate was the backbone + making every screen render inside the shell without breaking. The single primitive set, the single status map, the shell, and the resolved one-namespace route tree are all in place for them to build on.

---

## 8. REPAIR ROUND — public/auth perimeter migrated onto the system (Check 1 fix)

The authed product already passed; the FAIL was scoped to the public/boilerplate
perimeter still using the old warm-gray / raw-`bg-blue-600` / `bg-black` idiom.
That perimeter is now on the same one system.

**What changed**
- **One shared public chrome — `components/ui/public-chrome.tsx` (NEW):** `PublicHeader`
  (wordmark + nav slot + auth-aware CTA on slate/`bg-card`/`border-border`),
  `PublicNavLink` (Button ghost), `PublicFooter`, and the auth-aware `PrimaryCta`
  (Button primary, `Open app` with a key / `Get API Key` without). Used by the
  landing, docs, and signup so the public edge reads as the same product.
- **Landing — `app/page.tsx` rewritten.** Dropped the bespoke header, the legacy
  `FileDropZone`, the legacy `ModelViewer`, and the inline `AnalysisDashboard`
  results view. Now: design-system hero (Button/Card, slate tokens) and the demo
  **routes straight into the answer-first workspace** — it renders
  `<PartWorkspace defaultTab="cost" />` (the decision-first flow: should-cost hero,
  quantity slider, breakeven, viewer-linked Required/Advisory DFM, glass-box
  breakdown). The frictionless local demo is preserved (PartWorkspace keeps the
  `hasApiKey() ? authed : /validate/demo + cost/demo` switch and the STL
  triangle-limit feedback). `/` stays statically prerendered (○).
- **Signup — `app/(auth)/signup/page.tsx`.** `bg-black` Google button → `Button`
  primary; magic-link submit → `Button` secondary; raw inputs → `Input` primitive;
  wrapped in `Card` + `PublicHeader`. The exact blue-vs-black primary drift the
  check named is gone.
- **Docs — `app/docs/page.tsx`.** Reskinned to shared chrome (`PublicHeader` +
  `PublicFooter`), slate tokens (`text-foreground`/`text-muted-foreground`/`bg-muted`),
  `text-primary` links, code-block copy button → `Button`, code blocks on
  `bg-neutral-900`. **Dead `/dashboard` link removed** (repointed to `/keys`).
- **Error boundaries (3).** `app/error.tsx`, `app/(app)/error.tsx`,
  `app/global-error.tsx`: raw `bg-blue-600` buttons → `Button`; gray text → tokens.
  `global-error` (which replaces the root layout) now `import "./globals.css"` so
  the primitive's token classes resolve.
- **Dead code deleted.** `RulePackSelector.tsx` (+ its stale `PACK_COLORS` map),
  and — now that the landing no longer imports them — the legacy `ModelViewer.tsx`
  and `FileDropZone.tsx` (the duplicates `cad-viewer`/`dropzone` already replaced).
  Stale `RulePackSelector PACK_COLORS` reference removed from `lib/status.ts`'s
  header comment. Zero importers remain (verified by grep).

**Perimeter grep (post-fix):** `bg-black` → none · `bg-blue-600` → none (across all
5 former files) · `href="/dashboard"` → none · `text-blue-600` in perimeter → none.

**Proof the gate is green (real output, repair round)**
```
$ npx tsc --noEmit
TSC_EXIT=0

$ npm run build            # Next.js 16.2.3 (Turbopack)
✓ Compiled successfully in 2.5s
  Finished TypeScript in 1913ms
✓ Generating static pages (14/14)
  / ○ (Static) · /docs ○ (Static) · /signup ƒ · /analyze ○ · /cost ○ · … (exit 0)

$ npm run lint
✖ 1 problem (0 errors, 1 warning)   # only the TanStack useReactTable note (benign)

$ npm run dev              # :3000 route smoke
/ 200 · /docs 200 · /signup 200 · /analyze 200 · /cost 200
landing HTML renders both the hero ("The manufacturing decision, first.") AND the
answer-first workspace ("Should-cost & make-vs-buy") with bg-primary; no
bg-black/bg-blue-600/text-gray-900 leaked. signup renders bg-primary, no bg-black.
docs renders /keys (not /dashboard).
```

---

*Built against: design-system-spec.md (§2 tokens, §3 status, §4 primitives, §5 shell+IA, §7.A acceptance) and the LOCKED design-direction.md. No backend/ or data/ changes. No git commit.*
