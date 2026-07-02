# CadVerify — Platform IA & Design Vision

## The Decision Catalog: a governed lakehouse of manufacturing decisions

**Status:** Definitive design vision. Chosen spine + grafts from three competing visions ("Decision Catalog," "Decisions — the governed graph," "Datum — command workspace"). This supersedes the *look* of the single-part "Living Instrument / Bold Industrial Confidence" identity and keeps every piece of its substance (role lens, provenance atom, honest confidence, per-shop calibration, make-vs-buy crossover, the real `report_to_dict` bindings).

---

## 0. The judgment (why this spine, in one table)

Scored 0–100 on the six bars. Vision 3 self-scored 0–10; normalized ×10 for comparison.

| Bar | V1 Decision Catalog (lakehouse) | V2 Decisions (ontology + lifecycle) | V3 Datum (command workspace) |
|---|---|---|---|
| Enterprise-viable | **95** — namespace-as-home reads as system-of-record on arrival | 93 — queue framing is operational gravitas | 90 — command-first has a discoverability tax for execs |
| Efficient | 90 — grid + ⌘K + saved views | 88 — five queues + inbox is more surface | **100** — ⌘K spine is the point |
| Beautiful | 88 — dense-catalog beauty is quieter | **90** — lineage-DAG motion is earned | 90 — restraint risks reading austere |
| Manufacturing-credible | 90 | **91** — lifecycle mirrors how sourcing actually works | 90 |
| Buildable-incrementally | 86 — most net-new grid work | **89** — reuses shipped substance | 90 |
| Coherent w/ Databricks×Palantir×Linear | **95** — literal lakehouse = the North Star | 88 — leans Palantir | 90 — leans Linear |

**Verdict: V1 "Decision Catalog" is the spine.** It is the *most literal, most on-thesis* rendering of the founder's North Star — *"Databricks for manufacturability & cost… portfolio catalog = lakehouse."* It scores highest on enterprise-viability and blend-coherence, and — decisively — it is the only spine whose **home surface IS what W1 ships** (the tenant-scoped governed catalog). Building the catalog first is not a phase we bolt navigation onto later; the catalog *is* the navigation. That makes it the cleanest incremental path and the sharpest break from the current "you always hold exactly one part" single-persona shell.

V2 and V3 are not losers — they hold the two ideas V1 under-weights, and both graft cleanly onto the lakehouse spine (see §1).

---

## 1. The organizing big idea + why it wins

### The big idea

> **The home is not a dashboard and not a part — it is a governed catalog of manufacturing decisions you browse, filter, and roll up like a lakehouse table.** Parts, estimates (decisions), materials, processes, shops, and rate-libraries are first-class datasets in a three-level namespace — `Workspace ▸ Program ▸ Part ▸ Estimate` reads exactly as `catalog.schema.table`. The deterministic engine is **compute**. Provenance is **column-lineage**. Honest confidence is **data quality**. The portfolio is a **`GROUP BY` roll-up of the very same rows**. Every persona works over this one catalog through a saved-view lens, drills a row into a stateful decision object, and can trace any number back to the exact governed asset versions that produced it.

Unity Catalog Explorer married to a Foundry object workspace, rendered at Linear's craft bar — but the object at the center is a *manufacturing decision*, not a data table.

### Why it wins the six bars

- **Enterprise-viable on arrival.** The namespace breadcrumb, RBAC-scoped catalog, versioned governed assets, lineage/audit, and a visible data-locality badge are exactly what an Aramco/Zoox IT buyer reads as "system of record" in the first three seconds — before they've run anything. The other two visions signal trust *after* you engage (open a queue, hit ⌘K); the catalog signals it on load.
- **Coherent with the blend.** It is the literal lakehouse (Databricks catalog + column-lineage), hosting a Foundry-style object workspace (Palantir), at Linear's restraint. No strand is decorative; each owns a surface (§5).
- **Buildable incrementally.** The catalog is W1. Everything else is a *projection* of it: a role home is a saved view, the portfolio is a `GROUP BY`, a decision is `SELECT … LIMIT 1`, lineage is column-derivation. You build one grid and one object frame, then add schemas and roll-ups as the walls land — never a rewrite.
- **Manufacturing-credible.** Route-scoped DFM, per-shop calibration, honest confidence, real process ontology, and should-cost-vs-quote variance all reflect the shipped engine (`breakeven.ts`, `cost-views.ts`, `dfm-scope.ts`, `status.ts`).

### What was grafted from the runners-up

**From V2 "Decisions — the governed graph" (the operational corner):**
- **Lifecycle state as a first-class column** on every Decision, not a separate spine: `Drafted → Costed → Calibrated → In review → Sourced → Quote-returned → Award-ready → Awarded → Validated`, plus two interrupt flags surfaced as alerts — **DFM-blocked** and **Crossover-flipped**. Because state is just another catalog column, filtering/grouping the catalog by state gives you V2's queues *for free* — without making a five-queue state machine the whole architecture.
- **The Sourcing Decision Inbox** as the sourcing persona's home: the same catalog, grouped by lifecycle state, rendered as a triage inbox with "who is waiting on you." This is the single surface no incumbent serves neutrally, and it's V2's best surface.
- **Ontology rigor.** The nine linked object types and "edges = lineage" discipline give the lineage DAG and the governance model their backbone.

