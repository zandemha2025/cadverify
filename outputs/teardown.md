# CadVerify — Forensic Teardown (Cycle 1)

**What this is:** an honest, run-on-real-parts map of *exactly* what CadVerify outputs today,
where it is hollow, where it is wrong, and how that compares to what a manufacturing buyer
gets from CASTOR / 3D Spark / aPriori. Everything below is copied from real engine runs on the
repo's automotive STL parts. Nothing here is hand-waved or simulated.

---

## 0. Run provenance (so a skeptic can reproduce)

- **Engine:** `backend/src/...`, run via the canonical sequence used by `routes.py::validate_demo`
  (`analyze_geometry` → `GeometryContext.build` → `detect_all` → `run_universal_checks` →
  `score_process` over `pbase._REGISTRY` → `AnalysisResult` → `rank_processes`).
- **Python:** `backend/.venv/bin/python` (3.9), `cwd=repo root`, `sys.path.insert(0,'backend')`.
- **Parser:** every part is STL, loaded with `trimesh.load(path, force='mesh')`. cadquery absent (not needed).
- **Registry:** **21 processes registered, 21 analyzers present** — confirmed at runtime.
- **Parts:** 12 real automotive parts spanning enclosures, mounts, adapters, gaskets, plus two
  broken (non-watertight, zero-volume) parts. Source: `ecu_automotive_batch2.zip`.
- Harness + raw JSON: `scratchpad/teardown_run.py`, `scratchpad/results.json` (full per-part output).

---

## 1. Current-output INVENTORY — what the engine actually emits

For every part, `validate_demo` returns one JSON object with these fields (from `routes.py::_to_response`):

- `geometry`: vertex/face count, `volume_mm3`, `surface_area_mm2`, `bounding_box_mm`,
  `is_watertight`, `is_manifold`, `center_of_mass`, `units`.
- `universal_issues[]`: geometry-level DFM (NON_WATERTIGHT, DEGENERATE_FACES, NOT_SOLID_VOLUME,
  INCONSISTENT_NORMALS, MULTIPLE_BODIES) with severity + a generic fix suggestion.
- `segments[]` / `features[]`: heuristic feature detection (holes, cylinders, flats…).
- `process_scores[]`: for **each of 21 processes** → `score` (0–1), `verdict`
  (`pass`/`issues`/`fail`), `recommended_material`, `recommended_machine`,
  **`estimated_cost_factor`** (a dimensionless number), and per-process `issues[]`.
- `overall_verdict` and `best_process`.

That is the **entire** decision surface today: **a DFM checker + a process-suitability ranker +
one dimensionless "cost factor."** There is no dollar figure, no time, no quantity, no sourcing.

### 1a. A complete real example — "ECU Firewall Mount" (a clean, watertight plastic part)

```
geometry: vertices=789 faces=1586 volume=66790.4 mm3  surface_area=17512.9 mm2
          bbox=[160.0, 62.0, 32.6] mm  watertight=True  manifold=True  euler=-4  units=mm
universal_issues: []          overall_verdict: pass      best_process: sls
top process_scores:
  sls          score=1.0  pass    material=PA12 (Nylon 12)  machine=EOS P 396       cost_factor=13.36
  mjf          score=1.0  pass    material=PA12 (Nylon 12)  machine=HP Jet Fusion   cost_factor=12.02
  cnc_turning  score=1.0  pass    material=Inconel 718      machine=Haas ST-20      cost_factor=5.34   <-- see §3
  dlp          score=0.9  issues  material=Standard Resin   machine=Carbon M2       cost_factor=8.01
  dmls         score=0.9  issues  material=Ti6Al4V          machine=EOS M 400-4     cost_factor=133.58
  slm          score=0.9  issues  material=Ti6Al4V          machine=SLM 500         cost_factor=133.58
```

Read that as a buyer would: "Best process SLS, cost 13.36." **13.36 of what?** Nothing. It is
`0.20 × 66.8 cm³` rounded. It is not dollars, not hours, not a yield. And the #3 "pass" is to
**turn this flat bracket from Inconel 718** — an aerospace nickel superalloy on a lathe. (§3.)

### 1b. Per-part result matrix (all 12 real parts, copied from the run)

