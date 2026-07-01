# CadVerify — Visual Identity: "Bold Industrial Confidence" (Ramp / Mercury DNA)

**Role:** Principal Brand + Product Designer. **Date:** 2026-06-29.
**Status:** Locked identity spec. This is the LANGUAGE the build team executes on top of the existing
Next.js 16 / Tailwind v4 / shadcn-on-Radix plumbing. It supersedes the steel-blue (`#2563eb`) accent in
`design-system.md` — that was generic SaaS blue, the exact thing this brief kills.
**Companion docs (substance this identity serves):** `design-direction.md` (north star), `design-system.md`
(component library + provenance/confidence atoms — KEEP, re-skin to the new accent), `marketing.md` (the real
engine numbers every page must use), `ia-and-flows.md` (surfaces).

> **One-line read of the look:** *A finance-grade instrument panel with machine-shop soul — disciplined warm
> neutrals, one cyanotype-blueprint accent, and the cost rendered as a confident headline number that always
> shows where it came from.* The enemy is generic "clean modern SaaS." Every choice below is concrete enough
> that a builder cannot default to a template.

---

## 0. What I actually studied (references cited)

I could not extract live CSS from `ramp.com` / `mercury.com` via fetch (both are JS-rendered; the fetch
returned marketing copy, not computed styles). I sourced the real systems from Fonts In Use, Typewolf, and
design-token aggregators (Refero / BrandColorCode / DesignMD), cross-checked against what's publicly known.
Specific observed moves I'm building on or deliberately diverging from:

