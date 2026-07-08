# Phase 0 — Reconcile & re-found (impl note)

**Branch:** `feat/p0-refound` (off `dev`) · **Worktree:** `cadverify-wt-refound`
**Scope:** frontend only — the debt-clearance that swaps the visual identity from
"glowing gauge in a dark cockpit" → "governed catalog," re-founding the
already-shipped single-part cost/DFM loop. No backend changes (the Replicate
image→mesh egress is a separate builder).

Result: `tsc --noEmit` clean · `npm test` 17/17 green · `next build --webpack`
succeeds, all 20 app routes register.

---

## 1. The token swap (before → after identity)

Rewrote `src/app/globals.css` — the single biggest visible change.

| | BEFORE ("Bold Industrial Confidence") | AFTER ("Governed Catalog") |
|---|---|---|
| Neutrals | warm machinist limestone (`#f7f5f1` / warm bone) | cool **graphite** ramp |
| Default theme | OS-dependent; light = warm paper | **DARK-FIRST** everywhere (`.dark` added unless user pinned light); dark canvas `#080B0F` |
| Accent | Datum blue (`#0e66b3` / `#3fa3e8`), used on provenance too | **ONE scarce COBALT** (`#205AAE` light / `#4C90F0` dark) — action / active nav / focus / selection / the one hero-metric marker only |
| Provenance | measured shared the blue accent | held **APART from cobalt**: MEASURED teal `#0E7C86`, SHOP bronze `#A9682A`, USER indigo `#5B4FC0`, DEFAULT hollow outline (no fill) |
| Hero answer | Archivo Expanded, monumental signage (`cv-readout-hero`, 96px) | **Geist Mono**, tight, `--text-readout` = 44px (`.readout`) — a governed metric |
| Base UI | 14px (`text-sm`) | **13px** — retuned Tailwind `--text-sm` → `0.8125rem` in one token (the productive-app tell) |
| Depth | milled-metal faceplate/bezel/well + blueprint field + halo/bloom + inner highlights | **flat + structural**: hairline 1px borders + surface-tint elevation; exactly **one** soft shadow (`0 8px 24px -8px rgb(8 13 20/.24)`) reserved for overlays |
| Radius | chips 2 / buttons 4 / cards 6 / panels 10 | chips/controls **4** · cards **6** · panels **8** |
| Motion | `cv-settle` 520ms gauge-needle settle, blur-in | Linear discipline 120/160/240ms, opacity+transform only; `cv-reveal` ≤160ms; `prefers-reduced-motion` honored |

**Retired from the authed app:** the milled-metal `cv-faceplate` / `cv-bezel` /
`cv-viewer-well` / `cv-obsidian`, the blueprint `cv-hero-field`, the halo/bloom
gradients, `cv-settle`, and Archivo (`cv-display` / `cv-readout-hero`). Removed
the dead `cv-viewer-well` / `cv-elev` / `cv-display-tight` entirely.

**Token-drift consolidation:** `:root` (light graphite) and `.dark` (dark
graphite) are now the single source for the authed app. The `.cv-paper` /
`.cv-twilight` (and the faceplate/hero-field/obsidian) rules are **fenced under a
clearly-labelled "LEGACY — MARKETING ONLY" block** and are used by no authed
surface — they exist solely so the deferred marketing pages (`/`, `/method`)
keep rendering (open design question §8 #9: marketing re-founding is a separate
founder call). They no longer duplicate the app's ramp.

**Kept (honesty rail, verbatim):** `.cv-hatch` (the assumption/data-quality
hatch), `.cv-eyebrow` (now a cobalt witness tick), `.num` / `.readout` (Geist
Mono tabular), `cv-reveal`.

Consumers re-found for free: every `glass-box/*` component, the gen-2 workspace
views, and the persisted-decision path use **semantic tokens** (`bg-card`,
`text-foreground`, `text-prov-*`, `cv-eyebrow`, `border-border`), so the ramp
swap re-skins them with no per-file edits.

---

## 2. Shell unification — one 4-zone frame; the losing fork deleted

There were two decision surfaces in the tree:

- **Gen-3 (live):** `LivingInstrument` — the full-bleed "cockpit": a twilight
  blueprint field, a studio part with floating frosted HUD panels, a scrubber on
  the part, a slide-up `GlassBoxDrawer`. Hosted `/cost` + `/analyze` via a slim
  `TopStrip` shell.
- **Gen-2 (orphaned):** `PartWorkspace` — a tabbed, flat-chrome workspace,
  imported by nothing.

**Kept: the catalog-capable frame.** Rebuilt `src/components/ui/app-shell.tsx`
into the persistent **4-zone** shell:

```
rail 56 · sidebar 240 (collapsible) · context bar 48 · content · [Inspector 340]
```

- **Icon rail (56):** object domains (Workbench · Catalog · Portfolio · Sourcing
  · Calibration · Governance · Connect) + theme + account. Catalog/Portfolio/etc.
  are **present-but-disabled placeholders** with a "Phase N" tooltip — the zones
  are *ready*, but **no catalog data is faked** (Phase 1 ships the real Catalog).
- **Sidebar (240, collapsible to rail):** ⌘K search + the **real** destinations of
  the single-part loop (New analysis, Analyze DFM, Batch, Cost decisions, Compare,
  Recent analyses, API/docs) + a scaffolded (empty, honest) "Saved views" slot.
