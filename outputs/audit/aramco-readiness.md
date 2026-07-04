# CadVerify — Aramco-Readiness Gap Map (current, ex-security)

**Written:** 2026-07-04, against the live `claude/resume-review-oxqw0l` code (988+ tests green, migrations 0013→0017 live-Postgres-validated). **Security/compliance is deliberately OUT of scope here** (SAML/IdP, encryption-at-rest, SOC 2, pen-test, ITAR — all real, all human/third-party gated, tracked separately). This is: *"what, on the product/engineering side, makes a Saudi-Aramco-class enterprise say **no** today — and what can we build vs. what's gated."*

Tag key: **[BUILD]** in our lane now · **[ENV]** blocked by a missing library in this env (installable on a deploy target) · **[SCALE]** architectural scale work · **[EXT]** needs an external system to integrate/test · **[HUMAN]** needs a person/data.

---

## 0. Honest headline (updated from the pre-session "~15–20% of a platform")
The platform moved a long way this cycle. The old gap map's demo-killers are **closed**: CNC-cost-flat-across-qty (learning curve), DFM over-flagging (route-scoped), the 19 GB memory bomb (bounded), ephemeral output (persist/export/share/compare), single-seat (org/tenant/RBAC), DFM-only batch (portfolio cost), dead async tier + lying `/health` (async-honest), SQLite-only CI (CI-Postgres). Added this session: governed rate/material/shop libraries, governance flow, W5 flywheel + **CSV bulk import**, **owned-equipment in-house costing**, triage rollup, `/metrics`.

**So it is now a real multi-tenant platform with a real, honest, self-calibrating cost/DFM engine.** What still makes *Aramco specifically* say no is a different, mostly-additive set of gaps — clustered in **getting their parts in, at their scale, in their formats, with their tolerances/assemblies — and a UI to operate it.**

---

## 1. The five gaps that actually block Aramco (ex-security), ranked

### GAP 1 — Legacy CAD format coverage (THE #1 blocker) — **IGES CLOSED 2026-07-04**
Aramco's ~millions of legacy parts are overwhelmingly **IGES, native CAD (CATIA/NX/Creo/SolidWorks), 2D drawings (PDF/TIFF), and scans** — not clean STL/STEP.
- **IGES — [DONE].** The uploader now accepts `.iges/.igs` and routes them through the existing gmsh/OpenCASCADE mesher (no new mesher code), gated by a structural 80-column/section-letter magic check. STL/STEP behaviour is byte-identical; IGES-derived cost/DFM carries the same mesh-level (not B-rep) caveat as STEP. (`routes.py` `_parse_mesh`, `upload_validation.py`, `tests/test_iges_ingest.py`.)
- **Native CAD (CATIA/NX/Creo/SLDPRT) — [ENV/EXT].** Needs OCP/OpenCASCADE-XDE or a translator (e.g. a CAD-exchange lib); heavier, some formats are proprietary.
- **2D drawings / no-3D-model parts — [BUILD, large].** Many legacy parts have only a drawing. Needs a drawing→features/OCR path (or an explicit "declare specs, no geometry" mode). Big, but high-value for MRO.

### GAP 2 — Scale to millions — **whole-inventory triage + paginated grid CLOSED 2026-07-04**
The catalog/triage/portfolio read surfaces used to cap at `CATALOG_SCAN_CAP = 2000` parts (fold in Python). Now:
- **[DONE].** A materialized `part_summaries` projection (one row per `(org_id, mesh_hash)`, migration 0019) is maintained on every analysis/cost write (graceful-degrade in a SAVEPOINT, idempotent, byte-identical to the legacy derivation by *calling* `derive_row`/`triage_bucket`). **Triage is now an O(buckets) SQL `GROUP BY` over the whole inventory** — "triage your 14M parts" is real, uncapped. The catalog grid gains **keyset pagination** (`?keyset=true&cursor=…`) that hydrates one page at a time. The legacy capped fold is retained untouched as the byte-identity oracle **and** as a read-only fallback when an org's projection is still cold (pre-backfill deploy) — honest `truncated:true`, no write on a GET. Deploy runs `scripts/backfill_part_summaries.py` once to lift the cap for pre-existing data (idempotent; correctness never depends on it). (`part_summary_service.py`, `catalog_service.build_triage_scaled`/`build_catalog_page`, `tests/test_part_summary.py`.)
- **Still [SCALE] (not yet done):** streaming ingestion of very large corpora, and portfolio-savings ranking at full scale (portfolio still uses the legacy fold). The core Aramco triage-the-inventory claim is the piece that shipped.

