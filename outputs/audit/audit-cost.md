# CadVerify — Cost-Engine Audit (Senior Manufacturing Cost Engineer lens)

**Auditor stance:** a cost engineer who has quoted thousands of CNC/molded/sheet/AM
parts. I read the engine source, ran the CLI on real automotive parts (uncalibrated
and shop-calibrated), and traced every dollar. I did **not** attempt to certify the
numbers are *right* — that needs real quotes (see the validation packet at the end).

**Verdict in one line:** the *architecture* of a glass-box should-cost engine is
genuinely here and better than most commercial DFM tools' black boxes — itemized,
provenance-tagged, Σ-invariant, honestly banded. But the *manufacturing content* of
the cost model is a competent first-order physics sketch, not a cost engineer's
estimate: it is blind to the two things that actually move a quote — **tolerance/finish**
and **volume/learning economics** — and several sub-models under-cost by construction.
The ±40% is an unvalidated assertion (n=0 ground truth) that shop-rate variance alone
already blows past.

Evidence base (all reproducible):
`cd backend && .venv/bin/python -W ignore -m src.costing.cli "<part>" --qty ... [--shop "Midwest Precision CNC"]`
- ECU firewall mount (160×62×33mm, 66.8 cm³), aluminum
- Mazduino LITE TOP (85×88×23mm, 23.2 cm³ thin-wall enclosure), polymer
- e12can spacer (75×75×16mm plate), steel
- MAF adapter, OBD2 cover — both non-watertight → refused
Engine files: `backend/src/costing/{cost_model,rates,drivers,routing,decision,leadtime,confidence,shop_profile,groundtruth,estimate}.py`
Live app confirmed up (`:8000/health` 200, `:3000` 200); API route `POST /api/v1/validate/cost` calls the **same** `estimate_decision` as the CLI (`backend/src/api/routes.py:638`), so the CLI *is* the product's cost engine.

---

## REAL — works, and I verified how

1. **Itemized master formula with a hard Σ = unit_cost invariant.**
   `cost_model.py:cost_breakdown` builds `line_items = {amortized_fixed, material,
   machine, labor}` (+ `min_charge_floor` when it bites) and asserts the sum equals
   `unit_cost` before returning (`est.assert_sums()`, line 368). Every CLI run prints
   `line items Σ = $X (= ...)` and it ties out exactly. This is a real glass box, not a
   `$/cm³` toy — verified on every part.

2. **Provenance is wired end-to-end (MEASURED / USER / DEFAULT / SHOP).** Each `Driver`
   carries a provenance tag and a human-readable `source` string. Verified: material mass
   reads `[MEASURED CAD volume 66.79 cm³ × ... density ...]`; with a shop bound the same
   line flips to `[SHOP ... $9/kg (shop lot price)]`. The "where did this number come
   from" question a buyer/QE always asks is answered per line.

3. **Per-shop calibration is SUBSTANTIVE, not a stub.** `shop_profile.py` +
   `data/shop_profiles/*.json` bind loaded labor rate, per-process machine $/hr,
   negotiated material lot prices, utilization, overhead, target margin, and region as
   SHOP-provenance keys. Verified on the ECU part: uncalibrated `cnc_5axis` = **$64.74/unit**;
   with `--shop "Midwest Precision CNC"` = **$147.30/unit** — a **2.3×** swing from
   plausible real shop rates ($135/hr vs $110/hr, ÷0.8 util, ×1.15 overhead, ×1.3 margin,
   $52/hr labor), every changed line correctly re-tagged SHOP. Two realistic example
   profiles ship (US aerospace job shop + CN contract mfg). This is the single most
   credible part of the offering.

4. **Physics-based cycle-time sub-models per family** (not fitted constants):
   - CNC: roughing `removed_vol / (MRR·60)` + finishing `surface_area / finish_rate`.
   - Sheet: `perimeter / cut_speed(gauge)` + `bends × sec_per_bend` + handling.
   - Molding: cooling `coef·wall²` + shot overhead.
   - Additive: build-plate nesting (`parts_per_build`) + per-part deposition + amortized
     Z-sweep. Each term prints its own inspectable source string.

5. **Confidence interval on every estimate, honestly labeled.** `confidence.py` attaches
   a CI to every line and — critically — the `validated=True` flag can *only* be set from
   **real (non-stand-in) ground-truth residuals**; synthetic data can shape the spread but
   can never flip `validated`. Every run today prints "assumption-based, not yet validated".
   This is the correct honesty architecture.