**From V3 "Datum — command workspace" (the speed corner):**
- **⌘K as a co-primary navigator** with four verbs — jump / run / go / create — not a garnish. The catalog is the map; ⌘K is the teleport.
- **Saved Views as the primary catalog-navigation primitive** (Linear-style pinned filtered queries). A role home is literally a curated Saved View; this is the mechanism that makes personas cheap.
- **`Space`-to-peek** any object from any list without leaving it, and **optimistic client-side re-cost** ("instant reads as *it knows*").
- **The resolved inspector tradeoff:** V3 honestly flagged that a *summoned* inspector hurts the all-day cost engineer. We resolve it: the Inspector is **resident-by-default for the cost lens, summonable (press `L`/`G`) for the others** — a per-lens property, not a global choice.

The three visions already agreed on ~90% of the design system (shell dimensions, graphite+cobalt, provenance tiers, Geist type, motion). The real decision was the *spine*; the grafts add the operational queue (V2) and keyboard speed (V3) that a pure catalog would miss.

---

## 2. The IA spine — the Catalog IS the home; everything else is a projection of it

### The persistent shell (one shell, four zones)

```
┌ 56 ┬──── 240 ────┬──────────────────── primary region ──────────────────┬─ 340 ─┐
│icon│  sidebar    │  ┌ 48  context bar: namespace breadcrumb + lens ┐     │Inspec-│
│rail│  (collapses │  └───────────────────────────────────────────────┘   │ tor   │
│    │   to rail)  │  data surfaces full-fluid · decisions cap 1200px      │(resiz-│
│    │             │  prose ~72ch                                          │ able) │
└────┴─────────────┴───────────────────────────────────────────────────────┴───────┘
```

- **Icon rail (56):** the object domains you fly between. Always visible.
- **Sidebar (240, collapsible to rail):** within a zone — object lists, **Saved Views** (`★ pinned queries`), **Libraries** nested under Catalog. Queue counts live here ("Crossover 6 · Quotes back 9 · Awards 3").
- **Context bar (48):** the lakehouse breadcrumb `workspace ▸ program ▸ part ▸ estimate` — the single cheapest "governed platform" signal — plus the **Role Lens ▾**, the **Calibrated: <shop> ▾** pill, and Share.
- **Inspector (340, resizable 300–420):** the reframed glass box. Tabs `Lineage · Governance · Sources · Audit`. **Resident** for the cost lens; **summonable** (`L`/`G`, or click any number) for others. Replaces the retired `GlassBoxDrawer`.
- **⌘K:** co-primary navigator — *jump* (any object), *run* (override rate, calibrate, compare, export, switch lens), *go* (`G C` Catalog / `G P` Portfolio / `G Q` Quotes / `G V` Governance / `G H` Home), *create*.

### L0 — Org / workspace root (W1)
Org switcher binds all data to a tenant namespace. The breadcrumb is always live.

### L1 — Icon-rail zones (top-level object domains, catalog-forward order)
- `◱ Home` — the role home, which is literally a **Saved View over the Catalog** (not a separate app).
- `▤ Catalog` **(default landing / product home)** — one browser, schema tabs: **Parts · Decisions · Materials · Processes · Shops · Rate libraries**. This is the lakehouse table.
- `◫ Portfolio` — Savings / cost-down board · Batch runs · Portfolio analytics (W3). A `GROUP BY` over the Catalog; every aggregate drills back to rows.
- `⇄ Sourcing` — RFQ builder/list · Quote intake & compare vs should-cost · Award/PO handoff (W2/W5).
- `⚙ Calibration` — per-shop calibration workbench · validation/flywheel (DONE, feeds W5).
- `§ Governance` — Change requests/approvals · Lineage explorer · Audit log · Access/namespace policy · Publishing & effective-dating (W1/W4/W5).
- `⇡ Connect` — Connector catalog · Sync monitor · Field mapping/dedupe · Historical-quote import (W2). Admin/IT-scoped.
- `⟩ Develop` + account — API keys · Docs.

### L2 — The object workspace (open any Catalog row)
A part-decision opens as a stateful object with tabs: **Decision · Routing & DFM · Glass Box · Compare · History**. Library objects (material/process/shop/rate-library) open to an asset-detail object: **Overview · Versions · Usage/dependents · Lineage**. The Inspector rides alongside every L2. This revives the orphaned Gen-2 `PartWorkspace` as the universal object frame.

### L3 — Universal inline drill-down
Every number, in every grid/chart/card, is clickable → Inspector ▸ Lineage. Show-your-work becomes see-the-graph; nothing hides behind a slide-out drawer.

### How it nests (the lakehouse metaphor, literally)
- **Catalog** = `SELECT * FROM parts` with facets → **Saved Views** are the persisted queries (a role home is a curated Saved View).
- **Portfolio** = `SELECT program, SUM(savings) … GROUP BY` over the same grid.
- **Part Decision** = `SELECT * WHERE part=… LIMIT 1` → object workspace.
- **Lineage** = column-level derivation of the selected cell.
- **Lifecycle state** = a governed column on every Decision → filtering by it yields the persona queues.
- **RBAC/namespace grants** scope which schemas/rows a member can read or edit (W1).

---

## 3. Per-persona HOME surfaces (all Saved Views over the one governed catalog)

Every home is a **Saved View over the one Catalog** — a pre-filtered, pre-columned grid plus a thin KPI strip and the role's default density/disclosure. The Role Lens (from `role-lens.tsx` `ROLES`, graduated from a topbar toggle to the landing experience, derived from `user.role`/SSO) re-lands you; nothing is walled off — real people wear several hats in a sitting.

