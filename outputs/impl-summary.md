# CadVerify Implementation — Run Summary (2026-07-01)

Backlog = `outputs/audit/platform-gap-map.md`. Discipline: feature branch off `dev` → tests pass → adversarial Verifier → merge to `prod`. `prod` stayed demo-ready throughout.

## ✅ CLOSED + MERGED to `prod` this run (4 items, all adversarially verified)

**Phase 1 — demo-killers (the demo now holds):**
1. **DFM flag scoping** (DFM audit FRAGILE-1) — headline no longer sums flags across all 21 processes; scoped to the recommended route + part-level issues, full matrix behind an honest expander. Process-name identity proven end-to-end. Flag `NEXT_PUBLIC_DFM_SCOPED_FLAGS` (default ON). *(6bdf3ff)*
2. **CNC volume/learning curve** (cost audit S1) — Wright learning curve on attended conversion cost; CNC unit cost now drops ~49% from qty 100→10k (was flat), numerical make-vs-buy crossover proven monotone. Honestly tagged assumption (`validated` stays False). Flag `CADVERIFY_CNC_LEARNING` (default ON). *(2511e92)*
3. **Engine memory cap** (arch audit P0) — 12.2 GB → **300 MB** peak RSS on the 20k-face mesh class that OOM'd (batched ray-casting + threshold 50k→5k + ingest decimation). Real wall thickness still computed for every face. Decimation now surfaces a user-visible `DECIMATED_MESH` warning (one honesty route-back). *(6a967c9)*

**Phase 2 — the keepable artifact (the flagship output is now durable):**
4. **Persist + export/share/compare the should-cost decision** (product audit gap #3) — `CostDecision` model + migration 0008; persist on `/validate/cost`; list/detail/compare; cost PDF + JSON + CSV export; public sanitized share link; full save/export/share/history/compare UI. Verified on **real Postgres** (no PII leak, owner-scoped 404, migration up/down clean); honesty preserved everywhere (no "validated" stamp). Flags `COST_PERSIST_ENABLED` / `NEXT_PUBLIC_COST_PERSIST_UI` (default ON). *(060fca3 + 03c357b)*

**Audit's stated goal achieved:** "make the demo hold up, then make it produce a keepable artifact." Both done.

**Phase 0 (design re-founding) also shipped this run:**
5. **Kill Replicate egress** (F-ARCH-4 / honesty) — reconstruction defaults local; remote = explicit warned opt-in; no-local+no-opt-in → announced `RECONSTRUCTION_UNAVAILABLE` 501 (no egress); honest `/health` reconstruction block. Zero-egress claim now true. Suite 603/0. *(680757a)*
6. **Frontend re-founding** — the identity swap from "glowing-gauge cockpit" to "governed catalog": graphite dark-first + one cobalt, faceplate/bloom retired, one 4-zone shell, `PartWorkspace` = the **Decision** frame (Decision·Routing&DFM·Glass Box·Compare·History) with the crossover "aha" preserved in flat chrome, `GlassBoxDrawer` → `DecisionInspector` (provenance-as-infrastructure, no fabricated %). Demo path + Phase-2 artifact intact; zero-egress badge scoped to the cost/DFM path. tsc/tests/Turbopack-build green. *(4c17022)*

`prod` == `dev`, demo-ready with the new identity on the live loop. Full backend suite 603/0; frontend green. **Aesthetic judgment → founder (design is theirs to eyeball).**

## 🔜 Phase 3 — PLATFORM + DESIGN track (north star: "Databricks for manufacturability & cost")
See `outputs/impl-state.md` for the load-bearing walls. Sequence (design-first):
- **Design reconception (IN FLIGHT):** platform IA/UX/UI vision → `outputs/design/platform-ia-vision.md`. Multi-persona org workspace; Databricks × Palantir × Linear aesthetic (beyond glass-box-drawer, provenance-as-substance); 100x-better-than-incumbents. Founder-steered.
- **W1 — multi-tenant org/team/RBAC catalog** (the Unity-Catalog foundation; buildable now, do first — brutal to change later). Pairs with the redesigned workspace shell + catalog UI.
- **W2** ingestion/connectors (PLM/CAD/ERP + historical quotes). **W3** portfolio/batch COST compute. **W4** governed rate/material/shop libraries as versioned assets.
- **Async tier real + `/health` honest** (serves the #1 no-lying-stub rule; also kills the Replicate image→mesh egress landmine flagged by the Aramco research).
- **W5 ground-truth flywheel** — machinery buildable; validation is the Zoox human gate.
- **Deeper cost model** (tolerance/GD&T, real ±band) — correctness-dependent → gated on Zoox validation underway.

## 🚦 Human-gate queue (prepared, never self-certified)
- **Cost/DFM number correctness** → **Zoox Head of Manufacturing** on real parts + real quotes → load into `groundtruth.py` held-out eval. Each Phase-1/2 change carries its explicit Zoox caveat (CNC curve *magnitude*; sampled wall-thickness tail error; systematic under-costing). Packet basis: `outputs/verify/*.md` + `outputs/validation-packet.md`.
- **Security** → SAML vs a real IdP + pen test (security engineer / accredited firm). Public cost-share sanitization already verified; broader Phase-3 auth/tenant isolation to follow.
- **SOC 2** → qualified auditor. **ITAR/export + data-residency** → legal (+ kill Replicate egress).
- **Load/soak** → SRE on real Postgres+Redis+worker (the memory fix bounds the engine; capacity envelope needs a real run).
- **Design direction** → founder steer on `platform-ia-vision.md` when it lands.

## Branch topology
`prod` == `dev` (all Phase 1+2). Feature branches merged & retained for traceability: `feat/dfm-scope-flags`, `feat/cnc-volume`, `feat/engine-memory`, `feat/cost-persist`, `feat/cost-persist-ui`.
