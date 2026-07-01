# CadVerify — V0 Decision-Layer Spec (Cycle 1, Architect)

**Author:** Architect agent · **Date:** 2026-06-28 · **Status:** BUILD-READY (V0 only; human-validation gate respected)
**Inputs fused:** `outputs/teardown.md`, `outputs/strategy.md`, live codebase + verified probe runs on real parts.
**Locked decision honored:** cost source-of-truth = **(b) user-supplied shop rates + explicit, traceable driver assumptions** (strategy §2). Every number is MEASURED, USER, or a stated/overridable DEFAULT. No fabricated cost, ever.

**Acceptance contract for the Builder:** everything below is decided. Build exactly this. There are no open choices. If a default looks wrong, it is still the V0 default — ship it, flag it DEFAULT, make it overridable. Do **not** invent new behavior.

---

## 0. Scope (hard boundary — read first)

**IN (V0):**
- A new, self-contained Python package `backend/src/costing/` that consumes the existing engine's `AnalysisResult` + `mesh` + `features` and produces an **explainable should-cost, lead-time range, quantity crossover, and make-vs-buy direction** for a curated set of costed processes.
- A runnable **CLI** (`python -m src.costing.cli <part.stl> ...`) that runs the canonical engine sequence and prints a decision card + writes a JSON sidecar. Demoable on ≥2 real parts (ship it working on the ECU Firewall Mount and the Throttle Body Adapter).
- A **robustness gate** that refuses to cost broken geometry (vol ≤ 0 or non-watertight) — the single biggest credibility fix.
- Unit tests asserting G1–G7 from strategy §3 on the repo's real parts.

**OUT (explicitly not V0 — do not build):**
- API endpoint wiring (a stub signature is given §11; leave it commented/unrouted).
- Supplier-quote integration / live pricing / any network egress (violates CAD-as-IP; that is V2).
- Curated regional cost **libraries** (V1). V0 ships one default rate card + a region multiplier table.
- CO₂, PDF, frontend, DB persistence, batch-of-1000s.
- Costing the full 21 processes. V0 costs a **bounded shortlist** (§5.3); the rest get feasibility-only labels.
- Touching `profile_matcher._estimate_cost_factor` — leave the toy factor in place (legacy field), do **not** "upgrade it in place." The decision layer is additive and lives in `src/costing/`.

---

## 1. How the decision layer attaches to the engine

### 1.1 Data flow (no changes to the engine's hot path)

The engine already produces everything the cost layer needs; we **consume**, never fork it. Canonical sequence (verified, mirrors `routes.py::validate_demo`):

```
import src.analysis.processes                       # populate registry (21 analyzers)
mesh = trimesh.load(path, force='mesh')
geometry = analyze_geometry(mesh)                   # GeometryInfo (volume, area, bbox, watertight…)
ctx = GeometryContext.build(mesh, geometry)
features = detect_features(mesh); ctx.features = features
universal = run_universal_checks(mesh)
scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
          for p in pbase._REGISTRY if get_analyzer(p)]
result = AnalysisResult(filename=…, file_type='stl', geometry=geometry,
                        segments=ctx.segments, universal_issues=universal,
                        process_scores=scores)
rank_processes(result)
# ── NEW: decision layer ──
from src.costing import estimate_decision, EstimateOptions
report = estimate_decision(result, mesh, features, EstimateOptions(quantities=[50, 5000],
                                                                   material_class="polymer"))
```

The cost layer's **only** inputs:
- `result: AnalysisResult` — feasibility per process (`process_scores[*].verdict/score`), `universal_issues`, `geometry`.
- `mesh: trimesh.Trimesh` — for the few MEASURED drivers not on `GeometryInfo` (convex-hull volume → CNC stock; principal inertia + extents → rotational test; nominal wall = 2·V/A).
- `features: list[Feature]` — cylinder axes/radii for routing sanity (optional refinement; the rotational test below does not require it).
- `options: EstimateOptions` — buyer inputs (quantities, material class, any rate overrides).

It **never** mutates `result`, the engine, or the registry. It is import-isolated: `src/costing/` imports only from `src.analysis.models`, `src.profiles.database`, `numpy`, `trimesh`, stdlib.

### 1.2 New module layout (create exactly these files)

