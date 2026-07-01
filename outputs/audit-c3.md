# CadVerify Cycle 3 — Validation Audit (Validation-Auditor)

**Author:** Cycle 3 Validation-Auditor · **Date:** 2026-06-28 · **Verdict: COMPLETE.**
**Scope audited:** R1 finite-capacity lead-time, R2 serial-AM (FDM/SLA) XY build-plate nesting, and the new `POST /api/v1/validate/cost` endpoint.
**Everything below I ran myself** (CLI, accuracy harness, the full 48-test suite, the 8 endpoint tests, and a live TestClient end-to-end on the real ECU mount + broken MAF). No number here is copied from the builders' notes without independent reproduction.

## Result at a glance

| # | Check | Result |
|---|---|---|
| 1 | R1 high-qty AM lead time realistic + capacity an inspectable, overridable driver | **PASS** |
| 2 | R2 serial-AM cost dropped, harness re-run shows fdm/sla within the C2 band (real nesting, not fakery) | **PASS** |
| 3 | Invariants/regression: Σ=unit, provenance, G1 refusal, coherence, full suite, toy model unsurfaced | **PASS** |
| 4 | `POST /validate/cost` actually runs on a real part; broken part → clean 400; auth enforced | **PASS** |
| 5 | CAD-as-IP: zero network egress (endpoint included), no persistence, only MEASURED summary leaves | **PASS** |

**Full required suite: `48 passed in 380.56s`** (40 costing R1/R2 + 8 new API). Accuracy harness re-run: **Overall PASS**, all 5 criteria green.

---

## Commands I ran (reproducible)

```bash
PARTS=/private/tmp/claude-501/-Users-nazeem-Desktop-developer-cadverify/3182c9c6-e59b-4394-a584-d9c4cd4ce0dc/scratchpad/parts
cd backend
# R1 lead-time + R2 cost, ECU mount
.venv/bin/python -W ignore -m src.costing.cli "$PARTS/1090523_..._ECU_Firewall_mount.stl" --qty 50,5000 --quiet
# R1 override -> USER + 2nd-part spot-check
.venv/bin/python -W ignore -m src.costing.cli "$PARTS/1090523_..._ECU_Firewall_mount.stl" --qty 5000 --set n_machines.MJF=20 --quiet
.venv/bin/python -W ignore -m src.costing.cli "$PARTS/1481203_..._e46_ecu_box_plug_L.stl" --qty 5000 --quiet
# R2 mandated worked example
.venv/bin/python -W ignore -m src.costing.cli "$PARTS/printables_122552_ThrottleBodyAdapter.stl" --qty 100 --quiet
# Broken geometry refusal
.venv/bin/python -W ignore -m src.costing.cli "$PARTS/655044_..._MAF_Sensor_Adapter...stl" --quiet
# Accuracy harness re-run (regenerates outputs/accuracy-report.md)
CADVERIFY_PARTS_DIR=$PARTS .venv/bin/python -W ignore -m src.costing.harness
# Full suite + endpoint suite
CADVERIFY_PARTS_DIR=$PARTS .venv/bin/python -W ignore -m pytest \
  tests/test_costing_model.py tests/test_costing_gates.py \
  tests/test_costing_accuracy.py tests/test_cost_api.py -q
# Live end-to-end through the real FastAPI app (TestClient) on the real ECU + MAF parts,
# wrapped in an AF_INET/AF_INET6 socket guard (CAD-as-IP).
```

---

## Check 1 — R1: high-qty AM lead time is realistic + the capacity assumption is inspectable

**What I tested:** ECU mount `mjf @ qty 5000` lead time, that the machine-pool capacity is shown as a driver and is overridable, and a second-part spot-check.

**PASS — evidence (my CLI run):**
```
mjf / PP (Polypropylene)   qty 50: $44.13/unit   qty 5000: $43.98/unit   ±40%
  lead time qty 5000: ... · capacity 6 machines × 22 hr/day [DEFAULT]
DECISION
  @ qty 5000  → mjf / PP ($43.98/unit, 49.7–92.3 d)  (make-as-is, recommended)
```
- **ECU `mjf @ qty 5000` = 49.7–92.3 days** (≈7–13 weeks). The V1 defect was **744.1–1381.9 days** (≈2–4 years). Fixed.
- The capacity assumption renders **inline in every lead-time line**: `capacity 6 machines × 22 hr/day [DEFAULT]`. It is a structured `lead_time.capacity` dict ({n_machines, machine_hours_per_day, provenance, basis}) that also flows into the API JSON.
- **No costed process reads multi-year:** at q5000 the longest is `sla` 203–377 d (resin laser-trace is genuinely slow; honest, sub-year) and the headline make-now process (mjf) is the prominently-shown one.

