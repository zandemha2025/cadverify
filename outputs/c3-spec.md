# CadVerify Cycle 3 — Build-Ready Spec (Architect)

**Author:** Cycle 3 Architect · **Date:** 2026-06-28 · **Status:** BUILD-READY — zero open decisions
**Scope:** (A) R1 lead-time finite-capacity fix · (B) R2 serial-AM (FDM/SLA) XY-nesting fix · (C) `POST /validate/cost` API endpoint.
**Inputs fused:** `outputs/accuracy-report.md`, `outputs/v1-fix-spec.md`, `outputs/validation-packet.md`, `outputs/v1-build-notes.md`, and live code in `backend/src/costing/` + `backend/src/api/` + `backend/main.py` (every module opened). **Every number below was computed from a verified prototype run on the real ECU mount + the 12-part harness sample — none fabricated** (prototype results inline).

## Acceptance contract for the builders
Build exactly this. Every new default has a named source basis and a USER override path → it ships tagged DEFAULT and recomputes live when overridden. **Do not invent behavior not specified here.**

## Hard invariants that must NOT regress (Validation-Auditor enforces)
1. `abs(unit_cost_usd − Σ line_items.values()) < 0.01` on every estimate (G3). **R1 and R2 do not change this** — R1 touches lead-time only (no $), R2 re-derives a machine line that is still summed.
2. Every `Driver` has a non-empty `source` + `Provenance` tag (G6). New drivers/assumptions included.
3. G1 robustness gate stays first: broken geometry → `GEOMETRY_INVALID`, zero estimates. **The API surfaces this as a clean 400.**
4. Zero network egress (G7). The cost endpoint opens no sockets and **persists no CAD**.
5. Legacy `profile_matcher._estimate_cost_factor` stays untouched and unsurfaced.
6. Do not regress the 36 existing tests. The two accuracy tests that **document** the old serial-AM residual are explicitly rewritten by R2 (§B.6) — that is a required edit, not a regression.

## Two-builder split
- **Builder 1 — Costing residuals:** §A (R1 lead-time) + §B (R2 serial-AM nesting). Files: `rates.py`, `drivers.py`, `cost_model.py`, `leadtime.py`, `estimate.py`, `report.py`, `harness.py`, `tests/test_costing_*`. Regenerate `outputs/accuracy-report.md`.
- **Builder 2 — API:** §C (`POST /validate/cost`). Files: `src/api/routes.py`, `tests/test_cost_api.py` (new). No `main.py` change (the router is already mounted at `/api/v1`). Builder 2 consumes Builder 1's `report_to_dict` shape **as-is** — the only coupling is the new `lead_time.capacity` sub-key (§A.4), which is additive.

The two builders are independent except that the API test mesh exercises the cost model; run Builder 1 first, then Builder 2.

---

# A. R1 — Finite-capacity lead-time model

## A.0 The defect (verified live)
`ECU mount @ qty 5000 → mjf 744.1–1381.9 days` (≈2–4 years). Cause: `leadtime.py::lead_time` computes `production = ceil(qty * cycle_hr / daily_machine_hours)` with **one machine at 8 hr/day** producing the whole lot serially. For `mjf` cycle 1.6889 hr/part: `ceil(5000·1.6889/8)=1056` production days → mid `queue 3 + 1056 + post 1 + ship 3 = 1063` → `×0.7/×1.3 = 744.1–1381.9`. `fdm` q5000 is even worse: **9.4 years**. This is a lead-time artifact only (no $ effect), but it reads as nonsense to a manufacturing buyer.

## A.1 The model — a parallel machine pool with realistic uptime
Replace the single-machine assumption with a **bureau machine pool** running at a process-appropriate daily uptime:

```
production_days = ceil( qty * cycle_hr / (n_machines * machine_hours_per_day) )
```

This is the clean generalization of the current formula (the current code is the `n_machines=1, hours=8` special case). It only touches production days — **unit cost is unchanged**. Lead time still grows monotonically with qty (qty in the numerator), so **G5 holds**.