6. **The ground-truth loop mechanism exists** (`groundtruth.py`): deterministic
   split-by-part-identity (no leakage), tune-on-tuning/eval-on-held-out, stand-in-never-counts-as-real,
   one robust per-process correction factor. The *machinery* to eventually earn a trusted
   number is built (it just has no data — see MISSING #1).

7. **Make-vs-buy crossover is mathematically sound.** `decision.py` ranks by real per-qty
   unit cost, derives the tooling crossover from the fixed/variable split
   (`q* = (fixed_b − fixed_a)/(var_a − var_b)`), and refuses to headline a DFM-failing
   process. The framing ("crossover direction is robust even if absolute cost is ±40%") is
   the right thing to say.

8. **The "8 weaknesses" fixes are real code, not comments:** region 3-vector split, tooling
   `cavity^0.7 × complexity`, per-lot setup recurrence `ceil(qty/lot)`, min-charge floor,
   build-plate nesting. Verified in the printed source strings.

---

## STUBBED / FRAGILE — looks done, isn't (prioritized by $ impact)

### S1 — CNC unit cost is VOLUME-INVARIANT (highest priority; undermines the decision layer)
Verified: ECU mount, `cnc_3axis` = **$46.10/unit at qty 100, qty 1,000, AND qty 100,000**;
`cnc_5axis` = **$64.74/unit flat** across the same range. The *only* qty effects are the
min-charge floor (qty≈1) and setup amortized over `lot_size`. There is **no learning curve,
no cycle-time reduction, no dedicated fixturing/palletization/lights-out automation** at
volume. Every cost engineer knows a machined part drops **30–60%** from 100→10k/yr. Because
the make-vs-buy crossover quantity is computed from the machining variable cost vs the tooled
variable cost, a flat (too-high) machining variable cost **pushes the crossover to the wrong
quantity** — i.e. the headline "decision" is built on a variable cost that doesn't behave like
real machining. This is the most important single fix.

### S2 — No tolerance / surface-finish / GD&T input ANYWHERE
The #1 cost driver after material and envelope. Two identical geometries — one at ±0.1mm/Ra3.2,
one at ±0.005mm true-position with Ra0.4 and flatness callouts — produce the **identical** cost
here. Finishing is a single flat `finish_rate` (cm²/hr) per process. Real life: tight tolerance →
slower feeds, spring passes, grinding/reaming, CMM inspection, higher scrap; fine finish → extra
ops. A should-cost tool a buyer would trust *starts* from the drawing tolerances. Absent.

### S3 — CNC stock = convex hull, not the bounding-box billet you actually buy
`drivers.stock_mass_kg` uses `hull_volume × allowance`. You machine from a **rectangular billet ≈
the bounding box**, not the hull. ECU mount: hull **150 cm³** vs bbox **323 cm³**. Consequences:
(a) material mass under-charged; (b) worse — `removed = stock − part` uses the hull, so removed
volume is **98 cm³ instead of ~256 cm³**, understating roughing time **~2.6×** for any non-convex
part. Systematic under-cost that grows with how "un-blocky" the part is.

### S4 — CNC cycle time has no feature awareness
`cycle = removed/MRR + area/finish_rate`. No holes/pockets/slots/bores, no drilling/tapping/thread
milling, no tool changes, no rapids/approach-retract, no rest machining in corners, no separate
setups/re-fixturing count. Real machining time is driven by **feature count and tool changes**, not
total surface area. A plain block and a block covered in bored/tapped features cost the same per cm²
here. This is the weakest link in the subtractive model.

### S5 — No programming/NRE, no FAI/inspection → prototypes badly under-costed
CNC setup is `0.75–1.0 hr` only. There is **no CAM programming / first-article NRE** (2–8 engineering
hours for a 5-axis part) and **no inspection/FAI/PPAP** line. Verified: ECU mount at **qty 1 = $90**
(just the min-charge floor). A real one-off machined aluminum bracket with programming + first article
is **$150–400**. Low-volume and prototype numbers are the least trustworthy output today.

### S6 — Missing whole cost categories a quote always has
No **perishable tooling/consumables** (endmills, inserts ≈ 5–15% of machine cost), no coolant, and —
importantly — **no secondary-finishing COST**: anodize / plate / paint / powder-coat / passivate /
heat-treat are modeled only as `post_hr_part` labor hours, never as the outsourced **lot charge** they
actually are. An anodized aluminum bracket is missing a real $3–15/part (or minimum lot charge).

### S7 — The ±40/50/60% band is symmetric, uniform-per-family, and unvalidated
`confidence.py:_assumption_interval` is literally `point × (1 ± band)`. It is **not** a statistical
interval, **not** part-specific, and **not** measured (n=0). Real should-cost error is **asymmetric**
(estimates skew *low* because missed features/ops only add cost) and **grows with complexity/tolerance**.
And the killer: I verified that **shop-rate variance alone swings the same part 2.3× ($64.74→$147.30)** —
so for an *uncalibrated* quote the honest uncertainty is closer to **±2–3×, not ±40%**. The ±40% is
defensible only *after* a shop is calibrated, and even then only *after* it's measured against real quotes.

### S8 — Sheet metal bills a full rectangular blank per part; no cross-part nesting
`cost_model.py` sheet material = `bbox_volume × density` (footprint × gauge). Real sheet parts are
**nested on a 4×8/4×10 sheet** with skeleton/scrap credit. Charging each part its own rectangle
over-costs material and ignores nest utilization — a number a sheet shop would immediately reject.

### S9 — Additive ignores support material, rafts, and support-removal time
Material = net part mass only (`mass_kg`). Supports/rafts can be 10–50% of both material and print
time on FDM/SLA and drive most of the hand-finishing labor. Under-modeled.

### S10 — Injection molding cycle overhead is unrealistically low; tooling is a single knob
`shot_overhead_s = 5` (`rates.py:55`) — real small-part cycle (fill + pack/hold + cool + mold
open/close + eject + part removal) is **15–40 s**. Tooling is a flat size-tier ROM × `cavity^0.7 ×
complexity`; a single "complexity" enum stands in for slides/side-actions/SPI finish/steel grade/texture/
hot-vs-cold runner/cavity count. Default is single-cavity, so a 10k/yr part is modeled on a 1-cavity
tool unless the user knows to set `--cavities`. (The molding *machine* cost is tiny vs tooling, so this
mostly hurts cycle/lead-time realism, not the unit cost at volume.)

### S11 — Shop calibration is real but SHALLOW, and the example numbers are hand-entered
Profiles cover ~7 processes and ~5 materials; everything else stays DEFAULT (honestly tagged, but a
lot of the quote is still generic). And the two shipped profiles are *plausible hand-typed* numbers —
they are **not** derived from a residual fit against that shop's real quotes. The calibration path is
"enter your rates", not yet "we measured your rates" (that's what the empty ground-truth loop is for).

### S12 — Robustness on real-world STL: a large fraction simply won't cost
Two of the most interesting real automotive parts I pulled — the **MAF sensor adapter** and the
**OBD2 cover** — are **non-watertight** and return `GEOMETRY_INVALID` (no cost at all). Consumer/hobby
and even many supplier STLs are non-watertight. There is a `POST /api/v1/validate/repair` route (not
audited here) — its real efficacy needs verification; if repair is weak, the cost engine's *effective*
coverage on real uploads is much lower than it looks.

---

## MISSING — gaps to be a credible, buyable, enterprise should-cost platform

**M1 — Real ground truth (n=0).** `data/ground_truth/records.jsonl` does not exist. The entire accuracy
claim is asserted. Until ≥30–50 real quotes per dominant process are loaded and the held-out residual is
measured, the tool cannot say "$X ± Y%, validated." This is the gating item for "buyable."

**M2 — Tolerance/GD&T/surface-finish cost model** (see S2). Table-stakes for a should-cost tool that a
sourcing/QE org will trust.

**M3 — Volume & learning economics** (see S1): machining cycle-time reduction, labor learning curve,
dedicated-fixture/automation regimes, and yield improvement with volume.

**M4 — Feature-based CNC cycle time** (see S4): hole/thread/pocket recognition, a tool library, and an
explicit setup/re-fixturing count. This is what turns a "sketch" into a machinist's estimate.

**M5 — Programming/NRE, FAI/PPAP, inspection, and secondary-finishing cost lines** (S5, S6).

**M6 — Material coverage & pricing depth.** 46 materials, with real gaps:
- **No carbon/alloy machining steels** (1018, 1045, 4140, 4340, A36, 12L14) — the CNC "steel" class has
  *no* proper bar stock, so a steel CNC part is mislabeled with **"Mild Steel (Sheet)"** (verified on the
  e12can spacer). No tool steels (A2/D2/H13), no **brass/bronze/copper** for CNC, no **magnesium**, thin
  stainless (only 304/316L/17-4) and titanium (only 6Al-4V) grades.
- **$/kg are commodity-spot and several are 2–5× low** for shop-purchased stock: PEEK **$100** (rod is
  $200–500/kg), Ti6Al4V wrought **$30** ($40–120/kg), 6061 **$5** ($6–12/kg small-lot). No mill-cert /
  cut-to-size / minimum-buy stock model, no drop/offal.

**M7 — Process coverage.** Costed set is 11 processes; **investment/sand casting, forging, wire-EDM,
extrusion, metal powder-bed (DMLS/SLM), progressive-die stamping, and assembly** are feasibility-only or
absent. For an automotive customer (Zoox), high-volume casting/forging/stamping economics are exactly the
make-vs-buy conversations that matter.

**M8 — Region model over-discounts offshore machine cost.** `machine_cost × region_labor` multiplies the
*whole* machine rate by the labor factor (CN=0.55). Machine **capital depreciation is global**; only the
labor component should scale. Offshore CNC is under-costed as a result.

**M9 — No live raw-material price feed / dated price provenance.** Prices are static constants. Enterprise
should-cost needs LME/index-linked material with a timestamp and a "priced as of" date.

**M10 — No queue/capacity realism beyond a stated pool, no freight/duty** for offshore make-vs-buy.

---

## NEEDS REAL-EXPERT VALIDATION — the packet for the Zoox Head of Manufacturing

I **cannot** self-certify the numbers. Here is exactly what to put in front of a real
manufacturing engineer and what to ask. The goal is not "is it perfect" — it's to **measure the
residual** and either earn a validated band or expose the true error.

**What to show (per part): the full itemized decision card** — geometry drivers, every line item with
its source string, the confidence band, and the make-vs-buy crossover. Ask them to quote/recall a real
number *before* seeing ours (avoid anchoring), then reveal ours.

**Part set (pick 6–8 with real Zoox quotes on file):**
| # | Part | Process to probe | Why |
|---|------|------------------|-----|
| 1 | ECU firewall mount (aluminum) | CNC 3-/5-axis @ qty 100 & 1,000 | Tests S1 (volume flatness), S3 (hull stock), S4 (features) |
| 2 | A turned/rotational part (aluminum or steel) | CNC turning | Whole turning cycle model is untested on a real quote |
| 3 | A true sheet bracket (≤3mm, 1–2 bends) | Sheet metal @ qty 50 & 500 | Tests S8 (nesting), cut/bend physics |
| 4 | Mazduino-type cover, redesigned for molding | Injection molding @ qty 10k, multi-cavity | Tests tooling $ + cavity model + cycle (S10) |
| 5 | A tolerance-heavy 5-axis bracket (±0.01, Ra0.8) | CNC 5-axis | Directly exposes S2 (no tolerance input) |
| 6 | A cast housing (Al) | Die/investment casting | Casting is barely costed (M7) |

**Exact questions to ask (these are the disproof tests):**
1. **Volume economics:** "Our machined unit cost is flat from 100 to 10,000 units. On your quotes, how
   much does part #1 drop 100→10k, and *why* (cycle, fixturing, automation)?" *(disproves S1)*
2. **Tolerance:** "If part #5's tolerance loosened from ±0.01 to ±0.1mm, how much cheaper? Our tool
   shows $0 change." *(disproves S2)*
3. **Stock:** "For part #1, what billet size do you actually buy, and what's the buy-to-fly / removed
   volume?" Compare to our hull-based 98 cm³. *(disproves S3)*
4. **Missing cost:** "For part #1 at qty 100, what do you charge for CAM programming + first article +
   anodize? We currently charge $0 for all three." *(quantifies S5/S6)*
5. **The band:** "Give us your quote for each part. We'll compute predicted/actual − 1. Is our ±40%
   real?" — this is the only way to replace the asserted band with a measured one. *(the M1 test)*
6. **Rates:** "Are the Midwest-profile rates ($52/hr labor, $95/$135 CNC, 0.8 util, 15% OH, 30% margin)
   in the right zip code for a US aero/auto job shop?" *(validates the calibration surface, S11)*
7. **Make-vs-buy:** "For part #4, at what annual volume does molding beat machining/printing in your
   experience? We compute ~a few hundred." *(validates the decision headline)*

**Success criterion:** load their real quotes into `groundtruth.py`, run held-out evaluation, and report
the measured per-process residual. If |median residual| and the 80% band come back within the advertised
±40–50%, the number is earned. If not (my expectation: machining and low-qty will be biased **low** because
of S3/S4/S5), the band widens and/or bias-correction factors are fit — either way it's finally **measured,
not asserted.**

---

## Bottom line for the panel
The cost engine is a **credible glass-box scaffold with an honest uncertainty story and a genuinely
substantive per-shop calibration layer** — that part is real and differentiated. But as a *cost engineer's
estimate* it is **naive on the two axes that decide real quotes (tolerance/finish and volume/learning)** and
**under-costs by construction** (hull stock, no features, no NRE/inspection/finishing, no support material).
The ±40% is not yet a claim — it's a placeholder that shop-rate variance alone already exceeds. The path to
"trusted" is not more code; it is **real ground truth (M1)** plus the tolerance (M2) and volume (M3) models,
validated by exactly the packet above. Ship it as "directional should-cost, glass-box, calibrate-to-your-shop"
— **not** as a validated number — until the residual is measured.