**Overridable → USER (verified live):** `--set n_machines.MJF=20` on ECU q5000:
```
lead time qty 5000: 18.9–35.1 days [queue 3 + production 20 + post 1 + ship 3] · capacity 20 machines × 22 hr/day [USER]
line items Σ = $43.98 (unit cost unchanged — R1 is lead-time-only)
```
Production drops 64 d → 20 d, capacity flips DEFAULT → **USER**, and unit cost is unchanged (R1 touches lead time only).

**Spot-check part 2 — `e46_ecu_box_plug_L` @ q5000:** every process sub-year — `mjf 7.7–14.3 d`, `fdm 12.6–23.4 d`, `sls 8.4–15.6 d`, `cnc_5axis 11.9–22.1 d`, `injection_molding 23.1–42.9 d`. No multi-year reading.

The model is the clean generalization `production = ceil(qty·cycle_hr / (n_machines · machine_hours_per_day))` (`leadtime.py:43`); the old single-machine/8-hr formula is its `n=1, hours=8` special case. Lead time still grows monotonically with qty (qty in the numerator → G5 holds; verified by the monotonic gate test in the suite).

## Check 2 — R2: serial-AM cost dropped and the re-run harness lands in band (not faked)

**What I tested:** the mandated ThrottleBodyAdapter worked example, that the XY nesting is a real inspectable driver, and the **regenerated** accuracy report's per-process medians/criteria.

**PASS — worked example (my CLI run, throttle 2.81 cm³ @ q100):**
```
fdm / PLA   qty 100: $9.62/unit
  parts_per_build  18 parts  [DEFAULT XY nest: plate 250×250mm × xy_packing 0.5 ÷ footprint (34.0×39.9+4mm) = 18 parts/plate]
  machine_cost     $1.80  [... serial XY-nested: deposition V/16 = 2.81/16 = 0.176hr/part (per-part nozzle)
                          + Z-sweep (22.2/25)÷18 parts/plate = 0.049hr/part (plate Z-climb amortized) = 0.225hr/part]
  line items Σ = $9.62
sla / Standard Resin   qty 100: $14.82/unit
  parts_per_build  6 parts  [DEFAULT XY nest: plate 145×145mm × xy_packing 0.5 ÷ footprint (34.0×39.9+3mm) = 6 parts/plate]
  machine_cost     $6.44  [... deposition V/8 = 0.351hr/part (per-part nozzle) + Z-sweep (22.2/20)÷6 = 0.185hr/part ...]
```
This is the honest fix, not fakery: the single-nozzle/laser **deposition stays per-part and irreducible**; only the **shared Z-axis plate sweep is amortized** over the XY nest count (`cost_model.py:61-73`). The nesting count is a provenance-tagged `parts_per_build` driver with the XY footprint arithmetic on its face, and `xy_packing_density=0.50` is a DEFAULT overridable → USER.

**Re-run accuracy harness (`outputs/accuracy-report.md`, regenerated by me):**

| process | V1 (pre-fix) median | C3-fix median | % in band | C2 bar ≤0.60 |
|---|---|---|---|---|
| fdm | +0.75 (50%) | **+0.38** | 67% | ✓ |
| sla | +0.61 (67%) | **+0.35** | 67% | ✓ |

Throttle now lands centered: `fdm $9.62 (−3%, in band)`, `sla $14.82 (−17%, in band)`. Acceptance criteria (regenerated report):
```
PASS  C1_in_band>=80pct: 84% in band (169/202)
PASS  C2_no_systematic>60pct: worst median |err| = mjf -0.50
PASS  C3_smallpart_AM_in_band   PASS  C4_cnc_floor>=R4min   PASS  C5_tooling_in_R3
Overall: PASS
```
C2 flipped **FAIL → PASS**; every per-process verdict in the report is now PASS (no `FAIL` row in the verdict column). Powder-bed (SLS/MJF/DLP), CNC, IM are untouched — their bands unchanged. Deposition-dominated parts that nest 1–2/plate stay at the high edge; that is the honest, disclosed single-nozzle residual, and the **median** (what C2 measures) now passes.

## Check 3 — Invariants / regression

**What I tested:** Σ=unit, provenance on every driver, G1 refusal, decision coherence, full suite, toy model unsurfaced.