| Part (class) | vol mm³ | watertight | overall | best_process | best material / machine | cost_factor |
|---|---|---|---|---|---|---|
| MAF Sensor Adapter (adapter, **broken**) | **0.0** | **False** | fail | **sls (score 1.0, pass)** | PA12 / EOS P 396 | **0.2** |
| ECU Firewall Mount (mount, plastic) | 66790 | True | pass | sls | PA12 / EOS P 396 | 13.36 |
| E46 ECU Box / Plug (enclosure) | 9263 | True | issues | dlp | Std Resin / Carbon M2 | 1.11 |
| Throttle Body Adapter (adapter) | 2812 | True | issues | sla | Std Resin / Form 4 | 0.42 |
| Throttle Body Gasket (gasket, 0.6mm) | 334 | True | issues | dlp | Std Resin / Carbon M2 | 0.12 |
| Bosch MAP Sensor Adapter (adapter) | 3314 | True | issues | dlp | Std Resin / Carbon M2 | 0.4 |
| Mazduino Bottom Case (enclosure) | 27984 | True | pass | mjf | PA12 / HP 5200 | 5.04 |
| Macchina M2 Case Top (enclosure) | 7423 | True | issues | dlp | Std Resin / Carbon M2 | 0.89 |
| Miata MS3 Bottom Bracket (mount) | 37433 | True | pass | **wire_edm (score 1.0, pass)** | **None** / Sodick ALC600G | 18.72 |
| Battery Holddown (mount) | 65715 | True | issues | dlp | Std Resin / Carbon M2 | 7.89 |
| FD3S→GM Throttle Body (adapter) | 248714 | True | issues | **cnc_turning** | **Inconel 718** / Haas ST-20 | 19.9 |
| Upper Intake Manifold Gasket (gasket, **broken**) | **0.0** | **False** | fail | **wire_edm (score 0.9)** | **None** / Sodick ALC600G | 0.5 |

Every `cost_factor` in that column is `cost_per_cm³[process] × max(volume_cm³, 1.0)` — dimensionless.

---

## 2. Where it is HOLLOW — the toy cost model and the missing decision layer

### 2a. The actual cost code path (the whole thing)

`backend/src/matcher/profile_matcher.py`, lines 97–134:

```python
def _estimate_cost_factor(geometry, process) -> float:
    volume_cm3 = geometry.volume / 1000          # mm3 -> cm3
    cost_per_cm3 = {                              # "very approximate" hardcoded multipliers
        ProcessType.FDM: 0.05, ProcessType.SLS: 0.20, ProcessType.CNC_TURNING: 0.08,
        ProcessType.DMLS: 2.0, ProcessType.INJECTION_MOLDING: 0.02, ...
    }
    base_cost = cost_per_cm3.get(process, 0.1)
    return round(base_cost * max(volume_cm3, 1.0), 2)
```

That is the **entire** cost engine. Confirmed at runtime: with `volume=0.0`, it returns
`sls=0.2, cnc_turning=0.08, dmls=2.0` — because `max(volume_cm3, 1.0)` silently floors volume to
1 cm³. The number is:

- **Not money.** No currency, no rate card, no quote.
- **Volume-only.** Two drivers exist: a per-process constant and the part's bounding volume.
  Nothing else moves the number.
- **Driverless.** No machine/cycle time, no material *mass × $/kg* (material `cost_per_kg`
  exists in the profile DB but is never used here), no setup, no labor, no finishing, no region,
  **no lot size.** The docstring literally says "real costs depend on material, machine time,
  post-processing, and quantity" — none of which it computes.

### 2b. The decision layer a buyer needs — and what exists today

| Decision-layer output a buyer expects | In CadVerify today? | Evidence |
|---|---|---|
| Real **cost in $** | **No** | only `estimated_cost_factor` (dimensionless) |
| **Cost breakdown / drivers** (machine time, material mass×rate, setup, labor, region, lot) | **No** | single number from volume × constant |
| **Lead time** | **No** | field does not exist in `ProcessScore`/response |
| **Quantity / batch economics** (per-unit vs qty, breakeven) | **No** | cost is independent of quantity; molding tooling never amortized |
| **Process crossover** (e.g. print → mold at N units) | **No** | no qty axis to cross over |
| **Make-vs-buy** | **No** | no buy-side quote, no comparison |
| **Supplier pricing / sourcing** | **No** | no supplier model anywhere |
| **CO2 / sustainability** | **No** | not computed |

The injection-molding case makes the hollowness vivid: `cost_per_cm³[INJECTION_MOLDING] = 0.02`,
so molding always looks cheapest **per part with no tooling amortization and no quantity** — the
single most important driver in real molding economics (a $20k mold over N parts) is absent.