### GAP 3 — No connectors to where their data lives — **parts-manifest onboarding CLOSED 2026-07-04**
Aramco's parts + historical costs live in **SAP + a PLM (Teamcenter/SmarTeam/etc.)**.
- **Parts-manifest import — [DONE].** A declared-inventory registry (`manifest_parts`, keyed by `(org_id, part_id)`, migration 0020) with `POST /api/v1/manifest/import` (strict/honest CSV, mirrors the ground-truth importer — per-line errors, material validation, capped streaming, upsert per part_id), a keyset-paginated `GET /manifest`, and `GET /manifest/coverage` — the pilot headline: total declared, a scalable `GROUP BY program` breakdown, and a normalized-stem **geometry-coverage** count ("how much of your inventory do we even have geometry for"). Honest by construction: declared rows are USER inventory facts, the manifest is a SEPARATE registry that never creates analyses/cost_decisions and never moves the geometry-derived catalog/triage numbers. (`manifest_service.py`, `api/manifest.py`, `tests/test_manifest_ingest.py`.) This unblocks a structured pilot from a SAP/Excel export.
- **[EXT]** Real live PLM/ERP/SAP connectors still need those systems to build+test against; the manifest CSV + documented ingestion API is the pilot-grade bridge to them.

### GAP 4 — Tolerances / GD&T and assemblies — **declared-tolerance cost surface CLOSED 2026-07-04**
Aramco parts are pressure-rated, API-spec — **tolerance and material spec ARE the part.** Today:
- **Declared tolerance-class input — [DONE].** `/validate/cost` now accepts a `tolerance_class` (`standard`/`precision`/`tight`); the cost model applies an honest machining-cost multiplier to the tolerance-sensitive CNC conversion terms (finish pass + inspection) **and** widens the confidence band. `standard`/omitted is byte-identical; the factor is a DEFAULT assumption (not shop-validated), the declaration is USER, `validated` never fabricated. (`EstimateOptions.tolerance_class`, `cost_model.cost_breakdown`, `rates.TOLERANCE_CLASSES`, `tests/test_tolerance_input.py`.) This closes the biggest *cost-side* tolerance gap **without OCP**.
- **Real GD&T/PMI extraction — [ENV].** STEP is mesh-level, not B-rep; AP242 PMI extraction still needs OCP (tests skip). The declared input above is a STATED cost driver, not a measured tolerance.
- **No assembly / part-in-context** — can't ingest a STEP assembly BOM tree / where-used. The *declared*-context rung shipped (part_context); real geometry context is [ENV] (OCP).

### GAP 5 — No UI; it's an API-only platform
Everything we/I built — governed libraries, triage, portfolio, owned-equipment costing, CSV import, flywheel — is **backend/API only**, exercised by tests, not clickable. **Aramco can't pilot an API.** The frontend register is mid-redesign (founder rejected earlier passes). **[HUMAN/design]** — this is the founder's Claude Design track, but it is a hard prerequisite for an actual evaluation.

---

## 2. Secondary gaps (would surface in a serious evaluation, ex-security)