```
backend/src/costing/
  __init__.py          # exports: estimate_decision, EstimateOptions, DecisionReport, RATE_CARD_V0
  provenance.py        # Provenance enum, Driver dataclass, helpers
  rates.py             # RATE_CARD_V0: the full default rate table (§6) + MATERIAL_FAMILY map
  drivers.py           # extract_drivers(geometry, mesh, features) -> GeoDrivers  (all MEASURED)
  routing.py           # eligible_processes(), select_material(), is_rotational()   (kills G2)
  cost_model.py        # cost_breakdown(process, drivers, material, qty, rates, opts) -> CostEstimate
  leadtime.py          # lead_time(process, drivers, qty, rates, opts) -> LeadTime
  decision.py          # crossover(), make_vs_buy(), assemble DecisionReport
  estimate.py          # estimate_decision(): orchestrator + G1 robustness gate
  report.py            # render_text(report) -> str ; report_to_dict(report) -> dict (JSON)
  cli.py               # __main__ entry: parse args, run engine, call estimate_decision, print + write JSON
backend/tests/
  test_costing_gates.py   # G1–G7 assertions on real parts
  test_costing_model.py   # unit tests: Σ(lines)=total, monotonic sensitivity, crossover math
```

`estimate.py::estimate_decision` is the single public entry. `cli.py` is the demo surface.

---

## 2. The provenance model (this tagging *is* the product — strategy §2)

`provenance.py`:

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

class Provenance(str, Enum):
    MEASURED = "MEASURED"   # extracted from the CAD — not assumable
    USER     = "USER"       # buyer-supplied — authoritative
    DEFAULT  = "DEFAULT"    # our stated assumption — always visible, always overridable

@dataclass
class Driver:
    name: str                       # "material_mass", "machine_rate", "cycle_time", …
    value: float
    unit: str                       # "kg", "$/hr", "hr", "$", "units", …
    provenance: Provenance
    source: str                     # e.g. "CAD volume 66.8 cm³ × density 1.01 g/cm³"
    error_band_pct: Optional[float] = None   # ± % for estimated drivers (None = exact)

@dataclass
class CostEstimate:
    process: str
    material: str
    quantity: int
    unit_cost_usd: float            # == sum of per-unit line items below
    fixed_cost_usd: float           # setup_labor + tooling (amortized component, pre-/qty)
    variable_cost_usd: float        # per-unit material+machine+labor (qty-independent)
    drivers: list[Driver]           # every line item, each tagged
    line_items: dict[str, float]    # {"material":…, "machine":…, "labor":…, "amortized_fixed":…}
    est_error_band_pct: float       # rolled-up band (see §6.5)
```

**Hard rule enforced in `cost_model.py`:** `abs(unit_cost_usd - sum(line_items.values())) < 0.01`. Σ(lines) == total, or it is a bug (this is gate G3's test). Every `Driver` carries a non-empty `source`. No naked numbers anywhere in the output (gate G6).

---

## 3. MEASURED geometry drivers (`drivers.py`)

`extract_drivers(geometry, mesh, features) -> GeoDrivers`. All MEASURED. Verified values shown for the **ECU Firewall Mount** (the demo part).

```python
@dataclass
class GeoDrivers:
    volume_cm3: float          # geometry.volume / 1000                         # 66.79
    surface_area_cm2: float    # geometry.surface_area / 100                    # 175.13
    bbox_mm: tuple             # sorted(geometry.bounding_box.dimensions)       # (32.6, 62.0, 160.0)
    bbox_volume_cm3: float     # product(bbox)/1000                             # 323.30
    hull_volume_cm3: float     # mesh.convex_hull.volume / 1000 (fallback bbox) # 150.27
    nominal_wall_mm: float     # 2 * volume / surface_area  (plate proxy)       # 7.63
    face_count: int            # geometry.face_count                            # 1586
    is_valid: bool             # geometry.volume > 0 AND geometry.is_watertight # True
    # rotational descriptors (from routing.is_rotational)
    rotational: bool           # see §5.1                                       # False (bracket)
    rot_axis_len_mm: float
    rot_cross_dia_mm: float