**Ramp** — *the primary anchor (founder's choice).*
- Type: **TWK Lausanne** (custom neo-grotesque, WELTKERN®) sets *everything* from 64px hero to 13px caption
  with "quiet authority"; paired with **Burgess** (Colophon) serif for editorial moments. Custom wordmark
  cut from Lausanne. (Fonts In Use #38468.)
- Color: overwhelmingly neutral *warm* foundation — Obsidian text `#0c0a08`, Paper `#ffffff`, Limestone card
  `#f4f2f0`, Bone border `#d2cecb` (light) / Slate `#4d505d` (dark) — and **one** electric accent, "Lime
  Signal" **`#e4f222`**, reserved strictly for CTAs ("the only chromatic voice"). One dawn-sky gradient
  (`#0c0a08 → #5683d2 → #f4f2f0`) used *only* on the hero opener, never repeated. (Refero / BrandColorCode.)
- Signature: **the number as a confident headline**, set in the display sans at scale with tabular figures —
  not a terminal readout. A "financial command center rendered in dawn light."
- **What I take:** disciplined near-monochrome + exactly ONE electric accent + number-as-hero + one-time hero
  atmosphere. **What I refuse:** copying their lime (derivative) — my accent comes from *my* subject's world.

**Mercury** — *the dark-mode anchor.*
- Type: custom **Arcadia / ArcadiaDisplay** variable font; the **480 weight** is calibrated "authoritative
  without being heavy"; body line-height a generous **1.625**. (Typewolf; Refero.)
- Color: deep near-black **`#1e1e2a` / `#171721`**, glowing off-white **`#ededf3`**, a single violet-blue
  accent **`#5266eb`** used "like indicator lights on a console," Ghost Blue `#cdddff` for secondary. Art-
  directed photography, never stock. "A command center at twilight."
- **What I take:** the dark "command-center-at-twilight" canvas, variable-weight authority (~480 mid), generous
  leading. **What I refuse:** violet-blue (reads fintech) and any cinematic photography (our buyer trusts data,
  not mood).

**Stripe** — *craft discipline.* Söhne (`sohne-var`) at light 300/400 — "lightness as luxury"; **progressive
tracking** that tightens with size (`-1.4px @56px … -0.26px @26px … 0 @16px`); base `#061B31`, indigo `#533AFD`;
the signature flowing-gradient band in the upper third; 8px spacing, mostly 0 radius, **4px on buttons/inputs**.
(Fonts In Use #35338; DesignMD.) **What I take:** size-linked tracking, 4px control radius, restraint. **What I
refuse:** featherweight 300 as the only voice (our audience wants *weight* = authority) and the pastel gradient.

**Linear** — *craft discipline.* Inter + **Inter Display** + **Berkeley Mono**; true-black dark-first, desaturated-
blue brand, the purple gradient sphere; micro-motion, blurs, gradients. (FontOfWeb; linear.app/brand.) **What I
take:** Berkeley-Mono-grade technical numerals as a premium option, dark-first rigor. **What I refuse:** the
glow/blur/streamer hero — glassmorphism reduces trust for an aerospace buyer.

---

## 1. Positioning of the look (one line, for whom)

**For the engineer and the sourcing lead at a serious manufacturer (Zoox, Aramco) who trusts numbers and is
allergic to flash:** CadVerify should feel like *a calibrated instrument they'd find on the shop floor crossed
with the confidence of a Ramp dashboard* — the cost is the hero number, stated plainly and big; the evidence is
right behind it; nothing is decorated. Premium because it is **disciplined and honest**, not because it sparkles.

---

## 2. Typography

The personality is a **two-voice system** plus a monumental display moment — not an exotic font. The brand
speaks in a confident neo-grotesque; the *evidence* speaks in tabular mono. Ramp/Mercury both prove a single
characterful grotesque carries an entire identity; we do the same, free-first so the team ships today, with a
licensed upgrade that buys the last 10% of soul.

### 2.1 The faces (real, web-available, with fallbacks)

| Role | Free production default (ship today) | Licensed upgrade (the soul) | Fallback stack |
|---|---|---|---|
| **Display / headlines / the hero number** | **Archivo** (OFL, variable — use the **Expanded** width axis + 600–800 weight for monumental headlines) | **Söhne** (Klim) or **ABC Diatype / Neue Haas Grotesk Display** — the true Lausanne-class cut | `"Archivo","Söhne","Inter",system-ui,sans-serif` |
| **UI / body** | **Geist** (OFL — already in the stack) | keep Geist, or **Söhne** for one family across both | `"Geist","Inter",system-ui,sans-serif` |
| **Mono / all data numbers** | **Geist Mono** (OFL — in the stack) | **Berkeley Mono** (the instrument-grade numeral, Linear's pick) | `"Geist Mono","Berkeley Mono",ui-monospace,"SF Mono",monospace` |
| **Editorial accent — OPTIONAL, marketing pull-quotes only** | **Fraunces** *or* a mechanical slab like **Bricolage Grotesque** at one moment | a Burgess-class serif | used ≤ once per page; never in-app |

**Why Archivo, not Geist, for display:** Geist is a clean neutral UI sans (correct for body) but it is *quiet* —
on its own it reads like every Vercel/Linear clone. **Archivo Expanded** at 700–800 is wide, sturdy, signage-grade
— it gives the **monumental, dense, confident** headline Ramp gets from Lausanne and Mercury from ArcadiaDisplay,
which is exactly the "bold industrial confidence" the founder chose. This single substitution is the difference
between on-identity and template.

### 2.2 The type scale (px) — modular, with size-linked tracking (Stripe's move)

Tracking tightens as size grows; leading loosens as size shrinks. Numerals everywhere carry
`font-variant-numeric: tabular-nums`.

| Token | Size / line-height | Weight | Tracking | Use |
|---|---|---|---|---|
| `readout-hero` | **96 / 96** (marketing) · **72 / 72** (app) | Archivo Expanded 700, tabular | **-0.022em** | the ONE cost/decision number — the signature |
| `display-xl` | 56 / 60 | Archivo Expanded 700 | -0.02em | marketing hero headline |
| `display-l` | 40 / 46 | Archivo 700 | -0.015em | page / section opener |
| `display-m` | 28 / 36 | Archivo 600 | -0.01em | section title |
| `title` | 20 / 28 | Geist 600 | -0.005em | card / panel title |
| `body-l` | 18 / 29 (**1.6**, Mercury-loose) | Geist 400 | 0 | marketing prose |
| `body` | 16 / 24 | Geist 400 | 0 | app prose, default |
| `label` | 14 / 20 | Geist 500 | 0 | controls, table headers |
| `eyebrow` | 13 / 16 | Geist 600, **UPPERCASE** | **+0.10em** | the measurement-tick eyebrow |
| `micro` | 12 / 16 | Geist Mono 500 | +0.01em | provenance source strings |
| `num` | 14 / 20 (data) · 24 / 28 (sub-metric) | Geist Mono 500, tabular | 0 | every in-table / driver number |

### 2.3 The number-as-hero rule (the signature, made explicit)

There are **two number voices, and they never blur**:

1. **The answer speaks in the DISPLAY face.** The single hero figure — `$14.14/unit`, or the lead time, or the
   crossover quantity — is set in **Archivo Expanded `readout-hero`** at 72–96px, tabular, tight tracking. It
   reads as a *confident headline*, the Ramp move — authority, not a terminal dump. The `$` and `/unit` ride at
   ~40% of the figure size, baseline-aligned, in `muted` — so the digits dominate.
2. **The evidence speaks in MONO.** Every supporting number — driver line items, dimensions, rates, n_samples,
   Δ% — is **Geist Mono, tabular**, right-aligned in tables. Instrument precision; columns line up to the digit.

This split is itself ownable: *the decision is brand-voiced and big; the proof is instrument-voiced and exact.*
A builder who sets the hero number in mono (terminal look) or the table numbers in the sans (misaligned) has
broken the identity.

---

## 3. Color — disciplined foundation, ONE industrial accent

### 3.1 The accent (locked): **Datum Blue** — cyanotype / engineer's-marking blue

**Hex (light primary): `#0E66B3`. Dark primary (lifted): `#3FA3E8`.**

**Why this, and why it is NOT generic SaaS blue.** The brief is right to push off `#2563eb` — that royal/indigo
hue is the bootstrap default. I'm choosing instead the blue of the subject's own world: the **cyanotype** (the
literal blue of an engineering *blueprint*) and **engineer's marking blue** (the Prussian-blue compound a
machinist brushes onto metal to *verify* fit and flatness against a surface plate). It is the pigment of
**verification** — and the product is named CadVer**ify**. That story is unownable by a template.

Concretely it differs from SaaS blue by being a **cyan-leaning cerulean**, deeper and cooler:
`#0E66B3` sits at hue ≈ 205° (vs `#2563eb` at ≈ 221° royal/indigo). It reads "technical drawing," not "sign-up
button." **Builder rule: keep Datum cyan-leaning; if it ever drifts toward `#2563eb`/`#6366f1` royal-indigo, it
has failed.**

**Why cool, not a hot industrial orange.** Forge-orange is tempting and on-theme, but in a control room orange/red
= *alarm*, and this is a status-dense trust tool for aerospace where "flash reduces trust." The brand accent must
stay **out of the semantic warm zone** so pass/warn/fail stay legible. A calm cyanotype reads *authority and
verification*, not *caution*. That is the right register for the buyer.

```
Datum Blue ramp
  --datum-900  #082E50   ink / deepest (dark-mode structural fields, the blueprint hero ground)
  --datum-700  #0A4E8C   text-on-tint (light), deep emphasis
  --datum-600  #0E66B3   PRIMARY — CTAs, brand mark, the hero number's underline/marker (light)
  --datum-500  #1380D6   hover / interactive
  --datum-400  #3FA3E8   PRIMARY (dark), and the single "live" bright tint (active slider, focused datum)
  --datum-200  #BFDCF2   tint border (light)
  --datum-050  #E8F1FA   tint surface (light)
```

The accent is **scarce on purpose** (Ramp's "only chromatic voice"): it appears on the primary CTA, the brand
mark, focus rings, the hero number's datum marker, and the revealed glass-box "x-ray." Nowhere else carries it.

### 3.2 Neutral foundation — warm machinist paper (light) → blueprint twilight (dark)

Light mode borrows Ramp's **warm** paper/granite (a surface plate, not cold slate); dark mode borrows Mercury's
**twilight command center** but tinted toward Datum navy (not neutral gray) so the blueprint DNA carries through.

| Role | Light (machinist granite/paper) | Dark (blueprint twilight) |
|---|---|---|
| canvas (page) | `#F7F5F1` warm limestone | `#0B1220` blueprint near-black |
| surface / card | `#FFFFFF` | `#111B2D` |
| surface-raised / sunken panel | `#F1EDE6` | `#18243A` |
| hairline border | `#E4DFD6` warm bone | `#233149` |
| border-strong | `#CFC8BD` | `#33446122`→ use `#344461` |
| foreground (ink) | `#14110D` warm obsidian | `#EAEFF7` glowing off-white |
| muted text | `#5A554C` | `#9FB0C8` |
| subtle text | `#857E72` | `#6F8099` |

The warm-paper + cyanotype-blue + obsidian combination is itself the anti-template tell: SaaS reaches for cool
gray `#f8fafc` + royal blue. Warm neutral against cyan-blue is a deliberate, recognizable pairing.

### 3.3 Semantic status — refined, held in its own lane

Reserved strictly for **verdicts** (pass / advisory / required-fix). Never the brand accent; **always**
icon + label, never color alone (carry over the existing a11y law). Tuned to sit clearly apart from Datum.

| | Light | Dark | Surface (light / dark) |
|---|---|---|---|
| **pass** (instrument green) | `#15784D` | `#34D399` | `#E7F4ED` / `#0E2A1E` |
| **warn** (cool ochre — yellower & duller than any orange) | `#A36A00` | `#F0B429` | `#FBF1DD` / `#2A2310` |
| **fail** (deep serious crimson, not alarm-red) | `#B42318` | `#F87171` | `#FBEAE8` / `#2C1414` |
| **info** (muted slate — never competes with Datum) | `#475569` | `#94A3B8` | `#EEF1F5` / `#1A2436` |

### 3.4 Provenance lineage (the brand atom) — re-tuned to harmonize, kept distinct from verdicts

Small marks only (dots / chips / micro-labels) — **never large fills**, so the page color budget stays
"warm neutral + one accent + restrained status." **Fill = grounded in your reality; hollow = a guess.**

| Provenance | Hue (light → dark) | Mark | Meaning |
|---|---|---|---|
| `MEASURED` | **Datum Blue** `#0E66B3 → #3FA3E8` | ● filled | measured off your CAD geometry (ties to the blueprint accent) |
| `SHOP` | **shop copper** `#9A5B2A → #D08B4C` | ● filled | your shop's calibrated rate (warm = the human shop floor) |
| `USER` | override violet `#6D5BD0 → #A99BF0` | ● filled | you overrode it (violet appears *only* here) |
| `DEFAULT` | hollow slate `#8A93A3` | ○ **hollow ring** | generic guess — the visible gap, on purpose |

Confidence stays the existing **hatched-until-validated band** (low · point · high): diagonally hatched while
`method == "assumption-band"`, solid only when `validated == true`. We render `label` / `validated` / `n_samples`
**verbatim** and **never** print a fabricated ±X% accuracy. (See `design-system.md §1`; keep it, re-skin to Datum.)

---

## 4. Space · grid · depth (the premium finish)

- **8px base grid** (4px sub-step). Spacing scale: `4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96 · 128`.
- **Marketing grid:** 12-col, max-width **1240px**, gutter 24–32, **section padding 96–128 vertical** —
  breathing room like Mercury/Ramp. The hero may go full-bleed for the one-time atmosphere field.
- **App grid:** 8px, denser; content max ~1440 with a fixed left rail. **Density is a lens, not a default:**
  *airy around the decision* (the Decision Plate gets 48–64px of air), *compact around the data* (tables at
  32–40px row height, a density toggle on big tables). This tension is the brand's "instrument + breathing."
- **Radius (tight, not bubbly):** `--radius-xs 2px` (prov chips) · `--radius-sm 4px` (buttons/inputs — Stripe's
  exact move) · `--radius-md 6px` (cards) · `--radius-lg 10px` (marketing panels / the Decision Plate). Nothing
  rounder than 10px; no pills, no 16px bubbles.
- **Depth = flat-with-borders + an "instrument bezel," not drop shadows.** Hairline 1px borders do the structural
  work. Two shadows only: `--shadow-sm` (0 1px 2px rgba(20,17,13,.06) — raised cards) and `--shadow-pop`
  (0 8px 24px rgba(8,46,80,.16) — overlays/popovers). On dark, depth comes from **surface-step lightening +
  border**, not shadow. The **Decision Plate** gets a signature *bezel*: a 1px border + a 1px inner top
  highlight (`inset 0 1px 0 rgba(255,255,255,.5)` light / `inset 0 1px 0 rgba(255,255,255,.06)` dark) so it reads
  like a machined faceplate, not a CSS card.

---

## 5. Motion — precise, confident, restrained

- **Character:** a gauge needle settling, not a spring. Easing `--ease-instrument: cubic-bezier(0.2, 0, 0, 1)`
  (decisive entry, calm settle). Durations: `--dur-micro 120ms` · `--dur 180ms` · `--dur-panel 240ms`. **No
  bounce, no overshoot, no parallax, no scroll-jacking.**
- **Three earned motions, nothing more:**
  1. **The hero number settles.** On load the `readout-hero` figure does a short tabular roll to its final value
     (~360ms) then *locks* — like a caliper coming to rest. One time, hero only.
  2. **The crossover slider live-flips.** Dragging quantity reflows the make-vs-buy curve and flips the
     recommended process in `--dur-micro` — crisp, instant-feeling.
  3. **Glass-box reveal / inline drill-down.** The black-box→glass-box dissolve and the existing `.cv-reveal`
     row expansion run at `--dur-panel`, opacity + height only.
- **Reduced motion (`prefers-reduced-motion: reduce`):** the number appears at final value (no roll), the
  crossover updates instantly, reveals cut to a cross-fade. Fully honored — non-negotiable for this audience.

---

## 6. Signature elements (the memorable, non-generic moments)

Boldness is spent here; everything else stays quiet. Each is built from **real engine output**
(`report_to_dict` → `frontend/src/components/marketing/data.ts` and the showcase
`frontend/src/app/(app)/design-system/fixture.ts`) — never a hand-typed fixture.

**(1) The Decision Plate — the cost rendered as a designed, finance-grade artifact.**
The Ramp "number-as-hero" move, made true to *this* product. A single machined-faceplate panel (bezel from §4):
- the **monumental hero number** `$14.14` `/unit` in Archivo Expanded `readout-hero`,
- the recommended process + lead time as confident sub-figures (`Make: CNC turning · 5.6–10.4 days`),
- the **confidence band** drawn beneath as a measurement-bar (`$8.49–$19.80`, hatched = "assumption-based, not
  yet validated" — verbatim, no fake %),
- the **crossover line** ("CNC wins ≤ 1,962 units · injection molding above — *if redesigned*"),
- a row of **provenance dots** proving the figure is grounded.
This one object carries cost + provenance + confidence + crossover in a single glance. It is the marketing hero
artifact *and* the in-app decision header — same component, real data.

**(2) Black-box → Glass-box — the wedge as a literal reveal.**
Reimagine the existing black-box/glass-box hero (`glass-box-hero.tsx`) as a **transformation**, not a side-by-side.
Start with a solid **obsidian "black box"**: the incumbent experience — a bare `$14.14/unit` over *locked,
unreadable* driver rows ("trust us"). On scroll/interaction the opaque casing **dissolves into a cyanotype x-ray**
of its interior: the identical `$14.14` explodes into its provenance-tagged driver stack
(`amortized_fixed 3.89 + material 0.04 + machine 3.82 + labor 6.39`, MEASURED/SHOP/USER/DEFAULT dots, **Σ = unit
cost** visible) over a faint blueprint grid. You literally watch the black box become a glass box. The Datum-blue
"blueprint" treatment appears only on the revealed interior — the one-time atmosphere, Ramp-style.

**(3) The Datum rail — metrology motif, used with discipline.**
Engineering soul without a costume blueprint skin (which would read flashy and *reduce* trust):
- Section eyebrows are prefixed by a **2px Datum-blue witness/dimension tick** (the existing `.cv-eyebrow`).
- The hero number (or a part thumbnail) wears a thin **CAD dimension-line frame** — extension lines + small
  arrowheads, a real engineering callout — used **once** per page.
- A faint **cyanotype graph-paper texture** is permitted **only** in the dark hero field, never on interior
  sections (Ramp's "gradient sky used once, never repeated" rule).

**Supporting signatures (recurring, quieter):** the **provenance ledger** (fill=grounded / hollow=guess; numbers
are never naked) and the **make-vs-buy crossover chart with the live quantity slider** — drawn as a *branded*
chart (graphite process curves, a Datum datum-line at the crossover with the quantity called out), not a default
chart-library look. The slider flipping the recommendation live is the thing no competitor nails — make it feel
like turning a dial.

---

## 7. The marketing homepage (concrete enough to build)

Route `/` (`frontend/src/app/page.tsx`), static/prerendered, consuming the shared design system read-only and the
**real** `report_to_dict` numbers from `components/marketing/data.ts`. Persuasion spine: prove the glass-box wedge
with live engine output at every step. **No fake fixtures, no stock factory photos, no isometric SaaS blobs.**

```
┌──────────────────────────────────────────────────────────────────────┐
│  HERO  — dark "blueprint twilight" field, one-time graph-paper texture │
│  ┌───────────────────────────────┬──────────────────────────────────┐ │
│  │ ▍KNOW THE COST. AND WHY.       │   ░░ THE DECISION PLATE (live) ░░ │ │
│  │  (display-xl, Archivo Exp.)    │   $14.14 /unit                    │ │
│  │  Glass-box, per-shop-calibrated│   Make: CNC turning · 5.6–10.4 d  │ │
│  │  should-cost for real parts.   │   ▟ band $8.49–$19.80 (unvalid.) │ │
│  │  [ Analyze a part ]  Datum CTA │   ● MEASURED ● SHOP ○ DEFAULT     │ │
│  │  ─ trusted by mfg/aero teams ─ │   crossover ≤ 1,962 → mold above │ │
│  └───────────────────────────────┴──────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

- **§1 Hero** — left: an Archivo-Expanded headline (*"Know what the part should cost. And why."*), one-line
  subhead, the single Datum CTA, a discreet trust row (mfg/aero logos at ~40% opacity). Right: the **Decision
  Plate**, live, from a real part. The hero IS a working decision, not a screenshot. Dark field, one-time
  cyanotype texture + a single dawn/twilight gradient (`#082E50 → #0B1220`), never repeated below.
- **§2 The wedge** — the **Black-box → Glass-box** reveal (signature 2). Eyebrow `▍THE NUMBER, TRACED`. Real
  `drivers[]`, Σ = unit cost shown.
- **§3 Per-shop calibration** — the SAME part costed `DEFAULT` vs **calibrated shop**: Midwest labor `$52/hr`
  vs Shenzhen `$14/hr` (SHOP provenance), numbers visibly shifting, a "Calibrated to <shop>" bar. Proves
  *traceable + calibrated*, the wedge no marketplace has.
- **§4 Make-vs-buy crossover** — the interactive chart + quantity slider; drag to watch CNC → injection molding
  flip at ≈ 1,962 units (labeled *"if redesigned"*, never a current quote). Eyebrow `▍WHERE THE DECISION CHANGES`.
- **§5 Honest by construction** — the hatched confidence band, `n_samples`, the rule *"we never print an accuracy
  we haven't earned on your parts."* The trust section for aerospace. (Reinforced by reality: the current corpus
  is SMOKE/`n=0` human labels per `c4-accuracy.md` — so the site **must not** print any accuracy %; this section
  turns that honesty into the pitch.)
- **§6 Process routing + DFM** — the routing reasoning (rotational → CNC turning, conf 0.80) and the actionable,
  *named* DFM matrix (`cnc_3axis` fails: 423 faces / 59.6% undercut; `injection_molding`: 1 sidewall < 1.0°
  draft). Real `routing.*` + `engine_feasibility[]` + `dfm_blockers`.
- **§7 Proof band** — a Ramp-style stat row, but **earned**: only real corpus metrics (parts analyzed, process
  families covered), set in Archivo Expanded, tabular, each captioned with its provenance. **No invented stat.**
- **§8 CTA** — dark, confident, single Datum CTA, eyebrow tick. Close on authority, not hype.

Density rhythm: airy hero (§1, §8) → dense proof (§2–§6 carry real tables/charts) → airy close. The page breathes
around decisions and tightens around data — the brand tension, top to bottom.

---

## 8. Avoid list (the generic-template tells — never ship these)

- **Default shadcn-at-default look:** the out-of-the-box `#2563eb`/`#6366f1` primary, equal-weight neutral gray,
  `shadow-sm` on every card, default Inter everywhere. We re-skin shadcn — we never ship its defaults.
- **Generic SaaS royal/indigo blue** (`#2563eb`, `#3b82f6`, `#6366f1`). And don't let **Datum** drift toward it —
  keep it cyan-leaning cerulean (≈205°). If it looks like a sign-up button, it's wrong.
- **Cold pure-gray neutrals** (`#f8fafc` / slate canvases) in light mode. Use warm machinist paper.
- **The template hero:** a centered big number + tiny label + pastel gradient + three equal stat columns. Our
  number-as-hero is the *Decision Plate* — left-aligned, real data, with provenance and crossover, or it's a cliché.
- **Glow/blur/mesh-gradient/glassmorphism** Linear-clone hero, neon streamers, pastel Stripe-gradient blobs.
- **Featherweight-everything** (Stripe's 300 as the only voice). Use *weight* for authority — our audience reads
  confidence as bold, not thin.
- **Flat equal-weight layouts** with no focal point. Spend boldness on the Decision Plate; keep the rest quiet.
- **Bouncy/springy motion, parallax, scroll-jacking, count-up on every number.** One settle, one flip, one reveal.
- **Fake numbers, lorem stats, stock factory photography, isometric 3D SaaS illustration, emoji icons.**
- **Naked numbers** — every figure carries provenance + confidence. A number without a source is a template tell.
- **Rainbow status / the brand accent used as a status color.** Pass/warn/fail stay in their lane; Datum never
  signals state.
- **Pills and 16px+ bubble radii.** Nothing rounder than 10px.
- **A literal blueprint costume** (full grid-paper skin, drafting-table photo). The Datum rail is a *whisper* —
  one tick, one dimension-frame, one textured hero. More than that reads as flashy and loses the aerospace buyer.

---

## 9. Acceptance self-check

- **Distinctive, not a template:** warm-paper-+-cyanotype-Datum foundation, Archivo-Expanded number-as-hero in
  two deliberate voices, the Decision Plate + black-box→glass-box reveal + Datum metrology rail — none of this is
  a shadcn/Linear/Stripe default. A designer would read the Ramp/Mercury DNA (disciplined mono foundation, one
  electric accent, number-as-hero, twilight dark mode) and *not* mistake it for a kit. ✓
- **Serves the substance, doesn't decorate it:** the signatures *are* the cost decision, the provenance, the
  crossover, the confidence — bound to real `report_to_dict` fields. ✓
- **Right for the trust audience:** cool verification accent (not alarm-orange), status legible in its own lane,
  no glassmorphism/photography flash, honesty-by-construction front and center. ✓
- **Every choice concrete:** real fonts (Archivo / Geist / Geist Mono, + licensed upgrades), real hex (Datum
  `#0E66B3`, warm neutrals, semantics), a real px scale with size-linked tracking, real spacing/radius/shadow/
  motion tokens. A builder cannot default to generic from this. ✓
```