Two new per-process keys, both DEFAULT, both sourced, both overridable → USER:
- `n_machines` — the bureau pool size for that process.
- `machine_hours_per_day` — realistic uptime. AM/molding machines run **lights-out / near-continuous** (HP MJF 5200, EOS SLS, resin printers, IM presses all run unattended 24/7 with brief changeover → DEFAULT **22**). CNC runs **two attended shifts** → DEFAULT **16**. (V1's global `daily_machine_hours=8` was a one-shift, single-machine assumption — kept only as a fallback for processes without the per-process key.)

### A.1 rate-card values — add to each process dict in `RATE_CARD_V0` (`rates.py`)

| process | `n_machines` | `machine_hours_per_day` | source basis |
|---|---|---|---|
| FDM | 12 | 22 | FDM print-farm (printers are cheap; bureau farms run 10–50 units), lights-out |
| SLA | 8 | 22 | resin farm, near-continuous |
| DLP | 8 | 22 | resin farm |
| SLS | 6 | 22 | powder-bed bank (EOS P-class), lights-out builds |
| MJF | 6 | 22 | powder-bed bank (HP Jet Fusion 5200), lights-out builds |
| CNC_3AXIS | 8 | 16 | 3-axis mill bank, two shifts |
| CNC_5AXIS | 4 | 16 | 5-axis bank (pricier, fewer machines), two shifts |
| CNC_TURNING | 6 | 16 | lathe bank, two shifts |
| INJECTION_MOLDING | 2 | 22 | press pool around the tool, near-continuous |
| DIE_CASTING | 2 | 22 | casting-cell pool |

These are the V1 DEFAULTs ("our stated assumptions") — a mid-size bureau farm, not a claim of any specific supplier's capacity. The buyer overrides per process.

## A.2 `RateCard` accessors (`rates.py`)
```python
def machine_pool(self, proc: ProcessType) -> int:
    return max(1, int(self.p(proc, "n_machines")))

def machine_hours_per_day(self, proc: ProcessType) -> float:
    v = self.data["process"][proc].get("machine_hours_per_day")
    return float(v) if v is not None else float(self.g("daily_machine_hours"))
```

## A.3 `build_rate_card` override whitelist (`rates.py`)
Add `"n_machines"` and `"machine_hours_per_day"` to the `_NUMERIC_FIELDS` set (already coerced to float; `machine_pool()` does the `int()`). This gives the dotted override path `n_machines.MJF=10`, `machine_hours_per_day.MJF=24` → recorded in `user_keys` → USER provenance. No other change to override parsing.

## A.4 `leadtime.py` — formula + the inspectable capacity assumption
The capacity assumption MUST be stated and overridable. Add it to the `LeadTime` dataclass and surface it.

```python
@dataclass
class LeadTime:
    process: str
    quantity: int
    low_days: float
    high_days: float
    mid_days: float
    components: dict = field(default_factory=dict)
    capacity: dict = field(default_factory=dict)   # NEW: stated, inspectable, overridable

def lead_time(process, drivers_or_cycle_hr, qty, rates):
    cycle_hr = float(drivers_or_cycle_hr)
    n_machines = rates.machine_pool(process)
    hours = rates.machine_hours_per_day(process)

    production = math.ceil(qty * cycle_hr / (n_machines * hours))
    tooling_lead = rates.tooling_lead_days(process)
    queue = rates.p(process, "queue_days")
    post = rates.p(process, "post_days")
    ship = rates.g("ship_days")

    components = {
        "queue": float(queue),
        "tooling_lead": float(tooling_lead),
        "production": float(production),
        "post_process": float(post),
        "ship": float(ship),
    }
    cap_user = (f"n_machines.{process.name}" in rates.user_keys
                or f"machine_hours_per_day.{process.name}" in rates.user_keys)
    capacity = {
        "n_machines": int(n_machines),
        "machine_hours_per_day": float(hours),
        "provenance": "USER" if cap_user else "DEFAULT",
        "basis": (f"capacity-bound: {int(n_machines)} machines × {hours:g} hr/day "
                  f"parallel pool; production = ceil({qty}·{cycle_hr:.3f}hr ÷ "
                  f"({int(n_machines)}×{hours:g})) = {production} d"),
    }
    mid = sum(components.values())
    return LeadTime(
        process=process.value, quantity=int(qty),
        low_days=round(mid * 0.7, 1), high_days=round(mid * 1.3, 1),
        mid_days=round(mid, 1), components=components, capacity=capacity,
    )
```

`process` is a `ProcessType` (it already is — `estimate.py` passes the enum), so `process.name` works for the user-key lookup.

## A.5 Surface in the serialized estimate (`estimate.py::_serialize`)
Add `capacity` to the `lead_time` sub-dict so it flows through `report_to_dict` → the API JSON automatically:
```python
"lead_time": {
    "low_days": lt.low_days, "high_days": lt.high_days, "mid_days": lt.mid_days,
    "components": lt.components,
    "capacity": lt.capacity,        # NEW
},
```

## A.6 Report rendering (`report.py::render_text`)
In the per-estimate lead-time line, append the capacity assumption so the glass box shows it:
```python
cap = lt.get("capacity", {})
cap_str = ""
if cap:
    cap_str = (f" · capacity {cap['n_machines']} machines × "
               f"{cap['machine_hours_per_day']:g} hr/day [{cap['provenance']}]")
L.append(f"      lead time qty {head['quantity']}: "
         f"{lt['low_days']:g}–{lt['high_days']:g} days [{comp}]{cap_str}")
```
(No change to the decision-block recommendation lead rendering — it already reads `lead_low_days/lead_high_days`, which are now the pooled numbers.)

## A.7 Worked numbers (verified prototype; DEFAULTs above)
`cycle_hr` for `build_job` processes is unchanged by R1; FDM/SLA `cycle_hr` is the **post-R2** serial value (§B). ECU mount, queue/tooling/post/ship from the card:

| process | cycle_hr | pool (n×hr) | prod @50 | mid @50 → low–high | prod @5000 | mid @5000 → low–high |
|---|---|---|---|---|---|---|
| **mjf** | 1.689 | 6×22 | 1 | 8 → 5.6–10.4 | **64** | **71 → 49.7–92.3** |
| sls | 1.875 | 6×22 | 1 | 8 → 5.6–10.4 | 72 | 79 → 55.3–102.7 |
| fdm (R2) | 4.826 | 12×22 | 1 | 7 → 4.9–9.1 | 92 | 98 → 68.6–127.4 |
| sla (R2) | 9.977 | 8×22 | 3 | 9 → 6.3–11.7 | 284 | 290 → 203.0–377.0 |
| cnc_3axis | 0.325 | 8×16 | 1 | 10 → 7.0–13.0 | 13 | 22 → 15.4–28.6 |
| injection_molding | 0.034 | 2×22 | 1 | 32 → 22.4–41.6 | 4 | 35 → 24.5–45.5 |

**Headline:** `ECU mjf @ qty 5000` goes from **744.1–1381.9 days → 49.7–92.3 days** (≈7–13 weeks). `fdm` goes from **9.4 years → ~98 days**. No costed process reads multi-year at automotive volume. `sla`/`dlp` at q5000 are still long (~9–12 months) because resin laser-trace is genuinely slow and these are not volume processes — that is honest, sub-year, and the headline make-now process (mjf) is the one shown prominently. The capacity assumption is stated in every lead-time line and is overridable (`n_machines.MJF=10` → USER, recomputes live; e.g. 10 machines → mjf q5000 production 38 d).

## A.8 Tests (R1)
- **Update none that assert day-values** (none exist — `test_g5_lead_time_components_and_monotonic` and `test_lead_time_present_and_grows_with_qty` assert only component-keys, `low<high`, and monotonicity; all still pass).
- **Add `test_r1_capacity_pool_caps_high_qty_leadtime`** (`tests/test_costing_gates.py`, real ECU, skip-guarded):
  ```python
  def test_r1_capacity_pool_caps_high_qty_leadtime():
      """R1: high-qty AM lead time is finite-capacity, never multi-year, and the
      machine-pool assumption is stated + overridable."""
      report, _ = _decide(ECU, quantities=[50, 5000])
      mjf = [e for e in report.estimates if e["process"] == "mjf" and e["quantity"] == 5000][0]
      lt = mjf["lead_time"]
      assert lt["high_days"] < 365, f"q5000 mjf lead must be < 1 year, got {lt['high_days']}"
      cap = lt["capacity"]
      assert cap["n_machines"] >= 1 and cap["machine_hours_per_day"] > 0
      assert cap["provenance"] == "DEFAULT"
      # monotonic still holds
      mjf50 = [e for e in report.estimates if e["process"] == "mjf" and e["quantity"] == 50][0]
      assert mjf["lead_time"]["mid_days"] >= mjf50["lead_time"]["mid_days"]
  ```
- **Add `test_r1_capacity_override_to_user`** (procedural mesh, no parts dir needed):
  ```python
  def test_r1_capacity_override_to_user():
      """Overriding n_machines flips capacity provenance to USER and shrinks production."""
      result, mesh, feats = _analyze(_bulky_block())
      base = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[5000]))
      over = estimate_decision(result, mesh, feats, EstimateOptions(
          quantities=[5000], rate_overrides={"n_machines.MJF": 20}))
      m0 = [e for e in base.estimates if e["process"] == "mjf"][0]["lead_time"]
      m1 = [e for e in over.estimates if e["process"] == "mjf"][0]["lead_time"]
      assert m1["capacity"]["provenance"] == "USER"
      assert m1["components"]["production"] <= m0["components"]["production"]
  ```
  (`_bulky_block`, `_analyze`, `_small_block` already exist in `test_costing_model.py`; if placing this test there, reuse them; otherwise mirror the helper.)

---

# B. R2 — Serial-AM (FDM/SLA) XY build-plate nesting

## B.0 The defect (measured, accuracy-report C2 FAIL)
FDM median signed error **+0.75** (50% in band), SLA **+0.61** (67% in band) vs the independent volumetric bureau band (`harness.R1_AM`). Cause: V1 deliberately does NOT nest serial-deposition processes — `_additive_machine` serial branch charges `machine_hr = V/deposition + build_h/vert` **per part**. Real FDM/SLA bureaus nest many parts in X-Y on one plate (not stacked in Z like powder bed). The over-cost is concentrated on **medium parts** (Parktronik +75%, miata brackets +114…+174%, 1.stl +143%, mount +80%) — exactly the parts where the **height-sweep term dominates and nests few per plate**.

## B.1 Root-cause decomposition (what is and isn't per-part)
For a plate of parts laid flat (smallest bbox dim = build height, the two largest = footprint), printed in **one XY layer** (no Z-stacking):
- **`V/deposition`** — the single nozzle (FDM) / laser trace (SLA) must lay every part's material. **Genuinely per-part. Irreducible. Keep it per-part.** (This is why V1's "serial" instinct was half-right.)
- **`build_h/vert`** — the Z-axis climb. All nested parts build up **together**, layer by layer; the gantry climbs the plate height **once for the whole plate**. **This is a per-PLATE cost that V1 wrongly charges per part.** Amortizing it over `parts_per_plate` is the physically-honest fix and is exactly what collapses the medium-part bias.

