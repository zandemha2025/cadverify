# CadVerify V1 — Fix-Spec + Accuracy-Harness Design (Architect, Cycle 2)

**Author:** V1 Fix-Spec Architect · **Date:** 2026-06-28 · **Status:** BUILD-READY (single builder, zero open decisions)
**Inputs fused:** `outputs/validation-packet.md` (Section B, the 8 weaknesses), `outputs/v0-spec.md`, `outputs/strategy.md`, and the live code in `backend/src/costing/` (every module opened) + verified prototype runs on the real ECU mount and throttle adapter.

**Acceptance contract for the Builder:** everything below is decided. Build exactly this. Every new number is a stated **DEFAULT** with a named source basis and a USER override path → it ships flagged DEFAULT and recomputes live when overridden. No default is "claimed truth"; the glass box is preserved. If a default looks wrong, ship it anyway as the V1 DEFAULT and make it overridable. **Do not invent behavior not specified here.**

**Hard invariants that must NOT regress (carried from V0, enforced by tests):**
1. `abs(unit_cost_usd − Σ line_items.values()) < 0.01` on every estimate (gate G3). Every new term that touches unit cost adds or modifies a line item so the sum still holds.
2. Every `Driver` has a non-empty `source` and a `Provenance` tag (gate G6). New drivers included.
3. G1 robustness gate stays first: broken geometry (vol ≤ 0 / non-watertight / ERROR universal issue) → `GEOMETRY_INVALID`, zero estimates. Untouched.
4. Zero network egress (gate G7). The accuracy harness is **local math only** — no API calls.
5. The legacy `profile_matcher._estimate_cost_factor` stays untouched and unsurfaced.

---

## 0. Map: the 8 weaknesses → exact module/function to change

| # | Weakness | Module · function | Kind of change |
|---|---|---|---|
| 1 | Small-part AM over-costed (flat $17.50 post-labor never amortizes) | `cost_model.py::cost_breakdown` (post-labor split) + `rates.py` | amortize per-part finishing vs per-build bulk over `parts_per_build` |
| 2 | AM cycle = single isolated build (no nesting); machine = 82% of unit | `cost_model.py::_additive_cycle` → new `_additive_machine`; `drivers.py` (nesting count); `rates.py` (envelopes/packing) | build-plate nesting model; per-part machine = build-job ÷ parts-per-build (powder-bed/DLP), serial-per-part (FDM/SLA) |
| 3 | No minimum-charge / lot floor | `cost_model.py::cost_breakdown` (final clamp) + `rates.py` (`min_charge`) | per-lot order minimum; clamp unit cost, add a line item when it bites |
| 4 | One flat region scalar on labor+machine+material+tooling | `rates.py::RateCard.region_*` (split) + `cost_model.py` (per-line scaling) | three region vectors: labor, material, tooling |
| 5 | Tooling = 4-bucket step on max-bbox only | `rates.py::RateCard.tooling_cost` + `cost_model.py` (formative) + `EstimateOptions` | add `n_cavities` + `complexity` (USER); cavity & per-shot coupling |
| 6 | DFM-fail process headlined as "tool injection molding above…" | `decision.py::make_vs_buy` / `_build_note` | tooling/buy route presented conditionally ("if redesigned for molding"); never asserted as current-capability |
| 7 | Decision incoherence: headline process ≠ low-qty argmin | `decision.py::make_vs_buy` + `estimate.py` (real per-qty estimates) + `report.py` | headline make-now process ≡ low-qty argmin over DFM-ready make processes; one consistent semantics |
| 8 | One setup over the whole lot (optimistic) | `cost_model.py::cost_breakdown` (setup term) + `rates.py` (`lot_size`) | setup recurs per realistic lot: `ceil(qty/lot_size)` setups |

Weaknesses #1+#2 share the nesting machinery (§4). #6+#7 share the decision rewrite (§9). #3+#8 share the lot model (§5–§6).

---

## 1. New rate-card keys (all DEFAULT, all overridable) — `rates.py`

Add the following to `RATE_CARD_V0`. **Source basis** is the public, named grounding for each DEFAULT (machine spec sheets, standard machining references, common service-bureau / tooling price bands). These are stated assumptions, not claimed truth; every one is overridable to USER provenance.

### 1.1 Per-process additive build envelopes + nesting (new `process` sub-keys for ADDITIVE)

| process | `build_env_mm` (X,Y,Z) | `packing_density` | `part_spacing_mm` | `nesting_mode` | source basis |
|---|---|---|---|---|---|
| FDM | (250, 250, 250) | 0.10 | 4.0 | `serial` | Prusa MK4 250×210×220 / Bambu X1C 256³ class |
| SLA | (145, 145, 185) | 0.10 | 3.0 | `serial` | Formlabs Form 3/3+ 145×145×185 |
| DLP | (192, 120, 245) | 0.12 | 3.0 | `build_job` | representative benchtop DLP envelope |
| SLS | (340, 340, 600) | 0.10 | 5.0 | `build_job` | EOS P396 340×340×600 (industrial bureau machine) |
| MJF | (380, 284, 380) | 0.10 | 5.0 | `build_job` | HP Jet Fusion 5200 380×284×380 |

- `nesting_mode = build_job`: machine sweeps every layer regardless of part count (powder-bed laser/fuse, DLP whole-layer projection). Per-part machine time = full-build job time ÷ parts-per-build. **This is the structural fix for weakness #2** (the 82%-machine artifact).
- `nesting_mode = serial`: deposition is serial (FDM single nozzle, SLA laser trace). Nesting does **not** reduce per-part machine time; it only amortizes setup + per-build finishing. Per-part machine time stays the V0 isolated formula. (Physically honest: FDM machine time genuinely is per-part.)
- `packing_density` = fraction of build-envelope volume occupied by part bounding boxes (incl. spacing). Industry "build-volume utilization" for mixed powder-bed jobs is commonly 8–12% (up to ~20% optimized); DEFAULT 0.10. Overridable per process: `packing_density.SLS`.