---

## 3. Where it is WRONG on real parts — evidence, not assertion

### 3.1 Confident "pass" + fabricated cost on broken, zero-volume geometry

**MAF Sensor Adapter** loads as `volume=0.0 mm³, watertight=False, manifold=False, euler=-18`.
The universal layer correctly flags it:

```
universal_issues:
  NON_WATERTIGHT (error)  "Mesh is not watertight — has 0 boundary edges..."
  NOT_SOLID_VOLUME (warning)
overall_verdict: fail
```

…but the **per-process layer contradicts the overall verdict** and emits confident passes with a
cost:

```
best_process: sls
  sls          score=1.0  pass   material=PA12 (Nylon 12)  machine=EOS P 396   cost_factor=0.2   issues=0
  mjf          score=1.0  pass   material=PA12 (Nylon 12)  machine=HP 5200     cost_factor=0.18
  cnc_turning  score=1.0  pass   material=Inconel 718      machine=Haas ST-20  cost_factor=0.08  issues=0
```

A buyer sees `overall_verdict: fail` next to `best_process: sls, score 1.00, pass, cost 0.2`. The
geometry has **no volume**, yet the engine reports a manufacturable process and a price. This is
the single most credibility-destroying output: a fabricated cost on a part the engine itself
can't measure. The **Upper Intake Manifold Gasket** repeats it (`vol=0.0`, non-watertight →
`overall_verdict: fail` but `best_process: wire_edm, cost_factor 0.5`).

Side note — the engine's own diagnostic is self-contradictory: it declares the mesh
"not watertight" while reporting "**0 boundary edges**." Non-watertightness here comes from
non-manifold/inverted faces, but the message points the user at holes that don't exist.

### 3.2 Inconel 718 (aerospace superalloy) recommended for plastic parts

Root cause, confirmed at runtime: `score_process` sets
`recommended_material = materials[0].name` — the **first item in the process's material list**,
with **zero** part-fit logic. For CNC the first item is Inconel 718:

```
cnc_turning  -> material='Inconel 718'  machine='Haas ST-20'   (12 materials available, positional pick)
cnc_3axis    -> material='Inconel 718'  machine='Haas VF-2'
```

So **every** part for which a CNC process scores well is recommended in Inconel 718:
the **plastic ECU Firewall Mount** (cnc_turning, Inconel 718, "pass"), the E46 ECU box, the MAF
adapter, the battery holddown, and the FD3S throttle-body adapter (`best_process: cnc_turning,
Inconel 718`). There is no logic that says "this is a 3D-printed plastic bracket → suggest a
plastic or aluminum." Material selection is positional, not physical.

Compounding it: **cnc_turning** (a lathe process for *rotational* parts) is recommended for flat
brackets and boxes; **wire_edm** (which cuts 2D profiles through conductive plate) is the
`best_process` for the Miata bracket and the broken manifold gasket — with `material=None`. And
the **0.6 mm-thick Throttle Body Gasket** is offered in **Ti6Al4V DMLS/SLM** (`cost_factor 2.0`),
a titanium laser-melt for a part that in reality is die-cut/laser-cut elastomer or shim stock.

### 3.3 Numerical warnings (divide-by-zero / overflow) on real, normal parts

Every part triggers `RuntimeWarning: divide by zero / overflow / invalid value encountered in
matmul` at **`context.py:100`** and, for parts with curved features, repeatedly at
**`features/cylinders.py:84, 94, 107`**. These fire even on clean watertight parts (e.g. the ECU
Firewall Mount: 3 warnings). On the high-poly FD3S adapter (223,792 faces) the cylinder-fitting
warnings repeat **hundreds** of times. The broken manifold gasket adds
`triangles.py:302/550/555: invalid value encountered in divide/subtract`. The math runs on
degenerate normals without guarding, so the feature/curvature analysis is operating on NaN/Inf
intermediates — silent except for the warning spam.

---

## 4. Parity / gap map vs CASTOR, 3D Spark, aPriori

CadVerify column = **observed this run**. Competitor columns = their **public positioning** as
provided in the brief (I did not run their tools; stated as reference, not measured).

