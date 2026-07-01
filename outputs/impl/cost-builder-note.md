# Cost-builder note — F1-backend (per-shop calibration in the cost API) + F2 (routing↔DFM consistency)

Role: Senior Manufacturing Cost Engineer + Backend Engineer.
Scope closed this run: the **backend of F1** (shop param threaded into the cost API + `GET /shops` + override re-cost) and **all of F2** (routing never headlines a process the engine's own DFM hard-fails). No commit. Tests/invariants intact.

REAL-EXPERT GATE (not self-certified): the *numerical correctness* of the per-shop numbers (F1) and the routing/number correctness (F2) is NOT marked "done" here — it goes to the Zoox Head of Manufacturing validation packet. What is proven below is that the *mechanism* is in the product, consistent, and honest.

---

## F1-backend — the wedge is now IN the cost API (was CLI-only)

### What changed
`backend/src/api/routes.py`:
- `POST /api/v1/validate/cost` and `POST /api/v1/validate/cost/demo` gained two Form params:
  - `shop` — a shop-calibration profile id or display name. Resolved against the local store (`_resolve_shop_param`) and passed via `EstimateOptions(shop=…)`. Unknown shop → clean **400** (never a path read — see security note).
  - `overrides` — a JSON object of dotted rate/driver keys → numbers (same surface the CLI exposes via `--set`/`--labor-rate`/`--tooling`), passed via `EstimateOptions(rate_overrides=…)`. This is what makes **F3's** server re-cost real. Bad JSON/value → 400; unknown key fails fast via a `build_rate_card` dry-run → 400 (never a 500).
- `region` changed from `Form("US")` to `Form(None)`: unset ⇒ DEFAULT US **or** a bound shop's own region wins (`region_is_user`); an explicit region is validated against `{US,EU,MX,CN,IN,SA}` and treated USER. Invalid region → 400.
- New `GET /api/v1/shops` (viewer-gated, `_available_shops`) returns the bindable profiles: `{id, name, region, source}` so the UI can list them.
- The structured `cost_estimate`/`cost_timeout` logs now carry `shop` and the effective `region` (still no CAD/PII).

The cost engine already supported all of this (`EstimateOptions.shop/rate_overrides/region_is_user`, used only by the CLI before). This change is pure wiring through the HTTP route — no engine/invariant change.

### Security / IP-local
`shop` is matched only against profiles that already exist in `backend/data/shop_profiles/` (by slug or case-insensitive name) — never an arbitrary filesystem path, so it cannot be turned into a path-traversal read. The costing layer still opens zero sockets; nothing is persisted.

### New endpoint surface
| Method | Path | Auth | New |
|---|---|---|---|
| GET  | `/api/v1/shops` | viewer | returns `{shops:[{id,name,region,source}]}` |
| POST | `/api/v1/validate/cost` | analyst | + `shop`, `overrides`; `region` now optional/validated |
| POST | `/api/v1/validate/cost/demo` | public | same new params |

### REAL captured output — LIVE server (uvicorn :8000), real part `ecu_stm_fuel_pump_holder.STL`
```
# auth gating preserved (no key):
GET  /api/v1/shops              -> 401
POST /api/v1/validate/cost      -> 401      (with shop set)

# public demo route, real engine, real part:
generic mjf@100 = $64.63        <- the exact number the teardown cited as "real engine output"
shop    mjf@100 = $162.27       <- SHOP-calibrated (Midwest Precision CNC), the number MOVES
shop note: "Calibrated to shop 'Midwest Precision CNC' (region US): 19 rate(s) bound ... tagged SHOP"
POST .../cost/demo  shop=Nope   -> 400

GET /api/v1/shops (authed app):
  midwest-precision-cnc | Midwest Precision CNC | US
  shenzhen-contract-mfg | Shenzhen Contract Mfg | CN
```

### REAL captured output — through the real FastAPI app (TestClient), real part, full JSON
```
unit cost, GENERIC vs SHOP=Midwest Precision CNC (ecu_stm_fuel_pump_holder.STL):
  cnc_3axis@100          generic $  67.93   shop $ 156.28   CHANGED
  cnc_5axis@100          generic $ 101.95   shop $ 230.81   CHANGED
  injection_molding@100  generic $ 153.05   shop $ 202.53   CHANGED
  injection_molding@10000 generic $   4.55  shop $   9.48   CHANGED   <- tooling-crossover wedge intact
  mjf@100                generic $  64.63   shop $ 162.27   CHANGED
  sls@100                generic $  73.27   shop $ 172.18   CHANGED
  (every costed line changes under calibration)

SHOP-tagged assumptions: labor_rate=52.0, region_labor=1.0, region_material=1.0,
  region_tooling=1.0, margin=0.3, overhead=0.15, utilization=0.8
SHOP-tagged drivers on mjf line: material_cost, machine_cost, labor_cost, setup_cost
calibration note present: yes
invariant unit_cost == Σ line_items on SHOP run: True

F3 override re-cost (overrides={"machine_rate.MJF": 200}):
  mjf@100  $64.63 (default)  ->  $515.57 (override)   USER-tagged driver: machine_cost
```
So: the shop changes the number, the touched lines are SHOP-tagged, the calibration note is carried, the make-vs-buy tooling crossover still appears, and an edited rate truly re-costs server-side and is tagged USER. Σ=unit_cost holds throughout.

---

## F2 — routing is now CONSISTENT with DFM (no DFM-fail process headlined)

### Root cause (from the teardown, verified)
Two different definitions of "rotational":
- `routing.is_rotational` used **bounding-box squareness** (`roundness = min/ max`), so a square/near-square lid scored ~0.97 and was headlined `cnc_turning, rotational, 0.80`.
- `checks.check_rotational_symmetry` (the CNC-turning DFM gate) uses an **inertia-eigenvalue** test at **tolerance 0.15** and hard-failed the same parts "lacks rotational symmetry".

Reproduced before the fix: `macchina_m2_M2R3_CASE_TOP_UTD` and `ecu_stm_fuel_pump_holder` both headlined `cnc_turning` while their `cnc_turning` DFM = **fail** — a direct in-panel contradiction.

### What changed (`backend/src/costing/routing.py`, `…/estimate.py`)
1. **One definition of rotational.** `is_rotational` now requires BOTH (a) the existing turnable-shape guard (bbox roundness ≥ 0.80, real cross-section Ø, sane L/D) AND (b) `_inertia_axisymmetric(mesh)` — the *same* inertia-eigenvalue test the DFM gate runs, at the *same* 0.15 tolerance. Because `rotational ⟹ inertia-axisymmetric`, the engine's rotational-symmetry DFM can never fail a part routing calls rotational. The bbox-roundness term is kept so a flat bracket (which is *more* inertia-axisymmetric than a ring under the loose tolerance) is still correctly rejected — that's why the G2 bracket tests still pass.
2. **Headline never a DFM-fail process.** `recommend_routing` is split into a pure geometry classifier (`_classify_archetype`) + a guard (`_avoid_dfm_failed_headline`). The guard, given the set of processes the engine hard-fails (`verdict=="fail"`) on this part, demotes the headline to the first DFM-clean alternative (or, rarely, the best DFM-clean process overall) and keeps the original as the at-volume / design-for-process route in the reasoning.
3. **Wedge preserved.** Process *costing* selection (`eligible_processes`) is untouched, so injection molding is still costed and still surfaced as the make-vs-buy crossover in the decision card. Only the headline badge changes — e.g. `macchina…CASE_TOP_UTD` now headlines `mjf` (make-as-is) while injection molding still appears as the qty-10000 crossover ($3.39/unit, crossover_qty≈1899).

### REAL captured output
Cited parts (qty 100/10000):
```
part                                  headline(before->after)   rotational   cnc_turning DFM
macchina_m2_M2R3_CASE_TOP_UTD         cnc_turning -> mjf         True->False  fail   (contradiction GONE)
ecu_stm_fuel_pump_holder              cnc_turning -> mjf         True->False  fail   (contradiction GONE)
printables_122552_ThrottleBodyAdapter cnc_turning (unchanged)    True         issues (genuinely round -> still turns)
printables_122552_ThrottleBodyRingOuter cnc_turning (unchanged)  True         issues (genuinely round -> still turns)
```
Corpus-wide scan (77 valid parts, meshes < 700 KB):
```
HEADLINE-IS-DFM-FAIL contradictions: 40 (before)  ->  0 (after)
headline==cnc_turning: 8 parts, all with cnc_turning DFM != fail (genuinely rotational)
```
Live server, real part `ecu_stm_fuel_pump_holder.STL`: `routing headline = mjf | cnc_turning DFM = fail` → the recommended process is never one the same panel marks FAIL.

---

## Tests / invariants
- `tests/test_cost_api.py`: +7 tests (GET /shops; shop calibrates the number + SHOP tags + Σ invariant; unknown shop→400; override re-cost + USER tag; bad-JSON→400; unknown-key→400; demo route supports shop). **25 passed.**
- `tests/test_costing_gates.py` G2 turning gates, `tests/test_routing_sheet.py`, `tests/test_analyzers.py`, `tests/test_costing_calibration.py`, `tests/test_costing_groundtruth.py`: green (70 passed in the combined run; targeted G2/analyzer run 10 passed).
- Preserved invariants verified on real parts: unit_cost == Σ line_items, provenance tags (incl. SHOP/USER), confidence intervals, G1 broken-geometry → clean 400, and the auth gating (401 without key).

## Files touched
- `backend/src/api/routes.py` — shop/overrides/region params on both cost routes, `GET /shops`, validators, log fields.
- `backend/src/costing/routing.py` — inertia-consistent `is_rotational`; classifier/guard split; DFM-fail headline demotion.
- `backend/src/costing/estimate.py` — compute `dfm_failed`/`dfm_clean`, pass to `recommend_routing`.
- `backend/tests/test_cost_api.py` — F1/F3 endpoint tests.
