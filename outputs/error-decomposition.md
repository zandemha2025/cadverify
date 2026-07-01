# CadVerify — Empirical Cost-Error Decomposition (real parts)

**Author:** Error-Decomposition agent (Cost-Truth cycle) · **Status:** MEASURED from real engine
runs on real parts · **Network egress:** zero · **Date:** 2026-06-29

## What this is (and the honesty banner)

This document measures, on real parts in this repo, **where the current cost engine's
absolute-$ error actually comes from** — so the build that follows is grounded in
evidence, not assumption. The engine itself declares its absolute should-cost is
**±40–60%** (`estimate.py` closing note); this report opens that band and attributes it
across the four error buckets from the cycle brief:

1. **Default rates** — generic labor/machine $/hr, region, margin, overhead (removable by per-shop calibration).
2. **Routing** — wrong process/material family for the geometry (a heuristic/coverage bug).
3. **Cycle-time / process modeling** — per-process physics constants (shrinkable with tuning).
4. **Irreducible shop-to-shop business variance** — not solvable by any universal number; only by binding to a shop + measuring residuals on held-out parts.

> **STAND-IN yardsticks — not a validated accuracy claim.** We have **no real
> supplier quotes** for these parts. Every "true cost" reference here is either (a) an
> **independent local reference band** computed with *different math* than the engine
> (the harness R1 AM-volumetric / R2 CNC-MRR / R3 IM-tooling models in
> `backend/src/costing/harness.py`), or (b) a clearly-labeled **hand estimate / public
> quote band**. These are **STAND-IN** instruments to locate the *sources* of error and
> their *rough magnitudes*. The real ±X% accuracy figure is **PENDING the Zoox session**
> (real parts with real prices). Nothing below is presented as a measured accuracy claim.

All numbers are reproducible: `scratchpad/decomp.py` (this run) and
`python -m src.costing.harness` (the per-process aggregate).

---

## The parts (4 real parts: thin panel + flat bracket + 2 rotational)

| label | file | V (cm³) | bbox (mm, sorted) | wall 2V/A | shape | rotational |
|-------|------|---------|-------------------|-----------|-------|------------|
| **ThinPanel** | `Art2SideCover.stl` (corpus) | 51.8 | 2.0 × 120 × 280 | 1.94 mm | thin flat panel / cover | no |
| **FlatBracket** | `…_EK_0BD1_ECU_Firewall_mount.stl` | 66.8 | 32.6 × 62 × 160 | 7.63 mm | flat ECU firewall mount | no |
| **ThrottleBody** | `printables_707203_FD3S_to_GM_throttle_body.STL` | 248.7 | 35.6 × 133 × 143 | 9.76 mm | large rotational adapter | yes |
| **Parktronik** | `thangs_45359_…_Ford_Parktronik.STL` | 5.3 | 27.3 × 34 × 34 | 2.14 mm | small rotational sensor housing | yes |

All four are watertight and pass G1. (Note: the 5th common anchor — the MAF Sensor
Adapter — is `GEOMETRY_INVALID`: volume 0, non-watertight, so the engine correctly
refuses to cost it. That is the G1 gate working, not a cost error.)

---

## Engine output vs. STAND-IN yardstick (headline make-as-is pick)

The engine's headline "make-now" pick and unit cost, vs. the independent local reference
band (midpoint = stand-in "true" should-cost). Signed error `= engine/mid − 1`.

| part | qty | engine pick | engine $/u | indep. ref band | mid | signed err | in band? |
|------|-----|-------------|-----------:|-----------------|----:|-----------:|:--------:|
| ThinPanel | 1 | fdm (PLA) | **47.54** | 7.14 – 46.06 | 26.6 | **+79%** | ✗ |
| ThinPanel | 100 | mjf (PP) | **26.12** | 16.94 – 95.66 | 56.3 | **−54%** | ✓ |
| ThinPanel | 5000 | mjf (PP) | **25.99** | 16.94 – 95.66 | 56.3 | **−54%** | ✓ |
| FlatBracket | 1 | fdm (PLA) | **58.38** | 8.34 – 55.07 | 31.7 | **+84%** | ✗ |
| FlatBracket | 100 | cnc_3axis* | **43.34** | 18.99 – 81.55 | 50.3 | **−14%** | ✓ |
| FlatBracket | 5000 | mjf→IM xover | 43.98 / **9.39** | 5.05 – 14.60 | 9.8 | −4% | ✓ |
| ThrottleBody | 1 | cnc_turning | **90.00** | 75.0 – 201.1 | 138 | **−35%** | ✓ |
| ThrottleBody | 100 | cnc_turning | **62.61** | 49.0 – 201.1 | 125 | **−50%** | ✓ |
| Parktronik | 1 | fdm (PLA) | **30.00** | 3.42 – 18.19 | 10.8 | **+178%** | ✗ |
| Parktronik | 100 | mjf (PP) | **7.40** | 5.33 – 25.96 | 15.6 | **−53%** | ✓ |