```

Formulas (each a stated MEASURED source string):
- `mass_kg(density_g_cm3) = volume_cm3 * density_g_cm3 / 1000`
  → ECU in PA12 (1.01 g/cm³): `66.79 * 1.01 / 1000 = 0.0675 kg`. Source string: `"CAD volume 66.79 cm³ × PA12 density 1.01 g/cm³"`.
- `stock_mass_kg(density) = hull_volume_cm3 * STOCK_ALLOWANCE * density / 1000` — used for CNC material (you buy the billet, not the part). `STOCK_ALLOWANCE = 1.10`.
- `nominal_wall_mm = 2 * volume / surface_area` — molding cooling proxy. Stated as a proxy with ±50% band.
- `hull_volume` guard: `try mesh.convex_hull.volume; except → bbox_volume_cm3`.

> Probe-verified availability (do not re-derive): `geometry.volume`, `geometry.surface_area`, `geometry.bounding_box.dimensions`, `mesh.convex_hull.volume`, `mesh.principal_inertia_components`, `mesh.extents` all return on the real parts.

---

## 4. ROBUSTNESS GATE G1 (must be the first thing `estimate_decision` does)

This is the credibility killer from the teardown (MAF adapter: vol=0, non-watertight → "sls pass cost=0.2"). **Kill it at the top:**

```python
def estimate_decision(result, mesh, features, options) -> DecisionReport:
    g = result.geometry
    invalid = (g.volume is None) or (g.volume <= 0.0) or (not g.is_watertight) \
              or any(i.severity == Severity.ERROR for i in result.universal_issues)
    if invalid:
        return DecisionReport(
            filename=result.filename,
            status="GEOMETRY_INVALID",
            reason="Geometry is not a measurable solid (volume ≤ 0 or non-watertight). "
                   "Cost requires a watertight, positive-volume mesh. Repair required.",
            estimates=[], decision=None, geometry=_geo_summary(g))
    ...
```

**Output for invalid parts:** `status="GEOMETRY_INVALID"`, **zero** cost estimates, **no** verdict=pass, a one-line repair instruction. CLI prints: `GEOMETRY INVALID — repair required (volume ≤ 0 / non-watertight). No cost produced.` This must hold for **100%** of the 107 real parts (G1 test). The MAF Sensor Adapter and the Upper Intake Manifold Gasket must hit this path.

---

## 5. SANE ROUTING (`routing.py`) — kills G2 (Inconel-for-plastic, turning-for-brackets)

The engine's `score_process` picks `materials[0]` positionally and never checks rotational fit. The decision layer **never reuses** the engine's `recommended_material`. It re-derives a sane material and a sane process shortlist.

### 5.1 Rotational predicate `is_rotational(geometry, mesh) -> (bool, axis_len, cross_dia)`

Probe finding (ground truth): principal-inertia ratio **alone is misleading** (flat bracket = 1.12, *more* "axisymmetric" than the round ring = 1.57). The clean discriminator is **cross-section roundness** + **turnable aspect**:

```python
def is_rotational(geometry, mesh):
    d = sorted(geometry.bounding_box.dimensions)          # [d0 <= d1 <= d2]
    # For each candidate axis, roundness = min/max of the two PERPENDICULAR extents
    candidates = [
        (d[0], d[1], d[2]),   # axis = d0  -> cross (d1,d2)
        (d[1], d[0], d[2]),   # axis = d1  -> cross (d0,d2)
        (d[2], d[0], d[1]),   # axis = d2  -> cross (d0,d1)
    ]
    best = None
    for axis_len, c1, c2 in candidates:
        roundness = min(c1, c2) / max(c1, c2)
        cross_dia = 0.5 * (c1 + c2)
        if best is None or roundness > best[0]:
            best = (roundness, axis_len, cross_dia)
    roundness, axis_len, cross_dia = best
    rotational = (roundness >= 0.80) and (cross_dia >= 5.0) and (0.25 <= axis_len / cross_dia <= 8.0)
    return rotational, axis_len, cross_dia
```

Verified outcomes (thresholds chosen to match these): ECU bracket roundness **0.526 → NOT rotational** (excluded from turning ✓); Throttle Body Ring 0.903, L/D 0.45 → rotational ✓; **0.6 mm Gasket** roundness 0.866 but L/D 0.016 < 0.25 → **NOT turnable** ✓ (a paper-thin disc is laser/water-jet cut, not turned); Throttle Body Adapter 0.851, L/D 0.60 → rotational ✓.

### 5.2 Material class + sane material selection (`select_material`)

`material_class` is a **USER** input with stated **DEFAULT = "polymer"** (these are polymer automotive ECU parts; the buyer overrides for metal). Allowed classes: `polymer, aluminum, steel, stainless, titanium`. Each material in `profiles.database.MATERIALS` is tagged to a family via a curated `MATERIAL_FAMILY` dict in `rates.py` (Builder fills all ~40 entries; mapping is mechanical — by alloy/polymer name).

```python
def select_material(process, material_class, rates):
    mats = [m for m in get_materials_for_process(process)
            if MATERIAL_FAMILY.get(m.name) == material_class
            and m.density and m.cost_per_kg]
    if not mats:
        return None                      # process not eligible for this class
    return min(mats, key=lambda m: m.cost_per_kg)   # cheapest compatible = sane default pick