### Cost / Sourcing engineer — "Ledger" (verb: override & audit · compact · glass-box open · Inspector resident)
Lands on the **Catalog grid itself**, front-and-center — Parts × Decisions × Shops with **provenance micro-bars inline** in every cost cell. Pinned Saved Views: `★ My override queue` (DEFAULT-heavy drivers on high-spend parts), `★ Most-divergent driver watchlist` (the negotiation levers — e.g. `machine_rate Δ+38% Midwest▸Shenzhen`), `★ Compare A/B`. The catalog-first persona; the grid is their workbench, not decoration. Opening a row lands on **Glass Box** — a dense, inline-editable driver table with `Σ = unit_cost` as a coherence row. Binding a shop or rate library is a bulk action from here — the moat is built at this seat.

### Design / Manufacturing engineer — "Bench" (verb: tweak / verify routing · comfortable-airy · glass-box collapsed)
Lands answer-first on a **narrow Saved View** — "My parts" + a prominent **New analysis** dropzone (STEP drag → decision in seconds, zero onboarding). Columns favor Verdict and Route over dollars; the **Flagged DFM** list is scoped to *my parts* via `dfm-scope.ts` (the honest scoped count, not the scary 58-flag headline). Opening a row lands `design` on **Decision** (the answer-first render — the re-hosted Living-Instrument beauty as one tab), `mfg` on **Routing & DFM** (findings scoped to the recommended route, two-way face↔issue linked to the 3D part).

### Procurement / Program lead — "Portfolio" (verb: trust & approve · relaxed)
Lands on the **Portfolio roll-up** — a `GROUP BY` view of the catalog: realized vs potential savings, coverage %, and the **governance posture** stacked bar (validated / calibrated / assumption counts, rendered verbatim from `confidence.validated`, never a fabricated ±%). A ranked cost-down board where each opportunity has an owner + a lifecycle state, and every headline number drills back to its drivers. Exec/Sponsor gets the same roll-up in Relaxed density, export-to-deck ready.

### Sourcing / Procurement buyer — "Inbox" (verb: compare / decide / award · grafted from V2)
The true operational surface: a triage **Decision Inbox** — the same catalog grouped by lifecycle state. **Crossover-flipped** alerts (buy just passed make at the current volume), **RFQs out** (waiting on shops, nudgeable), **Quotes returned** (variance-to-should-cost surfaced, one click to compare), **Award-ready** (quote within band → award → PO handoff). A neutral should-cost sits as the *datum* beside every returned quote. No incumbent serves this buyer neutrally.

### Steward / Admin / IT — "Registry" (verb: approve / publish / effective-date)
Lands on a Saved View of the **governance backlog** as a grid: pending change-requests, stale/expiring rate-libraries, calibration drift, connector sync health — same chrome, different schema. The change-request review carries a version diff and a downstream-impact count ("47 live Decisions consume this rate card").

---

## 4. The HERO surfaces (ASCII wireframes)

**Legend (used throughout):** Provenance `◆`SHOP (bronze, the moat) · `●`MEASURED (teal) · `◑`USER (indigo) · `◌`DEFAULT (hollow graphite = "a guess"). Verdict `●`Pass · `▲`Advisory · `■`Required (always icon+label, never color-only). Posture fill: filled = grounded, hollow = guess. **Cobalt = the one accent.** Rail: `▣`mark `◱`Home `▤`Catalog `◫`Portfolio `⇄`Sourcing `⚙`Calibration `§`Governance `⇡`Connect.

### HERO 1 — Org/workspace shell + Catalog Explorer (the home; the lakehouse grid)
```
┌─56─┬──── 240 sidebar ───┬──────────────────────────────────────────────────────────────────────────┐
│ ▣  │ ⌘K search catalog… │ acme-mfg ▸ EV-NPI ▸ parts          Lens: Cost eng ▾   ★ Saved views ▾  ⇄  │ ←ctx 48
│ ◱H │                    ├──────────────────────────────────────────────────────────────────────────┤
│▤Cat│ WORKSPACE          │ Parts · Decisions · Materials · Processes · Shops · Rate libraries          │ ←schema tabs
│ ◫P │  + New analysis    │──────────────────────────────────────────────────────────────────────────│
│ ⇄S │  Batch run         │ 1,284 parts  ⌕filter  ⚑DFM Required(37)  Σposture ▓▓▒░  [Compact▾] [cols▾] │
│ ⚙Cal│ CATALOG           │┌──┬──────────────┬─────────┬──────────┬─────────┬────────────┬──────────┐│
│ §Gov│ ▸EV-NPI    (842)   ││▤ │ Part ▸rev    │ Route   │ Unit $   │ Δ vs buy│ Provenance │ State    ││
│ ⇡Con│ ▸Chassis   (311)   │├──┼──────────────┼─────────┼──────────┼─────────┼────────────┼──────────┤│
│     │ ▸Powertrain(131)   ││◰ │ bracket_v3   │ CNC 3ax │ $ 42.18 ⊕│ −$310/u │▓▓▓▒ ◆SHOP  │● Costed  ││
│ ───│ SAVED VIEWS         ││◰ │ housing_r2   │ IM      │ $  8.04 ⊕│ +$1.9k↑ │▓▓░░ ◌DEFAULT│▲ DFM-blk ││
│ ᴀᴄ │ ★My override queue  ││◱ │ manifold_a1  │ CNC 5ax │ $118.90 ⊕│ −$44/u  │▓▒░░ mixed  │◐ In RFQ  ││
│    │ ★Cost-down top 50   ││◰ │ shaft_88     │ Turning │ $ 12.55 ⊕│ break@1k│▓▓▓▓ ◆SHOP  │✓ Validated││
│    │ ★Compare A/B        ││  │ … rows 25/50/100                                       1,280 more ↓ ││
└────┴────────────────────┴┴──┴──────────────┴─────────┴──────────┴─────────┴────────────┴──────────┴┘
   selected 3 →  [ Compare ]  [ Send to sourcing ]  [ Export ]  [ Add to batch run ]
```
Frozen identifier column + 3D thumbnail · right-aligned tabular-mono numerics · `⊕` expands a row to its inline driver breakdown · the **provenance micro-bar** (`▓▓▓▒`) shows each number's SHOP/MEASURED/DEFAULT mix so governance posture is legible at catalog scale · the **State** column (grafted from V2) makes the catalog filterable into any persona queue · layout persists per-user (the Siemens PCM credibility move). Every row → Decision workspace; every number → Lineage.

