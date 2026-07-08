# CadVerify — Product Strategy & Honest Verdict (Fable)

**Author:** Fable (orchestrator) · **Date:** 2026-07-04 · **For:** founder + execution agents
**Method:** grounded in our own strategy/product-definition/IA/audit docs + two commissioned external research briefs (competitive landscape; buyer/JTBD/GTM), both adversarial and cited. This is the truth, not encouragement.

---

## 0. The verdict — novelty or worth its salt?

**The engine and platform are real, unusually honest, and well-built. That is not the same as a business — and as currently *positioned*, CadVerify risks being a beautifully-engineered novelty.** Not because the code is weak (it isn't), but because the product points at the wrong things:

- It **leads with glass-box transparency** — which the research shows is *table stakes* (Boothroyd Dewhurst DFMA has sold "transparent vs aPriori's black box" for 30 years), not a wedge.
- It **foregrounds DFM/makeability across ~21 processes** — which is a *free vitamin* (Protolabs/Xometry/Fictiv give DFM away as lead-gen) and an *accuracy trap* (aPriori spent 20 yrs / $109M on process cost models and still has gaps; a newcomer "credible across 21 processes" is a mile wide, an inch deep).
- It serves **three co-equal personas** — dilution when it should serve one.
- Its **core mechanic (radical honesty about uncertainty)** is only a wedge *if paired with a visible convergence loop* — otherwise it's "an estimate nobody trusts."
- Its **numbers are unvalidated** (cold-start), and there is **no clickable product** (UI is mid-redesign).

**It becomes "worth its salt" with a hard focus** (§4–§6). The good news: the two most defensible things we've *already built the bones for* — the **ground-truth flywheel** and **owned-equipment marginal costing** — are exactly the two things the market research independently identified as the real white space. We've been building the right engine and describing it with the wrong pitch.

**One more hard truth:** the "Sakana / AB-MCTS orchestration moat" is a research toy with no live consumer. It is intellectually cool and it is **not** the moat. The moat is (a) the ground-truth data flywheel, (b) owned-equipment marginal costing, and (c) becoming the *system of record* for a captive operator's make-vs-buy. Do not let the orchestration research distract from the wedge.

---

## 0.5. The product, corrected — the VERIFICATION thesis (founder, 2026-07-04)

The founder's own framing, which supersedes the "should-cost-for-negotiation" beachhead below and is *sharper and more defensible than the market-research default*:

> **CadVerify is a makeability VERIFICATION engine.** Put a part in. It understands the **environment the part operates in** (pressure, temperature, corrosion/sour service, medium — the spec). Then it answers: **Can this be made — by printing, CNC, casting, forging, any capacity? In what materials (that survive that environment)? How long? On what machines? And if they have their own machines — what's the best way to make it in-house, or is it even possible on their equipment?** That is the verification.
>
> **"Cost" here is NOT what a partner or shop would charge** — that's the red-headed stepchild. It is the **physical resource cost**: material, printing/machine hours, the machine itself — *do they own it (marginal), don't they, would they acquire it (capex)*. For Aramco it's this at massive catalog scale; same job, different magnitude.

**Why this is the right thesis (and escapes both traps the research flagged):**
- It is **not "free sell-side DFM"** (Protolabs/Xometry give that away to sell *you* parts). This is **in-house makeability against the customer's *own* machines, in environment-valid materials, at resource cost** — nobody gives that away, because nobody else is answering "can *you* make it on *your* equipment."
- It is **not the "should-cost accuracy trap" vs aPriori.** We are not predicting a *market price*. We compute **physical resource cost** — material mass × price, machine/print hours × the customer's own rate, on the customer's own (or acquirable) machine. That is physics + the customer's own inputs, not a market-price bet.
- It **maps exactly onto the two genuine white spaces the research found**: *marginal cost on owned equipment* and *triage-at-scale over a legacy catalog*. The founder has been describing the white space from the maker's side the whole time.

**What this thesis REQUIRES that we have not fully built (the real gaps):**
1. **A machine-inventory model.** Today we model owned *processes* (`owned_processes`), not owned *machines*. The thesis needs the org to declare their actual machines (type, build envelope, materials, rate, throughput) so makeability can answer "**on your Machine X: yes** · part exceeds the envelope of every machine you own → **no, you'd need ≥ Y build volume / Z-axis travel**." This is the single biggest new build the thesis implies.
2. **Environment/spec-fit at the front door.** Declare the service environment → the engine restricts materials + processes to those *valid* for it (NACE MR0175 sour service, temp limits, pressure rating). The makeability verdict becomes environment-aware ("makeable — but only in a NACE-compliant alloy; your requested aluminum fails sour service"). The oil-&-gas material pack (NACE/API flags) is the first half of this; the *gate* that filters on it is the second half.
3. **Resource-cost presentation, not price.** Lead the "cost" output with **machine/print HOURS + MATERIAL + MACHINE-OWNERSHIP** (own → marginal; don't → acquisition consideration), never a market $ or a supplier comparison.
4. **The flywheel, re-aimed:** it calibrates the **customer's actual machine times/throughput** (so "4.2 hrs on your machine" is trustworthy), not market prices. This is *still* the critical trust unlock — arguably more so, because now every number is a concrete machine-specific physical claim.

**ICP implication:** the buyer is the **in-house maker / manufacturing-ops owner** at a vertically-integrated operator — someone deciding *what to pull in-house on their own equipment* — from a mid-market OEM with its own machine shop (faster on-ramp) up to Aramco-scale captive operators (the prize). NOT the sourcing buyer negotiating a supplier quote (that's the should-cost path the founder is de-emphasizing).

*(The should-cost / negotiation framing in §2–§6 below is retained as market context, but where it conflicts with this section, THIS section wins. The plan in §6 is revised accordingly.)*

---

## 1. Does the architecture / flow make sense? (the founder's direct question)

**Yes — the architecture is coherent and logical.** There is a real North Star ("Databricks for manufacturability & cost — the governed decision layer": engine = compute, provenance = lineage, confidence = data quality, portfolio = a `GROUP BY` of the same rows). Every feature built this cycle (governed libraries, flywheel, catalog/triage, cost models, materials) slots cleanly into it. This is not a pile of random features.

**But the flow is almost entirely backend/API.** The elegant IA ("the catalog is home; a role view is a saved query; a decision is `SELECT … LIMIT 1`; the portfolio is a roll-up") exists in the data model and the tests, **not as an experience a buyer can click.** A buyer cannot *feel* the flow. Until one end-to-end flow is real in a UI, the coherence is invisible to everyone but us.

**Where the flow is missing a step (product-level, not Aramco-feature-level):** there is no **RFQ / quote / negotiation object** — the buyer's actual workflow endpoint. A should-cost that can't become "here's what it should cost → here's the supplier's quote → here's the variance and the lever" has no home in the buyer's real job. This is the single most important *missing* piece of the flow.

---

## 2. Market reality (synthesized from both briefs)

- **The pure-play should-cost software market is small** (plausibly low-hundreds-of-millions, ~9–12% CAGR), dominated by **aPriori**. Beware inflated "$34B / 18.8% CAGR" figures — they're loosely-defined SEO market-research; do not cite to investors.
- **The capital and momentum are in adjacent categories:** on-demand marketplaces (Xometry $686M rev; Protolabs $501M), part/drawing intelligence (**CADDi $202M raised**), AI-CAM/quoting (Toolpath, Paperless Parts $51M), AI-native DFM (Leo AI a16z-backed). The field is **hot but crowding** — we are early-but-not-first.
- **The job IS a painkiller — for the right buyer.** Should-cost-for-negotiation is a named, budgeted procurement discipline with same-quarter ROI (a % off a quote; Axcelis held a 10% discount via should-cost). DFM-for-everyone is a vitamin given away free.
- **The trust problem — the most important single finding:** *honest uncertainty is a wedge for the sourcing/triage buyer and a dealbreaker for the design-to-cost/exec buyer.* The market leader **itself** publicly concedes "your should-cost is NOT accurate… could be $71–$132" and reframes it as *negotiation leverage, not truth*. The market is **already trained** that should-cost = leverage. So our honesty is *inside the norm* — **but only if paired with a visible convergence mechanism** (feed real quotes/actuals → watch the estimate tighten → it becomes validated). **Sell the loop, not the estimate.** Honesty without convergence = the classic "estimate nobody trusts" failure.

---

## 3. The competitor to watch, and the white space

- **CADDi is the most dangerous competitor** to our catalog-triage thesis: same buyer (huge legacy catalogs, procurement), well-funded ($202M), explicitly markets make-or-buy. **But today it is retrieval / similarity-search, not a costing engine on owned equipment.** That gap is our seam — and it is closing.
- **The cleanest genuine white space (both briefs agree):** *marginal-cost make-vs-buy on **owned / idle equipment**, calibrated to your actuals.* **No incumbent does this as a first-class capability.** Marketplaces structurally can't (they sell a buy-price with margin). aPriori/DFMA give fully-burdened *buy-benchmarks*, not "what does it cost *me* on *my* paid-off machine." We already built the backend seam for this (`machine_capital_frac`, `owned_processes`). It should be the **tip of the spear, not one bullet among five.**

---

## 4. Sharpened wedge + ICP (the core reframe)

**Beachhead (fast revenue + validation data): the strategic-sourcing / cost engineer at a mid-market discrete manufacturer.**
- **Job:** "Give me a defensible number to challenge this supplier's quote before I sign."
- Why: named budget, tolerates uncertainty (it's a comparison point, not a promise), same-quarter ROI, short(er) sale, buys a point tool on a champion's discretionary budget.
- **Land on ONE commodity** (e.g. machined parts, or the pilot's dominant process family) where our cost model is *validated-good* — depth beats breadth for trust.

**Big prize + unique moat (expansion): captive / vertically-integrated operators (Aramco-class — oil & gas, defense MRO, rail, mining).**
- **Job:** triage a huge legacy catalog → makeable-in-house-at-marginal-cost vs buy.
- Why it's the moat: the owned-equipment marginal-cost wedge + becoming the system of record for their make-vs-buy. Real, budgeted *adjacent* money exists (MRO is 5–10% of COGS with 50–60% excess/obsolete; Aramco IKTVA localization + $30B AM-spares framing).
- **Why it's NOT the beachhead:** the demand is real but **not yet a named budget line** — you'd be creating a category inside someone else's initiative (obsolescence / localization / AM spares), needing an internal champion; plus enterprise + (for defense) FedRAMP/CMMC/ITAR = 9–24-month, security-gated sales where startups die. **Defense is the reward for surviving, not the entry point.**

**The reconciliation:** land on the mid-market sourcing wedge to earn revenue, validated numbers, and a reference customer — which is *exactly* what de-risks and unlocks the Aramco/captive sale later. Same engine, sequenced. The founder's Aramco instinct is the right *destination*; a faster wedge is the right *on-ramp*.

---

## 5. Positioning reframe — lead with / stop leading with

| Stop leading with | Start leading with |
|---|---|
| "Glass-box / transparent should-cost" (table stakes — DFMA owns it) | **"Should-cost that gets *provably* more accurate as you feed it your own quotes"** (the convergence loop — the honest, novel mechanic) |
| "DFM + makeability across 21 processes" (free vitamin + accuracy trap) | **"Marginal-cost make-vs-buy on *your* equipment"** (the unique white space) |
| "A platform for design + sourcing + portfolio owners" (three personas) | **One buyer, one job:** a defensible number to win a negotiation / a make-vs-buy call |
| "AI orchestration moat (AB-MCTS/Sakana)" (research toy, no consumer) | **The ground-truth flywheel as the moat** (data network effect on the buyer's own actuals) |

DFM/makeability stays — but as the **free adoption hook** (get into the CAD-adjacent workflow), never the thing we charge for.

---

## 6. The plan — what to build / kill / re-sequence (for the execution agents)

Ordered by leverage on "novelty → worth its salt." Each is a track the agents can pick up; the orchestrator specs + gates as usual.

**P0 — the four that make the VERIFICATION thesis (§0.5) a real product:**
1. **The machine-inventory model + machine-specific makeability verdict.** Let the org declare their actual machines (type, build envelope, materials, rate, throughput). Then the verdict becomes concrete: "**on your DMG MORI 5-axis: yes** · exceeds the envelope of every machine you own → **no; you'd need ≥ 400mm build volume**." Today we only model owned *processes*; this is the biggest new build the thesis needs and the heart of "on what machines / do they have them / if not, what would they need."
2. **The environment/spec gate at the front door.** Declare the service environment (pressure / temp / corrosion / sour / medium) → restrict materials + processes to those *valid* for it, and make the makeability verdict environment-aware ("makeable — but only NACE-compliant 13Cr/Inconel; aluminum fails sour service"). The oil-&-gas pack's NACE/API flags are the data half; this is the *gate* that uses them.
3. **Resource-cost presentation (NOT price).** Lead the cost output with **machine/print HOURS + MATERIAL + MACHINE OWNERSHIP** — own it → marginal cost; don't → an explicit acquisition/capex consideration ("not on current equipment; a $X machine makes it viable at Y volume"). Kill the make-vs-*buy-a-supplier* framing from the hero; a buy price is at most an optional benchmark.
4. **The convergence loop as HERO — re-aimed at machine times.** We have the plumbing (W5 flywheel, CSV import, recalibration, residual model, `validated` flag). Build the *experience* — but it calibrates the org's **actual machine times/throughput/material usage**, so "4.2 hrs on your machine" earns trust and the `validated` badge is a trophy. This is the trust unlock; without it, machine-specific physical claims are just confident guesses.

**P1 — modern-expectation + depth:**
4. **AI copilot grounded on the glass-box provenance.** "Why is this number? How do I get it down? What do I push the supplier on?" The category went AI-native in 2025–26; our provenance data is *ideal* LLM grounding. Zero LLM today is now a competitive liability, not a missing nicety.
5. **Depth + validation on ONE commodity/process family** (the beachhead's dominant one) — get it *validated-accurate*, not shallow-across-21. **Stop adding process breadth** (see §7 on metal-AM).
6. **The UI — pick ONE flow and make it real:** the sourcing should-cost → convergence loop → negotiation artifact. Not the whole three-persona Decision Catalog at once. The catalog is the right long-term IA; the *first clickable thing* should be the one flow that closes a sale.

**KILL / de-prioritize:**
- Stop chasing all 21 processes to equal depth (accuracy trap). Metal-AM/DED breadth is done-enough; **do not add more process families until the beachhead commodity is validated.**
- Park the AB-MCTS orchestrator as R&D (already disclosed as no-live-consumer) — do not invest further until there's a live consumer that moves a real metric.
- De-emphasize glass-box and DFM-breadth in all outward positioning.

---

## 7. What code CANNOT fix (the human gates — and the #1 lever)

1. **THE UNLOCK: get real ground-truth data from ONE design partner.** Every number is `validated=False` until a real customer feeds real quotes/actuals. This is the single highest-leverage action in the entire company and it is *not a code problem* — it's a design-partner conversation. It simultaneously (a) validates the numbers, (b) proves the convergence loop, (c) produces a reference, (d) de-risks the Aramco sale. **Nothing else matters as much as this.**
2. **Security/compliance for the enterprise/defense expansion** (SOC 2 first; FedRAMP/CMMC/ITAR only when defense is real) — prepare-not-close; the reward for surviving.
3. **The founder's design-register decision** — the UI keeps getting rejected; one flow needs to land so the product is clickable for a pilot.

---

## 8. The through-line (one sentence)

**Point the (already-good) honest engine at ONE buyer's ONE painful job — a defensible, self-tightening should-cost that wins a negotiation or a make-vs-buy on their own equipment — get one real customer's data to make the numbers *validated*, and let that reference open the captive-operator (Aramco) prize the founder is rightly aiming at.** Everything in §6 serves that; everything that doesn't is a distraction.

---

*Metal-AM cost track (in flight) will land to close the feasibility-only gap, but per §6/§7 it is the LAST process-breadth work — the pivot is to depth, validation, the convergence loop, the negotiation object, and one clickable flow.*