\* FlatBracket q100: engine's true argmin make-as-is is `cnc_3axis $43.34` but it is
DFM-`fail` as modeled; the DFM-ready headline is `mjf $44.13`. Both shown.

Three patterns jump out immediately, and they map directly onto the buckets:

- **At qty 1, the engine is +79% to +178% high and falls OUT of band** — driven by the
  per-lot **min-charge floor** and per-part labor/setup defaults (bucket 1/3), not geometry.
- **At production qty the same parts read −50% to −54% LOW** on powder-bed (MJF/SLS) — a
  systematic **cycle-time/process-model** bias (bucket 3).
- **The "make-now" process itself is questionable** for the panel (sheet metal, not MJF)
  and for the rotational parts (the default polymer class, not aluminum) — **routing**
  (bucket 2).

---

## Bucket 1 — Default rates (the biggest *controllable* lever)

**Measured by sensitivity sweep:** re-run the headline process, moving each rate from the
generic default to a plausible shop-specific value. Span of the resulting unit cost = the
error a generic rate card injects vs. knowing YOUR shop.

| part / process | base $/u | labor 25→60 | margin 0→25%→50% | machine ±40% | region US→CN | **full sweep** |
|---|---:|---|---|---|---|---|
| ThinPanel mjf q100 | 26.12 | −6% / +14% | +25% / +50% | ±32% | −45% | **$14.4–39.2 (×2.7, ±46%)** |
| FlatBracket mjf q100 | 44.13 | −4% / +11% | +25% / +50% | ±34% | −45% | **$24.3–66.2 (×2.7, ±46%)** |
| ThrottleBody turn q100 | 62.61 | −5% / +12% | +25% / +50% | ±30% | −42% | **$36.3–93.9 (×2.6, ±44%)** |
| Parktronik mjf q100 | 7.40 | −13% / +32% | +25% / +50% | ±22% | −45% | **$4.1–11.3 (×2.8, ±47%)** |

**Findings:**
- **Generic rates alone move the answer ±44–47% (a 2.6–2.8× full span).** This is the
  single largest *removable* contributor and it is removed entirely by calibration: once
  the shop's labor rate, machine rate, region and margin are known, this collapses.
- **`margin = 0.00` is a structural low-bias of −20% to −33% vs. a real *price*.** The
  card (`rates.py`, `global.margin`) sets margin to zero by design ("should-cost, not price"). A real
  supplier *quote* carries 25–50% margin, so comparing engine output to a real quote will
  read systematically low by exactly that amount. Named, quantified, removable.
- **Region is a ±45% lever by itself** (`region_labor`: US 1.00 vs CN 0.55, `rates.py:136`).
  Defaulting to US over-states an offshore-sourced part by ~1.8×.

**Responsible constants (all in `backend/src/costing/rates.py`):** `global.labor_rate=35`,
`global.margin=0.00`, per-process `machine_rate` (FDM 8 … CNC-5ax 110), the three
`region_*` tables. All are DEFAULT-tagged and override-able — exactly the inputs a
per-shop calibration step would bind.

---

## Bucket 2 — Routing (small on correctly-routed parts; dominant on the misrouted class)

Routing error is **bimodal**: ≈0 when the engine's process/material family matches the
real part, but **1.5×–6×** when it does not. Two concrete failure modes, both present here:

**2a. The flat-panel routing GAP (structural — the headline cycle example).**
`SHEET_METAL` exists as a `ProcessType` (`analysis/models.py:42`) but is **excluded from
`COSTED_PROCESSES`** (`rates.py:28`) — so a sheet-metal/stamped panel **can never receive
a dollar should-cost**. Worse, on the as-modeled solid STL the sheet-metal analyzer
returns `verdict=fail, score=0.0` (the printed solid carries no bend/constant-wall
topology), so the engine cannot even *see* the route. The 2 mm ThinPanel is therefore
forced into AM/CNC:
- Engine make-as-is at volume: **MJF $26/u** (or IM $8/u "if redesigned").
- Hand estimate (STAND-IN), 120×280×2 mm panel as **stamped/sheet metal** at 1k+ with a
  form tool: **~$4–10/u** (laser-blank + bend; public SendCutSend/Xometry-class band).