### HERO 2 — Part Decision workspace (the crossover is the hero interaction; the "aha")
```
┌ acme ▸ EV-NPI ▸ bracket_v3.step ▸ estimate@v3   Lens Cost ▾  Calibrated: Midwest CNC ▾  ⇄ ⤓Export▾ ┐  Inspector 340 →
│ Decision │ Routing & DFM │ Glass Box │ Compare │ History │                    ◧Lineage Governance Sources│
├────────────────────────────────────────────────────────────────────────────┤ Σ posture ▓▓▓▒ 3 tiers  │
│  RECOMMEND   Make · CNC 3-Axis                                               │ 19 SHOP·4 MEAS·6 DEFAULT │
│                                                                              │ ── this number ──────────│
│    $42.18 /unit    data-quality: calibrated ▓▓▓▒  (no fabricated ±%)         │  unit_cost  $42.18       │
│    at qty 500                                                                │   = Σ drivers            │
│  ┌ make-vs-buy ─────────────────────────────────────────────────────────┐   │   volume 41.2cm³ ●MEASURE│
│  │$/u  \                              _____ buy (Shenzhen)               │   │   material $6.10 ◆SHOP   │
│  │      \___ make (CNC) _____________/    ◆ crossover ≈ 1,962 units      │   │   machine  $22.4 ◆SHOP   │
│  │            ● qty 500       10   100   1k    10k  (log)                 │   │   setup    $8.90 ◆SHOP   │
│  └──────────────────[ ◀────────●──────────▶ ]  qty 500 ──────────────────┘   │   tooling  $1.20 ◌DEFAULT│
│  Below 1,962 make in-house · above, buy. Divergent driver: setup amortization│  ────────────────────────│
│  [ Save scenario ]   [ Send to sourcing ]   [ Override a rate ]              │  [ Open lineage graph ]  │
│                                                                              │  data-locality LOCAL ✓   │
│                                                                              │  zero egress · CAD-as-IP │
└──────────────────────────────────────────────────────────────────────────────┴──────────────────────────┘
```
The draggable quantity slider (backed by `breakeven.ts` `posToQty`/`recommendAt`) live-flips the recommendation at the breakeven — the single "aha" no incumbent ships. Re-costs client-side instantly ("it knows"). Confidence renders as an honest data-quality track, never a made-up percentage. The Living-Instrument beauty (studio-lit part, monumental readout, the scrubber, the resolve sequence) survives here as the Design lens — re-hosted in flat platform chrome, no bloom/well/halo.

### HERO 3 — Glass Box + Lineage Inspector (provenance as infrastructure, not a drawer)
```
┌ …▸ bracket_v3 ▸ estimate ▸ Glass Box ────────────────────────────┬ Inspector ▸ LINEAGE ────────────────┐
│ Driver table   (Σ = unit_cost, always visible)                    │ directed derivation graph            │
│┌───────────┬────────┬──────────┬────────────┐                     │  [geometry.step]                     │
││ Driver    │ Value  │ Rate     │ Source      │                    │     │ volume 41.2cm³  ●MEASURED       │
│├───────────┼────────┼──────────┼────────────┤                     │     ▼                                │
││ material  │ $ 6.10 │ 4.10 $/kg│ ◆SHOP  edit │                    │  [material 6061-T6] ◆SHOP           │
││ machine   │ $22.40 │ 78 $/hr  │ ◆SHOP  edit │                    │     │  Midwest Q2 accounting export  │
││ setup     │ $ 8.90 │ 0.31 hr  │ ◆SHOP  edit │                    │     ▼        ▼                       │
││ tooling   │ $ 1.20 │ generic  │ ◌DEFAULT ✎  │                    │ [machine_cost] [setup_cost]         │
││ finishing │ $ 3.58 │ 12 $/hr  │ ◑USER  edit │                    │      \        /                     │
│├───────────┼────────┼──────────┼────────────┤                     │       ▼      ▼                       │
││ Σ unit    │ $42.18 │          │ ▓▓▓▒ mixed  │                    │   [ Σ unit_cost $42.18 ]            │
│└───────────┴────────┴──────────┴────────────┘                     │   ◌ tooling node hollow=ungoverned  │
│ ◌ hollow = DEFAULT ("we're guessing here")                        │ Governance posture ████████░░ 8/11  │
│ Override a cell → re-tags USER → re-runs live, logged to Audit.    │ 🔒 IP-local · zero egress · audited  │
└───────────────────────────────────────────────────────────────────┴──────────────────────────────────────┘
```
This is Databricks column-lineage / Foundry ontology applied to a should-cost — the same receipts as the old `GlassBoxDrawer`, expressed as infrastructure (DAG + posture + source string + locality badge). Filled = grounded, hollow = a guess; the gaps are visible, not hidden. Nobody put lineage on a *cost decision*.

