# Home page execution fix — note

**Date:** 2026-06-30. **Scope:** `frontend/src/app/page.tsx`, `frontend/src/app/globals.css`,
`frontend/src/components/marketing/black-box-reveal.tsx`. Identity unchanged (Datum Blue, Archivo
Expanded, Geist/Geist Mono, machinist-paper/blueprint-twilight). Only the EXECUTION changed.

The render critique was almost certainly captured with the OS in dark preference: because every
section used the theme-flipping semantic tokens (`bg-canvas` / `bg-card`), the whole page collapsed
to one dark navy slab. Fix at the root: **the marketing home is now a curated light↔dark composition,
not a document that inverts with the OS theme.**

---

## 1. Reclaim the light, create rhythm (the #1 fix)
- Added two palette-LOCKING scope classes in `globals.css`: `.cv-paper` (warm machinist-paper light)
  and `.cv-twilight` (blueprint-twilight). They re-declare the `--cv-*` semantic vars for their
  subtree, so custom-property inheritance overrides any ancestor `.dark`. The page therefore reads
  light-dominant **in either OS mode**, and both palettes are exercised and correct on one page.
- New section rhythm (9 sections), top→bottom: **DARK** hero → **LIGHT** reveal → **LIGHT** compare →
  **LIGHT** calibration → **LIGHT** crossover → **DARK** "honest" band → **LIGHT** routing/DFM →
  **LIGHT** trust → **DARK** CTA. That's **6 light : 3 dark** — warm paper is the dominant canvas;
  twilight is punctuation (hero plate instrument, one candid mid-page band, the close).
- Tonal variation inside the light run so sections don't blur: `bg-canvas` (#f7f5f1) ↔ `bg-card`
  (#fff) ↔ `bg-card-raised` (#f1ede6 warm sunken) alternate across the paper sections.
- Verified in the served HTML: `cv-paper` ×6 sections, `cv-twilight` ×3, `cv-hero-field` ×1.

## 2. Vary the section rhythm
Each section now has a distinct composition instead of headline+dark-panel repeated:
- Reveal: centered single device. Compare: full-bleed comparison. Calibration: asymmetric
  `0.85fr / 1fr` split (story left, board right). Crossover: centered interactive dial on a warm
  sunken panel. Honest: two-column dark band. Routing/DFM: two-card grid. Trust: 4-up + a quiet
  fact strip. Vertical padding opened up to `py-24 lg:py-28/32` for breathing room.

## 3. De-densify the tables
- **Incumbent comparison** rebuilt from a 7-row dense `<table>` into a 4-row CSS-grid board:
  `py-6` rows (was `py-3.5`), `leading-relaxed`, a clear hierarchy (dimension = `font-semibold`
  foreground label; incumbents muted; the CadVerify column is the lit accent panel). Horizontal
  scroll preserved for mobile.
- **Calibration board**: now renders 3 illustrative processes (`mjf`, `cnc_turning`,
  `injection_molding`) sliced from the full five — fewer rows, more air, still real engine numbers.

## 4. Reduce signature repetition
- The monumental Decision Plate `$14.14` is now the **only** monumental number on the page (hero
  signature, once).
- Black-box→glass-box reveal: both `$14.14` readouts dropped from `text-5xl`/`text-4xl` to
  `1.75rem` — they still make the "same number, one shows its work" point in the brand number-voice,
  but no longer re-stamp the monument.
- The proof band's four monumental `cv-readout-hero` stats were removed; the facts now live as a
  quiet **mono** strip ("the only numbers we'll stand behind") inside the trust section.

## 5. Restraint (remove one accessory per section)
- Cut the entire **role-aware "One engine, four jobs"** section (4 near-identical cards — the most
  template-slab-like block) and folded the standalone proof band into the trust section.
- Removed the decorative `01 / 02 / … / 07` eyebrow indices everywhere (the sections aren't an
  ordered sequence, so the numbering encoded nothing — per the design-skill guidance).
- Page went from 11 sections to 9.

## 6. Copy polish + eyebrow legibility
- Eyebrows: bumped from 11px to **13px**, tracking `0.12em → 0.16em`, color → `accent-text`
  (higher contrast, ties to the datum tick). Confirmed live in the served CSS bundle.
- Tightened copy to active voice ("which process to make it by"; "It decides how the part is made —
  and shows its reasoning"; trust descriptions de-passivized). Proofread throughout — no
  "increments"/typo present (0 matches in source and rendered output). Kept the honest n=0 /
  "assumption-based, not yet validated" framing verbatim; no fabricated accuracy anywhere.

---

## Build proof
```
npx tsc --noEmit   → exit 0 (green)
npm run build      → exit 0, "✓ Compiled successfully", "/" prerendered as ○ (Static)
```
Served the production build and curled `/` → HTTP 200; verified scope counts, removed sections,
reduced monument count (4 `cv-readout-hero` spans = the 2-part hero plate figure + the 2 small
reveal numbers), and the eyebrow rule in the live CSS.

**No git commit made.** `/method` left as-is this round.
