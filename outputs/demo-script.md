# CadVerify V0 Decision Layer — Demo Walkthrough (real parts, real output)

Everything below is **actual captured output** from running the V0 CLI on the
repo's real automotive STL parts with the venv Python. Nothing is hand-edited.
Reproduce with the commands in `build-readme.md`.

Read this as a manufacturing engineer would: every dollar resolves to a driver
(process · cycle/machine time · material mass × rate · setup · labor · lot size),
each tagged `MEASURED` (from the CAD), `USER` (you supplied it), or `DEFAULT`
(our stated, overridable assumption). Line items always sum to the unit cost.

---

## Part A — ECU Firewall Mount (flat polymer bracket)

`160 × 62 × 33 mm`, `66.79 cm³`, watertight. A non-rotational mounting bracket —
the kind of part where the real question is *"print it or tool it?"*

```
CadVerify Decision — 1090523_..._EK_0BD1_ECU_Firewall_mount.stl
========================================================================
Geometry: 66.79 cm³ · 160×62×32.6 mm · watertight ✓ · 1586 faces        [MEASURED]
Material class: polymer

PROCESS OPTIONS (should-cost, USD)
  injection_molding / PP (Molded)    qty 50: $603.39/unit   qty 5000: $9.39/unit    ±60%  ⚠ NOT DFM-ready as-modeled (design-for-process required)
      material_cost    $0.12  [MEASURED CAD volume 66.79 cm³ × PP (Molded) density 0.90 g/cm³ = 0.0601 kg × $2/kg × (1+0.03 scrap) ±5%]
      machine_cost     $1.52  [DEFAULT 0.0337 hr × $45/hr  [cooling 2·wall² = 2·7.63² = 116.4s + shot 5s = 121.4s = 0.0337 hr  [wall = 2V/A proxy, ±50%]] ±60%]
      labor_cost       $1.75  [DEFAULT post-process 0.05 hr × $35/hr ±20%]
      tooling_cost     $30,000.00  [DEFAULT size tier by max bbox 160 mm, single-cavity; ±60%, OVERRIDABLE ±60%]
      setup_cost       $0.00  [DEFAULT setup 0 hr × $35/hr (amortized over qty) ±20%]
      line items Σ = $603.39 (= amortized_fixed $600.00 + material $0.12 + machine $1.52 + labor $1.75)
      lead time qty 50: 22.4–41.6 days [queue 2 + tooling_lead 25 + production 1 + post_process 1 + ship 3]
      DFM blockers: 564 sidewall faces (96.9% of sidewall area) below 1.0° draft for injection_molding.

  sls / PA12 (Nylon 12)    qty 50: $126.12/unit   qty 5000: $125.78/unit    ±40%
      material_cost    $4.45  [MEASURED CAD volume 66.79 cm³ × PA12 (Nylon 12) density 1.01 g/cm³ = 0.0675 kg × $60/kg × (1+0.1 scrap) ±5%]
      machine_cost     $103.82  [DEFAULT 5.1910 hr × $20/hr  [cycle = V/18 + h/22 = 66.79/18 + 32.6/22 = 5.19 hr (single-orientation, build height = smallest extent 32.6 mm)] ±40%]
      labor_cost       $17.50  [DEFAULT post-process 0.5 hr × $35/hr ±20%]
      setup_cost       $17.50  [DEFAULT setup 0.5 hr × $35/hr (amortized over qty) ±20%]
      line items Σ = $126.12 (= amortized_fixed $0.35 + material $4.45 + machine $103.82 + labor $17.50)
      lead time qty 50: 28–52 days [queue 3 + production 33 + post_process 1 + ship 3]

  cnc_5axis / Delrin (POM)    qty 50: $61.56/unit   qty 5000: $60.87/unit    ±50%
      material_cost    $1.22  [MEASURED hull volume 150.27 cm³ × 1.10 stock allowance × Delrin (POM) density 1.41 g/cm³ = 0.2331 kg × $5/kg × (1+0.05 scrap) ±5%]
      machine_cost     $42.14  [DEFAULT 0.3831 hr × $110/hr  [rough 98.5 cm³ ÷ (50 cm³/min·60) = 0.033 hr + finish 175.1 cm² ÷ 500 cm²/hr = 0.350 hr  [stock hull 150.3 cm³ × 1.10 = 165.3 cm³; MRR polymer]] ±50%]
      labor_cost       $17.50  [DEFAULT post-process 0.5 hr × $35/hr ±20%]
      setup_cost       $35.00  [DEFAULT setup 1 hr × $35/hr (amortized over qty) ±20%]
      line items Σ = $61.56 (= amortized_fixed $0.70 + material $1.22 + machine $42.14 + labor $17.50)
      lead time qty 50: 9.8–18.2 days [queue 7 + production 3 + post_process 1 + ship 3]

  fdm / PLA    qty 50: $55.02/unit   qty 5000: $54.85/unit    ±40%
      material_cost    $2.28  [MEASURED CAD volume 66.79 cm³ × PLA density 1.24 g/cm³ = 0.0828 kg × $25/kg × (1+0.1 scrap) ±5%]
      machine_cost     $43.82  [DEFAULT 5.4772 hr × $8/hr  [cycle = V/16 + h/25 = 66.79/16 + 32.6/25 = 5.48 hr (single-orientation, build height = smallest extent 32.6 mm)] ±40%]
      labor_cost       $8.75  [DEFAULT post-process 0.25 hr × $35/hr ±20%]
      setup_cost       $8.75  [DEFAULT setup 0.25 hr × $35/hr (amortized over qty) ±20%]
      line items Σ = $55.02 (= amortized_fixed $0.17 + material $2.28 + machine $43.82 + labor $8.75)
      lead time qty 50: 28.7–53.3 days [queue 2 + production 35 + post_process 1 + ship 3]

  (also costed, omitted for brevity: sla $141.77, dlp $101.86, mjf $120.11, cnc_3axis $43.60⚠)

DECISION
  Make by fdm for ≤ ~583 units; invest in injection_molding tooling above ~583. NOTE: injection_molding is not DFM-ready as modeled (fail) — requires design-for-molding (add draft) before tooling.
  Crossover ≈ 582.9 units (make fdm below; tool injection_molding above).
  @ qty 50     → cnc_3axis / Delrin (POM) ($43.60/unit, 8.4–15.6 d)  [requires design-for-process]
             cheapest DFM-ready as-is: fdm ($55.02/unit)
  @ qty 5000   → injection_molding / PP (Molded) ($9.39/unit, 37.1–68.9 d)  [requires design-for-process]
             cheapest DFM-ready as-is: fdm ($54.85/unit)

ASSUMPTIONS (all DEFAULT unless tagged USER; every one overridable)
  labor_rate $35/hr [DEFAULT] · region_multiplier 1× [DEFAULT] · margin 0 [DEFAULT] · stock_allowance 1.1× [DEFAULT] · daily_machine_hours 8hr/day [DEFAULT] · material_class polymer [DEFAULT]
  • Absolute cost is ±40–60% (cycle-time/tooling defaults). The crossover quantity and make-vs-buy direction are robust to it because they depend on the fixed-vs-variable split, driven by your rates.

ENGINE FEASIBILITY (DFM, all processes; * = feasibility-only, not costed):
  fdm issues(0.8) · sla issues(0.8) · dlp issues(0.9) · sls pass(1) · mjf pass(1) · ... · cnc_3axis fail(0) · cnc_5axis issues(0.8) · cnc_turning pass(1) · injection_molding fail(0) · die_casting fail(0) · ...

[wall-clock 0.44s · IP-local, zero network calls]
```