### HERO 4 — Portfolio / Savings roll-up (`GROUP BY` over the catalog; every aggregate drills to rows)
```
┌ acme ▸ EV-NPI ▸ portfolio ───────────────────── Lens Program lead ▾   ⤓ Export deck ────────────────────┐
│ Realized $2.4M   Potential $6.1M   Coverage 74%   Governance ▓▓▓▒ (validated 41% · calibrated 33% · assume 26%)│
│ ┌ savings realized▸potential ┐ ┌ cost distribution ┐ ┌ driver heatmap (cost-down levers) ───────────┐    │
│ │ ▁▂▃▅▆█ by quarter          │ │ ▁▃▅█▅▃▁ by $/unit  │ │ setup ▓▓▓   material ▓▓   finishing ▓         │    │
│ └────────────────────────────┘ └───────────────────┘ └───────────────────────────────────────────────┘    │
│ Cost-down opportunities (ranked)                                    Batch ⧉ EV-NPI #42 · 10,412 · ✓ [New run]│
│┌──────────────┬────────┬─────────┬───────────┬───────────┬─────────┬───────────────┐                       │
││ Part ▸rev    │ Now $  │ Target $│ Δ savings │ Lever     │ Owner   │ State         │                       │
│├──────────────┼────────┼─────────┼───────────┼───────────┼─────────┼───────────────┤                       │
││ housing_r2   │  8.04  │  5.90   │ $214k/yr ▓│ re-route  │ J. Vane │ ◐ In sourcing │                       │
││ manifold_a1  │ 118.90 │  96.00  │ $88k/yr  ▓│ shop swap │  —      │ ○ Unassigned  │                       │
││ bracket_v3   │  42.18 │  39.10  │ $31k/yr  ░│ qty>break │ A. Cruz │ ✓ Realized    │                       │
││ … every $ drills back to its drivers (click)                                          1,281 more ↓        │
│└──────────────────────────────────────────────────────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
aPriori/3D Spark roll up to *opaque* aggregates. Here every headline number drills back to its provenance, the posture bar states confidence honestly (no fabricated ±%), and each opportunity carries an owner + a lifecycle state — the roll-up is still a decision queue.

### HERO 5 — Quote / RFQ compare vs should-cost (the ground-truth flywheel closes here)
```
┌ acme ▸ EV-NPI ▸ sourcing ▸ RFQ-0143 ──────────── Lens Sourcing ▾   [ Award ]  ⤓ PO payload ──────────────┐
│ 4 parts · 3 shops invited · 2 responded            should-cost basis: Midwest CNC (calibrated)            │
│┌──────────────┬────────────┬──────────────┬──────────────┬──────────────┬──────────────────────┐          │
││ Line         │ Should-cost│ Midwest CNC  │ Shenzhen Co  │ Precision LLC│ Variance vs should-cost│         │
│├──────────────┼────────────┼──────────────┼──────────────┼──────────────┼──────────────────────┤          │
││ bracket_v3   │ $42.18 ▓▓▓▒│ $44.90 (+6%) │ $38.10 (−10%)│  no bid      │ Shenzhen ↓ = lever    │         │
││ housing_r2   │ $ 8.04 ▓▓░░│ $ 9.10 (+13%)│ $ 7.80 (−3%) │ $ 8.40 (+4%) │ within band           │         │
││ manifold_a1  │ $118.90▓▒░░│ $131.0 (+10%)│  no bid      │ $124.0 (+4%) │ ⚑ investigate DEFAULTs│         │
││ shaft_88     │ $12.55 ▓▓▓▓│ $12.40 (−1%) │ $13.90 (+11%)│ $12.60 (0%)  │ ✓ matches model       │         │
│├──────────────┼────────────┼──────────────┼──────────────┼──────────────┼──────────────────────┤          │
││ bundle       │ $181.7     │ $197.4       │  —           │  —           │ awarding → validates  │         │
│└──────────────┴────────────┴──────────────┴──────────────┴──────────────┴──────────────────────┘          │
│ Awarding a quote links it to the part as ground-truth → validates/promotes the calibration profile (W5).   │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
A neutral should-cost sits as the *datum* beside every returned quote; the most-divergent driver is the negotiation lever. Awarding closes the flywheel: the returned quote becomes ground truth, and the decision's lifecycle advances to `Validated`.

