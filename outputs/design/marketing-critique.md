# Marketing Site — Brutal Design-Director Critique

**Role:** Adversarial design director. **Date:** 2026-06-30.
**Verdict: COMPLETE.** I went in assuming generic; it is not. The Ramp/Mercury
DNA is actually present, the three signatures are built (not stubbed), the
banned steel-blue is gone, and both `npm run build` and `npx tsc --noEmit` are
green with the product pages intact. Nits below, none rising to a rejection.

Files audited: `frontend/src/app/page.tsx`, `frontend/src/app/method/page.tsx`,
`frontend/src/app/globals.css`, `frontend/src/app/layout.tsx`,
`frontend/src/components/marketing/{decision-plate,black-box-reveal,datum,data}.tsx`,
plus the shared `frontend/src/components/glass-box/*` and
`frontend/src/components/cost/BreakevenChart.tsx` the marketing pages consume.

---

## Check 1 — DISTINCTIVE vs GENERIC — PASS

A designer would read the Ramp/Mercury lineage, not a template. The tells of the
direction are all load-bearing, not decoration:

- **Number-as-hero in two deliberate voices.** The ANSWER is `.cv-readout-hero`
  (`globals.css:289` — Archivo Expanded, `"wght" 800, "wdth" 122`, `-0.026em`,
  `line-height: 0.9`) rendered at 96px in the Decision Plate
  (`decision-plate.tsx:80`). The EVIDENCE is `.num` (Geist Mono, `tnum`,
  `globals.css:263`). These never blur — the plate sets `$14.14` monumental and
  every driver line in mono. This split is the identity's signature and it is
  executed literally.
- **Warm-paper + cyanotype + obsidian**, not cool-gray + royal-blue. Light
  canvas `#f7f5f1` warm limestone, ink `#14110d` warm obsidian, warm-bone
  borders `#e4dfd6` (`globals.css:172-204`). That warm/cool tension against
  Datum is the anti-template pairing the brief demanded.
- **Blueprint-twilight dark hero** tinted toward navy (`#0b1220`), with a
  one-time cyanotype graph-paper field (`.cv-hero-field::before/::after`,
  `globals.css:349-382`) masked to the corner — used once, never repeated (the
  §8 closing CTA is a flat `#0b1220` with no texture, correctly NOT echoing the
  atmosphere).
- **Instrument bezel instead of stock shadows** (`.cv-bezel` /
  `.cv-faceplate`, `globals.css:327-344`): 1px border + inner top highlight so
  panels read as milled metal. Only two real shadows defined.

This is a point of view, not shadcn-at-default.

## Check 2 — ON-IDENTITY TOKENS — PASS