```

Consequences (structurally eliminates the teardown's worst bug): CNC + polymer → **Delrin/PEEK** (machinable polymers), never Inconel; CNC + aluminum → **6061-T6**; SLS + polymer → **PA12**; injection molding + polymer → **PP/ABS molded**. There is **no positional `materials[0]`** and **no superalloy on a polymer part**, by construction.

### 5.3 Process shortlist (`eligible_processes`)

V0 costs only the bounded **`COSTED_PROCESSES`** set (those with a defensible cost model below). All other feasible processes are listed feasibility-only (`"costed": false`, no number — honest).

```python
COSTED_PROCESSES = {FDM, SLA, DLP, SLS, MJF, CNC_3AXIS, CNC_5AXIS, CNC_TURNING,
                    INJECTION_MOLDING, DIE_CASTING}
```

`eligible_processes(result, drivers, material_class, rates)` returns the subset of `COSTED_PROCESSES` where **all** hold:
1. **DFM-feasible:** the engine's `ProcessScore` for that process has `verdict != "fail"` and `score > 0`.
2. **Material-compatible:** `select_material(process, material_class) is not None`.
3. **Routing-sane:**
   - `CNC_TURNING` → only if `drivers.rotational` (§5.1).
   - `INJECTION_MOLDING` → only if `material_class == "polymer"`.
   - `DIE_CASTING` → only if `material_class in {aluminum, steel, stainless}`.
   - metal AM is excluded from V0 cost (not in `COSTED_PROCESSES`); all AM here is polymer AM.

This guarantees the gate G2 assertions: turning never surfaces for the bracket; no superalloy for a polymer part.

---

## 6. THE COST MODEL (`cost_model.py`) — formulas + the locked default rate card

### 6.1 Master formula (strategy §2, itemized)

```
unit_cost(qty) = ( fixed_cost / qty                       ← amortized FIXED
                 + material_cost                          ← MATERIAL
                 + machine_cost                           ← MACHINE (cycle_time × rate)
                 + labor_cost )                           ← LABOR / FINISH
               × region_multiplier × (1 + margin)

fixed_cost    = setup_time_hr × labor_rate + tooling_cost
material_cost = input_mass_kg × material_$per_kg × (1 + scrap_factor)
machine_cost  = cycle_time_hr × machine_rate_$per_hr
labor_cost    = post_process_time_hr × labor_rate
input_mass_kg = AM/molding: part_mass × (1+scrap) ;  CNC: stock_mass (you buy the billet)
```

`region_multiplier` DEFAULT = 1.00 (US baseline). `margin` DEFAULT = 0.0 (this is a **should-cost**, not a price). Both USER-overridable. Each term is a `Driver` with provenance + source + error band.

### 6.2 Cycle-time sub-models (each with formula + stated error band)

**Additive (FDM/SLA/DLP/SLS/MJF).** Default orientation = **smallest bbox dimension along build-Z** (minimizes layer count; stated). Error band **±40%**.
```
build_height_mm = d_small                      # smallest extent up
cycle_hr = volume_cm3 / deposition_rate_cm3_hr[proc]
         + build_height_mm / vertical_rate_mm_hr[proc]
```
Stated assumption surfaced in output: *"per-part, single-orientation; powder-bed nesting reduces effective per-part time — DEFAULT is worst-case isolated build."*

**CNC (3-axis/5-axis/turning).** Material-removal model. Error band **±50%** (the least-certain driver — strategy §2 names this explicitly; the buyer overrides cycle_time to their real value and the model recomputes).
```
stock_volume_cm3 = hull_volume_cm3 × STOCK_ALLOWANCE            # 3/5-axis
                 = π·(cross_dia/2)²·axis_len / 1000             # turning: bounding cylinder