### HERO 6 — Governance / Change-request / Lineage explorer (governance-over-time)
```
┌ acme ▸ EV-NPI ▸ governance ─────────────────────────────────── Lens Steward ▾   ⇄ ─────────────────────┐
│ CHANGE REQUESTS (4)   LINEAGE EXPLORER   AUDIT LOG   ACCESS POLICY   PUBLISHING & EFFECTIVE-DATING       │
├──────────────────────────────────────────────────────────────────────────────────────────────────────┤
│┌ pending change ─────────────────────────────────────────┐┌ downstream impact ────────────────────────┐│
││ RateLib "Midwest CNC" v12 → v13    proposed by J. Ruiz   ││ 47 live Decisions consume this rate card  ││
││ ─ diff ─────────────────────────────────────────────────││  ▸ 12 in EV-NPI · 31 Chassis · 4 Powertrain││
││  machine_rate   $78/hr  →  $82/hr   (+5.1%)              ││ est. portfolio cost impact: +$71k/yr      ││
││  setup_rate     0.31hr  →  0.29hr   (−6.5%)              ││ ─ effective-date ─────────────────────────││
││ ─ review ───────────────────────────────────────────────││  ○ immediate  ● pin 2026-07-15  ○ schedule││
││  [ Approve & publish ]  [ Request changes ]  [ Reject ]  ││  affected Decisions re-cost on publish     ││
│└──────────────────────────────────────────────────────────┘└────────────────────────────────────────────┘│
│ AUDIT · who changed/ran/exported what · immutable · searchable · exportable                              │
│  ✎ A.Cruz overrode setup_rate on bracket_v3 → USER   2h ago   ↥ v12 published   9d ago                   │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
Change → review → publish → effective-date, with a downstream-impact count and version diff. Rate/material/shop libraries are first-class versioned assets; publishing re-costs the Decisions that consume them. This is Foundry's governance grammar applied to a manufacturing rate card.

---

## 5. Design-system direction — the Databricks × Palantir × Linear blend

### The one move
Stop looking like a **glowing gauge in a dark cockpit**; start looking like a **governed catalog**. Cool the neutrals, kill the decorative depth, put the data-grid at the center. The reframe converts the "show-your-work gimmick" into platform substance: the glass-box drawer becomes a **lineage graph + governance panel**; provenance tags become **data-source governance chips**; the honest confidence band becomes a **data-quality indicator**. The receipts stay — they stop being theatrical and start being infrastructural.

**What each strand contributes (and where it wins the tie-break):**
- **Databricks (lakehouse-technical)** — owns the catalog grid, the column-lineage DAG, the three-level `catalog.schema.table` breadcrumb, and light-mode dense-table readability.
- **Palantir Foundry (operational)** — owns the dark command register, the three-pane object workspace, density/gravitas, and the decision-queue framing.
- **Linear/Vercel (minimal)** — wins every tie-break on color discipline, 13px type, hairline borders, ⌘K, and functional motion.

### Layout & density
Persistent 4-zone shell — rail 56 · sidebar 240 (collapsible to rail) · context bar 48 · full-fluid data region (decisions cap 1200px, prose ~72ch) · Inspector 340 (resizable 300–420). Three density modes as a **lens property + per-grid toggle, persisted per user**: **Compact 32px** rows (catalog/driver/compare grids — the cost lens default), **Comfortable 40px** (global default, homes/decisions), **Relaxed 48px** (portfolio/present). 8px base grid, religiously; 4px micro.

### Grid — the data-grid is a hero surface
Sticky header, frozen identifier column + 3D thumbnail, hairline row separators, hover `surface-2/60`, selection = tint + 2px cobalt left-marker, right-aligned tabular numerics, column sort/filter/show-hide, row-select → bulk actions, expandable rows → inline driver breakdown. The old identity had a gauge where a grid should be.

### Type
Two families only. **Geist Sans** UI/body at **13px base** (the productive-app tell). **Geist Mono, tabular (`tnum`)** for every cost, dimension, qty, rate, ID, source string — right-aligned wherever numbers column up. **Retire Archivo Expanded** as identity — the one hero answer (unit cost) is Geist Mono, tight tracking, ≤44px: a governed metric, not signage. Weights 400/500/600 only; graphite `#12161C`, never pure black.

### Color (incl. dark)
Cool **graphite** ramp (`#F5F7FA` canvas light / `#080B0F` canvas dark) replaces the warm limestone — the single biggest enterprise-credibility swap. One scarce **cobalt** accent (`#205AAE` light / `#4C90F0` dark) on primary action, active nav, links, focus ring, selection, and the one hero-metric marker — nowhere decorative. Dark is **co-equal**: light = Databricks catalog register (dense-table readability, default for catalog/data), dark = Foundry command register (operational focus); user-pinnable. Status lane (Pass/Advisory/Required) muted and icon+label, never color-only.