- **Datum Blue is the accent and steel-blue is gone.** `--color-primary-600:
  #0e66b3` / `--color-primary-400: #3fa3e8` (`globals.css:55-57`), wired through
  `--cv-primary`, `--cv-ring`, and MEASURED provenance. Grep of `src/` for
  `#2563eb|#3b82f6|#6366f1|#1d4ed8|#4f46e5`: the **only** hit is the cautionary
  comment at `globals.css:48` ("if it ever drifts toward #2563eb… it has
  failed"). No `bg/text/border-blue-*` or `indigo/sky/cyan-*` Tailwind tokens
  anywhere. No `slate-*` or "steel" in the marketing files.
- **Archivo Expanded drives headlines.** Loaded WITH the width axis in
  `layout.tsx:19-24` (`axes: ["wdth"]`); `.cv-display` requests `"wdth" 112` and
  the hero readout `"wdth" 122` — genuine Expanded width, not a faux-bold neutral
  sans. This is the one substitution that separates on-identity from template,
  and it's wired correctly end-to-end.
- **Geist Mono for numbers** via `.num`/`.readout`; **Geist** for body. All three
  font vars resolve through next/font.
- **Light + dark both real.** Full `:root` and `.dark` token sets
  (`globals.css:172-249`); no-flash theme script in `layout.tsx:45-50`.
- **Accent stays scarce and out of the status lane.** Status is its own warm
  ramp — pass green `#15784d`, warn ochre `#a36a00`, fail crimson `#b42318`
  (`globals.css:192-194`) — never the accent. The "if redesigned" warning in the
  crossover uses `warn`, not Datum (`page.tsx:447`).

## Check 3 — SIGNATURE ELEMENTS — PASS (all three built, real data)

1. **The Decision Plate** (`decision-plate.tsx`): a graphite faceplate carrying
   the monumental `$14.14/unit` (Archivo Expanded 96px), recommended make + lead
   time sub-figures, a **hatched** confidence band with a point marker and the
   verbatim "assumption-based, not yet validated" label, the crossover line
   (`≤ 1,962 … if redesigned`), and a provenance-dot row. Model is mapped from
   the real `ESTIMATE`/`BREAKEVEN` (`data.ts`), not typed inline. Reused on the
   hero (`page.tsx:104`) and method stage 05 (`method/page.tsx:131`) — one
   component, as specified.
2. **Black-box → Glass-box reveal** (`black-box-reveal.tsx`): a genuine
   transformation, not a side-by-side. The obsidian casing (`.cv-obsidian`)
   dissolves via a `clipPath inset(0 0 100% 0)` wipe + opacity (`:104-115`),
   auto-triggered by an IntersectionObserver (`:41-58`) with a manual "Trace the
   number" toggle, exposing the **real** `DriverBreakdown` + `ConfidenceInterval`
   over a cyanotype grid. Σ-of-the-stack is stated. Reduced motion is honored by
   the global override.
3. **The Datum rail** (`datum.tsx` + globals): the witness-tick eyebrow
   (`.cv-eyebrow::before`, a 2px Datum tick), a real CAD `DimensionLine` SVG
   (extension ticks + arrowheads + value) used once under the hero number, and
   the dark-hero-only graph-paper texture. A whisper, not a costume blueprint
   skin — exactly the discipline the brief asked for.

Supporting: the make-vs-buy crossover is a **live dial** (`CrossoverExplorer`,
`page.tsx:424`) whose verdict header flips at ~1,962, feeding a re-skinned chart
(`BreakevenChart.tsx`: recommended curve in `var(--cv-primary)` at 2.5px, others
muted graphite, dashed crossover `ReferenceLine` with the qty called out) — a
branded chart, not a default chart-library look.

## Check 4 — AVOID-LIST — PASS

- Generic SaaS blue: gone (Check 2).
- Featherweight/centered type: headlines are Archivo Expanded **740–800**, the
  hero is **left-aligned** with the Decision Plate as the focal artifact (not a
  centered big-number + pastel-gradient template hero). Only the closing CTA and
  method intro center, which is appropriate for a close.
- Stock/mesh/glow gradients & glassmorphism: the single hero gradient is the
  permitted one-time blueprint-twilight field; no neon streamers, no blur-glass
  cards.
- Naked numbers: the hero number wears a dimension line + provenance dots;
  driver numbers carry provenance; even the §7 stat cells are captioned with
  their basis. No figure ships bare.
- Accent-as-status: held apart (Check 2).
- Real engine numbers / no fabricated accuracy: `data.ts` is captured engine
  output (`unit 14.14`, band `8.49–19.80`, `n_samples: 0`, `validated: false`,
  crossover `1962`). The honesty section and the "0 — faked accuracy" stat make
  the `n=0` SMOKE corpus the pitch rather than hiding it.

## Check 5 — BUILDS — PASS

- `npx tsc --noEmit` → exit **0**, no output.
- `npm run build` → exit **0**: "Compiled successfully", 18/18 static pages,
  `/` and `/method` both prerendered as static (`○`). Every product route
  (`/analyze`, `/cost`, `/design-system`, `/batch`, `/history`, …) still builds —
  the new tokens are inherited, nothing broken. (The stale concurrency caveat in
  `marketing.md §4` no longer applies: the current `page.tsx` does not embed
  `PartWorkspace`.)

---

## Nits (logged, not blocking)

- **Stale companion doc.** `outputs/design/marketing.md §5` still claims the page
  uses "slate + steel-blue" and embeds `PartWorkspace`. The *code* is correct
  and on-identity; the doc is out of date and should be refreshed so a future
  reader isn't misled.
- **`cv-settle` uses a 6px blur-in** (`globals.css:419`). It's one-time, 520ms,
  and reduced-motion kills it, but a blur entrance is a faint Linear-ish tell in
  a brief that otherwise specifies opacity/height-only motion. Consider dropping
  the blur for a pure fade+translate to stay strictly in-character.
- **Hand-tuned hex on the dark surfaces.** The hero/CTA (`page.tsx`) and the
  faceplate (`decision-plate.tsx`) use many literal navy hexes (`#101e34`,
  `#274063`, `#7fa3c8`, …) instead of tokens. They're consistent with the
  blueprint-twilight palette and not off-identity, but they're a maintainability
  smell — a `--plate-*` token set would harden them.
- **One headline accent stretch.** The hero's "And why." is set in a light Datum
  tint (`#6fbcef`, `page.tsx:73`). Defensible as the thesis word, but it nudges
  the "accent is scarce" rule; keep an eye that this stays the page's single
  headline-color moment.

**Decision: COMPLETE.** Distinctive, on-identity, all three signatures real, no
template tell shipped, builds green, product pages intact.
