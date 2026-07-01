# CadVerify — Design Critique & Validation Audit

**Role:** Design-Critique / Validation-Auditor (adversarial). I do not design. I read the built
surfaces and the engine, then ran every build/typecheck/CLI myself.
**Date:** 2026-06-29.
**Verdict: COMPLETE.** All four thesis checks PASS. The glass box is the hero (in the live product
*and* the marketing hero, rendered from the engine's real output, not a picture of it); each of the
five roles has a real landing view without drowning the others; the language is instrument-grade and
appropriately restrained for an aerospace/automotive buyer (not consumer-flashy); and marketing +
platform tell the *same* true story — no decimal-exact promise, **no fabricated validated-±X%**, every
number traced to the cost-truth engine. Both surfaces compile (`npm run build` exit 0, 16/16 pages).

This is **not** a reskin: the provenance fill/hollow + hatched-confidence + measurement-tick system is
a custom visual language bound to this subject's metrology world and to the glass-box thesis, wired
through real `@theme` tokens (light + dark) and dogfooded into the live workspace — not a templated
shadcn default.

The findings below are **non-blocking**: a few honesty/consistency nits to tighten, and — most
important for the validation gate — one **infra caveat** (a stale API process suppresses
routing/confidence/calibration on the *live* `/cost` route today), which the validation protocol is
written around so the hero isn't accidentally buried during a user test.

---

## Method (commands actually run)

- `npx tsc --noEmit` (frontend) → **exit 0**.
- `npm run build` (Next.js 16 + Turbopack) → **exit 0**, "Compiled successfully", "Finished
  TypeScript", **16/16** static pages incl. `○ /`, `○ /method`, `○ /cost`, `○ /analyze`,
  `○ /design-system`.
- Live engine CLI: `cd backend && .venv/bin/python -W ignore -m src.costing.cli
  ".venv/share/doc/gmsh/examples/api/object.stl" --qty 10,1000 --shop "Midwest Precision CNC"` →
  captured the real report and diffed every marketing/showcase number against it.
- Read the token layer (`globals.css` + the compiled `.next` CSS), the glass-box component library,
  `PartWorkspace` + the five lens views, both marketing pages, the role lens, and the shop profiles.
- Adversarial greps: fabricated-accuracy / decimal-exact strings; toy `cost_per_cm3` leak; part-name
  honesty; role coverage.

---

## CHECK 1 — Is the GLASS BOX the hero (drivers, confidence, editability visible)? — **PASS**

**What I tested:** whether "every cost driver/assumption visible + editable, confidence shown" is the
*UI*, not a footnote — in both surfaces, against real engine fields.

**Evidence:**
- **The atom is real and honest by construction.** `components/glass-box/provenance.tsx` renders a
  **filled dot when grounded** (`MEASURED`/`SHOP`/`USER`) and a **hollow ring for `DEFAULT`** — "where
  the model is guessing" is *visible*, with a distinct lineage palette (measured-blue `#1d4ed8`,
  calibration-teal `#0d9488`) kept separate from verdict hues. Confirmed in `globals.css`
  (`--cv-prov-measured`, `--cv-prov-shop`, both light + dark) and the compiled CSS.
- **Driver breakdown shows the arithmetic.** `driver-breakdown.tsx` lists each driver
  provenance-tagged + sourced, expands **inline** (`cv-reveal`, never a modal) to the engine's
  verbatim `source` string + an override affordance that re-tags `USER`, and **always** shows the
  `Σ line items = unit cost` coherence row (turns `fail`-red if Σ ≠ unit). No naked numbers.
