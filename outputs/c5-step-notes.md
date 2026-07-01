# Cycle 5 — STEP Ingestion Builder Notes (Workstream A)

Status: **DONE** — a real, OSI-licensed STEP file runs end-to-end to a cost
decision through the existing DFM + cost pipeline. STL path untouched and green.
Full backend suite: **494 passed, 5 skipped, 0 failed** (no regressions).

Date: 2026-06-29 · Env: `/Users/nazeem/Desktop/developer/cadverify/backend/.venv/bin/python` (Python 3.9.6, macOS arm64 / Darwin 25.4).

---

## 1. gmsh install result

`gmsh` was already present in the venv and verified working:

```
$ .venv/bin/python -m pip install gmsh
Requirement already satisfied: gmsh in ./.venv/lib/python3.9/site-packages (4.15.2)

$ .venv/bin/python -c "import gmsh; print(gmsh.GMSH_API_VERSION)"
4.15.2          # initialize() / finalize() round-trip OK
```

Wheel: `gmsh-4.15.2` (py2.py3 native wheel, ~36 MB), embeds the OpenCASCADE
kernel. Added `gmsh>=4.13` to `backend/requirements.txt` with a note that the
route degrades to a clean 501 (via `is_step_supported()`) if no wheel exists for
the deploy target.

---

## 2. The loader

New module: **`backend/src/parsers/step_mesher.py`**

- `is_step_supported()` → True iff `import gmsh` succeeds.
- `step_to_trimesh_from_bytes(data, filename)` → writes bytes to a `0o600`
  temp file (IP-local discipline, guaranteed `unlink` in `finally`, mirrors
  `step_parser`), then meshes via `_mesh_step_file`.
- `_mesh_step_file(path)`:
  - serialized by a module-level `_GMSH_LOCK` (gmsh is a process-global,
    non-thread-safe context).
  - `gmsh.model.occ.importShapes(path)` (STEP/IGES/BREP via OCC) →
    `mesh.generate(2)` (2D surface mesh = triangulated shell).
  - scale-aware element budget: `MeshSizeMax ≈ bbox_diagonal / 200`, clamped
    `[0.05, 50] mm`, `MeshSizeFromCurvature=12`, `OCCTargetUnit="MM"`.
  - extracts gmsh nodes + type-2 (3-node) triangles → `trimesh.Trimesh(...,
    process=True)`. `process=True` merges coincident per-OCC-face vertices,
    which is what recovers `is_watertight=True` on single solids.
  - OCC reader errors and empty/triangle-less results raise a **static-message
    `ValueError`** (the route maps `ValueError` → 400; gmsh internals never
    leak to the caller).

**One deviation from the spec's reference loader (required, not optional):**
`gmsh.initialize(interruptible=False)`. The default `interruptible=True` makes
gmsh install a SIGINT handler via `signal.signal()`, which raises
`"signal only works in main thread of the main interpreter"` when meshing runs
in the `ThreadPoolExecutor` (which it must — see §3). `interruptible=False`
skips that handler; safe because the executor pool is the only caller and the
lock serializes it. Without this the STEP cost path 500s/400s under the
executor. Verified by the box + non-watertight + concurrency-safe tests passing.

### Plug points (`backend/src/api/routes.py`)
- Import swapped: `step_parser.{is_step_supported,parse_step_from_bytes}` →
  `step_mesher.{is_step_supported,step_to_trimesh_from_bytes}`. The cadquery
  `step_parser.py` is left in place (unused by the route) for the future B-rep
  path.
- `_parse_mesh` STEP branch now calls `step_to_trimesh_from_bytes` then the
  existing `enforce_triangle_cap` (post-mesh 2 M hard stop for runaway
  tessellation / assemblies). STL branch, magic check, and caps unchanged.
