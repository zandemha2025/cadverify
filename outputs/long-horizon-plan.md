# CadVerify — Long-Horizon Build Plan (product design + platform)

**Written:** 2026-07-02 by the orchestrator (Fable 5). **Supersedes** the sequencing sections of `impl-state.md` (which stays as the item ledger). **Grounded in:** `outputs/audit/platform-gap-map.md` + the five sub-audits (residue re-verified against source 2026-07-02), `outputs/design/{visual-landscape,platform-ia-vision}.md`, the design-corpus inventory, a backend/frontend state survey, the validation-machinery survey, and `outputs/research/aramco-spare-parts.md`.

**North star (unchanged):** *Databricks for manufacturability & cost* — the governed decision layer. Deterministic engine = compute; provenance = lineage/governance; ground truth = the moat; the portfolio catalog = the lakehouse. Scoped precisely to the decision layer (triage/DFM/should-cost brain feeding a partner ecosystem — per the Aramco research, we do not own material ID, spec authoring, or qualification).

---

## 0. Operating contract (how every item below gets built)

- **Orchestrator (Fable 5):** writes specs, sequences work, assigns agents, gates merges, runs founder steers, personally re-verifies the crux of every verifier verdict. Writes no feature code.
- **Builders (sub-agents):**
  - **Opus 4.8** — architectural/hard builds: W1 schema+RBAC, batch-cost coordinator, design-system foundation, signature-moment motion, world-concept renders.
  - **Sonnet** — standard feature work, surveys, adversarial verifiers, batched small fixes.
  - **Haiku** — mechanical sweeps once a pattern is established: org_id route threading, token renames, dead-code deletion, config hygiene.
- **Discipline per change (unchanged, non-negotiable):** feature branch off `dev` → tests green → WIP behind a flag → adversarial verification (2–3 skeptics with *distinct lenses*: finding-closed, honesty/no-lying-stub, demo-path-intact; orchestrator re-checks the crux) → merge to `prod`. `prod` stays demo-ready at all times.
- **#1 rule: no stub masquerading as real.** `/health` must not lie, no silent egress, no fabricated numbers. Every numeric change carries a Zoox-validation caveat; `validated` stays `False` until real quotes are measured.
- **Two human gates, never conflated:** (a) **Zoox numeric gate** — cost/DFM correctness needs a real manufacturing engineer + real quotes; (b) **external security gate** — real-IdP SAML, pen test, SOC 2, ITAR legal. Neither can be closed by more code; both get *prepared* by code.
- **Workflow mechanics:** parallel builds in git worktrees (symlink `backend/data` + `frontend/node_modules`; build worktrees with `--webpack`; final Turbopack gate in the main tree). Keep agent concurrency modest (529s). `pipeline()` over barriers; carry earlier-stage data by wrapping the last stage.

---

## 1. The map — six tracks, four gates

```
TRACK D  Design (LIVE gate: the world)        D0 world → D1 brief → D2 system → D3 moments → D4 reconcile
TRACK F  Foundations sprint (buildable now)   CI-Postgres · security quick-wins · async honesty
TRACK W  Platform walls                       W1 tenant/catalog → W3 portfolio cost → W4 libraries → W5 flywheel → W2 connectors
TRACK E  Engine credibility                   E-now (structure) → Zoox session → E-gated (coefficients)
TRACK S  Enterprise hardening                 medium items scheduled per sprint; external gates async
TRACK V  Human-gate queue                     Zoox · design-partner · IdP/pentest/SOC2/legal · load/soak
```

**Gates (the only hard orderings):**

