# CadVerify — Competitor / Category UX Research

**Role:** Competitor & category UX research (research only, no code).
**Goal:** Map how real enterprise DFM / manufacturing-intelligence / instant-quote / should-cost products look and feel, so CadVerify's redesign matches category expectations and beats them on clarity — credible to a Head of Manufacturing and to enterprise IT/procurement (Zoox, Saudi Aramco in view).
**Date:** 2026-06-29.

---

## 0. How to read this document

- Each product has: **IA / primary nav**, **key screens & flows**, **visual language**, **enterprise/trust signals**, and **CadVerify implication**.
- **Honesty about sources:** Most of these products gate their real UI behind login/demo. Vendor marketing pages describe *function* far more than *pixels*. Where a detail is **stated** by a source I cite it; where it is **inferred** from feature copy or category convention I label it `[inferred]`. I could not capture literal screenshots (no image access), so "screens described" are reconstructed from documentation, help centers, "what's new" posts, and analyst write-ups.
- The **synthesis sections (5–9)** are where the actionable, design-from-this material lives. Sections 1–4 are the evidence.

### Category map (the single most important framing for CadVerify)

The space splits into three archetypes with very different UX DNA. CadVerify must deliberately straddle the first and third while *looking* as enterprise-credible as the second.

| Archetype | Examples | UX DNA | Primary user | Density |
|---|---|---|---|---|
| **A. Design-engineer-facing DFM/feasibility** | 3D Spark, DFMPro, Fusion add-ins, aPriori's "Design Engineering" persona | 3D-viewer-first, instant feedback, "is this OK + what will it cost", low-ceremony | Mechanical/design engineer | Medium |
| **B. Cost-engineer / should-cost heavyweight** | aPriori (core), Siemens Teamcenter PCM | Spreadsheet-grade cost structures, bottom-up bill-of-process, deep tables, role dashboards | Cost engineer, sourcing, procurement | Very high |
| **C. Marketplace instant-quote** | Xometry, Protolabs, Fictiv, Geomiq | Upload → configure → price → checkout funnel, consumer-grade polish | Buyer / engineer purchasing | Low-medium |

**CadVerify's lane (per brief):** fast, broad-process, transparent, *design-engineer-facing* — explicitly the 3D Spark lane (A), NOT additive-first CASTOR, NOT the opaque aPriori black box (B). But the enterprise buyers (Zoox/Aramco) and the "glass-box explainable decision" promise mean CadVerify needs **A's approachability + C's funnel polish + B's data credibility and trust signals**. The design job is to make a type-A tool *read* as trustworthy as a type-B platform without inheriting B's density and ceremony.

---

## 1. Design-engineer-facing DFM / feasibility tools (Archetype A — CadVerify's home lane)

### 1.1 3D Spark — the direct comp and template