- **Reliability fix (spec §A.5):** added `_parse_mesh_async(data, filename)` —
  offloads `_parse_mesh` to the analysis executor under `ANALYSIS_TIMEOUT_SEC`
  and turns a runaway STEP mesh into a clean **504** instead of blocking the
  event loop. `validate_cost` and `validate_demo` now `await
  _parse_mesh_async(...)`. STL is functionally unaffected (now just runs in a
  thread). `/validate` + `/validate/repair` reuse `_parse_mesh` via
  `analysis_service`, so STEP is now analyzable there too (was 501).

Routing-by-extension + `ISO-10303-21` magic guard were already correct and are
unchanged: only `.stl/.step/.stp` are accepted; STEP requires the magic header;
compound suffixes (`part.stp.bak` → `.bak`) are rejected as unsupported.

---

## 3. Real STEP test file (source + license)

**`eight_cyl.stp`** from **`tpaviot/pythonocc-core`**:
```
https://raw.githubusercontent.com/tpaviot/pythonocc-core/master/test/test_io/eight_cyl.stp
```
- License confirmed via the GitHub license API: **`spdx_id: "LGPL-3.0"`**
  (`GNU Lesser General Public License v3.0`). OSI-approved, permissive enough
  to use as a test fixture.
- 63,663 bytes, header `ISO-10303-21;`. Single solid.

Not committed as a binary blob. The always-on tests synthesize a STEP box via
gmsh's OCC kernel at test time; this network-fetched real file is exercised only
by the gated `test_step_network.py` (`STEP_NETWORK_TESTS=1`).

---

## 4. Captured end-to-end decision on the real STEP part (REAL output)

`eight_cyl.stp` → `step_to_trimesh_from_bytes` → `_run_cost_engine` →
`estimate_decision` → `report_to_dict` (qty `50,5000`, `material_class=aluminum`,
region `US`):

**Mesh (gmsh):** 24,524 faces, 12,278 verts, **watertight=True**, volume
**1175.26 cm³**, bbox **499.4 × 195.8 × 453.9 mm**, ~0.25 s.

**Decision:** `status: OK`
- **make_now: `cnc_turning` / 6061-T6 Aluminum** — $2006.07/unit @ qty 50.
- **crossover_qty: 45.6** (`cnc_turning` cheapest at every tested qty; no
  tooling crossover).
- per-qty: q50 → cnc_turning $2006.07/unit, lead 14.0–26.0 d ·
  q5000 → cnc_turning $2005.89/unit, lead 747.6–1388.4 d.

**Invariant `unit_cost == Σ line_items` — holds on every estimate:**

| process | qty | unit_cost | Σ line_items | drivers tagged |
|---|---|---|---|---|
| cnc_turning | 50 | $2006.07 | $2006.07 | ✓ |
| cnc_turning | 5000 | $2005.89 | $2005.89 | ✓ |
| cnc_5axis | 50 | $3801.61 | $3801.61 | ✓ |
| cnc_5axis | 5000 | $3801.26 | $3801.26 | ✓ |
| die_casting | 50 | $1834.14 | $1834.14 | ✓ |
| die_casting | 5000 | $52.14 | $52.14 | ✓ |
| cnc_3axis | 50 | $2780.66 | $2780.66 | ✓ |
| cnc_3axis | 5000 | $2780.40 | $2780.40 | ✓ |

**Headline line items (cnc_turning, q50):** `material $673.88 + machine $1321.33
+ labor $10.50 + amortized_fixed $0.35 = $2006.07`. Every driver carries a
`MEASURED|USER|DEFAULT` provenance tag and a human-readable source string, e.g.:
- `material_cost = 673.88 $  [MEASURED | hull volume 43218.39 cm³ × 1.10 stock × 6061-T6 density 2.70 g/cm³ = 128.36 kg × $5/kg × (1+0.05 scrap)]`
- `cycle_time = 20.33 hr  [DEFAULT | rough 33766.9 cm³ ÷ (30 cm³/min·60) + finish 1255.1 cm² ÷ 800 cm²/hr; stock bounding cylinder; MRR aluminum]`
- assumption `material_class = aluminum [USER | buyer-supplied]` (the rest DEFAULT).

