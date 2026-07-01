# CadVerify — Audience Definition

**Role:** Audience Researcher (research only, no design).
**Goal:** Define *who CadVerify is really for*, what each segment needs from the **interface**, and how that translates to a **distinct role-aware view / IA implication** — so a designer can derive the role-based views directly from this document, and so opposing needs between segments are explicit rather than averaged away.
**Date:** 2026-06-29.

> The acceptance bar this doc is written against: a designer can build role views straight from §2; every need traces to a real workflow or studied pain (evidenced, §6), not taste; and the **opposing needs are made explicit** (§3) so we design IA that serves contradictory users without drowning anyone.

---

## 0. How to read this

- **§1** grounds the audience in *product reality* — the real outputs of the Cost-Truth Engine in the repo. Every "need" below maps to a real surface the engine already produces, so designers aren't designing against a toy model. This is non-negotiable per the program: design against `report_to_dict`, not `cost_per_cm3`.
- **§2** is the heart: five segments, each with **Who → Jobs-to-be-done → Tools today → Pains → Interface NEEDS → View/IA implication.**
- **§3** is the most load-bearing section for IA: the **opposing-needs matrix** — the explicit tensions the IA must resolve, not paper over.
- **§4** prioritizes the segments against the *actual named buyers* (Zoox Head of Manufacturing; Saudi Aramco) so design effort is spent where the wedge is.
- **§5** is the cross-cutting thesis tie-back (glass-box; the decision not the dollar; role-aware density).
- **§6** is the evidence/source list. `[evidenced]` = backed by a cited source or the repo; `[inferred]` = reasoned from adjacent evidence, flagged honestly.

---

## 1. Product reality the audience is reacting to (so needs map to real surfaces)

The engine (`backend/src/costing/`) already produces, per part, a structured report (`report.report_to_dict`) that is *unusually rich for a should-cost tool* — and that richness is precisely what lets one engine serve five very different users. The real outputs the views will be cut from:

| Engine output (real, in repo) | Field(s) | Which segment it's *for* |
|---|---|---|
| **MEASURED geometry drivers** | `geometry` (volume, bbox, watertight, faces, walls, rotational, sheet gauge/bend count) — `drivers.py` | Design + Mfg engineer |
| **Geometric routing** (archetype + recommended process + human reasoning string + alternatives + confidence) | `routing` — `routing.py: recommend_routing` | Mfg engineer (correctness); Design engineer (the answer) |
| **Per-process should-cost** at multiple quantities, with **itemized drivers, each provenance-tagged** `MEASURED / USER / DEFAULT / SHOP` **+ a source string** | `estimates[].drivers[]`, `line_items` (sum to total) | Cost/value engineer (audit); Sourcing (negotiate) |
| **Confidence interval** per estimate — `low/high`, `half_width_pct`, `validated` flag, honest `label` ("assumption-based, not yet validated" until real ground truth), `basis` string | `estimates[].confidence` — `confidence.py` | All — *the trust object*; Economic buyer especially |
| **Make-vs-buy decision + quantity crossover** (make-now pick per qty, "cheaper if redesigned" tier-2, `crossover_qty`, plain-English `note`) | `decision` — `decision.py: make_vs_buy` | Sourcing (make-vs-buy); Economic buyer (the decision) |
| **DFM verdict + blockers** per process (engine feasibility; `dfm_ready`, `dfm_blockers`) | `engine_feasibility`, `estimates[].dfm_*` | Design + Mfg engineer |
| **Per-shop calibration** — every rate bound to *this shop's* real loaded rates, each tagged `SHOP` + sourced | `data/shop_profiles/*.json` (e.g. Midwest Precision CNC vs Shenzhen Contract Mfg → same part, different cost) | Cost engineer; Sourcing; Economic buyer |
| **Editable assumptions** (every DEFAULT/SHOP/USER value overridable, "your numbers become yours") | `assumptions[]` | Cost/value engineer (the override surface) |

**Critical reality gap to design *for* (build harness owns implementation):** routing, confidence, and per-shop calibration live in the *engine* but are **not yet fully surfaced** by the API/frontend (`/api/v1/validate/cost`). Designs must assume these become available and note the gap — do **not** design as if they don't exist.