**PASS:**
- **Σ-invariant** `unit_cost == round(Σ line_items, 2)`: **0 violations** across all real-ECU estimates in my live API run; `cost_model.py` calls `est.assert_sums()` before returning; the min-charge floor is booked as its own line and still summed.
- **Provenance:** **0 drivers** missing a provenance tag or `source` string across the live ECU response (every driver ∈ {MEASURED, USER, DEFAULT} with non-empty source). New drivers (`parts_per_build` XY-nest, `lead_time.capacity`) are tagged.
- **G1 broken-geometry refusal:** MAF adapter → `Geometry: 0 cm³ ... watertight ✗ → GEOMETRY INVALID — repair required. No cost produced.` Zero estimates. (Holds in CLI and as a 400 in the API.)
- **Coherence:** ECU headline `make_now_process = mjf` ≡ `@ qty 50` recommendation `mjf` (single ranking, verified live). The make-vs-buy direction and crossover (739.2) are unchanged.
- **Full suite:** `48 passed in 380.56s` (40 costing + 8 API; the two accuracy tests that documented the old serial-AM residual were correctly rewritten to assert the fix). No regression of the prior 36; the delta is +4 R1/R2 regression locks and +8 API tests.
- **Legacy toy model unsurfaced:** `grep -rE 'cost_per_cm3|cost_factor' src/costing/` returns only docstring/comment lines stating it is **never** surfaced. No code path emits it.

## Check 4 — `POST /api/v1/validate/cost` actually runs

**What I tested:** the 8-test endpoint suite, plus a live TestClient end-to-end on the **real** ECU mount and the **real** broken MAF part.

**PASS — endpoint suite (my run):** `8 passed in 0.52s` — covers clean-part decision, clean-400 GEOMETRY_INVALID, auth-required (401), bad complexity/qty/extension (400), USER provenance on overrides, and zero network egress.

**PASS — live end-to-end through the real FastAPI app (TestClient):**
```
ECU status: 200
make_now_process: mjf | q50 reco: mjf | crossover: 739.2     <- coherent headline == low-qty reco
mjf q5000 unit_cost: 43.98 | lead: 49.7 - 92.3 days          <- R1 fix carried into the JSON
mjf q5000 capacity: 6 machines x 22.0 hr/day [ DEFAULT ]     <- R1 assumption inspectable in response
Sigma-invariant violations: []                               <- unit_cost == Σ line_items, every estimate
Drivers missing provenance/source: []                        <- G6 holds end-to-end
geometry keys: bbox_mm, face_count, surface_area_cm2, volume_cm3, watertight   <- MEASURED summary only

MAF status: 400 (not 500)
MAF body: {"code":"GEOMETRY_INVALID","message":"...repair required","geometry":{"volume_cm3":0.0,...}}
```
The broken part returns a **clean structured 400 carrying the geometry summary**, never a crash/500. Auth is enforced (`test_cost_requires_auth`: removing the bypass → 401 `auth_missing/auth_invalid`). The handler declares **no DB session dependency** (lines 425–438) → no persistence: the CAD is parsed, costed, and discarded in-process.

## Check 5 — CAD-as-IP: zero network egress (endpoint included)

**What I tested:** network primitives in the costing package and the new routes code; whether the live endpoint opens any internet socket; whether raw CAD leaves the process.

**PASS:**
- `grep -rE 'socket|requests|urllib|httpx|aiohttp|urlopen|\.connect\(' src/costing/` → **NONE**. The costing layer is stdlib + local-engine only.
- The full live run above (both the ECU 200 and the MAF 400 requests) executed **inside an `AF_INET`/`AF_INET6` socket guard** that raises on any internet socket; it completed without tripping → **zero egress** during a real request. `test_cost_zero_network_egress` asserts the same in CI.
- The endpoint **persists nothing** (no `session`/`get_db_session` dependency, no mesh blob, no row). The response carries only the **MEASURED geometry summary** (volume/area/bbox/watertight/face_count) — no mesh, no raw vertices. CAD never leaves the process.

---

## Decision

**COMPLETE.** Both residual defects are genuinely fixed and honestly disclosed (R1 capacity assumption + R2 XY-nesting are inspectable, provenance-tagged, overridable → USER drivers), the accuracy harness re-run shows C2 FAIL → PASS with fdm/sla medians within band, every hard invariant holds (Σ=unit, provenance, G1 refusal, coherence, toy model unsurfaced), the full 48-test suite passes with no regression, the new `POST /api/v1/validate/cost` endpoint actually runs on real parts (clean 400 on broken geometry, auth enforced), and there is zero new network egress or CAD persistence. No fabricated number found.