removed_cm3 = max(0, stock_volume_cm3 − volume_cm3)
rough_hr  = removed_cm3 / (MRR_cm3_min[material_class] × 60)
finish_hr = surface_area_cm2 / finish_rate_cm2_hr[proc]
cycle_hr  = rough_hr + finish_hr
```

**Injection molding / die casting.** Per-part machine cost is small; the **tooling** dominates fixed cost (the crossover driver). Error band **±60%** on tooling, ±50% on cycle.
```
cooling_s = COOLING_COEF × nominal_wall_mm²                     # cooling ∝ wall²
cycle_s   = cooling_s + SHOT_OVERHEAD_s
cycle_hr  = cycle_s / 3600
tooling_cost = TOOLING_BY_SIZE[size_tier(max_bbox_mm)]          # die_casting = ×1.5
```

### 6.3 RATE_CARD_V0 — the concrete, reproducible default table (`rates.py`)

Every value below is **DEFAULT**, ships in `RATE_CARD_V0`, and is overridable via `EstimateOptions.rate_overrides`. These are stated assumptions, not claimed truth (gate G6).

**Global defaults**
| key | value | unit | notes |
|---|---|---|---|
| `labor_rate` | 35.00 | $/hr | loaded shop-floor labor |
| `region_multiplier` | 1.00 | × | US baseline (table below) |
| `margin` | 0.00 | frac | should-cost, not price |
| `STOCK_ALLOWANCE` | 1.10 | × | CNC billet oversize on hull |
| `daily_machine_hours` | 8 | hr/day | for lead-time production days |

**Per-process rates**
| process | machine_rate $/hr | setup_hr | post_hr | scrap | deposition cm³/hr | vert mm/hr | finish cm²/hr | queue_days | post_days |
|---|---|---|---|---|---|---|---|---|---|
| FDM | 8 | 0.25 | 0.25 | 0.10 | 16 | 25 | — | 2 | 1 |
| SLA | 12 | 0.30 | 0.50 | 0.10 | 8 | 20 | — | 2 | 1 |
| DLP | 12 | 0.30 | 0.50 | 0.10 | 12 | 30 | — | 2 | 1 |
| SLS | 20 | 0.50 | 0.50 | 0.10 | 18 | 22 | — | 3 | 1 |
| MJF | 22 | 0.50 | 0.50 | 0.10 | 20 | 25 | — | 3 | 1 |
| CNC_3AXIS | 75 | 0.75 | 0.50 | 0.05 | — | — | 600 | 5 | 1 |
| CNC_5AXIS | 110 | 1.00 | 0.50 | 0.05 | — | — | 500 | 7 | 1 |
| CNC_TURNING | 65 | 0.50 | 0.30 | 0.05 | — | — | 800 | 5 | 1 |
| INJECTION_MOLDING | 45 | 0.00 | 0.05 | 0.03 | — | — | — | 2 | 1 |
| DIE_CASTING | 90 | 0.00 | 0.10 | 0.03 | — | — | — | 3 | 2 |

**CNC material-removal rate (MRR, cm³/min) by material class**
| class | polymer | aluminum | steel | stainless | titanium |
|---|---|---|---|---|---|
| MRR | 50 | 30 | 8 | 5 | 2 |

**Molding/casting constants:** `COOLING_COEF = 2.0` s/mm², `SHOT_OVERHEAD_s = 5.0`.
**Tooling by size tier** (max bbox dim → single-cavity tool, DEFAULT, ±60%):
| tier | max bbox | IM tooling $ | die-cast (×1.5) $ |
|---|---|---|---|
| S | < 50 mm | 6,000 | 9,000 |
| M | 50–150 mm | 15,000 | 22,500 |
| L | 150–300 mm | 30,000 | 45,000 |
| XL | > 300 mm | 60,000 | 90,000 |

**Region multiplier table** (DEFAULT, USER selectable): US 1.00 · EU 1.10 · MX 0.75 · CN 0.65 · IN 0.60 · SA (Saudi) 1.05.

### 6.4 Worked example — ECU Firewall Mount (verified geometry: V=66.79 cm³, bbox 160×62×33, watertight)

**SLS / PA12** (cheapest polymer SLS): mass = 0.0675 kg; height-up = 32.6 mm.
- material = 0.0675 × 60 × 1.10 = **$4.46**
- cycle = 66.79/18 + 32.6/22 = 3.71 + 1.48 = 5.19 hr → machine = 5.19 × 20 = **$103.8**
- labor (post) = 0.50 × 35 = **$17.5** ; fixed = setup 0.50 × 35 = $17.5, tooling 0
- unit@50 = 17.5/50 + 4.46 + 103.8 + 17.5 = **$126.1** ; unit@5000 ≈ **$125.8** (flat — low fixed)

**Injection Molding / ABS-molded:** tooling tier L = $30,000; nominal_wall = 7.63 mm.
- material = (66.79×1.04/1000) × 3 × 1.03 = **$0.21**
- cooling = 2.0 × 7.63² = 116.4 s, cycle = 121.4 s = 0.0337 hr → machine = **$1.52** ; labor 0.05×35 = **$1.75**
- variable ≈ $3.48 ; fixed = $30,000
- unit@50 = 30000/50 + 3.48 = **$603.5** ; unit@5000 = 30000/5000 + 3.48 = **$9.48**

**Crossover (SLS vs IM):** `q* = (fixed_IM − fixed_SLS)/(var_SLS − var_IM) = (30000 − 17.5)/(125.8 − 3.48) ≈ 245 units.`
→ **Make by SLS below ~245 units; tool injection molding above.** Sensitivity check (gate G4): raise IM tooling $30k→$60k ⇒ q* ≈ **490** (moves right — monotone, explainable). This is the headline demo output.

### 6.5 Error-band roll-up
`est_error_band_pct` = the cycle-time/tooling band of the dominant cost line (machine for AM/CNC; tooling for molding), reported per estimate. Output states: *"Absolute cost is ±X%; the crossover quantity and make-vs-buy direction are robust to it because they depend on the fixed-vs-variable split, driven by your rates."* (strategy §2.)

---

## 7. LEAD-TIME MODEL (`leadtime.py`) — gate G5

Range with **stated components**, scales with quantity, never a fake precise date.

```python
@dataclass
class LeadTime:
    process: str; quantity: int
    low_days: float; high_days: float          # ±30% band on the midpoint
    components: dict[str, float]               # each a labeled day-count