- → the headline is **~3–6× the true production cost** for a part that is "really" sheet
  metal. This is the exact "3 mm flat panel led with MJF instead of stamping" failure the
  cycle brief calls out, reproduced and quantified.
- **Caveat (honest):** if this cover is genuinely intended as a 3D-printed part, AM
  routing is *correct* and routing error ≈ 0. The miss is conditional on **design intent
  that the STL alone does not encode** — which is itself the finding: geometry-only
  routing cannot recover intent, so this bucket needs an intent/material signal, not just
  better geometry math.

**2b. The default material-class lever (`polymer`).**
`EstimateOptions.material_class` defaults to `"polymer"` (`estimate.py`, `EstimateOptions`). For the two
rotational parts that is plausibly wrong — a throttle-body adapter and a sensor housing
are commonly **aluminum**. Re-running with the real class:

| part | polymer (default) make-now | aluminum make-now | swing |
|------|----------------------------|-------------------|-------|
| ThrottleBody | cnc_turning Delrin **$62.61** | cnc_turning Al **$70.73** | +13% (material) |
| Parktronik | **mjf $7.40** | **cnc_turning $15.73** | **×2.1 + process flip** |

For Parktronik the default class flips both the **process** (MJF→turning) and **doubles**
the unit cost. The class guess is a routing decision worth up to ~2× — and it is a single
buyer-supplied field away from being right.