**The accuracy honesty rail (hard constraint):** there is **no validated ±X% accuracy number yet** — it is PENDING the first real-data session (the Zoox calibration protocol in `outputs/zoox-calibration-protocol.md`). The interface sells *transparency + method + "validated on YOUR parts"*, never a fabricated figure. The `confidence.validated` flag and `label` are the literal UI hooks for this: an un-validated band must *read* as "assumption-based, not yet validated."

---

## 2. The segments

Each segment below is a real role with a distinct **job, default tool, pain, and a single sharpest interface need** that a view can be cut from. The segments are ordered by how directly they touch the product loop (engineer-in → decision-out → buyer-over-the-top).

---

### 2.A — Design / Mechanical Engineer  *(the "fast, glanceable, tweak-rerun" user)*

**Who.** The person who actually models the part in SOLIDWORKS / Creo / NX / Fusion / Onshape. Owns the geometry. Usually has *no* cost-engineering training and *no* time for it. The largest population by far (at GE Appliances: ~1,600 design/mfg engineers behind just **4 cost engineers** — the ratio that defines the whole category problem). `[evidenced — aPriori GE case study]`

**Jobs-to-be-done.**
- "When I finish (or revise) a part, tell me **fast** whether it's manufacturable and *roughly* what it'll cost — before I commit the design."
- "When my design has a cost or DFM problem, show me **which feature** caused it so I can change *that*, then re-check."
- "Let me **tweak → rerun** in a tight loop without leaving my flow or filing a request to another team."

**What they use today.**
- **CAD-embedded DFM + instant-estimate add-ins** — Autodesk Fusion "Get Estimate" (material+process+qty → subtotal + lead time + per-part DFM), Xometry/Protolabs Fusion add-ins, HCL DFMPro (rule checks *inside* SOLIDWORKS/Creo/NX with issues **tagged on the 3D model**). `[evidenced — competitor-ux §1]`
- **Sending the file to a shop / instant-quote site** and waiting — the slow fallback.

**Pains (evidenced).**
- **Feedback arrives too late / too slow.** Waiting days for external DFM checks "slows iteration… wasted time, delayed schedules, drove up costs." Manufacturability problems surface at production ramp as "last-minute redesigns, missed deadlines, unexpected costs." `[evidenced — DFM workflow sources]`
- **Cost is invisible at design time.** Cost drivers (deep cavities, thin walls, tight tolerance/finish, secondary ops like deburr/tap/ream) "quietly force machining and inspection" and "never showed up in the concept discussion." `[evidenced]`
- **The cost tool isn't theirs to drive.** The should-cost expertise sits behind 4 cost engineers; "adoption by design engineers remains a goal rather than an achieved outcome." aPriori needs ~1 month training. `[evidenced — aPriori/GE]`

**Interface NEEDS.**
1. **A single, glanceable answer first**: pass/warn/fail + recommended process + a *confidence-banded* cost — not a 400-field cost structure. Decisiveness over completeness.
2. **A live, persistent estimate** that updates on every config change (material/process/qty), with **price + lead time always on screen** — the core loop they live or die on. `[evidenced — Fusion "Get Estimate", Xometry Configure tab]`
3. **Face/edge-level DFM highlights on the 3D mesh**, two-way linked to an issue list (click issue → geometry lights up). This is table stakes, not a nice-to-have. `[evidenced — DFMPro HD3D, Fusion Visual DFM]`
4. **Depth on demand, hidden by default** — the cost breakdown and assumptions exist but are *collapsed*; they don't have to look unless they want to.

**VIEW / IA IMPLICATION → "Design Engineer view = answer-first, 3D-first, depth-collapsed."**
The default landing for this role is the existing `/cost` answer-first screen, sharpened: a big verdict + recommended-process + banded cost headline, a live 3D viewer with DFM highlights occupying primary real estate, a persistent estimate rail, and **everything cost-engineer-grade (driver table, overrides, scenario history) collapsed behind a "show the math" affordance.** Optimize for *time-to-first-answer* and *re-run latency*. The role's verb is **TWEAK**.

---

### 2.B — Cost / Value Engineer  *(the "depth, traceability, override-everything" user)*