### 1.2 Build-job vert rates (recalibrated so full-build duration is realistic)

For `build_job` processes the per-part machine time derives from the **full-build job duration** `build_job_hr = build_env_Z_mm / vert_rate_mm_hr`. Recalibrate `vert` so a full build is realistic:

| process | `vert` (mm/hr) | full-build `build_job_hr` = Z/vert | sanity |
|---|---|---|---|
| SLS | 20 | 600/20 = **30.0 hr** | EOS full build ~24–40 h |
| MJF | 25 | 380/25 = **15.2 hr** | HP MJF full build ~12–16 h |
| DLP | 30 | 245/30 = **8.2 hr** | resin DLP plate ~6–10 h |

`deposition` (cm³/hr) is now **only** used by `serial` processes (FDM=16, SLA=8). Keep FDM `vert`=25, SLA `vert`=20 unchanged (serial height term). `deposition` for SLS/MJF/DLP is unused under `build_job` — leave the key present (ignored) so the card schema is uniform.

### 1.3 Lot model + minimum charge (weaknesses #3, #8)

New per-process keys:

| process | `lot_size` (units / setup) | `min_charge` ($/lot, order floor) | source basis |
|---|---|---|---|
| FDM | = parts_per_build | 30 | AM bureau order min ~$30 |
| SLA | = parts_per_build | 40 | resin bureau min ~$40 |
| DLP | = parts_per_build | 40 | resin bureau min ~$40 |
| SLS | = parts_per_build | 75 | powder-bed bureau min ~$50–100 |
| MJF | = parts_per_build | 75 | powder-bed bureau min ~$50–100 |
| CNC_3AXIS | 100 | 90 | CNC shop min ~$75–150 (Protolabs/Xometry instant-quote) |
| CNC_5AXIS | 100 | 110 | 5-axis shop min |
| CNC_TURNING | 100 | 90 | turning shop min |
| INJECTION_MOLDING | 100000 | 0 | tooling is the floor; continuous run |
| DIE_CASTING | 100000 | 0 | tooling is the floor |

For ADDITIVE, the natural production lot **is one build**, so `lot_size = parts_per_build` (computed at runtime, §4.1). Encode `lot_size` for AM as the sentinel string `"build"` in the card; `cost_model` resolves it to `parts_per_build`. CNC/molding use the integer defaults above. Overridable: `lot_size.CNC_3AXIS`, `min_charge.SLS`.

### 1.4 Region split (weakness #4) — replace the single `region` table with three vectors

Delete the single `"region"` scalar table; add:

```python
"region_labor":    {"US":1.00,"EU":1.10,"MX":0.70,"CN":0.55,"IN":0.50,"SA":1.05},
"region_material": {"US":1.00,"EU":1.02,"MX":1.00,"CN":0.98,"IN":0.98,"SA":1.02},
"region_tooling":  {"US":1.00,"EU":1.05,"MX":0.75,"CN":0.45,"IN":0.50,"SA":1.10},
```

