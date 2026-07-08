# CadVerify — Platform Gap-Map Implementation State

**Backlog:** `outputs/audit/platform-gap-map.md` (5-lens expert audit, 2026-07-01).
**Discipline:** feature branch off `dev` → tests pass → WIP behind a flag → adversarial Verifier → merge to `prod`. `prod` stays demo-ready.

## Branch topology
- `main` — history + checkpoint `95ad0c4` (versioned the previously-uncommitted running demo state incl. the whole cost engine; closes audit F-ARCH-8).
- `prod` — demo-ready line. Only verified + production-worthy work merges here.
- `dev` — WIP integration. Feature branches cut from here.
- Feature branches: `feat/<item>` per gap-map item.

## Items (audit priority order)

| # | Phase | Item (gap-map finding) | Area | Status |
|---|-------|------------------------|------|--------|
| 1 | 1 | Scope DFM flags to the RECOMMENDED process (kill "78 flags/15 critical" summed across 21 processes) — DFM audit FRAGILE-1 | frontend + api presentation | ✅ MERGED to prod (6bdf3ff). 3 adversarial verifiers PASS; process-name identity proven end-to-end. Flag NEXT_PUBLIC_DFM_SCOPED_FLAGS (default ON). |
| 2 | 1 | CNC real volume/learning curve so cost drops 100→10k and make-vs-buy crossover behaves (currently flat) — cost audit S1 | backend/src/costing | ✅ MERGED to prod (2511e92). Wright learning curve ~49% drop 100→10k; numerical crossover proven monotone; validated stays False. Flag CADVERIFY_CNC_LEARNING (default ON). Zoox-gated: curve magnitude. |
| 3 | 1 | Cap engine memory (fix ~19 GB OOM on ordinary 37k-face part) — arch audit P0 | backend/src/analysis | ✅ MERGED to dev (6a967c9); prod ff pending merged-suite gate. 12.2GB→300MB proven; batched-ray byte-identical; decimation now user-visible (DECIMATED_MESH warning). Routed back once for honesty (silent decimation). Zoox-gated: sampled-path tail error. |
| 4 | 2 | Persist + export/share/compare the should-cost decision (flagship artifact; currently ephemeral) — product gap #3 | db + api + pdf + frontend | TODO |
| 5 | 3 | `/health` honest + async tier fails loud (serves #1 global no-lying-stub rule) — arch F-ARCH-1/2 | backend | TODO (if cap allows) |

## Phase 3 — PLATFORM + DESIGN track  ★ NORTH STAR: "Databricks for manufacturability & cost"
Scope precisely to the **decision layer** (manufacturability + should-cost), NOT all manufacturing data (that's Cognite/Palantir/operations). The deterministic engine = compute; provenance = governance/lineage; ground-truth = the data moat; a portfolio catalog = the lakehouse. Gating: platform/infra items start now that the demo (Phase 1+2) HOLDS; **correctness-dependent** items (deeper cost model) need the Zoox validation underway; enterprise-governance (multi-tenant isolation, encryption-at-rest, SAML→IdP, SOC2) per audit gap #6.

**Load-bearing walls (build in this order; each ships with its UX surface, not after):**
| # | Wall | Audit gap | Buildable now? | Notes |
|---|------|-----------|----------------|-------|
| W1 | **Catalog/tenant model** — multi-tenant org/team/RBAC namespace (the Unity-Catalog analog). A schema change touching every user-scoped table + isolation. | #4 platform + #6 enterprise | ✅ (not Zoox-gated) — **do first, brutal to change later** | FOUNDATION; unblocks W2–W4. Design-first (schema + IA together). |
| W2 | **Ingestion / connectors** — meet buyers at PLM/CAD/ERP (Windchill, Onshape, part masters, historical quotes) + CSV round-trip. | #4 integrations | ✅ (big) | incumbents' deepest moat; biggest whitespace. |
| W3 | **Portfolio/batch COST compute** — run the engine over a whole catalog, ranked by cost-down (batch is DFM-only today). | #4 P0 | ✅ | the enterprise value story. |
| W4 | **Governed rate/material/shop libraries** as first-class, versioned, access-controlled assets (aPriori "digital factories"). | #4/#6 | ✅ | the catalog's *content*. |
| W5 | **Ground-truth flywheel** — groundtruth.py fueled by real quotes; each row VALIDATED against reality. | #1 correctness | Machinery ✅ / **validation = Zoox human gate** | the moat fuel; n=0 today. |
| — | Async tier real + **/health honest** (serves #1 no-lying-stub rule) | #5 | ✅ (not Zoox-gated) | also enables portfolio compute + kills the Replicate egress landmine (research). |

**DESIGN track (first-class, NOT a reskin):** the platform reframing demands a re-conceived IA/UX/UI — enterprise-viable, efficient, AND beautiful — around workspace → governed catalog → portfolio/savings → decision/quote → governance/lineage, replacing the single-seat instrument IA. Design-first: a platform IA + UX/design-system vision that W1–W4 build toward. Anchored on the existing design system (outputs/design/) + competitor UX + the Aramco/positioning research. **Steering (founder calls, being confirmed): aesthetic north-star + primary front-door persona.**

## Human-gate queue (cannot self-certify — prepared, never faked)
- **Cost/DFM number correctness** → Zoox Head of Manufacturing on real parts + real quotes (load into groundtruth.py held-out eval).
- **SAML vs real IdP + pen test** → security engineer / accredited firm.
- **SOC2 readiness** → qualified auditor. **ITAR/export** → legal.
- **Load/soak test** on real Postgres+Redis+worker → SRE.

## Notes
- No central settings module; feature-flag convention is `os.getenv("FLAG", default)` per-module.
- Backend test baseline: 564 tests collected; `.venv` present (py3.9). Frontend: Next.js.
- Phase-3 deeper-cost-correctness items are GATED by Zoox validation → prepare packet + queue, do not self-certify.