### How to read it (the four answers a buyer asked for)
1. **Cost — explainable.** SLS at qty 50 = `$126.12`. Trace it: material `$4.45`
   = MEASURED CAD volume 66.79 cm³ × PA12 density 1.01 g/cm³ = 0.0675 kg × `$60/kg`
   × 1.10 scrap; machine `$103.82` = cycle 5.19 hr (`V/18 + h/22`, deposition +
   layer-up) × `$20/hr`; labor `$17.50`; amortized setup `$0.35`. The four lines
   sum to `$126.12` exactly — that's enforced, not coincidental.
2. **Lead time — components, not a fake date.** SLS qty 50 = `28–52 days` =
   queue 3 + production `ceil(50 × 5.19 hr / 8 hr-day) = 33` + post 1 + ship 3,
   ±30% band. It scales with quantity (qty 5000 production days dominate).
3. **Crossover — the wedge.** `≈ 583 units`. Below it, **make** by FDM ($55/unit,
   ~no fixed cost); above it, **tool** injection molding (the $30k tool amortizes:
   $603/unit at 50 → $9.39/unit at 5000). The number is `(fixed_IM − fixed_FDM) /
   (var_FDM − var_IM)` — pure fixed-vs-variable economics, so it's stable even
   though absolute $ is ±40–60%.
4. **Make-vs-buy — honest.** The headline says make-by-FDM-below / tool-IM-above,
   AND flags that injection molding is **not DFM-ready as-modeled**: the engine
   found `564 sidewall faces (96.9%) below 1.0° draft`. So the real action item is
   *"redesign with draft, then the $30k tool pays off past ~583 units."* No fake
   "moldable" verdict; the blocker is shown.

