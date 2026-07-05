# CadVerify — Production-Readiness Assessment

_Founder-grade. No cheerleading. The house rule — "nothing that is a stub may masquerade as real" — is applied here to the assessment itself: where an assessor found nothing, this document says so instead of implying coverage._

**Assessment date:** 2026-07-04
**Basis:** four independent dimension reviews — Runnability, Functional completeness, Trust & correctness, Ops/enterprise.
**Coverage caveat (read this first):** three of the four dimensions were assessed against live code and a live process. **The Ops/Enterprise dimension returned no data (null).** So this report does NOT cover deploy hardening, secrets management, backups/DR, rate-limiting, observability, on-call, tenancy-at-scale, or cost controls. Treat anything ops-shaped below as *unassessed*, not *passed*.

---

## 1. Verdict

**No — CadVerify is not production-ready, and it is not yet pilot-ready either.** What it *is*, precisely: a **real, honest single-analyst costing-and-makeability engine** with a genuine glass-box should-cost model, a genuine Phase-C machine-verification block computed by ~1000 lines of real matcher logic (not stubs), and a trust layer that is actually enforced end-to-end on the live estimate path (confidence intervals on every estimate, byte-tight sum checks, provenance tags, adversarial "validated" guard). That core loop — drop a part → `/validate` (routing + DFM) → `/validate/cost` (should-cost + verification) → persisted, listable, exportable record — works end to end for **one authenticated analyst**. Everything around that core is either (a) honest, clearly-labelled in-development scaffolding, (b) present-but-unwired backend the frontend doesn't call yet, or (c) genuinely absent (multi-user org, Programs backend, audit/notifications). And the single most important thing a buyer pays for — *"the number is right"* — is **completely unproven**: n=0 real ground truth, every live estimate returns `validated=false`, and the ±40–60% band is itself a stated assumption, not a measured error. It runs on 3.9 locally today; it has *served an authed app* once (the older surface); the **new Verify instrument has never been observed running end to end**.

---

## 2. The blockers, ranked

Each tagged: **[blocks pilot]** vs **[blocks GA only]**, and **[we-can-close]** (our engineering, no external dependency) vs **[world-gated]** (needs real parts, real IdP, real deploy target, or time in the world).