- **Cost coverage is now 15 of 18 processes — [forging/casting/EDM DONE 2026-07-04].** Dollar cost now covers **15** (`COSTED_PROCESSES`): additive, CNC, injection/die-cast, sheet, **+ forging, investment casting, sand casting, wire-EDM** (new honest physics models, own `casting`/`forging`/`edm` families, byte-identical to the prior 11). Remaining feasibility-only: **DMLS, SLM, EBM, binder-jet, DED, WAAM** (advanced/metal-additive) — [BUILD] next if Aramco needs metal-AM cost. Wire-EDM's cut-path uses a 2D-outline proxy (honestly caveated, wide 45% band) pending a true 3D cut-length driver.
- **Oil-&-gas material breadth — [DONE 2026-07-04].** Added a 10-alloy API-spec pack (AISI 4130/4140, ASTM A105, A182 F22; API 13Cr, Super 13Cr, Super Duplex 2507, F6NM/CA6NM; Incoloy 825, Hastelloy C276) with correct metallurgical properties, NACE MR0175 + API/ASTM standards, and honest approximate wrought $/kg. **Also activated WIRE_EDM end-to-end** (it had zero compatible material, so Track D's wire-EDM cost was previously unreachable via the live path) and the sand-cast stainless route (F6NM). Family-cheapest defaults for existing classes stay byte-identical (new grades priced above the incumbents); the only shifts are to genuinely-cheaper real alloys (nickel→Incoloy 825, forging-stainless→API 13Cr). Orgs can still override via the governed material library. Remaining out-of-box gap: even broader alloy coverage (Monel, Alloy 625/718 forged variants, more grades) is easy follow-on data.
- **Numbers still n=0 out-of-box — [HUMAN/data], now self-serve.** Assumption bands until real data; but that's now *onboardable by them* (CSV import → flywheel → owned-equipment marginal cost), not a Zoox-bureau gate.
- **Scale/ops unproven — [SCALE/HUMAN].** No load/soak at Aramco volume; single-request CPU/memory-bound engine; no SLA/DR/backup-restore runbook; batch/recon blobs on local disk (no object-store abstraction) breaks on multi-machine.
- **No RFQ/quote/sourcing object — [BUILD].** Matters less for a make-in-house buyer, but absent.
- **No AI copilot — [BUILD].** Category is AI-native; we have zero LLM. Was parked until W1+W4 land — they now have. Revisitable ("why is this number / how do I reduce it," grounded on the governed provenance we built).

---

## 3. What I can build next (no human/env gate) — recommended order
1. ~~**IGES ingestion**~~ — **DONE 2026-07-04.**
2. ~~**Tolerance/finish input surface**~~ — **DONE 2026-07-04.**
3. ~~**Cost models for forging / casting / EDM**~~ — **DONE 2026-07-04.**
4. ~~**Catalog/triage at scale**~~ — **DONE 2026-07-04** (whole-inventory SQL triage + keyset-paginated grid; portfolio-at-scale + streaming ingest still open).
5. ~~**Parts-manifest CSV + ingestion API**~~ — **DONE 2026-07-04** (declared-inventory registry + import + coverage summary).
6. ~~**Oil-&-gas material pack**~~ — **DONE 2026-07-04** (10 API-spec alloys + WIRE_EDM/sand-cast activation).
7. **Metal-AM cost (DMLS/SLM/EBM)** [BUILD] — the last feasibility-only families, if Aramco needs additive-metal costing. **← next recommended.**

## 4. What is genuinely NOT in our lane
- **Native-CAD / PMI / STEP-assembly geometry** [ENV] — needs OCP/OpenCASCADE-XDE, not installable in this container; a deploy-target task.
- **Real PLM/ERP/SAP connectors** [EXT] — need the live systems.
- **UI / product design** [HUMAN] — founder's design track.
- **Numbers validated** [HUMAN/data] — their real costs (now self-serve via import), or a Zoox-style session.
- **On-prem/air-gap acceptance, load/soak, SLA/DR** [HUMAN/SRE] — real hardware + ops sign-off.
- **(Security/compliance — excluded by scope, tracked separately.)**

---

**Bottom line for Aramco:** the *decision engine and the platform around it are real* — the remaining "no" is about **ingesting their actual parts (formats), at their scale, from their systems, with their tolerances/assemblies, through a UI.** Of those, **formats (IGES), tolerance-input, more costed processes, and catalog-scale are all buildable by us now**; native-CAD/PMI/assemblies, real connectors, and the UI are env/external/human-gated.
