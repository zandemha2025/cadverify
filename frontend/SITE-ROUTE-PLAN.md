# CadVerify marketing site — ROUTE PLAN (dark-theater rebuild)

Foundation branch: `feat/site-theater`. This plan maps the 12 canonical design
files in `handoff_cadverify_2026-07-04/site/` to production routes, names the
shared foundation, and states the cutover (what replaces / removes what).

**Register (binding):** marketing = **dark theater** (`#050506`, Helvetica Neue
light, mono evidence); product = **light instrument** (already built, untouched).
Never a third identity. See `handoff_cadverify_2026-07-04/DESIGN-DECISIONS.md`.

All new site pages live under the **`(site)` route group** so they share one
dark-theater layout. The group adds no URL segment — `(site)/method/page.tsx`
serves `/method`. The light-instrument product — `(app)`, `(verify)`, `(auth)`,
`/docs`, `/scalar` — stays OUTSIDE the group and never renders `.site-theater`.

---

## 1. Design file → route

| # | Design file (`site/…dc.html`) | Route | Source file (create) | WebGL? |
|---|---|---|---|---|
| 1 | `Direction - Cinematic` | `/` | `app/(site)/page.tsx` | yes (home shaft) |
| 2 | `Method` | `/method` | `app/(site)/method/page.tsx` | no |
| 3 | `Platform` | `/platform` | `app/(site)/platform/page.tsx` | no |
| 4 | `Teams` | `/teams` | `app/(site)/teams/page.tsx` | no |
| 5 | `Security` | `/security` | `app/(site)/security/page.tsx` | no (schematic beam) |
| 6 | `Developers` | `/developers` | `app/(site)/developers/page.tsx` | no |
| 7 | `Company` | `/company` (pilot at `/company#pilot`) | `app/(site)/company/page.tsx` | no |
| 8 | `For Cost Engineering` | `/teams/cost-engineering` | `app/(site)/teams/cost-engineering/page.tsx` | yes |
| 9 | `For Design Engineering` | `/teams/design-engineering` | `app/(site)/teams/design-engineering/page.tsx` | yes |
| 10 | `For In-House Manufacturing` | `/teams/in-house-manufacturing` | `app/(site)/teams/in-house-manufacturing/page.tsx` | no |
| 11 | `For Shop Owners` | `/teams/shop-owners` | `app/(site)/teams/shop-owners/page.tsx` | yes |
| 12 | `For Sourcing` | `/teams/sourcing` | `app/(site)/teams/sourcing/page.tsx` | yes |

**Persona prefix = `/teams/*`.** The five `For *` journeys are children of Teams:
the Teams hub links to them and each persona hero reads "Teams / <persona>". The
nav "Teams" link stays lit for the whole `/teams/*` subtree (`SiteNav` already
does this via `startsWith`).

