# CadVerify — RESUME-HERE (granular session handoff)

**Written:** 2026-07-02. **Purpose:** resume this work with zero context loss. Exhaustive and literal — commit hashes, flag names, file paths, test counts, open decisions. Nothing summarized away.

---

## 0. MISSION / OPERATING CONTRACT (what we're doing and how)

- **Backlog / source of truth:** `outputs/audit/platform-gap-map.md` (5-lens expert audit, 2026-07-01) + its sub-audits `outputs/audit/audit-{cost,dfm,arch,product,enterprise}.md`.
- **Goal:** turn CadVerify from "a real core wrapped in scaffolding (~15–20% of a platform)" into something that actually works end-to-end, production-worthy, following the audit's sequence: (Phase 1) make the demo hold; (Phase 2) make it produce a keepable artifact; (Phase 3) deeper correctness + platform + enterprise, gated by real human validation (Zoox etc.).
- **Discipline (enforced every change):** feature branch off `dev` → tests pass → WIP behind a feature flag → **adversarial Verifier** → merge to `prod`. `prod` stays demo-ready at all times.
- **#1 NON-NEGOTIABLE RULE:** NO STUB MASQUERADING AS REAL. Every part is real or announces it isn't. `/health` must not lie. No silent egress. No fabricated numbers. (We caught + fixed two violations this run — see items 3 and P0-A.)
- **Correctness honesty:** cost/DFM numbers are NOT self-certified. Every numeric change carries an explicit **Zoox validation caveat** (the human gate). `validated` stays `False` until real quotes are measured.
- **Mode:** ultracode (multi-agent workflows, adversarial verification, exhaustive over cheap).

---

## 1. CURRENT STATE SNAPSHOT

- **`prod` == `dev` == `32164a6`** (in sync, demo-ready). Main tree checked out on `dev` at `/Users/nazeem/Desktop/developer/cadverify`.
- **`main` = `95ad0c4`** (the original checkpoint; `origin/main` ahead 1 — the checkpoint was committed but NOT pushed. Nothing has been pushed to origin this run.)
- **Feature branches (merged, retained for traceability):** `feat/dfm-scope-flags@446191b`, `feat/cnc-volume@cc9de08`, `feat/engine-memory@26205c3`, `feat/cost-persist@d38190f`, `feat/cost-persist-ui@fd3896b`, `feat/p0-kill-egress@8ec1e0e`, `feat/p0-refound@ec98897`.
- **Other worktree (unrelated, leave alone):** `cadverify-platform-universe` on `codex/platform-universe@63acc74`.
- **Running processes (macOS, user machine):**
  - `:8000` backend (uvicorn, FastAPI) — up, `/health` returns `{"status":"ok","postgres":true,"redis":true}` (NOTE: redis:true may be the F-ARCH-2 lie — unverified; separate item).
  - `:5432` local Postgres (role/db `cadverify`) — up.
  - `:3000` frontend — **STALE** `npm start` build (started 17:15, pre-Phase-0). Ignore.
  - `:3100` frontend — **FRESH Phase-0 build** (`next start -p 3100`, serving the current `.next`, `API_BASE=http://localhost:8000`). This is what to look at. A preview account is signed in.
- **Preview screenshots:** `~/Desktop/cadverify-refound-preview/{01-cost-empty,02-decision,03-dfm,04-glassbox,05-compare}.png`. Playwright driver: `<scratchpad>/shoot.mjs` (uses `frontend/node_modules/playwright-core` + system Google Chrome; CJS import `import pw from ...; const {chromium}=pw`).
- **Test baselines:** backend full suite was **558 passed / 6 skipped** at checkpoint → **603 passed / 7 skipped / 0 failed** now (Phase 0-A). Frontend: `tsc` clean, `npm test` 17/17 (node --test), `next build` (Turbopack) green in the MAIN tree.

---

## 2. WHAT'S DONE — granular, per item (all verified + merged to prod)

### PHASE 1 — demo-killers