**Who.** The specialist who builds should-cost models, runs value-engineering / VA-VE teardowns, and defends a number to finance and to suppliers. Few of them, supporting many engineers (the 4:1,600 ratio). Lives in spreadsheets and aPriori. `[evidenced]`

**Jobs-to-be-done.**
- "Build a **defensible bottom-up should-cost** I can stand behind — material, cycle time, setup, tooling, overhead, margin — every number sourced."
- "**Override** any assumption the model got wrong for *our* reality and re-derive, keeping an audit trail of what I changed and why."
- "Compare **design iterations / process scenarios** and quantify what each change does to cost over time."

**What they use today.**
- **Excel** (the incumbent) — and its documented failures: static historical data, no CAD/PLM/ERP integration ("a solitary island"), can't keep up with market volatility, needs a seasoned expert to drive. `[evidenced]`
- **aPriori / Siemens Teamcenter PCM** — physics-based bottom-up cost structures, bill-of-process table editors, heat-map cost-driver visualizations, scenario versioning across iterations. Powerful but dense and training-heavy; "really hard to customize for your own way of manufacturing." `[evidenced — competitor-ux §2; aPriori reviews]`

**Pains (evidenced).**
- **Static, un-calibrated numbers.** Excel "relies on static historical data… fails to provide updated cost data amid market volatility." `[evidenced]`
- **A number you can't audit is a number you can't act on.** "Cost estimates that can't be audited or explained are hard to act on and impossible to negotiate from." Traceability must survive "sources, revisions, and approvals… without having to rebuild the rationale." `[evidenced — DFMA/teardown sources]`
- **The opaque-tool allergy.** This persona's entire job is *defending* a number; a black-box estimate (Xometry/Paperless-style proprietary pricing) is unusable to them — they can't put their name on math they can't see. `[evidenced — Practical Machinist threads: "drastically different prices for the same parts," 50–70% markups, methodology undisclosed → skepticism]`

