# CadVerify Design System — Tokens, Components & IA Reference

**Author:** Enterprise B2B SaaS design-system & IA research agent
**Date:** 2026-06-29
**Status:** Research deliverable (no code changed). This is the *spec source* a synthesis pass and an implementation cycle execute from.
**Scope:** A concrete, implementable design system (color, type, spacing, density, components, states) + an information architecture / navigation shell for CadVerify, mapped to the existing stack (Next.js 16 + React 19 + TypeScript + Tailwind v4 + Three.js).

---

## 0. How to read this document

Every recommendation is one of:
- **ADOPT** — directly implementable in CadVerify now; concrete token/value/component given.
- **PATTERN** — a structural rule borrowed from a named enterprise system; cited.
- **CADVERIFY-SPECIFIC** — tailored to CadVerify's surfaces (DfM pass/warn/fail, cost/make-vs-buy, 3D viewer, glass-box explainability, labeling, reconstruct, batch).

The north star: **a glass-box DfM decision tool for design engineers** in the lane of 3D Spark (fast, broad-process, transparent) — *not* additive-first (CASTOR), *not* an opaque heavyweight (aPriori). The visual language must read **technical, precise, trustworthy, calm** — credible to a Head of Manufacturing *and* to enterprise IT/procurement. That means: restrained neutral-dominant palette, one disciplined accent, semantic status used *only* for real status, tabular numerics, generous-but-dense data layouts, and zero decorative noise.

---

## 1. Current-state findings (the "Frankenstein" baseline)

Observed in `/frontend` (so the spec is grounded, not generic):

| Area | Current state | Problem |
|---|---|---|
| Theme | `globals.css` is the **default Next.js starter**: `--background:#fff/--foreground:#171717`, `body{font-family:Arial,Helvetica}` overriding Geist. Only 2 color tokens. | No design tokens, no semantic colors, no surface layering. Arial fallback contradicts the loaded Geist font. |
| Type | Geist + Geist Mono loaded via `next/font`, but body CSS forces Arial. No type scale. | Inconsistent typography; no numeric/tabular treatment for cost/lead-time data. |
| App shell | `(dashboard)/layout.tsx` = a thin top nav, `max-w-3xl` container (≈768px), 4 links. | A 768px column is a *document*, not an enterprise app. No sidebar, no breadcrumbs, no global search, no account/org context. |
| Routing | **Two parallel route trees exist**: legacy `src/app/dashboard/*` (1-line layout) **and** grouped `src/app/(dashboard)/*` (real layout). Same pages duplicated (cost, batch, reconstruct, analyses, keys). | Frankenstein root cause: two IAs coexist. Must consolidate to one app shell. |
| Components | 20+ bespoke components (`CostDecisionCard`, `ProcessScoreCard`, `IssueList`, `FileDropZone`, `AnalysisHistoryTable`, `ConfidenceBadge`, batch tables…). No shared primitive layer. | Each component re-invents spacing/color/badge logic → visual incoherence. Needs a primitive layer (buttons, badges, cards, table, inputs) they all compose from. |
| Libraries present | `sonner` (toasts), `@react-three/fiber` + `drei` (3D), `@sentry/nextjs`. No component library, no `clsx`/`tailwind-merge`, no icon set, no Radix. | Need to add a primitive layer that fits Tailwind v4. |
| Tailwind | v4 (`@tailwindcss/postcss`, `@import "tailwindcss"`), **CSS-first `@theme`** — *no* `tailwind.config.js`. | Good: tokens belong in `@theme` as CSS variables (see §9). |

**Implication:** the work is (1) a token layer in `@theme`, (2) one consolidated app shell, (3) a small primitive component library the existing feature components recompose against.

---

## 2. Recommended implementation stack (and why)

**ADOPT this stack** — chosen for fastest path to cohesion on the *existing* Next 16 / React 19 / Tailwind v4 base:

| Layer | Choice | Why (cited) |
|---|---|---|
| Styling | **Tailwind v4, CSS-first `@theme`** (already present) | Tailwind v4 ships its palette as OKLCH CSS variables and is configured in CSS, not JS — tokens live in `@theme`. ([Tailwind colors](https://tailwindcss.com/docs/colors)) |
| Component primitives | **shadcn/ui** (copy-in components) on **Radix UI** primitives | shadcn is "a collection of reusable components built on Radix UI primitives and styled with Tailwind"; you **own the code** after generation, and Radix "handles keyboard navigation and ARIA attributes so interactive components are accessible by default." Best fit for an owned, themeable enterprise system. ([shadcn/ui](https://ui.shadcn.com/), [comparison](https://www.inspoai.io/blog/ui-component-library-comparison)) |
| Data tables | **TanStack Table** headless + shadcn `Table` skin | shadcn's Data Table pattern is explicitly "used to display complex datasets with sorting, filtering, pagination, row selection, and inline actions… for scalable dashboards, admin panels, analytics, and enterprise applications." ([shadcn data table](https://ui.shadcn.com/docs/components/radix/data-table)) |
| Toasts | **sonner** (already installed) | Keep; shadcn standardized on sonner. |
| Icons | **lucide-react** | shadcn's default icon set; single consistent stroke-based family (technical look). |
| Class utils | **`clsx` + `tailwind-merge`** (via shadcn `cn()`) | Required for variant composition; tiny. |
| Charts | **Recharts** (shadcn `Chart` wrapper) | For cost-vs-quantity / make-vs-buy crossover curves; themeable via CSS vars. |
| 3D viewer chrome | Keep `@react-three/fiber`+`drei`; wrap canvas in design-system frame | Viewer stays; only its *chrome* (toolbar, badges, panels) adopts tokens. |

**Why shadcn/Radix over Carbon-React, Polaris-React, AntD, or MUI here:** those are *prescriptive* libraries — adopting one repaints the whole app in *their* brand and fights Tailwind v4. shadcn gives **owned, Tailwind-native, Radix-accessible** primitives we theme with *our* tokens, so we can **borrow the rigor of Carbon/Polaris/M3 (their token discipline, type scale, density rules) without inheriting their skin.** This document therefore borrows *system rules* from Carbon/Atlassian/Polaris/M3/Untitled UI and *implements* them in shadcn+Tailwind.

---

## 3. Color system

### 3.1 Principles (PATTERN, borrowed)
- **Neutral-dominant.** Carbon's neutral gray family "is dominant in the default themes," using "subtle shifts in value to help organize content into distinct zones," and grays are *layered* to create depth. ([Carbon color](https://carbondesignsystem.com/elements/color/overview/)) Untitled UI: "almost everything in UI design—text, form fields, backgrounds, dividers—are usually gray." ([Untitled UI palettes](https://www.untitledui.com/blog/figma-color-palettes))
- **One restrained accent** (the "primary/brand"), used *only* on interactive/primary elements. Untitled UI: "the primary color… is used across all interactive elements such as buttons, links, inputs" and "sits at brand-500." ([Untitled UI palettes](https://www.untitledui.com/blog/figma-color-palettes))
- **Semantic colors mean status, never decoration.** Polaris roles: default / brand / warning / critical. ([Polaris palettes & roles](https://polaris-react.shopify.com/design/colors/palettes-and-roles)) Untitled UI feedback: success / warning / error. ([Untitled UI palettes](https://www.untitledui.com/blog/figma-color-palettes))
- **Tokens are role-based, themes supply values.** "Tokens are role-based, and themes specify the color values that serve those roles." ([Carbon color](https://carbondesignsystem.com/elements/color/overview/)) Atlassian color tokens are named `color.[property].[role].[emphasis].[state]` with dedicated tokens for text/border/background/icon/**chart**/skeleton. ([Atlassian color](https://atlassian.design/foundations/color))

### 3.2 Neutral ramp (ADOPT) — **Tailwind `slate`**
Cool slate reads more "engineering/CAD" than warm gray. Tailwind v4 ships these as OKLCH (native to `@theme`); hex given for reference. ([Tailwind colors](https://tailwindcss.com/docs/colors))

| Token | Slate shade | OKLCH (Tailwind v4) | Hex (ref) | Use |
|---|---|---|---|---|
| `--neutral-0` | white | `oklch(100% 0 0)` | `#ffffff` | App canvas (light), card surface |
| `--neutral-50` | slate-50 | `oklch(98.4% 0.003 247.86)` | `#f8fafc` | Subtle fill / hover row / layer-01 |
| `--neutral-100` | slate-100 | `oklch(96.8% 0.007 247.90)` | `#f1f5f9` | Striped row / muted bg |
| `--neutral-200` | slate-200 | `oklch(92.9% 0.013 255.51)` | `#e2e8f0` | **Borders / dividers** (default) |
| `--neutral-300` | slate-300 | `oklch(86.9% 0.022 252.89)` | `#cbd5e1` | Input border / stronger divider |
| `--neutral-400` | slate-400 | `oklch(70.4% 0.040 256.79)` | `#94a3b8` | Disabled text / placeholder / icon-muted |
| `--neutral-500` | slate-500 | `oklch(55.4% 0.046 257.42)` | `#64748b` | **Secondary text** |
| `--neutral-600` | slate-600 | `oklch(44.6% 0.043 257.28)` | `#475569` | Body text (light theme) |
| `--neutral-700` | slate-700 | `oklch(37.2% 0.044 257.29)` | `#334155` | Strong text / icons |
| `--neutral-800` | slate-800 | `oklch(27.9% 0.041 260.03)` | `#1e293b` | Headings; dark-theme surface |
| `--neutral-900` | slate-900 | `oklch(20.8% 0.042 265.76)` | `#0f172a` | **Primary text** (light); dark canvas |
| `--neutral-950` | slate-950 | `oklch(12.9% 0.042 264.70)` | `#020617` | Dark canvas (deepest) |

### 3.3 Accent / brand (ADOPT) — **`indigo-600` primary**
A confident, technical, non-playful blue-violet. (`blue-600 #2563eb` is the safe alternative; indigo differentiates from generic SaaS blue.)

| Token | Shade | Hex | Use |
|---|---|---|---|
| `--accent-50` | indigo-50 | `#eef2ff` | Selected-row tint, info-on-brand bg |
| `--accent-100` | indigo-100 | `#e0e7ff` | Hover tint of selected |
| `--accent-500` | indigo-500 | `#6366f1` | Focus ring, links (hover) |
| `--accent-600` | **indigo-600** | `#4f46e5` | **Primary buttons, active nav, links, key data accents** |
| `--accent-700` | indigo-700 | `#4338ca` | Primary hover/pressed |
| `--accent-fg` | white | `#ffffff` | Text/icon on accent |

> Rule: accent appears on **primary action, active nav state, links, focus ring, and the single most important number per card** — nowhere else. This single-accent discipline is what separates "enterprise" from "Frankenstein."

### 3.4 Semantic status (ADOPT) — mapped to CadVerify's domain
CadVerify's core verb is **pass / warn / fail** (DfM manufacturability) plus **info** (explainability/neutral facts). Use a 3-token-per-status set: `bg` (subtle), `fg`/`solid` (icon+text+badge), `border`.

| Semantic | Meaning in CadVerify | Solid (hex) | Subtle bg (hex) | Border (hex) | Tailwind base |
|---|---|---|---|---|---|
| **Pass / Success** | Manufacturable, within DfM limits, recommended process | `#059669` | `#ecfdf5` | `#a7f3d0` | emerald-600 / 50 / 200 |
| **Warn / Caution** | Borderline, cost-driver, review needed, "on-hold" | `#d97706` | `#fffbeb` | `#fde68a` | amber-600 / 50 / 200 |
| **Fail / Critical** | Not manufacturable as-is, blocking defect, destructive action | `#dc2626` | `#fef2f2` | `#fecaca` | red-600 / 50 / 200 |
| **Info / Neutral fact** | Glass-box explanation, assumptions, derived values | `#0284c7` | `#f0f9ff` | `#bae6fd` | sky-600 / 50 / 200 |

> Polaris note we adopt: it separates **warning** ("needs attention / in-progress / pending") from **critical** ("impossible, blocked, or error"). Map *warn = cost driver / borderline*, *fail = non-manufacturable / blocking*. ([Polaris palettes & roles](https://polaris-react.shopify.com/design/colors/palettes-and-roles))
> **Accessibility:** never encode status by color alone — pair every status with an icon + label (badge text "Pass/Warn/Fail"), per WCAG. Confidence levels (reconstruct, matcher) get the same `info`/`warn` treatment, not a separate palette.

### 3.5 Surface / elevation layering (ADOPT, Carbon "layering model")
Carbon layers neutrals to create zones/depth. ([Carbon themes](https://carbondesignsystem.com/elements/themes/overview/)) For CadVerify, define **layer tokens** so panels-in-panels (e.g., issue list inside a card inside the dashboard) stay legible:

| Token | Light | Dark | Use |
|---|---|---|---|
| `--surface-canvas` | `#f8fafc` (slate-50) | `#020617` | App background behind everything |
| `--surface-1` | `#ffffff` | `#0f172a` | Cards, panels, table, top/side nav |
| `--surface-2` | `#f1f5f9` | `#1e293b` | Nested panel, table header, inset, code/JSON blocks |
| `--surface-3` | `#e2e8f0` | `#334155` | Hover/active rows, selected states |
| `--border` | `#e2e8f0` | `#1e293b` | Hairline dividers (1px) |
| `--border-strong` | `#cbd5e1` | `#334155` | Inputs, emphasized separators |

**Text tokens:** `--text-primary` `#0f172a` / dark `#f1f5f9`; `--text-secondary` `#475569` / `#94a3b8`; `--text-muted` `#94a3b8` / `#64748b`; `--text-on-accent` `#fff`.

### 3.6 Dark mode (ADOPT)
Ship light + dark from day one (the 3D viewer and enterprise night-shift floors both benefit). Implement via `@theme` light defaults + a `.dark` class overriding the same CSS variables (Tailwind v4 + shadcn convention). Keep semantic *hues* constant, swap *surfaces/text* per §3.5.

---

## 4. Typography

### 4.1 Font choice (ADOPT)
- **UI sans: keep Geist Sans** (already loaded) — geometric-humanist, neutral, technical; an excellent peer to IBM Plex Sans/Inter. (Carbon uses IBM Plex Sans for the same "reads as product, not marketing" reason. ([Carbon typography](https://carbondesignsystem.com/elements/typography/overview/))) **Fix the bug**: remove `font-family:Arial` from `body`; bind `--font-sans: var(--font-geist-sans)`.
- **Numeric / mono: Geist Mono** (already loaded) for **costs, lead-times, dimensions, tolerances, part IDs, API keys, JSON/glass-box payloads**. Carbon reserves IBM Plex **Mono** for code tokens for the same reason. ([Carbon productive type set](https://v10.carbondesignsystem.com/guidelines/typography/productive/))
- **Tabular figures everywhere numbers align** (tables, cost cards, history): apply `font-variant-numeric: tabular-nums` (`tabular-nums` utility) so digits don't jitter between rows.

### 4.2 Type scale (ADOPT) — Carbon "productive" set, expressed in Tailwind
CadVerify is a **productive** (data/task) app, not an editorial one — so adopt Carbon's *productive* type set, which is calibrated for dense product UI. Exact Carbon values (IBM Plex Sans, px/line-height/weight): ([Carbon productive type set](https://v10.carbondesignsystem.com/guidelines/typography/productive/))

| Role (CadVerify name) | Size / line-height | Weight | Carbon token | Tailwind |
|---|---|---|---|---|
| `caption` (badge, table meta, helper) | 12 / 16 | 400 | label-01 / helper-text-01 | `text-xs leading-4` |
| `body-sm` (table cells, secondary) | 14 / 18 | 400 | body-short-01 | `text-sm leading-[18px]` |
| `body` (default body) | 14 / 20 | 400 | body-long-01 | `text-sm leading-5` |
| `body-lg` (lead paragraph) | 16 / 24 | 400 | body-long-02 | `text-base leading-6` |
| `label` / `h-eyebrow` | 12 / 16, +tracking, uppercase | 600 | productive-heading-01* | `text-xs font-semibold uppercase tracking-wide` |
| `h-section` (card title) | 16 / 22 | 600 | productive-heading-02 | `text-base font-semibold leading-[22px]` |
| `h-page` (page title) | 20 / 28 | 600 | productive-heading-03 | `text-xl font-semibold leading-7` |
| `h-display` (hero metric, e.g. unit cost) | 28 / 36 | 600 | productive-heading-04 | `text-[28px] font-semibold leading-9` |
| `h-display-xl` (rare, marketing/empty) | 32 / 40 | 600 | productive-heading-05 | `text-[32px] font-semibold leading-10` |

> Cross-check (sanity): Material 3 uses 12/14/16 body, 14 label, 22/16/14 title, 24/28/32 headline — i.e. the same compact rhythm. ([M3 type scale](https://m3.material.io/styles/typography/type-scale-tokens)) Keep the app between **12–20px** for 95% of UI; reserve 28/32 for a *single* hero number (unit cost / lead time). **Base UI font-size = 14px** (Carbon/enterprise default), *not* 16 — this is a defining "productive app" choice vs marketing sites.

### 4.3 Type rules (ADOPT)
- Max 2 weights in product: **400 (regular)** and **600 (semibold)**. (Avoid 500/700 sprawl.)
- Headings = semibold slate-900; body = regular slate-600/700; never pure black on white (use slate-900 `#0f172a`).
- Line length for prose (docs, explanations) capped ~72ch; data tables are full-width.
- Mono + `tabular-nums` for any column of numbers; right-align numeric columns.

---

## 5. Spacing, grid & density

### 5.1 Base unit & scale (ADOPT) — 4/8px
Carbon's mini-unit is the **8px square**, with a spacing scale in multiples of 2/4/8. ([Carbon 2x grid](https://carbondesignsystem.com/elements/2x-grid/overview/), [Carbon spacing](https://carbondesignsystem.com/elements/spacing/overview/)) Atlassian's base unit is 8px = `space.100`, every token a multiple, range 0–80px. ([Atlassian spacing](https://atlassian.design/foundations/spacing)) Adopt Carbon's exact ramp (it maps 1:1 to Tailwind's 4px step):

| Token | px | Carbon | Tailwind | Typical use |
|---|---|---|---|---|
| `space-1` | 2 | spacing-01 | `0.5` | Icon-to-text nudge, badge inset |
| `space-2` | 4 | spacing-02 | `1` | Tight inline gap |
| `space-3` | 8 | spacing-03 | `2` | **Base gap**; control inner padding-y |
| `space-4` | 12 | spacing-04 | `3` | Input padding-x, compact gaps |
| `space-5` | 16 | spacing-05 | `4` | **Default component padding / gap** |
| `space-6` | 24 | spacing-06 | `6` | Card padding, section gap |
| `space-7` | 32 | spacing-07 | `8` | Between major sections |
| `space-8` | 40 | spacing-08 | `10` | Page section spacing |
| `space-9` | 48 | spacing-09 | `12` | Page top padding, large gaps |

(Carbon documents spacing-01…09 = 2,4,8,12,16,24,32,40,48px. ([Carbon spacing per practical breakdown](https://design.gothe.se/10251/)))

### 5.2 Density modes (ADOPT) — ship three, default "comfortable"
Data-table density is "three named modes, not a single fixed value": compact / comfortable / spacious. Guidance: **compact 40–44px**, **standard/comfortable 48–56px** rows; Material baseline 52dp row / 56dp header; MUI compact/standard/comfortable = 32/49/65px; ≥16px left/right cell padding. ([Setproduct data-table guide](https://www.setproduct.com/blog/data-table-ui-design), [MUI row height](https://mui.com/x/react-data-grid/row-height/), [Carrie Lee, enterprise tables](https://medium.com/@calee607/data-table-design-guidelines-for-enterprise-applications-40f7ef0e0186)) Ant Design's default `controlHeight` is **32px** — the enterprise control baseline. ([AntD layout/space](https://ant.design/docs/spec/layout/))

**ADOPT for CadVerify:**

| | Row height | Cell padding-y | Font | Use |
|---|---|---|---|---|
| Compact | 36px | 6px | `body-sm` 14 | Batch results, history, large datasets (power users) |
| **Comfortable (default)** | 44px | 10px | `body-sm` 14 | Analyses list, issue lists |
| Spacious | 52px | 14px | `body` 14 | Touch/review contexts |

**Control heights (ADOPT):** inputs/buttons/selects = **36px** default (`h-9`), small = 32px (`h-8`), large = 44px (`h-11`). Min touch target 44px where relevant. Min ≥16px cell side padding.

### 5.3 App layout grid (ADOPT)
- **Kill the `max-w-3xl` document.** Enterprise app shell = **fluid full-width** with a content `max-w-screen-2xl` (1536px) for ultra-wide, and inner content gutters of 24–32px.
- 12-column fluid grid for dashboards; standard column gap 24px (`space-6`).
- Sidebar **256px** (expanded) / **64px** (rail/collapsed). Topbar **56px**. Content region = remaining width.

### 5.4 Radius & elevation (ADOPT)
- **Radius scale** (compact, technical — small radii read more "instrument" than "consumer"): `radius-sm 4px` (badges, inputs, buttons), `radius-md 6px` (cards, menus — default), `radius-lg 8px` (modals, large panels), `radius-full` (avatars, status dots, pills). (M3 shape rationale: a stepped corner scale none→xs(4)→sm(8)→md(12)→lg(16)→xl(28); we choose the tighter end for a productive app. ([M3 typography & shape](https://m3.material.io/styles/typography/type-scale-tokens)))
- **Elevation** — keep flat; depth via **borders + surface tint**, not heavy shadows (Carbon-style). Only two shadows: `shadow-sm` (cards/dropdowns: `0 1px 2px 0 rgb(15 23 42 / 0.06)`), `shadow-md` (popovers/modals: `0 4px 12px -2px rgb(15 23 42 / 0.12)`). Overlays use a `rgb(15 23 42 / 0.4)` scrim ("blanket").

---

## 6. Component set (the primitive library)

Build/skin these as shadcn components themed with §3–§5 tokens. **Left = generic primitive; right = CadVerify usage it must serve.** All interactive components inherit Radix accessibility (keyboard + ARIA). ([shadcn/ui](https://ui.shadcn.com/))

### 6.1 App shell & navigation
- **AppShell**: persistent **left sidebar** + **topbar** + content region. Sidebar is right for "products with many sections or complex hierarchies… remains visible as users scroll." ([Lollypop SaaS nav](https://lollypop.design/blog/2025/december/saas-navigation-menu-design/))
- **Sidebar** (256/64px): grouped nav (see §7), active item uses `--accent-600` left-border + tinted bg; collapsible to icon-rail; persists collapse state.
- **Topbar** (56px): breadcrumbs (left) · global **command/search** (center) · environment/org switcher, notifications, account menu, **theme toggle** (right).
- **Breadcrumbs**: location-based (reflect IA hierarchy, *not* history); show current location; truncate middle on overflow. ([Eleken breadcrumbs](https://www.eleken.co/blog-posts/breadcrumbs-ux))
- **Command palette** (⌘K): jump to any part, run analysis, search history — Radix-based; satisfies "any feature within 2–3 clicks." ([Pencil & Paper nav](https://www.pencilandpaper.io/articles/ux-pattern-analysis-navigation))
- **PageHeader**: title (`h-page`) + subtitle + primary action(s) right-aligned + optional tabs/secondary nav row.

### 6.2 Data display
- **DataTable** (TanStack + shadcn): sticky header (`surface-2`), sortable columns, row selection (batch), column visibility, pagination, right-aligned numeric (mono/tabular), inline row actions, density switch (§5.2), zebra optional. ([shadcn data table](https://ui.shadcn.com/docs/components/radix/data-table)) → *Analyses history, batch items, corpus/label rows, API keys.*
- **Card**: header (title + optional badge + actions), body, optional footer. Variants: **MetricCard** (label + big mono value + delta + trend spark), **DecisionCard** (recommendation + rationale), **PanelCard** (list container). → *Cost decision, process scores, make-vs-buy.*
- **Badge / StatusPill**: `pass | warn | fail | info | neutral`, with leading icon + text (never color-only). Sizes sm/md. → *DfM verdicts, confidence, batch item status.*
- **Stat / KPI row**: 2–4 MetricCards across the top of a page (unit cost, lead time, recommended process, confidence).
- **DescriptionList (key-value)**: 2-col label/value grid for part metadata, assumptions, glass-box inputs (mono values).
- **Tabs** (Radix): underline style; for switching analysis views (Issues / Features / Cost / Processes). Secondary "segmented control" variant for density/units toggles.
- **Tooltip / Popover / HoverCard** (Radix): glass-box "why?" explanations on any derived number — core to the transparent positioning.
- **CodeBlock / JSONViewer**: mono, `surface-2`, copy button — for API responses, raw payloads, share/embed snippets.
- **Charts** (Recharts): line (cost vs quantity / make-vs-buy crossover), bar (process comparison), themed by CSS-var tokens. Annotate crossover point explicitly.

### 6.3 Inputs & forms
- **Button**: variants `primary` (accent-600), `secondary` (surface-1 + border), `ghost`, `destructive` (red-600), `link`; sizes sm/md/lg; loading + icon-only states. One primary per view.
- **Input / Textarea / Select / Combobox / Checkbox / Radio / Switch / Slider** (Radix where interactive): 36px height, slate-300 border, accent focus ring (2px `accent-500` + offset), error state (red border + helper). Label above, helper/error below.
- **FileDropZone / Uploader**: drag-drop + click, accepted-types hint (STEP/STL/images), progress, per-file validation errors, success state, multi-file (batch). → *Replace/standardize the existing `FileDropZone`, `ImageUploader`, `BatchUploadForm` on one primitive.*
- **Form**: react-hook-form + zod (shadcn `Form`); inline validation; section grouping; sticky action footer for long forms (rule packs, profiles).
- **NumberField with unit**: value (mono) + unit suffix + unit-system toggle (mm/in, $/€) — recurring in a CAD/cost app.

### 6.4 Feedback & states (the "states matrix" — ADOPT, all four required per surface)
Every data surface must define all four:
1. **Empty**: icon + one-line explanation + primary CTA (e.g., "No analyses yet — Upload a CAD file"). Used on first-run dashboard, empty history, empty batch.
2. **Loading**: **skeletons** matching final layout (table-row skeletons, card skeletons) — *not* spinners — plus progress for long jobs (analysis, reconstruct, batch) with stage labels (glass-box: show *what* it's doing).
3. **Error**: inline error card with cause + retry; field-level for forms; toast for transient. Never a dead screen.
4. **Loaded/partial**: content; if partial (e.g., cost computed, lead-time pending) show per-section loading, not a blocked page.
- **Toast** (sonner, installed): success/info/warn/error, top-right, auto-dismiss + close; use for async confirmations (saved key, share link copied, batch queued).
- **Dialog / Sheet / Drawer / AlertDialog** (Radix): modal for focused tasks (create API key, share); AlertDialog for destructive confirm (revoke key, delete). Sheet/side-drawer for detail-without-leaving-context (inspect a batch item, an issue).
- **Progress / ProgressStepper**: multi-stage jobs (upload → parse → analyze → cost) with current-stage emphasis.
- **ConfidenceBadge**: reconstruct/matcher confidence as `info`/`warn`/`fail` pill + numeric % (mono) + tooltip explaining basis. → *standardize the existing `ConfidenceBadge`.*

### 6.5 Component inventory mapping (existing → primitive)
| Existing bespoke component | Recompose on |
|---|---|
| `CostDecisionCard`, `ProcessScoreCard` | `Card` / `MetricCard` / `DecisionCard` + `Badge` |
| `IssueList`, `FeaturesList` | `PanelCard` + list rows + `StatusPill` |
| `AnalysisHistoryTable`, `batch/BatchItemsTable` | `DataTable` |
| `FileDropZone`, `reconstruct/ImageUploader`, `batch/BatchUploadForm` | `FileDropZone`/`Uploader` |
| `ConfidenceBadge` | `Badge`/`StatusPill` (info/warn) |
| `QuotaDisplay`, `batch/BatchProgressBar`, `reconstruct/ReconstructionProgress` | `Progress`/`ProgressStepper` |
| `ShareModal`, `RevealOnceModal`, `keys` reveal | `Dialog`/`AlertDialog` |
| `RulePackSelector` | `Select`/`Combobox` |
| `(dashboard)/layout` top-nav | `AppShell` + `Sidebar` + `Topbar` |

---

## 7. Information architecture & navigation

### 7.1 The core problem to fix
Two route trees (`dashboard/*` + `(dashboard)/*`) = two IAs. **Consolidate into one app shell** under the route group `(dashboard)`; delete/redirect the legacy `dashboard/*` tree. Replace `max-w-3xl` top-nav with the §6.1 sidebar shell.

### 7.2 Global nav structure (CADVERIFY-SPECIFIC)
Group by **mental model / workflow**, not by feature list (per "match users' mental models… 2–3 clicks to any feature"). ([Lollypop](https://lollypop.design/blog/2025/december/saas-navigation-menu-design/), [Pencil & Paper](https://www.pencilandpaper.io/articles/ux-pattern-analysis-navigation)) Proposed sidebar:

```
[ CadVerify ▾ ]   ← org/workspace switcher (enterprise: Zoox / Aramco tenants)

ANALYZE
  • Dashboard            /            (overview, recent, KPIs)
  • New analysis         /analyze     (upload STEP/STL → DfM + cost)
  • Cost & make-vs-buy   /cost
  • Batch                /batch
  • Image → 3D           /reconstruct

LIBRARY
  • Analyses (history)   /analyses
  • Parts / Corpus       /label       (ground-truth labeling)

DEVELOP
  • API keys             /keys
  • API docs             /docs

──────────────  (footer, pinned bottom)
  • Settings / Profile / Rule packs
  • Account menu (avatar)   theme toggle
```

Rationale: **ANALYZE** = the daily verb (do work). **LIBRARY** = look back / curate ground truth. **DEVELOP** = integrate (procurement/IT-credible). The labeling tool (`/label`) is reframed as *Parts/Corpus* under Library so it stops looking like an orphan internal tool.

### 7.3 Page hierarchy & templates (ADOPT)
Standardize three page templates so every screen feels same-family:
1. **List/Index template** (Dashboard, Analyses, Batch, Keys): PageHeader (title + primary CTA) → optional KPI row → filter/search bar → DataTable → pagination. Empty/loading/error states (§6.4).
2. **Detail template** (single analysis, single batch item, cost page): Breadcrumb → PageHeader (part name + status pill + actions: Share/PDF/Re-run) → KPI row (unit cost · lead time · process · confidence) → Tabs (Overview / Issues / Features / Cost / Processes / 3D) → tab body (cards + viewer + glass-box panels).
3. **Task/Flow template** (New analysis, Reconstruct, Create key): centered focused column (max ~720px) → stepper/uploader → progress → result hands off to a Detail page.

### 7.4 Navigation rules (PATTERN)
- **Persistent primary nav** always visible; **highlight current section** (active state). ([Lollypop](https://lollypop.design/blog/2025/december/saas-navigation-menu-design/))
- **Breadcrumbs** on all Detail pages: `Analyses / Bracket-rev3.step` — location-based, reflect hierarchy. ([Eleken](https://www.eleken.co/blog-posts/breadcrumbs-ux))
- **Global search / ⌘K** reachable from anywhere; searches parts, analyses, processes.
- **Shallow hierarchy**: any feature ≤2–3 clicks. ([Pencil & Paper](https://www.pencilandpaper.io/articles/ux-pattern-analysis-navigation))
- **URL = IA**: `/analyses/[id]`, `/batch/[id]`, `/cost?part=…` — predictable, shareable. Share routes (`/s/[shortId]`) render the Detail template read-only.
- Tabs for *within-object* views (an analysis's facets); sidebar for *between-object* navigation. Don't mix.

---

## 8. Cross-cutting state, density & content rules (ADOPT)
- **Numbers are first-class**: mono + `tabular-nums`, right-aligned, unit-suffixed, consistent precision (e.g., cost 2 dp, lead-time integer days). The *one* hero number per card uses `h-display`.
- **Status discipline**: pass/warn/fail/info only for real status; icon+label always; never color-only.
- **Glass-box affordance**: any derived value carries a "why?" Tooltip/Popover with inputs/assumptions (mono). This is the product's differentiator — make it a *component contract*, not ad-hoc.
- **One primary action per view**; everything else secondary/ghost.
- **Skeletons over spinners**; staged progress for long jobs with human-readable stage names.
- **Density toggle** persisted per user; default comfortable.
- **Empty states sell the next step** (CTA), never a blank panel.

---

## 9. Tailwind v4 implementation notes (ADOPT)
Tokens live in `@theme` as CSS variables; dark mode overrides the same vars under `.dark`. Skeleton (illustrative — real values from §3–§5):

```css
/* globals.css — replace the starter file */
@import "tailwindcss";

@theme {
  /* fonts (fix the Arial bug) */
  --font-sans: var(--font-geist-sans);
  --font-mono: var(--font-geist-mono);

  /* neutrals (slate, OKLCH per Tailwind v4) */
  --color-neutral-50:  oklch(98.4% 0.003 247.86);
  --color-neutral-200: oklch(92.9% 0.013 255.51);  /* border */
  --color-neutral-500: oklch(55.4% 0.046 257.42);  /* secondary text */
  --color-neutral-900: oklch(20.8% 0.042 265.76);  /* primary text */
  /* …200/300/400/600/700/800/950 from §3.2 */

  /* accent */
  --color-accent:      #4f46e5;  /* indigo-600 */
  --color-accent-fg:   #ffffff;

  /* semantic */
  --color-pass: #059669; --color-pass-bg: #ecfdf5; --color-pass-bd: #a7f3d0;
  --color-warn: #d97706; --color-warn-bg: #fffbeb; --color-warn-bd: #fde68a;
  --color-fail: #dc2626; --color-fail-bg: #fef2f2; --color-fail-bd: #fecaca;
  --color-info: #0284c7; --color-info-bg: #f0f9ff; --color-info-bd: #bae6fd;

  /* radius */
  --radius-sm: 4px; --radius-md: 6px; --radius-lg: 8px;
}

/* semantic surface/text aliases (theme-swappable) */
:root {
  --surface-canvas:#f8fafc; --surface-1:#fff; --surface-2:#f1f5f9; --surface-3:#e2e8f0;
  --border:#e2e8f0; --text-primary:#0f172a; --text-secondary:#475569; --text-muted:#94a3b8;
}
.dark {
  --surface-canvas:#020617; --surface-1:#0f172a; --surface-2:#1e293b; --surface-3:#334155;
  --border:#1e293b; --text-primary:#f1f5f9; --text-secondary:#94a3b8; --text-muted:#64748b;
}

body { background: var(--surface-canvas); color: var(--text-primary);
       font-family: var(--font-sans); }  /* remove Arial */
```
- Use shadcn `cn()` (`clsx`+`tailwind-merge`) for variant composition.
- Build a small `cva` variant set for Button/Badge/Card so the feature components in §6.5 recompose against one source of truth.
- Keep the 3D viewer's WebGL canvas as-is; only its overlay chrome (toolbar, badges, panels) consumes tokens.

---

## 10. Borrowed-from matrix (what we took from each system)
| System | What CadVerify adopts | Source |
|---|---|---|
| **IBM Carbon** | Neutral-dominant + **layering model**; productive **type set** (exact px); **spacing 01–09** (2–48px); 8px 2x grid; role-based tokens; mono reserved for code/data; flat-with-borders elevation | [color](https://carbondesignsystem.com/elements/color/overview/) · [type](https://v10.carbondesignsystem.com/guidelines/typography/productive/) · [spacing](https://carbondesignsystem.com/elements/spacing/overview/) · [2x grid](https://carbondesignsystem.com/elements/2x-grid/overview/) |
| **Atlassian** | Token naming `foundation.property.role.emphasis.state`; **8px base** (`space.100`), 0–80px; dedicated **chart/skeleton** color tokens | [tokens](https://atlassian.design/foundations/tokens/design-tokens) · [color](https://atlassian.design/foundations/color) · [spacing](https://atlassian.design/foundations/spacing) |
| **Shopify Polaris** | Semantic alias tokens `color.[bg/border/text/icon].[role]`; **warning vs critical** distinction (→ warn vs fail); semantic text variants | [color tokens](https://polaris-react.shopify.com/design/colors/color-tokens) · [palettes & roles](https://polaris-react.shopify.com/design/colors/palettes-and-roles) |
| **Material 3** | Compact type rhythm sanity-check (body 12/14/16; title 14/16/22); stepped corner-radius scale (we pick tight end) | [type scale tokens](https://m3.material.io/styles/typography/type-scale-tokens) |
| **Untitled UI** | 12-step 25–950 ramp idea (we map to Tailwind); **brand-500/600 primary**; flat neutral gray; success/warning/error feedback set | [color palettes](https://www.untitledui.com/blog/figma-color-palettes) |
| **Ant Design** | Enterprise **controlHeight ≈32px** baseline; data-heavy form/table orientation | [layout spec](https://ant.design/docs/spec/layout/) |
| **MUI X / Material / Setproduct** | Three density modes; row heights 36/44/52; ≥16px cell padding | [MUI row height](https://mui.com/x/react-data-grid/row-height/) · [Setproduct](https://www.setproduct.com/blog/data-table-ui-design) · [Carrie Lee](https://medium.com/@calee607/data-table-design-guidelines-for-enterprise-applications-40f7ef0e0186) |
| **shadcn/ui + Radix + TanStack** | Owned, Tailwind-native, accessible primitive layer + data table | [shadcn](https://ui.shadcn.com/) · [data table](https://ui.shadcn.com/docs/components/radix/data-table) · [comparison](https://www.inspoai.io/blog/ui-component-library-comparison) |
| **IA references** | Sidebar for complex hierarchy; persistent nav + active state; location breadcrumbs; ⌘K; ≤2–3 clicks | [Lollypop](https://lollypop.design/blog/2025/december/saas-navigation-menu-design/) · [Eleken](https://www.eleken.co/blog-posts/breadcrumbs-ux) · [Pencil & Paper](https://www.pencilandpaper.io/articles/ux-pattern-analysis-navigation) |

---

## 11. Implementation priority (for the later build cycle)
1. **Token layer** — rewrite `globals.css` `@theme` (§9); fix Arial bug; wire light/dark.
2. **Primitive layer** — install shadcn + Radix + lucide + clsx/tailwind-merge; generate Button, Badge/StatusPill, Card, Input/Select, Table, Tabs, Dialog/Sheet, Tooltip, Skeleton, Sonner.
3. **App shell** — `AppShell`/`Sidebar`/`Topbar`/`Breadcrumbs`/`PageHeader`; consolidate the two route trees into one `(dashboard)` shell (§7.1).
4. **DataTable** — TanStack-backed; migrate Analyses/Batch/Keys.
5. **Recompose feature components** per §6.5; enforce the states matrix (§6.4) and glass-box tooltip contract (§8).
6. **Density toggle + dark mode** polish.

---

## 12. Sources (all reachable as of 2026-06-29 unless noted)
- IBM Carbon — Color: https://carbondesignsystem.com/elements/color/overview/
- IBM Carbon — Themes/layering: https://carbondesignsystem.com/elements/themes/overview/
- IBM Carbon — Typography: https://carbondesignsystem.com/elements/typography/overview/
- IBM Carbon — Productive type set (exact px): https://v10.carbondesignsystem.com/guidelines/typography/productive/
- IBM Carbon — Spacing: https://carbondesignsystem.com/elements/spacing/overview/
- IBM Carbon — 2x Grid: https://carbondesignsystem.com/elements/2x-grid/overview/
- Carbon spacing values (secondary, exact 01–09): https://design.gothe.se/10251/
- Atlassian — Design tokens: https://atlassian.design/foundations/tokens/design-tokens
- Atlassian — Color: https://atlassian.design/foundations/color
- Atlassian — Spacing: https://atlassian.design/foundations/spacing
- Shopify Polaris — Color tokens: https://polaris-react.shopify.com/design/colors/color-tokens
- Shopify Polaris — Palettes & roles: https://polaris-react.shopify.com/design/colors/palettes-and-roles
- Shopify Polaris — Typography tokens: https://polaris-react.shopify.com/design/typography/typography-tokens
- Material 3 — Type scale tokens: https://m3.material.io/styles/typography/type-scale-tokens
- Untitled UI — Color palettes guide: https://www.untitledui.com/blog/figma-color-palettes
- Ant Design — Layout spec: https://ant.design/docs/spec/layout/
- Tailwind CSS v4 — Colors (OKLCH): https://tailwindcss.com/docs/colors
- shadcn/ui — Home: https://ui.shadcn.com/
- shadcn/ui — Data Table: https://ui.shadcn.com/docs/components/radix/data-table
- UI library comparison (shadcn vs Radix vs Chakra vs MUI): https://www.inspoai.io/blog/ui-component-library-comparison
- MUI X — Data grid row height/density: https://mui.com/x/react-data-grid/row-height/
- Setproduct — Data table UI design guide: https://www.setproduct.com/blog/data-table-ui-design
- Carrie Lee — Data tables for enterprise apps: https://medium.com/@calee607/data-table-design-guidelines-for-enterprise-applications-40f7ef0e0186
- Lollypop — SaaS navigation menu design: https://lollypop.design/blog/2025/december/saas-navigation-menu-design/
- Eleken — Breadcrumbs UX 2026: https://www.eleken.co/blog-posts/breadcrumbs-ux
- Pencil & Paper — Navigation UX patterns for SaaS: https://www.pencilandpaper.io/articles/ux-pattern-analysis-navigation

**Unreachable / partial during research:** Carbon spacing & typography *overview* pages returned truncated bodies via fetch (exact values recovered from the v10 productive-type page and the gothe.se breakdown above). The Material-3-skill GitHub typography file returned 404; M3 values taken from the official m3.material.io type-scale page + search summary. Polaris typography-tokens page is conceptual (no px in body); exact Polaris px not quoted — Polaris is used here only for *semantic-token structure*, not numeric scale.