**Item 1 — Scope DFM flags to the recommended process** (DFM audit FRAGILE-1). Branch `feat/dfm-scope-flags@446191b`, merge `6bdf3ff`.
- Finding: the DFM headline was the UNION of issues across all 21 process analyzers ("58 flags / 11 critical") contradicting a DFM-clean recommended route (MJF=0). Trust-killer.
- Built: pure module `frontend/src/lib/dfm-scope.ts` (`scopedDfmSummary`, `partitionDfmByRoute`, `flattenScopedIssues`, `flattenIssues` moved here + re-exported from `IssueList.tsx`). Headline scoped to recommended route (`recProcess` from cost engine; `best_process` pre-cost fallback) + part-level `universal_issues`; full 21-process matrix behind an honest expander. Fixed `LivingInstrument.tsx` + `AnalysisDashboard.tsx`.
- Flag: `NEXT_PUBLIC_DFM_SCOPED_FLAGS` (default ON; `0/false/off/no` = legacy union).
- Verify: 3 adversarial verifiers high-conf PASS. Process-name identity PROVEN end-to-end (DFM `process_scores[].process`, `best_process`, cost `make_now_process`/`estimates[].process` all = same `ProcessType` enum `.value`; verified on 3 meshes / 3 routes). 7/7 frontend tests, tsc clean. `outputs/verify/dfm-scope-flags.md`.

**Item 2 — CNC real volume/learning curve** (cost audit S1). Branch `feat/cnc-volume@cc9de08`, merge `2511e92`.
- Finding: CNC unit cost was volume-INVARIANT ($46.10/$64.74 flat at qty 100/1k/100k). Broke the make-vs-buy crossover.
- Built: Wright cumulative-average learning curve on attended conversion cost (machine cycle + post-labor) for subtractive+fabrication families. `mult(Q)=clamp((Q/lot_size)^log2(rate),floor,1)`, DEFAULT `learning_rate=0.90`, `floor=0.25`, anchored at first production lot. Files: `backend/src/costing/{rates,cost_model,decision,estimate,harness}.py`. `_learning_multiplier` in cost_model; `learning_curve` driver tagged `Provenance.DEFAULT` + `[assumption, not shop-validated]`. Added `_numerical_crossover` in decision.py (scans actual per-qty curves via geometric-bracket+bisection; `make_vs_buy` takes `unit_cost_fn`).
- Result: CNC unit cost drops ~49% from qty 100→10k (Σ=unit_cost invariant holds to 1e-15; `validated` stays False).
- Flags/off-switch: `CADVERIFY_CNC_LEARNING=0` or `rate_overrides={"learning_rate":1.0}`.
- Verify: finding + honesty verifiers high-conf PASS (drop is EMERGENT Wright, not a fudged constant; both off-switches recover old flat cost byte-identically). Crossover proven by orchestrator (synthetic 1000/2000, monotone in tooling fixed cost). Full suite 561/0 (in-worktree with backend/data symlinked). `outputs/verify/cnc-volume.md`.
- **Zoox caveat:** the curve MAGNITUDE (0.90 rate, 30–60% envelope) is an assumption; direction is correct. Two small turned parts dip below the (qty-flat) accuracy reference at qty 1000 — known residual.

