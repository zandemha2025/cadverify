# Giants Intel — SolidWorks, Fusion 360, Zoo.dev vs CadVerify (2026)

**Scope (no category error):** SolidWorks and Fusion are CAD *creation* tools; Zoo.dev is AI-native CAD *infrastructure*. CadVerify does not model geometry. This brief judges the giants ONLY where they touch CadVerify's actual turf — **DFM checking + should-cost + manufacturing decision (routing, make-vs-buy, quantity crossover, per-shop calibration)** — plus the "looks like real software" bar they set. It does NOT fault CadVerify for not being a modeler, and it does NOT fault the giants for being modelers.

**What CadVerify is, judged against (ground truth, current state):** a web, design-engineer-facing DFM + glass-box should-cost + decision tool. Upload STL/STEP → routing + itemized, provenance-tagged cost drivers (MEASURED/USER/DEFAULT/SHOP) + confidence intervals + lead time + make-vs-buy crossover. Wedge = glass-box (every assumption visible/editable) + per-shop calibration (same part priced $44/$110/$35 across three shops, every rate tagged + sourced) + decision-not-dollar + speed for the design engineer, no CAD seat required. **Honest weaknesses it carries into this fight:** absolute cost is ±40–60% and NOT YET validated against real quotes; per-shop calibration works in the engine/CLI but is NOT wired into the live web API (UI shows generic defaults); local-dev only, no cloud, no SOC2/ITAR yet. These are the things the giants would laugh at, and they are mostly fair laughs.

Every finding below is split two ways: by **AXIS** (credibility/polish · UX/ease · capability/depth · correctness/trust) and by **COPYABILITY** (table-stakes = a giant clones it in a release → must-fix-to-be-real; structural = hard for THAT giant specifically to copy given what they already are).

---

## TL;DR

- **None of the three giants ships a real should-cost decision product.** SolidWorks Costing is the closest (real editable-rate cost templates, live in the modeler) but it is desktop-bound, locked behind a $3,456–$4,716/yr Pro/Premium CAD seat, single-part, and has no make-vs-buy / quantity-crossover / multi-shop framing. Fusion's "cost" is CAM cycle-time, machinist-facing, and requires you to program a toolpath first (its own users call the estimates "junk"). Zoo has **zero** cost/quoting today.
- **The thing CadVerify bets on — per-shop calibrated, glass-box, decision-grade should-cost for the design engineer, no CAD seat — none of them sell.** That is a real opening.
- **But CadVerify is bringing an unvalidated ±40–60% number and an unwired calibration feature to a fight where SolidWorks Costing has been shipping grounded, editable, template-based cost for a decade.** The giants laugh at "trust me" accuracy and a marquee feature (per-shop) that the live web app doesn't actually run.
- **LIVE THREAT — Zoo.dev.** Zoo is the one structurally positioned to eat this category: AI-native, web-streamed (runs on a potato), own GPU geometry engine, Zookeeper already markets "manufacturing-aware feedback" and "design reviews," public SOC2 Type II + Trail of Bits report, free tier. Today Zoo does NOT do should-cost, DFM rule-checking, quoting, or per-shop calibration — but it is the player whose distribution + engine + AI loop could bolt on manufacturability/cost fastest. Treat Zoo as the clock CadVerify is racing.

---

## 1) SolidWorks (Dassault Systèmes)