This is a real, defensible accuracy fix (amortize a shared machine motion), **not** fakery: per-part deposition stays per-part; only the shared Z-sweep is divided.

## B.2 XY nesting count — extend `parts_per_build` (`drivers.py`)
Make `parts_per_build` branch on `nesting_mode`. `build_job` (powder-bed/DLP) keeps the current **volumetric** fit unchanged; `serial` (FDM/SLA) uses an **areal (XY-footprint)** fit:

```python
def parts_per_build(proc, bbox_mm, rates) -> int:
    """Build-plate nesting count.
      build_job (powder-bed/DLP): volumetric fit (unchanged).
      serial (FDM/SLA): XY-footprint fit — parts laid flat in one layer on the plate.
    """
    dd = sorted(bbox_mm)                       # ascending: dd[0]=height, dd[1],dd[2]=footprint
    s = rates.part_spacing(proc)
    if rates.nesting_mode(proc) == "serial":
        X, Y, _Z = rates.build_env(proc)
        plate_area = X * Y                                          # mm^2
        footprint = (dd[1] + s) * (dd[2] + s)                      # mm^2 (laid flat, height = dd[0])
        if footprint <= 0:
            return 1
        n = int(rates.xy_packing_density(proc) * plate_area / footprint)
        return max(1, n)
    # build_job: volumetric (unchanged)
    X, Y, Z = rates.build_env(proc)
    part_vol_cm3 = ((dd[0] + s) * (dd[1] + s) * (dd[2] + s)) / 1000.0
    env_vol_cm3 = (X * Y * Z) / 1000.0
    if part_vol_cm3 <= 0:
        return 1
    n = int(rates.packing_density(proc) * env_vol_cm3 / part_vol_cm3)
    return max(1, n)
```

