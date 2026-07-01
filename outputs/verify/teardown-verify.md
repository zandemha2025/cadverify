# CadVerify — Teardown Remediation Verification

**Verifier role:** independent check of F1, F2, F3, F5 against the *original* teardown
findings and their cited evidence. Ran the live gated stack (Postgres + secrets +
uvicorn :8000), the cost CLI, and a 105-part batch over the real automotive corpus.
**Date:** 2026-06-29. **Decision: COMPLETE** — F1/F2/F3/F5 are closed to the bar the
teardown set. The *correctness* of the per-shop numbers (F1) and the routing
process/number (F2) is NOT self-certified and is queued for the real expert (see
`expert-validation-packet.md`).

Environment used:
- Backend: `DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify`,
  `DASHBOARD_SESSION_SECRET`, `API_KEY_PEPPER`, `ACCEPTING_NEW_ANALYSES=true`,
  `LABELING_ENABLED=1`, `uvicorn main:app :8000`. Health: `{"status":"ok","postgres":true,"redis":true}`.
- Login verified: `nazeem+livetest@anodeadvisory.com` → HTTP 200, role `analyst`.
- Engine: `backend/.venv/bin/python -m src.costing.cli` (per-shop `--shop`, `--set`).
- Test part for marketing fixture: `backend/.venv/share/doc/gmsh/examples/api/object.stl`
  (the `object.stl` the marketing data captions). Corpus: 105 real STL parts in the
  scratchpad `parts/` dir.

---

## F1 — the wedge (per-shop calibration) is now IN the product — **CLOSED**

**Teardown evidence:** cost API had NO shop param (`routes.py` POST `/validate/cost`
~585-615 + `/validate/cost/demo`); a signed-in buyer saw "Not calibrated — generic
defaults"; switching shops just toasted a "build gap" (`PartWorkspace.tsx` ~391-396);
the `$14.14 / Midwest Precision CNC` marketing hero was a HARDCODED fixture while the
engine returned a different number on a real part; per-shop calibration worked ONLY in
the CLI.

**What I verified (gone / present):**

1. **Cost API accepts a shop (+ region/overrides) param.** `backend/src/api/routes.py`:
   `_run_cost_decision(... shop, overrides ...)` builds `EstimateOptions(shop=shop_slug,
   rate_overrides=..., region_is_user=...)`; both `POST /validate/cost` (line ~720, role
   `analyst`) and `POST /validate/cost/demo` (line ~774) expose `shop` + `overrides`
   form fields. Helpers `_resolve_shop_param` (slug/name → profile, 400 on unknown,
   path-traversal-safe), `_parse_overrides` + `_validate_overrides` (clean 400 on bad
   key/value).
2. **Live API returns a SHOP-calibrated number (not generic).** `POST /api/v1/validate/cost/demo`
   on `object.stl`, qty 10:
   - GENERIC (no shop) → make_now mjf **$7.50**, crossover 3546
   - `shop=Midwest Precision CNC` → make_now mjf **$14.14**, crossover 1962
   - `shop=Shenzhen Contract Mfg` → make_now **dlp $5.68**, crossover 819 (process flips)
   - Authed `POST /api/v1/validate/cost` (dash_session cookie) + `shop=Midwest` → **$14.14** (same).
   - Unknown shop / bad override key → **HTTP 400** (clean, not 500).
3. **`GET /api/v1/shops` exposes the bindable profiles** (gated: 401 unauth; authed
   returns `midwest-precision-cnc` (US) and `shenzhen-contract-mfg` (CN) with sources).
4. **Live UI binds a shop and re-costs (no more "build gap" toast).**
   `frontend/src/components/workspace/PartWorkspace.tsx`: `getShops()` populates the
   picker; `CalibrationBar` receives `shops`/`activeShopId`/`onSelectShop`; `onSelectShop`
   → `recostWith` → `runCost` (a real `costEstimate` call). The live `ShopPicker`
   (`frontend/src/components/glass-box/calibration.tsx`) shows "Bind a shop — re-costs"
   and a re-costing spinner. `frontend/src/lib/api.ts` `costEstimate` appends
   `shop` + `overrides` to the form.
