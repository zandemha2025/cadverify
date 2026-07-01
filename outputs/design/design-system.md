# CadVerify — Design System (2026)

**Role:** Design-System Builder. **Date:** 2026-06-29.
**Status:** Built, in the repo, compiles green (`npx tsc --noEmit` + `npm run build`).
**Scope:** the 2026 visual language + the glass-box / data-dense component library the product lives on. This **elevates** the existing cohesive Next.js 16 / React 19 / Tailwind v4 / shadcn-on-Radix base — it keeps the plumbing and pushes the language to the thesis bar. It does **not** re-decide structure (that is `ia-and-flows.md`) or re-run the engine.

**Companion docs:** `design-direction.md` (locked north star), `ia-and-flows.md` (IA + the surfaces these components fill), `audience.md` / `design-landscape.md` (the why).

---

## 0. The thesis, made into tokens (not prose)

> **Glass box is the hero. The decision, not the dollar. Role-aware. 2026 = clarity + density-done-well + trust — never consumer flashiness.**

Every decision below traces to that spine. The one memorable thing — where the boldness is spent (Chanel's "remove one accessory" rule) — is the **provenance + confidence visual system**: a number is never naked, it carries *where it came from* and *how sure we are*, and both are **honest by construction**. Everything else (slate, one steel-blue accent, flat-with-borders, fast small motion) stays quiet and disciplined so that system reads.

This is deliberately **not** any of the three current AI-design defaults (cream+serif+terracotta / near-black+acid-accent / broadsheet hairlines). The direction is **instrument-grade control-room**: cool slate, tabular mono numbers, measurement-tick motifs from the subject's own world (CAD / metrology).

---

## 1. Signature elements (what a designer would not mistake for a template)

Three content-true devices carry the brand. Each **encodes something true**, per the design skill — none is decoration.

1. **Provenance: fill = grounded, hollow = a guess.** Every engine number is tagged `MEASURED · SHOP · USER · DEFAULT`. The marker is a **filled dot** when grounded in your reality (measured off geometry, your shop's rate, your override) and a **hollow ring** when it's a generic `DEFAULT` — "we're guessing here." The gaps are *visible*, not hidden. Hue encodes source (measured-blue / calibration-teal / override-green / slate). Status is never colour-only — fill + label + hue together.

2. **Confidence: hatched = not yet validated, solid = validated.** A cost is drawn as a band (low · point · high) using a measurement-tick. While the engine's `method` is `assumption-band` the fill is **diagonally hatched** — it literally *looks* provisional. It goes **solid** only when `validated == true` (real residuals on your parts). We render `label`/`validated`/`n_samples` **verbatim** and **never** print a fabricated ±X% accuracy figure. The honesty rail is structural.

3. **The measurement-tick eyebrow (`.cv-eyebrow`).** Section labels are prefixed by a 2px steel-blue tick — a CAD dimension witness line. It ties the brand to metrology without a full blueprint skin (which would read flashy and *reduce* trust for an aerospace/heavy-industry buyer).

---

## 2. Tokens — `frontend/src/app/globals.css`

Tailwind v4 `@theme`. **Raw ramps** (slate, steel-blue, calibration-teal) are static. **Every semantic token** is `@theme inline → var(--cv-*)`, defined in `:root` (light) and `.dark` (dark). Result: toggling `.dark` on `<html>` re-themes the *whole app* — every existing `bg-card` / `text-foreground` / `bg-pass-bg` / `border-prov-*` utility switches for free, and new components are dark-correct by default. Verified in the compiled CSS: `.bg-card{background-color:var(--cv-card)}`.

### 2.1 Color

| Role | Light | Dark | Notes |
|---|---|---|---|
| canvas / card / card-raised | `#f6f8fb` / `#ffffff` / `#f8fafc` | `#080c16` / `#0f1729` / `#16203a` | deep-slate "control room" in dark |
| foreground / muted-fg / subtle-fg | `#0f172a` / `#475569` / `#64748b` | `#e8eef7` / `#93a1ba` / `#7889a3` | |
| border / border-strong | `#e2e8f0` / `#cbd5e1` | `#1f2a42` / `#324158` | flat-with-borders |
| **primary** (steel blue, LOCKED) | `#2563eb` | `#3b82f6` | accent lifts in dark for contrast |
| accent-subtle / -border / -text | `#eff6ff` / `#bfdbfe` / `#1d4ed8` | `#0f1f3d` / `#1e3a6b` / `#93c5fd` | tinted accent surfaces, dark-safe |
| pass / warn / fail / info | `#059669` / `#d97706` / `#dc2626` / `#0284c7` | `#10b981` / `#f59e0b` / `#ef4444` / `#38bdf8` | strict semantic; reserved for verdicts |

**Provenance (the atom)** — a lineage palette kept *distinct from verdict hues* so meaning doesn't muddy:

| Provenance | Hue (light → dark) | Fill | Meaning |
|---|---|---|---|
| `MEASURED` | measured-blue `#1d4ed8` → `#60a5fa` | ● filled | measured from your CAD geometry |
| `SHOP` | **calibration-teal** `#0d9488` → `#2dd4bf` | ● filled | your shop's calibrated rate |
| `USER` | override-green `#047857` → `#34d399` | ● filled | you overrode it |
| `DEFAULT` | slate `#64748b` → `#94a3b8` | ○ **hollow** | generic guess — the visible gap |

### 2.2 Typography — two voices

The personality is the *system*, not an exotic font: **a humanist sans (Geist) for the answer/prose, a tabular mono (Geist Mono) for the evidence/data.** Numbers are the product, so they speak in mono everywhere (`.num`, `font-variant-numeric: tabular-nums`).

| Token | Size / line | Use |
|---|---|---|
| `text-readout` | 40 / 44, mono, `-0.01em` | the **one** instrument hero metric (unit cost / lead time) |
| `text-display-xl` | 32 / 40 | page title |
| `text-display` | 28 / 36 | secondary hero |
| `text-base` … `text-xs` | 16 / 14 / 12 | prose, controls, labels |
| `text-micro` | 11 / 16 | provenance source strings, dense captions |

`.readout` and `.num` set tabular figures; `.cv-eyebrow` is the tick-prefixed micro label.

### 2.3 Space · radius · shadow · motion

- **8px grid** (unchanged). Density is a *lens property* — airy around the decision, compact around the data.
- **Radius:** `--radius-xs 3px` (prov chips), `--radius-sm 4px`, `--radius 6px` (default), `--radius-lg 8px` (panels). One family, "modern but not bubbly."
- **Shadow:** flat-with-borders. `shadow-sm`, `shadow-md`, and `shadow-pop` (overlays/popovers only).
- **Motion:** `--duration-fast 120ms` / `--duration 180ms`, `--ease-out`. One purposeful animation: `.cv-reveal` (inline drill-down expansion — "inline before modal"). `prefers-reduced-motion` fully honored.

---

## 3. Component library — `frontend/src/components/glass-box/`

Every component renders **real `report_to_dict` fields** (typed in `lib/api.ts`; SHOP provenance + `CostConfidence` + `CostRouting` added). Barrel: `@/components/glass-box`.

| Component | Glass-box pattern | IA surface · role (`ia-and-flows.md`) | Engine fields |
|---|---|---|---|
| `ProvenanceChip` / `ProvenanceDot` / `ProvenanceLegend` | **the atom** — provenance tag on any number, fill=grounded | universal drill-down (L3) · all | `driver.provenance` + `source` |
| `ConfidenceInterval` / `ConfidenceTrack` / `ConfidenceLabel` / `ConfidenceChip` | **confidence interval** — banded, hatched-until-validated, honesty verbatim | every cost, everywhere · all | `estimate.confidence.*` |
| `NumberReadout` | instrument hero metric + its band | Decision hero · Design/Buyer | `decision` + `confidence` |
| `DriverBreakdown` | **driver breakdown** — provenance + source, inline drill, Σ=unit check, override | Glass Box tab · Cost eng | `estimate.drivers[]` + `line_items` |
| `AssumptionGrid` | **editable assumption rows** — override → re-tag USER | Glass Box · Cost eng | `assumptions[]` |
| `ProcessComparison` | **process-comparison** — process×shop, banded cells, Δ, negotiation lever | Compare tab · Sourcing | multi-shop `estimates` + `confidence` |
| `CrossoverChart` (elevated `BreakevenChart`, now theme-aware) | **make-vs-buy / crossover** — qty curves, marked crossover | Decision · Design/Sourcing | fitted from reported `unit_cost_usd` |
| `RoutingCard` / `DfmMatrix` | routing reasoning + actionable DFM matrix | Routing & DFM tab · Mfg eng | `routing.*` + `engine_feasibility[]` + `dfm_blockers` |
| `CalibrationBar` | **calibration / shop-profile UI** — "Calibrated to <shop>" + SHOP-vs-DEFAULT panel; not-calibrated CTA | topbar context · all | `assumptions` split + shop `source` |
| `RoleLens` | role-aware default-setter (landing tab + density + disclosure) | topbar · all 5 roles | client-side; no engine change |
| `DecisionHeadline` / `RedesignBanner` | the decision hero + the "if redesigned" honesty banner | Decision · Design/Buyer | `decision.*` + `tooling_dfm_ready` |

**Dogfooded into the real screen:** `CostDecisionCard` now uses `ProvenanceChip` (so the live `/cost` glass box renders SHOP correctly and is dark-correct); `CostDecisionView`, `Badge`, `Table` migrated to the dark-safe accent tokens.

**Showcase / build proof:** `frontend/src/app/(app)/design-system/page.tsx` (route `/design-system`, in the sidebar under Develop) renders **all** components against the engine's real output (`./design-system/fixture.ts`, captured from the CLI), with a live **theme toggle** and **role-lens** switcher.

---

## 4. Accessibility

- Visible keyboard focus on every interactive element (`focus-visible:ring-2 ring-ring`).
- **Status is never colour-only:** provenance = fill + label + hue; verdicts carry a lucide icon or dot (`lib/status` `TONE_ICON`); confidence carries an icon + words.
- `color-scheme` set per theme; both themes target WCAG-AA body contrast on their surfaces.
- `prefers-reduced-motion: reduce` collapses all animation/transition.
- Editable cells are real inputs with `aria-label`, Enter/Escape handling.

---

## 5. Build proof

```
cd frontend
npx tsc --noEmit     # clean (exit 0)
npm run build        # ✓ Compiled successfully; ✓ 15/15 static pages; /design-system prerendered
```
Compiled-CSS spot checks confirm theming is wired (not static): `.bg-card{background-color:var(--cv-card)}`, `--cv-canvas` present in both light (`#f6f8fb`) and dark (`#080c16`), `.cv-eyebrow` / `.cv-hatch` emitted. No headless browser is available in this environment, so **no screenshot is claimed** — the green `next build` (which runs Tailwind and TypeScript and would fail on invalid `@theme`/`@custom-variant`) is the honest proof.

---

## 6. Notes for the build harness (design assumes; build delivers)

These are the *same* gaps `ia-and-flows.md §10` flags — the components are built **for** them:
1. Surface `routing`, `confidence`, and per-shop calibration through `/api/v1/validate/cost` → frontend (added as **optional** TS fields so today's payload still type-checks; components light up when populated).
2. Multi-shop cost in one call (for `ProcessComparison` / the Midwest-vs-Shenzhen A/B).
3. Persisted USER overrides + scenarios (the `onOverride` callbacks are wired; persistence is server work).
4. Role-scoped shareable analysis object (the Role Lens itself needs no engine change — ship it first).

---

## 7. Acceptance self-audit

- **Distinctive + intentional (not a template):** the provenance fill/hollow + hatched-confidence + measurement-tick system is specific to this subject's world and to the glass-box thesis — not one of the AI-default looks. ✓
- **Appropriate to a technical/trust audience (clear + confident, not flashy):** slate instrument-grade, one accent, flat-with-borders, fast small motion; boldness spent only on the honesty system. ✓
- **Covers the glass-box patterns the flows require:** editable assumptions, confidence intervals, driver breakdowns, process-comparison, make-vs-buy/crossover, calibration/shop-profile UI, plus the role lens + routing — each bound to a real engine field and IA surface (§3). ✓
- **Light + dark, accessible, builds green.** ✓