Sources: [3dspark.de home](https://www.3dspark.de/), [Part Screening](https://www.3dspark.de/3d-spark-part-screening), [Engineering Hub](https://www.3dspark.de/engineering-hub), [Software Advice profile](https://www.softwareadvice.com/scm/3d-spark-profile/), [Capterra](https://www.capterra.com/p/10014404/3D-Spark/), [3Dnatives profile](https://www.3dnatives.com/en/3dstartup-3d-spark-060620234/).

**What it is / positioning.** "Manufacturing and Procurement Insights Platform." Simulates **18 manufacturing technologies deterministically** — process-based costing, geometric manufacturability, lead time from cycle math, and CO₂ — explicitly *engineered, not estimated*. Headline promise: a full feasibility + cost + lead-time + CO₂ answer in a **5-minute lead time**. This is almost exactly CadVerify's value prop, minus CadVerify's explicit make-vs-buy/mold-crossover angle.

**IA / primary nav `[inferred from feature set]`.** Three functional zones: (1) **Part screening / analysis** (upload a part, get printability + conventional-tech comparison), (2) **Costing & quoting / RFQ** (CPQ: configure process, material, spec → price + lead time + smart RFQ vs market price), (3) **Management dashboard** (portfolio-level KPIs: cumulative cost savings, lead-time saving, CO₂ reduction across all implemented parts).

**Key screens & flows.**
- **Per-part result view:** the part's **analysis process chains, cost, lead time and CO₂ outputs** are shown together, with the model in a browser-based 3D viewer alongside data panels. Results are also **exportable to Excel** and to **management summary slides / PDF** — i.e. the screen is the source of truth but every view has a "take it to a meeting" export.
- **Technology comparison:** "compare manufacturing technologies in an instant" — the core differentiator. Multiple candidate processes are ranked side-by-side rather than the tool committing to one. **This is the make-vs-buy / process-selection surface and the most directly transferable pattern to CadVerify's `/cost`.**
- **Cost breakdown:** material / labor / machine time broken out (glass-box), not a single number.
- **Management dashboard:** tracks current cost, delivery time and CO₂ savings at **company/group level** to "generate management support and funding" — i.e. an executive-roll-up explicitly designed to be shown to a budget owner.

**Visual language `[partly inferred]`.** Clean, light, browser-native SaaS; 3D viewer + side data panels; KPI tiles on the management dashboard; results designed to be screenshot-able into management decks. Not spreadsheet-dense. The brand leans modern-startup, not legacy-CAD.

**Enterprise/trust signals.** The word "deterministic / engineered, not estimated" is itself the trust signal — they sell *defensibility of the number*. Costing is "based on their in-house production reality" and "real-time supplier pricing," i.e. the model is anchored to the customer's own shop. Management-reporting exports = procurement/finance credibility.

**CadVerify implication.** This is the closest analog — **mirror its three-zone IA (analyze → cost/decide → portfolio roll-up)** and its "engineered not estimated" framing. CadVerify can *beat* 3D Spark on (a) an explicit, visual **make-vs-buy / mold-crossover** decision (3D Spark compares technologies but does not foreground a breakeven-quantity decision), and (b) a tighter **glass-box "why this number"** explanation surface.

### 1.2 HCL DFMPro — CAD-embedded rule-based DFM (the "checks" model)

Sources: [dfmpro.com](https://dfmpro.com/), [About DFMPro](https://dfmpro.com/about-dfmpro/), [DFMPro for NX](https://dfmpro.com/cad-systems/dfmpro-nx/), [DFMPro for SOLIDWORKS](https://dfmpro.com/cad-systems/dfmpro-for-solidworks/), [HCL Software U](https://hclsoftwareu.hcltechsw.com/dfmpro), [CAD Micro](https://www.cadmicro.com/hcl-dfmpro-for-manufacturers/).

**What it is.** CAD-integrated DFM/DFA that runs *inside* SOLIDWORKS / Creo / NX / 3DEXPERIENCE rather than as a separate web app. Rules-based checks for machining, sheet metal, additive, assembly, injection molding.

**Key UX patterns directly relevant to CadVerify's analysis dashboard:**
- **Rule Manager:** users configure which checks run and the **criticality** of each rule (a settings surface that turns the engine from black box to tunable). → CadVerify should expose a "what we checked and at what threshold" panel.
- **HD3D / problem navigation & tagging:** issues are *tagged on the 3D model* and navigable from a list; "results visualized and interpreted in a 3D environment." → the canonical DFM interaction: **issue list ↔ 3D highlight, two-way linked.**
- A new **hardware-database UI with Excel import/export** — even the heavyweight CAD-plugin world is moving its config surfaces to web-style tables with Excel interop.

**Trap it embodies:** DFMPro lives inside CAD and looks like a CAD plugin (toolbars, tree, modal dialogs) — powerful but *not* a clean standalone product surface. CadVerify's advantage is being a coherent web product; don't import plugin-era visual clutter.

### 1.3 Autodesk Fusion — DFM + quote *embedded in CAD* (Xometry / Protolabs add-ins)

Sources: [Fusion DFM page](https://www.autodesk.com/products/fusion-360/design-for-manufacturing), [Xometry add-in for Fusion blog](https://www.autodesk.com/products/fusion-360/blog/xometry-add-in-fusion-360/), [Protolabs add-in blog](https://www.autodesk.com/products/fusion-360/blog/instant-dfm-pricing-feedback-proto-labs/), [Fusion Cost Estimation help](https://help.autodesk.com/view/fusion360/ENU/?guid=GD-COSTING), [Xometry CAD add-ins](https://www.xometry.com/cad-add-ins/).

**Key pattern — "Get Estimate":** select material + process + quantity → **Subtotal and Lead Time appear**, plus **per-part DFM checks**. **Visual DFM highlights the faces and edges of troublesome features directly on the 3D model** so designers focus their attention. This is the cleanest articulation of the core loop CadVerify lives or dies on: *change a parameter → price + lead time update instantly → problem geometry lights up in 3D.*

**CadVerify implication.** The estimate panel should be **persistent and live** (price + lead time always visible, updating on every config change), and DFM issues must be **face/edge-level highlights on the mesh**, not just a text list. Three.js can do face-group highlighting; this is table stakes, not a nice-to-have.

---

## 2. Cost-engineer / should-cost heavyweights (Archetype B — the "enterprise credible" benchmark to borrow trust from, density to avoid)

### 2.1 aPriori — Manufacturing Insights Platform

Sources: [apriori.com](https://www.apriori.com/), [Manufacturing Insights](https://www.apriori.com/manufacturing-insights/), [Digital Factories](https://www.apriori.com/digital-factories/), [Design Engineering role](https://www.apriori.com/solutions/roles/design-engineering/), [CAD to Cost](https://www.apriori.com/cad-to-cost/), [Tech-Clarity analyst write-up](https://tech-clarity.com/apriori/23198).

**What it is.** Evolved from Product Cost Management into a "manufacturing intelligence platform." Physics/process-based simulation of **400+ manufacturing simulations / 18+ process families** from CAD geometry + metadata → cycle time, **should-cost**, carbon, and DFM guidance. Serves **multiple personas in one platform**: design engineering, cost analysts, sourcing, sustainability, manufacturing.

**Key screens (stated by aPriori/analyst):**
- **Visual toolkit:** "**summary tiles, detail panels, interactive charts, and 3D visualization**" — and **heat-map visualizations to rapidly spot cost drivers** across a design. (This summary-tile + detail-panel + chart + 3D quad-pattern is the enterprise-credible layout vocabulary CadVerify should echo.)
- **Design Value Dashboard:** project-level **cost and manufacturability risk**, leaders **compare performance across programs, drill into root causes.** Plus **aP Analytics / Value Dashboards** tracking cost mitigation *across design iterations over time*.
- **Detailed cost breakdown:** labor / machine / tooling / material components — the glass-box itemization.
- **Guided UX (the modern push):** "drag-and-drop model import, **guided process selection, scenario comparisons**," and **system-generated, on-screen instructions on how to fix manufacturability problems.** aPriori explicitly markets being "easy to learn and easy to use" now — a tell that *even the heavyweight is fleeing its own density.*

**Visual language `[inferred + stated]`.** Data-dense, chart-heavy, role-dashboard-driven, 3D embedded but secondary to tables/charts. Heat maps as the signature data-viz. Mobile access marketed for *leadership* views (read-only roll-ups), not for the analyst workstation.

**Enterprise/trust signals.** "Physics-based," "digital twin," "400+ simulations," named manufacturing-process fidelity, role-based dashboards, program/portfolio roll-ups, scenario versioning across iterations. The trust comes from **traceable methodology + auditability + breadth**, displayed as itemized breakdowns and comparison scenarios.

**CadVerify implication.** **Borrow the credibility vocabulary, not the density.** Specifically adopt: (1) **summary tiles → detail panel → chart → 3D** as the screen grammar; (2) **itemized cost breakdown** (material/machine/labor/tooling/setup) as the default, collapsed-expandable; (3) **scenario comparison** (compare two processes / two quantities side by side); (4) an **executive roll-up** for the history/portfolio surface. Reject: 400-field forms, bill-of-process editing, anything requiring a cost-engineering background. CadVerify's wedge vs aPriori is literally "the answer aPriori gives, without needing a cost engineer to drive it."

### 2.2 Siemens Teamcenter Product Cost Management — the legacy-enterprise visual baseline

Sources: [Siemens PCM product page](https://www.siemens.com/en-us/products/teamcenter/solutions/product-cost-management/), ["What's New" v2512](https://blogs.sw.siemens.com/teamcenter/whats-new-in-teamcenter-product-cost-management-version-2512/), [v2406 What's New](https://blogs.sw.siemens.com/teamcenter/teamcenter-product-cost-management-whats-new/), [PCM news index](https://blogs.sw.siemens.com/teamcenter/teamcenter-product-cost-management-news/), [Teamcenter costing PDF](https://www.plm.automation.siemens.com/media/country/engage/Siemens-PLM-Teamcenter-product-costing-fs-32233-A8_tcm47-35476.pdf).

**What it is.** Bottom-up should-cost: cost structures built from detailed product structures + bill-of-process, calculated against benchmark databases of machines, materials, and worldwide labor rates. The cost-engineer's spreadsheet, productized.

**UX details Siemens actually published (rare hard signal on enterprise visual direction):**
- **Table editor is the heart of the product:** "state-of-the-art table editor" with **real-time feedback, multi-line / parallel editing, pre-configured layouts, and parallel collaboration** (multiple cost engineers editing a bill-of-process simultaneously). **Column order, width, selection, and collapse/expand state persist automatically per user.**
- **UI modernization explicitly toward "simple colors aligned with Siemens style," better color *ratios*, larger font sizes for readability, and a modern application header with refined navigation.** Tabs were **relocated inside the document** and the calculation-variant view **split into 4 focused views.**
- **Inline validation:** "warnings and errors are visualized in the field where the validation occurs" — error-at-the-cell, not in a separate panel.
- **Collapsible unused views** to manage hierarchy.

**CadVerify implication.** Even Siemens' answer to "make our dense tool credible" was: **fewer, bolder colors; larger type; persisted table state; inline cell-level validation; a clean app header.** These are cheap, high-credibility moves CadVerify should adopt wholesale — they read as "enterprise/grown-up" without adding density. The **persisted per-user table state** (column order/width/density) is a specific feature to implement on CadVerify's data tables (batch, history).

---

## 3. Marketplace instant-quote tools (Archetype C — the funnel polish to borrow)

### 3.1 Xometry — Instant Quoting Engine (the gold-standard funnel)

Sources: [How Xometry Works](https://www.xometry.com/how-xometry-works/), [Quoting home](https://www.xometry.com/quoting/home), [Quote configuration update blog](https://www.xometry.com/resources/blog/quote-configuration-update/), [ML for manufacturing](https://www.xometry.com/machine-learning-for-manufacturing/), [EU instant quoting engine](https://xometry.eu/en/instant-quoting-engine/).

**IA / flow (clean, linear, recoverable):** personal **dashboard** → **drag-and-drop upload** (STEP/STP/SLDPRT/STL/IPT/CATPART/SAT/DXF/…) → auto-started quote with a **recommended process + material** → **Configure** → **Analyze** → **Checkout**. The system *pre-fills a sensible default* so the user is never staring at an empty form.

**Key screens (from their redesign blog):**
- **Full-page, two-tab layout:** **Configure tab** (pricing + configurable part properties, the working surface) and **Analyze tab** (a *much larger* 3D preview + design-feedback window). Splitting "decide" from "inspect" lets each tab use full width.
- **Top-of-screen utilities:** **Revise Part Model** button (re-upload a fix), **Price-Tier dropdown** (Standard / Expedited / Economy), **DFM Feedback dropdown** (what checks ran).
- **Parameters section:** process / material / finish / quantity / inspection, plus **certifications (ITAR, CoC, Material Certs) as tick-boxes applied per line item.**
- **A built-in search bar *inside the configuration page*** to look up manufacturing terminology, acronyms, and the right parameter — they explicitly designed for "endless terms and acronyms" confusing users.
- **Pricing & lead time update instantly** on every selection; three price tiers presented as a tradeoff (cost vs speed).

**CadVerify implication (high value):**
1. **Pre-fill a recommended process/material on upload** — never show an empty config.
2. **Split "Configure / decide" from "Analyze / inspect 3D"** so the 3D viewer can go big and the decision panel stays focused. This maps directly onto CadVerify's analysis-dashboard vs `/cost` tension — consider tabs or a two-pane split rather than cramming both.
3. **A glossary/term search inside the tool** — for a design-engineer audience hitting process/cost jargon, an inline "what does this mean / how did we compute this" is both UX *and* the glass-box trust play.
4. **Tradeoff presentation** (CadVerify's version: not price tiers but *process options / quantity scenarios* presented as an explicit comparison).

### 3.2 Protolabs (incl. ProDesk) — the best-described DFM 3D interaction

Sources: [Navigating Manufacturing Analysis](https://www.protolabs.com/resources/design-tips/navigating-manufacturing-analysis/), [Online quoting & analysis](https://www.protolabs.com/online-quoting-and-manufacturing-analysis/), [Automated Design Analysis](https://www.protolabs.com/en-gb/automated-design-analysis/), [Quoting Platform help](https://www.protolabs.com/help-center/quoting-platform/), [ProDesk launch (3Printr)](https://www.3printr.com/protolabs-launches-prodesk-instant-quotes-with-ai-driven-dfm-for-3d-printing-cnc-and-injection-molding-0286963/).

**The DFM 3D interaction — the most transferable detail set in this whole report:**
- **Interactive 3D part with highlighted issues**, and a **transparency slider that hides non-problematic areas** to focus attention on undercuts / draft / thin walls / surface finish / material flow. → CadVerify: a **"ghost the healthy geometry, spotlight the problem features"** mode.
- **Two-tier issue severity, named clearly:** **"Required changes"** (must fix before production) vs **"Advisories"** (recommended, not mandatory). → adopt this exact two-tier model; it's clearer than a 1–5 score for an engineer who just wants to know "do I *have* to fix this."
- **Precise measurements surfaced on the offending feature** (e.g. thickness of a too-thin wall), not just "wall too thin."
- **ProtoFlow fill analysis:** animated resin flow with **color-coded pressure fields** — process-specific simulation viz.
- **Keyboard shortcuts** for power users: `~` orthogonal views, `D` dimensions, `F` draft. → enterprise tools earn engineer trust with keyboard affordances.
- **Quote stays active 30 days and updates in real time** as you change finish/material/delivery/quantity.

**ProDesk (2024+):** AI-driven DFM with instant quotes across 3D printing, CNC, and injection molding — "end-to-end web front end with real-time quotes, automated DFM, collaboration." The whole industry is converging on CadVerify's exact pattern; differentiation is in clarity and the make-vs-buy decision, not in having the feature.

**CadVerify implication.** Adopt verbatim: **Required vs Advisory** severity language; **transparency/ghost mode** to isolate problem geometry; **measurement annotations on the feature**; **keyboard shortcuts** for view/measure/section; **live-updating estimate** with a stated validity window.

### 3.3 Fictiv — quote management & comparison at scale

Sources: [Our Platform](https://www.fictiv.com/our-platform), [FictivMade quoting](https://www.fictiv.com/articles/fictiv-made-online-platform-quote), [Next-gen Quotes experience](https://www.fictiv.com/articles/welcome-to-our-next-generation-quotes-experience), [Getting started](https://www.fictiv.com/help/getting-started/how-to-get-started-with-fictiv).

**Patterns relevant to CadVerify's batch / history / share surfaces:**
- **Quotes dashboard:** create many quotes, **compare pricing across material / production time / shipping** to find the right configuration — *comparison as a first-class screen.*
- **BOM grouping + bulk configure:** group multiple files from one BOM into a quote and **configure in bulk** (set material/finish across many parts at once). → directly maps to CadVerify **batch**.
- **Share with collaborators** (view / edit / purchase permissions) from either the dashboard or the detail page → CadVerify **share/PDF**.
- **Dynamic search** across file name, PO#, order id, purchaser, owner, email → the search bar a real history/orders table needs.

Reputation: "smoother UI than competitors" — Fictiv competes partly on UX polish, confirming the funnel-archetype's design bar.

### 3.4 Geomiq — AI-OS framing

Sources: [geomiq.com](https://geomiq.com/), [Platform](https://geomiq.com/platform/), [Tech.eu profile](https://tech.eu/2025/07/02/how-geomiq-is-rewiring-custom-manufacturing-for-speed-and-scale/).

Drag-drop upload (STEP/STL/IGS/PDF/DXF/DWG) → **G-Quote** matches part to suppliers; simple parts instant, complex within 24h, **best-of-3 quotes** to choose from. **GeomiqOS** "interprets CAD, estimates pricing, evaluates manufacturability, suggests DFM improvements in seconds." A **tolerance configurator that lets you specify tolerances directly on the 3D model.** → the "annotate the requirement on the model" interaction is worth noting for CadVerify's label/requirement-capture flows.

---

## 4. Adjacent — manufacturing data / drawing intelligence

### 4.1 CADDi (Drawer / AI Data Platform)

Sources: [us.caddi.com](https://us.caddi.com/), [Product Overview](https://us.caddi.com/product-overview), [G2 reviews](https://www.g2.com/products/caddi-drawer/reviews), [GetApp](https://www.getapp.com/it-management-software/a/caddi-drawer/).

**Relevant patterns:** multi-modal **search (keyword / similarity / image)**, **find-similar drawings**, **diff two drawings**, **compare suppliers for a part**, **annotate drawings/docs**, and a **collaborative data warehouse** linking cost/defect/purchase history to each drawing. Enterprise integrations (**SAP, Oracle, Epicor, Plex**) and "secure access to sensitive data" are the procurement/IT trust signals. Brand UI = **blue/white, geometric, restrained** (consistent with the enterprise-credible palette norm). Reviewers repeatedly cite an **intuitive, easy-to-learn interface** as the adoption driver — a reminder that for enterprise tools, *learnability* is itself a competitive feature.

**CadVerify implication.** "Find similar parts you've already analyzed," "compare two parts," and **named ERP/PLM integrations on the marketing/IA** are credibility multipliers for the Zoox/Aramco buyer.

---

## 5. Synthesis — the category's design conventions (what "looks enterprise" here)

These recur across A/B/C and are the conventions CadVerify must satisfy to *not* read as a hobby tool:

1. **The 3-pane / quad screen grammar:** a **persistent 3D viewer**, a **configuration/decision panel**, an **issues/results list**, and **summary tiles** up top. aPriori's "summary tiles + detail panels + interactive charts + 3D" is the canonical statement of it.
2. **Live, persistent price + lead-time readout.** Always on screen, updates on every change (Xometry, Protolabs, Fusion "Get Estimate"). Never a separate "calculate" round-trip the user has to trigger and wait for.
3. **Two-way linked issue list ↔ 3D highlight.** Click an issue → the feature lights up on the model; problem geometry is highlighted at face/edge level; a transparency/ghost mode isolates it (Protolabs, DFMPro HD3D, Fusion Visual DFM).
4. **Named, two-tier severity** ("Required changes" vs "Advisories") instead of opaque scores (Protolabs). Pair each with a concrete measurement and a suggested fix (aPriori "system-generated fix instructions").
5. **Glass-box itemized cost breakdown** (material / machine / labor / tooling / setup), default-visible or one click away (3D Spark, aPriori, Siemens). The breakdown *is* the trust.
6. **Scenario / option comparison as a first-class screen** — process-vs-process, quantity-vs-quantity, quote-vs-quote, supplier-vs-supplier (3D Spark tech comparison, aPriori scenarios, Fictiv quote compare, Geomiq best-of-3).
7. **Sensible defaults / guided start, not empty forms.** Auto-recommend a process+material on upload; pre-fill; guided process selection (Xometry, aPriori).
8. **Pro-grade 3D viewer affordances:** orientation **ViewCube** (top-right corner, click face/edge/corner for ortho/iso views), orbit/pan/zoom, **section/cut plane**, **measure** (linear/angular/radial), **isolate/hide/show**, **explode** (assemblies), and **keyboard shortcuts**. These read as "real CAD tool." (ViewCube is an Autodesk-originated, now-universal convention.)
9. **Dense-but-disciplined data tables** for batch/history: right-aligned numbers, sticky headers, frozen identifier column, sortable + column filters + global search, **adjustable row density (compact/comfortable)**, expandable rows for breakdowns, **per-user persisted column state**, pagination at 25/50/100. (Stéphanie Walter; Siemens persisted-state.)
10. **Role-tiered views / progressive disclosure:** analyst-density working screen vs executive roll-up dashboard (5–9 KPIs); show the next decision first, reveal detail on demand. (Orbix/925/context.dev dashboard guidance; aPriori leadership dashboards.)
11. **Export-to-meeting everywhere:** every analysis exports to **PDF / Excel / management slide**. The screen is the truth; the export is the deliverable the engineer hands up the chain (3D Spark, aPriori).
12. **Restrained, credible visual identity:** blue/neutral palettes, few bold colors used as *signal* (semantic status), larger type for readability, modern app header — Siemens explicitly modernized *toward* "simple colors / larger fonts," CADDi/aPriori use blue/white restraint.
13. **Explicit trust artifacts:** named methodology ("physics-based," "deterministic," "engineered not estimated"), named process count ("18/400 simulations"), named integrations (SAP/Oracle/PLM), and — for IT/procurement — **SOC 2 Type II**, audit trails, access controls.

---

## 6. Concrete patterns CadVerify should adopt (mapped to its actual surfaces)

### 6.1 Global navigation shell & IA
- **Left sidebar = product sections** (primary wayfinding), **top bar = global utilities** (search, notifications, help/glossary, account/org, API). This sidebar+topbar split is the universal B2B-SaaS shell (Orbix). 
- Proposed top-level IA, consolidating today's "Frankenstein" surfaces into one product:
  - **Analyze** (upload → manufacturability dashboard) — the home/working surface.
  - **Decide / Cost** (`/cost`: process selection, cost breakdown, make-vs-buy, lead time) — reachable as a *tab on the same part*, not a disconnected page.
  - **Reconstruct** (image-to-mesh) — an *input method* that funnels into Analyze, not a sibling silo.
  - **Label** (ground-truth tooling) — a distinct mode, visually separated (it's an internal/expert surface), but sharing the same shell, viewer, and tokens.
  - **Library / History** (past parts, search "find similar," compare).
  - **Batch** (multi-part upload, bulk configure, table results).
  - **Developers / API keys**, **Settings/Org**.
  - **Share/PDF** is an action available on any part, not a nav item.
- **Anchor everything to "the part."** A part has tabs: *Analyze · Cost/Decide · Issues · History · Share*. This is the single most important IA move — today's pages should become tabs on one object. (Xometry's Configure/Analyze tabs on one quote is the model.)

### 6.2 The part workspace (Analyze + Cost) — screen layout
- **Layout:** left = **3D viewer (dominant)**, right = a **decision rail**, bottom or right-collapsible = **issues list**, top = **summary tiles + persistent price/lead-time/decision readout.**
- **Persistent header readout (always visible):** *Recommended process · Est. unit cost · Est. lead time · Make-vs-buy verdict · Confidence.* Updates live on any config change (Xometry/Fusion pattern).
- **3D viewer:** ViewCube top-right; orbit/pan/zoom; section plane; measure; isolate; **ghost/transparency mode** to spotlight problem features; **face/edge-level issue highlighting two-way-linked to the issues list**; keyboard shortcuts (views/measure/section). (Protolabs + ViewCube conventions.)
- **Issues list:** grouped **Required vs Advisory**; each row = icon + plain-language title + the **measured value** + the rule/threshold + **suggested fix** + "show on model." Configurable rule thresholds surfaced ("what we checked, at what limit") for glass-box trust (DFMPro Rule Manager).

### 6.3 `/cost` — the glass-box decision (CadVerify's signature, beat the category here)
- **Itemized cost breakdown** card: material / machine time / labor / setup / tooling-amortization, with a **"why this number" expandable** showing the driving geometry + rate assumptions. (aPriori/3D Spark itemization + Xometry inline glossary = the glass box.)
- **Make-vs-buy / mold-crossover chart — the hero visualization the category lacks as a *decision*:** a **cost-per-part (or total-cost) vs quantity line chart** with **two+ process curves** (e.g. CNC flat-ish line vs injection-molding curve = high fixed tooling, low marginal) and a **clearly marked crossover/breakeven point**, annotated with the breakeven quantity. Math the category uses: `breakeven units = tooling cost ÷ per-part savings`; typical crossover **500–2,000 units** (simple) to **2,000–5,000** (side-actions/tight tolerance) — use these as sane defaults/anchors. (Sources: Xometry, Printform, RapidDirect breakeven guides.) Let the user **drag a quantity slider** and watch the recommended process flip — this single interaction *is* the product's "aha."
- **Scenario comparison:** two processes (or two quantities) **side-by-side columns** — cost, lead time, manufacturability flags, CO₂. (3D Spark tech comparison / aPriori scenarios.)
- **Confidence / assumptions panel:** state inputs and uncertainty explicitly. This is how a fast tool earns trust against aPriori's "physics-based" claim — by being *transparent about what it assumed* rather than pretending to false precision.

### 6.4 Batch / History — disciplined data tables
- Table with: frozen **part-name/thumbnail** column; right-aligned numeric columns (unit cost, total, lead time, qty); **sortable + per-column filter + global search** (Fictiv dynamic search across name/PO/owner); **status chips** (semantic colors); **density toggle** (compact/comfortable); **expandable row** → cost breakdown inline; **per-user persisted column order/width/density** (Siemens); pagination 25/50/100; bulk-select → **bulk configure** (Fictiv BOM bulk config); **export to Excel/PDF**.
- **"Find similar" + "Compare selected"** actions (CADDi pattern) turn history from a log into an analysis tool.

### 6.5 Executive roll-up (History/portfolio top, or a Dashboard)
- 5–9 KPI tiles only (cost analyzed, avg savings vs baseline, parts flagged, lead-time saved, CO₂) each with **value + comparison delta + period + sparkline** (Orbix KPI tile spec). Read-only, screenshot-/PDF-ready for a Head of Manufacturing (3D Spark management dashboard).

### 6.6 Design tokens / visual system (concrete starting values)
> Treat as a starting scale to tune, grounded in the cited B2B-dashboard guidance + category visual norms. (Verify current Tailwind setup before implementing — token *values* below, not framework.)
- **Spacing:** 8px base grid; 16px card padding; 24px section gaps; 12px intra-group gaps.
- **Type scale:** Display 32px (page title) · Headline 24px (section) · Subhead 18px · Body 14–16px · Caption/label 12px. KPI value 28–32px. **Use a single, neutral, highly-legible sans** (the enterprise norm; Siemens moved *toward* larger fonts/readability). Tabular/monospaced figures for all numbers in tables and cost breakdowns so columns align.
- **Color:** neutral-dominant (off-white/light-gray backgrounds, dark-gray primary text, mid-gray secondary, light-gray borders); **one brand/primary** (a blue is the safe enterprise default — CADDi/aPriori/Siemens all blue-family) used sparingly for primary actions; **semantic set:** success/green, warning/amber, error/red, neutral/gray — reserved for *status and DFM severity only*, never decoration. Few bold colors, used as signal (Siemens "simple colors / better ratios").
- **DFM severity mapping:** Required = red, Advisory = amber, Pass = green/neutral — consistent everywhere (chips, 3D highlights, issue list, summary tiles).
- **Charts:** line for trend/breakeven; bar for category comparison; ≤2–3 series; clear legends; consistent color-per-series across screens; avoid pie/donut except simple composition. Reserve **heat map** for a cost-driver / risk overview (aPriori signature).
- **States:** design **empty** (guidance to upload first part), **loading** (skeleton + context message during analysis — analysis takes seconds, so a *progress with stages* — "parsing geometry → checking manufacturability → costing" — doubles as a glass-box reveal), **error** (red + recovery action; for upload, an inline "Revise Part Model" re-upload affordance à la Xometry).

### 6.7 Enterprise trust signals to build into the UI/IA (for Zoox/Aramco, IT & procurement)
- **Methodology transparency in-product:** "How we computed this" links; named approach ("deterministic, process-based — engineered, not estimated"); stated assumptions + confidence. This is *both* the glass-box product promise and the trust signal — they're the same feature.
- **Named breadth:** "N manufacturing processes," explicit process list (3D Spark "18," aPriori "400+").
- **Security/compliance surface:** a visible **trust/security page + SOC 2 Type II** badge — SOC 2 Type II is a *procurement gate*; for many enterprise buyers a missing report disqualifies the vendor outright (sources: Sprinto, Spinify, Drata). Surface **access controls, SSO/SAML, audit trail/activity log, data-residency** in Settings/Org.
- **Audit trail / activity history** on parts and analyses (who ran what, when, with which assumptions) — both a compliance control and a collaboration feature.
- **Named integrations** (PLM/ERP: Teamcenter/SAP/Oracle — CADDi-style) signal "fits our stack" to enterprise IT.
- **Sharing with permissions** (view/edit/purchase-equivalent) + PDF export with the org's branding (Fictiv).

---

## 7. The 3D Spark (design-engineer) vs aPriori (cost-engineer) contrast — and where CadVerify sits

| Dimension | 3D Spark (Archetype A) | aPriori / Siemens PCM (Archetype B) | **CadVerify target** |
|---|---|---|---|
| Primary user | Design/feasibility engineer, procurement | Cost engineer, sourcing analyst | **Design/mechanical engineer** |
| Time-to-answer | ~5 min, "instant" | Hours of setup; deep model | **Seconds–minutes, instant** |
| Screen DNA | 3D viewer + result panels + KPI dashboard | Bill-of-process **tables**, role dashboards, charts | **Viewer-first + decision rail (A), with B's itemized credibility** |
| Cost depth | Itemized but approachable | Bottom-up, machine/labor/tooling to the cell | **Itemized + glass-box "why," not editable-to-the-cell** |
| Config burden | Low — recommended defaults | High — model the factory | **Low — guided defaults, advanced optional** |
| Differentiator claim | "Engineered, not estimated"; tech comparison; CO₂ | "Physics-based"; 400 sims; should-cost authority | **"Glass-box explainable make-vs-buy decision"** |
| Visual register | Modern startup SaaS | Modern-but-dense enterprise | **Modern enterprise: A's clarity, B's restraint & trust** |

**Net:** CadVerify should *feel* like 3D Spark/Fusion (viewer-first, instant, low-ceremony, design-engineer-native) while *signaling* aPriori/Siemens-grade credibility through itemized glass-box breakdowns, named methodology, scenario comparison, persisted-state pro tables, and explicit security/trust artifacts. The make-vs-buy/mold-crossover **decision** — presented as an interactive breakeven chart with a quantity slider — is the differentiator none of them foreground as cleanly.

---

## 8. Traps to avoid (anti-patterns observed in the category)

1. **The aPriori/Siemens density trap.** Bill-of-process tables, 400-field configurators, cost-engineer mental models. Powerful, but it's exactly the "heavyweight opaque black box" CadVerify is positioned against. Keep advanced depth behind progressive disclosure; default to the engineer's decision, not the analyst's worksheet.
2. **CAD-plugin visual clutter (DFMPro/legacy).** Toolbars, modal-dialog stacks, tree-view-everything. CadVerify's edge is being a clean standalone web product — don't import plugin-era chrome.
3. **The "Frankenstein silo" trap (CadVerify's current state).** Analysis, /cost, /label, reconstruct, batch as disconnected pages with different layouts. Fix via **one shell, part-as-object with tabs, one design system.** Every competitor that feels coherent anchors to a single object (a quote/part) with tabs.
4. **False precision without transparency.** A fast tool that emits a confident single number with no breakdown reads as a *toy* to a Head of Manufacturing and as *untrustworthy* to procurement. The breakdown + assumptions + confidence is mandatory; it's how you out-trust the heavyweights despite being fast.
5. **Empty-form cold start.** Don't drop the user into a blank process/material configurator. Recommend, pre-fill, guide (Xometry/aPriori).
6. **Text-only DFM.** A list of issues with no 3D highlight is a regression vs the entire category. Face/edge highlight + ghost mode is table stakes.
7. **Opaque severity scoring.** A "manufacturability score: 72/100" means nothing to an engineer. Use **Required vs Advisory** + measured value + fix (Protolabs).
8. **Decorative color / chart soup.** Semantic colors only; ≤3 series per chart; 5–9 KPIs max. Density where it earns its keep (tables), calm everywhere else.
9. **Mobile-cramming the analyst surface.** Use mobile/compact only for executive roll-ups; the working analysis screen is a desktop, data-dense tool (context.dev/925 guidance). Don't strip the working screen's density to fit a phone.
10. **Burying the decision.** The make-vs-buy verdict and the price/lead-time must be *persistent and top-level*, not the payoff at the end of a scroll.

---

## 9. Source reachability notes

- **Reachable & useful:** all vendor marketing/help pages cited, Tech-Clarity (aPriori), Siemens Teamcenter blog "what's new" posts, Stéphanie Walter data-tables resource, Orbix B2B dashboard guide, breakeven-analysis guides (Xometry/Printform/RapidDirect), SOC 2 references (Sprinto/Spinify/Drata), ViewCube/CAD-viewer convention sources.
- **Limitation (important):** real product UIs sit behind login/demo, and most vendor pages describe **function over pixels**. Hard visual specifics (exact hex, type families, literal layouts) are largely **inferred from feature copy + cross-product convention + the cited design-system guidance**, and labeled `[inferred]` where so. The strongest *stated* visual-direction evidence came from **Siemens' "what's new" posts** (simple colors, larger fonts, persisted table state, inline validation) and **aPriori's stated "summary tiles + detail panels + charts + 3D + heat maps"** vocabulary — both load-bearing for sections 5–6.
- **CASTOR:** intentionally light here (positioned-against, additive-first); not researched in depth per brief.
- **Could not retrieve literal screenshots** (no image capability in this environment); "screens described" are documentation-reconstructed.

### Full source list
- 3D Spark: https://www.3dspark.de/ · https://www.3dspark.de/3d-spark-part-screening · https://www.3dspark.de/engineering-hub · https://www.softwareadvice.com/scm/3d-spark-profile/ · https://www.capterra.com/p/10014404/3D-Spark/ · https://www.3dnatives.com/en/3dstartup-3d-spark-060620234/
- aPriori: https://www.apriori.com/ · https://www.apriori.com/manufacturing-insights/ · https://www.apriori.com/digital-factories/ · https://www.apriori.com/solutions/roles/design-engineering/ · https://www.apriori.com/cad-to-cost/ · https://tech-clarity.com/apriori/23198
- Siemens Teamcenter PCM: https://www.siemens.com/en-us/products/teamcenter/solutions/product-cost-management/ · https://blogs.sw.siemens.com/teamcenter/whats-new-in-teamcenter-product-cost-management-version-2512/ · https://blogs.sw.siemens.com/teamcenter/teamcenter-product-cost-management-whats-new/ · https://blogs.sw.siemens.com/teamcenter/teamcenter-product-cost-management-news/
- Paperless Parts: https://www.paperlessparts.com/quote-workflow-management/ · https://www.paperlessparts.com/ · https://www.paperlessparts.com/manufacturing-software/ · https://www.softwareadvice.com/cpq/paperless-parts-profile/ · https://www.g2.com/products/paperless-parts/reviews
- Xometry: https://www.xometry.com/how-xometry-works/ · https://www.xometry.com/quoting/home · https://www.xometry.com/resources/blog/quote-configuration-update/ · https://www.xometry.com/machine-learning-for-manufacturing/ · https://xometry.eu/en/instant-quoting-engine/ · https://www.xometry.com/cad-add-ins/
- Protolabs: https://www.protolabs.com/resources/design-tips/navigating-manufacturing-analysis/ · https://www.protolabs.com/online-quoting-and-manufacturing-analysis/ · https://www.protolabs.com/en-gb/automated-design-analysis/ · https://www.protolabs.com/help-center/quoting-platform/ · https://www.3printr.com/protolabs-launches-prodesk-instant-quotes-with-ai-driven-dfm-for-3d-printing-cnc-and-injection-molding-0286963/
- Fictiv: https://www.fictiv.com/our-platform · https://www.fictiv.com/articles/fictiv-made-online-platform-quote · https://www.fictiv.com/articles/welcome-to-our-next-generation-quotes-experience · https://www.fictiv.com/help/getting-started/how-to-get-started-with-fictiv
- DFMPro / HCL: https://dfmpro.com/ · https://dfmpro.com/about-dfmpro/ · https://dfmpro.com/cad-systems/dfmpro-nx/ · https://dfmpro.com/cad-systems/dfmpro-for-solidworks/ · https://hclsoftwareu.hcltechsw.com/dfmpro
- Autodesk Fusion: https://www.autodesk.com/products/fusion-360/design-for-manufacturing · https://www.autodesk.com/products/fusion-360/blog/xometry-add-in-fusion-360/ · https://www.autodesk.com/products/fusion-360/blog/instant-dfm-pricing-feedback-proto-labs/ · https://help.autodesk.com/view/fusion360/ENU/?guid=GD-COSTING
- CADDi: https://us.caddi.com/ · https://us.caddi.com/product-overview · https://www.g2.com/products/caddi-drawer/reviews
- Geomiq: https://geomiq.com/ · https://geomiq.com/platform/ · https://tech.eu/2025/07/02/how-geomiq-is-rewiring-custom-manufacturing-for-speed-and-scale/
- Cross-cutting UX / tokens: https://stephaniewalter.design/blog/essential-resources-design-complex-data-tables/ · https://www.orbix.studio/blogs/saas-dashboard-design-b2b-optimization-guide · https://www.925studios.co/blog/saas-dashboard-design-examples-2026 · https://www.context.dev/blog/dashboard-design-best-practices
- 3D viewer conventions: https://www.research.autodesk.com/app/uploads/2023/03/viewcube-a-3d-orientation.pdf_recsg8BsEjf1BeIbZ.pdf · https://cad.onshape.com/help/Content/View/view_navigation_and_the_view_cube.htm · https://help.cadrooms.com/exploring-section-views-and-exploded-views/ · https://modelviewer.dev/
- Make-vs-buy / breakeven: https://www.xometry.com/blog/3d-printing-vs-injection-molding-breakeven/ · https://printform.com/cnc-machining-vs-injection-molding-cost-lead-time-and-volume-tradeoffs/ · https://www.rapiddirect.com/blog/injection-molding-costs/
- Enterprise trust / SOC 2: https://sprinto.com/blog/why-soc-2-for-saas-companies/ · https://spinify.com/blog/why-soc-2-type-ii-is-the-gold-standard-for-saas-trust-and-security/ · https://drata.com/learn/soc-2/overview