**Item 3 — Cap engine memory** (arch audit P0, 19 GB OOM). Branch `feat/engine-memory@26205c3` (base build `0dee207` + honesty fix `26205c3`), merge `6a967c9`.
- Finding: `GeometryContext.build` allocated ~19 GB on an ordinary 37k-face part (per-face pure-Python ray cast; `RAYCAST_SAMPLE_THRESHOLD` default 50000 was backwards).
- Built: `RAYCAST_SAMPLE_THRESHOLD` default 50000→**5000**; batched memory-bounded ray casting (`WALL_THICKNESS_RAY_BATCH=512`, `WALL_THICKNESS_RAY_BUDGET=1200000`, batch=clamp(budget//faces,8,batch)); ingest decimation for meshes > `MAX_ANALYSIS_FACES=250000` (trimesh quadric if available else uniform vertex-clustering); `MAX_TRIANGLES=2M` hard-refuse kept. Files: `backend/src/analysis/context.py`, `+ routes.py/analysis_service.py/eval/engine.py/costing/cli.py` (`detect_features(mesh)`→`detect_features(ctx.mesh)`).
- **Route-back happened here:** first verify FAILED honesty — decimation recorded in `ctx.metadata` but NEVER surfaced to the user, and comments falsely claimed "labelled accordingly." Builder fixed: `base_analyzer.decimation_issue(ctx)` emits a user-visible universal `Issue` `DECIMATED_MESH` (severity warning) in all 4 analysis paths; comments made truthful; cosmetic numpy RuntimeWarning suppressed.
- Result (orchestrator-measured, direct): 20,480-face sphere **12,181 MB → 300 MB**; 81,920-face → 496 MB; real finite wall thickness for every face. Reproduced DECIMATED_MESH surfacing on a 327,680→230,186-face mesh.
- Verify: correctness verifier high-conf PASS (batched ray = byte-identical to unbatched; decimation fallback watertight; `detect_features(ctx.mesh)` a true no-op for normal parts). Full suite 563/0. `outputs/verify/engine-memory.md`.
- **Zoox caveat:** threshold 50000→5000 expands the KDTree-propagated sampled wall-thickness path to most real CAD (5k–50k faces); verifier measured tail error up to ~567% relative at wall-thickness discontinuities (thin rib next to thick boss).

### PHASE 2 — the keepable artifact (product audit gap #3)

**Item 4A — cost persistence BACKEND.** Branch `feat/cost-persist@d38190f`, merge `060fca3`.
- Finding: the should-cost decision was computed in-memory and thrown away.
- Built: `CostDecision` model (mirrors `Analysis`, JSONB `result_json`=`report_to_dict()`, denormalized `make_now_process`/`crossover_qty`/`quantities`, dedup `UniqueConstraint(user_id,mesh_hash,params_hash)`, partial-unique share index) + migration `backend/alembic/versions/0008_create_cost_decisions.py` (down_revision 0007). New `backend/src/api/cost_decisions.py` (+ `services/cost_decision_service.py`, `services/cost_pdf_service.py`, `templates/pdf/cost_report.html`). Routes: `POST /api/v1/validate/cost` persists + returns `saved:{id,url}`; `GET /cost-decisions` (list), `/{id}` (owner-scoped 404), `/{id}/pdf`, `/{id}/export.json`, `/{id}/export.csv`, `POST|DELETE /{id}/share`, public `GET /s/cost/{short_id}` (sanitized), `GET /cost-decisions/compare?ids=a,b`.
- Auth: added `/validate/cost/demo` to `scripts/ci/check_route_auth.py` PUBLIC_ROUTES (legit public demo, mirrors `/validate/demo`; the guard was failing on HEAD for it). `/validate/cost` is `require_role(analyst)`.
- Flag: `COST_PERSIST_ENABLED` (default ON; demo stays ephemeral).
- Verify (on REAL Postgres): migration up/down/re-up clean; full lifecycle works; public share leaks 0 PII (noindex, revocable→404); owner-scoping 404 cross-user; bad input never 500; honesty preserved (`validated=false`, "assumption-based, not yet validated", no "VALIDATED" stamp). Full suite 594/0. `outputs/verify/cost-persist.md`.
- Non-blocking notes: `/{id}/pdf` binary render needs WeasyPrint system libs (present in Docker, absent locally — same stack as working DFM PDF); persist wrapped in bare `except` (graceful degrade); `result_json.decision.recommendation`/`if_redesigned` keys become STRING after JSONB round-trip (handled).

**Item 4B — cost persistence FRONTEND.** Branch `feat/cost-persist-ui@fd3896b`, merge `03c357b`.
- Built: `CostArtifactBar` (save/PDF/JSON/CSV/share) on the cost surface; `app/(app)/cost-decisions/{page,[id],compare}.tsx`; public `app/s/cost/[shortId]/page.tsx`; extended `PdfDownloadButton`/`ShareButton`/`ShareModal` with `kind:'cost'`; `CostHonestyNote.tsx`; api.ts additions (fetch/download/export/share/compare); pure logic `lib/cost-decision.ts` (string-key recommendation reader; compare-diff formatter returns "—" not fake 0/NaN).
- Flag: `NEXT_PUBLIC_COST_PERSIST_UI` (default ON).
- Verify: high-conf PASS — no fake affordance (all wired to real endpoints via `/api/proxy`), honesty preserved, 17/17 tests, tsc clean, Turbopack build 20 routes. (Builder-log has the verdict; no standalone verify md.)

### PHASE 0 — design re-founding (started after founder pivot to "Databricks for manufacturability")

**P0-A — kill the Replicate egress** (honesty / F-ARCH-4). Branch `feat/p0-kill-egress@8ec1e0e`, merge `680757a`.
- Finding: image→mesh reconstruction defaulted to REMOTE → Replicate, silently egressing customer imagery (torch/tsr absent locally).
- Built: `DEFAULT_RECONSTRUCTION_BACKEND="local"`; remote requires explicit `RECONSTRUCTION_BACKEND=remote` or `RECONSTRUCTION_ALLOW_REMOTE_EGRESS=1` (truthy) + logs "DATA EGRESS ACKNOWLEDGED"; no-local+no-opt-in → `ReconstructionUnavailableError` code `RECONSTRUCTION_UNAVAILABLE` → `POST /api/v1/reconstruct` returns 501 (no job, nothing egressed); `/health` gains honest `reconstruction:{available,backend,egress}` block. Files: `services/reconstruction_service.py`, `api/reconstruct_router.py`, `api/health.py`, `jobs/worker.py`, `jobs/reconstruction_tasks.py`.
- Verify: default local confirmed, announce-unavailable no-egress confirmed, health honest. Full suite 603/0. `outputs/verify/p0-kill-egress.md`.

**P0-B — frontend re-founding** ("governed catalog" identity). Branch `feat/p0-refound@ec98897`, merge `4c17022`.
- Built: re-tokened `globals.css` to graphite dark-first + one cobalt (retired faceplate/well/bloom/blueprint/gauge-settle; provenance tiers held apart: MEASURED teal `#0E7C86`, SHOP bronze `#A9682A`, USER indigo `#5B4FC0`, DEFAULT hollow); Geist Mono hero numerics, 13px base; one 4-zone shell (`ui/app-shell.tsx`); `PartWorkspace` = the L2 **Decision** object frame (tabs Decision · Routing & DFM · Glass Box · Compare · History) absorbing the crossover scrubber "aha" in flat chrome; `GlassBoxDrawer`→`DecisionInspector` (Lineage/Governance/Sources/Audit). Deleted the losing Gen-3 cockpit shell (~2,360 lines: LivingInstrument, top-strip, DecisionReadout, QuantityScrubber, GhostPart, InstrumentControls, GlassBoxDrawer). Converged decision renderings onto DecisionHeadline+ConfidenceInterval+CostDecisionCard. Zero-egress badge scoped to `LOCAL_PATHS=[/cost,/analyze,/cost-decisions,/history,/batch]` (never reconstruction).
- Flag: `NEXT_PUBLIC_COST_PERSIST_UI` reused; dark-first default via a no-flash script (light pinnable).
- Verify: high-conf PASS, NO blockers — /analyze+/cost render the complete Decision frame; crossover wired to `lib/breakeven`; DFM tab + Phase-2 artifact intact; no fabricated %; identity re-founded. tsc clean, 17/17, MAIN-TREE Turbopack build 20 routes. (Builder-log verdict.)
- **Non-blocking:** `layout.tsx` still imports Archivo (fenced to marketing only) with a stale comment.

---

## 3. STRATEGY / PRODUCT DIRECTION (the "why")

- **North star (founder):** "**Databricks for manufacturability & cost**" — the governed DECISION layer (NOT all manufacturing data; that's Cognite/Palantir/operations). Deterministic engine = compute; provenance = governance/lineage; ground-truth = the data moat; a portfolio catalog = the lakehouse. Scope precisely to the decision layer.
- **Aramco / spare-parts research** (`outputs/research/aramco-spare-parts.md`): the MRO spare-parts-digitization / AM-on-demand play is real but a 4-function value chain owned by incumbents (Immensa, 3YOURMIND, Ivaldi, Replique, Siemens, DNV). Aramco's tie is INDIRECT (via Dussur/NAMI + a qualification/audit role); NO verifiable signed digital-warehouse SaaS contract. CadVerify's transferable asset = the deterministic triage + glass-box should-cost. It structurally CANNOT own 3 of 5 hard pieces (material ID = sensor; spec/tolerance authoring = mating part + engineer + its dead GD&T code; qualification = accredited body under API 20S/API 6A/DNV-ST-B203). Recommendation: reposition as the triage/DFM/should-cost BRAIN feeding a partner ecosystem, after killing the cloud egress (done, P0-A).
- **Platform "walls" (in backlog, `outputs/impl-state.md`, Phase-3 track):** W1 multi-tenant org/team/RBAC catalog (the Unity-Catalog analog; do first, expensive-later) · W2 ingestion/connectors (PLM/CAD/ERP + historical quotes) · W3 portfolio/batch COST compute · W4 governed rate/material/shop libraries as versioned assets · W5 ground-truth flywheel (machinery buildable; validation = Zoox gate) · async tier real + `/health` honest (redis lie F-ARCH-2 still unfixed).

---

## 4. THE DESIGN THREAD — this is the LIVE, OPEN work (read carefully)

Sequence of what happened:
1. **Design vision v1** (`outputs/design/platform-ia-vision.md`) — spine "**The Decision Catalog**" (`catalog.schema.table` metaphor), multi-persona Role-Lens saved views, phased plan (Phase 0 reconcile → Phase 1 W1 → additive walls). Founder steered: **dark-first**, **Decision-contains-Estimates**.
2. **Phase 0 built + shipped** (P0-A + P0-B above) and previewed on `:3100`.
3. **FOUNDER REJECTED Phase 0 as (a) a RE-SKIN** (same layout/IA, just recolored — true: Phase 0 was scoped as re-token+re-host) **and (b) generic "AI slop"** (the dark-graphite + one-blue = LLM-median dashboard look). This SUPERSEDES the dark-first choice.
4. **New taste anchors captured (founder):** register = **LIGHT & EDITORIAL** (escape dark entirely — paper/canvas, print-craft). Soul = **Cinematic & expressive** (Arc/Apple/Framer motion, theatrical reveals) + **Dense power done beautifully** (Palantir/Bloomberg gravitas, density-as-beauty) + **Tactile & made** (Teenage Engineering materiality, a crafted object). Bar: "not slop, an art piece you enjoy opening, Disneyland magic." Founder wants craft across UX/UI/IA/product-design/user-flow/journey/interactions/wireframes.
5. **Visual research done** (`outputs/design/visual-landscape.md`): the whole category has NO signature world (legacy-dense vs generic-clean; nobody has identity/type/materiality/a crafted moment). Named our exact slop-trap (`#080B0F` + one cobalt + shadcn + Geist = LLM median). Anti-slop AVOID/DO checklist. 5 magic-moment candidates (The Specimen, The Crossover, Provenance Assembles, The Hallmark, Commissioning). **5 whitespace WORLDS:**
   1. **The Assay Office** — reverent industrial materiality; light; brushed steel + marking-blue + brass; verdict struck as a hallmark.
   2. **The Should-Cost Journal** — editorial/data-journalism; warm paper; display serif + tabular mono; the decision as a signed engineering document.
   3. **The Metrology Bench** — precision-instrument (Teenage Engineering); anodized aluminum; safety-orange; gauges that sweep to a verdict.
   4. **The Foundry Ledger** — spatial/cinematic; the one DARK world (founder likely skips — chose light).
   5. **The Provenance Organism** — living-lineage/organic; bright; the reasoning graph grows/assembles.
6. **DELIVERABLE THE FOUNDER WANTS:** a **Design Brief** = "what to give cloud design" (tool-agnostic input package; or render in the connected **Open Design MCP**). Contains: product context + the thesis · personas & jobs · IA + flows + journey · the anti-slop constraints (explicitly NO dark-graphite+one-blue) · taste references · the chosen WORLD + palette/type/motion/materiality · candidate magic moments · exact screens · interaction/motion notes · deliverables & fidelity (wireframes → hi-fi → clickable hero flow).

### ⏳ THE OPEN DECISION (blocks the brief):
I asked the founder to pick the **WORLD** (single biggest design decision) from 4 curated-to-taste options (The Assay Journal [a recommended fusion of Journal+Assay], The Assay Office, The Metrology Bench, The Provenance Organism), each with a mood-board preview. **The founder REJECTED the question and wants to CLARIFY it first** — they may want to blend, see them rendered rather than described, bring their own metaphor, or push back on the "commit to one world" framing / the names. **Next action: resolve what they want to clarify, then land the world, then write the Design Brief (and optionally render 1-3 concepts in Open Design).**

---

## 5. OPEN THREADS / NEXT ACTIONS (prioritized)

1. **[LIVE] Design world-choice** — resolve the founder's clarification on the 4 worlds → land the world → write the **Design Brief** → optionally render concept(s) in Open Design MCP. Everything design flows from this.
2. **[PAUSED] W1 build** (task #6) — multi-tenant org/team/RBAC catalog + the Catalog home. PAUSED until the design direction is locked (build to the chosen world, not to Phase-0 dark).
3. **Founder-steer questions still open** (vision §8, non-blocking): Inspector default per persona; lifecycle State-column timing; a distinct Sourcing "Inbox" home; how much Palantir object-graph; **whether to re-found marketing (`/`, `/method`)** to the new look or keep the "instrument" beauty as its hero.
4. **Non-blocking cleanups:** remove Archivo import + stale comment (`layout.tsx`); the `/health` redis-lie (F-ARCH-2) is still unaddressed (separate async-tier item); a real-PDF smoke test in the Docker image; a soft-warning/metric on the bare-except cost persist path.
5. **Stop the `:3100` preview server** when done (it's a `nohup next start`).

## 6. HUMAN-GATE QUEUE (prepared, never self-certified)
- **Cost/DFM correctness → Zoox Head of Manufacturing** on real parts + real quotes → load into `groundtruth.py` held-out eval. Caveats to hand over (corrected 2026-07-04): CNC curve MAGNITUDE; sampled wall-thickness tail error (~567% at discontinuities); systematic bias from a hull/bbox stock proxy with NO feature recognition (pockets/holes/threads not modeled — direction plausible, magnitude wrong); the ±40–60% band is itself an n=0 assumption, not a measured error. NOTE: NRE (CAM programming) and first-article/in-process inspection ARE now costed (Zoox-caveated) — earlier drafts of this sheet wrongly said "no NRE/inspection". Packet basis: `outputs/verify/*.md` + `outputs/validation-packet.md` + `outputs/truth-engine-validation.md`.
- **Security → SAML vs a real IdP + pen test** (security engineer / accredited firm). Public cost-share sanitization already verified.
- **SOC 2 → auditor. ITAR/export + data-residency → legal** (Replicate egress now killed).
- **Load/soak → SRE** on real Postgres+Redis+worker (memory bounded; capacity envelope needs a real run).
- **Design → founder** steer (the live one).

---

## 7. ARTIFACT INDEX (produced/updated this run)
- **Plan (2026-07-02, post-handoff): `outputs/long-horizon-plan.md`** — the full long-horizon build plan (design track D−1→D4, gates G0a–G4, sprint sequence, walls W1–W5, engine-credibility split, human-gate queue). Survey-grounded + 3-critic adversarially reviewed. Supersedes the *sequencing* sections of `impl-state.md`; `impl-state.md` remains the item ledger.
- State: `outputs/impl-state.md` (backlog + Phase-3 walls), `outputs/impl-summary.md` (run summary), `outputs/impl-harness-log.md` (event log), `outputs/orchestrator-log.md`, THIS file.
- Verify verdicts: `outputs/verify/{dfm-scope-flags,cnc-volume,engine-memory,cost-persist,p0-kill-egress}.md`.
- Impl notes (builders): `outputs/impl/{dfm-scope,cnc-volume,engine-memory,cost-persist,cost-persist-ui,p0-kill-egress,p0-refound}-note.md`, `outputs/impl/phase2-persist-cost-spec.md`.
- Design: `outputs/design/platform-ia-vision.md` (vision v1), `outputs/design/visual-landscape.md` (visual research + 5 worlds). Plus 30+ pre-existing `outputs/design/*` from earlier design cycles.
- Research: `outputs/research/aramco-spare-parts.md`.

---

## 8. OPERATIONAL GOTCHAS / HOW-TO (so a resumer doesn't relearn the hard way)
- **Parallel builds use git worktrees** off `dev`. Gitignored dirs are NOT copied into worktrees → fixes:
  - Backend: symlink `ln -sfn <main>/backend/data <worktree>/backend/data` (else shop-profile tests in `test_cost_api.py` FAIL — `backend/data/shop_profiles/*.json` is gitignored via `data/`).
  - Frontend: symlink `ln -sfn <main>/frontend/node_modules <worktree>/frontend/node_modules`.
  - Run tests with the MAIN venv: `<main>/backend/.venv/bin/python -m pytest` from the worktree's `backend/` (imports the worktree's `src`).
- **Turbopack panics on the worktree node_modules symlink** ("points out of filesystem root") — build with `npx next build --webpack` in worktrees; the real Turbopack gate runs in the MAIN tree (real node_modules) — confirmed green.
- **Frontend is a NONSTANDARD Next.js** — read `frontend/node_modules/next/dist/docs/` before touching routing/data-fetching (there's an `AGENTS.md` warning).
- **Frontend API calls** go through the authed proxy: `API_BASE=/api/proxy` → `frontend/src/app/api/proxy/[...path]/route.ts` forwards to backend `/api/v1/*` with the session cookie. `next start` needs runtime `API_BASE=http://localhost:8000`.
- **Local run:** `bash scripts/run-local-app.sh` (needs Postgres role/db `cadverify`/`localdev`; real email+password auth, no dev bypass; secrets in gitignored `.env.local-auth`).
- **Full backend suite ~4.5–7.5 min.** Env-flag convention is per-module `os.getenv("NAME", default)` — there is NO central settings module.
- **Workflow lessons:** (a) transient `529 Overloaded` hits when too many agents run concurrently — keep concurrency modest, and resume workflows (`resumeFromRunId`) to recover (cached agents return instantly). (b) `pipeline()` returns only the LAST stage's result per item — to carry earlier-stage data forward, wrap the last stage: `stageN(...).then(r => ({prev, r}))`.
- **Adversarial-verifier pattern:** the 3rd parallel agent occasionally drops (returns null); verify the crux yourself as backup. Every merge to prod was gated on: finding-closed + honesty/no-lying-stub + demo-path-intact + full-suite green.

## 9. TASK LIST (harness tasks)
- #1 DFM scoping — DONE. #2 CNC volume — DONE. #3 engine memory — DONE. #4 persist/export/share/compare — DONE. #5 Platform IA/UX reconception (design-first) — marked DONE (vision + Phase-0 shipped) but SUPERSEDED by the founder's re-skin critique → the real design reconception is now the LIVE open work (§4). #6 W1 org-tenant-RBAC catalog — PENDING/PAUSED (blocked on the design world-choice).