5. **Marketing no longer captions a contradictory hardcoded fixture as "real output."**
   `frontend/src/components/marketing/data.ts` is now the engine's REAL output, and I
   re-captured it from the CLI: `object.stl` + Midwest yields make_now mjf **$14.14 @
   qty 10 / $10.45 @ 1000**, crossover **1962**, routing rotational→cnc_turning conf
   **0.8**, geometry volume **4.63 cm³**, bbox **21.2×21.4×21.5 mm** — every value in
   the fixture matches the live engine (verified 2026-06-29). The landing page
   (`src/app/page.tsx`) and `/method` import this verified fixture.

**Self-cert boundary:** that $14.14 (Midwest) / $5.68 (Shenzhen) are the *right* dollars
for these parts is a correctness claim → **queued for the Zoox Head of Manufacturing.**

---

## F2 — routing never headlines a process its own DFM hard-fails — **CLOSED (structure)**

**Teardown evidence:** RoutingCard said "cnc_turning, rotational, 0.80" while the DFM
matrix flagged cnc_turning FAIL "lacks rotational symmetry". Root cause: `routing.py:41-47`
computed "roundness" as bounding-box squareness (an 85×88mm lid scored 0.97) vs
`checks.py:553-575` which uses an inertia-eigenvalue rotational test. Systematic on 4/5
printed parts.

**What I verified (gone / consistent):**

1. **One definition of "rotational."** `backend/src/costing/routing.py` `is_rotational()`
   now requires `_inertia_axisymmetric(mesh)` — the SAME inertia-eigenvalue test as the
   DFM gate `checks.check_rotational_symmetry`, at the SAME tolerance **0.15**
   (`cnc_turning.py:24` calls `check_rotational_symmetry(..., tolerance=0.15)`;
   `routing.ROTATIONAL_INERTIA_TOL = 0.15`). So `routing rotational ⟹ the DFM
   rotational check passes` by construction — the bbox-squareness path can no longer
   call a flat lid "turnable."
2. **Belt-and-suspenders headline guard.** `_avoid_dfm_failed_headline()` demotes the
   routing headline to a DFM-clean process whenever the archetype's primary process has
   DFM verdict `fail` on that part (catches L/D, wall, draft fails too, not just
   rotational). The make-vs-buy crossover (the wedge) is untouched — `eligible_processes`
   still costs the tooling route; only the headline badge stops contradicting the matrix.
3. **0 violations across 105 real parts.** Batch (`scratchpad/f2_check.py`): for every
   part I compared `routing.recommended_process` against the set of DFM-`fail` processes
   in `engine_feasibility`. **F2 VIOLATIONS: 0 / 105.** Every routing headline's own DFM
   verdict is `pass` or `issues` — never `fail`. Lids/covers (Ancel_Lid, Speeduino Lid,
   obd_cover, etc.) now route to `thin_wall_enclosure → mjf`/`sheet_metal`, not turning.
   The 16 rotational/turning headlines (throttle bodies, ducts, adapters) all carry DFM
   `issues`/`pass`.
4. **Marketing fixture is internally consistent AND real.** `object.stl` engine output:
   routing cnc_turning + `cnc_turning issues(0.9)` (NOT fail) — RoutingCard and DfmMatrix
   in `/method` Stage 02 agree. The old self-contradiction is gone; `design-system/fixture.ts`
   matches (cnc_turning `issues`).

**Self-cert boundary:** whether cnc_turning / mjf is the *right* process and the dollar is
in-range on the Zoox parts is a correctness call → **queued for the real expert.**

---

## F3 — override actually re-costs (not a toast) — **CLOSED**

**Teardown evidence:** "Override → re-runs" was FALSE — assumption/driver edit handlers
only relabeled client-side and toasted "Server re-cost is a build gap"
(`PartWorkspace.tsx` ~189-210; `driver-breakdown.tsx` ~90); the number never moved;
"Save as scenario" didn't persist.

**What I verified (the number truly moves):**