| Gate | What it blocks | Why |
|---|---|---|
| **G0a — founder resolves the world QUESTION** | any concept rendering | The founder rejected the "pick one of 4 worlds" question itself — they may want to blend, see renders, bring their own metaphor, or reject the one-world framing. Resolving *what they want to decide* comes before building anything to decide with. |
| **G0 — founder lands the WORLD** | D1–D4 | Founder rejected Phase-0 as re-skin/slop; authoring more design in a dead register multiplies rework. Does **not** block W1 backend. Budgeted across Sprints 0–1 with an explicit 2-round loop — this decision already slipped once; the plan does not assume a clean single-pass close. |
| **G0b — D2 world foundation LANDED (not begun)** | every new-world UI surface (Catalog UI, Portfolio UI, moments) | The critic-verified failure mode: Sprint-2 UI "on D2 tokens" while D2 has only *begun*. New surfaces wait for the landed foundation; if G0/G0b slip, UI lanes swap for backend work (listed per sprint) — **never** "build it in the old register and re-token later," which is the rejected re-skin by another name. |
| **G1 — CI runs real Postgres+Redis** | merging the W1 org_id migration | Survey-verified: CI mocks `AsyncSession`, migration tests mock `alembic.op`; the backfill would ship to `fly` `release_command` with zero real-DB coverage. |
| **G2 — async tier honest+real** | W3 batch-cost, W5 recalibration job, session revocation | Batch cost rides the arq worker; `arq_backend.enqueue()` currently hardcodes `run_sam3d_job` (live bug); `/health` lies about Redis. **Hard Sprint-0 exit criterion** — no "or nearly." |
| **G3 — Zoox session** | E-gated coefficients, `validated=True`, measured bands | The single most important dependency per the cost audit: "the path to trusted is not more code; it is real ground truth." Prereqs: W5 plumbing landed (results must persist beyond the meeting) **and the E-now freeze checkpoint** — E-now merged to prod and the packet regenerated *from the merged build*, so the packet can never trail the served model. The session is scheduled when the checkpoint fires, not on a calendar slot. |
| **G4 — design-partner validation** | W2 first-connector choice, quote/RFQ depth | Audit: ask 3–5 real buyers which system a part arrives from before building a connector to a guess. |

Everything not behind a gate runs in parallel lanes.

---

## 2. TRACK D — Product design (the live thread)

The founder's rejection was of the **register** (dark graphite + one cobalt = LLM-median), not the substance. The survey confirms what survives and what doesn't:

**Survives (reuse, don't re-derive):**
- The **IA spine** — Decision Catalog, `workspace ▸ program ▸ part ▸ estimate`, Saved-View persona homes, lifecycle-state column, ⌘K, Inspector (`platform-ia-vision.md` §2–4). Register-agnostic.
- The **Phase-0 structural shell** — 4-zone `app-shell.tsx` (401 lines) already ships with Catalog/Portfolio/Sourcing/Governance/Connect as reserved rail slots; `PartWorkspace` (822 lines) is the single object frame for `/analyze` + `/cost`. The IA work remaining is *the Catalog route itself*, not the chrome.
- The **token indirection** — 80% of the component tree consumes semantic Tailwind-v4 tokens through a 3-layer `globals.css` indirection purpose-built for a world swap. A palette/type/motion re-found touches ~200 lines of CSS + `layout.tsx` fonts + ~25 hardcoded hexes (`cad-viewer.tsx` WebGL lights/materials, `PartWorkspace` SEVERITY_HEX).
- **Design-corpus equity:** `audience.md` (5 personas + opposing-needs matrix — lift as-is), `ia-and-flows.md` (F0–F6 flow map — lift as-is), `competitor-ux.md` + `design-landscape.md` (adopt/avoid patterns), `design-validation-protocol.md` (re-point at the new world), the **provenance grammar** (filled=grounded / hollow=guess; hatched=assumption / solid=validated — semantic, not a color choice), and the minable interaction logic (quantity-scrubber-as-chart, progressive hero render, ⌘K-over-admin-chrome).

**Dead (author fresh):** every token/type/color system in the corpus (indigo → steel-blue → Datum Blue, all dark-leaning); there is **zero prior light-register exploration**. The world's visual language starts from `visual-landscape.md`'s territories and nothing else.

### D−1 — Resolve the founder's clarification (G0a) ← THE ACTUAL OPEN STEP
The founder rejected the *question* ("commit to one of 4 worlds"), not just the medium. Before anything is rendered, one short founder conversation settles, in writing: **blend vs. commit vs. their own metaphor vs. renaming/reframing the territories** — and only then whether rendering is the right next move and *which* concepts to render. All four light-register territories stay on the table (**The Assay Office** as a standalone, **The Should-Cost Journal**, **The Metrology Bench**, **The Provenance Organism** — plus the Journal×Assay fusion as an *option*, not a pre-decision). Foundry Ledger (dark) stays shelved per the founder's light call. Nothing is pre-collapsed on the founder's behalf.

### D0 — Land the world (make taste concrete; budget two rounds)
Once G0a says what to build:
- **Round 1 is cheap and divergent:** low-fidelity boards per direction the founder named — palette/type/material studies + one hero-composition sketch each — for a fast founder gut-check *before* committing to full builds. The founder gates register from the first low-fi pass; no polished artifact is built on an unconfirmed direction.
- **Round 2 renders the survivors:** self-contained interactive HTML (Open Design MCP or Artifacts), each rendering the **same two surfaces** for apples-to-apples comparison — the Part Decision workspace (crossover scrubber as hero) + a Catalog glimpse — with real engine vocabulary (provenance chips, Σ=unit_cost, honest hatched confidence), the world's type/palette/**layout/materiality**/motion, and one signature moment sketched per concept. One **Opus 4.8 design-builder per concept** (parallel, isolated), fed the territory language, the anti-slop AVOID/DO checklist, the craft-bar moves, and the surviving IA.
- The Sonnet **slop-critic is a hygiene pre-filter only** (catches AVOID tells: near-black canvas, one-accent monoculture, uniform radius, default shadcn). It does not decide what the founder sees, and it cannot certify taste — **the founder is the only verifier of register.**
- Founder reviews → picks, blends, or counters. A second miss loops (that's what round-budgeting is for); it does not stall the program — backend lanes are explicitly world-independent.

### D1 — The Design Brief (the founder-requested deliverable)
Written by the orchestrator, assembled from parts that already exist + the D0 outcome:
product context & thesis · personas/JTBD (`audience.md`) · IA + flows + journey (`ia-and-flows.md` + vision §2–4) · anti-slop constraints (explicit: no dark-graphite+one-blue, no uncustomized shadcn, no uniform radius/border, **and no unchanged-layout-with-new-colors**) · taste references · **the chosen world**: palette/type/**layout-grammar**/motion/materiality spec · magic-moment specs (The Specimen, The Crossover, Provenance Assembles, The Hallmark — spent per the impact curve) · consolidated screen inventory (extract from `screen-a-notes.md`/`screen-b-notes.md`/`platform.md` — one Sonnet consolidation pass) · interaction/motion notes (named springs, productive-vs-expressive registers) · deliverable ladder (wireframes → hi-fi → clickable hero flow). Tool-agnostic: usable by cloud design or rendered in Open Design.

### D2 — Re-author the surfaces of the world (G0b closes when this LANDS)
**Not a re-token.** Phase-0 was rejected because "the layout and the sameness are the slop, not the hue" — recoloring the existing tree repeats that mistake. D2 changes **layout, grid, materiality, and component structure together with token values**: the world's layout grammar (editorial grid + serif verdict document, or brutalist spec-table with 1px gaps and no radius, or anodized panel + gauge — whatever the world demands) is authored as first-class layout work on each core surface. The token indirection and 4-zone shell are *engineering substrate* that make the mechanical part cheap (~200 CSS lines, `layout.tsx` fonts, ~25 WebGL/severity hexes, `lib/status.ts` maps) — they are not the strategy, and zone dimensions/chrome are allowed to change where the world requires it.
**Verify lens:** a per-surface **craft rubric that FAILS if the layout is unchanged** — squint test (does the most important element dominate?), the one-line slop test ("could a competitor reach this screen by prompting an LLM for 'modern SaaS dashboard for CAD'?"), world-specific materiality checks, type-with-opinion check, accent-rationing check — plus tsc/tests/build. Explicitly **not** judged by visual diff against the old screenshots; resemblance to them is a failure signal, not a pass signal.

### D3 — The signature moments (why it stops being a re-skin)
Built one per branch, each with a motion spec before code:
1. **The Specimen** — *first, because it is the always-on world-definer*: on upload the part materializes on a lit stage, one weighted rotation, signals etch onto the geometry. This is the default feel of every session; the episodic moments layer on top of it. Without it the space between ceremonies reverts to generic chrome — and the founder's complaint was the everyday register, not the absence of a climax.
2. **The Crossover** — the scrubber climax on the Decision tab (backed by `lib/breakeven`; the "aha" no incumbent ships).
3. **Provenance Assembles** — tap a figure → it rebuilds as the lineage graph (the deterministic claim made watchable; structurally un-reskinnable; becomes the Inspector's Lineage tab).
4. **The Hallmark** — the validated-state ceremony (lands with W5's `validated` promotion — the design and the data model meet here).
Plus first-run **Commissioning** when onboarding is built (Product-P1 #7).

### D4 — Reconcile the stragglers (founder steers pending)
- **Marketing (`/`, `/method`)** — currently the old blueprint-twilight identity, fenced. Founder steer: re-found to the world in lockstep, or hold as-is until the app world is proven. (Vision §8 Q9.)
- **Gen-2 surface** (`/analyses/[id]`, `/history` — ~1,850 lines, token-clean but IA-orphaned): fold into `PartWorkspace`/Catalog patterns during W1 UI, don't silently reskin.
- Delete orphans (`ProcessScoreCard`, `FeaturesList`), retire the Archivo import + stale comment.

**Track-D model note:** concept renders and the design system are *craft-critical* — these get Opus 4.8 with the richest prompts in the program, and the founder is the verifier of record on register; agents only gate slop/honesty/build-health.

---

## 3. TRACK F — Foundations sprint (all buildable now; no gate; start immediately)

Small, self-contained, high leverage. One Sonnet builder per cluster, standard verify, ~all parallelizable in worktrees.

| Cluster | Items (size) | Evidence |
|---|---|---|
| **CI gets real** (→ opens G1) | Postgres+Redis service containers in CI + a real `alembic upgrade head` smoke (M); make pyright blocking (S) | conftest mocks AsyncSession; migration tests mock `alembic.op`; F-ARCH-7 |
| **Security quick-wins** | HTTP security headers (S); webhook SSRF allowlist — block private/link-local/metadata ranges (S–M); SAML config `expandvars` fix (S); stop minting a new API key on every SSO login (S); `SESSION_SECRET` fail-closed in prod (S); DB `sslmode=require` default (S); Helm/env-example gaps (S) | Enterprise S2/S3/S5/S6/S7/S10, M4 — all re-verified present |
| **Async honesty** (→ opens G2 with F-ARCH-1) | `/health` stops lying about Redis (S); fix `ArqJobQueue.enqueue()` hardcoded job type (S–M); reject-don't-orphan on enqueue failure + stuck-batch sweeper (M); Redis-backed rate limiting required in prod (S); stream ZIP uploads, reject-early on size (S); env-driven pool size + coordinator session release (M); S3 batch input: implement or **remove the advertised params** until built — a lying stub today (M) | F-ARCH-1/2/3/5/6/9; arq bug survey-verified |
| **Engine hygiene** | delete 5 dead top-level analyzers (S); repair-route efficacy check on real non-watertight STLs (S, QA); verify Wright-curve work covers M3's fixture/yield sub-components (S, 30-min check); regression-check DFM values unchanged by the memory fix's sampling (S); real-PDF smoke test in the Docker image (S — WeasyPrint present there, absent locally); soft-warning/metric on the bare-except cost-persist path (S) | DFM #7, Cost S12/M3, arch validation note, RESUME §5.4 |
| **Frontend hygiene** | `lib/breakeven` + `lib/cost-views` unit tests (M); wire Playwright e2e + visual-regression baseline (M) — **before** the D2 re-token so the redesign has a safety net | survey: zero tests on the shared derivation layer; playwright-core installed, unused |
| Ops | stop the stale `:3100`/`:3000` preview servers (S) | RESUME §5 |

---

## 4. TRACK W — The platform walls

### W1 — Tenant/catalog (XL; the foundation; do first, brutal later)
Survey-verified fully greenfield: zero org/tenant scaffolding; 10 user-scoped tables; flat 3-role RBAC; `admin_routes.py` lists every user globally; ~43 authed routes across 10 routers on a uniform `WHERE user_id == user.user_id` idiom (good: the org version is the same mechanical pattern).

Build order (each its own branch/spec/verify; backend does NOT wait for G0):
1. **Schema + migration** (Opus): `organizations`, `teams`, `memberships`; `org_id` explicitly enumerated on **all ten** user-scoped tables — `users, api_keys, analyses, cost_decisions, jobs, usage_events, batches, batch_items, webhook_deliveries, audit_log` (count verified against migration head 0008; the spec re-counts at build time so any table added since is caught) — plus backfill (every existing user → a personal org). Gated on **G1**. Run against real Postgres in CI + a production-clone rehearsal.
2. **RBAC redesign** (Opus): org-scoped roles; superadmin vs org-admin split; `auth/models.py` raw-SQL helpers get org resolution; backward-compat for the existing role column.
3. **Route threading** (Sonnet establishes the pattern on 2 routers → Haiku/Sonnet sweep the rest): org resolution dependency + query filters through ~43 routes and services. Adversarial verifier lens: *cross-tenant isolation* — every list/get/delete provably scoped, with `/cost-decisions/*` (the flagship artifact) asserted by name (this is also enterprise M1; one workstream).
4. **Catalog API** (Sprint 1, same lane — pure backend, needs only the org-scoped schema, not G0/D2): the lakehouse read surface — parts×decisions grid query with facets, saved-view persistence, lifecycle-state column (Drafted/Costed only at first — vision §8 Q3 defaulted to "early, mostly-empty" unless founder objects). Lands a sprint *before* the UI so the UI consumes a real API, never races one.
5. **Catalog Explorer UI** — the first surface **born in the world** (post-**G0b**): the rail slot and sidebar placeholder already exist; build the route/page/grid + Saved Views + role-lens landing. **Craft note (critic-verified risk):** a bare facet-grid is the exact e-commerce/BI cliché the research names as the category failure — the Catalog ships with its own materiality (the world's spec-table treatment for rows, hero-object thumbnails) and one small signature beat (parts *admitted* to the catalog via the Specimen — the "Part 001" plate), and first founder contact with the world should be the Decision workspace with The Crossover, not the grid. Admin UI (M — the API already exists) and search/projects/tags (M) ride this wall. Collaboration primitives (M) and notifications (S–M) follow once orgs exist.

### W3 — Portfolio/batch cost (L–XL; the enterprise value story; after G2)
Batch pipeline is DFM-only (`batch_tasks.py` calls `run_analysis`, never `cost_decision_service`; `BatchItem` has no qty/region/material/shop fields). Build: batch-cost job type + item params + coordinator (reuse the webhook infra — solid — and the `groundtruth.py` per-part×qty loop pattern) → portfolio roll-up API (`GROUP BY` over the catalog) → Portfolio UI (ranked cost-down board, posture bar, drill-to-rows) in the world. Portfolio-level scenarios/compare (M) and the CO₂ checkbox metric (S–M) attach here. **Pre-build validation (G4-lite):** show a design partner the mocked ranked-savings report first — the audit's own advice.

### W4 — Governed libraries (L; the catalog's content)
Today: `RATE_CARD_V0` is a hardcoded 487-line dict with **no API at all**; shop profiles are 2 flat JSON files (read-only GET); materials are code+YAML. Build: DB-backed, versioned, effective-dated rate/material/shop assets + CRUD + engine cache invalidation → asset-detail UI (Overview·Versions·Usage·Lineage) → Governance zone (change request → review → publish → re-cost consumers, downstream-impact count). Material library expansion (carbon/alloy steels, corrected $/kg — Cost M6) lands *as governed data*, not more hardcoded constants. Supplier/shop directory (M) attaches here.

### W5 — Ground-truth flywheel plumbing (M-heavy; land BEFORE the Zoox session)
The math is real and tested (22 tests: no-leakage split, tuner, held-out evaluate, ResidualModel); the plumbing is absent — today a completed Zoox session's results **evaporate on server restart**:
1. Groundtruth ingest REST API (M) — kill the Python-REPL requirement.
2. Persist tuned `Calibration` + load-and-apply in `estimate_decision()` (M) — `EstimateOptions` has no calibration field today.
3. Wire `ResidualModel` into live `POST /validate/cost` (S–M) — measured CIs never reach the served product today.
4. Recalibration job on new records (M; needs G2).
5. `CostDecision` lifecycle/`validated` column + link-to-ground-truth migration (L) — the Hallmark moment's data model; overlaps the future award flow.
Note: the marketing page already **publicly promises** this flywheel ("send back real costs → band flips solid") — closing it is a product-integrity item, not just roadmap.

### W2 — Connectors (L; last on purpose; after G4)
No integrations exist beyond outbound webhooks and the broken S3 stub. Sequence: fix/remove S3 (Track F) → historical-quote CSV import (cheap, feeds W5 directly) → **one** CAD/PLM/ERP connector chosen by asking 3–5 real buyers (G4) → sync monitor/field-mapping UI (Connect zone). Live material-price feeds (Cost M9) slot here. The RFQ/quote object + Sourcing Inbox + award-closes-the-flywheel flow (XL) is the W2/W5 convergence and depends on W1; it is the *last* major build in this horizon.

---

## 5. TRACK E — Engine credibility (the numbers themselves)

Split hard by the two halves of every item: **structure is buildable now; coefficients are Zoox-gated.** Sequence the E-now sprint **before** the Zoox session so Zoox validates the improved model, not the known-wrong one — then regenerate the validation packet.

**E-now (structure, with DEFAULT-provenance + caveats):**
- Hull→bbox billet stock w/ configurable allowance (M) — verified 2.6× understatement.
- Region model: scale only the labor component, not whole machine rate (S) — isolated formula bug.
- CAM programming/NRE + FAI/inspection cost lines (M) — qty-1 badly under-costed today.
- Secondary finishing as outsourced lot charges; perishable tooling/consumables (M).
- IM: real shot overhead, cavity/complexity params surfaced (M). Additive: supports/rafts/removal (S–M). Sheet: nesting/scrap credit (M).
- Tolerance/finish **input surface** + honest "no tolerance ⇒ wider band" wiring (L; coefficients Zoox-gated; the GD&T dead code needs OCP installed or a user-entered-tolerances path — STL has no path at all today).
- DFM: 3-axis undercut severity fix (S), real rib check (S–M), flat-disk routing (S), material-class input — kill polymer-by-default, an API-578-grade credibility risk per the Aramco research (M), setup/fixturing reasoning (M), orientation/parting-line search (L, can trail).
- DFM verdict confidence when wall thickness came from the sampled path (S–M) — pairs with the known ~567% tail-error caveat.

**E-gated (post-G3):** every coefficient above; the threshold table (per-process, then per-material); feature-based CNC cycle time (XL — shares the feature-recognition engine with DFM's holes+flats gap; spec as ONE workstream); measured residual bands replacing ±40% assertion; per-process DFM depth beyond the rib check (molding sink/weld-line/gate, casting parting-line/riser, sheet bend-relief/K-factor/min-flange — DFM MISSING-7, sequenced by what Zoox flags as trust-critical); offshore landed cost — freight/duty + queue/capacity realism (Cost M10 — material to the crossover, parked here because its coefficients are meaningless before real quotes exist); process-coverage expansion (casting/forging/EDM/DMLS — XL, sequence by what Zoox/design partners actually quote).

---

## 6. TRACK S — Enterprise hardening (beyond the Track-F quick wins)

Scheduled one cluster per sprint, not as a big-bang: session revocation store (M; needs Redis/G2) · audit-log hash chaining + fail-loud writes (M) · MFA + lockout + password reset (M) · encryption-at-rest: disk-level first, envelope encryption of `result_json`/blobs second (M) · SCIM/deprovisioning + IdP-group→role mapping (M) · CI SAST/dep-scan/secret-scan (S–M each) · observability: metrics/tracing/alerting (M) · queue-depth backpressure/load-shedding + interactive-vs-batch priority isolation (S–M) · analysis out of the web process into a memory-capped, cancellable worker + embreex install (L — the arch-P0 *residual*: the acute OOM is closed, but a cooperative timeout still can't kill a runaway ray-cast thread; scheduled with the observability cluster) · blob-storage abstraction + lifecycle/GC (M) · backup/restore + DR runbook with stated RTO/RPO (M) · data lifecycle/DSAR (M) · billing/plans (M; when a design partner needs it). External gates (V): real-IdP SAML cycle, pen test, SOC 2 readiness, ITAR/legal — schedule the IdP test as soon as the S-cluster quick wins land; the rest after W1 (tenant isolation is what a pen test will probe).

---

## 7. TRACK V — Human gates (prepared, never self-certified)

| Gate | Prereqs we control | Action |
|---|---|---|
| **Zoox session** (G3) | W5 plumbing landed; E-now sprint landed; packet regenerated (6–8 parts, 7 disproof questions, protocol doc is ready as-is) | Founder schedules; ~60–75 min per protocol; results ingest via the new API so they persist |
| **Design-partner validation** (G4) | Mocked ranked-savings portfolio report; persona/wedge question sheet | Decides: front-door persona, first connector, quote-workflow depth |
| **Founder design steer** (G0) | D0 renders + slop-critic pass | The world decision; then §8 steers (inspector default, state-column timing, object noun, sourcing inbox, marketing lockstep) |
| **Security externals** | Track-F quick wins; W1 isolation | Real-IdP SAML → pen test → SOC 2 → ITAR legal, in that order |
| **Load/soak** | G2 async real; observability | SRE run on real Postgres+Redis+worker; measured capacity envelope |

---

## 8. Sprint sequence (dependency-ordered; lanes run in parallel within each sprint)

**Sprint 0 — "Stop the lies, open the gates"**
- Lane 1: **D−1 clarification with the founder (G0a)** → D0 round 1 (low-fi divergent boards, founder gut-check) → round 2 renders if the founder confirms.
- Lane 2: Track F in full (CI-Postgres · security quick-wins · async honesty · hygiene · e2e baseline).
- Lane 3: W1 **spec** (schema/RBAC/threading plan written and reviewed while CI work lands).
- Exit criteria (hard): **G1 open; G2 fully closed** (a full sprint of buffer remains before W3 needs it); G0a resolved. G0 (world landed) is *hoped for* here but budgeted through Sprint 1 — its slip idles no lane below.

**Sprint 1 — "Foundation + brief"**
- Lane 1: close **G0** (D0 round 2 / loop) → **D1 Design Brief** → founder sign-off → **D2 surface re-authoring** starts immediately and must *land* (G0b) before any Sprint-2 UI.
- Lane 2: **W1 backend** — schema+backfill → RBAC → route threading → **Catalog API**. This is a *sequential chain*, not four parallel builds (the isolation-verifier is the star here).
- Lane 3: **E-now wave 1** — the S/M items that most distort the Zoox packet (bbox stock, region formula, NRE/inspection, finishing lot charges, IM/additive/sheet, DFM severity fixes, material-class input) → **E-now freeze checkpoint**: wave 1 merged to prod, packet regenerated from the merged build (G3 prereq — Zoox gets scheduled when this fires). The L-sized wave-2 items (tolerance input surface, orientation search) trail without blocking the freeze and join the *next* packet regen.
- Lane 4: **W5 plumbing** (ingest API, calibration persistence, residual wiring; the recalibration job needs G2 — closed in Sprint 0).
- Lanes 2–4 are **explicitly world-independent**: a G0 loop costs the program nothing here.
- **Concurrency discipline:** lanes are logical tracks, not simultaneous agent counts — at most 3–4 builders active program-wide at any moment (RESUME §8: 529s), and the two Opus-grade builds (W1 schema/RBAC vs. D2 foundation) are *staggered*, never co-scheduled: W1 schema leads the sprint, D2 starts after D1 sign-off. If both cannot fit, W1 threading spills into Sprint 2 rather than parallelizing harder.
- Exit: org_id migration merged with the cross-tenant verifier green across all ~43 routes (`/cost-decisions/*` asserted by name); Catalog API serving org-scoped data; E-now freeze checkpoint fired; calibration survives a server restart; Design Brief signed off.

**Sprint 2 — "The catalog is born in the world"**
- Lane 1 (requires **G0b**): **Catalog Explorer UI** + admin UI + search/tags; D3 moment #1 (**The Specimen** — the always-on world-definer) and #2 (**The Crossover**) on the Decision workspace, which is the founder's first-contact surface with the world. *If G0b slipped:* this lane swaps for backend work pulled forward (W4 asset schema, observability, session-revocation store) — it does **not** build UI in the old register.
- Lane 2: **W3 backend** (batch-cost job type + portfolio API; G2 closed in Sprint 0).
- Lane 3: Gen-2 surface reconciliation (`/analyses`, `/history` folded into the world's patterns).
- External: **Zoox session happens** (scheduled off the Sprint-1 freeze checkpoint).
- Exit: Catalog UI live behind its flag with the Specimen beat; Decision workspace carries The Crossover in the world; batch-cost job type runs a 100-part portfolio on real infra; Zoox ground truth ingested via the API (first non-stand-in rows on disk).

**Sprint 3 — "Portfolio + proof"**
- Lane 1: **Portfolio UI** (ranked cost-down board) in the world; D3 moment #3 (**Provenance Assembles** = Inspector Lineage).
- Lane 2: **E-gated wave 1** — apply Zoox coefficients/thresholds; first measured band; first `validated=True` rows; **The Hallmark** ships with them (design meets data model).
- Lane 3: **W4** rate/shop/material assets + Governance zone.
- External: design-partner sessions (G4); real-IdP SAML test.
- Exit: first measured (non-asserted) accuracy band served by the live API; first `validated=True` decision with its Hallmark; Portfolio UI drills from aggregate to lineage; rate-card served from a versioned DB asset (not the 487-line dict); G4 answered (persona + first connector chosen).

**Sprint 4 — "Governed + connected"**
- Lane 1: W4 completion (effective-dating, re-cost-on-publish, downstream impact).
- Lane 2: **W2 start** — quote CSV import (feeds W5), first buyer-validated connector.
- Lane 3: Marketing re-found (if founder steered yes) + Commissioning onboarding; S-cluster continues (encryption, sessions, MFA).
- Exit: publishing a rate-card version re-costs its consumers with a visible downstream-impact count; historical quotes importable by CSV; first connector syncing real buyer data in a sandbox.

**Sprint 5+ — "Close the loop"**
- RFQ/quote object + Sourcing Inbox + award-validates flow (the W2/W5 convergence; the flywheel closes end-to-end).
- Assemblies/BOM (XL) and process-coverage expansion (XL) — sequenced by what design partners actually ask for.
- Pen test → SOC 2 → load/soak as the external calendar allows.
- Exit (the horizon's definition of done): a returned quote, awarded in-product, becomes a ground-truth row that recalibrates the engine and advances its Decision to `Validated` — the marketing page's public promise, kept end-to-end.

---

## 9. Parked / explicit decisions for the founder

1. **The world question (G0a, live — the very next conversation):** how do you want to land the world? Blend territories, commit to one, bring your own metaphor, rename/reframe them — and is seeing them rendered the right way to decide? All four light territories (Assay Office standalone, Should-Cost Journal, Metrology Bench, Provenance Organism, plus the Journal×Assay fusion *as an option*) remain live; nothing has been collapsed for you. Everything in Track D flows from this.
2. **AI copilot (audit Product-P0 #4):** category peers are AI-native; we have zero LLM anywhere. Recommendation: **park until W1+W4 land** — the copilot's differentiator is grounding on governed provenance ("why is this number, how do I reduce it"), which doesn't exist as a queryable asset until the catalog + libraries do. Revisit at Sprint 3 exit. It is deliberately *not* on the current critical path — say the word if you disagree.
3. **Vision §8 steers** (all nine accounted for; defaulted where cheap to flip): Q1 Inspector resident-for-cost-lens only · Q2 light default — superseded by the world decision itself · Q3 lifecycle State column appears in Sprint 2 (mostly empty) · Q4 object noun "Decision" · Q5 Sourcing Inbox deferred to W2 · Q6 design-engineer landing defaulted to the narrow "My parts" saved view **with** a prominent dropzone (the vision's own proposal) · Q7 Palantir object-graph scope defaulted to **lineage-DAG only** — no Object-Explorer search-arounds this horizon · Q8 zero-egress-before-badge — already resolved (P0-A shipped) · Q9 marketing lockstep decision due at Sprint 3 exit.
4. **Wedge/persona priority (G4):** cost-engineering vs DFM-buyer front door — a design-partner question, not a code question; it steers W2 vs deeper-DFM investment.

## 10. Anti-goals (so scope holds)

- No dark-register work anywhere until the light world is proven (Foundry Ledger stays shelved).
- No new numeric claims without provenance tags + Zoox caveats; no `validated=True` from code alone, ever.
- No building the identifier/material-authority/qualification pieces (Aramco research: structurally not ours — we are the triage/should-cost brain feeding partners).
- No second connector before the first has a real buyer using it.
- No big-bang rewrite of the frontend — but **no re-skin either**: the shell's zones and the token indirection are engineering substrate, not the design strategy. The world is authored at the surface level — layout, materiality, type, motion. A surface that ships with unchanged layout + new colors fails review by definition.
- No polished design artifact built on a direction the founder hasn't gut-checked at low fidelity first.

## 11. Standing verification pattern (every merge)

```
spec (orchestrator) → builder (worktree, flag) →
  verifier A: finding actually closed (repro before/after)
  verifier B: honesty — no lying stub, no fabricated number, flags/off-switches work
  verifier C: demo-path intact (/analyze, /cost, catalog once it exists) + full suite green
→ orchestrator re-verifies the crux → merge dev → prod fast-forward
```
Third verifier occasionally drops (known); the orchestrator's crux-check is the backstop. Isolation-sensitive merges (W1) add a dedicated **cross-tenant adversarial verifier** (asserting `/cost-decisions/*` scoping by name). Design merges swap verifier A for the **craft rubric** (fails on unchanged layout; squint test; one-line slop test) — the slop-critic checklist is a hygiene pre-filter, and **the founder is the only verifier of register/taste**.
