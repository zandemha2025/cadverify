# Design-System Builder — log

**2026-06-29 — DONE (not blocked).**

Built the 2026 glass-box design language by elevating the existing Tailwind v4 / shadcn-on-Radix base (plumbing kept). Real, building artifacts in the repo.

## Shipped
- **Tokens** (`frontend/src/app/globals.css`): light + dark via `@theme inline → --cv-*` switched on `.dark`; added 4th provenance `SHOP` (calibration teal), confidence/band tokens, `text-readout`/`text-micro` scale, motion tokens, signature classes `.cv-eyebrow` (measurement tick) and `.cv-hatch` (unvalidated confidence). Whole app re-themes for free (verified in compiled CSS).
- **Provenance system** (`lib/status.ts`): `Provenance` now 4-way; `PROVENANCE_META` encodes fill (grounded) vs hollow (DEFAULT guess) + hue + plain-language meaning.
- **API types** (`lib/api.ts`): `CostConfidence`, `CostRouting` added; `SHOP` provenance; optional `confidence`/`routing` so today's payload still type-checks.
- **Glass-box component library** (`frontend/src/components/glass-box/`): ProvenanceChip/Dot/Legend, ConfidenceInterval/Track/Label/Chip, NumberReadout, DriverBreakdown (Σ=unit + inline drill + override), AssumptionGrid (editable → re-tag USER), ProcessComparison (process×shop, banded, lever), RoutingCard + DfmMatrix, CalibrationBar, RoleLens, DecisionHeadline + RedesignBanner. `BreakevenChart` elevated to theme-aware (= CrossoverChart).
- **Dogfood**: `CostDecisionCard` now uses `ProvenanceChip` (real `/cost` glass box gets SHOP + dark mode); `CostDecisionView`/`Badge`/`Table` migrated to dark-safe accent tokens. `ThemeToggle` + no-flash script in root layout.
- **Showcase / build proof**: `/design-system` route rendering every component against the engine's REAL report (`fixture.ts`, captured from the CLI), with live theme + role-lens toggles.
- **Deliverable doc**: `outputs/design/design-system.md`.

## Build
`npx tsc --noEmit` clean. `npm run build` green (15/15 static pages, `/design-system` prerendered). No headless browser available → no screenshot claimed; the green build (Tailwind + TS) is the proof.

## Gaps flagged for the build harness (not design-owned)
Surface `routing`/`confidence`/per-shop calibration through the API; multi-shop in one call; persisted overrides/scenarios; role-scoped share. Components are built for these; Role Lens needs no engine change.
