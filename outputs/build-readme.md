# CadVerify V0 Decision Layer — Build & Run README

Explainable should-cost + lead-time + quantity-crossover + make-vs-buy on top of
the existing DFM engine. New, self-contained package: `backend/src/costing/`.
Nothing in the engine's hot path is changed; the layer is read-only.

## 0. Prerequisites (already true in this repo)
- Python venv: `/Users/nazeem/Desktop/developer/cadverify/backend/.venv/bin/python` (3.9).
- `trimesh` installed; `cadquery` NOT needed (every real part is STL).
- Real parts (37+ automotive STL) extracted at:
  `/private/tmp/claude-501/-Users-nazeem-Desktop-developer-cadverify/3182c9c6-e59b-4394-a584-d9c4cd4ce0dc/scratchpad/parts`
  (re-extract `ecu_automotive_batch2.zip` to a temp dir if missing).
- Engine imports are `from src...`, so run with **cwd = `backend`** (or put `./backend` on `sys.path`).

## 1. Run the CLI on a real part (the demo surface)

```bash
cd /Users/nazeem/Desktop/developer/cadverify/backend
PARTS=/private/tmp/claude-501/-Users-nazeem-Desktop-developer-cadverify/3182c9c6-e59b-4394-a584-d9c4cd4ce0dc/scratchpad/parts
PY=/Users/nazeem/Desktop/developer/cadverify/backend/.venv/bin/python

# Demo part A — ECU Firewall Mount (flat polymer bracket)
$PY -W ignore -m src.costing.cli \
  "$PARTS/1090523_b8dd5bfe-0a71-405c-906b-aa8dc51a6c30_EK_0BD1_ECU_Firewall_mount.stl" \
  --qty 50,5000 --quiet

# Demo part B — Throttle Body Adapter (rotational; turning becomes eligible)
$PY -W ignore -m src.costing.cli \
  "$PARTS/printables_122552_ThrottleBodyAdapter.stl" \
  --qty 100,10000 --quiet

# Broken geometry — MAF Sensor Adapter (vol=0, non-watertight) -> G1 refuses to cost
$PY -W ignore -m src.costing.cli \
  "$PARTS/655044_0b409a7e-0e9d-424a-81ae-5261cd5f4181_MITSUBISHI_LANCER_1993-MAF_Sensor_Adapter_for_High_Flow_Air_filetr.stl" \
  --quiet
```

Each run prints a decision card and writes a JSON sidecar next to the part
(`<part>.decision.json`) or to `--json <path>`. `--quiet` suppresses engine
RuntimeWarnings. Exit code is 0 for both OK and GEOMETRY_INVALID (it prints the
invalid card, does not crash). Zero network calls; wall-clock < 10 s on these meshes.

## 2. CLI flags
```
python -m src.costing.cli <part.stl>
    --qty 50,5000                 # comma list of quantities (DEFAULT 50,5000)
    --material-class polymer      # polymer|aluminum|steel|stainless|titanium (DEFAULT polymer -> USER when set)
    --region US                   # US|EU|MX|CN|IN|SA (multiplier table)
    --labor-rate 35               # $/hr override (-> USER provenance)
    --margin 0.0                  # should-cost by default
    --set machine_rate.SLS=25     # any per-process rate, repeatable
    --tooling INJECTION_MOLDING=50000   # flat tooling override, repeatable
    --strict-dfm                  # drop verdict=='fail' processes (literal spec §5.3)
    --json out.json               # JSON sidecar path
```

Overridden values become **USER** provenance and show alongside the DEFAULT in
the report. Example — bump injection-molding tooling and watch the crossover move:
```bash
$PY -W ignore -m src.costing.cli "$PARTS/1090523_..._ECU_Firewall_mount.stl" \
    --qty 50,5000 --tooling INJECTION_MOLDING=60000 --quiet
# crossover moves right (more units needed to justify the larger tool) — monotone, explainable.
```

## 3. Use from Python (the public entry)
```python
import sys; sys.path.insert(0, "backend")     # or run with cwd=backend
import src.analysis.processes                  # populate the 21-analyzer registry
import trimesh
from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.matcher.profile_matcher import rank_processes, score_process
from src.analysis.processes.base import get_analyzer
from src.analysis.processes import base as pbase
from src.analysis.models import AnalysisResult

mesh = trimesh.load(path, force="mesh")
geometry = analyze_geometry(mesh)
ctx = GeometryContext.build(mesh, geometry); ctx.features = detect_features(mesh)
universal = run_universal_checks(mesh)
scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
          for p in pbase._REGISTRY if get_analyzer(p)]
result = AnalysisResult(filename="part.stl", file_type="stl", geometry=geometry,
                        segments=ctx.segments, universal_issues=universal,
                        process_scores=scores)
rank_processes(result)

# ── decision layer ──
from src.costing import estimate_decision, EstimateOptions, render_text, report_to_dict
report = estimate_decision(result, mesh, ctx.features,
                           EstimateOptions(quantities=[50, 5000], material_class="polymer"))
print(render_text(report))          # decision card
sidecar = report_to_dict(report)    # JSON-serializable dict
```

## 4. Run the tests (gates G1–G7 + model invariants)
```bash
cd /Users/nazeem/Desktop/developer/cadverify/backend
CADVERIFY_PARTS_DIR=/private/tmp/claude-501/-Users-nazeem-Desktop-developer-cadverify/3182c9c6-e59b-4394-a584-d9c4cd4ce0dc/scratchpad/parts \
  /Users/nazeem/Desktop/developer/cadverify/backend/.venv/bin/python -W ignore \
  -m pytest tests/test_costing_model.py tests/test_costing_gates.py -q
# -> 17 passed
```
- `test_costing_model.py` — procedural meshes, always runs (Σ=total, monotone sensitivity, crossover math, lead-time monotonicity).
- `test_costing_gates.py` — real parts; G1 scans all 105 STL (~2–3 min). Skips cleanly if `CADVERIFY_PARTS_DIR` is absent.

## 5. What V0 deliberately does NOT do (honesty ledger)
- No supplier pricing / live quotes / network egress (V2 — CAD stays local).
- No CO₂, no PDF, no DB persistence, no regional cost *libraries* (one default rate card + region multiplier table only).
- Costs a bounded shortlist (FDM/SLA/DLP/SLS/MJF/CNC-3/5/turning/injection-molding/die-casting); all other feasible processes are listed feasibility-only (no number).
- Absolute dollars are ±40–60% (stated). The **decision** (crossover qty + make-vs-buy direction) is what V0 stands behind — it depends on the fixed-vs-variable shape driven by *your* rates, not on absolute cost precision.
- The legacy `profile_matcher._estimate_cost_factor` toy is left untouched and never surfaced.

## 6. API stub (OUT of V0 — documented, unrouted)
A future `POST /validate/cost` would call `estimate_decision(result, mesh, features, options)`
after the existing analysis and merge `report_to_dict(report)` into the response.
Not wired in V0 (per spec §11).