1. **Engine + live API move the number on override.** CLI Midwest `--labor-rate 150`:
   qty10 mjf **$14.14 → $33.52**, crossover 1962 → 864, `labor_rate` tagged **USER**.
   Live `POST /api/v1/validate/cost/demo` with `shop=Midwest` + `overrides={"labor_rate":150}`
   → **$33.52** (same as engine). Bad override key → clean **400**.
2. **The UI override loop calls the cost API.** `driver-breakdown.tsx` `onOverride(driver,
   value)` (button "Override … — re-tags USER, re-costs") → `GlassBoxView` `onOverrideDriver`/
   `onOverrideAssumption` → `PartWorkspace` `onApplyOverride(key, value)` → `recostWith({
   ...opts, overrides })` → `runCost` (real `costEstimate`). `n_cavities` → `onSetCavities`
   → real re-cost. The "Server re-cost is a build gap" toast is **gone** (grep: no
   occurrence in the F3 path).
3. **Save-as-scenario now works.** `onSaveScenario` persists the option set + resulting
   unit cost to session state and toasts "Saved to this session — click it to recall and
   re-cost"; `onRecallScenario` → `recostWith` re-costs. Honestly labeled session-local
   (not a false cross-session-persistence claim).

---

## F5 — credibility hygiene (dev tools + honest marketing) — **CLOSED**

**Teardown evidence:** internal dev tools shipped in the CUSTOMER sidebar — "Parts
(Label)" (corpus annotator) and "Design system" ("the build proof") (`sidebar.tsx:20-44`);
marketing rendered a static hardcoded fixture captioned "Real output … not screenshots"
(`method/page.tsx:57-61`) and the flagship fixture self-contradicted.

**What I verified (gone / honest):**

1. **Dev tools gated out of the customer nav.** `frontend/src/components/ui/sidebar.tsx`:
   "Parts (Label)" and "Design system" both carry `devOnly: true`; the nav filters them
   unless `devToolsEnabled()` (`frontend/src/lib/dev-flag.ts`) — driven by
   `NEXT_PUBLIC_SHOW_DEV_TOOLS` or a localStorage opt-in, **OFF by default**, SSR-safe.
   A normal buyer's sidebar shows only Analyze / Cost / Batch / History / Developer / API
   docs.
2. **Marketing claims are honest.** The `/method` caption ("the real product components …
   rendering the cost-truth engine's own report … captured from the engine. Real output,
   not screenshots") is now TRUE: the fixture matches live CLI output (verified above).
   The landing-page hero ("Real output · object analyzed by the cost-truth engine", $14.14)
   matches. No self-contradiction: cnc_turning shows `issues` (not `fail`) in both the
   RoutingCard and the DfmMatrix, consistent with the engine.

---

## Invariants & regression (preserved)

- **Σ line-items = unit_cost:** live Midwest response coherent (`786.4548 ≈ 786.45`,
  `abs<0.02`). **Provenance includes SHOP** (driver provenances `['DEFAULT','SHOP']`).
  **Confidence interval present** (`314.58–1258.33`, assumption-band, `validated:false`).
  Shop calibration note present.
- **G1 broken-geometry refusal** preserved (GEOMETRY_INVALID → structured 400 path intact
  in `_run_cost_decision`).
- **Auth gating** intact: `/api/v1/shops` and `/validate/cost` 401 unauth; `/validate/cost/demo`
  kill-switch-gated public.
- **Build/tests:** frontend `npx tsc --noEmit` → exit 0, no errors. Backend
  `pytest test_cost_api.py test_costing_gates.py test_costing_calibration.py
  test_routing_sheet.py` → **57 passed**.

---

## Decision

**COMPLETE.** F1, F2, F3, F5 are each closed against the specific thing the teardown
flagged, verified on the live product + CLI. The two correctness items that cannot be
self-certified — F1 per-shop *number* correctness and F2 routing *process/number*
correctness — are correctly QUEUED for the Zoox Head of Manufacturing (see
`expert-validation-packet.md`); per the rules that queueing is not a failure.