### Power
The default mechanical CAD seat for a generation of design engineers; enormous installed base, reseller channel (GoEngineer, TriMech, Hawk Ridge), training pipeline, and the "this is what real engineering software looks like" expectation. SolidWorks 2026 is an explicit AI push — Dassault marketed ~10–12 AI features at 3DEXPERIENCE World 2026, most GA July 2026, most in beta before then ([engineering.com](https://www.engineering.com/10-ai-tools-coming-to-solidworks-in-2026/), [3ds.com newsroom](https://www.3ds.com/newsroom/media-alerts/dassault-systemes-announces-solidworks-2026-ai-powered-design-and-collaboration-generative-economy)).

### Manufacturability / cost / AI footprint (the part that touches CadVerify)
- **SOLIDWORKS Costing** — real, integrated, live-updating should-cost. Recognizes manufacturing features (cutouts, bends, holes, bosses, pockets) and prices machined parts, sheet metal, weldments, plastics, 3D printing. Uses **Costing Templates** where you set raw-material cost, setup time, operation/machine times, scrap reclamation, etc. — i.e. it is partially **glass-box and editable**, not a pure black box. Available in **Professional** (parts/multibody) and **Premium** (assemblies) ([SOLIDWORKS Costing Overview 2025](https://help.solidworks.com/2025/English/SolidWorks/sldworks/c_costing_overview.htm), [Machining Costing 2025](https://help.solidworks.com/2025/English/SolidWorks/sldworks/c_machining_costing.htm), [Javelin: SOLIDWORKS Costing](https://www.javelin-tech.com/3d/solidworks-costing/)).
- **DFMXpress** — rules-based manufacturability checker (drill/mill/turn, sheet metal, standard holes, injection molding). Included from the **Standard** tier ([DFMXpress Overview](https://help.solidworks.com/2025/English/SolidWorks/dfmxpress/c_DFMXpress_overview.htm), [Rule Descriptions 2026](https://help.solidworks.com/2026/english/SolidWorks/DFMXpress/c_rules.htm)).
- **2026 AI** — Design Inspection (natural-language model queries), Material Manager (chat material assignment), Assembly Performance Doctor, Design Change Impact, Shop Floor Programmer (cloud CAM, now in Design licenses). Notably, the AI wave is about modeling/drawings/PLM/assembly help — **not** a should-cost or sourcing-decision copilot. Assembly Performance Doctor "cannot currently take action on its own recommendations" ([engineering.com](https://www.engineering.com/10-ai-tools-coming-to-solidworks-in-2026/), [Hawk Ridge](https://hawkridgesys.com/blog/upgrading-solidworks-2026-new-features)).
- **Pricing:** Design Professional ~$3,456/yr, Design Premium ~$4,716/yr USD; quote-gated; 2-year minimum commitments ([CheckThat.ai pricing](https://checkthat.ai/brands/solidworks/pricing), [Ohmycad price list](https://ohmycad.com/en/official-price-list-3dexperience-solidworks/)).

### What SolidWorks would LAUGH AT in CadVerify
- **(Correctness/trust — fair, material)** "You ship an unvalidated ±40–60% number; our Costing has been grounded in editable, auditable rate templates for ten-plus years and updates live as the model changes." A buyer who already owns Costing will ask why they'd trust a brand-new tool's dollar figure that the tool itself labels PENDING validation. **This is the biggest fair laugh.**
- **(Credibility/polish — fair)** Local-dev, no cloud, no SOC2/ITAR, seeded test login. SolidWorks is enterprise-procured, ITAR-handled, channel-supported. The gap in "is this a real, buyable, supported product" is enormous today.
- **(Capability/depth — partly fair)** "Your marquee per-shop calibration isn't even wired into your own web app — the UI reads generic defaults." A feature that only runs in the CLI is not a feature a buyer can buy yet. Fair until it's wired.
- **(Capability — NOT fair / category error to avoid)** They might sneer "it can't even open a native part / has no feature tree / can't model." Reject this — CadVerify is not a modeler and consumes STL/STEP on purpose.

### Where SolidWorks is STRUCTURALLY weak / slow on the DFM-cost-decision axis (the openings)
- **Locked behind a CAD seat (structural).** Costing requires SOLIDWORKS Professional/Premium ($3,456–$4,716/yr) and lives inside the modeler. The design engineer who just wants "what will this cost / who should make it" must own and open a heavyweight seat. CadVerify's "web, upload a file, no CAD license" is a posture Dassault cannot adopt without cannibalizing seat revenue. **Hard for THEM specifically.**
- **Desktop-bound, native-geometry-biased (structural-ish).** Costing/feature recognition works best on native SOLIDWORKS geometry; it is a desktop, single-part workflow, not a web/portfolio/batch decision surface.
- **No decision layer (table-stakes-to-build, but absent today).** SOLIDWORKS Costing produces a *number*, not a *decision*: no make-vs-buy crossover, no print-vs-mold quantity breakeven, no "which of my N shops is cheapest for this part," no supplier/sourcing comparison. CadVerify's entire decision framing (routing + crossover + per-shop) is whitespace for them. (Caveat: Dassault could add quantity/crossover in a release — it's not deeply structural, but it isn't there now.)
- **No per-shop calibration as a product (structural-ish).** You can hand-edit a Costing Template, but there is no "bind shop X's real rates and reprice the same part across shops X/Y/Z, every line provenance-tagged + sourced." That bind-to-real-rates concept is CadVerify's wedge.
- **Cost-engineer / power-user ergonomics.** Costing templates are configured by someone who knows machine rates; it is not a fast, opinionated, design-engineer-glanceable decision. CadVerify's speed-for-the-design-engineer is a genuine UX gap.

**Net vs SolidWorks:** they have the credible *number* and the install base; CadVerify has the *decision*, the *web/no-seat reach*, and *per-shop calibration* — but only wins the argument once its number is validated and its calibration is actually live in the app.

---

## 2) Fusion 360 (Autodesk Fusion)

### Power
Cloud-connected CAD+CAM+CAE+PCB in one product, aggressive pricing (~$680/yr base), and the dominant tool in small/medium shops, makerspaces, and CAM. Strong generative design and a growing AI layer (Autodesk Assistant). It owns the **design→toolpath→machine** path better than anyone in this trio ([Fusion overview](https://www.autodesk.com/products/fusion-360/overview), [Fusion AI automation](https://www.autodesk.com/products/fusion-360/ai-automation)).

### Manufacturability / cost / AI footprint (the part that touches CadVerify)
- **Cost is CAM-derived, not should-cost.** Fusion predicts **machining cycle times** from programmed toolpaths and simulates/compares strategies (e.g., ball vs barrel cutters) for time/finish/wear. Nesting gives "instant insights for costing, quoting, ordering" at the sheet level. There is no fast, design-time, geometry-in → dollars-out should-cost that doesn't require you to first program the job ([Fusion Cost Estimation help](https://help.autodesk.com/view/fusion360/ENU/?guid=GD-COSTING), [Fusion for manufacturing](https://www.autodesk.com/products/fusion-360/fusion-for-manufacturing)).
- **Its own users call the cycle-time estimates unreliable** — long-standing community thread "Machining time estimates are junk" ([Autodesk forums](https://forums.autodesk.com/t5/fusion-manufacture-forum/machining-time-estimates-are-junk/td-p/7035875)). The real should-cost-ish capability comes from a **third-party marketplace app, "Toolpath,"** which AI-scores machinability and returns a cost estimate broken down by setup/operation/tool — telling that Autodesk itself didn't ship this ([Toolpath on Autodesk Marketplace](https://marketplace.autodesk.com/apps/34f13847-ff12-42f4-ad42-03ffdf2190d5)).
- **Generative design** produces manufacturing-aware geometry options under constraints (incl. cost/material), and **Autodesk Assistant** is a natural-language copilot for modeling commands, project management, and "manufacturing insights" ([Fusion AI automation](https://www.autodesk.com/products/fusion-360/ai-automation), [Fusion extensions/pricing](https://www.autodesk.com/products/fusion-360/extensions)).
- **Pricing:** base ~$680/yr; Manufacturing Extension ~$1,465–$2,040/yr ([G2 Fusion pricing](https://www.g2.com/products/autodesk-fusion/pricing), [Fusion extensions](https://www.autodesk.com/products/fusion-360/extensions)).

### What Fusion would LAUGH AT in CadVerify
- **(Capability/depth — fair)** "We close the loop to the actual machine — toolpaths, post, simulation, cycle time. You output an advisory number you admit is ±40–60%." Fusion's manufacturing is *executional*; CadVerify's is *advisory*. For a shop that machines its own parts, Fusion's loop is more tangible.
- **(Credibility/polish — fair)** Cloud, mature, supported, free trials, huge community vs a gated local-dev build. Same "real software" gap as SolidWorks.
- **(UX — partly fair)** Generative design + Assistant make Fusion feel "AI-modern"; CadVerify's AI/agent story is comparatively thin.
- **(NOT fair / category error)** "It doesn't do CAM / can't program a 5-axis job." Reject — CadVerify isn't a CAM tool and isn't trying to be.

### Where Fusion is STRUCTURALLY weak / slow on the DFM-cost-decision axis (the openings)
- **Cost requires a programmed toolpath (structural workflow gap).** Fusion's number is downstream of CAM — it answers "how long will THIS toolpath take," not "what should this part cost and who should make it, before I've touched CAM." The design engineer making an early routing/make-vs-buy decision is the wrong user for Fusion's cost. **CadVerify's design-time, pre-CAM decision posture is genuinely upstream of where Fusion lives.**
- **Machining-only cost lens (structural-ish).** Fusion costs what its CAM/nesting touches (milling, turning, sheet). It does not give a process-agnostic should-cost across CNC vs AM vs molding vs sheet with a quantity crossover and make-vs-buy. CadVerify's process-breadth + crossover is whitespace.
- **No should-cost product of its own; outsourced to a marketplace app (telling).** The fact that "Toolpath" is a 3rd-party plugin, and that Autodesk's native estimates are widely distrusted, says Autodesk hasn't prioritized credible design-time should-cost. An opening — though also a warning that this is buildable.
- **No per-shop calibration / no sourcing decision.** Fusion has no notion of "bind my three vendors' real rates and pick the cheapest, with provenance." Make-vs-buy and multi-shop sourcing are absent.
- **Machinist/CAM-programmer-facing, not decision-facing.** Its manufacturing depth is for the person running the machine, not the design engineer deciding *whether/where* to make. Audience mismatch is the wedge.

**Net vs Fusion:** Fusion owns *execution* (toolpath→machine); CadVerify owns *the upstream decision* (route/cost/make-vs-buy before CAM). They barely overlap in audience — but Fusion's price, cloud maturity, and AI momentum mean any decision layer it bolts on would reach a huge base fast.

---

## 3) Zoo.dev — **LIVE THREAT, flag explicitly**

### Power
The only AI-native, ground-up rebuild of the CAD stack in this trio. Own **GPU-native geometry engine** (KittyCAD/Design API); Design Studio is **web/desktop streamed from a hosted engine over WebSockets** (runs on low-powered machines — no $4k seat, no beefy workstation); a real ML/Text-to-CAD research program; and **Zookeeper**, the conversational CAD agent shipped Jan 2026 (Design Studio v1.1). Free tier (20 min Zookeeper reasoning) lowers adoption friction to ~zero ([Zoo Design Studio](https://zoo.dev/design-studio), [Design API](https://zoo.dev/design-api), [Zookeeper research](https://zoo.dev/research/zookeeper), [Zoo pricing](https://zoo.dev/zoo-pricing)).

### Transparency posture (a credibility bar CadVerify has NOT met)
- **SOC 2 Type II — completed (audit window Jun 1–Oct 2025) and the report is PUBLIC at trust.zoo.dev** ("we decided to make the report publicly available because opening support tickets or emailing sales to get access is painful"). Public trust center, security.txt, GitHub security advisories, open-sourced ruleset bot ([Zoo SOC2 blog](https://zoo.dev/blog/soc2)).
- **Trail of Bits** secure code review + threat model (2024), 14 findings, all fixed, report going public.
- **Contrast:** CadVerify has no SOC2/ITAR yet (design references the path) and runs as a local-dev gated build. Zoo has set a *public, radical-transparency* security bar that maps directly onto CadVerify's own glass-box ethos — and Zoo got there first on the compliance side.

### Manufacturability / cost / AI footprint — and the encroachment
- **Zookeeper markets "manufacturing-aware feedback" and "design reviews."** "With Zookeeper built in, engineers can design and iterate using internet research and manufacturing-aware feedback"; Zookeeper can "perform design reviews," do internet research, propose constraints/parameters, produce a design plan, and compute mass/CoM/surface area/volume ([Zoo home](https://zoo.dev/), [Zookeeper research](https://zoo.dev/research/zookeeper), [Zookeeper product](https://zoo.dev/zookeeper)).
- **BUT — and this is the key honest read — Zoo does NOT currently do should-cost, quoting, DFM rule-checking, sourcing, make-vs-buy, or per-shop calibration.** The Zookeeper research page explicitly contains **no** cost estimation, **no** DFM recommendation/constraint-checking detail, and **no** quoting; "manufacturability" appears as a *design goal/ethos* (B-Rep "designed for building real stuff"), not as concrete DFM checks or economics. March 2026 "What's New" added file uploads, surface modeling, transparency controls, KCL fixes — **nothing** about DFM/cost/quoting ([Zookeeper research](https://zoo.dev/research/zookeeper), [What's New Mar 2026](https://zoo.dev/blog/whats-new-mar-2026)).

### What Zoo would LAUGH AT in CadVerify
- **(Credibility/polish — fair, and pointed)** "We shipped public SOC 2 Type II and a public Trail of Bits report; you have a seeded localhost login and no compliance." Zoo's transparency story currently out-credentials CadVerify on Zoo's home turf (trust).
- **(UX/ease — fair)** AI-native conversational agent, own engine, streamed web app on any machine, free tier. CadVerify's agent/AI experience is comparatively thin and it's local-dev only.
- **(Capability — NOT fair / category error)** "It can't model / has no engine." Reject — different category.

### Where Zoo is STRUCTURALLY weak / slow on the DFM-cost-decision axis (the openings — TODAY)
- **Zero should-cost. Zero quoting. Zero sourcing/make-vs-buy.** Zoo's value is *creation + design assistance*, not *manufacturing economics/decision*. The entire glass-box should-cost + per-shop calibration + make-vs-buy decision surface is **absent** from Zoo today. This is the single biggest open lane.
- **"Manufacturing-aware feedback" is shallow and qualitative.** It's design guidance ("designed for building real stuff," reviews, research), not itemized, provenance-tagged, shop-calibrated dollars with confidence intervals and a crossover. No rate cards, no per-shop number, no decision.
- **Tied to its own modeling/engine workflow.** Zoo's manufacturability story assumes you're modeling *in Zoo*. CadVerify's "upload any STL/STEP from any CAD" is format-agnostic and CAD-neutral; Zoo's gravity pulls toward its own stack.
- **Cloud-only by architecture.** The engine runs in Zoo's cloud (video-streamed) — which is a *strength* for reach but a *structural constraint* for ITAR/air-gapped/defense work where a self-hostable, on-prem decision tool could win. (CadVerify hasn't built this either, but it's a lane Zoo's architecture makes hard.)

### WHY ZOO IS THE LIVE THREAT (not the others)
Zoo is the **only** player whose stack makes the CadVerify wedge cheap-ish to attack:
1. **Distribution + zero friction** — free, web-streamed, AI-native, growing fast.
2. **Own geometry engine + ML/Text-to-CAD loop** — they can compute geometric/manufacturability features at the source and feed an agent.
3. **An agent (Zookeeper) already framed around "manufacturing-aware feedback" and "design reviews"** — the narrative is one product cycle away from "...and here's the should-cost and who should make it."
4. **Radical public transparency (SOC2 + Trail of Bits public)** — they already out-execute on the *trust* axis CadVerify is staking ground on.

What they conspicuously **lack** is exactly CadVerify's moat-in-progress: **shop-calibrated, glass-box, provenance-tagged should-cost + make-vs-buy decision, bound to real rates.** That requires a per-shop rate-calibration data asset and validated cost models — data + trust, not just AI + an engine. If CadVerify gets calibration wired, validated (the Zoox session), and defensibly per-shop *before* Zoo decides manufacturing economics is on-roadmap, that's the structural lead. If not, Zoo's distribution + engine + agent could frame "manufacturability + cost" first and make CadVerify look like a feature. **The race is real; the clock is Zoo's roadmap.**

---

## 4) Cross-cutting: what's table-stakes vs structural

| CadVerify capability | vs the giants today | Copyability | Verdict |
|---|---|---|---|
| Web, no-CAD-seat, upload STL/STEP → decision | SW behind $3.4–4.7k seat; Fusion cloud but CAM-centric; Zoo cloud but own-engine-centric | **Structural** for SW (seat cannibalization); table-stakes-ish for Zoo/Autodesk reach | Real reach advantage, esp. vs SolidWorks |
| Glass-box, every assumption visible/editable | SW Costing templates are *partly* editable; Fusion/Zoo opaque on cost | **Table-stakes** (SW already half-does it) | Differentiator only if paired with per-shop + validation |
| **Per-shop calibration** (bind real rates, reprice across shops, provenance-tagged) | None of the three sell this | **Structural** — needs a shop-rate data asset | The actual moat — but NOT YET wired into CadVerify's web app |
| Make-vs-buy + quantity crossover (decision, not dollar) | Absent in all three today | **Table-stakes to build**, but absent now | Open lane; defensible only via calibration data |
| Process-agnostic should-cost (CNC/AM/molding/sheet) | SW per-process; Fusion machining-only; Zoo none | **Table-stakes-ish** | Breadth helps; not a moat alone |
| Validated accuracy (±X% on N real parts) | SW grounded for years; CadVerify PENDING | **Must-fix-to-be-real** | The gating credibility item |
| Public trust posture (SOC2/ITAR) | Zoo public SOC2 + ToB; CadVerify none yet | **Table-stakes** (Zoo proves it's achievable) | Catch-up item; Zoo set the bar |

**Bottom line for Zan:** The giants don't have a per-shop-calibrated, glass-box, decision-grade should-cost for the design engineer — that gap is real and worth paying for. But two of CadVerify's own honest weaknesses (unvalidated ±40–60% number; per-shop calibration not wired into the live app) are exactly what SolidWorks Costing's decade of grounded, editable cost and Zoo's public-SOC2 transparency will use to laugh it out of a buyer's room. **Validate the number and wire calibration into the web app — those two moves convert the opening from wishful to buyable, and they're the only two the giants can't quickly answer because they require the shop-rate data asset, not just engineering.**
