# Living Instrument — Restraint Pass

**Date:** 2026-07-01. **Scope:** hierarchy / restraint / breathing room only. Locked
identity untouched (blueprint-twilight surface, Datum Blue `#0E66B3` / `#3FA3E8`,
Archivo Expanded numbers, Geist Mono data, the quantity scrubber). No new look.
All functionality + all states preserved (shop dial, knobs, override re-cost,
glass-box drawer, DFM-on-geometry, scrubber; resolving / geometry-invalid /
cost-failed / no-decision / dfm-error states all intact).

## The three stars, given the room

The screen now has **one** hierarchy: the **PART** (hero visual) + the **NUMBER**
(hero data) + the **SCRUBBER** (hero interaction). Everything else recedes or is
one click away.

## What moved / tucked / enlarged

**1. The part is now the hero visual (was tiny, lost in empty dark).**
- Canvas height `h-[340px]/sm:420px` → `h-[440px] / sm:560px / lg:620px`.
- Camera pulled in on the instrument surface: added a `distanceScale` prop to
  `cad-viewer` (`STLModel`), instrument passes `1.45` vs the default `2.0` — the
  geometry fills ~30% more of the frame instead of floating small. Scoped by prop
  so the label/reconstruct/workspace viewers are unchanged.
- The instrument grid dropped from a bright `#3fa3e8/#21314c` competing plane to a
  faint `#1f3350/#16233a` floor, so it grounds the part instead of dwarfing it.

**2. The decision column now leads with ONLY the answer (was 8 stacked, competing
blocks).**
- Kept & enlarged: "Make by <process>" + the monumental `$/unit` (up to
  `4.5rem`), the one-line crossover. Column gap widened to `gap-7`, grid gap to
  `lg:gap-8` — real air.
- **Two stat cards (lead time / at-quantity) → one quiet mono metaline**
  ("5–10 day lead · at 1,200 units"). Two bordered cards gone.
- **The ±band + verbose "not yet validated / n=0" note → a single quiet line**
  ("±40% · not yet validated") that expands to the full honest band on click.
  The honest ±/n=0 framing is kept verbatim — just no longer competing with the
  number.
- **The big amber "if redesigned" warning → a compact one-line note** (small,
  quiet ochre), not a full warn-bg block.

**3. The RECALIBRATE controls are tucked behind a click.**
- The whole shop-dial / material / region / labor panel (`InstrumentControls`) is
  now hidden by default and revealed by a **"Recalibrate"** toggle in the quiet
  action row (progressive disclosure, `cv-reveal`). It no longer clutters the
  answer; it's one click away, fully functional.

**4. The DFM flags are a calm summary strip (was a cramped scrolling wall).**
- Collapsed default now reads a quiet severity breakdown — e.g. "76 flags · 2
  critical · 1 advisory · 3 info" with small colored dots — instead of a raw
  count over a dense list. The rows still open on demand (and auto-open in DFM
  focus); expanded list given more breathing room (`max-h-56`, `space-y-2`).

## Before / after hierarchy

- **Before:** small floating part; a right column stacking 8 items (headline,
  badge, subtext, big number, band, ±note, 2 stat cards, amber banner,
  MEASURED/DEFAULT row, full Recalibrate panel) all at equal weight; DFM as a
  dense row list. Eye lands nowhere.
- **After:** a large hero part; a calm decision that reads process → monumental
  number → crossover, then a quiet action row (provenance · Recalibrate · Ask
  why); band + redesign note demoted to quiet/one-click; controls tucked; DFM a
  one-line severity strip. Part + number + scrubber are the three stars.

## Build proof

- `npx tsc --noEmit` → exit 0
- `npm run build` → exit 0 (all 18 pages generated)
- `npx eslint` on the three touched files → exit 0

**Touched files:**
`frontend/src/components/instrument/LivingInstrument.tsx`,
`frontend/src/components/instrument/DecisionReadout.tsx`,
`frontend/src/components/ui/cad-viewer.tsx`.