production_days = ceil(qty * cycle_hr / daily_machine_hours)        # MEASURED-driven
tooling_lead_days = {INJECTION_MOLDING: 25, DIE_CASTING: 35}.get(process, 0)   # DEFAULT, once
ship_days = 3                                                       # DEFAULT
mid = queue_days[proc] + tooling_lead_days + production_days + post_days[proc] + ship_days
low, high = mid*0.7, mid*1.3
```

Components dict (every term labeled, gate G5 + G6): `{"queue":…, "tooling_lead":…, "production":…, "post_process":…, "ship":…}`. Output example (ECU SLS @ qty 50): production = ceil(50×5.19/8)=33 d → `queue 3 + tooling 0 + production 33 + post 1 + ship 3 = 40 d (range 28–52)`. IM @ qty 5000: production = ceil(5000×0.0337/8)=22 d → `queue 2 + tooling 25 + production 22 + post 1 + ship 3 = 53 d (37–69)`. Lead time **increases with quantity** (test asserts this).

---

## 8. DECISION LAYER (`decision.py`) — crossover + make-vs-buy (gate G4, the wedge)

```python
def crossover(est_a, est_b):   # est_* are (fixed, variable) per process at a reference qty
    if est_a.variable_cost_usd == est_b.variable_cost_usd: return None
    q = (est_b.fixed_cost_usd - est_a.fixed_cost_usd) / (est_a.variable_cost_usd - est_b.variable_cost_usd)
    return q if q > 1 else None         # crossover only meaningful for q>1
```

`make_vs_buy` framing (honest, no supplier quote — strategy §2(c) is V2): compare the **lowest-fixed feasible process** (prototype/low-volume "make now") against the **lowest-variable feasible process** (production "invest in tooling"). The crossover quantity **is** the make-vs-tooling boundary.

```python
@dataclass
class Decision:
    low_volume_process: str          # min fixed_cost among estimates (make now)
    high_volume_process: str         # min variable_cost among estimates (production)
    crossover_qty: Optional[float]   # q*
    recommendation: dict             # per requested qty -> chosen process + unit cost
    note: str                        # "Make by SLS ≤ ~245 units; tool injection molding above."
```

For each requested quantity, the recommended process = `argmin(unit_cost(qty))` over eligible estimates. The report shows the **direction** and the **crossover**, with the fixed-vs-variable split visible (the decision is robust even when absolute $ is not — strategy §2). V2 hook: a supplier "buy" quote would slot in as a third curve later; not built now.

---

## 9. `DecisionReport` (the assembled object `estimate.py` returns)

```python
@dataclass
class DecisionReport:
    filename: str
    status: str                      # "OK" | "GEOMETRY_INVALID"
    geometry: dict                   # vol, bbox, watertight, faces (summary)
    reason: Optional[str] = None     # set when GEOMETRY_INVALID
    material_class: Optional[str] = None
    quantities: list[int] = field(default_factory=list)
    estimates: list[dict] = field(default_factory=list)   # per (process, qty): CostEstimate + LeadTime, serialized
    decision: Optional[Decision] = None
    assumptions: list[Driver] = field(default_factory=list)   # global DEFAULT/USER rates used
    engine_feasibility: list[dict] = field(default_factory=list)  # all 21 processes: verdict/score, "costed" bool