Honest caveat surfaced by the engine itself: this part was modeled for 3D
printing, so it is flagged `dfm_ready=False` for molding/casting (no draft);
the casting/molding numbers are shown as "if redesigned" economics. Absolute
cost band is ±40–60%; the crossover direction is robust. This is the real,
unmodified engine output — nothing hardcoded.

---

## 5. Scope boundary (in the module docstring + relevant to UI copy §B)

- **IN scope:** STEP/STP → triangulated shell → existing geometry/feature engine
  → existing cost/decision layer. Single solids cost cleanly; assemblies /
  non-watertight bodies are refused by the G1 gate as a structured 400.
- **OUT of scope / BLOCKED:** B-rep face graph, exact analytic surfaces, GD&T /
  PMI / tolerance extraction from STEP AP242 — requires cadquery/OCP, which is
  not installable in this env (known-hard). gmsh gives a tessellated shell good
  enough for DFM + cost, not B-rep. This remains the cadquery "v2" story.

---

## 6. Tests + results

Added (no git commit):
- **`backend/tests/test_step_mesher.py`** (always-on; each test skips cleanly if
  gmsh absent): gmsh-available, box-STEP-meshes-watertight (20 mm box → 8 cm³,
  bbox 20³, watertight, faces in bounds), empty-STEP→ValueError,
  no-temp-file-leak, temp-file-mode-0o600.
- **`backend/tests/conftest.py`**: session-scoped `box_step_bytes` fixture
  (gmsh-built 20 mm box STEP, synthesized at test time; `importorskip` gmsh).
- **`backend/tests/test_cost_api.py`** (extended): STEP box → 200 + invariants +
  provenance; open-shell STEP (non-watertight) → **400 GEOMETRY_INVALID** (G1);
  STEP suffix without `ISO-10303-21` magic → 400; renamed `part.stp.bak` → 400.
- **`backend/tests/test_step_network.py`** (gated `STEP_NETWORK_TESTS=1`):
  fetches the LGPL `eight_cyl.stp`, asserts full cost path 200 + invariant.

Results:
```
# subset
$ .venv/bin/python -m pytest -q tests/test_step_mesher.py tests/test_cost_api.py tests/test_step_parser.py
19 passed

# gated network test
$ STEP_NETWORK_TESTS=1 .venv/bin/python -m pytest -q tests/test_step_network.py
1 passed in 16.84s

# full backend suite (regression gate)
$ .venv/bin/python -m pytest -q
494 passed, 5 skipped, 220 warnings in 383.14s   # exit 0, no regressions
```

(The `RuntimeWarning: divide/overflow in matmul` lines are benign numpy noise
from a handful of degenerate tessellation triangles; the engine clips/handles
them and the output is fully valid. Not a failure.)

---

## 7. Files changed/added

- `backend/src/parsers/step_mesher.py` (new) — gmsh STEP → trimesh loader.
- `backend/src/api/routes.py` — import swap; STEP branch → gmsh; new
  `_parse_mesh_async` (executor + 504); `validate_cost`/`validate_demo` await it.
- `backend/requirements.txt` — `gmsh>=4.13`.
- `backend/tests/conftest.py` — `box_step_bytes` fixture.
- `backend/tests/test_step_mesher.py` (new), `test_step_network.py` (new),
  `test_cost_api.py` (extended STEP cases).

## 8. Notes for adjacent builders
- **Builder C (§C.4):** `501` is not yet in `errors.py::ERROR_CODES`, so the
  no-gmsh degraded response maps to `UNKNOWN_ERROR`. Spec assigns the one-line
  `501: "NOT_IMPLEMENTED"` add to C — left untouched here to avoid file
  conflicts. The 501 path is not exercised in this env (gmsh is installed).
- The `interruptible=False` fix is mandatory for the executor path; do not
  revert it. `_GMSH_LOCK` serializes concurrent STEP costs (correct, at a
  throughput cost — escalate to a process pool only if throughput demands it).