- **Confidence is structural honesty.** `confidence.tsx` draws the band low·point·high; the fill is
  **diagonally hatched (`cv-hatch`) while `validated == false`** ("assumption-based, not yet
  validated") and only goes **solid** when `validated == true` ("validated on N of your parts"). It
  renders the engine's `label`/`basis`/`n_samples` **verbatim** and never prints a fabricated ±X%.
- **First-class tab + universal drill-down.** In the live product (`PartWorkspace.tsx`) the **Glass
  Box** is one of five tabs *and* "View glass box" drills any Decision number to its drivers — the box
  is both a destination and one click from everywhere.
- **It is the marketing hero.** `components/marketing/glass-box-hero.tsx` puts the incumbent's **locked
  black-box** card (the same `$14.14`, unreadable `Lock`'d rows — "trust us") beside the **real**
  `DriverBreakdown` + `ConfidenceInterval` for the identical `$14.14`. The wedge is the literal UI,
  rendered from `data.ts` (engine output), not a slogan.

**Why it's not buried:** the boldness is spent *only* on this honesty system (Chanel "remove one
accessory" rule); everything else stays quiet (slate, one accent, flat borders) so the provenance +
confidence reads as the brand.

**Fix (non-blocking):** none required. Tightening note carried to Check 4 (the live-API caveat is what
could *accidentally* bury it during a demo).

---

## CHECK 2 — Is each audience segment served by a real view, without drowning the others? — **PASS**

**What I tested:** that the five personas (design eng, cost/value eng, sourcing, mfg eng, buyer) each
get a real landing view set by one control, and that no role's density drowns another.

**Evidence:**
- **Five roles, real landings.** `role-lens.tsx` defines all five (`design`/`cost`/`sourcing`/`mfg`/
  `buyer`), each with a `lands` tab + default density + default disclosure. `PartWorkspace`'s
  `LANDS_TO_TAB` maps them: Design→Decision, Cost→Glass Box, Sourcing→Compare, Mfg→Routing & DFM,
  Buyer→Decision (+ "Why trust this" panel). Verified all five ids present in the workspace.
- **Walls nothing off.** Switching the lens re-lands you, but all five tabs stay one click away —
  correct for the multi-hat reality (an engineer wears several hats in one sitting).
- **Each view is genuinely different, not a density slider on one page:**
  - *Decision* (`CostDecisionView`) — answer-first: make-vs-buy headline, three readouts, the
    signature **quantity slider that live-flips the process at the crossover**, banded cost.
  - *Glass Box* (`GlassBoxView`) — every assumption inline-editable (override → `USER`), Σ=unit, CI.
  - *Routing & DFM* (`RoutingDfmView`) — foregrounds the engine's **reasoning paragraph** + a
    per-process DFM matrix with **two-way face↔blocker highlight** in the 3D rail.
  - *Compare* (`CompareView`) — process × shop × quantity board, banded cells, the negotiation lever.
  - *Share* — role-scoped handoff ("open as <recipient's lens>").
- **The opposing-needs problem is solved by IA, not averaging:** the airy decision and the compact
  open-model coexist as separate lenses over one report; nobody gets the "averaged-out middle".

**Minor finding (non-blocking):** the marketing landing section is titled **"One engine, four jobs"**
and shows **four** role cards (design / cost / sourcing / mfg) — the **Buyer** role (which the live
product *does* have, folded onto the Decision landing) is omitted there. Defensible (buyer ≈ design's
decision landing), but it's a small marketing↔platform inconsistency.
**Fix:** either add a 5th "Buyer — trust & approve" card and retitle "One engine, five jobs", or keep
four and add one line noting the buyer shares the design landing. Cosmetic.

---

## CHECK 3 — Is it 2026-appropriate for THIS buyer (clear/trustworthy, not flashy)? — **PASS**

**What I tested:** whether the language reads as instrument-grade trust (right for an aerospace /
automotive / ITAR-adjacent buyer) rather than consumer flash — and whether it's distinctive enough to
not be a templated default.

**Evidence:**
- **Restraint is the system.** One steel-blue accent (`#2563eb`, lifting to `#3b82f6` in dark),
  flat-with-borders (no glassmorphism/gradients), tabular **mono numbers** everywhere (numbers are the
  product), a single `text-readout` 40px hero metric. Motion is one purposeful inline expansion
  (`cv-reveal`, `--duration-fast 120ms`) and **`prefers-reduced-motion` collapses all of it**.
- **Distinctive, not a default.** The `.cv-eyebrow` measurement-tick (a 2px steel-blue CAD witness
  line via `::before`), the provenance fill/hollow dot, and the hatched confidence band are a custom
  metrology-grounded language — deliberately none of the three AI-design defaults
  (cream+serif+terracotta / near-black+acid / broadsheet hairlines). This is the opposite of a
  reskin: the signature *encodes truth* (grounded vs guess, validated vs not).
- **Light + dark, both wired (not static).** Compiled `.next` CSS shows `--cv-canvas:#f6f8fb` (light)
  and `#080c16` (dark), `bg-card{background-color:var(--cv-card)}`, and `cv-hatch` emitted — toggling
  `.dark` re-themes the whole app via tokens.
- **Trust signals are content, not chrome:** auditable provenance, "the arithmetic is shown",
  IP-stays-put / zero-egress, ITAR/AS9100 framed as *path* ("designed to run inside a controlled
  environment"), never a certification claim.

**Fix (non-blocking):** none. The one thing to watch in future iterations is keeping the dark "control
room" surfaces at AA contrast for the dense data tables; spot-checks pass, but it's worth a formal
contrast pass before GA.

---

## CHECK 4 — Do marketing + platform tell the SAME true story, and do both build? — **PASS**

**What I tested:** I diffed every marketing number against the live CLI, swept for decimal-exact and
fabricated-accuracy language, checked the toy model is gone, and built both surfaces.

**Evidence — every claim is the engine's real output (verified against the CLI this session):**

| Claim on the surfaces | Live engine (CLI) | Match |
|---|---|---|
| Unit cost `$14.14` (MJF/PP, qty 10) | `$14.14/unit` | ✓ |
| Line items `3.887 + 0.0417 + 3.8213 + 6.3935` **sum to unit** | `Σ = $14.14` | ✓ |
| Confidence `$8.49–$19.80` (±40%), "assumption-based, not yet validated" | `$8.49–$19.80/unit (±40%) [assumption-based, not yet validated…]` | ✓ |
| Routing → `cnc_turning`, archetype rotational, conf `0.80`, reasoning paragraph | identical string | ✓ |
| Make-vs-buy crossover ≈ `1,962`; tooling = injection_molding "if redesigned" | `crossover ~1962 … the tooling cost shown is 'if redesigned for molding', not a current-capability quote` | ✓ |
| DFM: `cnc_3axis` 423 faces (59.6%) undercut; `injection_molding` 1 sidewall < 1.0° draft | identical | ✓ |
| Per-shop calibration: Midwest labor `$52/hr` vs Shenzhen `$14/hr`, rates tagged `SHOP` | `midwest-precision-cnc.json` 52.0 / `shenzhen-contract-mfg.json` 14.0 | ✓ |

**Honesty constraints held:**
- **No decimal-exact promise** — the page *attacks* fake-exactness ("The answer is a choice, not a
  fake-exact price"); cost is always banded.
- **No fabricated validated-±X%** — adversarial grep for `validated within / ±N% across / measured
  error of / N% validated` on the marketing surfaces returns **nothing**. The only "±5% accurate"
  string is the honesty section *rejecting* it ("Anyone can print '±5% accurate' on a slide. We
  don't"). Confidence renders the engine's `validated`/`label` **verbatim**; "validated on your parts"
  is framed as the future state that flips the band solid on the user's held-out residuals.
- **Toy model gone** — the only `cost_per_cm3` string in the whole frontend is a comment in
  `design-system/fixture.ts` stating it is **not** used.
- **Marketing doesn't touch platform** — marketing imports the glass-box library and public chrome
  read-only; its numbers live in `components/marketing/data.ts` (mirrors the platform showcase
  fixture, identical values).

**Builds:** both surfaces compile in one `next build` (exit 0, 16/16 pages, `/`, `/method`, `/cost`,
`/analyze`, `/design-system` all prerendered). The "transient red" concurrency caveat the marketing
log warned about is **resolved** — the tree builds green at the current checkpoint.

**Minor finding (non-blocking, honesty hygiene):** `data.ts` defines `PART.name = "bracket_v3.stl"`,
but the underlying numbers are the engine's output for the gmsh demo `object.stl`. **This name is dead
data** — it is never rendered on any marketing surface (only `PART.process`/`PART.qty` are shown; the
hero caption honestly reads "object analyzed by the cost-truth engine"). So no user ever sees a
mislabeled part. Still, an unused fictional filename sitting next to real costs is a foot-gun.
**Fix:** delete the unused `name` field (or rename the demo part file) so a future edit can't surface
"bracket_v3.stl" over object.stl's numbers.

---

## The one finding that matters for the validation gate — the live-API caveat (infra, not design)

This is **not** a thesis/reality failure (the design is correct and degrades honestly), but it is the
single most important thing for whoever runs the user sessions:

> **On the *live* `/cost` and `/analyze` routes today, the running API process is stale** — it imported
> the engine before `routing`, per-estimate `confidence`, and per-shop `calibration` were added to
> `report_to_dict`. So a real upload through the live API returns drivers + decision + DFM, but the
> `RoutingCard`, `ConfidenceInterval`, and a calibrated `CalibrationBar` are **suppressed** (the
> frontend shows an honest build-gap note and "Not calibrated — generic defaults").

The design handles this gracefully and labels the gap — but it means **if you sit a buyer in front of
the live upload flow today, the glass-box hero shows a weaker version than the thesis promises**
(no routing reasoning, no confidence band, no SHOP tags). The hero would be accidentally half-buried
by an infra gap, not a design gap.

**Consequence for the protocol (handled in `design-validation-protocol.md`):** drive user tests off
the **fixture-backed full experience** (the `/design-system` showcase + the `/` and `/method` marketing
pages, which render the complete engine output incl. routing/confidence/calibration), **and/or** have
the build harness restart the API so the live `/cost` serves the new fields before the session. Don't
let stale infra be the thing the Head of Manufacturing judges the glass box on.

**Owned by the build harness** (the design correctly designs *for* these; they are not design defects):
1. Surface `routing` + per-estimate `confidence` through `/api/v1/validate/cost` (restart the server).
2. Add a `shop` param to the cost API so calibration lights up the `CalibrationBar` end-to-end.
3. Multi-shop-in-one-call for a true Midwest-vs-Shenzhen A/B in `Compare`.
4. Server re-cost on driver/assumption override (today the override re-tags `USER` client-side + toasts
   the gap).
5. Persisted, versioned scenarios + a role-scoped shareable analysis object.

---

## Reskin / template check — **CLEAR**

Adversarially looked for "templated default" tells: there are none. The token layer is a bespoke
instrument-grade system (custom provenance lineage palette, hatched-confidence, measurement-tick
eyebrow), the components render **real engine fields** (not lorem/placeholder), the prior cohesion
audit confirmed ten visual languages collapsed into one (`lib/status.ts` single source, one accent,
one radius, one shell), and the signature elements *encode truth* rather than decorate. This is a
thesis-driven elevation of the existing Next/shadcn/Radix base, not a reskin.

---

## Scorecard

| Check | Verdict | One-line |
|---|---|---|
| 1 · Glass box is the hero | **PASS** | Provenance fill/hollow + hatched-CI + Σ=unit, first-class tab + universal drill-down, and the literal marketing hero — rendered from real engine output. |
| 2 · Each segment served, none drowned | **PASS** | Five real lenses set by one Role Lens; nothing walled off. (Minor: marketing says "four jobs", omits Buyer card.) |
| 3 · 2026-appropriate, not flashy | **PASS** | Slate instrument-grade, one accent, mono numbers, one motion, reduced-motion honored; distinctive metrology language, light+dark wired. |
| 4 · Marketing == platform, both build | **PASS** | Every number diffed to the live CLI; no decimal-exact, no fabricated ±X%; toy model gone; `next build` exit 0, 16/16. |

**DECISION: COMPLETE.** No glass-box burial, no unserved segment, no inappropriate flash, no
marketing/platform divergence, no fabricated accuracy, no reskin, no failing build. Ship to the
validation gate — running the protocol in the companion doc, with the live-API caveat handled.
</content>
</invoke>
