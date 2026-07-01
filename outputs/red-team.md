# Red-Team — is the CadVerify read honest AND material?

**Date:** 2026-06-29 · **Role:** Red-team (enforce no-flattery AND no-pedantry; kill wishful moats; catch category errors).
**Inputs reviewed:** `read-draft.md` (strategist synthesis) + the three dossiers (`self-audit.md`, `giants.md`, `direct-competitors.md`).
**Method:** I did NOT take the draft or the self-audit on faith. I re-ran the live app and the engine and read the load-bearing source for every one of the draft's most damaging claims. The app is up (frontend :3000 → 200, backend :8000 → 200). Verification ledger below.

**Headline verdict: the draft is honest and material — it is neither too soft nor too nitpicky, and it contains no category error.** It is, if anything, harder on itself than a flatterer would dare ("the wedge is a slide, not software"). One moat-rigor *sharpening* is required (the per-shop-calibration **mechanism** is copyable; only the **data asset + intersection** is structural — the draft has the right bones but doesn't puncture the feature). Two minor flattery tightenings. None rises to a bias failure. **Decision: COMPLETE.**

---

## Verification ledger (I reproduced the draft's evidence, live)

| Draft claim | Independent check | Result |
|---|---|---|
| A1: cost API takes no `shop` param; `EstimateOptions` built without shop | Read `backend/src/api/routes.py` — `validate_cost(qty, region, cavities, complexity, material_class)`, `EstimateOptions(...)` has no shop | **TRUE** |
| A1: live run tags everything DEFAULT, "generic defaults" | Ran engine on real ECU part — `labor_rate $35/hr [DEFAULT] · material_class polymer [DEFAULT]`, every line DEFAULT | **TRUE** |
| A2: router headlines a process its own DFM hard-fails (round-metal prose on a plastic box) | Ran engine on `amrikarisma_Mazduino_LITE_TOP` (one of the named parts). Routing: *"reads as 'rotational' → cnc_turning … A round metal part is rarely powder-bed printed."* DECISION: **Make by mjf (PP)**. DFM: **`cnc_turning fail(0)`**, *"Part lacks rotational symmetry (eigenvalue ratios 0.81, 0.57)."* | **TRUE — reproduced live** |
| A2: root cause = two "rotational" defs | `routing.py:47` `rotational = roundness>=0.80` (bbox squareness); `checks.py:553-575` inertia-eigenvalue ratios | **TRUE** |
| A3: override toasts "build gap," never re-costs | `PartWorkspace.tsx:198,204,209,393` toast "…is a build gap"; `page.tsx:276` promises "re-tags the value USER and re-runs" | **TRUE** |
| A4: ±40–60%, `n_samples:0`, unvalidated | Live engine: *"assumption-based, not yet validated … no ground truth yet"* on every line | **TRUE** |
| B2: dev surfaces in customer nav | `ui/sidebar.tsx` — "Parts (Label)" under Library, "Design system" under Develop | **TRUE** |
| B3: marketing numbers hardcoded, captioned live; fixture embeds A2 | `marketing/data.ts` `unit_cost_usd:14.14`, `crossoverQty:1962`, `recommended_process:"cnc_turning"` + "round metal" prose, under hero `title="Make by MJF (PP)"`; `page.tsx:87` "Real output · …cost-truth engine" | **TRUE** |
| "Engine is real" (Σ-check, confidence, IP-local, 18 procs) | Live: `line items Σ = $24.60` coherence line, confidence interval per line, `[wall-clock 3.38s · IP-local, zero network calls]`, 20+ processes in ENGINE FEASIBILITY | **TRUE** |
| Fixes are "wiring over an existing engine" | `cli.py` exposes `--shop, --set, --labor-rate, --margin, --tooling`; web form exposes only 5 of these | **TRUE** |

**No claim in the draft was found overstated beyond its evidence, and none understated.** The draft does not invent a finding, fake a screen, or soften the self-audit.

---

## CHECK 1 — FLATTERY (is anything sugarcoated / understated vs the evidence?)

**Verdict: PASS.** The draft does not sugarcoat the things that block a buy. It calls the live product "a thin, partly-cosmetic demo," says the marquee differentiator "does not exist in the live product," and the bottom line is "a cleaner-looking 3D Spark with no data, no customers, no validation, and its one differentiator disabled — copyable in a sprint." That is the self-audit's brutality carried through, not blunted. The competitive losses (aPriori at the design seat via aP Design/aP Generate; ProDesk shipping AI-DFM at the design engineer Feb 2026; 3D Spark funded + selling the same shape) are all present, not buried. The "no-bias the other way" passages (Σ-check, confidence, provenance, IP-local) are each **verified true**, so they are accurate credit, not flattery.

**Two minor tightenings (do not flip a buy, but sharpen honesty):**

- **A4 normalizes the wrong way slightly.** The draft leans on aPriori's *"±30–40% is normal"* to argue CadVerify's ±40–60% is "category-correct framing, not a confession." Fair as far as it goes — but aPriori's band is **validated/empirical**, while CadVerify's ±40–60% is an **unvalidated *stated-assumption* band with n=0**: the error bar itself has never been checked against reality, so true error could be wider. The draft *does* land "the laugh is the zero, not the band," so it doesn't let the buyer off the hook — but it should not let ±40–60% read as equivalent to aPriori's grounded spread. **Fix:** one clause — "and unlike aPriori's, CadVerify's band is itself unvalidated."
- **A1's "single highest-leverage line of code" oversells in isolation.** Wiring the `shop` param makes calibration *visible*, but it would bind only the **seeded demo shop** (Midwest Precision CNC) — a buyer still sees a fixture, not their own shop, and still has zero validation. Part 3 sequences this correctly (wire → onboard one real shop → validate), but the A1 "Fix" line implies one line solves the marquee gap. **Fix:** state in A1 that wiring is necessary-but-not-sufficient; the moat still needs ≥1 real shop's real rates + validation.

---

## CHECK 2 — PEDANTRY (is any "laugh at" cosmetic / immaterial? Cut it.)

**Verdict: PASS — nothing needs cutting.** Every laugh ties to either a buy decision or the "looks like real software" bar:
- A1/A2/A3 are existential (missing differentiator; trust-destroying self-contradiction reproduced on the first real part; the core glass-box interaction is fake). Not cosmetic.
- A4 is the gating credibility receipt. B1 is procurement-gating. B2 ("dev tools in the customer nav") is trivially fixable but **maximally material to "is this a product"** — a competitor or buyer who sees "Parts (Label)" and "Design system" one click from Cost knows it's a dev build. The draft labels it exactly right ("trivially fixable, maximally embarrassing"); that's the correct altitude, not pedantry. B3 is an honesty/credibility issue (static captioned "live").
- C2 (DFM depth vs DFMPro) answers a real first-question buyers ask. Material.

**Two thinnest items — flagged, but they survive (not cut):**
- **B4 (ITAR/AS9100 copy)** is the closest to pedantry because the copy is already hedged ("*on the path*"). It survives only because it is tied to materiality: overclaiming compliance is precisely what poisons the **one lane that is the real bet** (zero-egress for IP-gated programs). Keep, but keep it framed as "don't poison your own moat," not as a generic gotcha — which the draft already does.
- **C3 (thin AI/agent story)** is soft as a *single-buy* blocker, but material as 2026 *momentum* (Zoo Zookeeper, Leo $9.7M, SW-2026 AI). The draft correctly refuses the me-too fix ("not a reason to bolt on a chatbot") and reframes it as "the glass box is the substrate for a grounded agent." That keeps it material rather than fashion-chasing. Keep.

If forced to drop one, B4 is the candidate — but its strategic hook (self-poisoning the moat) justifies its place. **No mandatory cut.**

---

## CHECK 3 — MOAT RIGOR (does each "shit their pants" survive structural + hard-for-THEM + buyable? Kill the wishful.)

**Verdict: PASS — but with the single most important sharpening in this red-team.** The draft is *self-skeptical*, which is the opposite of a wishful-moat document: it **demotes 3 of its 6 tested components to NOT-a-moat** (glass-box = table-stakes; decision/crossover = copyable-in-a-sprint; design-engineer-web = half-stale, structural vs SolidWorks only). The three it keeps are each correctly **scoped to which players they beat** and **honestly flagged as unrealized in the product**:
- **Neutral / no-margin (Test 5):** structural vs the **marketplaces specifically** — they are *economically barred* (exposing markup cannibalizes take-rate; Xometry's Q1-2026 personalized pricing, sourced, sharpens this). The draft correctly says it does **not** beat aPriori (also neutral). Survives, well-bounded.
- **Local-first / zero-egress (Test 6):** structural vs marketplaces + 3D Spark + Zoo (Zoo is cloud-only by architecture, verified). Draft is honest it is **not productized** ("a dev build that happens to make no network calls"). Survives, honestly conditioned.
- **Per-shop calibration (Test 4):** survives **only as a data asset + inside the intersection**, and the draft flags it **vaporware** (not in web app, zero real shops). Survives *as conditioned*.

**Required sharpening — the draft does not puncture the calibration MECHANISM, and it must.** I read the implementation: a shop profile (`backend/data/shop_profiles/midwest-precision-cnc.json`, `shop_profile.py`) is **~20 scalar rates** — `labor_rate, margin, overhead, utilization`, 7 `machine_rates`, 5 `material_prices`, region multipliers — plus a `source` audit string. Mechanically, "per-shop calibration" is a **rate-override table that re-tags lines SHOP**. That mechanism is **copyable in a sprint** and the giants dossier *itself* concedes SolidWorks Costing templates are already "partly editable (you set raw-material cost, setup/operation times, scrap)"; Paperless Parts already holds **richer, real** shop rate data. So per the project's own rule — *"copyable-in-a-sprint is NOT a moat"* — the calibration **feature** is table-stakes. The draft locates the hard part correctly ("a per-shop rate data asset nobody hands you — data + trust, not just an engine") but never says plainly that the **mechanism is copyable**, leaving a skimming reader free to over-credit the feature as the moat. **Fix (one paragraph in Test 4):** state explicitly that the rate-substitution mechanism is table-stakes (SolidWorks half-ships it; Paperless owns richer data), and that the *only* structural pieces are (a) a **network of real, validated shop profiles** (CadVerify: zero) and (b) the **neutral + zero-egress + decision intersection** — i.e., the moat is data + the intersection, never the calibration UI.

**Does this make any kept moat wishful? No.** When read in full, the surviving moat IS the data-asset + intersection, both genuinely hard (a network of validated shop rates is not a sprint; the marketplace margin/exfiltration bar and Zoo's cloud-only architecture are structural), and the draft brutally flags both as unbuilt. Part 3 even narrows the final bet to the **one lane** — zero-egress, IP-gated, design-engineer cost-decision — where the intersection holds even against aPriori (whose design-engineer products aP Design/aP Generate are **cloud**, and whose on-prem product is the wrong persona/shape). That narrowing is defensible. The intersection is not wishful; it is correctly conditioned. The mechanism-copyability sentence is a sharpening, not a kill.

*(Secondary note: in isolation, "per-shop calibration is structural" overstates vs aPriori, which is held off by **positioning**, not capability — it could add a rate-override. The intersection + zero-egress narrowing is what genuinely binds aPriori; the standalone Test-4 "STRUCTURAL. Survives." header should inherit that qualifier.)*

---

## CHECK 4 — CATEGORY ERROR (is CadVerify judged for not being a modeler? Is it fairly judged where it competes?)

**Verdict: PASS — clean.** Nowhere does the draft fault CadVerify for not modeling geometry. The frame is stated up front and held. The dossiers explicitly **reject** the category-error sneers ("it can't open a native part / has no engine" → "Reject"). Where the draft judges hard, it judges **inside CadVerify's category**: DFM depth vs DFMPro (DFM is its category), cost credibility vs SolidWorks Costing / aPriori (should-cost is its category), trust/compliance vs Zoo's public SOC2 (the axis it stakes), neutrality + zero-egress vs the marketplaces (its wedge). C3 (AI) is not a demand to become a modeling copilot — it asks for a **grounded agent over the glass box**, which is squarely its category. The draft also does **not** abuse the frame in the other direction — it never hides a real cost/DFM/trust weakness behind "but we're not a modeler." Fairly judged only where it touches the giants; correctly excused where it doesn't.

---

## Decision

**COMPLETE.** The read is honest (no material weakness understated — I reproduced the four worst laughs live, including the router/DFM self-contradiction on a real ECU part) and material (no laugh is mere cosmetics; the two thinnest are saved by strategic materiality). The moats are rigorously self-skeptical (3 of 6 demoted) and every surviving moat is correctly scoped and flagged as unbuilt; there is no wishful moat and no category error.

**Apply before publishing (sharpenings, not failures):**
1. **(Moat rigor — do this one)** In Test 4, say plainly that the per-shop calibration *mechanism* (~20 scalar rate overrides) is table-stakes/copyable (SolidWorks Costing half-ships editable rates; Paperless owns richer real shop data); the structural moat is **exclusively** the data-network of real validated shops + the neutral/zero-egress/decision intersection. Inherit that qualifier in the section header.
2. **(Flattery)** A4: add that CadVerify's ±40–60% is an *unvalidated* assumption band, unlike aPriori's empirically grounded ±30–40%.
3. **(Flattery)** A1: mark the "wire the shop param" fix necessary-but-not-sufficient — it binds the seeded demo shop; the differentiator still needs ≥1 real shop + validation.

None of these reverses the draft's bottom line, which is correct and brutal: **the engine is real; the buyable product is a demo whose one structural differentiator is a disabled button; the thesis is right, the receipts are missing, the window is Zoo's roadmap.**