**What is already fixed (don't re-attack):** the routing layer (`routing.py`) *did* kill
the Inconel-for-plastic / turning-for-brackets bugs — material is re-derived by family
(`MATERIAL_FAMILY`), turning is gated on `rotational`, IM on polymer. Among *costable*
processes, material routing is sane. The residual routing error is the **process-coverage
gap** (sheet metal, stamping, real casting not costable) and the **default class guess**.

---

## Bucket 3 — Cycle-time / process modeling (systematic, per-process, tunable)

**Measured by:** signed error vs. the *independent* reference (R1/R2/R3 use different
cycle/throughput math), holding process and rates fixed. The per-process medians from the
full harness sample (24 comparisons/process, `outputs/accuracy-report.md`) corroborate the
4-part run:

| process | median signed err | direction | likely responsible constant |
|---------|------------------:|-----------|------------------------------|
| fdm | **+38%** (4-part: +70…+178%) | over | `deposition=16 cm³/hr` slow + per-part labor/setup |
| sla | +35% | over | `deposition=8`, laser-trace machine time |
| dlp | −39% | under | `vert=30` build-job sweep amortization |
| **mjf** | **−50%** | under | `packing_density=0.10` over-nests in 380×284×380 env |
| **sls** | **−48%** | under | same volumetric nesting + `machine_rate=20` |
| cnc_3axis | −5% | centered | well-modeled |
| cnc_5axis | +27% | over | `machine_rate=110` |
| **cnc_turning** | **−30%** (4-part: −35…−50%) | under | `mrr.polymer=50 cm³/min` too fast + **no per-part handling line** |
| injection_molding | −28% (variable +50…+146% at 5k) | mixed | `cooling_coef=2.0·wall²`, molded-variable too thin at high qty |

**Findings:**
- **Powder-bed (MJF/SLS) is systematically −48 to −50% low.** Root cause: the volumetric
  `parts_per_build` model with `packing_density=0.10` packs many small parts into the big
  SLS/MJF envelope, driving per-part machine cost very low (e.g. MJF machine = $20.90 on a
  52 cm³ panel). A real 3D nesting/orientation-aware packer would pack fewer.
- **FDM is systematically +38 to +180% high** and is the one process that repeatedly
  falls OUT of band — the deposition rate (16 cm³/hr) + per-part finishing/setup labor
  over-cost it, worst at qty 1.
- **CNC turning is −30 to −50% low** because `mrr.polymer=50` makes roughing time
  negligible **and the model has no separate per-part load/deburr/inspect handling line**
  — the independent R2 reference adds 0.05–0.15 hr/part handling that V1 omits.
- **IM molded-variable is too thin at high qty** (Parktronik IM $3.14 vs ref mid $1.3 →
  +146% at 5k): cooling ∝ wall² with `cooling_coef=2.0` under-resolves the real shot/
  packing/handling floor.

These are ±30–60% process-dependent biases — the bucket that shrinks with per-process
physics + tuning against real cycle data, **not** with calibration.

**Responsible constants:** `rates.py` per-process `deposition`, `vert`, `packing_density`,
`machine_rate`, `mrr`, `cooling_coef`; and `cost_model.py` `_additive_machine` /
`_cnc_cycle` / `_formative_cycle` (notably the missing CNC per-part handling term).

---

## Bucket 4 — Irreducible shop-to-shop variance (the floor; only per-shop binding removes it)

The independent reference **band width** is the realistic cross-shop price spread for a
given part+process. Measured from this run:

| part / process | ref band | band ratio | half-width |
|---|---|---:|---:|
| ThinPanel mjf | 16.94 – 95.66 | **5.6×** | ±70% |
| FlatBracket mjf | 20.70 – 118.19 | **5.7×** | ±70% |
| ThrottleBody turning | 49.05 – 201.09 | **4.1×** | ±61% |
| FlatBracket cnc_3axis | 18.99 – 81.55 | **4.3×** | ±62% |

The raw cross-shop band is **±60–70%**. **But this is not all irreducible** — most of it is
the *knowable* rate/margin/region spread (bucket 1, measured at ±44–47%). The portion that
survives **after** you bind to one shop and learn its rates — genuine business variance
(utilization, what-the-market-bears, quote-to-quote noise) — is the truly irreducible
floor. Published *same-process, same-part* quote spreads across nominally-similar shops run
**~±20–35%** (STAND-IN from industry observation, **not measured here**). That residual is
the part no universal geometry-derived number can remove; it is removed only by **binding
to a shop and measuring residuals on held-out real parts** — which is the product thesis.

---

## Which buckets dominate — priority for the build

Ranked by *attackability × magnitude* on these real parts:

| rank | bucket | magnitude here | nature | how it's removed |
|------|--------|----------------|--------|------------------|
| **1** | **Default rates** | ±44–47%, +structural −20–33% from margin=0 | fully controllable | **per-shop calibration** of labor/machine/margin/region |
| **2** | **Routing** | ≈0 when right; **2×–6×** on the misrouted class (panel→stamping, polymer→aluminum) | heuristic/coverage bug | cost `SHEET_METAL`/stamping/casting + capture material-class & intent |
| **3** | **Cycle-time / process model** | ±30–60%, per-process (MJF/SLS −50%, FDM +40–180%, turning −30%) | modeling error | per-process physics + tuning vs real cycle data |
| **4** | **Irreducible business variance** | ~±20–35% (stand-in) of a ±60–70% raw band | not solvable universally | **bind to shop + measure residuals on held-out parts** |

**Bottom line for the cost-truth engine:** the dominant *removable* error on real parts is
**generic rates (bucket 1)** — directly answered by per-shop calibration, which is the
engine's core thesis. The highest-variance *tail* is **routing (bucket 2)** on flat panels
and metal rotational parts, where the engine is structurally unable to cost the real
process (sheet metal not in `COSTED_PROCESSES`) or guesses the wrong material class. The
**±40–60% the engine self-declares is real and decomposes as**: ~±45% rates (calibratable)
+ ±30–60% process-model bias (tunable) + a routing tail that is small-or-huge depending on
the part + an irreducible ~±20–35% floor that only per-shop binding + held-out measurement
can characterize. The first three are engineering; the fourth is the moat (measure it,
don't chase it).

---

## Honesty / limitations

- **No real ground truth.** Every "true cost" here is an independent local reference band
  or a labeled hand estimate. They locate *sources and rough magnitudes* of error; they do
  **not** establish a validated ±X% accuracy. That figure is **PENDING the Zoox session**.
- **The independent references are themselves ±2–4× bands**, so the per-part signed errors
  carry that uncertainty; the *direction and rough size* of each bias are robust (they
  repeat across parts and across the 24-part harness sample), the exact percentages are not.
- **Bucket boundaries are approximate and partly overlapping** (rates vs. band width share
  cause); the brief treats them as rough, and so does this report — no quadrature games.
- **Routing bucket is intent-conditional:** geometry alone cannot tell a printed cover from
  a stamped one; the panel "routing miss" assumes a production-sheet-metal intent and is
  stated as such.
- Reproduce: `python scratchpad/decomp.py` (this run) and `python -m src.costing.harness`
  (per-process aggregate). Zero network.