```

---

## 10. OUTPUT / REPORT FORMAT (`report.py`) — gate G3/G6

`render_text(report)` prints a **decision card**; `report_to_dict(report)` writes a JSON sidecar (`<part>.decision.json`). Target shape of the text card:

```
CadVerify Decision — ECU_Firewall_mount.stl
Geometry: 66.8 cm³ · 160×62×33 mm · watertight ✓ · 1586 faces        [MEASURED]
Material class: polymer [USER, default]

PROCESS OPTIONS (should-cost, USD)
  SLS / PA12                  qty 50: $126.1/unit     qty 5000: $125.8/unit   ±40%
    material  $4.46   [MEASURED  66.79 cm³ × 1.01 g/cm³ × $60/kg × 1.10 scrap]
    machine   $103.8  [DEFAULT   cycle 5.19 hr × $20/hr ; cycle = V/18 + h/22 ; ±40%]
    labor     $17.5   [DEFAULT   0.50 hr × $35/hr]
    fixed/qty $0.35→0.00 [DEFAULT setup 0.50 hr × $35/hr ; no tooling]
    lead time qty 50: 28–52 days [queue 3 + production 33 + post 1 + ship 3]
  Injection Molding / ABS     qty 50: $603.5/unit     qty 5000: $9.48/unit    ±60% (tooling)
    material  $0.21   [MEASURED] · machine $1.52 [DEFAULT cooling∝wall² , wall 7.63 mm]
    tooling   $30,000 [DEFAULT size tier L (150–300 mm), single-cavity, ±60%, OVERRIDABLE]
    lead time qty 5000: 37–69 days [queue 2 + tooling 25 + production 22 + post 1 + ship 3]

DECISION
  Make by SLS for ≤ ~245 units ; tool Injection Molding above.
  Crossover ≈ 245 units  (raise tooling $30k→$60k ⇒ crossover ≈ 490 — moves right).
  @ qty 50   → SLS              ($126.1/unit, 28–52 d)
  @ qty 5000 → Injection Molding ($9.48/unit, 37–69 d)

ASSUMPTIONS (all DEFAULT unless tagged USER; every one overridable)
  labor_rate $35/hr · region US ×1.00 · margin 0% · stock_allowance 1.10 · …
  Absolute cost ±~40–60%; crossover & make-vs-buy direction robust to it (depend on fixed/variable split).

ENGINE FEASIBILITY (DFM, all 21 processes): SLS pass(1.0) · MJF pass(1.0) · CNC_3AXIS pass …  [21 listed; non-costed flagged]
```

Every figure carries a provenance-tagged source; line items sum to the unit total; no naked numbers.

---

## 11. CLI (`cli.py`) — the V0 demo surface

```
python -m src.costing.cli <part.stl> [--qty 50,5000] [--material-class polymer]
        [--region US] [--labor-rate 35] [--set machine_rate.SLS=25] [--json out.json]
```
Behavior: run cwd=`backend` (or `sys.path.insert(0,'backend')`). Runs the canonical engine sequence (§1.1), builds `EstimateOptions` from flags (flags → USER provenance; absent → DEFAULT), calls `estimate_decision`, prints `render_text`, writes `report_to_dict` JSON next to the part (or `--json` path). Exit 0 on OK, exit 0 + printed "GEOMETRY INVALID" card on invalid (not a crash). **Zero network calls** (gate G7); wall-clock target < 10 s on the demo part (engine already runs in well under that on these meshes).

`EstimateOptions`:
```python
@dataclass
class EstimateOptions:
    quantities: list[int] = (50, 5000)
    material_class: str = "polymer"          # DEFAULT, stated
    region: str = "US"
    rate_overrides: dict = field(default_factory=dict)   # {"labor_rate":40, "machine_rate.SLS":25, "tooling.INJECTION_MOLDING":50000}