**Interface NEEDS.**
1. **Full driver traceability, surfaced not buried** — every line item shows value + **provenance tag** (`MEASURED / SHOP / USER / DEFAULT`) + source string + error band. This is exactly what `estimates[].drivers[]` already carries; the view's job is to *show all of it*.
2. **Every assumption editable, with the change tracked.** Override a rate → it re-tags `USER` → recompute → and the override persists as an auditable scenario. "Your numbers become yours" is literally this surface.
3. **Line-items that visibly sum to the total** (no naked numbers; the report already enforces `Σ line_items = unit total`). Show the arithmetic.
4. **Scenario comparison + persistence** — two processes or two design revs side by side; saved, named, versioned (vs the design engineer's ephemeral tweak). `[evidenced — aPriori scenario versioning, Siemens persisted table state]`
5. **The confidence interval with its *basis* spelled out** — they will read `confidence.basis` and `label` and trust the tool *more* for admitting "assumption-based, not yet validated."

**VIEW / IA IMPLICATION → "Cost Engineer view = the glass-box, fully open."**
This is the inverse of 2.A: depth is the *default*, not collapsed. A driver-level table (provenance column is first-class, color/tagged), an inline-editable assumptions panel that re-runs on commit, side-by-side scenario columns, and a confidence panel that exposes method/basis/validated. Borrow aPriori's "summary-tile → detail-panel → chart → 3D" grammar and Siemens' **persisted per-user table state, inline cell-level validation, fewer-bolder colors** — credibility without consumer flash. The role's verb is **OVERRIDE & AUDIT.**

---

### 2.C — Sourcing / Procurement Engineer  *(the "compare, make-vs-buy, negotiate" user)*

**Who.** Strategic-sourcing / commodity / supplier-quality engineer who turns a design into a sourcing decision and a negotiated price. Often *not* the part's author; reasons about suppliers, regions, volumes, and make-vs-buy.

**Jobs-to-be-done.**
- "Decide **make-vs-buy** and **which process/supplier/region** at *this* volume — and know where the **crossover** is if volume changes."
- "Walk into a negotiation with a **defensible should-cost** so I'm not taking the supplier's number on faith."
- "**Compare** quotes/options on equal footing and justify the selection."

**What they use today.**
- **RFQ tools + supplier scorecards in spreadsheets + email threads** (the documented fragmented status quo: "supplier scorecards living in spreadsheets and category strategies in email threads"). `[evidenced — strategic-sourcing sources]`
- **Should-cost analysis** as the negotiation baseline ("a baseline reference point used to negotiate final pricing"). `[evidenced — DigiSource/precoro]`
- **Instant-quote marketplaces** (Xometry/Fictiv/Protolabs) for a fast market price — but distrusted on transparency. `[evidenced]`

**Pains (evidenced).**
- **No independent baseline → you negotiate from the supplier's number.** ~60% of orgs overpay due to poor negotiation planning. `[evidenced — Deloitte via search]`
- **Reactive, context-less purchasing** when sourcing and procurement aren't connected ("suppliers scrambled to find… unvetted… worse prices"). `[evidenced]`
- **Can't pressure-test a quote line-by-line.** The win pattern is showing a supplier "your material cost is in line, but your **setup assumption implies half the production rate** we'd expect for this machine class" — which requires a *driver-level* should-cost, not a total. `[evidenced — DFMA cost-engineering]`

**Interface NEEDS.**
1. **Make-vs-buy + crossover as the hero output**, not a footnote — exactly `decision.make_vs_buy`'s `crossover_qty` + per-qty recommendation + plain-English `note`. The quantity crossover *is* the decision they're paid to make.
2. **Side-by-side comparison** — process A vs B, **shop A vs shop B** (the engine already prices the same part differently per shop: Midwest Precision CNC @ $52/hr labor vs Shenzhen @ $14/hr), region multipliers visible.
3. **A driver-level should-cost they can wield** — share the *structure* (material / cycle time / tooling) to focus a negotiation on the line that diverges, without revealing their target total. `[evidenced]`
4. **Confidence as leverage, not false precision** — a band ("$X ± Y%, validated on N of your parts") is *more* credible to a supplier than a fake-exact figure, and matches the thesis (the decision, not the dollar).

**VIEW / IA IMPLICATION → "Sourcing view = the comparison/decision board."**
A two-or-three-column **compare** layout (process × shop × quantity) with the **make-vs-buy crossover chart** as the centerpiece (unit-cost-vs-quantity curves crossing at `q*`), each cell a banded cost with expandable drivers, and an export to a negotiation-ready breakdown. This is the only view where multiple answers coexist on equal footing. The role's verb is **COMPARE & DECIDE.**

---

### 2.D — Manufacturing / Process Engineer  *(the "is the routing actually right" user)*

**Who.** The process/methods engineer who owns *how* the part is actually made — routing correctness, process selection, DFM feasibility for the chosen process. The technical conscience that catches "you can't turn a bracket" and "this has no draft for molding."

**Jobs-to-be-done.**
- "Confirm the **recommended process is correct for this geometry** — and see *why* the tool chose it."
- "Catch the **DFM blockers** for the intended process (undercuts, no draft, wall too thin) before tooling is cut."
- "Sanity-check the cost's **physical basis** — cycle time, stock removal, nesting/build packing — against shop reality."

**What they use today.**
- **CAD-embedded DFM rule engines** (DFMPro: per-process rule checks, criticality config, issues tagged on the model). `[evidenced]`
- **Tribal knowledge + rules of thumb** for process selection — the "casting for high volume" heuristic that experienced engineers now treat as too crude (breakeven interacts with complexity, material, tolerance; Inconel/Ti break even at *lower* volume because machining premium is so high). `[evidenced — CNC-vs-casting sources]`

**Pains (evidenced).**
- **Generic process tools route badly.** A DFM scorer that ranks by *absence of violations* makes a flat 2mm panel read as wire-EDM/binder-jet, and naively picks turning for a bracket or superalloy for a polymer — the exact failure modes the engine's `routing.py` was written to kill (gate G2). The need is *positive, geometry-evidenced* routing with surfaced reasoning. `[evidenced — repo routing.py]`
- **Breakeven is nuanced and easy to get wrong** when volume thresholds are treated as absolute. `[evidenced]`
- **DFM findings that don't tie to geometry** are unactionable ("can't tie manufacturability findings to design intent → last-minute redesigns"). `[evidenced]`

**Interface NEEDS.**
1. **Routing rationale, fully surfaced** — the engine already emits a human `reasoning` string ("constant ~2mm wall over a 200×150mm planar footprint, aspect 75:1 → a flat sheet, not a printed solid"), an **archetype**, **confidence**, and **alternatives**. Show all of it; the *reasoning* is the trust object for this persona.
2. **DFM verdict + blockers per process, geometry-anchored** — and the honest "NOT DFM-ready as-modeled" flag (the engine costs the tooling route but labels "requires design-for-molding" rather than hiding it).
3. **The measured geometric drivers visible** — bbox, wall, rotational/sheet predicates, solidity — so they can verify the classification themselves. The `MEASURED` provenance tag is the credibility cue.

**VIEW / IA IMPLICATION → "Mfg Engineer view = routing-correctness + DFM audit."**
A view foregrounding the **routing card** (archetype, recommended process, confidence, *reasoning paragraph*, alternatives) with the measured drivers that decided it exposed beneath, plus a per-process **DFM matrix** (verdict + blockers, geometry-linked). Less about the dollar, more about "is this manufacturable, the right way, and does the tool's reasoning hold up." The role's verb is **VERIFY ROUTING.** (Overlaps 2.A on geometry/DFM but diverges on *depth of routing rationale* — the design engineer wants the answer, the mfg engineer wants the derivation.)

---

### 2.E — Enterprise / Economic Buyer  *(the "decision, risk, trust, ROI" user — and our actual named buyer)*

**Who.** The budget owner who signs: **Head of Manufacturing / VP Operations / Director of Supply Chain.** Owns NPI-to-volume outcomes and the cost of getting a sourcing decision wrong. **Our two named buyers live here:** the **Zoox Head of Manufacturing** (automotive / autonomous-vehicle) and **Saudi Aramco** (aerospace / heavy-industry, ITAR/AS9100-adjacent). `[evidenced — program brief; VP-Manufacturing role sources]`

> **Crucial nuance for design:** our named economic buyer is *hands-on technical*, not a slideware exec. The Zoox calibration protocol shows the Head of Manufacturing personally bringing real parts, reading the **routing recommendation, the driver line-items, and the confidence interval**, and editing rates live. So the "executive view" here is **not** a dumbed-down dashboard — it's a trustable decision surface that *also* rolls up. Do not over-simplify it into vanity KPIs.

**Jobs-to-be-done.**
- "Decide whether to **trust this tool with real decisions** — is its number defensible, and validated *on our parts*?"
- "See the **decision and the risk** (confidence, where the model is guessing vs measured) — not a fake-precise price."
- "Justify ROI and roll it up across a **program/portfolio**; show savings and de-risked decisions to *my* boss/finance."
- "Confirm it **clears IT/security/compliance** — CAD-as-IP, ITAR/AS9100/CMMC data handling." `[evidenced]`

**What they use today.**
- **aPriori/Teamcenter executive dashboards** (Design Value Dashboard, cross-program cost & manufacturability-risk roll-ups; mobile read-only for leadership). 3D Spark's **management dashboard** (cumulative cost/lead-time/CO₂ savings to "generate management support and funding"). `[evidenced — competitor-ux §1–2]`
- **Supplier qualification machinery** (a single new supplier ≈ $1,400 internal cost to onboard; aerospace OEMs cutting supplier lists). `[evidenced]`

**Pains (evidenced).**
- **Cost/schedule risk on NPI and supplier decisions** in a disrupted supply chain (64% of aerospace firms still hit disruptions; aircraft backlog at historic highs). `[evidenced]`
- **Can't trust an opaque number with a program-level decision** — the black-box allergy at the highest stakes. The buyer's defense is *method + provenance + measured-on-our-parts*, which is exactly CadVerify's wedge.
- **Security/compliance gate.** ITAR requires CAD/specs on US-person-only networks, role-based access, audit logs (NIST 800-171); a tool that egresses CAD geometry is dead on arrival. The Zoox protocol's "**runs locally, zero network egress** (CAD-as-IP)" is a deliberate answer to this. `[evidenced]`

**Interface NEEDS.**
1. **The decision, framed with confidence and provenance** — make-vs-buy + crossover + a banded cost whose `validated`/`basis` state is honest ("validated on N of your parts" once real; "assumption-based, not yet validated" until then). **Never a fabricated ±X%.**
2. **A "why trust this" surface** — the methodology made legible: glass-box drivers, per-shop calibration, held-out measured error. This is a *trust artifact*, not a marketing claim.
3. **Portfolio / program roll-up** — savings and de-risked decisions across parts, exportable to a management deck / PDF (every result has a "take it to a meeting" export, per 3D Spark/aPriori). `[evidenced]`
4. **Visible trust signals** — local/zero-egress, provenance-tagged everything, audit trail, compliance posture — surfaced as UI, not buried in a security PDF.

**VIEW / IA IMPLICATION → "Buyer view = decision + trust + roll-up, still glass-box."**
An executive surface that leads with the **decision and its confidence** and a **methodology/trust panel** (calibration state, provenance legend, validated-vs-pending honesty, data-locality badge), plus a **portfolio roll-up** with exec export — but every headline number remains *clickable down into the glass box* (because our buyer is technical and will drill). The role's verb is **TRUST & APPROVE.**

---

## 3. The opposing-needs matrix  *(the IA's hardest job — make these explicit, don't average them)*

The five segments share *one engine* but pull the interface in **contradictory directions**. Averaging them produces a tool that drowns the design engineer and starves the cost engineer (aPriori's and Xometry's opposite failure modes). The IA must serve both poles *role-aware*, not split the difference.

| # | Tension | Pole A (who / wants) | Pole B (who / wants) | IA resolution |
|---|---|---|---|---|
| **T1** | **Decide vs Deliberate** | **Design eng** — one decisive answer, glanceable, "just tell me" | **Cost eng** — every assumption visible & editable; a single answer is *suspicious* | Same data, **role-gated depth**: answer-first with the glass box *collapsed* (A) vs *open by default* (B). Depth is a per-role default, not a global setting. |
| **T2** | **Commit vs Compare** | **Design eng / Mfg eng** — commit to *the* recommended process | **Sourcing** — hold *multiple* options on equal footing to negotiate / make-vs-buy | Two distinct layouts off one report: a **committed answer** view (A) and a **comparison board** (C) — not one compromised middle. |
| **T3** | **Locked defaults vs Open overrides** | **Design eng** — sensible defaults; overrides would paralyze them | **Cost eng** — override *everything*; defaults are a starting point to argue with | Overrides are **progressive disclosure**: invisible to A, first-class to B. The provenance tag (`DEFAULT→USER`) is the shared mechanism, exposed at different intensities. |
| **T4** | **Part-level vs Portfolio-level** | **Mfg eng** — one part's routing correctness & DFM | **Economic buyer** — savings/risk rolled up across a program | **Zoom levels** in IA: part → program → portfolio, each a real surface, navigable both ways (drill down from roll-up to the glass box). |
| **T5** | **The dollar vs The decision** | **Sourcing** — genuinely wants a *number* to wield in negotiation | **Thesis / Economic buyer** — *no fake-precise price*; the decision + confidence is the hero | Resolve with the **confidence-banded driver breakdown**: sourcing gets a number *with its bounds and its drivers* (more wieldable than a point), satisfying both. |
| **T6** | **Speed/automation vs Auditability** | **Design eng / Buyer** — AI-native, fast, low-ceremony | **Cost eng / Mfg eng** — determinism, provenance, "engineered not estimated," distrust of AI black boxes | The product is **AI-native *and* fully traceable**: automation proposes, provenance + editability lets the skeptic verify. Never speed *instead of* traceability. |
| **T7** | **Ephemeral vs Persisted** | **Design eng** — fast throwaway tweak-rerun loop | **Cost eng / Sourcing / Buyer** — named, saved, versioned scenarios with an audit trail | The tweak loop is live/ephemeral by default; **"save as scenario"** promotes it into the persisted, versioned, comparable world (and the audit trail). |
| **T8** | **Glanceable density vs Data density** | **Design eng** — sparse, big verdict, white space | **Cost eng** — high-density tables are *home*; sparse feels like hidden information | **Density is a role property**, executed *well* at both ends (Siemens' "fewer/bolder colors, larger type, persisted table state" proves dense-done-well reads as credible, not cluttered). |

**The single meta-tension:** *transparency that a cost engineer reads as rigor, a design engineer reads as noise.* Glass-box is the thesis and the wedge, so the answer is **never to hide the glass box — only to gate how much of it is open by default per role**, with one shared mechanism (provenance-tagged, editable, summing line-items) dialed to different intensities. The black box (Xometry/aPriori-opaque) loses the cost engineer; the firehose (raw aPriori) loses the design engineer; **role-gated glass-box** wins both.

---

## 4. Prioritization against the *actual* named buyers

Design effort should follow the wedge, not serve all five equally on day one.

1. **Economic buyer (2.E) + Sourcing (2.C) are the beachhead** — because the *named, real* buyers (Zoox Head of Manufacturing; Aramco) sit here, and the make-vs-buy decision + "validated on your parts" trust artifact is the literal thing being sold. But note the buyer here is **technical and drills into the glass box** — so winning them requires the cost-engineer depth (2.B) to exist *underneath* the decision, reachable.
2. **Design engineer (2.A) is the volume/adoption and habit driver** — the 4:1,600 ratio means this is who makes the tool *sticky*; the answer-first `/cost` loop is how it spreads bottom-up. Second priority by sequence, but the largest population.
3. **Cost/value engineer (2.B)** is the depth layer that makes (2.E) trustable and (2.C) wieldable — it must *exist and be reachable* even before it's the default surface for anyone.
4. **Manufacturing engineer (2.D)** is the routing-correctness conscience — highest-leverage as a *trust check* (the reasoning string is a credibility multiplier for everyone) but the smallest standalone audience; ship its surface as a depth layer of 2.A/2.C rather than a separate destination at first.

**Implication:** the IA should make **2.E/2.C the front door**, with **2.A as the everyday workspace**, and **2.B/2.D as glass-box depth reachable from any number** — one report, role-aware entry points, universal drill-down. The role is chosen (or inferred) at entry and sets *defaults*, but every surface remains *navigable* across roles, because real users wear several hats (the Zoox buyer is buyer + mfg engineer + cost engineer in one sitting).

---

## 5. Thesis tie-back (so design never drifts from the spine)

- **Glass-box is the hero → it is the shared mechanism across all five roles**, dialed to different intensities (T1/T3/T8). The provenance tag (`MEASURED/SHOP/USER/DEFAULT`), the summing line-items, the editable assumption, and the honest confidence `label` are the *components* every view is built from. The competitor evidence is unanimous: opacity is the universal complaint (Xometry "drastically different prices… undisclosed method → skepticism"; aPriori "too dense"); transparency-done-right is open territory.
- **The decision not the dollar → the make-vs-buy crossover is the hero output** for the buyer/sourcing front door (T5), and the cost is *always* banded, never fake-exact. The accuracy number stays "validated on your parts / PENDING," wired to `confidence.validated`.
- **Role-aware → the opposing-needs matrix (§3) IS the IA spec.** One engine, role-set defaults, universal drill-down. Density and override-intensity are *role properties*, not global settings.
- **2026 for this audience = clarity, density-done-well, speed, trust signals, not consumer flash.** Borrow Siemens' credibility moves (fewer/bolder colors, larger type, persisted table state, inline validation) and 3D Spark/aPriori's "summary-tile → detail → chart → 3D" grammar; reject consumer flashiness — for an aerospace/AV buyer, flash *reduces* trust.

---

## 6. Evidence & sources

**Repo (product reality, primary):** `backend/src/costing/{report,routing,decision,drivers,confidence,rates}.py`; `backend/data/shop_profiles/{midwest-precision-cnc,shenzhen-contract-mfg}.json`; `outputs/zoox-calibration-protocol.md`; `outputs/design/competitor-ux.md`.

**Design / DFM workflow & pains:**
- [Leo AI — Best DFM Services with Instant Feedback (2026)](https://www.getleo.ai/blog/5-best-dfm-services-that-provide-instant-feedback---2026-review)
- [Trustbridge — Structured DFM feedback reduces iterations](https://www.trustbridge.pro/blogs/post/structured-dfm-feedback-to-reduce-Iterations-in-smart-home-hardware-development)
- [Modus Advanced — What happens during a DFM review](https://www.modusadvanced.com/resources/blog/design-for-manufacturability-review)
- [Fictiv — DFM guide](https://www.fictiv.com/articles/dfm-design-for-manufacturing-guide)

**Cost / value engineering & should-cost:**
- [aPriori — Should Cost Analysis](https://www.apriori.com/should-cost-analysis/) · [Cost & Value Engineering role](https://www.apriori.com/solutions/roles/cost-and-value-engineering/) · [From Excel to Excellence](https://www.apriori.com/blog/from-excel-to-excellence-the-evolution-of-cost-engineering/) · [GE Appliances case study (4 cost engineers / 1,600 design engineers)](https://www.apriori.com/resources/case-study/how-ge-appliances-should-cost-model-implementation-transforms-cost-engineering/) · [aPriori reviews — adoption/training](https://www.capterra.com/p/162255/aPriori/reviews/)
- [DFMA — Cost Engineering / should-costs & supplier negotiations](https://www.dfma.com/cost-engineering.asp)
- [TechInsights — teardown intelligence](https://www.techinsights.com/beyond-cost-estimates-optimizing-product-costs-teardown-intelligence)
- [Precoro — Should-Cost Model guide](https://precoro.com/blog/should-cost-model-how-to-build-calculate-and-negotiate/) · [Galorath — Should Cost Analysis](https://galorath.com/cost/should-cost-analysis/)

**Sourcing / procurement:**
- [Ivalua — 7-step strategic sourcing](https://www.ivalua.com/blog/strategic-sourcing-process/) · [Gartner — Strategic Sourcing](https://www.gartner.com/en/supply-chain/topics/strategic-sourcing) · [DigiSource — Should-cost vs strategic sourcing](https://blog.thedigisource.com/should-cost-strategic-sourcing) · [Spendflo — supplier negotiation (≈60% overpay)](https://www.spendflo.com/blog/supplier-negotiation-strategy-techniques)

**Make-vs-buy / process-routing / breakeven:**
- [Matson — Casting vs CNC (2026), breakeven framing](https://www.matsoncorp.com/casting-vs-cnc-machining-which-process-is-right-for-your-project-in-2026) · [Modus — when casting meets machining](https://www.modusadvanced.com/resources/blog/designing-for-manufacturing-when-casting-meets-machining-in-production-strategy) · [3ERP — casting vs machining 12-factor](https://www.3erp.com/blog/casting-vs-machining/)

**Instant-quote opacity / trust:**
- [Xometry — how it works / quoting](https://www.xometry.com/how-xometry-works/) · [Practical Machinist — "What is the deal with Paperless Parts?"](https://www.practicalmachinist.com/forum/threads/what-is-the-deal-with-paperless-parts.431259/) · [Practical Machinist — Xometry as quoting software](https://www.practicalmachinist.com/forum/threads/using-xometry-as-a-free-quoting-software.410582/) (forum sources gate full text; complaints summarized via search: same-part price variance, 50–70% markups, undisclosed method → skepticism)

**Enterprise buyer / NPI / aerospace-automotive / compliance:**
- [JRG Partners — VP of Operations Manufacturing 2026 hiring guide](https://www.jrgpartners.com/vp-operations-manufacturing-2026-hiring-guide/) · [CMF Pro — aerospace OEMs cutting supplier lists](https://cmfpro.com/why-aerospace-oems-are-cutting-their-supplier-lists-in-half/)
- [Shamrock Precision — AS9100 & ITAR define supply-chain access](https://shamrockprecision.com/why-as9100-and-itar-compliance-now-define-access-to-americas-defense-aerospace-supply-chain/) · [Modus — AS9100/ITAR/CMMC traceability (US-person networks, NIST 800-171)](https://www.modusadvanced.com/resources/blog/manufacturing-traceability-for-defense-complete-guide-to-as9100-itar-and-cmmc-documentation-requirements)

**Competitor UX grammar (borrowed credibility/density patterns):** `outputs/design/competitor-ux.md` (3D Spark three-zone IA; aPriori summary-tile→detail→chart→3D + heat maps; Siemens PCM fewer/bolder colors, larger type, persisted table state, inline validation; Xometry Configure/Analyze split + persistent live estimate; Fusion/DFMPro face-level DFM highlights).