### Two routing fixes visible here (the teardown's G2 bugs, dead)
- The engine's feasibility row says `cnc_turning pass(1)` — but **turning is NOT in
  the costed options**. A 160×62×33 mm flat bracket is not rotational, so the
  decision layer refuses to route it to a lathe. (On Part B, which *is* rotational,
  turning appears and wins — see below.)
- CNC materials are `Delrin (POM)` — a machinable polymer — **not** Inconel 718.
  The teardown's "plastic bracket → Inconel superalloy" bug is structurally
  impossible: materials are re-selected by family (polymer), cheapest-compatible.

---

## Part B — Throttle Body Adapter (rotational part)

`40 × 34 × 22 mm`, `2.81 cm³`, watertight, roundness 0.85 / L:D 0.60 → rotational,
so **CNC turning becomes eligible** and is the cheapest make-as-is route.

```
CadVerify Decision — printables_122552_ThrottleBodyAdapter.stl
========================================================================
Geometry: 2.81 cm³ · 39.9×34×22.2 mm · watertight ✓ · 23786 faces        [MEASURED]
Material class: polymer

PROCESS OPTIONS (should-cost, USD)
  cnc_turning / Delrin (POM)    qty 100: $14.93/unit   qty 10000: $14.76/unit    ±50%
      material_cost    $0.14  [MEASURED hull volume 17.60 cm³ × 1.10 stock allowance × Delrin (POM) density 1.41 g/cm³ = 0.0273 kg × $5/kg × (1+0.05 scrap) ±5%]
      machine_cost     $4.11  [DEFAULT 0.0633 hr × $65/hr  [rough 21.0 cm³ ÷ (50 cm³/min·60) = 0.007 hr + finish 45.0 cm² ÷ 800 cm²/hr = 0.056 hr  [stock bounding cylinder π·(37.0/2)²·22.2 mm = 23.8 cm³; MRR polymer]] ±50%]
      labor_cost       $10.50  [DEFAULT post-process 0.3 hr × $35/hr ±20%]
      setup_cost       $17.50  [DEFAULT setup 0.5 hr × $35/hr (amortized over qty) ±20%]
      line items Σ = $14.93 (= amortized_fixed $0.17 + material $0.14 + machine $4.11 + labor $10.50)
      lead time qty 100: 7–13 days [queue 5 + production 1 + post_process 1 + ship 3]

  fdm / PLA    qty 100: $17.44/unit   qty 10000: $17.35/unit    ±40%
      material_cost    $0.10  [MEASURED CAD volume 2.81 cm³ × PLA density 1.24 g/cm³ = 0.0035 kg × $25/kg × (1+0.1 scrap) ±5%]
      machine_cost     $8.50  [DEFAULT 1.0629 hr × $8/hr  [cycle = V/16 + h/25 = 2.81/16 + 22.2/25 = 1.06 hr (single-orientation, build height = smallest extent 22.2 mm)] ±40%]
      labor_cost       $8.75  [DEFAULT post-process 0.25 hr × $35/hr ±20%]
      setup_cost       $8.75  [DEFAULT setup 0.25 hr × $35/hr (amortized over qty) ±20%]
      line items Σ = $17.44 (= amortized_fixed $0.09 + material $0.10 + machine $8.50 + labor $8.75)
      lead time qty 100: 14–26 days [queue 2 + production 14 + post_process 1 + ship 3]

  injection_molding / PP (Molded)    qty 100: $61.86/unit   qty 10000: $2.46/unit    ±60%  ⚠ NOT DFM-ready as-modeled (design-for-process required)
      material_cost    $0.01  [MEASURED CAD volume 2.81 cm³ × PP (Molded) density 0.90 g/cm³ = 0.0025 kg × $2/kg × (1+0.03 scrap) ±5%]
      machine_cost     $0.10  [DEFAULT 0.0023 hr × $45/hr  [cooling 2·wall² = 2·1.25² = 3.1s + shot 5s = 8.1s = 0.0023 hr  [wall = 2V/A proxy, ±50%]] ±60%]
      labor_cost       $1.75  [DEFAULT post-process 0.05 hr × $35/hr ±20%]
      tooling_cost     $6,000.00  [DEFAULT size tier by max bbox 40 mm, single-cavity; ±60%, OVERRIDABLE ±60%]
      setup_cost       $0.00  [DEFAULT setup 0 hr × $35/hr (amortized over qty) ±20%]
      line items Σ = $61.86 (= amortized_fixed $60.00 + material $0.01 + machine $0.10 + labor $1.75)
      lead time qty 100: 22.4–41.6 days [queue 2 + tooling_lead 25 + production 1 + post_process 1 + ship 3]
      DFM blockers: 1722 sidewall faces (88.7% of sidewall area) below 1.0° draft for injection_molding.

  (also costed: cnc_5axis $28.50, sla $35.31, dlp $29.47, sls $41.15, mjf $40.29, cnc_3axis $23.95⚠)

DECISION
  Make by fdm for ≤ ~387 units; invest in injection_molding tooling above ~387. NOTE: injection_molding is not DFM-ready as modeled (fail) — requires design-for-molding (add draft) before tooling.
  Crossover ≈ 386.7 units (make fdm below; tool injection_molding above).
  @ qty 100    → cnc_turning / Delrin (POM) ($14.93/unit, 7–13 d)
  @ qty 10000  → injection_molding / PP (Molded) ($2.46/unit, 23.8–44.2 d)  [requires design-for-process]
             cheapest DFM-ready as-is: cnc_turning ($14.76/unit)

[wall-clock 9.29s · IP-local, zero network calls]
```