```

**API (OUT of V0 — leave as a documented stub, unrouted):** a future `POST /validate/cost` would call `estimate_decision(result, mesh, features, options)` after the existing analysis and merge `report_to_dict` into the response. Do not wire it in V0.

---

## 12. ACCEPTANCE CRITERIA (real-use bar) + tests (`test_costing_*.py`)

Build is **done** when all pass on the repo's real parts. Each maps to a strategy G-gate.

| Gate | Assertion (test) | Pass bar |
|---|---|---|
| **G1** robustness | Run all 107 parts; for every part with `volume ≤ 0` or `is_watertight=False`, `estimate_decision().status == "GEOMETRY_INVALID"`, `estimates == []`, no `verdict=="pass"`. MAF adapter + manifold gasket explicitly invalid. | 100% |
| **G2** sane routing | On the ECU Firewall Mount (polymer): no estimate has `process==CNC_TURNING`; no estimate's material family ∈ {titanium, superalloy/Inconel}. Turning appears only when `is_rotational` true (assert on Throttle Body Ring vs bracket). | 0 violations |
| **G3** explainable cost | For ECU mount: every estimate has ≥4 itemized `Driver`s, each with non-empty `source` + `provenance`; `abs(unit_cost − Σ line_items) < 0.01`; perturb one rate (`machine_rate.SLS +10%`) ⇒ unit cost rises (correct direction). | exact |
| **G4** decision/crossover | ECU mount at [50, 5000]: `decision.crossover_qty` is a positive number; recommendation differs across the two qtys (low→AM/CNC, high→IM); raising `tooling.INJECTION_MOLDING` increases `crossover_qty` (monotone). | computed + monotone |
| **G5** lead time | Every estimate has a `LeadTime` with all 5 components labeled and `low<high`; `lead_time(qty=5000) > lead_time(qty=50)` for the same process. | present + monotone |
| **G6** honesty/error band | No `Driver.source` empty; each estimated driver has `error_band_pct`; report `assumptions` non-empty; ≥1 documented validation anchor in the spec/test (see below). | no naked numbers |
| **G7** speed + IP-local | CLI on the demo part completes < 10 s wall-clock; assert no outbound socket during analysis (test monkeypatches `socket.socket` to fail / or asserts none opened). | local, fast |

**G6 validation anchor (document in the test docstring):** a 67 cm³ nylon SLS bracket at low volume from a service bureau is commonly ~$80–180/unit; V0 SLS estimate = $126/unit falls inside that band → stated as the anchor with the resulting band. (This is a *positioning* anchor, not a precision claim — V0 explicitly declines absolute should-cost accuracy, strategy §2.)

**Demo deliverable:** CLI runs cleanly on **both** the ECU Firewall Mount and the Throttle Body Adapter, printing a full decision card with crossover for each.

---

## 13. BUILDER SPLIT — recommendation

**SINGLE builder.** Rationale: the package is ~9 small modules (~600–800 LOC total) with one linear data flow (drivers → routing → cost/leadtime → decision → report) and a thin CLI; the rate table is data, not logic; the engine integration is read-only and already verified. A cost-engine / report split would add an interface boundary with no payoff at this size and risks the report drifting from the model (the Σ(lines)=total invariant is easiest to keep in one head). One builder, build order: `provenance → rates → drivers → routing → cost_model → leadtime → decision → estimate → report → cli → tests`. Each module is independently unit-testable; land tests alongside `cost_model` and `routing` first (they carry the gate logic).

---

## 14. Honesty ledger (what V0 deliberately does **not** claim)

- Cycle-time and tooling defaults are **estimates with stated bands**, not should-cost-grade truths. The buyer overrides them; the model recomputes live. (Strategy §2 — this is the whole point.)
- Absolute dollars are ±40–60%. The **decision** (crossover qty, make-vs-buy direction) is what V0 stands behind, because it depends on the fixed-vs-variable *shape* driven by the buyer's own rates.
- No supplier pricing, no CO₂, no regional libraries, no metal-AM costing — named V1/V2, not faked in V0.
- The legacy `estimated_cost_factor` (dimensionless toy) is left untouched and is **not** surfaced by the decision layer; the layer emits dollars with drivers or nothing.

**Acceptance self-check:** A competent builder can ship this with zero further decisions — module paths, dataclasses, formulas, the full default rate table, the routing predicates with verified thresholds, the report format, the CLI contract, and the G1–G7 tests are all specified. No fabricated or unexplainable number is designed in (G1 refuses broken geometry; every figure is provenance-tagged and sums to its total). The human-validation gate is respected: this is a runnable V0 CLI on real parts, not a production build.
```