**Home nav → routes (from the design's `.dc.html` hrefs):**
`Method.dc.html → /method`, `Platform.dc.html → /platform`,
`Teams.dc.html → /teams`, `Security.dc.html → /security`,
`Developers.dc.html → /developers`, `Company.dc.html → /company`,
`Company.dc.html#pilot → /company#pilot`. All internal `*.dc.html` links in the
designs remap to these paths (relative `.dc.html` hrefs become route paths).

---

## 2. Shared foundation (page builders MUST NOT edit these)

Built on this branch; consume via `import { … } from "@/components/site"`.

- `src/app/(site)/layout.tsx` — the dark-theater group layout (scopes
  `.site-theater`, imports the tokens CSS, sets site metadata).
- `src/app/(site)/site-theater.css` — **(a) dark-theater design tokens**, fully
  scoped under `.site-theater` (`--st-*` vars + `.st-*` classes). No bare
  `:root`/`body` selector, so the product's semantic tokens are untouched by
  construction.
- `src/components/site/site-shell.tsx` — **(b) SiteShell**: `SiteNav`
  (`cinematic`|`document`), `SiteFooter`, `SiteFooterTagline`, `SiteShell`
  wrapper, plus `SITE_NAV`, `SITE_TAGLINE` (`"verification, made of glass"`),
  `PILOT_HREF`. Every page cross-links through these; the footer tagline is
  everywhere.
- `src/lib/site/scroll-acts.ts` — **(c) scroll-act measurement utility**:
  `measureSection` (ramp/pin/vis), `lerp/clamp01/smooth/seg`,
  `documentScrollProgress`, `applyCaptionReveal`, `scrollToSection`, and the
  `useRafLoop` hook (scroll-smoothed rAF).
- `src/components/site/part-stage.tsx` — **(d) reusable WebGL part-choreography
  stage**: `PartStage` (turned-aluminum shaft studio, ported faithfully from the
  design, using the repo's installed `three` — NO CDN) + `makeHomeChoreography`
  (the exact five-act home choreography as a factory wired to the page's section
  refs).
- `src/components/site/evidence.tsx` — **(e) mono-evidence / typography
  primitives**: `Eyebrow`, `DisplayHeading`, `Mono`, `MonoRow`,
  `ProvenanceChip`, `IllustrativeTag`, `InDevelopmentChip`, `HonestyBand`,
  `ScrollHint`, `Panel`. These encode the honesty rules structurally (filled ●
  MEASURED/SHOP/USER vs hollow ○ DEFAULT/MODEL; fabricated figures wear
  `[illustrative]` / `IN DEVELOPMENT`; bands are hatched until validated).
- `src/components/site/index.ts` — the barrel page builders import from.

**Rule:** page builders create only their `page.tsx` (+ page-local components in
their own folder) and consume the foundation. They do **not** edit any file
above — changes to shared machinery go through a foundation branch so the 12
pages stay consistent. Cinematic pages compose `<SiteNav variant="cinematic" />`
+ `<PartStage …/>` (fixed, behind) + `<SiteFooterTagline/>`; document pages wrap
in `<SiteShell>`.

**Scaffolding (NOT foundation, delete at cutover):**
`src/app/(site)/site-preview/page.tsx` (`/site-preview`) — a live end-to-end
reference exercising every foundation piece. It is disposable; the real Home is
built at `(site)/page.tsx`.

---

## 3. Cutover — what replaces / removes / redirects (integration step, NOT this branch)

The current top-level marketing pages sell the **killed should-cost thesis** and
are replaced wholesale:

**Replace**
- `src/app/page.tsx` (old should-cost home) → **removed**; `(site)/page.tsx`
  (Direction - Cinematic) takes `/`.
- `src/app/method/page.tsx` (old should-cost method) → **removed**;
  `(site)/method/page.tsx` takes `/method`.

**Remove after cutover (orphaned once old `/` + `/method` are gone)**
- `src/components/marketing/*` (decision-plate, black-box-reveal, datum, data).
- `src/components/ui/public-chrome.tsx` (old light `PublicHeader`/`PublicFooter`/
  `PrimaryCta`) — superseded by `SiteNav`/`SiteFooter`.
- `src/components/glass-box/*` **except** keep `provenance.tsx` + `confidence.tsx`
  as reference implementations (per DESIGN-DECISIONS.md "REFERENCE-ONLY").
- Dead marketing tokens in `src/app/globals.css`: the `.cv-paper` / `.cv-twilight`
  / `.cv-*` locks, `--font-display`/Archivo import in `layout.tsx`, and the
  `cv-hero-field`/`cv-obsidian` etc. — all only referenced by the old marketing
  pages. Prune once nothing imports them. (Do NOT touch `:root`/`.dark`/
  `[data-stage]`/`[data-stage-type]` — those are the product.)

**Keep (product / API surface, cross-linked FROM the new site)**
- `/docs` (`src/app/docs/page.tsx`) and `/scalar` (`src/app/scalar/route.ts`) —
  the API reference. The new **Developers** page (`/developers`) is the marketing
  surface that links out to `/docs`, `/scalar`, and GitHub.
- `(app)`, `(verify)`, `(auth)` — the light-instrument product and auth. The
  site's CTAs point at `/signup` (account) and `/company#pilot` (pilot form).

**Redirects**
- None required at cutover: `/platform`, `/teams`, `/security`, `/developers`,
  `/company`, and `/teams/*` are all new paths (no prior occupants); `/` and
  `/method` are re-pointed by replacing their `page.tsx`. Existing
  `next.config.ts` redirects (`/dashboard/*`, `/keys`, `/settings`, `/auth/signup`)
  are product/auth and unaffected.
- Root metadata: update `src/app/layout.tsx` title/description (currently the
  should-cost line) — the `(site)` layout already overrides for site routes.

---

## 4. Verification gate (this branch)

`tsc --noEmit` green · `next build --webpack` green (worktree builds use webpack;
Turbopack panics on symlinked `node_modules`). `/site-preview` prerenders static,
so SSR of the whole foundation is proven; all product routes are unchanged.