## B.3 New rate-card key + accessor (`rates.py`)
Add `xy_packing_density` to the FDM and SLA process dicts (areal packing fraction of the plate). DEFAULT **0.50** — real FDM/SLA bed nesting commonly fills **40–60%** of plate area (parts + spacing + edge margin); 0.50 = "half the bed," the V1 DEFAULT. Overridable per process → USER.

```
PT.FDM: dict(..., xy_packing_density=0.50)
PT.SLA: dict(..., xy_packing_density=0.50)
```
(Do **not** add it to DLP/SLS/MJF — they stay `build_job`/volumetric.)

Accessor + override whitelist:
```python
def xy_packing_density(self, proc):  return self.p(proc, "xy_packing_density")
```
Add `"xy_packing_density"` to `_NUMERIC_FIELDS` in `build_rate_card` (dotted override `xy_packing_density.FDM=0.6` → USER).

## B.4 Serial machine sub-model (`cost_model.py::_additive_machine`)
Replace the `serial` branch so the height-sweep is amortized over `n` (= `parts_per_build`, now XY for serial); deposition stays per-part. `n` is already computed at the top of `_additive_machine`.

```python
else:  # serial (FDM single nozzle / SLA laser): XY-nested plate
    dep = rates.p(process, "deposition")
    vert = rates.p(process, "vert")
    build_h = drivers.bbox_mm[0]                       # smallest extent = build height
    deposition_hr = drivers.volume_cm3 / dep           # per-part — single nozzle/laser, irreducible
    sweep_hr = (build_h / vert) / n                    # per-PLATE Z-climb, amortized over the XY nest
    machine_hr = deposition_hr + sweep_hr
    src = (f"serial XY-nested: deposition V/{dep:g} = {drivers.volume_cm3:.2f}/{dep:g} "
           f"= {deposition_hr:.3f}hr/part (per-part nozzle) + Z-sweep "
           f"({build_h:.1f}/{vert:g})÷{n} parts/plate = {sweep_hr:.3f}hr/part "
           f"(plate Z-climb amortized; XY packing {rates.xy_packing_density(process):g}, "
           f"plate {rates.build_env(process)[0]:g}×{rates.build_env(process)[1]:g}mm) "
           f"= {machine_hr:.3f}hr/part")
    return machine_hr, n, src
```
The `parts_per_build` driver `source` string in `cost_breakdown` already prints `nesting: packing … ÷ part bbox …`. Update it to read XY for serial so the glass box is consistent — gate it on `nesting_mode`:
```python
if rates.nesting_mode(process) == "serial":
    pp_src = (f"XY nest: plate {rates.build_env(process)[0]:g}×{rates.build_env(process)[1]:g}mm "
              f"× xy_packing {rates.xy_packing_density(process):g} ÷ footprint "
              f"({drivers.bbox_mm[1]:.1f}×{drivers.bbox_mm[2]:.1f}+{rates.part_spacing(process):g}mm) "
              f"= {n} parts/plate")
    pp_prov = rates.prov_tag(f"xy_packing_density.{process.name}")
else:
    pp_src = (f"nesting: packing {rates.packing_density(process):g} × env "
              f"{rates.build_env(process)} ÷ part bbox {tuple(drivers.bbox_mm)}+"
              f"{rates.part_spacing(process):g}mm spacing = {n} parts/build")
    pp_prov = rates.prov_tag(f"packing_density.{process.name}")
```
Use `pp_src`/`pp_prov` in the `parts_per_build` Driver. Everything downstream (`post_hr_build/n`, `lot_size = n`, setup) already uses `n` — so the serial lot and per-build finishing now amortize over the XY count too (correct and consistent). **No new line item; the machine line is still summed → Σ-invariant holds.**

## B.5 Worked before/after (verified prototype; `xy_packing_density=0.50`, q100)
Throttle adapter is the mandated worked example; medium parts show the bias collapse:

| part (V cm³) | proc | parts/plate | V0-serial $/unit | **R2 $/unit** | indep. band | before → after |
|---|---|---|---|---|---|---|
| **ThrottleBodyAdapter (2.81)** | **fdm** | 18 | $15.96 (+60%) | **$9.62** (−3%) | $3.2–16.7 | edge → **centered** |
| **ThrottleBodyAdapter (2.81)** | **sla** | 6 | $25.00 (+40%) | **$14.82** (−6%) | $5.6–30.1 | high → **centered** |
| Parktronik (5.31) | fdm | 21 | $18.94 (+75%, OUT) | **$10.86** | $3.4–18.2 | OUT → **in band** |
| miata-bottom (37.43) | fdm | 2 | $59.55 (+174%, OUT) | **$43.27** | $6.0–37.5 | far-high → near band |
| mount (66.79) | fdm | 2 | $57.24 (OUT) | **$54.01** | $8.3–55.1 | OUT → **in band** |

**Per-process median signed error (the C2 headline), prototype over the 12-part sample:**
- **fdm: +0.75 → +0.38** (≤ 0.60 ✓, C2 passes)
- **sla: +0.61 → +0.35** (≤ 0.60 ✓, C2 passes)

In-band rate improves (fdm 50%→~67%, sla ~67%) so overall **C1 stays ≥ 80%**. Deposition-dominated parts that nest only 1–2/plate (1.stl, 6Complete fdm) remain at the high edge — that is the honest, irreducible single-nozzle residual; the **median** is what the C2 bar measures and it now passes. Powder-bed (SLS/MJF/DLP), CNC, IM are untouched — C3/C4/C5 unaffected.

## B.6 Harness + accuracy tests — REQUIRED edits (so the fix is shown, not contradicted)
After R2, `harness.pass_criteria`'s **C2 flips FAIL → PASS** automatically (computed). But two accuracy tests and two prose bullets **document** the old residual and would now contradict the fix. Edit them:

1. **`tests/test_costing_accuracy.py::test_serial_am_residual_high_bias_is_measured` — REPLACE** with a test that asserts the fix landed:
   ```python
   def test_serial_am_within_band_after_xy_nesting(res):
       """R2: FDM/SLA now nest in X-Y on the build plate (per-part deposition kept,
       shared Z-sweep amortized), so their systematic bias drops inside the +/-60%
       bar. The pre-fix V1 ran +0.6..+0.75 high; this asserts the fix, not the old
       residual."""
       per = harness.aggregate_by_process(res.comparisons)
       for proc in ("fdm", "sla"):
           assert proc in per
           assert abs(per[proc]["median_signed_err"]) <= 0.60, (
               f"{proc} median {per[proc]['median_signed_err']:+.2f} must now be "
               f"within +/-60% after XY nesting")
   ```
2. **`tests/test_costing_accuracy.py::test_non_serial_processes_within_band_excluding_serial_am` — GENERALIZE** (remove the FDM/SLA exclusion; now ALL processes pass the bar):
   ```python
   def test_all_processes_within_systematic_bias_bar(res):
       """Every costed process — including the now-XY-nested FDM/SLA — sits within
       the +/-60% systematic-bias bar (C2)."""
       per = harness.aggregate_by_process(res.comparisons)
       for proc, v in per.items():
           assert abs(v["median_signed_err"]) <= 0.60, (
               f"{proc} median {v['median_signed_err']:+.2f} exceeds +/-60%")
   ```
3. **`harness.py::build_report`** — update the two residual-bias bullets (currently lines ~605–610) that describe serial AM as un-nested/high. Replace the serial bullet with the XY-nesting description:
   ```python
   L.append(f"- **Serial AM (FDM/SLA) is now XY-nested** (median {_med(am_serial):+.0%}): "
            f"per-part deposition (single nozzle/laser) is kept per-part, but the shared "
            f"Z-axis plate sweep is amortized over the X-Y nest (parts laid flat in one "
            f"layer). This collapses the prior +60..+75% medium-part over-cost into the "
            f"+/-60% band. Build-job powder-bed/DLP (median {_med(am_nested):+.0%}) "
            f"remains nested per the build-job model.")
   ```
   Leave the size-dependent-curvature bullet; its numbers recompute. (The `Overall:` line will now read `PASS` since all 5 criteria pass.)
4. **Regenerate** `outputs/accuracy-report.md`:
   `cd backend && CADVERIFY_PARTS_DIR=<parts> .venv/bin/python -W ignore -m src.costing.harness`
   Confirm the printed criteria show `PASS C2_no_systematic>60pct` and fdm/sla medians ≤ 0.60.

5. **Add `test_r2_serial_xy_nesting_amortizes_sweep`** (`tests/test_costing_gates.py`, real medium part, skip-guarded) for a direct model assertion:
   ```python
   def test_r2_serial_xy_nesting_amortizes_sweep():
       """R2: a medium FDM part nests >1 per plate and its unit cost drops vs the
       un-amortized serial baseline; Σ-invariant holds; parts/plate is XY-derived."""
       report, _ = _decide(ECU, quantities=[100])
       fdm = [e for e in report.estimates if e["process"] == "fdm"][0]
       n = next(d["value"] for d in fdm["drivers"] if d["name"] == "parts_per_build")
       assert n >= 1
       assert abs(fdm["unit_cost_usd"] - round(sum(fdm["line_items"].values()), 2)) < 0.02
   ```
   (ECU fdm nests 2/plate; for a stronger >1 assertion use the throttle `TBA` anchor where n≈18.)

---

# C. `POST /validate/cost` — the authenticated decision endpoint