### Walkthrough
- **Turning surfaces only because the part is rotational.** Stock is a bounding
  **cylinder** `π·(37/2)²·22.2 mm = 23.8 cm³` (not a hull billet), turned down to
  2.81 cm³ — that's why machine cost is just `$4.11`. Turning wins as-is at low
  volume: `$14.93/unit`.
- **Crossover ≈ 387 units.** This part's tool is only `$6,000` (size tier S,
  40 mm) — a *much* smaller bet than the bracket's $30k tool, so the crossover is
  lower. At 10,000 units injection molding collapses to `$2.46/unit`. Again the
  layer is honest: that molding route **needs draft added first**.
- The cheapest **DFM-ready** option at 10k is still `cnc_turning` ($14.76) — shown
  so a buyer who can't redesign knows their real floor without faking moldability.

---

## Part C — MAF Sensor Adapter (broken geometry) → the credibility fix

This is the teardown's headline bug: a mesh that loads as `volume = 0 mm³`,
non-watertight, yet the raw engine still returns `sls pass score=1.00`. V0 refuses
to put a price on it.

```
CadVerify Decision — 655044_..._MAF_Sensor_Adapter_for_High_Flow_Air_filetr.stl
========================================================================
Geometry: 0 cm³ · 173.8×127.5×104.1 mm · watertight ✗ · 18028 faces        [MEASURED]

GEOMETRY INVALID — repair required (volume ≤ 0 / non-watertight). No cost produced.
  Reason: Geometry is not a measurable solid (volume ≤ 0 or non-watertight). Cost requires a watertight, positive-volume mesh. Repair required.

ENGINE FEASIBILITY (DFM, all processes; * = feasibility-only, not costed):
  fdm issues(0.9) · sla fail(0) · dlp fail(0) · sls pass(1) · mjf pass(1) · ... · cnc_turning pass(1) · injection_molding fail(0) · ...

[wall-clock 3.82s · IP-local, zero network calls]
```

The engine row still shows `sls pass(1)` — but the **G1 robustness gate** returns
`GEOMETRY_INVALID` with **zero** estimates and a one-line repair instruction. No
fabricated cost, no confident "pass" on garbage. Across the full set this gate
refuses **11 of 105** STL parts (including this MAF adapter and the Upper Intake
Manifold Gasket); the other 94 are costed.

---

## Why this is credible (and where it is honest about its limits)
- **Every number is traceable.** Process · cycle/machine time · material mass × rate
  · setup · labor · lot size — each a provenance-tagged driver with a `source`
  string. Line items sum to the unit cost (asserted). No toy `cost_per_cm3`.
- **The decision is what we stand behind, not the absolute dollar.** Absolute cost
  is ±40–60% (cycle/tooling defaults the buyer overrides). The crossover quantity
  and make-vs-buy direction come from the fixed-vs-variable *shape* driven by the
  buyer's own rates, so they hold even when absolute $ is uncertain. Validation
  anchor: a ~67 cm³ nylon SLS bracket at low volume from a service bureau commonly
  runs ~$80–180/unit; V0's SLS estimate ($126) lands inside that band — a
  positioning check, not a precision claim.
- **It refuses to lie.** Broken geometry → no cost (G1). A draft-less printed part
  → molding is costed but flagged *not DFM-ready, design-for-molding required*, with
  the engine's exact blocker. No supplier pricing, no CO₂, no metal-AM costing — all
  named V1/V2, none faked.
- **IP-local & fast.** Zero network calls (asserted in test G7); sub-10 s wall-clock
  on these meshes.
```