**Provenance tiers held apart from cobalt** so "governed source" never reads "clickable": MEASURED **teal** `#0E7C86`, SHOP **bronze** `#A9682A` (the data-moat hue, given weight — the pillar the giants can't copy), USER **indigo** `#5B4FC0`, DEFAULT **hollow graphite outline, no fill, ever**. Filled = grounded, hollow = a guess — one governance grammar across chips, grid micro-bars, the lineage DAG, and portfolio posture bars.

### Data-viz — instruments, not decoration; ≤3 series; provenance-tinted
- **Cost breakdown** = horizontal stacked bar/waterfall, each segment tinted by its provenance tier (the breakdown *is* the lineage).
- **Make-vs-buy crossover** = 2–4-line breakeven chart, log-X qty, make-curve cobalt, buy/tooling graphite, marked crossover ReferenceLine, live slider marker — on a clean bordered panel, not a blueprint field.
- **Lineage** = directed derivation DAG (new, load-bearing) — nodes colored by provenance tier, DEFAULT hollow.
- **Portfolio** = ≤9 KPI tiles + sparklines + a governance-posture stacked bar.
- **Confidence** renders as a quiet track — solid when `validated==true`, diagonal-striped (the honest `cv-hatch`, restyled as a micro-indicator) when assumption-based; never a fabricated ±X%.

### Depth, radius, borders
Flat and structural. Elevation = surface-tint steps separated by 1px hairline borders; exactly **one** soft shadow (`0 8px 24px -8px rgb(8 13 20/.24)`) reserved for true overlays (menus/dialogs/⌘K/tooltips). No bezels, blooms, halos, grid fields. Radius tight: chips/controls 4 · cards 6 · panels 8; `rounded-full` only for dots and avatars.

### Motion — Linear discipline
120ms micro / 160ms standard / 240ms max, `cubic-bezier(0.2,0,0,1)`, opacity+transform only, no blur-in, no gauge-needle settle, no bounce. **Lineage edges draw in with a 160ms stagger** — the one place motion *explains* (data flowing through the derivation). Optimistic client-side re-cost on the slider (instant reads as "it knows"); server re-cost shows skeletons over spinners; `prefers-reduced-motion` honored.

### Components
One of each `ui/*` primitive. Cobalt primary button scarce (one per view), `Verb + Noun` labels; governance/verdict/filter chips; **inline-editable numeric grid cells** for cost overrides (not modals); ⌘K primary nav; underline tabs; Inspector tabs Lineage/Governance/Sources/Audit; `Space`-to-peek. All four data states: skeleton over spinner, staged human-named progress ("Parsing geometry → Routing → Costing across processes"), inline retry, selling empty states.

### Explicit keep / evolve / kill vs the current UI

| | Verdict | What |
|---|---|---|
| **KEEP** | as-is | `lib/breakeven` · `cost-decision` · `cost-views` · `dfm-scope` · `status`; the `glass-box/*` provenance vocabulary (`provenance.tsx` atom, driver-breakdown, confidence, calibration); the `ROLES` model; the token layer + `ui/*` primitives + `cad-viewer`; the honesty rail (`confidence.validated` verbatim, hollow-DEFAULT). |
| **EVOLVE** | re-scope | Demote `LivingInstrument` from *the product* to *the Design/Buyer lens* (its logic already lives in `lib/breakeven`+`cost-views`, so re-hosting is cheap). Grow the ⌘K-only + single-part shell into the catalog-first multi-object IA. Role from client-side dropdown → platform identity from `user.role`/SSO. Default authed surface from dark instrument → **light catalog** (scope dark to focus/ops). Ephemeral decision → persisted, versioned, shareable object with a lifecycle state. Consolidate `.cv-paper`/`.cv-twilight` token drift into one source. |
| **KILL** | delete | The Gen-2/Gen-3 fork — pick the catalog shell, delete the loser (do not ship both). Gen-1 legacy cards (`CostDecisionCard`, `ProcessScoreCard`, standalone `AnalysisDashboard`). The `GlassBoxDrawer` peek-drawer as the workbench for depth personas (keep at most as a Design-lens flourish). The three redundant decision renderings (`SavedCostDecisionView` vs `CostDecisionView` vs `DecisionReadout`) → converge on one. The milled-metal faceplate/bezel/well/obsidian CSS + blueprint hero-field + halo/bloom. **And clear the one honesty blocker: kill the Replicate image→mesh egress before claiming zero-egress.** |

---

## 6. The 100x-better claims (specific, vs each incumbent)

- **vs aPriori (validated black box):** they *assert* an authoritative regional number and bury the driver-level "why"; their 2026 `aiSource` chatbot is a patch on opacity. We make the number a **governed asset with clickable column-lineage** — `Σ(drivers)=unit_cost`, every line tagged MEASURED/SHOP/USER/DEFAULT, inline-editable, no training tax, decision-in-seconds on file drop. Answer-first, not intimidating-on-open.
- **vs Paperless Parts (owns shop rates, hides them in a sell price):** they produce a *sell price to win a job* for the estimator. We surface the shop's calibrated rates as **first-class, versioned, effective-dated rate-library assets** feeding a **neutral** should-cost for the design/cost engineer — the make-vs-buy decision, not a quote to accept.
- **vs 3D Spark (closest analog):** they compare technologies but foreground neither a **draggable breakeven-quantity crossover** nor **per-shop-per-driver provenance**, and their supplier-indicative pricing round-trips CAD out. We ship the crossover as the signature interaction, per-shop calibration inline, and **zero-egress local-first**.
- **vs Xometry (funnel polish, structurally opaque):** their price is marked-up and "personalized to willingness-to-pay"; CAD leaves the building; they structurally cannot show a glass box or ever say "make it in-house." We are the opposite on every axis: transparent Σ, neutral, IP-local, honest confidence with **no fabricated ±%** — while matching their instant tweak→re-price loop mechanically.
- **vs Cognite (industrial DataOps):** value is gated behind a heavy integration project and is SME/data-engineer-facing; nothing about a manufacturing *decision in seconds*. We deliver day-one value from a single STEP file, then let connectors (W2) deepen the moat — value before the platform tax.
- **vs Palantir Foundry (the ontology, done heavy):** the closest to our provenance thesis — but for *data*, needing forward-deployed engineers and consulting pricing, never a should-cost. We take Foundry's lineage/governance grammar and apply it to the **manufacturing cost decision**, self-serve, no FDEs.
- **vs Databricks (the lakehouse we're named for):** notebook/developer-first, utilitarian, no domain. We keep Unity-Catalog governance + column-lineage + saved-view discipline but land a **decision-maker** on a domain-native catalog of parts and should-costs — the lakehouse UX without the cluster-config friction.

**The unheld intersection (the 100x lane):** each vertical tool holds one corner (aPriori=validated data, Paperless=shop rates, 3D Spark=multi-tech, Xometry=funnel, DFMPro=DFM depth) and the giants hold the credibility corner (Palantir's ontology, Databricks' Unity Catalog, Cognite's contextualization). Nobody holds the whole: a **neutral, per-shop-calibrated, glass-box, decision-first should-cost, catalog-first and role-aware over one governed object model, running zero-egress** — where every headline number in a 10k-part portfolio drills to its own lineage, every Decision moves through a visible lifecycle, and every returned quote feeds the ground-truth flywheel.

---

## 7. Phased UI build plan (mapped to the platform walls; W1 tenant/catalog first)

No big-bang rewrite. Each phase reuses the prior shell; the catalog is built once and everything after is a projection/schema-add.

### Phase 0 — Reconcile & re-found (pre-W1; the debt clearance)
Ship the **graphite/cobalt platform chrome** and unify to **one shell**. Re-token `globals.css` (graphite ramp, one cobalt, retire Archivo/faceplate/bloom CSS, consolidate `.cv-paper`/`.cv-twilight`). Revive `PartWorkspace` as the **L2 Decision object frame** (tabs: Decision · Routing & DFM · Glass Box · Compare · History), absorbing `LivingInstrument` as the Design lens. Reframe `GlassBoxDrawer` into the **Inspector** (Lineage/Governance/Sources/Audit). Delete Gen-1 cards + the losing shell + redundant decision renderings. **Kill the Replicate egress.** *Delivers the beauty re-founding immediately on the already-shipped single-part loop — no backend dependency.*

### Phase 1 — Org-workspace shell + Governed Catalog (**W1**; the spine lands)
Org switcher + tenant namespace + **RBAC namespace grants**. The **Catalog Explorer becomes the home** (Parts schema first). **Saved Views** + **⌘K** co-primary nav + **Role Lens** from `user.role`/SSO → three role homes (Ledger/Bench/Portfolio) as saved views. Context-bar breadcrumb. Persisted per-user density/columns. *This is the surface an IT buyer lands on; it is what W1 ships, rendered as the product home.*

### Phase 2 — Governed Libraries + Lineage + Governance (**W4**)
Add the **Materials · Processes · Shops · Rate-libraries** schema tabs as first-class versioned assets; the **asset-detail** object (Overview · Versions · Usage · Lineage). Ship the **Lineage DAG** inspector and the **Governance** zone (change requests → review → publish, effective-dating, downstream-impact, audit). The Calibration workbench (already DONE) plugs in here. *Turns the catalog from "parts" into a governed lakehouse.*

### Phase 3 — Portfolio / Batch / Savings (**W3**)
The **Portfolio** zone: `GROUP BY` roll-up, batch cost compute (rank a 10k-part catalog), analytics (cost distribution, driver heatmap, coverage), the ranked cost-down board with owner + lifecycle state. Surface the **lifecycle State column** across the catalog. *Every aggregate drills to rows; portfolio is a projection of the catalog you already built.*

### Phase 4 — Connectors + RFQ/Quote + Sourcing Inbox (**W2**)
The **Connect** zone (PLM/CAD/ERP + historical-quote import, sync monitor, field mapping/dedupe). The **Sourcing** zone: RFQ builder/list, quote intake, and the **Decision Inbox** (catalog grouped by lifecycle state — the V2 graft). *Connectors deepen the moat additively; the inbox is a saved view, not new architecture.*

### Phase 5 — Ground-truth flywheel (**W5**)
Quote-compare-vs-should-cost closes the loop: awarding links a returned quote as ground truth → validates/promotes the calibration profile → advances the Decision to `Validated`. Validation trend + calibration-drift alerts in Governance/Calibration. *The catalog's governance posture now reflects real quotes, not just assumptions.*

---

## 8. Open design questions for the founder to steer

1. **Inspector default per persona.** Resident for the cost lens, summonable for others (our proposal) — or resident everywhere for maximum audit-forwardness at the cost of screen real estate?
2. **Light vs dark default.** We propose light-for-catalog/data, dark-for-focus/ops, user-pinnable — flipping the current dark-everywhere default. Confirm the authed app should default to **light**?
3. **When does the lifecycle State column appear?** From Phase 1 as a mostly-empty column (Drafted/Costed only), or introduced with Sourcing (Phase 4) when the later states become real? Earlier = more coherent; later = less "empty scaffolding."
4. **The object noun.** "Decision" vs "Estimate" as the primary object label in the UI. "Decision" is more on-thesis; "Estimate" is the term cost engineers already say.
5. **Distinct Sourcing home?** Ship a separate Sourcing "Inbox" persona home (V2's hero), or fold sourcing into the Cost/Sourcing "Ledger" until W2 makes the inbox states real?
6. **Design-engineer landing.** Catalog-grid-first (consistent) vs dropzone-first (answer-first for the person who mostly wants DFM on one new part)? We propose a narrow "My parts" saved view *with* a prominent dropzone.
7. **How much Palantir object-graph do we build?** Just the lineage DAG (our scope), or the full Object-Explorer "search-arounds" over the ontology later?
8. **Zero-egress claim timing.** The Replicate image→mesh egress must be killed before we can honestly show the data-locality badge. Confirm this is a Phase 0 blocker, not a "later."
9. **Marketing↔product coherence.** The old blueprint-twilight/Living-Instrument aesthetic still lives in marketing (`/`, `/method`). Do we re-found marketing to the graphite platform look in lockstep, or let the Design-lens moment carry the "instrument" beauty as the marketing hero?