| Capability (what a buyer evaluates) | **CadVerify (today, observed)** | CASTOR (AM-decision, dead) | 3D Spark (alive) | aPriori (incumbent) |
|---|---|---|---|---|
| Geometry/DFM manufacturability checks | **Yes** — 21 processes, watertight/normals/degenerate/multi-body | Yes (AM-focused DFM) | Yes | Yes (deep process models) |
| Process breadth | **Yes** — 21 process types scored | Additive-first + compare to traditional | 15+ technologies, process-agnostic | Broad: machining/casting/sheet/molding |
| **Real cost in $** | **No** — dimensionless `cost_factor` only | **Yes** — per-part cost | **Yes** — costing | **Yes** — should-cost in currency |
| **Cost explainability / drivers** | **No** — one number = const × volume | Partial (AM vs traditional compare) | **Yes** — transparent/explainable | Yes — driver-level, but heavy/training-heavy |
| **Lead time** | **No** | **Yes** — lead-time comparison | **Yes** | Partial (via cycle time) |
| **Quantity / batch economics + crossover** | **No** — cost is qty-independent | **Yes** — what to print at volume | **Yes** — break-even qty | **Yes** — cost vs volume |
| **Make-vs-buy** | **No** | **Yes** — print vs traditional | Partial (+ sourcing) | **Yes** — should-cost vs quote |
| **Supplier pricing / sourcing** | **No** | No (decision, not marketplace) | **Yes** — supplier pricing | Partial (cost libraries, not live suppliers) |
| **CO2 / sustainability** | **No** | Partial | **Yes** — CO2 | Partial |
| **Regional cost libraries** | **No** | No | Some | **Yes** — 20yr libraries = the moat |
| **Robustness on broken/zero-volume CAD** | **No** — confident "pass" + fabricated cost on vol=0, non-watertight | Handles/repairs | Handles | Handles |
| **Sane material/process matching** | **No** — Inconel 718 for plastic; Ti DMLS for a gasket; turning/EDM for printed brackets | AM-appropriate | Yes | Yes |
| **Portfolio / batch scale (1000s of parts)** | **No** — single-file API | **Yes** — thousands at once | **Yes** — batch | **Yes** |
| **CAD format breadth** | STL only (STEP stubbed; cadquery absent) | STEP/native | STEP/native | STEP/native |
| **Primary audience served by the output** | DFM/geometry, **not decision-grade** | Design/AM engineers | Design engineers | Cost engineers |

**One-line read:** CadVerify today is a **competent process-agnostic DFM checker with a fake price
tag stapled on.** The DFM/feature/multi-process-ranking spine is real and broad (its genuine
asset, and the closest thing to 3D Spark's "process-agnostic, design-engineer-facing" framing).
But the **entire decision layer that makes 3D Spark / CASTOR / aPriori credible to a buyer — real
$, drivers, lead time, quantity/crossover, make-vs-buy, sourcing — is absent**, and the one
number it does emit is dimensionless and is fabricated on broken geometry.

---

## 5. Honest summary of works / hollow / wrong

**Works (real, today):**
- End-to-end run on real automotive STL via trimesh; 21/21 analyzers execute.
- Geometry extraction (volume, area, bbox, watertight/manifold, euler) is correct on clean parts.
- Universal DFM gating: NON_WATERTIGHT/DEGENERATE/NOT_SOLID_VOLUME are detected and set
  `overall_verdict=fail` for the two broken parts.
- Broad multi-process suitability ranking with per-process DFM issues.

**Hollow (claimed-ish but empty):**
- "Cost" = `cost_per_cm³[process] × max(volume_cm³,1)` — dimensionless, volume-only, driverless.
- No lead time, no quantity/batch economics, no crossover, no make-vs-buy, no supplier pricing,
  no CO2 — none of the decision-layer fields exist.

**Wrong (a buyer catches instantly):**
- Confident per-process **"pass" + fabricated cost** on zero-volume / non-watertight parts (MAF
  adapter, manifold gasket), contradicting the engine's own `overall_verdict: fail`.
- **Inconel 718** (and Ti6Al4V) recommended for **plastic** parts because material = `materials[0]`
  (positional, no part-fit logic); CNC-turning / wire-EDM proposed for non-rotational printed
  brackets; titanium DMLS for a 0.6 mm gasket.
- **Divide-by-zero / overflow** RuntimeWarnings on degenerate normals at `context.py:100` and
  `features/cylinders.py:84/94/107` (hundreds of times on high-poly parts), plus
  `triangles.py:302/550/555` on the broken gasket.

**Acceptance:** on the real parts above, a reader can see exactly what runs, exactly what is
fabricated, and exactly which decision-layer capabilities are missing relative to all three
competitors — with the real outputs shown inline.
