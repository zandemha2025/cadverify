# CadVerify — Marketing rebuild to the locked Ramp/Mercury identity (build note)

**Role:** Principal Product Designer + Staff Frontend Engineer. **Date:** 2026-06-30.
**Source of truth:** `outputs/design/identity-ramp-mercury.md` (executed, not re-decided).
**Scope:** marketing only — `/` , `/method`, `components/marketing/*`, plus the identity tokens
in `globals.css` + font wiring. Product `(app)` screens were not redesigned; they inherit the new
tokens and still build.

---

## 1. What changed (files)

**Design system / tokens**
- `src/app/globals.css` — rewritten to the identity. Datum Blue accent (supersedes the steel-blue
  `#2563eb` everywhere), warm machinist-paper light mode, blueprint-twilight dark mode, the new type
  scale + size-linked tracking, tight radius (xs2/sm4/md6/lg10), the instrument-bezel + faceplate +
  blueprint-field + hatch utilities, gauge-needle motion tokens, and the two-number-voice classes.
- `src/app/layout.tsx` — wired **Archivo** via `next/font/google` **with the `wdth` axis**
  (`axes: ["wdth"]`) → real Archivo *Expanded*; kept Geist + Geist Mono. Updated `<html>` variable
  list and the page metadata.
- `src/components/ui/button.tsx` — primary hover now uses the per-mode `--color-primary-hover` token
  (so the bright dark-mode Datum CTA stays legible on hover; one-line change, app-wide safe).
- `src/components/ui/public-chrome.tsx` — wordmark now wears the display face (`.cv-wordmark`) with a
  2px Datum witness-tick; tagline → "should-cost, made of glass".

**Marketing-local (new / rebuilt)**
- `src/components/marketing/datum.tsx` *(new)* — the Datum-rail primitives: `Eyebrow` (witness-tick +
  mono index), `DimensionLine` (a real CAD dimension callout: extension ticks + arrowheads + label),
  `ProvDot` (on-dark provenance marks), and `useCountUp` (the one hero-number "settle", reduced-motion
  aware).
- `src/components/marketing/decision-plate.tsx` *(new)* — **signature 1**, reusable.
- `src/components/marketing/black-box-reveal.tsx` *(new)* — **signature 2**, reusable.
- `src/app/page.tsx` — rebuilt to the locked §1–§8 section flow.
- `src/app/method/page.tsx` — rebuilt to the identity (display headlines, drafting station numerals,
  the Decision Plate as stage 05).
- `src/components/marketing/glass-box-hero.tsx` *(deleted)* — replaced by the reveal.
- `src/components/marketing/data.ts` — unchanged; still the engine's real `report_to_dict`.

---

## 2. Tokens & fonts established

**Type — three voices.** `--font-display` = Archivo Expanded (next/font, `wdth` axis loaded); UI/body =
Geist; data numbers = Geist Mono (tabular). New monumental tokens: `--text-hero` (96/0.94),
`--text-headline` (56/60), `--text-display-l` (40/44); in-app `readout/display/display-xl/micro`
preserved so product surfaces are unaffected. Signature classes:
- `.cv-readout-hero` — the ANSWER: Archivo `wght 800 / wdth 122`, tabular, `-0.026em`, lh 0.9.
- `.cv-display` — headlines: Archivo `wght 740 / wdth 112`, `-0.02em`.
- `.num` / `.readout` — the EVIDENCE: Geist Mono, tabular.

**Color — Datum Blue, scarce.** Light primary `#0E66B3`, dark primary `#3FA3E8` (≈205° cyanotype, not
the ≈221° royal-indigo). Ring, brand mark, CTA, band-fill, focus, `MEASURED` provenance, and the
revealed x-ray all carry Datum; nothing else does. Foundation: light = warm limestone `#F7F5F1` /
obsidian `#14110D` / bone borders `#E4DFD6`; dark = blueprint near-black `#0B1220` / navy-tinted
surfaces `#111B2D`–`#18243A` / off-white `#EAEFF7`. Status kept warm + in its own lane (pass `#15784D`,
warn ochre `#A36A00`, fail `#B42318`, info muted slate). Provenance re-skinned to the identity:
MEASURED = Datum, SHOP = copper `#9A5B2A`, USER = violet `#6D5BD0`, DEFAULT = hollow slate.

**Space / depth / motion.** 8px grid; radius xs2/sm4/md6/lg10 (no pills). Flat-with-borders +
`.cv-bezel` (1px border + inner top highlight) and `.cv-faceplate` (graphite milled panel) instead of
stocky shadows. Motion = `--ease-instrument` `cubic-bezier(0.2,0,0,1)`, durations 120/180/240ms, and
`prefers-reduced-motion` fully honored (the settle + reveal both degrade to instant/cross-fade).

