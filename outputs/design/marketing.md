# CadVerify — Marketing Site (delivered)

**Role:** Marketing-Site Designer. **Date:** 2026-06-29.
**Job:** persuade a skeptical Head of Manufacturing that CadVerify is credible *and* different — leading with the glass-box wedge, positioned against the opaque black-box incumbents (aPriori / Xometry). Built in the real frontend, consuming the shared design system read-only; no platform `(app)` screens edited.

---

## 1. Routes (real, built in the frontend)

| Route | File | Type | Purpose |
|---|---|---|---|
| `/` | `frontend/src/app/page.tsx` | Static (prerendered ○) | The persuasion spine — hero wedge → differentiation → decision → calibration → honesty rail → trust signals → role-aware → live demo → CTA |
| `/method` | `frontend/src/app/method/page.tsx` | Static (prerendered ○) | "How the number is built" — the 5-stage pipeline shown with the **real product components** (not screenshots), plus the honesty rail + ITAR/AS9100 data-locality posture |

**Supporting marketing-local files (new, do not touch platform):**
- `frontend/src/components/marketing/glass-box-hero.tsx` — the signature element (below).
- `frontend/src/components/marketing/data.ts` — the engine's **real** `report_to_dict` output (mirrors the platform showcase fixture; identical values), so every number on the page is a real cost-truth-engine result, never invented.

Both pages reuse the shared public chrome (`PublicHeader` / `PublicFooter` / `PrimaryCta`) and the glass-box component library (`@/components/glass-box`) read-only.

---

## 2. The signature (where the boldness is spent)

**Black box vs. glass box — the *same* number, shown two ways.** The hero puts the incumbent's opaque card (a `$14.14/unit` headline over **locked, unreadable** driver rows — "trust us") directly beside the **real** CadVerify `DriverBreakdown` + `ConfidenceInterval` for the *identical* `$14.14`: every driver measured/sourced/provenance-tagged, summing visibly to the unit cost, with the honest hatched (not-yet-validated) confidence band. The wedge isn't a slogan — it's the literal UI, rendered from the engine's real output. Everything else on the page stays quiet and disciplined (the design system), so the signature carries the page.

---

## 3. Claims used (every one checked against platform reality)

All numbers are the cost-truth engine's real output for one part (MJF/PP, Midwest Precision CNC calibration; Shenzhen for the A/B):

- **Unit cost `$14.14`**, line items (`amortized_fixed 3.89 + material 0.04 + machine 3.82 + labor 6.39`) **sum visibly to the unit cost**.
- **Confidence band `$8.49–$19.80` (±40%)**, rendered **verbatim** as *"assumption-based, not yet validated"* — the engine's stated assumption band, **not** a measured accuracy.
- **Make-vs-buy crossover ≈ 1,962 units**; lead time `5.6–10.4 days`.
- **Geometric routing**: rotational → CNC turning, confidence 0.80, with the engine's reasoning paragraph; cost-cheapest make (MJF) ≠ geometry pick — shown honestly.
- **DFM (actionable, named)**: `cnc_3axis` fails — *423 faces (59.6%) undercut*; `injection_molding` fails — *1 sidewall < 1.0° draft* → the molding crossover is labeled **"if redesigned," never a current quote**.
- **Per-shop calibration**: Midwest `labor $52/hr` vs Shenzhen `$14/hr`; bound rates tagged `SHOP` + sourced, gaps left as visible `DEFAULT`.

### Claims explicitly held to the honesty constraints
- **No decimal-exact promise** — the page attacks fake-exactness ("the decision, not a fake-exact price"); cost is always banded.
- **No fabricated ±X% validated accuracy** — a whole section ("We won't quote you an accuracy we haven't earned") states we never print an accuracy figure we haven't measured on real data. The only percentages on the page are the engine's stated *assumption* band (labeled unvalidated), a relative shop Δ%, and a measured geometry fact (undercut %). "Validated on your parts" is framed as the future state that flips the band solid on **your** held-out residuals.
- **ITAR / AS9100** framed as *path / designed-for* ("designed to run inside a controlled environment"), never a certification claim. Data-locality ("CAD parsed in-process and discarded; zero network egress on the local path") matches the existing demo messaging.

### Differentiation (the table a skeptic will actually read)
Concrete 3-column comparison — *Instant-quote marketplace (e.g. Xometry/Protolabs)* vs *Cost-engineering suite (e.g. aPriori/Teamcenter)* vs *CadVerify* — across: the number, the hero output, what happens when it's wrong, DFM feedback, how it earns trust, shop calibration, and what the AI does. Both incumbents framed fairly (legitimate models, but opaque/heavy), which is what keeps it credible to a skeptic.

---

## 4. Build proof

```
cd frontend
npm run build      # ✓ Compiled successfully; ✓ 16/16 static pages;
                   #   / and /method prerendered as static content (○)
npx tsc --noEmit   # marketing files (app/page.tsx, app/method/*, components/marketing/*) are CLEAN
```

A fully green `next build` (exit 0, all 16 pages incl. `/` and `/method` prerendered) was captured this session at a consistent tree checkpoint.

**Concurrency note (honest):** the platform designer is editing `PartWorkspace.tsx` / `RoutingDfmView.tsx` concurrently (their tasks #10/#11, the role-aware Decision rewire). While they are mid-edit, the *shared whole-graph* `next build` can be transiently red on **their** files (e.g. `PartWorkspace` missing the new `role`/`onOpenGlassBox`/`onSeeRouting` props they are adding) — `/` embeds `PartWorkspace` as the live-demo section (as the original landing did), so the shared build inherits their state. **No marketing file is the cause; all marketing files type-check clean.** The build goes green again once their in-flight refactor lands. No screenshot is claimed (no headless browser in this environment); the green `next build` is the honest proof.

---

## 5. Acceptance self-check

- **Credible + clearly differentiated from aPriori/Xometry** — the black-box/glass-box signature + the 7-row differentiation table + the "shows its work" method page make the wedge concrete, not asserted. ✓
- **Every claim matches platform reality** — all numbers are real engine output; no decimal-exact promise; no fabricated validated-accuracy figure. ✓
- **Uses the design system** — slate + steel-blue, mono numbers, `.cv-eyebrow` tick, provenance fill/hollow, hatched confidence; reuses the glass-box components and public chrome read-only; light/dark via the shared tokens. ✓
- **Builds green** — `next build` exit 0 with `/` + `/method` prerendered (caveat: shared tree transiently depends on the concurrent platform-agent edits to PartWorkspace). ✓