### B1 — Accuracy is entirely unproven. n=0 real ground truth. **[blocks GA] [world-gated]** — the dominant blocker
Nothing has been validated. `backend/data/ground_truth/` and `backend/data/calibrations/` are both absent. Every live estimate returns `validated=false`, `method=assumption-band`, `n_samples=0`. The gate `groundtruth_service.py:71 MIN_REAL_RECORDS=8` raises `InsufficientGroundTruth` before the calibrated engine can run below 8 real records. This is the **correct, honest state** — the system refuses to launder synthetic data into a "validated" claim, and that moat holds through persistence (`confidence.py:155 validated=bool(from_real)`; stand-in defaults True; the calibration store re-derives `from_real` on restart so a reboot can't upgrade a stand-in band). **But honest-and-unproven is still unproven.** The docstring promise of "$X ± Y%, validated across N real parts" has never been earned. You cannot sell accuracy you have not measured. This is world-gated: it closes only by feeding ≥8 real parts with real quoted/actual costs through the loop — which requires the pilot partner. That is the strategic tension: **the thing that gates GA can only be closed by running the pilot.**

### B2 — The Verify instrument has never been observed running live, and the only live backend is stale. **[blocks pilot] [we-can-close]** — the cheap, urgent one
This is the fastest, highest-leverage fix and it is embarrassing to leave open. Three facts stack:
- **The one live backend is pre-merge and 404s the Verify contract.** Live PID 31026 (uvicorn, started before the Verify merge) returns `/api/v1/machine-inventory → 404` and `PUT /api/v1/part-context/{h} → 404`. Current code (`HEAD a6ce85b`) *mounts* both (`backend/main.py:242, :262`), and the Verify UI calls exactly these (`frontend/src/lib/verify/run.ts`). So **right now, nothing serves the Verify contract.**
- **No frontend is up** (ports 3000 and 3100 both empty), the **flag is baked OFF** in the current build (`NEXT_PUBLIC_VERIFY_UI` absent from `.next/static`, and `run-local-app.sh`/`.env.example` never set it), so the shipped default is the *older* surface.
- **Zero evidence it has ever run:** no `/verify` screenshots or run-logs anywhere in `outputs/`; the only e2e automation (`frontend/scripts/e2e-smoke.mjs`) covers the *unauthenticated marketing page only* and explicitly refuses authed runs.

Reading the code, the architecture is consistent (proxy `/api/proxy/* → /api/v1/*` with same-origin `dash_session`, `(verify)/layout.tsx` gates on flag then `verifySession()`, RBAC via `require_role`, writes behind `require_kill_switch_open` which the run script satisfies). **But "verified by reading" is not "observed running."** Until a fresh backend is up, the flag is on, and someone drives the full authed loop with a saved screenshot/run-log, the Verify product is *asserted*, not *demonstrated*.

### B3 — No multi-user org. Every user is auto-siloed into a personal org. **[blocks pilot] [we-can-close]**
`org_context.py:119 ensure_personal_org` is the **only** membership-creation path (sole `INSERT INTO memberships` at `:154`). There is no invite / add-member / create-org / switch-org endpoint anywhere in `backend/src/api` (grep returns nothing; no member/org router file). A second engineer at the same company gets an **isolated world**. That means: any pilot beyond a single seat is impossible, and the org-memory moat plus the SSO/team marketing are hollow. `feat/org-membership` exists but is **NOT merged to dev** (one WIP commit `4742b49`, self-labelled UNVERIFIED). This is pure engineering — we can close it — but it is a hard gate on any real design-partner pilot, which is never one person.

### B4 — STEP ingestion — the format real MEs actually send — is not deployable in this environment. **[blocks pilot] [we-can-close, but environment-hard]**
`step_parser.py:56` raises `RuntimeError "STEP parsing requires cadquery"`; both `import cadquery` and `import OCP` traceback in the backend venv. GD&T/PMI extraction from AP242 is blocked for the same reason (`gdt_extractor.py:7` degrades gracefully to nothing). A design partner who sends a STEP file hits a **hard wall**. Today the loop only truly works for STL. This is closable but not trivially — it needs the deploy target to ship the OCP native libs (OpenCascade C++), documented as "known-hard, not installable in this env." **Whether this blocks the pilot depends on the partner:** if they can send STL, it's a GA item; if they send STEP (most do), it's a pilot blocker. Resolve by asking the partner what they'll send *before* committing.

### B5 — Units and currency are silently locked to mm/USD with no detection. **[blocks pilot] [we-can-close]**
`drivers.py:50` divides mesh volume by 1000 assuming vertex units are **mm**; STL carries no units; so an **inch-authored STL mis-costs by 25.4³ (~16,000×)** with no warning. Currency is USD throughout (`rates.py` has no FX; region is only a labor multiplier). The failure mode is the worst kind: a **confidently-wrong number wrapped in a valid-looking ±50% band.** For a pilot this is a credibility landmine — one inch part and the tool looks broken or dishonest. Cheap to close (unit sniff + explicit unit field + hard warn on out-of-range volume), and it should be closed *before* any real part goes through.

### B6 — The documented local launcher never starts the arq worker. **[blocks pilot for async features only] [we-can-close]**
`scripts/run-local-app.sh` starts only uvicorn + next; no arq process runs. So batch costing, SAM-3D, reconstruction and webhooks **enqueue but never execute** — they hang. **The core Verify loop is unaffected** because validate/validate_cost are synchronous (`routes.py` returns results inline, no enqueue). `docker-compose.yml` *does* define a `worker` service, so the capability exists — it's just not wired into the local run path. One-line fix for local; matters for pilot only if the partner touches batch/3D. Trivial.

---

### Blockers that gate GA only (not the pilot)

These are real and must be honest, but they do not stop a scoped single-partner pilot:

- **B7 — The product is mostly honest scaffolding. [blocks GA] [we-can-close].** Of "14+ surfaces," only Home, Verify, Machines, Records are wired to the real engine. Catalog, Compare, Triage, Calibration & truth, Programs render `<StubScreen>` placeholders explicitly labelled "NOT YET BUILT — AND NOT FAKED" (`stub-screens.tsx`). Honest, but non-functional.
- **B8 — Several stubs already have working backends; the gap is frontend wiring. [blocks GA] [we-can-close].** `catalog.py` exposes `/portfolio, /triage, /makeability, /capability-investment`; `cost_decisions.py` exposes `/compare` — all mounted (`main.py:214,217`), none called by the UI. This is *cheap* GA progress: wire, don't build.
- **B9 — Programs has no backend at all. [blocks GA] [we-can-close].** No programs table/router/CRUD/lifecycle. "Program" is a free-text label; the "declare a world once at the program, exposure = verified unit cost × volume" story cannot be delivered as an object. This one is *build*, not *wire*.
- **B10 — The verdict can't take the cost-dominant process specs a real ME declares. [blocks GA] [we-can-close].** No surface finish (Ra), heat-treat (HRC), or inspection level (FAI) input on `/validate/cost` (`routes.py:1131-1171`). The engine bakes DEFAULT (Zoox-caveated) assumptions for these; the user can only nudge a generic overrides blob, never declare the spec. This is the #1 *verdict-credibility* hole after validation itself.
- **B11 — Shops/machines carry no certifications. [blocks GA] [we-can-close].** No AS9100/NADCAP/ISO/ITAR field, even though the aerospace rule pack already *demands* FAIR per AS9102. A "make outside" verdict cannot route to a qualified shop.
- **B12 — The environment door is single-vertical (O&G-shaped). [blocks GA] [we-can-close].** Fixed schema (temps, pressure, corrosive, sour, medium, standard); unknown keys rejected. Cannot express fatigue, biocompatibility, radiation, galvanic, or flammability — despite aerospace/automotive/medical rule packs existing.
- **B13 — Audit + notifications are stubs with nothing behind them. [blocks GA] [we-can-close].** Decisions, machine CRUD, library publishes, governance approvals emit no audit events; no `verification.completed`/band-flip webhook (grep returns none). The existing webhook infra is batch-job-only. The Calibration & truth surface's audit/delivery log renders as a stub. **Enterprise-relevant — and note this overlaps the unassessed Ops dimension.**
- **B14 — Systematic cost bias: bounding-box billet, no feature recognition. [blocks GA] [we-can-close].** Material is costed as a whole block sawn away (`drivers.py:68-85`, "[assumption, not shop-validated]"); pockets/holes/threads that change MRR and real cycle time aren't modeled. Cost is driven by a hull/bbox proxy, not the features an ME sees. Direction plausible, magnitude wrong — and it's exactly what validation (B1) will expose.
- **B15 — Wall-thickness geometry error on sampled CAD. [blocks GA] [we-can-close].** Dropping `RAYCAST_SAMPLE_THRESHOLD` 50000→5000 routes most real CAD (5k–50k faces) through the sampled/KDTree path, where the verifier measured tail error up to ~567% relative at wall-thickness discontinuities. A wrong wall flips the min-wall DFM gate and the molding cooling proxy — an ME would catch this on a real housing. This undermines the *makeability* verdict, not just cost.
- **B16 — Single watertight solids only. [blocks GA] [we-can-close].** Assemblies / non-watertight bodies are refused by the G1 gate as a structured 400; a mesh that fails to split is treated as one body. Weldments and multi-body sheet-metal are out of scope. Bounds the verdict to a fraction of real production CAD.
- **B17 — The ±40–60% band is itself an assumption. [blocks GA] [world-gated].** With n=0, the half-width is a per-family constant (CNC ±50%), honestly labelled "assumption-based, not yet validated." It tells the buyer nothing about *true* accuracy. Closes only with real ground truth (same gate as B1).
- **B18 — CNC learning-curve magnitude unvalidated (direction correct). [blocks GA] [world-gated].** Wright rate 0.90 / 30–60% envelope is DEFAULT-tagged; two small turned parts dip below the qty-flat reference at qty 1000 (known residual). Emergent, not a fudged constant — but the slope's real magnitude is unproven until validated.

### Minor / parity / hygiene (don't gate pilot; note for GA)

- **Prod-parity gap. [blocks GA] [we-can-close].** Local venv + running backend are **Python 3.9.6**; Dockerfile + fly.toml build on **3.12**. It runs on 3.9 today, but local runs don't prove prod-container parity.
- **Only email+password auth is runnable locally. [blocks GA] [world-gated].** Google OAuth, magic-link, SAML SSO are wired but need external IdP/deploy credentials not present. Enterprise-SSO login can't be exercised locally.
- **Trust-hygiene defect: the caveat sheet is stale. [blocks neither] [we-can-close].** `RESUME-HERE.md §6` tells the Zoox validation reviewer "no NRE/inspection," but the live engine now costs **both** (a CAM-programming NRE line and a first-article/in-process inspection line). Handing an auditor a caveat sheet that *understates* what the engine models is itself a truth-telling miss. Fix the sheet — cheap, and it's a house-rule violation to leave it.

---

## 3. Two bars, drawn clearly

### Bar A — "runs + works for a design-partner PILOT" (the minimum)
One design partner, a small number of named seats, sending real parts, getting a real should-cost + makeability verdict, and — critically — **feeding actuals back so validation can begin.** This bar is about *trust, multi-seat, and the ingest path being real*, not feature breadth.

Under Bar A: **B2** (must observe Verify running live on a fresh backend, flag on), **B3** (multi-user org — a pilot is never one person), **B5** (units — a wrong-unit part destroys credibility), **B4** (STEP — *conditionally*, gate on what the partner sends), **B6** (worker — only if the partner touches batch/3D). B1 is *entered* during the pilot (you start collecting the ground truth) but not *closed* — the pilot is how you close it.

### Bar B — "GA / production-ready" (the full bar)
Multiple orgs self-serving, the verdict credible across verticals, accuracy *measured and stated*, and the enterprise/ops surface real.

Under Bar B: **B1** (validated accuracy, ≥8+ real parts per family — the headline), **B17/B18** (measured bands and learning curve), **B7–B13** (the product actually built out: wire the ready backends, build Programs, add process specs, certs, multi-vertical environment door, audit + notifications), **B14/B15/B16** (feature-aware cost, correct wall thickness, multi-body support), **prod-parity to 3.12**, **SSO exercised against a real IdP**, and — flagged explicitly — **the entire unassessed Ops/Enterprise dimension** (deploy hardening, secrets, backups/DR, observability, rate-limiting, tenancy-at-scale). **GA cannot be declared until Ops is assessed at all.**

---

## 4. Shortest credible path to the PILOT bar

Ordered. **[WE]** = our engineering, no external dependency. **[WORLD]** = needs the partner, an IdP, a deploy target, or real time.

**Already done this session (don't re-litigate):** Phase C machine-verification block is real and wired; Phase D persistence is on; the Verify UI is built and architecturally consistent; org-membership is in flight on `feat/org-membership` (WIP, unverified).

1. **[WE] Boot a FRESH backend on current `HEAD` and prove the Verify loop live.** Kill stale PID 31026, start uvicorn from `a6ce85b`, set `NEXT_PUBLIC_VERIFY_UI=1`, run `next build`/`start`, sign in, drive drop→validate→validate/cost→record, and **save a screenshot + run-log to `outputs/`.** This closes B2 and is the single highest-leverage hour of work. *Blocks everything downstream — do it first.*
2. **[WE] Add the flag to the run path.** Set `NEXT_PUBLIC_VERIFY_UI` in `run-local-app.sh`/`.env.example` so the instrument, not the legacy surface, is the default for the pilot build. (Falls out of step 1.)
3. **[WE] Merge and verify org-membership (B3).** Take `feat/org-membership` from WIP/UNVERIFIED to merged-on-dev with a passing test: create org → invite → second seat sees the shared world. Without this there is no multi-seat pilot.
4. **[WE] Close the units landmine (B5).** Add an explicit unit field + STL unit-sniff + hard warn/refuse on out-of-range volume, so no inch part silently mis-costs by 16,000×. Do this *before* any real part is uploaded.
5. **[WORLD → then WE] Resolve STEP (B4).** Ask the partner what they'll send. If STL only → defer to GA. If STEP → get OCP native libs onto the deploy target (known-hard) and confirm `parse_step` runs. Don't guess; the partner's answer decides whether this is a pilot gate.
6. **[WE] Wire the arq worker into the run path (B6)** *if* the pilot scope includes batch/3D; otherwise scope those features out of the pilot explicitly and defer. One line either way.
7. **[WE] Fix the stale caveat sheet.** Update `RESUME-HERE.md §6` to reflect that NRE + inspection are now costed. House-rule hygiene; do it before handing anything to a validation reviewer.
8. **[WORLD] Run the pilot to START closing B1.** Feed ≥8 real parts per family with real quoted/actual costs; let the calibration store accumulate real records; watch the first estimates flip toward `validated=true`. **This is the point of the pilot** — and it's also the only path to the GA-gating accuracy claim.

Net: **steps 1–4 and 7 are a few days of our engineering** and get you to a *defensible* single-partner pilot. Step 5 is a partner conversation plus a known-hard deploy task. Step 8 is the pilot itself. **The critical realization for the founder: B1 (the GA blocker) and the pilot are the same activity — you can't validate accuracy without a partner, and the partner is your validation.** So the strategy is: get to Bar A cheaply and fast, then let the pilot manufacture the evidence that Bar B requires.

---

## 5. What's genuinely strong (the real asset under the gaps)

Don't let the blocker list bury this. Three things here are rare and hard-won, and they're exactly the things you *can't* fake later:

- **The engine is real, not a stub.** The core loop works end to end for one analyst: routing + DFM → glass-box should-cost → a Phase-C machine-verification block computed by ~1000 lines of real matcher logic (`makeability.py`: fit_machine, envelope failures, environment gate) with **no `NotImplementedError`, no stubbed gate.** Records persist, list, and export. This is a working instrument, not a demo.

- **The provenance and honesty discipline is enforced in the running code, not just claimed in docs.** On a real 24-estimate corpus run: **every** estimate carries a confidence interval (0 missing); `unit_cost == Σ line_items` byte-tight (0 violations, gate G3); every cost driver is tagged DEFAULT while only CAD geometry is MEASURED; cycle-time/hours are honestly DEFAULT; the literal "[assumption, not shop-validated]" shows on 6 of 8 drivers; 21 honesty-guard tests pass. The system tells the buyer *exactly* what it knows versus assumes. Most costing tools blur that line to look smarter; this one refuses to.

- **The adversarial "validated" gate holds — the moat is real.** `validated` can only flip true from ≥1 real, non-stand-in record; stand-in defaults True (fail-safe); the persistence layer *re-derives* `from_real` on restart so a reboot cannot launder a synthetic band into a validated one. The reason the accuracy is "unproven" (B1) is *because the system refuses to lie about it.* That is the correct, and commercially defensible, failure mode: it will earn "validated" the day real parts arrive, and not one minute before.

**The honest summary for the founder:** you have built the hard, un-fakeable part — a real engine with a real conscience. What's missing is (a) proof it runs as the new instrument (cheap, do it today), (b) a second seat (in flight), (c) a clean ingest path (cheap), and (d) real parts to earn the accuracy claim — which is the pilot itself. The gap between "impressive engine" and "sellable product" is a short, ordered list, not a rewrite. But it is not zero, it is not done, and — per your own #1 rule — this document will not call it ready when it isn't.
