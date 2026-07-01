# CadVerify — Per-Shop Calibration (Shop Profiles)

**Author:** Calibration-Builder agent (Cost-Truth cycle) · **Status:** built + RUNS on
real repo parts · **Network egress:** zero (CAD-as-IP) · **Date:** 2026-06-29

## What this is (and which error it kills)

`outputs/error-decomposition.md` measured, on real parts, that **generic default
rates are the single largest *removable* source of absolute-cost error — ±44–47%**
(bucket #1: labor/machine $/hr, region, overhead, margin). That error exists only
because the engine costs every part with one generic rate card. This deliverable
removes it by **binding the engine to ONE shop's real numbers**: a `ShopProfile`.

> The product sentence this enables: *"For YOUR shop, this part should cost $X — and
> here is every driver, tagged whether it came from your profile (SHOP) or a generic
> fallback (DEFAULT), all editable."* The remaining ±Y% accuracy figure is still
> **PENDING real ground-truth quotes** (the Zoox session) — calibration removes the
> *rate* error; it does not invent a validated accuracy claim. Nothing here is
> presented as a measured accuracy number.

## The four-way provenance (the glass box)

Every driver and assumption now carries one of four tags:

| tag | meaning |
|-----|---------|
| `MEASURED` | extracted from the CAD (volume, area, bbox). Not assumable. |
| `SHOP` | **NEW** — bound from the **active calibrated shop profile** (this shop's reality). |
| `USER` | overridden ad-hoc for THIS quote (`rate_overrides`, `--set ...`). |
| `DEFAULT` | the generic rate card — the clearly-labeled fallback when no shop covers it. |

**Precedence:** `DEFAULT < SHOP < USER`. A bound shop flips its covered defaults to
SHOP; an explicit ad-hoc override still wins (and reads USER). A field the shop never
set **stays DEFAULT** — gaps in a half-calibrated shop are visible, never hidden.

## What a profile captures (`src/costing/shop_profile.py`)

```python
ShopProfile(
    name="Midwest Precision CNC",
    region="US",
    labor_rate=52.0,            # $/hr loaded shop-floor labor
    margin=0.30,                # target margin (price vs should-cost)
    overhead=0.15,              # indirect burden on conversion (machine+labor+setup)
    utilization=0.80,           # machine utilization (idle recovered in machine cost)
    machine_rates={             # per-process machine $/hr (ProcessType NAMES)
        "CNC_3AXIS": 95, "CNC_5AXIS": 135, "CNC_TURNING": 85,
        "SLS": 28, "MJF": 30, "FDM": 12, "INJECTION_MOLDING": 60},
    material_prices={           # $/kg by exact material name OR "@<class>" sentinel
        "@polymer": 7.0, "@aluminum": 9.0, "Delrin (POM)": 6.5},
    region_multipliers={"labor": 1.0, "material": 1.0, "tooling": 1.0},
    source="Shop accounting export 2026-Q2",   # audit trail of where the numbers came from
    notes="Aerospace/automotive job shop, 8 CNC machines, in-house SLS.")
```

Every field except `name` is optional; anything left unset falls back to the generic
DEFAULT. The fields map 1:1 onto bucket #1: **labor, machine $/hr per process,
material lot prices, utilization, overhead, margin, region.**

## How it binds (no rebuild — it reuses the rate-card override path)

`ShopProfile.to_shop_overrides()` flattens into the dotted-key form the rate card
already understands. `build_rate_card(overrides, shop_overrides=..., shop_name=...,
shop_region=...)` applies the shop bindings as SHOP, then any ad-hoc `rate_overrides`
as USER on top. Two new global levers were added to the rate card, both **no-ops at
their defaults** so nothing changes when no shop is bound:

- `overhead` (default `0.0`) — `(1+overhead)` markup on machine + labor + setup (not
  on commodity material).
- `utilization` (default `1.0`) — machine cost ÷ utilization (idle recovery).

Material lot prices live in a new `material_prices` map (default empty → fall back to
the material-DB unit price, which stays `MEASURED`).

## Persistence (local, CAD-as-IP)

Profiles are JSON in a **local store**: `backend/data/shop_profiles/<slug>.json`.
Nothing opens a socket.

```python
from src.costing import ShopProfile, save_profile, load_profile, list_profiles
save_profile(profile)                 # -> backend/data/shop_profiles/midwest-precision-cnc.json
list_profiles()                       # -> ['midwest-precision-cnc', 'shenzhen-contract-mfg']
shop = load_profile("Midwest Precision CNC")   # name or slug or explicit .json path
```

## Use it

**Python:**
```python
from src.costing import estimate_decision, EstimateOptions
report = estimate_decision(result, mesh, features,
                           EstimateOptions(quantities=[50, 5000], shop="Midwest Precision CNC"))
```
`shop=` accepts a `ShopProfile`, a stored name/slug, a `.json` path, a dict, or `None`.

**CLI:**
```
python -m src.costing.cli part.stl --qty 50,5000 --shop "Midwest Precision CNC"
```

Reproduce the whole demo (creates the two example profiles + re-costs a real part):
```
cd backend && PYTHONPATH=. .venv/bin/python scripts/calibration_demo.py
```

---

## Before / After — REAL captured output (ECU Firewall Mount, qty 50)

Same part, same geometry (`66.79 cm³` polymer bracket), headline process **MJF**.
Captured from `python -m src.costing.cli <ECU>.stl --qty 50,5000 [--shop ...]`.

### BEFORE — generic DEFAULT rate card (no shop)
```
mjf / PP (Polypropylene)    qty 50: $44.13/unit   qty 5000: $43.98/unit    ±40%
    material_cost  $0.13  [MEASURED ... × $2/kg (material-DB unit price (DEFAULT)) ...]
    machine_cost   $37.16 [DEFAULT 1.6889 hr × $22/hr × region-labor ×1 ...]
    labor_cost     $4.74  [DEFAULT ... × $35/hr × region-labor ×1]
    setup_cost     $2.10  [DEFAULT setup 0.5hr × $35/hr ...]
    line items Σ = $44.13 (= amortized_fixed $2.10 + material $0.13 + machine $37.16 + labor $4.74)
ASSUMPTIONS: labor_rate $35/hr [DEFAULT] · margin 0 [DEFAULT] · overhead 0 [DEFAULT]
             · utilization 1 [DEFAULT] · ...
```

### AFTER — bound to `Midwest Precision CNC` (`--shop`)
```
mjf / PP (Polypropylene)    qty 50: $110.49/unit   qty 5000: $110.15/unit    ±40%
    material_cost  $0.60  [SHOP ... × $7/kg (shop polymer lot price) ...]
    machine_cost   $94.68 [SHOP 1.6889 hr × $30/hr ÷ 0.8 utilization × region-labor ×1 × 1.15 overhead ...]
    labor_cost     $10.54 [SHOP ... × $52/hr × region-labor ×1]
    setup_cost     $4.66  [SHOP setup 0.5hr × $52/hr ...]
    line items Σ = $110.49 (= amortized_fixed $4.66 + material $0.60 + machine $94.68 + labor $10.54)
ASSUMPTIONS: labor_rate $52/hr [SHOP] · margin 0.3 [SHOP] · overhead 0.15 [SHOP]
             · utilization 0.8 [SHOP] · stock_allowance 1.1× [DEFAULT] · ...
  • Calibrated to shop 'Midwest Precision CNC' (region US): 19 rate(s) bound to this
    shop's reality and tagged SHOP [...]. Every other line stays a generic DEFAULT —
    the gaps are visible, not hidden. Source: Shop accounting export 2026-Q2.
```

### Switching profiles visibly changes the cost
Same ECU part, headline MJF @ qty 50:

| profile | headline | unit cost | vs DEFAULT |
|---------|----------|----------:|-----------:|
| DEFAULT (no shop) | mjf | **$44.13** | — |
| Midwest Precision CNC (US, premium) | mjf | **$110.49** | **+150%** |
| Shenzhen Contract Mfg (CN, low-cost) | mjf | **$35.29** | **−20%** |

CNC_3AXIS @ qty 50 (where **both** material lot price and machine $/hr bind):

| profile | unit | material | machine |
|---------|-----:|----------|---------|
| DEFAULT | $43.60 | $1.22 `[MEASURED]` | $24.35 `[DEFAULT]` |
| Midwest | $99.75 | $2.07 `[SHOP]` | $57.65 `[SHOP]` |
| Shenzhen | $27.73 | $1.06 `[SHOP]` | $18.34 `[SHOP]` |

In every row, `unit_cost == Σ(line_items)` still holds (asserted in the demo and tests).

---

## Acceptance test — all pass

- **Re-costs real parts with the shop's numbers** — yes (ECU bracket above; demo runs
  on `scratchpad/parts`).
- **Every line item shows profile-vs-default** — yes (`SHOP` / `DEFAULT` / `MEASURED`
  / `USER` on every driver + assumption; source strings name the price/rate).
- **Switching profiles visibly changes cost** — yes ($44 → $110 → $35).
- **`unit_cost == Σ(line_items)` still holds** — yes (gate G3 assertion intact).
- **Existing tests still pass** — yes: `test_costing_model` (14), `test_cost_api` (18),
  `test_costing_gates` (16, real parts), plus **12 new** `test_costing_calibration`.

## Honest notes / limitations

- **Region & double-counting.** The engine models effective labor as
  `labor_rate × region_labor[region]`. A calibrated shop's `labor_rate` is its TRUE
  loaded rate, which already encodes its region — so a fully-bound profile should pin
  `region_multipliers` (typically `labor=1.0`) to avoid charging a regional factor
  twice. Both example profiles do exactly this. A profile that sets `region` but not
  `region_multipliers` will still apply the generic regional vectors on top of its
  absolute rate; that is documented, visible in the drivers, and editable.
- **Overhead is applied to conversion only** (machine + labor + setup), not to
  commodity material or to quoted tooling — consistent with the existing region-split
  design (material ≠ labor).
- **Calibration removes bucket #1 (rates), not buckets #2/#3** (routing coverage,
  per-process cycle-time physics). Those are separate work. A perfectly calibrated
  shop can still be wrong on a misrouted part — calibration makes the *rate* truthful,
  not the *process model*.
- **No accuracy claim.** This binds the engine to a shop's stated reality; it does not
  validate the result against real quotes. The real ±Y% is PENDING ground truth.

## Files

- `backend/src/costing/shop_profile.py` — `ShopProfile`, save/load/list, `resolve_shop`.
- `backend/src/costing/rates.py` — `overhead`/`utilization`/`material_prices` levers;
  `RateCard` shop tracking + `material_price()` + `region_prov()`; `build_rate_card`
  shop binding.
- `backend/src/costing/cost_model.py` — overhead/utilization/material-price wiring.
- `backend/src/costing/estimate.py` — `EstimateOptions.shop` + binding + assumptions.
- `backend/src/costing/provenance.py` — `Provenance.SHOP`.
- `backend/src/costing/cli.py` — `--shop` flag.
- `backend/tests/test_costing_calibration.py` — 12 tests.
- `backend/scripts/calibration_demo.py` — reproducible end-to-end demo.
- `backend/data/shop_profiles/{midwest-precision-cnc,shenzhen-contract-mfg}.json` —
  two example persisted profiles.