- **Context bar (48):** the lakehouse **breadcrumb** `workspace ▸ decisions ▸
  <part>` (the part is published by the workspace via the existing chrome
  context), + the **data-locality `LOCAL · zero-egress`** pill (scoped to the
  cost/DFM paths only).

**Deleted (the losing Gen-3 shell):** `LivingInstrument`, `top-strip`,
`DecisionReadout`, `QuantityScrubber`, `GhostPart`, `InstrumentControls`,
`GlassBoxDrawer` (≈2,360 lines). The `instrument-chrome` context and
`CostArtifactBar` survive (reused).

---

## 3. The L2 Decision frame + the Inspector

`src/components/workspace/PartWorkspace.tsx` is now the **L2 DECISION object
frame** (object model: *a Decision contains Estimates*), routed from `/cost`
(Design lens) and `/analyze` (Mfg lens).

- **Tabs:** **Decision · Routing & DFM · Glass Box · Compare · History**. The Role
  Lens still sets the landing tab and walls nothing off.
- **Design-lens "aha" absorbed, flattened:** the studio-lit part lives in a
  persistent left rail on a **flat graphite panel** (cad-viewer default surface,
  now theme-flipping — no bloom/well/halo), and the **make-vs-buy crossover
  scrubber** survives via `CostDecisionView`'s slider + `BreakevenChart` (log-X,
  cobalt make-curve, marked crossover) — no gauge-needle settle.
- **Reframed Inspector** (`src/components/workspace/DecisionInspector.tsx`) — the
  retired `GlassBoxDrawer` re-expressed as **infrastructure**, a resident right
  panel (open for the cost lens, collapsible otherwise) with tabs:
  - **Lineage** — directed derivation `geometry → drivers → Σ unit_cost`, nodes
    tinted by provenance tier (DEFAULT hollow), edges draw in with a 40ms stagger.
  - **Governance** — an honest **posture bar** (governed vs guessed, provenance-
    tinted) + the confidence **DATA-QUALITY track** rendered from
    `confidence.validated` **verbatim** (no fabricated ±%) + the LOCAL badge.
  - **Sources** — the driver table (provenance chip + source string + inline rate
    override → re-tags USER, re-costs live).
  - **Audit** — the applied USER overrides (the immutable log lands in Phase 2).

---

## 4. Deletions / convergences (and what was deliberately kept)

**Deleted (truly dead after the shell swap):** `LivingInstrument`, `top-strip`,
`DecisionReadout`, `QuantityScrubber`, `GhostPart`, `InstrumentControls`,
`GlassBoxDrawer`.

**Converged the redundant decision renderings:** `DecisionReadout` (the cockpit
HUD render) is **deleted**; the two survivors — `CostDecisionView` (live,
re-costs) and `SavedCostDecisionView` (read-only, persisted) — now both project
the **one shared vocabulary** (`DecisionHeadline` + `ConfidenceInterval` +
`CostDecisionCard`). Three renderings → one grammar with a read-only projection.

**Kept deliberately (deleting them breaks the build or the demo — noted per
discipline):**
- `CostDecisionCard` — load-bearing for `CostDecisionView`, `SavedCostDecisionView`,
  and the geometry-invalid **repair** card.
- `AnalysisDashboard` + `ProcessScoreCard` — `AnalysisDashboard` is embedded by the
  live **Routing & DFM** tab (`RoutingDfmView`) and by `/analyses/[id]`.
  The Gen-1 "kill" would break the DFM tab and the saved-analysis route, so they
  stay (the graphite ramp re-skins them for free).

---

## 5. Demo path + honesty preserved

- **cost + analyze:** `/cost` and `/analyze` drop → cost + DFM run in parallel
  (unchanged engine calls) → Decision/Routing/Glass Box/Compare all render.
- **Phase-2 artifact:** `CostArtifactBar` (Save / PDF / JSON / CSV / Share) is
  wired into the Decision tab when `costPersistUiEnabled() && report.saved`; it
  was re-tokenized off its twilight hardcodes onto semantic tokens. The
  `/cost-decisions`, `/cost-decisions/[id]`, `/cost-decisions/compare` and
  `/s/cost/[shortId]` pages are untouched — persisted-decision rendering is intact.
- **Honesty:** `confidence.validated` / `label` / `basis` render verbatim; the
  data-quality track is solid when validated, `cv-hatch` (provisional) otherwise;
  DEFAULT is always a hollow outline; **no fabricated ±%** is introduced anywhere.
- **Zero-egress:** the `LOCAL · zero-egress` badge is scoped to the genuinely local
  cost/DFM paths (context bar + Inspector Governance) — **not** claimed for
  image→mesh reconstruction.
- **Untouched per the "nonstandard Next.js" caution:** no routing / data-fetching /
  proxy / DAL changes — only page→component wiring and client components.

---

## 6. Tests / build

- `npx tsc --noEmit` — **clean**.
- `npm test` — **17/17 green** (breakeven / cost-views / dfm-scope pure logic;
  unchanged and unbroken). No new pure-logic modules were introduced (the shell/
  inspector helpers are trivial presentational functions), so no new suites.
- `npx next build --webpack` — **succeeds**; all 20 app routes register
  (`/cost`, `/analyze`, `/cost-decisions/*`, `/batch/*`, `/s/cost/[shortId]`, …).

**Turbopack caveat:** the worktree's `frontend/node_modules` is a symlink, on
which Turbopack panics; the build gate here uses `next build --webpack` (per the
launch brief). The orchestrator runs the real Turbopack gate in the main tree.
Nothing in this change is bundler-specific (pure token/component edits).
