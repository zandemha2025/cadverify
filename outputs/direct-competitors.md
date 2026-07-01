# CadVerify — Direct-Competitor Teardown (the real category)

**Author:** Direct-Competitor Intel agent · **Date:** 2026-06-29 · **Network egress:** yes (sources cited, 2026 state verified)
**Scope:** CadVerify judged head-on vs the tools in its ACTUAL category — should-cost / DFM / instant-quote / make-vs-buy — not vs the CAD giants. For each rival: what it is (2026-verified), real strengths, specific soft spot, and an honest win/lose call for CadVerify *today*.

**Method note.** I re-ran the CadVerify engine on real automotive STL parts (generic and `--shop "Midwest Precision CNC"`) to confirm what it actually does before judging it; I read the project's own accuracy-report.md (84% in independent band, honest ±40–60% absolute, unvalidated against real quotes); and I verified every rival's 2026 product state from primary sources (vendor pages + trade press + reviews), cited inline. No claim here rests on memory of the category alone.

---

## 0. The reframe that governs every call below (read this first)

The instinct is that CadVerify's honest "absolute cost is ±40–60%, not yet validated" is a fatal weakness in a should-cost tool. **It is not — and the proof is the category leader's own marketing.** aPriori, with a 20-year cost-data moat, publishes a blog titled *"Your Should Cost Estimate is NOT Accurate, but that's Okay,"* which states verbatim: *"If you should cost a given casting part at $100, its actual cost could be $71 or $132, a variance of nearly 30%,"* and *"If the same part is sent to three different suppliers, an inherent variance in each supplier's quote can be +/-40% or more,"* concluding *"The goal of the should cost estimate is not to get the most accurate cost but to serve as a valuable point of comparison between the assumed and actual prices."* ([apriori.com/blog](https://www.apriori.com/blog/your-should-cost-estimate-is-not-accurate-but-thats-okay/))

So the entire category — the 20-year incumbent included — concedes that should-cost is a **decision/negotiation instrument, not a precise dollar**, and that ±30–40% is the *normal* spread of reality. CadVerify's "decision-not-dollar + honest error bands + glass-box provenance" is therefore **category-correct framing**, not a confession of weakness.

The trap: CadVerify brings the *right framing* with **none of the assets that make the framing buyable** — no validation data, no customers, no integrations, and (fatally) its sharpest differentiator hidden from the live product. The incumbents bring the same framing **with** the data, the customers, the CAD/PLM hooks, and a buy button. That tension is the whole teardown.

---

## 1. The category map — where CadVerify actually sits

Five clusters, each with a different center of gravity. CadVerify touches all five but lives in none of them cleanly:

| Cluster | Players (2026) | What they sell | The number they produce | Who drives it |
|---|---|---|---|---|
| **Should-cost heavyweight** | **aPriori** | Physics-based cost + DFM, regional libraries | Validated should-cost (their data) | Cost engineer (+ now design eng via aP Design) |
| **Instant-quote marketplace** | **Xometry, Protolabs, Fictiv/MISUMI** | Upload → price → **buy** | A *real, buyable price* = their cost + margin | Buyer / design eng purchasing |
| **Shop-side quoting** | **Paperless Parts** | Estimating/quoting software *for the shop* | The shop's own sell price | Shop estimator / sales |
| **Make-or-buy decision** | **3D Spark** | Per-part scorecard across 18+ techs | Parametric should-cost + indicative supplier price | Design eng / procurement |
| **Design-engineer AI / DFM** | **Leo AI, DFMPro** | DFM(A) feedback / generative CAD copilot | DFM verdicts (Leo adds BOM cost rollups) | Design engineer |

**CadVerify's actual position:** it is 3D Spark's *shape* (per-part, multi-process, design-engineer-facing, make-vs-buy headline) with aPriori's *itemized glass-box* and a unique **per-shop-calibrated, neutral** number — but with **zero** of the incumbency assets (data, customers, integrations, buy button, security certs) and its calibration wedge **not yet in the live web product**.

---

## 2. aPriori — the should-cost incumbent (the moat is real; the door is the persona)

**What it is (2026):** The Manufacturing Insights Platform. Product line is now `aP Pro` (full cost management for cost engineers), `aP Design` (browser-based, design-engineer-facing cost+DFM+sustainability), `aP Generate` (auto-simulates cost+DFM on every CAD check-in to PLM, zero effort), `aP Analytics`, `aP Workspace`. Moat = ~20 years of "digital factories," physics-based process models, and **regional cost data libraries**, with machine-level routing across hundreds of processes. ([apriori.com](https://www.apriori.com/), [aP Design](https://www.apriori.com/solutions/products/ap-design/), [aP Generate](https://www.apriori.com/solutions/products/ap-generate/))

**Real strengths:** validated, calibrated, regionally-resolved absolute cost that procurement *trusts in negotiations*; machine-level routing; deep DFM with system-generated fix instructions; deployed at Carrier/scale; the category's credibility benchmark.

**Real soft spots (specific, sourced):**
- **Training-heavy, cost-engineer-shaped.** Reviewers: *"the complexity of what you see when you open the tool can be intimidating,"* *"you need an understanding of the manufacturing process to leverage the tool,"* and there's an "aPriori Academy" because you need a course to drive it. ([Capterra reviews](https://www.capterra.com/p/162255/aPriori/reviews/), [aPriori Training](https://www.apriori.com/services/training/))
- **Authoritative black box.** It hands you *a* number; the driver-level "why," at the granularity a design engineer can edit live, is not the product's center — its routing frequently needs expert override.
- **Enterprise weight/price.** Subscription is an enterprise line-item, not a self-serve design-engineer tool (reviewers reference being "intimidated with the subscription fee"). ([Capterra pricing](https://www.capterra.com/p/162255/aPriori/pricing/))

**Where CadVerify COULD genuinely beat it:** (1) **Driver-level glass box** — every line tagged MEASURED/USER/DEFAULT/SHOP *with its formula and source*, Σ(lines)=total, an error band per driver, every input editable live. aPriori gives you cost composition; CadVerify gives you the *equation*, which is what defuses a skeptic's "where did this number come from?" (2) **Per-shop neutrality** — bind a specific shop's rates and get *that shop's* number ($44/$110/$35 across three shops, verified in the engine), not a regional-library average. (3) **Self-serve, design-engineer-native, seconds, no course.** (4) **Local-first / zero egress** for IP-sensitive programs.

**Where CadVerify LOSES today (brutal):** aPriori's numbers are **calibrated and validated**; CadVerify's are honestly **±40–60% and validated against zero real quotes**. And the persona-door CadVerify is walking through — *the design engineer* — **aPriori already walked through**: `aP Design` is browser-based, "design to cost easier than ever," and `aP Generate` auto-runs cost+DFM on **every CAD check-in** claiming "40 hours to a few minutes." The "we're the design-engineer-facing one, they're the cost-engineer black box" line is **half-stale**: aPriori is actively colonizing the design seat with 20 years of data behind it. CadVerify wins the *transparency* axis cleanly; it loses *credibility/data depth* badly and no longer owns *design-stage placement* uncontested.

---

## 3. The instant-quote marketplaces — Xometry / Protolabs / Fictiv (a real price, a structural conflict of interest)

These are one cluster with one defining property: **the number they give you is a price they will sell you, = their cost + their margin, sourced through their network.** That is simultaneously their biggest strength (it's *real and buyable*) and the soft spot CadVerify is built against.

### 3a. Xometry — the gold-standard funnel, now AI-native pricing
**2026:** Instant Quoting Engine analyzes CAD geometry → process/material/qty → live price + lead time + DFM, fulfilled by a vetted partner network (8M+ offers, 1M+ parts). In **Q1 2026** it rolled out **"personalized pricing" / conversion-rate models** — a per-quote price-response function tuned per customer "to increase revenue per user" — plus an Enterprise machining lead-time model. ([how it works](https://www.xometry.com/how-xometry-works/), [GlobeNewswire 2026-03-03](https://www.globenewswire.com/news-release/2026/03/03/3248487/0/en/xometry-deepens-ai-native-marketplace-advantage-with-new-enterprise-lead-time-intelligence-and-personalized-pricing-models.html))
**Strength:** frictionless upload→buy, real fulfilment, massive pricing data, consumer-grade polish — the "looks like real software" bar.
**Soft spot (sourced):** the price is **opaque and marked up**. Shop owners and engineers report Xometry markups *"exceeding 50%, highest ~70%,"* same part quoted *$600 vs $1,100* to different users, and single-unit quotes *"almost 2x higher than retail."* The new "personalized pricing" makes price a function of *your* willingness to pay, not the part's cost. ([Practical Machinist](https://www.practicalmachinist.com/forum/threads/using-xometry-to-compare-your-own-quotes.389827/), [seathertechnology](https://seathertechnology.com/xometry-processing-costs-7-factors-behind-high-pricing/)) And the CAD **leaves the building** to be quoted.

### 3b. Protolabs / ProDesk — the giant just shipped CadVerify's surface
**2026:** **ProDesk launched 17 Feb 2026** — real-time AI-driven DFM across **injection molding, CNC, and 3D printing**, configurable instant quotes (material/finish/secondary ops), a Production Catalog for reorders. ([protolabs.com/prodesk](https://www.protolabs.com/prodesk/), [3printr](https://www.3printr.com/protolabs-launches-prodesk-instant-quotes-with-ai-driven-dfm-for-3d-printing-cnc-and-injection-molding-0286963/))
**Strength:** AI DFM + instant quote at the design engineer, backed by Protolabs' real factories — and it's free to use pre-order.
**Soft spot:** the quote is **Protolabs' own factory price** for **Protolabs' own processes** — not a neutral should-cost, not your shop, not a make-vs-buy across the open market. It exists to route you into Protolabs.

### 3c. Fictiv (now MISUMI) — instant quote + DFM + a global catalog
**2026:** Acquired by Japan's MISUMI, **$350M all-cash, closed 17 Jun 2025**; now fusing Fictiv's instant-quote + DFM engine with MISUMI's 22 plants / 20 logistics hubs and standard-component catalog. ([Fictiv](https://www.fictiv.com/articles/fictiv-announces-agreement-to-join-misumi), [MISUMI press](https://www.prnewswire.com/news-releases/fictiv-joins-misumi-to-power-the-next-generation-of-digital-manufacturing-302484260.html))
**Strength:** instant quote, "expert DFM," and now a deep-pocketed parent with physical infrastructure and a standard-parts catalog.
**Soft spot:** same conflict — it quotes to *win the job through MISUMI/Fictiv's network*; the number is a sell price, not a transparent, editable, per-shop should-cost. CAD leaves the building.

**Where CadVerify COULD beat the whole cluster (structural):** This is CadVerify's cleanest structural wedge. (1) **A neutral, glass-box should-cost has no margin and no network conflict** — it tells a design engineer what the part *should* cost at *their* shop's real rates, which is precisely the number these marketplaces are economically incentivized **not** to show (it would let buyers see the markup and undercut the take-rate). A marketplace literally cannot ship "here's our cost, here's our margin, here's what your shop would charge" without cannibalizing itself — that's the "hard-for-THEM-to-copy" part. (2) **Local-first / zero egress** — the marketplace model *requires* exfiltrating CAD to a supplier network; for Zoox/defense/Aramco IP that's a procurement gate CadVerify clears by construction. (3) **Make-vs-buy across the open market** — a marketplace will never tell you "actually, make this in-house" or "a different process is cheaper than anything we offer."

**Where CadVerify LOSES today (brutal):** their number is a **price you can click to buy**; CadVerify's is an *unvalidated estimate you cannot act on*. They have real fulfilment, real pricing data (Xometry's 1M+ parts), shipped polished products, and — as of 2026 — the **AI-DFM-at-the-design-engineer surface CadVerify thinks of as its own** (ProDesk, Xometry add-ins). The "looks like real software" bar is set here, and CadVerify is a local dev build with no deploy, no buy button, and no fulfilment.

---

## 4. Paperless Parts — the real threat to the "per-shop calibration" wedge

**What it is (2026):** Cloud quoting/estimating software **for job shops and contract manufacturers** — RFQ→quote→order, geometry analysis, costing automation, ERP integration. AI layer **"Wingman"** auto-extracts specs (10,000+ ASTM/AMS/MIL-SPEC/GD&T) from quote packages; new **"Requirements Review"** (GA Oct 2025) surfaces critical requirements across prints/models. Pricing ~$500–$2,000+/mo. ([paperlessparts.com](https://www.paperlessparts.com/), [AI press](https://www.paperlessparts.com/press/paperless-parts-new-ai-features-surface-critical-requirements-helping-shops-quote-faster-with-confidence/), [G2](https://www.g2.com/products/paperless-parts/reviews))

**Why it matters to CadVerify specifically:** CadVerify's headline structural bet is **per-shop calibration** — "bind a shop's real rates, get that shop's number." Paperless Parts **already lives inside thousands of real shops with their real cost data and costing automation.** If "the shop's own number" is the moat, the incumbent that *owns the shop's quoting workflow* is the most dangerous holder of that data.

**Soft spot:** it's **shop/estimator-facing, not design-engineer-facing**, and it exists to **produce a quote to sell to a customer** — not a neutral make-vs-buy decision for the person *creating* the part. It's a sell-side tool; CadVerify is a design-side decision tool. Different buyer, different moment.

**CadVerify win:** design-engineer placement, make-vs-buy framing, multi-process should-cost *before* an RFQ exists, glass-box driver provenance. **CadVerify loses:** Paperless Parts has the real shops, the real rate data, ERP integration, and revenue; CadVerify's shop calibration is a CLI feature with seeded demo profiles and **no real shops onboarded** — and (see §7) it isn't even exposed in the live web app a buyer would log into.

---

## 5. 3D Spark — the closest analog and the most important comparison

**What it is (2026):** Hamburg B2B manufacturing & procurement platform — per-part scorecard across **15–18+ AM *and* conventional** techs: manufacturability, cost estimate, lead time, **make-or-buy**, CO₂, plus **indicative market pricing from qualified suppliers**. Raised **~€2M / $2.26M (May 2025), ~$3.5M total, ~22 employees**, customers incl. Deutsche Bahn; funding earmarked to broaden into casting/milling/sheet-metal (toward "truly technology-agnostic"). ([3dspark.de](https://www.3dspark.de/), [3D Printing Industry](https://3dprintingindustry.com/news/3d-spark-raises-e2m-to-broaden-ai-powered-manufacturing-platform-and-strengthen-supplier-connections-239342/), [Tracxn](https://tracxn.com/d/companies/3d-spark/__mtVLCcugaOBRnEifSqEgawmVcIuPEqR6f75cdruN1o0))

**Real strengths:** this is the *proven-survivable shape* CadVerify is copying — alive, funded, real logos, make-or-buy + multi-tech + CO₂, integrated cost profiles *and* real supplier pricing. It is years and customers ahead of CadVerify on the identical thesis.

**Soft spots:** (1) it leans on **supplier indicative pricing** → CAD/round-trip to suppliers, an IP gate for Zoox/defense; (2) its cost is integrated-profile-driven, **not per-shop-calibrated to the buyer's own rates with per-driver provenance**; (3) it does compare technologies but does **not foreground a breakeven-quantity make-vs-buy *decision* with a draggable crossover** as the hero; (4) it's small (22 people, $3.5M) and EU/AM-rooted.

**Where CadVerify COULD beat it:** (1) **glass-box per-driver provenance + per-shop neutral number** (3D Spark is more "trust our integrated profiles + supplier feed"); (2) **local-first / CAD-as-IP** (3D Spark's supplier-pricing model can't natively clear a data-residency gate); (3) **make-vs-buy + crossover as the explicit hero decision** with a quantity slider, which 3D Spark has the ingredients for but doesn't foreground.

**Where CadVerify LOSES today (brutal):** 3D Spark is **shipped, funded, and selling**; CadVerify is local dev with no customers. 3D Spark already has *real* supplier pricing (a path to a buyable number) and broader validated process coverage. On the identical thesis, the only things CadVerify has that 3D Spark doesn't are *architecture choices* (glass-box, per-shop, local-first) — which are worth nothing to a buyer until they're shipped, validated, and in front of a real shop. Right now 3D Spark wins on every axis that isn't a whiteboard.

---

## 6. Leo AI & DFMPro — the design-engineer adjacencies

### 6a. Leo AI — well-funded "AI copilot for the mechanical engineer"
**2026:** Generative AI design copilot inside CAD — turns text/sketches/specs into DFMA-optimized CAD, answers technical Qs, retrieves parts, gives **DFM/DFMA suggestions, extracts/compares BOMs with cost rollups**, citations. **$9.7M seed** (Flint Capital), customers **Scania, HP, Siemens**. ([getleo.ai](https://www.getleo.ai/), [funding](https://www.getleo.ai/blog/leo-ai-raises-9-7m-to-build-the-world-s-first-ai-for-mechanical-engineering))
**Strength:** owns the "AI for the design engineer" narrative, real logos, generative + DFM + BOM cost in one copilot, well-capitalized, CAD-embedded.
**Soft spot:** it's **design-*generation*-first and qualitative**; the cost piece is BOM rollups, **not a glass-box, provenance-tagged, per-shop should-cost with make-vs-buy and a quantity crossover**. It helps you *make a better model*, not *make a defensible economic decision* about it.
**CadVerify win:** the rigorous, itemized, editable cost-decision layer Leo doesn't have. **CadVerify loses:** Leo has funding, logos, CAD integration, and the AI-copilot story buyers are excited about in 2026; CadVerify has a CLI and a local web app.

### 6b. DFMPro (HCL) — mature rule-based DFM, no cost
**2026:** CAD-native (SOLIDWORKS, Creo, NX, CATIA, 3DEXPERIENCE) rule-based DFM/A across molding, sheet metal, machining, casting, assembly — now adding a **"Hybrid AI" probabilistic layer** atop the deterministic rules engine. ([dfmpro.com](https://dfmpro.com/), [about](https://dfmpro.com/about-dfmpro/))
**Strength:** deep, mature, configurable DFM *rules* across processes, native in the engineer's existing CAD, established enterprise vendor.
**Soft spot:** **DFM only — no cost, no lead time, no make-vs-buy decision.** And it's a CAD plugin (toolbars/dialogs), not a standalone decision product.
**CadVerify win:** the entire cost + decision layer DFMPro lacks; a clean standalone product surface. **CadVerify loses:** DFMPro's *DFM depth* — CadVerify's DFM is heuristic and shallow (a sheet-metal routing bug was *just* fixed; draft/undercut checks are coarse), where DFMPro has years of curated, configurable rules. If a buyer's first question is "how good is your DFM," DFMPro wins that narrow contest.

---

## 7. The honest scorecard — win / lose, today

| Rival | CadVerify wins on (real) | CadVerify loses on (today) | Net call |
|---|---|---|---|
| **aPriori** | Glass-box per-driver provenance; per-shop neutral #; self-serve/seconds; local-first | Validated 20-yr data vs CadVerify's unvalidated ±40–60%; aPriori already at the design seat (aP Design/Generate) | **Lose on credibility, win on transparency.** Complementary, not frontal. |
| **Xometry/Protolabs/Fictiv** | Neutral no-margin should-cost; make-vs-buy across open market; local-first IP | They give a *buyable price*; real fulfilment; shipped polished AI-DFM at the design eng (ProDesk 2/2026) | **Lose on "real & buyable," win on neutrality + IP.** Structural conflict is theirs. |
| **Paperless Parts** | Design-eng placement; pre-RFQ make-vs-buy; glass box | Owns the shops + real rate data + ERP; CadVerify has no real shops onboarded | **Lose on data/distribution, win on persona + decision framing.** |
| **3D Spark** | Per-shop calibration + glass box; local-first; crossover-as-hero | Shipped, funded, selling, real supplier pricing & validated coverage vs CadVerify's local dev | **Lose today on everything shipped; win only on architecture (unrealized).** |
| **Leo AI** | Rigorous editable cost-decision layer | Funding/logos/CAD-integration/AI-copilot momentum | **Lose on momentum, win on cost rigor.** Different axis. |
| **DFMPro** | Cost + lead time + make-vs-buy (it has none) | Deeper, mature, configurable DFM rules | **Win on decision layer, lose on DFM depth.** |

---

## 8. The two things that would make them nervous — and the one that's currently vaporware

**Structural, hard-for-THEM-to-copy (real wedges):**
1. **Neutral, glass-box, per-shop should-cost.** A number with *no margin and no network*, every driver tagged + sourced + editable, calibrated to the buyer's *own* shop. The marketplaces (Xometry/Protolabs/Fictiv) are *economically barred* from shipping this — it exposes their markup and cannibalizes take-rate. aPriori *could* but is shaped around cost engineers + its own library, not the buyer's per-shop rates with equation-level transparency. **Verified working in the engine/CLI** (generic $31.05 → shop-calibrated re-derivation with every line re-tagged `SHOP`, $52/hr labor / $12-hr machine ÷0.8 util ×1.15 overhead / $7-kg).
2. **Local-first / CAD-as-IP (zero egress).** Every marketplace requires shipping the CAD to a supplier network; 3D Spark leans on supplier pricing; aPriori/ProDesk are cloud. For IP-sensitive automotive/defense/data-residency programs, "the part never leaves the machine" is a procurement gate the dominant business models can't natively clear. **Verified:** engine runs IP-local, zero network calls.

**The brutal asterisk:** the #1 wedge — **per-shop calibration — is NOT wired into the live web API** a buyer logs into; the UI reads generic defaults (per the project's own current-state and confirmed: the calibration path is engine/CLI-only). **So an evaluator who signs in today sees a generic should-cost — the exact thing aPriori and 3D Spark already do, minus their data and customers.** The single differentiator that would make a marketplace "shit their pants" is invisible in the product. Until it's in the web app, the moat is a slide, not software.

---

## 9. Bottom line (no cheerleading)

- **The framing is right and the category proves it.** Decision-not-dollar + honest error bands is exactly how aPriori (20-yr leader) defends its own ±30% should-cost. CadVerify is not naive here; it's category-correct. ([aPriori blog](https://www.apriori.com/blog/your-should-cost-estimate-is-not-accurate-but-thats-okay/))
- **But framing is free; assets aren't.** Every serious rival brings the same framing *plus* validation data (aPriori), a buyable price (Xometry/Protolabs/Fictiv), real shops (Paperless Parts), shipped product + funding (3D Spark, Leo AI), or deep DFM (DFMPro). CadVerify brings the framing *minus* all of it, on a local dev build with no customers, no SOC2/ITAR, no integrations, and **its sharpest differentiator hidden from the live product.**
- **Two structural wedges are genuinely hard for the incumbents to copy** (neutral per-shop glass box; local-first IP) — but both are **unrealized in the buyable product** (calibration not in the web API; security certs "pending"). They are real moats *only after* they ship, get validated against even a handful of real quotes, and reach one real shop.
- **Where it loses today is not the thesis — it's the receipts.** Get per-shop calibration into the web app, validate ±X% on N real parts (the pending Zoox/Zoox-class session), and clear one IP-gate procurement, and the win/lose table flips on the two structural rows. Until then, a giant looks at the live product and sees a cleaner-looking 3D Spark with no data and no customers — copyable in a sprint, not yet a moat.

---

### Sources
- aPriori: [home](https://www.apriori.com/) · [aP Design](https://www.apriori.com/solutions/products/ap-design/) · [aP Generate](https://www.apriori.com/solutions/products/ap-generate/) · [should-cost "not accurate" blog](https://www.apriori.com/blog/your-should-cost-estimate-is-not-accurate-but-thats-okay/) · [Capterra reviews](https://www.capterra.com/p/162255/aPriori/reviews/) · [Training](https://www.apriori.com/services/training/)
- Xometry: [how it works](https://www.xometry.com/how-xometry-works/) · [2026 personalized pricing / lead-time models](https://www.globenewswire.com/news-release/2026/03/03/3248487/0/en/xometry-deepens-ai-native-marketplace-advantage-with-new-enterprise-lead-time-intelligence-and-personalized-pricing-models.html) · [markup discussion (Practical Machinist)](https://www.practicalmachinist.com/forum/threads/using-xometry-to-compare-your-own-quotes.389827/) · [pricing factors](https://seathertechnology.com/xometry-processing-costs-7-factors-behind-high-pricing/)
- Protolabs ProDesk: [product](https://www.protolabs.com/prodesk/) · [launch 17 Feb 2026 (3printr)](https://www.3printr.com/protolabs-launches-prodesk-instant-quotes-with-ai-driven-dfm-for-3d-printing-cnc-and-injection-molding-0286963/) · [investor release](https://investors.protolabs.com/news-releases/news-release-details/protolabs-introduces-prodesk-ai-enabled-manufacturing-platform/)
- Fictiv/MISUMI: [Fictiv announcement](https://www.fictiv.com/articles/fictiv-announces-agreement-to-join-misumi) · [$350M close (PRNewswire)](https://www.prnewswire.com/news-releases/fictiv-joins-misumi-to-power-the-next-generation-of-digital-manufacturing-302484260.html)
- Paperless Parts: [home](https://www.paperlessparts.com/) · [Wingman/Requirements Review AI](https://www.paperlessparts.com/press/paperless-parts-new-ai-features-surface-critical-requirements-helping-shops-quote-faster-with-confidence/) · [G2](https://www.g2.com/products/paperless-parts/reviews)
- 3D Spark: [home](https://www.3dspark.de/) · [€2M raise / roadmap (3DPI)](https://3dprintingindustry.com/news/3d-spark-raises-e2m-to-broaden-ai-powered-manufacturing-platform-and-strengthen-supplier-connections-239342/) · [Tracxn profile](https://tracxn.com/d/companies/3d-spark/__mtVLCcugaOBRnEifSqEgawmVcIuPEqR6f75cdruN1o0)
- Leo AI: [home](https://www.getleo.ai/) · [$9.7M seed](https://www.getleo.ai/blog/leo-ai-raises-9-7m-to-build-the-world-s-first-ai-for-mechanical-engineering)
- DFMPro (HCL): [home](https://dfmpro.com/) · [about / Hybrid AI](https://dfmpro.com/about-dfmpro/)
</content>
</invoke>