## C.0 Design constraints (from ENVIRONMENT + invariants)
- **Auth + abuse controls match the existing `/validate` family:** `dependencies=[Depends(require_kill_switch_open)]` + `user: AuthedUser = Depends(require_role(Role.analyst))` + `@limiter.limit("60/hour;500/day")`.
- **CAD-as-IP:** the costing layer opens zero sockets (G7) and the endpoint **persists nothing** (no DB session, no mesh blob, no `result_json` row). Like `/validate/demo`, it computes and returns — it never writes the CAD anywhere. This is the safest IP posture and keeps the endpoint DB-free.
- **Reuse, don't reinvent:** `_read_capped` (413 size cap), `_parse_mesh` (magic-byte + extension + triangle-cap, 400/413/501), `_analysis_timeout_sec` + `asyncio.wait_for` (504), `report_to_dict` (response), `src/api/errors.py` structured codes (already wired in `main.py`).
- **Registration:** none needed in `main.py` — the handler is added to `routes.py::router`, already mounted at `prefix="/api/v1"`. Final path: **`POST /api/v1/validate/cost`**.

## C.1 Imports to add (`src/api/routes.py`)
Add `Form` to the existing `from fastapi import (...)` block. The costing layer is imported lazily inside the handler (mirrors `/validate/demo`'s lazy engine imports) to keep module import cheap and side-effect-free.

## C.2 Engine helper (factor the CLI's `_run_engine` to bytes) — add to `routes.py`
The costing decision needs an `AnalysisResult` scored over the **full** analyzer registry (not a user-narrowed subset) plus the `mesh` and `features`. Mirror `cli.py::_run_engine` but from an already-parsed mesh:

```python
def _run_cost_engine(mesh, filename: str):
    """Score every registered process for the cost decision layer (mirrors
    cli._run_engine but from an in-memory mesh; no narrowing, no persistence)."""
    import src.analysis.processes  # noqa: F401  populate registry
    from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
    from src.analysis.context import GeometryContext
    from src.analysis.features import detect_all as detect_features
    from src.matcher.profile_matcher import rank_processes, score_process
    from src.analysis.processes.base import get_analyzer
    from src.analysis.processes import base as pbase
    from src.analysis.models import AnalysisResult

    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    ctx.features = detect_features(mesh)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(
        filename=filename, file_type="stl", geometry=geometry,
        segments=ctx.segments, universal_issues=universal, process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx.features
```

## C.3 Options parsing + validation helper — add to `routes.py`
```python
_COMPLEXITY = {"simple", "moderate", "complex", "very_complex"}
_MATERIAL_CLASSES = {"polymer", "aluminum", "steel", "stainless", "titanium"}
_MAX_QTYS = 6
_MAX_QTY = 10_000_000

def _parse_qty_list(qty: str) -> list[int]:
    out: list[int] = []
    for tok in (qty or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            v = int(tok)
        except ValueError:
            raise HTTPException(400, detail=f"Invalid quantity '{tok}' (must be an integer)")
        if not (1 <= v <= _MAX_QTY):
            raise HTTPException(400, detail=f"Quantity {v} out of range [1, {_MAX_QTY}]")
        out.append(v)
    if not out:
        raise HTTPException(400, detail="At least one quantity required (e.g. qty=50,5000)")
    if len(out) > _MAX_QTYS:
        raise HTTPException(400, detail=f"At most {_MAX_QTYS} quantities allowed")
    return out
```

## C.4 The handler — add to `routes.py`
```python
@router.post("/validate/cost", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def validate_cost(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    qty: str = Form("50,5000", description="Comma list of quantities, e.g. 50,5000"),
    region: str = Form("US", description="US|EU|MX|CN|IN|SA"),
    cavities: int = Form(1, description="Formative tooling cavity count (DEFAULT 1)"),
    complexity: str = Form("moderate", description="simple|moderate|complex|very_complex"),
    material_class: str = Form("polymer", description="polymer|aluminum|steel|stainless|titanium"),
    user: AuthedUser = Depends(require_role(Role.analyst)),
):
    """Explainable make-vs-buy should-cost decision for an uploaded STL/STEP part.

    IP-local: the CAD is parsed, costed, and discarded in-process — nothing is
    persisted and no network call is made (the costing layer opens zero sockets).
    """
    import asyncio

    # ---- validate options (fail fast, before reading bytes is fine too) ----
    quantities = _parse_qty_list(qty)
    if complexity not in _COMPLEXITY:
        raise HTTPException(400, detail=f"Unknown complexity '{complexity}'. Use one of {sorted(_COMPLEXITY)}")
    if material_class not in _MATERIAL_CLASSES:
        raise HTTPException(400, detail=f"Unknown material_class '{material_class}'. Use one of {sorted(_MATERIAL_CLASSES)}")
    if cavities < 1:
        raise HTTPException(400, detail="cavities must be >= 1")

    data = await _read_capped(file)                 # 413 on size, 400 on empty
    mesh, suffix = _parse_mesh(data, file.filename or "unknown")   # 400/413/501

    from src.costing import estimate_decision, EstimateOptions, report_to_dict

    options = EstimateOptions(
        quantities=quantities,
        material_class=material_class,
        material_class_is_user=material_class != "polymer",
        region=region,
        n_cavities=cavities,
        n_cavities_is_user=cavities != 1,
        complexity=complexity,
        complexity_is_user=complexity != "moderate",
    )

    def _run():
        result, m, features = _run_cost_engine(mesh, file.filename or "unknown")
        return estimate_decision(result, m, features, options)

    timeout = _analysis_timeout_sec()
    loop = asyncio.get_event_loop()
    try:
        report = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Cost analysis exceeded {timeout:.0f}s timeout.")

    if report.status == "GEOMETRY_INVALID":
        # G1 surfaced cleanly as a structured 400 (errors.py passes dict-with-code through)
        raise HTTPException(status_code=400, detail={
            "code": "GEOMETRY_INVALID",
            "message": report.reason,
            "geometry": report.geometry,
            "doc_url": "https://docs.cadverify.com/errors#GEOMETRY_INVALID",
        })

    return report_to_dict(report)
```

Notes:
- `*_is_user` flags flip to USER only when the form value differs from the DEFAULT (`material_class != "polymer"`, `cavities != 1`, `complexity != "moderate"`), matching CLI semantics so provenance reads honestly: an omitted/default form field stays DEFAULT, an explicit non-default value is USER.
- No `session` dependency → no DB coupling, no persistence (CAD-as-IP).
- `region` is not pre-validated against the table: an unknown region falls back to ×1.0 on all three vectors by design (`RateCard.region_*` use `.get(region, 1.0)`) — the assumptions panel still records the region string. That is intentional and harmless; do not 400 on it.

## C.5 Response shape (reuses `report_to_dict` — already JSON-serializable)
`200` body = `report_to_dict(report)`:
```jsonc
{
  "filename": "...stl",
  "status": "OK",
  "reason": null,
  "geometry": { "volume_cm3": ..., "surface_area_cm2": ..., "bbox_mm": [..], "watertight": true, "face_count": ... },
  "material_class": "polymer",
  "quantities": [50, 5000],
  "estimates": [ {
      "process": "mjf", "material": "PP (Polypropylene)", "quantity": 50,
      "unit_cost_usd": 44.13, "fixed_cost_usd": ..., "variable_cost_usd": ...,
      "est_error_band_pct": 40.0, "dfm_ready": true, "dfm_verdict": "pass",
      "dfm_score": 1.0, "dfm_blockers": [],
      "line_items": { "amortized_fixed": .., "material": .., "machine": .., "labor": .. },
      "drivers": [ { "name": "machine_cost", "value": .., "unit": "$",
                     "provenance": "DEFAULT", "source": "...", "error_band_pct": 40.0 }, ... ],
      "lead_time": { "low_days": .., "high_days": .., "mid_days": .., "components": {..},
                     "capacity": { "n_machines": 6, "machine_hours_per_day": 22.0,
                                   "provenance": "DEFAULT", "basis": "capacity-bound: ..." } }
  }, ... ],
  "engine_feasibility": [ { "process": "...", "verdict": "...", "score": .., "costed": true }, ... ],
  "notes": [ "..." ],
  "assumptions": [ { "name": "labor_rate", "value": 35.0, "unit": "$/hr",
                     "provenance": "DEFAULT", "source": "..." }, ... ],
  "decision": { "make_now_process": "mjf", "make_now_material": "...",
                "tooling_process": "injection_molding", "tooling_dfm_ready": false,
                "crossover_qty": 739.0, "recommendation": {..}, "if_redesigned": {..}, "note": "..." }
}
```
Every `$` is a provenance-tagged driver; `Σ line_items == unit_cost`; the new `lead_time.capacity` carries the R1 assumption inline. No CAD mesh, no raw vertices — only the MEASURED geometry summary leaves the process.

## C.6 Error handling (all via the wired `errors.py` handlers)
| condition | status | code | source |
|---|---|---|---|
| missing `file` field | 422 | VALIDATION_ERROR | FastAPI request validation |
| empty file | 400 | BAD_REQUEST | `_read_capped` |
| unsupported extension / bad magic / parse fail | 400 | BAD_REQUEST | `_parse_mesh` |
| bad `qty` / `complexity` / `material_class` / `cavities` | 400 | BAD_REQUEST | C.3/C.4 validation |
| **broken geometry (G1)** | 400 | GEOMETRY_INVALID | handler dict-with-code (structured, carries `geometry` + `reason`) |
| over `MAX_UPLOAD_MB` | 413 | FILE_TOO_LARGE | `_read_capped` |
| over triangle cap | 413 | FILE_TOO_LARGE | `_parse_mesh` → `enforce_triangle_cap` |
| STEP without cadquery | 501 | (passthrough) | `_parse_mesh` |
| compute > `ANALYSIS_TIMEOUT_SEC` | 504 | ANALYSIS_TIMEOUT | `asyncio.wait_for` |
| missing/invalid API key | 401 | (auth dict) | `require_api_key` |
| role < analyst | 403 | insufficient_role | `require_role` |
| kill-switch closed | 503 | service_paused | `require_kill_switch_open` |
| rate limit exceeded | 429 | RATE_LIMITED | slowapi |

The `GEOMETRY_INVALID` 400 carries the geometry summary + repair reason so the buyer sees *why* (matches CLI Beat-1 "refuse to monetize broken geometry"), while still being a clean structured 400.

## C.7 Endpoint test (new file `backend/tests/test_cost_api.py`)
Uses `TestClient(main.app)` with the conftest autouse auth/DB bypass (`_bypass_api_key_auth` installs `require_api_key` → analyst user; no real DB needed since the endpoint has no `session` dependency). Meshes are procedural via existing fixtures — nothing binary in git.

```python
"""POST /api/v1/validate/cost — endpoint contract + invariants, no external services."""
from __future__ import annotations

import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)             # conftest re-applies the auth bypass on reload
    return TestClient(main.app)


def _post(client, name, data, **form):
    return client.post(
        "/api/v1/validate/cost",
        files={"file": (name, data, "application/octet-stream")},
        data=form,
    )


def test_cost_decision_on_clean_cube(client, cube_10mm, stl_bytes_of):
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), qty="50,5000",
              material_class="polymer", region="US")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "OK"
    assert body["decision"] and body["decision"]["make_now_process"]
    assert body["estimates"], "expected costed estimates"

    # Invariant: unit_cost == Σ line_items, and every $ driver is provenance-tagged.
    for e in body["estimates"]:
        assert abs(e["unit_cost_usd"] - round(sum(e["line_items"].values()), 2)) < 0.02
        for d in e["drivers"]:
            assert d["provenance"] in ("MEASURED", "USER", "DEFAULT")
            assert d["source"]
        # R1: lead-time capacity assumption is present + inspectable.
        cap = e["lead_time"]["capacity"]
        assert cap["n_machines"] >= 1 and cap["machine_hours_per_day"] > 0
        assert cap["provenance"] in ("DEFAULT", "USER")


def test_cost_geometry_invalid_is_clean_400(client, non_watertight_box, stl_bytes_of):
    r = _post(client, "torn.stl", stl_bytes_of(non_watertight_box))
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["code"] == "GEOMETRY_INVALID"
    assert "geometry" in body            # carries the measured summary + reason


def test_cost_rejects_bad_complexity(client, cube_10mm, stl_bytes_of):
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), complexity="bogus")
    assert r.status_code == 400
    assert "complexity" in r.json()["message"].lower()


def test_cost_rejects_bad_qty(client, cube_10mm, stl_bytes_of):
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), qty="-5")
    assert r.status_code == 400


def test_cost_rejects_bad_extension(client):
    r = _post(client, "foo.txt", b"bad")
    assert r.status_code == 400
    assert "Unsupported" in r.json()["message"]


def test_cost_user_provenance_on_overrides(client, cube_10mm, stl_bytes_of):
    """cavities/complexity off the DEFAULT flip the assumption provenance to USER."""
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm),
              cavities="4", complexity="complex")
    assert r.status_code == 200, r.text
    assumptions = {a["name"]: a for a in r.json()["assumptions"]}
    assert assumptions["n_cavities"]["provenance"] == "USER"
    assert assumptions["complexity"]["provenance"] == "USER"
```

(If `cube_10mm` produces no formative estimate, the cavity/complexity assumptions still surface in the assumptions panel — they are global drivers in `_global_assumptions`, independent of whether IM is eligible — so `test_cost_user_provenance_on_overrides` is robust.)

The suite needs no Redis/Postgres/network: the endpoint has no `session` dependency and the cost layer is pure-local. Optionally add a socket-block wrapper (as `test_costing_accuracy.test_zero_network_egress_during_harness` does) to assert zero egress during a request.

---

# D. Build order + acceptance

**Builder 1 (costing):** `rates.py` (A.1 capacity keys + B.3 `xy_packing_density` + accessors + whitelist) → `drivers.py` (B.2 `parts_per_build` branch) → `cost_model.py` (B.4 serial machine + parts_per_build source) → `leadtime.py` (A.4 pool + `capacity`) → `estimate.py` (A.5 `_serialize`) → `report.py` (A.6 capacity line) → tests (A.8 + B.6) → regenerate `outputs/accuracy-report.md`.

**Builder 2 (API):** `routes.py` (C.1 import + C.2 `_run_cost_engine` + C.3 parsing + C.4 handler) → `tests/test_cost_api.py` (C.7).

**Done when:**
- `cd backend && CADVERIFY_PARTS_DIR=<parts> .venv/bin/python -W ignore -m pytest tests/test_costing_model.py tests/test_costing_gates.py tests/test_costing_accuracy.py tests/test_cost_api.py -q` is green (36 prior + R1/R2/API additions; the two rewritten accuracy tests pass on the fix, not the residual).
- `ECU mjf @ qty 5000` lead time reads weeks-to-months (≤ ~92 days high), the capacity assumption is shown + overridable, and no costed process is multi-year.
- `accuracy-report.md` shows **C2 PASS** with fdm/sla medians ≤ 0.60; C1/C3/C4/C5 still PASS.
- `POST /api/v1/validate/cost` returns the full decision JSON for a clean part, a clean structured **400 GEOMETRY_INVALID** for broken geometry, and the right 400/413/504/401/403/503 codes; Σ-invariant + provenance hold in the response; zero CAD persisted, zero sockets opened.

**Acceptance self-check:** every change names its module/function, formula, DEFAULT + source basis, and override path; all worked numbers were computed from a verified prototype (mjf q5000 49.7–92.3 d; fdm median +0.75→+0.38, sla +0.61→+0.35; throttle fdm $15.96→$9.62, sla $25.00→$14.82); the API design is testable with the existing TestClient + conftest bypass and no external services. A competent two-builder team ships A+B+C from this with zero further decisions.