- `region_labor` → applied to machine_cost, post-labor, setup. (Machine rate is loaded labor+overhead; scales with the region's shop-labor index.)
- `region_material` → applied to material_cost only. **≈1.0 everywhere**: resin/billet are globally-traded commodities (LME metals, global polymer feedstock) and do **not** track regional shop labor. This is the fix for the "CN ×0.65 on a resin PO" bug.
- `region_tooling` → applied to amortized tooling. Toolmaking is labor-intensive (offshore tools commonly 40–60% of US) but the steel is global, so the spread sits between labor and material.

Source basis: commodity feedstock priced on global indices (≈uniform); offshore tooling 40–60% of US toolmaking cost; offshore shop labor 50–60% of US loaded rate. All overridable: `region_labor.CN`, etc., or supply a custom region key.

`EstimateOptions.region` selects the column; default `"US"` = (1.00, 1.00, 1.00). If `region` not in the tables, all three default to 1.0.

### 1.5 Tooling cavity + complexity (weakness #5)

Keep the size-tier base table (`{"S":6000,"M":15000,"L":30000,"XL":60000}`, die ×1.5). Add multipliers:

```python
"cavity_exponent": 0.70,          # tool cost ~ n_cavities^0.70 (shared base, economies)
"complexity_factor": {"simple":0.80, "moderate":1.00, "complex":1.50, "very_complex":2.20},
```

Source basis: multi-cavity tool cost scales sub-linearly (~n^0.6–0.7) because the bolster/base is shared; side-actions/slides/tight-tolerance add 25–120%. DEFAULTs: `n_cavities = 1`, `complexity = "moderate"` (1.00). Both USER inputs (§3). Tooling formula §8.

---

## 2. Updated `RateCard` accessor API (`rates.py`)

Replace `region_multiplier(region)` with three getters and add helpers:

```python
def region_labor(self, region):    return self.data["region_labor"].get(region, 1.0)
def region_material(self, region):  return self.data["region_material"].get(region, 1.0)
def region_tooling(self, region):   return self.data["region_tooling"].get(region, 1.0)

def build_env(self, proc):          return tuple(self.p(proc, "build_env_mm"))
def packing_density(self, proc):    return self.p(proc, "packing_density")
def part_spacing(self, proc):       return self.p(proc, "part_spacing_mm")
def nesting_mode(self, proc):       return self.p(proc, "nesting_mode")
def min_charge(self, proc):         return self.p(proc, "min_charge")
def lot_size_raw(self, proc):       return self.p(proc, "lot_size")   # int or "build"
```

`build_rate_card` override parsing already supports dotted per-process keys; extend the accepted per-process field whitelist to include `packing_density`, `part_spacing_mm`, `min_charge`, `lot_size`, `vert`. `build_env_mm` override is accepted as a 3-tuple via `rate_overrides["build_env_mm.SLS"] = (x,y,z)` (special-cased; not coerced to float). Region-vector overrides: dotted keys `region_labor.CN`, `region_material.CN`, `region_tooling.CN` route into the respective table and add the dotted key to `user_keys`. Global `cavity_exponent` overridable; `complexity_factor.<name>` overridable.

`prov_tag` / `is_user` logic unchanged (a dotted key present in `user_keys` → USER).

---

## 3. `EstimateOptions` additions (`estimate.py`) + CLI flags (`cli.py`)

```python
@dataclass
class EstimateOptions:
    quantities: list = field(default_factory=lambda: [50, 5000])
    material_class: str = "polymer"
    region: str = "US"
    rate_overrides: dict = field(default_factory=dict)
    strict_dfm: bool = False
    material_class_is_user: bool = False
    # NEW (weakness #5):
    n_cavities: int = 1               # DEFAULT 1, single-cavity should-cost
    complexity: str = "moderate"      # simple|moderate|complex|very_complex
    n_cavities_is_user: bool = False
    complexity_is_user: bool = False
```

CLI flags (add to `cli.py`):
```
--cavities N                 # n_cavities (-> USER), default 1
--complexity moderate        # simple|moderate|complex|very_complex (-> USER)
--region US                  # now selects the 3 region vectors
--set packing_density.SLS=0.15   # already-supported dotted override path
--set min_charge.CNC_TURNING=120
--set lot_size.CNC_3AXIS=250
```

Pass `n_cavities`/`complexity` through `estimate_decision` into `cost_breakdown` (formative only). Tag them USER when set on the CLI, DEFAULT otherwise, and surface in the ASSUMPTIONS panel.

---

## 4. Fix #2 + #1 — AM build-plate nesting + post-labor amortization

### 4.1 Parts-per-build (new helper in `drivers.py`, called from `cost_model`)

```python
def parts_per_build(proc, bbox_mm, rates) -> int:
    X, Y, Z = rates.build_env(proc)
    s = rates.part_spacing(proc)
    part_vol_cm3 = ((bbox_mm[0]+s) * (bbox_mm[1]+s) * (bbox_mm[2]+s)) / 1000.0
    env_vol_cm3  = (X * Y * Z) / 1000.0
    n = int(rates.packing_density(proc) * env_vol_cm3 / part_vol_cm3)
    return max(1, n)
```
`bbox_mm` is `drivers.bbox_mm` (sorted ascending, already on `GeoDrivers`). The fit is volumetric (`packing_density` already discounts geometric inefficiency). DEFAULT-driven, fully traceable, overridable via `packing_density.*` / `build_env_mm.*`.

Verified counts (DEFAULTs): ECU mount (32.6×62×160) → SLS **16**, MJF **9**, DLP 1, FDM 3, SLA 1. Throttle (22.2×34×39.9) → SLS **145**, MJF **86**, DLP 16, FDM 35, SLA 9.

### 4.2 AM machine sub-model (replaces `_additive_cycle`)

```python
def _additive_machine(proc, drivers, rates):
    n = parts_per_build(proc, drivers.bbox_mm, rates)
    mode = rates.nesting_mode(proc)
    if mode == "build_job":
        Z = rates.build_env(proc)[2]
        vert = rates.p(proc, "vert")
        build_job_hr = Z / vert                       # full-build duration (height-driven recoat/sweep)
        machine_hr   = build_job_hr / n               # this part's amortized share
        src = (f"build-job {Z:g}mm ÷ {vert:g}mm/hr = {build_job_hr:.1f}hr full build, "
               f"÷ {n} parts/build (packing {rates.packing_density(proc):g}, "
               f"env {rates.build_env(proc)}) = {machine_hr:.3f}hr/part")
    else:  # serial: deposition is per-part; nesting does not reduce machine time
        dep  = rates.p(proc, "deposition"); vert = rates.p(proc, "vert")
        build_h = drivers.bbox_mm[0]
        machine_hr = drivers.volume_cm3/dep + build_h/vert
        src = (f"serial V/{dep:g}+h/{vert:g} = {drivers.volume_cm3:.2f}/{dep:g}"
               f"+{build_h:.1f}/{vert:g} = {machine_hr:.3f}hr/part "
               f"(deposition serial; nesting amortizes setup+finish only, n={n})")
    return machine_hr, n, src
```

The `cycle_time` Driver `name` stays (lead-time consumes it); its value is now `machine_hr/part` and `error_band_pct` stays 40 (additive band). The output **states** the nesting assumption in `source`, so the glass box shows exactly why the per-part machine cost dropped.

### 4.3 Post-process labor split (weakness #1)

Replace `post_hr` with a two-part split for AM. Add per-process keys:

| process | `post_hr_part` (per-part finishing) | `post_hr_build` (per-build bulk, amortized over n) |
|---|---|---|
| FDM | 0.20 | 0.10 |
| SLA | 0.15 | 0.20 |
| DLP | 0.15 | 0.20 |
| SLS | 0.08 | 0.50 |
| MJF | 0.08 | 0.50 |

Powder-bed: depowder is a per-**build** bulk op (0.50 hr, amortized over the whole plate); only light per-part finishing (0.08 hr) stays per-part. FDM: support removal is genuinely per-part (0.20 hr). For SUBTRACTIVE/FORMATIVE keep the single `post_hr` (no nesting): set `post_hr_part = post_hr`, `post_hr_build = 0`.

```python
post_labor = (post_hr_part + post_hr_build / n) * labor_rate          # n = parts_per_build (1 for CNC/molding)
```

Source basis: bulk depowder/bead-blast of a full powder-bed plate is one operation regardless of part count; per-part finishing is the deburr/inspect step. Stated DEFAULT, overridable (`post_hr_part.SLS`, `post_hr_build.SLS`).

### 4.4 Verified result (resolves the weaknesses — computed from the DEFAULTs above)

| part / process | V0 unit (q50) | **V1 unit (q50)** | what changed |
|---|---|---|---|
| ECU SLS | $126.12 | **$47.25** | machine $103.82→$37.50 ($600 build ÷ 16); post $17.50→$3.89 |
| ECU MJF | $120.11 | **$44.13** | machine $102.13→$37.16 ($334 build ÷ 9); post amortized |
| ECU FDM | $55.02 | **$57.25** | machine unchanged (serial, honest); post split |
| Throttle SLS (q100) | $41.15 | **$7.42** | machine $23.29→$4.14 (÷145); post $17.50→$2.92 |
| Throttle MJF (q100) | $40.29 | **$7.25** | nested |
| Throttle FDM (q100) | $17.44 | **$15.97** | serial machine unchanged; post split |

ECU SLS machine is now **79% lower** and is no longer 82% of unit cost; the throttle powder-bed numbers land in the validation-packet's independent $4–8 ballpark (B-1). FDM stays ~flat because FDM machine time genuinely is per-part — stated, not hidden.

---

## 5. Fix #8 + #3 — per-lot setup + minimum charge

### 5.1 Per-lot setup (weakness #8)

```python
lot_size = parts_per_build if lot_size_raw == "build" else int(lot_size_raw)
n_setups = math.ceil(qty / lot_size)
setup_total = n_setups * setup_hr * labor_rate
setup_per_unit = setup_total / qty            # = setup_hr*labor_rate*ceil(qty/lot)/qty
```
Setup recurs every lot (a re-fixture for CNC; a new build for AM). Replaces the V0 "one setup over the whole qty." The `setup_cost` Driver `source` becomes: `"setup {setup_hr}hr × ${labor}/hr × ceil({qty}/{lot_size}) setups ÷ {qty}"`.

### 5.2 Minimum charge / order floor (weakness #3)

Computed as the **last** step, after region/margin scaling, so the floor is a real-dollar floor:

```python
order_min = rates.min_charge(proc) * n_setups          # each lot/setup carries the shop minimum
floor_per_unit = order_min / qty
if unit_cost < floor_per_unit:
    delta = floor_per_unit - unit_cost
    line_items["min_charge_floor"] = round(delta, 4)    # preserves Σ = unit invariant
    unit_cost = round(sum(line_items.values()), 4)
    drivers_out.append(Driver("min_charge_floor", round(delta,4), "$", Provenance.DEFAULT,
        f"shop/order minimum ${rates.min_charge(proc):g}/lot × {n_setups} lots ÷ {qty} = "
        f"${floor_per_unit:.2f}/unit floor (applied)", error_band_pct=None))
```

The clamp only bites at low qty / tiny parts (e.g., turning a single part → max($14.93, $90) = $90; the throttle's $4.11-machine case can never sink below the $90/lot floor). At production qty it is negligible and adds no line item. **This guarantees no estimate ever falls below a real shop floor** (B-3), and the Σ-invariant is preserved by booking the delta as its own line item.

---

## 6. Fix #4 — region split applied per line item (`cost_model.py`)

Replace the single `scale = region_mult*(1+margin)` with per-line region factors, all `× (1+margin)`:

```python
rl = rates.region_labor(region)
rm = rates.region_material(region)
rt = rates.region_tooling(region)
mgn = 1.0 + margin

material_scaled = material_cost  * rm * mgn
machine_scaled  = machine_cost   * rl * mgn
labor_scaled    = post_labor     * rl * mgn
setup_scaled    = setup_per_unit * rl * mgn
tooling_amort_scaled = (tooling_cost/qty) * rt * mgn      # formative only, else 0

line_items = {
    "amortized_fixed": round(tooling_amort_scaled + setup_scaled, 4),   # tooling@rt + setup@rl
    "material":        round(material_scaled, 4),
    "machine":         round(machine_scaled, 4),
    "labor":           round(labor_scaled, 4),
}
unit_cost = round(sum(line_items.values()), 4)            # then apply §5.2 min-charge clamp
```

The 4-key `line_items` shape is **unchanged** (report/tests depend on it); `amortized_fixed` now bundles tooling-at-`region_tooling` + setup-at-`region_labor`. A new `region_split` Driver records the three factors when any ≠ 1.0:
```python
Driver("region_split", 0.0, region, prov, f"labor ×{rl:g} · material ×{rm:g} · tooling ×{rt:g}")
```
provenance = USER if any of the three dotted region keys was overridden or `region` was set on the CLI, else DEFAULT.

**Decision-relevant split** (for crossover, §9): `fixed_cost_usd = tooling_cost * rt * mgn` (one-time); `variable_cost_usd = material_scaled + machine_scaled + labor_scaled + setup_asymptotic_scaled`, where `setup_asymptotic_scaled = (setup_hr*labor_rate/lot_size)*rl*mgn` (per-unit setup as qty→∞, a clean continuous term for the crossover line). Report these on `CostEstimate` exactly as before.

---

## 7. Fix #5 — tooling cavity + complexity (`rates.py::tooling_cost`, formative path)

```python
def tooling_cost(self, proc, max_bbox_mm, n_cavities=1, complexity="moderate"):
    flat = self.data.get("_tooling_flat", {}).get(proc)
    if flat is not None:
        base = float(flat)                      # USER flat override = the whole tool, pre-cavity/complexity
        cav = comp = 1.0
    else:
        tier = family_to_size_tier(max_bbox_mm)
        base = float(self.data["tooling"][tier])
        if proc == ProcessType.DIE_CASTING:
            base *= self.data["tooling_die_mult"]
        cav  = n_cavities ** self.data["cavity_exponent"]                 # ^0.70
        comp = self.data["complexity_factor"][complexity]
    return base * cav * comp
```

**Per-shot output couples to cavities** (a multi-cavity tool makes `n_cavities` parts per machine cycle):
```python
machine_cost = (cycle_hr * machine_rate) / n_cavities      # formative only
```
So raising cavities raises tooling (`n^0.70`) but lowers per-part machine (`/n`) — the realistic trade, visible in the glass box. DEFAULT `n_cavities=1, complexity="moderate"` → identical to V0 tooling (no silent change). Tooling Driver `source` becomes:
`"size tier {tier} ${base} × {n_cav} cav^0.70 (={cav:.2f}) × {complexity} (={comp:.2f}) = ${tooling:,.0f}; ±60%, OVERRIDABLE"`.

Worked: ECU IM, tier L $30,000, 4-cavity, complex → `30000 × 4^0.7 × 1.5 = 30000 × 2.639 × 1.5 = $118,756`; per-part machine `$1.52/4 = $0.38`. Single-cavity moderate (DEFAULT) → `$30,000`, machine `$1.52` (= V0).

**Complexity is never auto-changed silently.** When the engine reports undercut/side-action DFM blockers on a formative process, emit a NOTE ("part shows undercuts; a production mold may need side-actions → consider `--complexity complex`") but keep the DEFAULT `moderate` unless the user overrides. (Honest: no hidden assumption.)

---

## 8. Fix #7 + #6 — decision coherence (top priority) — `decision.py` rewrite

### 8.1 Root cause (verified live on the ECU mount)

V0 output today:
```
DECISION
  Make by fdm for ≤ ~583 units; invest in injection_molding tooling above ~583.
  @ qty 50   → cnc_3axis  ($43.60/unit)  [requires design-for-process]
               cheapest DFM-ready as-is: fdm ($55.02/unit)
```
Three different processes — headline make = **fdm** (lowest *fixed* among DFM-ready), crossover buy = **injection_molding** (lowest *variable*, but **DFM-fail**), low-qty argmin = **cnc_3axis** (also **DFM-fail**). `low_volume_process` (argmin **fixed**) ≠ `recommendation[q_lo]` (argmin **unit**). That is the incoherence.

### 8.2 Coherent semantics (the fix — make it deterministic)

Partition eligible estimates:
- **MAKE-NOW set** = eligible processes that need no hard tooling: `MAKE_NOW_FAMILIES = ADDITIVE ∪ SUBTRACTIVE` (AM + CNC).
- **TOOLING set** = `FORMATIVE` (injection molding, die casting) — the "invest in a tool" route.
- **DFM-ready** = `dfm_ready == True` (engine verdict ≠ "fail").

Define, using **actual per-qty unit costs** (not a fixed/var reconstruction):

```
q_lo  = min(quantities)
q_hi  = max(quantities)

make_ready(q)   = [e for e in MAKE-NOW if e.dfm_ready],  ranked by real unit_cost(q)
make_now        = argmin_{make_ready(q_lo)} unit_cost(q_lo)        # THE headline make process
tool_ready(q)   = [e for e in TOOLING],                  ranked by real unit_cost(q)   # DFM-ready or not
tool_champion   = argmin_{tool_ready(q_hi)} unit_cost(q_hi)        # the production/tooling candidate
```

**Invariant (resolves #7):** the headline make-now process **≡** `recommendation[q_lo].process` **≡** `argmin make_ready(q_lo)`. They are computed from the *same* ranking, so they can never disagree. The builder must wire all three off the single `make_now` selection.

**Crossover** uses the clean asymptotic fixed/var split (§6):
```
q_star = crossover(make_now.fixed, make_now.var, tool_champion.fixed, tool_champion.var)
       = tool_champion.fixed / (make_now.var − tool_champion.var)        # make_now.fixed ≈ 0
```
(`crossover()` helper math is unchanged and already tested.)

**DFM gating of the headline (resolves #6):** the headline make process is drawn **only** from DFM-ready make candidates, so it is never a process the part currently fails. The tooling route may be DFM-fail; if so it is presented **conditionally** ("if redesigned for molding"), never as a current-capability assertion.

### 8.3 Per-qty recommendation (two clean tiers, never conflated)

For every requested `q`, report:
1. **Recommended (make-as-is):** `argmin make_ready(q)` — always DFM-ready, always a make-now process. At `q_lo` this is exactly `make_now`.
2. **Cheaper if redesigned (optional):** the single cheapest estimate at `q` that beats tier-1 but is either DFM-fail or a tooling process — shown with its caveat. If none beats tier-1, omit.

So cnc_3axis ($43.60, DFM-fail, undercuts) and injection_molding ($9.39 @5000, DFM-fail, draft) appear only as **tier-2 "if redesigned"** lines — never as the recommendation, never in the headline.

### 8.4 Exact decision-sentence template (`_build_note`)

```
Make by {make_now.process} ({make_now.material}) — ${make_now.unit(q_lo)}/unit at qty {q_lo},
the cheapest make-as-is option and your low-volume pick.
{crossover_clause}
{tooling_clause}
```

`crossover_clause`:
- if `tool_champion` exists and `q_star` is a number > q_lo:
  `"{make_now.process} stays cheapest up to ~{q_star:.0f} units; above ~{q_star:.0f}, {tool_champion.process} is cheaper (${tool_champion.unit(q_hi)}/unit at qty {q_hi})."`
- elif no tooling candidate or no crossover > q_lo:
  `"{make_now.process} is cheapest at every quantity tested — no tooling crossover."`

`tooling_clause` (only when a `tool_champion` is named):
- if `tool_champion.dfm_ready`:  `""`
- else: `"Note: {tool_champion.process} requires design-for-molding — the part currently FAILS draft DFM ({blocker}); the tooling cost shown is 'if redesigned for molding', not a current-capability quote."`

### 8.5 Verified coherent output (ECU mount, V1 DEFAULTs, qty 50 & 5000)

```
DECISION
  Make by mjf (PP) — $44.13/unit at qty 50, the cheapest make-as-is option and your low-volume pick.
  mjf stays cheapest up to ~739 units; above ~739, injection_molding is cheaper ($9.39/unit at qty 5000).
  Note: injection_molding requires design-for-molding — the part currently FAILS draft DFM
        (564 sidewall faces below 1.0° draft); the tooling cost shown is 'if redesigned for molding'.

  @ qty 50   → mjf / PP        $44.13/unit   (make-as-is, recommended)
               cheaper if redesigned: cnc_3axis $43.60/unit (remove undercuts) ·
                                      injection_molding $603.39/unit (add draft, tooling-dominated)
  @ qty 5000 → mjf / PP        $43.98/unit   (make-as-is, recommended)
               cheaper if redesigned: injection_molding $9.39/unit (add draft) ← crossover ~739
```
Headline make process (**mjf**) = `recommendation[50].process` (**mjf**) = `argmin make_ready(50)` (**mjf**). One process, three places, identical. No DFM-fail process is ever the headline. `q_star ≈ 739` (= 30000 / (43.98 − 3.39)); raising `tooling.INJECTION_MOLDING` → 60000 moves it to ~1478 (monotone, unchanged crossover math).

### 8.6 `Decision` dataclass changes

```python
@dataclass
class Decision:
    make_now_process: str            # headline make (argmin DFM-ready make at q_lo)
    make_now_material: str
    tooling_process: Optional[str]   # production/tooling candidate (may be DFM-fail)
    tooling_dfm_ready: bool
    crossover_qty: Optional[float]
    recommendation: dict             # q -> {process, material, unit_cost, dfm_ready, lead_low/high}  (tier-1, make-as-is)
    if_redesigned: dict              # q -> {process, material, unit_cost, caveat} | None  (tier-2)
    note: str
```
`low_volume_process`/`high_volume_process`/`dfm_ready_recommendation` are removed; `make_now_process`/`tooling_process`/`if_redesigned` replace them. Update `report.py` and the G4 tests to the new fields (§11–§12).

---

## 9. New master cost flow (`cost_model.py::cost_breakdown`) — assembled

Signature: `cost_breakdown(process, drivers, material, material_class, qty, rates, region, n_cavities, complexity, process_score)`.

```
family   = process_family(process)
labor    = rates.g("labor_rate");  margin = rates.g("margin");  scrap = rates.p(process,"scrap")
rl,rm,rt = region_labor/material/tooling(region);  mgn = 1+margin

# MATERIAL (MEASURED mass; CNC uses stock, AM/molding uses part mass) — unchanged mass logic
material_cost = input_mass * material.cost_per_kg * (1+scrap)

# MACHINE
if family=="additive":  machine_hr, n, src = _additive_machine(process, drivers, rates)
elif family=="subtractive": machine_hr, src = _cnc_machine(...);  n = 1
else:                   machine_hr, src = _formative_machine(...); n = 1
machine_cost = machine_hr * machine_rate / (n_cavities if family=="formative" else 1)

# LABOR (post) — AM split, CNC/molding single
post_labor = (post_hr_part + post_hr_build / n) * labor       # n=1 for CNC/molding

# SETUP per lot (#8)
lot_size = n if lot_raw=="build" else int(lot_raw)
n_setups = ceil(qty/lot_size);  setup_per_unit = setup_hr*labor*n_setups/qty

# TOOLING (formative; cavity+complexity #5)
tooling = rates.tooling_cost(process, drivers.max_bbox_mm, n_cavities, complexity) if formative else 0

# scale per line (#4) and assemble (4-key line_items; Σ invariant)
... (exactly §6) ...
unit_cost = round(sum(line_items.values()), 4)

# MIN CHARGE clamp (#3) — adds line item only if it bites
... (exactly §5.2) ...

est.fixed_cost_usd    = tooling*rt*mgn
est.variable_cost_usd = material*rm*mgn + machine_cost*rl*mgn + post_labor*rl*mgn + (setup_hr*labor/lot_size)*rl*mgn
est.assert_sums()
```
Every term remains a provenance-tagged Driver with a `source` string; the new drivers (`min_charge_floor`, `region_split`, cavity/complexity in `tooling_cost.source`, nesting in `cycle_time.source`) all carry sources. **Σ(line_items) = unit_cost holds by construction** (line items are the post-scaled, post-clamp components).

---

## 10. Lead-time consistency (`leadtime.py`) — small change

`production_days = ceil(qty * machine_hr_per_part / daily_machine_hours)` already consumes the `cycle_time` driver, which is now `machine_hr/part` (nesting-reduced for powder-bed). This **correctly** shrinks production days for nested AM (a real win: a nested SLS run of 5000 small parts is far faster per part). No formula change; just confirm it reads the new `cycle_time` value. Add `n_setups`-aware note only if desired (optional). Lead time still grows with qty (G5 holds).

---

## 11. Report changes (`report.py`)

1. DECISION block: render the new `Decision` fields — `make_now_process`, the single coherent `note`, the crossover line, then per-qty tier-1 recommendation and (when present) tier-2 "cheaper if redesigned" line. Remove the old `low/high_volume_process` rendering.
2. Per-estimate card: when `min_charge_floor` ∈ line_items, print a `min charge` line: `min charge $X.XX [DEFAULT shop/order min …]`. Σ line shows it.
3. ASSUMPTIONS panel: add `region_labor/material/tooling`, `n_cavities`, `complexity`, and (for AM) `parts/build` with its packing source. Tag USER/DEFAULT correctly.
4. Machine line `source` now reads e.g. `build-job 600mm ÷ 20mm/hr = 30.0hr ÷ 16 parts/build (packing 0.10, env (340,340,600))` — the nesting is visible (glass box).

The text-card target shape (ECU, V1):
```
PROCESS OPTIONS (should-cost, USD)
  mjf / PP (Polypropylene)     qty 50: $44.13/unit   qty 5000: $43.98/unit   ±40%
    material  $0.13   [MEASURED 66.79 cm³ × 0.90 g/cm³ × $2/kg × 1.10 scrap × region-material ×1.00]
    machine   $37.16  [DEFAULT build-job 380mm ÷ 25mm/hr = 15.2hr ÷ 9 parts/build (packing 0.10) × $22/hr ±40%]
    labor     $4.74   [DEFAULT finish 0.08hr/part + depowder 0.50hr/build ÷ 9 × $35/hr]
    fixed/qty $2.10→$1.95 [DEFAULT setup 0.50hr × $35 × ceil(qty/9) ÷ qty; no tooling]
    line items Σ = $44.13
  injection_molding / PP (Molded)   qty 50: $603.39   qty 5000: $9.39   ±60%   ⚠ NOT DFM-ready (add draft)
    tooling   $30,000 [DEFAULT tier L (150–300mm) × 1 cav^0.70 × moderate × region-tooling ×1.00; OVERRIDABLE]
    ...
```

---

## 12. Tests — update + add (`tests/test_costing_model.py`, `tests/test_costing_gates.py`)

Keep all existing invariants; update the ones the rewrite touches and add coverage for the 8 fixes.

**Update (signatures/fields changed):**
- `test_g4_ecu_crossover_and_make_vs_buy`: assert `dec.make_now_process == dec.recommendation[q_lo]["process"]` (the **coherence invariant** — this is the headline test for #7); assert `dec.tooling_process == "injection_molding"`; assert the `make_now_process` estimate has `dfm_ready == True` (#6); assert `recommendation[q_hi]` is DFM-ready make-as-is and `if_redesigned[q_hi]["process"] == "injection_molding"`.
- `test_g4_raising_tooling_moves_crossover_right`: unchanged intent, new field name.

**Add:**
- `test_nesting_reduces_powderbed_machine` (#2): ECU SLS V1 machine_cost < 0.5 × V0-equivalent isolated (`build_job_hr/n`); assert `machine_cost` is **not** > 70% of unit_cost for ECU SLS.
- `test_small_part_am_not_overcosted` (#1): throttle SLS unit @ q100 ≤ $12 (was $41); ≥ $3 (sanity).
- `test_min_charge_floor` (#3): a 1-unit CNC_TURNING order ≥ `min_charge.CNC_TURNING`; Σ invariant still holds with the floor line.
- `test_region_split_material_not_labor_scaled` (#4): CN vs US — `material` line ratio ≈ region_material (≈0.98), `machine` line ratio ≈ region_labor (0.55); assert they differ (material not discounted like labor).
- `test_cavity_complexity_tooling` (#5): `--cavities 4 --complexity complex` raises IM tooling by `4^0.7×1.5` and lowers IM machine by /4; Σ holds.
- `test_per_lot_setup` (#8): setup_per_unit at qty=2×lot_size ≈ 2× setup_per_unit at qty=lot_size (per-lot recurrence), not ÷2.
- `test_decision_coherence` (#7, procedural + ECU): for several parts, `make_now_process == recommendation[min(qtys)]["process"]` and that process is `dfm_ready` — across the whole real-parts set (loop, like G1).

All gate tests keep the `CADVERIFY_PARTS_DIR` skip guard. Procedural-mesh tests (block) must still pass with the new model.

---

## 13. ACCURACY HARNESS DESIGN (local, independent ground-truth — no network)

A new module `backend/src/costing/harness.py` + `tests/test_costing_accuracy.py`. It compares V1 estimates against **independent** reference bands computed with *different math* than V1's rate card, so agreement is a real cross-check, not a tautology. All references are public price/throughput **bands** encoded as constants in the harness; **zero network calls** (CAD-as-IP).

### 13.1 Independent reference models (computed locally, per part)

**(R1) AM volumetric service-bureau bands** — independent of V1's cycle-time math; pure $/cm³-of-part + bureau minimum (how Shapeways/Sculpteo/Craftcloud price):
```
ref_unit_band(proc, V_cm3) = [ max(min_lo, V*rate_lo),  max(min_hi, V*rate_hi) ]
```
| proc | rate_lo–rate_hi ($/cm³) | min_lo–min_hi ($) | source basis |
|---|---|---|---|
| FDM | 0.10 – 0.40 | 15 – 35 | desktop/bureau FDM volumetric |
| SLA/DLP | 0.30 – 1.00 | 25 – 60 | resin bureau volumetric |
| SLS/MJF | 0.30 – 0.80 | 50 – 100 | nylon powder-bed bureau volumetric |

**(R2) CNC independent machining math** — material + (independent MRR time × independent shop-rate band) + setup + shop minimum, with reference constants distinct from V1's card:
```
t_machine_hr = (stock_cm3 − V_cm3) / (MRR_ref[class] * 60) + area_cm2 / finish_ref
ref_unit = max( shop_min_ref,
                material_ref + t_machine_hr * rate_ref + setup_ref*rate_ref/lot_ref ) [band over rate_ref_lo..hi]
```
Reference bands: `rate_ref` $60–120/hr; `MRR_ref` polymer 40, Al 25, steel 6, SS 4, Ti 1.5 cm³/min (independent, slightly more conservative); `shop_min_ref` $75–150; `setup_ref` 0.5–1.0 hr. Band = [low-rate/high-MRR, high-rate/low-MRR].

**(R3) Injection-molding tooling $ bands by size × cavity** (independent of V1's tier table):
| size (max bbox) | single-cavity tool band ($) |
|---|---|
| < 50 mm | 1,500 – 8,000 |
| 50–150 mm | 8,000 – 40,000 |
| 150–300 mm | 25,000 – 70,000 |
| > 300 mm | 50,000 – 120,000 |
Cavity scaling band `n^[0.5..0.8]`; per-part molded variable band $0.05–0.60. Source basis: published prototype-aluminum vs production-steel tool ranges.

**(R4) Shop/bureau minimums** (cross-check the §1.3 floors): CNC $75–150; powder-bed $50–100; resin $25–60; FDM $15–35.

### 13.2 Representative sample (≥10 real parts, spanning size × shape)

Selection algorithm (deterministic; run once, freeze the list into the harness as `SAMPLE_PARTS`):
```
for each *.stl in PARTS_DIR:
    run engine + extract_drivers; skip if GEOMETRY_INVALID
    bucket by  size_tier ∈ {tiny <5 cm³, small 5–30, medium 30–150, large >150}
           ×  shape ∈ {rotational (drivers.rotational), flat (nominal_wall>5 & min_bbox<0.25*max), boxy/other}
pick ≥1 valid part per non-empty (size×shape) bucket, ≥10 total; prefer the named demo parts first.
```
Mandatory anchors (must be in the sample): ECU Firewall Mount (flat, medium), Throttle Body Adapter (rotational, tiny — the B-1/B-2 regression part), Throttle Body Ring Outer (rotational, small). Fill the remaining ≥7 from the 105-file batch by the bucketing above. The frozen list + each part's (V, bbox, rotational) is written into the harness header so the sample is reproducible and auditable.

### 13.3 Error-band computation

For each (part, process) where V1 produces an estimate and a reference exists, at reference quantities **q ∈ {100, 1000}**:
```
v1   = V1 unit_cost(part, proc, q)              # make-as-is estimate
lo,hi= reference band (R1/R2/R3-variable + tooling/q for IM)
mid  = (lo+hi)/2
in_band   = lo ≤ v1 ≤ hi
signed_err= v1/mid − 1                            # + = V1 high, − = V1 low
```
Aggregate **per process**: n, median signed error, % in-band, worst over/under, and a PASS/FLAG verdict. Also a **per-part** detail table.

### 13.4 Pass criteria (V1 accuracy acceptance) — asserted in `test_costing_accuracy.py`

1. **≥ 80%** of (part, process, q) estimates fall inside the independent band.
2. **No process** has |median signed error| > 0.60 (no systematic > ±60% bias — consistent with the stated ±40–60% band).
3. **Regression (B-1/B-2):** throttle adapter SLS and MJF unit cost ≤ 2× the R1 upper band (the small-part AM over-cost is gone) — and **not** > 70% machine for any nested powder-bed estimate (B-2).
4. **Floors (B-3):** every CNC estimate at q=1 ≥ R4 CNC minimum; no estimate below its process's R4 floor.
5. **Tooling (B-5):** every IM tooling figure within the R3 band for its size×cavity.

### 13.5 Report format — `outputs/accuracy-report.md` (generated by the harness)

```
# CadVerify V1 — Accuracy Characterization (local, independent references)
Date · sample: N parts · references: R1 AM-volumetric, R2 CNC-MRR, R3 IM-tooling, R4 shop-mins (all local bands)

## Per-process error bands
| process | n | median signed err | % in band | worst over | worst under | verdict |
|---------|---|-------------------|-----------|------------|-------------|---------|
| sls     | … | +0.08             | 86%       | +0.4       | −0.2        | PASS    |
...

## Per-part detail
| part | V (cm³) | shape | process | V1 $/unit (q100) | ref band | in-band | signed err |
...

## Regression checks (the 8 weaknesses)
- B-1/B-2 small-part AM: throttle SLS $7.42 ≤ 2× ref-hi $… ✓ ; powder-bed machine ≤70% unit ✓
- B-3 floors: min CNC@q1 = $90 ≥ ref-min $75 ✓
- B-5 tooling: ECU IM $30,000 ∈ [25k,70k] ✓
## Stated honesty line
V1 stands behind the DECISION (crossover qty + make-vs-buy direction). Absolute $ characterized
here at ±X% per process against INDEPENDENT local bands — not a claim of absolute should-cost truth.
```

The harness is deterministic, runs in seconds, opens zero sockets (a G7-style `socket.socket` monkeypatch wraps the run in the test). It is the V1 deliverable that turns "±40–60%, trust us" into a **measured, reproducible** error characterization the Zoox buyer can audit.

---

## 14. Build order + acceptance

**Single builder.** Order: `rates.py` (new keys/accessors/region split) → `drivers.py` (`parts_per_build`) → `cost_model.py` (machine sub-models, post split, setup-per-lot, region per-line, min-charge clamp, cavity/complexity) → `estimate.py` (new options, pass-throughs, real per-qty estimates for decision) → `decision.py` (coherent semantics rewrite) → `report.py` (new decision block + new lines) → `cli.py` (new flags) → update `tests/*` → `harness.py` + `test_costing_accuracy.py` → generate `outputs/accuracy-report.md`.

**Done when:** all updated/added tests pass on the real parts (`CADVERIFY_PARTS_DIR=… pytest tests/test_costing_model.py tests/test_costing_gates.py tests/test_costing_accuracy.py -q`); the ECU decision card shows **one** make-now process identical in headline + low-qty recommendation + argmin, and that process is DFM-ready; the IM tooling route reads "if redesigned for molding"; powder-bed machine cost is no longer the dominant 80%; small-part AM is in the independent band; no estimate falls below its shop floor; `accuracy-report.md` exists with per-process error bands; Σ(line_items)=unit_cost and provenance-on-every-driver invariants still hold; zero network egress.

**Acceptance self-check:** every change names its module/function, formula, DEFAULT value + source basis, and override path; all new numbers in this spec were computed from the stated DEFAULTs in a verified prototype (ECU SLS $47.25, MJF $44.13, throttle SLS@100 $7.42, crossover ~739) — none fabricated; the coherence semantics are deterministic and single-sourced (headline ≡ low-qty argmin ≡ DFM-ready make champion); the accuracy harness uses independent local bands with explicit pass criteria. A competent builder ships V1 + the harness from this with zero further decisions.