---

## 3. The three signature elements (built, and where)

1. **THE DECISION PLATE** — `decision-plate.tsx`. A machined graphite faceplate carrying, in one glance:
   the monumental `$14.14 /unit` (`.cv-readout-hero`, $ and /unit at ~40%, muted), the CAD dimension-line
   callout under it, the recommended make (`Make by MJF (PP)`) + lead time (`5.6–10.4 days`), the
   **hatched** confidence band `$8.49–$19.80` ("assumption-based, not yet validated"), the crossover line
   (`MJF wins ≤ 1,962 units · injection molding above — if redesigned`), and the provenance dot row
   (●MEASURED ●SHOP ○DEFAULT). The number does the one-time "settle" on load. **Used on:** the homepage
   hero (animated) and `/method` stage 05 (static). Driven by `data.ts`, never a typed fixture.

2. **BLACK-BOX → GLASS-BOX REVEAL** — `black-box-reveal.tsx`. An obsidian opaque incumbent card (bare
   `$14.14` over locked, blurred driver rows + "trust us") that **dissolves** (IntersectionObserver on
   scroll, or the "Trace the number" toggle) into its cyanotype x-ray: the real `DriverBreakdown` (Σ =
   unit cost) + `ConfidenceInterval` + provenance legend over a faint Datum blueprint grid. Reduced
   motion → clean cross-fade. **Used on:** homepage §2 ("The number, traced").

3. **THE DATUM RAIL** — `datum.tsx` + `globals.css`. (a) Every section eyebrow is prefixed by the 2px
   Datum witness-tick (`.cv-eyebrow::before`) with an optional mono drawing index. (b) The hero number
   wears one `DimensionLine` CAD callout (extension ticks + arrowheads). (c) A one-time cyanotype
   graph-paper texture + twilight gradient lives **only** in the dark hero field (`.cv-hero-field`),
   never repeated below — the closing CTA is flat dark (no grid).

**Supporting:** the make-vs-buy **crossover dial** (homepage §4, `CrossoverExplorer`) — a Radix slider on
a log quantity scale that live-flips the recommendation at ~1,962 units (make MJF → tool up IM, labeled
"if redesigned"), with per-route unit costs recomputing and the branded crossover chart's accent curve
moving with it.

---

## 4. Honesty held

Every number is the engine's real `report_to_dict` (`$14.14`; band `$8.49–$19.80` rendered verbatim as
"assumption-based, not yet validated"; `n=0` stated plainly; crossover `1,962`; routing rotational →
CNC turning conf 0.80; DFM `cnc_3axis` 423 faces / 59.6% undercut, `injection_molding` 1 sidewall < 1.0°
draft). The §7 proof band ships **no** vanity "parts analyzed" stat and **no** fabricated accuracy — only
four defensible structural facts (21 process families · 4 provenance marks · Σ reconciles · 0 faked
accuracy). The molding crossover is always "if redesigned," never a current quote.

---

## 5. Build proof

```
cd frontend
npx tsc --noEmit     # clean (exit 0)
npm run build        # ✓ Compiled successfully; TypeScript finished; 18/18 static pages
                     #   / → ○ (prerendered static) ; /method → ○ (prerendered static)
                     #   all product (app) routes still build (ƒ as before)
```
Runtime smoke (dev server): `GET /` and `GET /method` → **HTTP 200**; rendered HTML contains
`cv-hero-field`, `cv-faceplate`, `cv-readout-hero` (×8), `cv-display` (×15), "The decision plate",
`$14.14`, and the Archivo font variable on `<html>` (`archivo_…__variable`). No headless browser in this
environment, so no screenshot is claimed — the green `next build` + 200 render is the honest proof.

## 6. Acceptance self-check
- **Distinctive, not a template** — warm machinist-paper + cyanotype-Datum foundation, Archivo-Expanded
  number-as-hero in two deliberate voices, the Decision Plate + black-box→glass-box reveal + Datum rail.
  A designer reads the Ramp/Mercury DNA, not a shadcn/Stripe kit. ✓
- **3 signature elements real** — Decision Plate, the dissolve reveal, the Datum rail (all bound to real
  engine output, light + dark). ✓
- **Datum Blue, not generic blue** — `#0E66B3`/`#3FA3E8`; no `#2563eb`/`#3b82f6`/`#6366f1` in any token
  value or marketing file. ✓
- **Monumental Archivo numbers; builds green.** ✓
```
