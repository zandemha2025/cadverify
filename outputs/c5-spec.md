# CadVerify Cycle 5 — Architecture Spec (productionization)

Author: Cycle 5 Architect · Date: 2026-06-29
Scope: three independently-shippable workstreams — **(A) STEP ingestion**, **(B) frontend cost-decision surface**, **(C) observability/reliability hardening**. Each section is a build-ready contract: exact files, signatures, plug points, test files, and acceptance criteria. Three builders can take A/B/C in parallel with **zero open decisions**.

Positioning is unchanged: glass-box, design-engineer-facing manufacturing cost+decision tool. CAD is IP-local (parsed, costed, discarded in-process; zero network egress in the serve path). The legacy toy `estimated_cost_factor` is never surfaced in the cost layer.

---

## 0. Pre-flight: what was actually verified for this spec (real runs, not claims)

All of the following were executed in this environment against the project venv (`/Users/nazeem/Desktop/developer/cadverify/backend/.venv/bin/python`, Python **3.9.6**, macOS **arm64** / Darwin 25.4):

| Check | Result |
|---|---|
| `pip install gmsh` | **OK** — native wheel `gmsh-4.15.2-py2.py3-none-macosx_12_0_arm64.whl` (36.4 MB), installed clean. |
| `import gmsh` + runtime | **OK** — `gmsh.GMSH_API_VERSION == "4.15.2"`. |
| gmsh OCC kernel reads STEP | **OK** — `gmsh.model.occ.importShapes(path)` + `mesh.generate(2)` on real STEP files. |
| STEP → `trimesh.Trimesh` (single-solid) | **OK** — `eight_cyl.stp`: 6738 faces, **watertight=True**, vol 1167.35 cm³, bbox 499×196×454 mm, 1.4 s. |
| STEP → `trimesh.Trimesh` (single-solid #2) | **OK** — `face_recognition_sample_part.stp`: 38462 faces, watertight=True, vol 3063 cm³, 0.21 s. |
| Full path STEP→engine→cost | **OK** — `estimate_decision` returns `status:"OK"`, headline make-now, crossover qty, per-qty $/unit + lead time. |
| Invariant `unit_cost == Σ(line_items)` on STEP-derived cost | **OK** — verified True on cnc_3axis / cnc_5axis / cnc_turning / die_casting line items. |
| G1 gate on STEP-derived mesh | **OK** — watertight + positive volume → passes; multi-body assembly → non-watertight → G1 refuses (see cautionary case). |
| gmsh `Geometry.OCCTargetUnit="MM"` option | **OK** — settable; parts import at mm scale (consistent with OCC default). |

**Cautionary case (drives the caps/timeout requirements in A & C):** the classic AS1 **assembly** (`as1_pe_203.stp`, multi-body, 5 m across) meshed to **8,500,098 faces in 76.7 s** and came out **non-watertight** (separate bodies). This single file simultaneously (1) blows the 2 M triangle cap, (2) exceeds the 60 s analysis timeout, and (3) fails G1. The spec below bounds all three. **Assemblies are out of scope for cost** — we cost single solids; assemblies are refused cleanly.

> Honesty note: gmsh delivers **STEP → mesh → DFM + cost**, i.e. a triangulated shell good enough for the existing geometry/feature/cost engine. It does **NOT** give B-rep faces, exact analytic surfaces, or GD&T/PMI extraction. Full B-rep + tolerance reads remain the cadquery/OCP "v2" story and are **out of scope / BLOCKED** (cadquery/OCP not installable in this env — known-hard). This is stated explicitly to the user in the UI copy (§B) and the spec (§A.7).

---

# A. STEP INGESTION (builder A)

## A.1 Approach
Add a **gmsh-based STEP→`trimesh.Trimesh` parser** and route `.step` / `.stp` uploads through it inside `_parse_mesh`. gmsh embeds the OpenCASCADE kernel, reads STEP/IGES/BREP via `model.occ.importShapes`, and tessellates to a triangle shell we wrap as `trimesh.Trimesh`. This reuses 100% of the existing engine + cost path (which only needs a `trimesh.Trimesh`). STL handling is untouched.

The existing `src/parsers/step_parser.py` (cadquery/OCP, returns `is_step_supported()==False` here → 501) is **left in place but no longer used by the route**. We add a new module so the cadquery path can return later for B-rep without conflict.

## A.2 New module — `backend/src/parsers/step_mesher.py`

```python
"""STEP/STP -> trimesh.Trimesh via gmsh's embedded OpenCASCADE kernel.

This is the STEP->mesh path for DFM + cost. It produces a triangulated shell
(not B-rep / GD&T). gmsh uses a single PROCESS-GLOBAL context and is NOT
thread-safe, so every entry into the gmsh critical section is serialized by
_GMSH_LOCK. Meshing is CPU-bound and can be slow on assemblies; callers MUST
run this under the analysis executor + timeout (see routes.py changes A.5).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np
import trimesh

_HAS_GMSH = False
try:
    import gmsh  # noqa: F401
    _HAS_GMSH = True
except ImportError:
    pass

# gmsh is process-global / not thread-safe; serialize across worker threads.
_GMSH_LOCK = threading.Lock()

# Tessellation tuning (mm). Curvature-adaptive, with a face budget guard.
_CURVATURE_PTS = 12.0        # min facets around a full circle
_TARGET_DIAG_SEGMENTS = 200  # MeshSizeMax ~ bbox_diagonal / this
_MIN_SIZE_MM = 0.05          # floor so tiny parts still tessellate
_MAX_SIZE_MM = 50.0          # ceiling so huge parts don't vanish


def is_step_supported() -> bool:
    """True iff the gmsh STEP path is importable."""
    return _HAS_GMSH


def step_to_trimesh_from_bytes(data: bytes, filename: str = "upload.step") -> trimesh.Trimesh:
    """Parse STEP bytes -> watertight-where-possible trimesh.Trimesh.

    Mirrors step_parser's temp-file discipline (0o600, guaranteed unlink).
    Raises ValueError with a SAFE, static-ish message on any parse/mesh failure
    (the route maps ValueError -> 400). Never leaks gmsh internals to the caller.
    """
    if not _HAS_GMSH:
        raise RuntimeError("gmsh not installed")  # route maps to 501 (see A.5)

    import tempfile
    suffix = Path(filename).suffix.lower() or ".step"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w+b")
    try:
        os.chmod(tmp.name, 0o600)           # owner R/W only (IP-local discipline)
        tmp.write(data)
        tmp.flush()
        tmp.close()
        return _mesh_step_file(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass


def _mesh_step_file(path: str) -> trimesh.Trimesh:
    with _GMSH_LOCK:                         # serialize the global gmsh context
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)          # no stdout spew
            gmsh.option.setString("Geometry.OCCTargetUnit", "MM") # normalize to mm
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", _CURVATURE_PTS)
            gmsh.model.add("part")
            gmsh.model.occ.importShapes(path)   # STEP/IGES/BREP via OCC
            gmsh.model.occ.synchronize()

            # scale-aware element budget: target ~_TARGET_DIAG_SEGMENTS across the diagonal
            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
            diag = ((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5
            size_max = min(max(diag / _TARGET_DIAG_SEGMENTS, _MIN_SIZE_MM), _MAX_SIZE_MM)
            gmsh.option.setNumber("Mesh.MeshSizeMax", size_max)

            gmsh.model.mesh.generate(2)          # 2D surface mesh = triangulated shell

            node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
            if node_coords.size == 0:
                raise ValueError("STEP file produced no meshable geometry.")
            verts = node_coords.reshape(-1, 3)
            tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

            etypes, _etags, enodes = gmsh.model.mesh.getElements(dim=2)
            tris = []
            for et, conn in zip(etypes, enodes):
                if et == 2:                       # gmsh type 2 == 3-node triangle
                    tris.append(np.fromiter((tag_to_idx[int(n)] for n in conn),
                                            dtype=np.int64).reshape(-1, 3))
            if not tris:
                raise ValueError("STEP file contains no surface triangles after tessellation.")
            faces = np.vstack(tris)
        finally:
            gmsh.finalize()

    # process=True merges coincident vertices -> recovers watertightness on
    # single solids whose faces share edges. Outside the gmsh lock (pure numpy).
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError("STEP tessellation yielded an empty mesh.")
    return mesh
```

Rationale for choices (all observed in the verification runs):
- **`process=True`** is what recovers `is_watertight==True` on single solids (gmsh emits per-OCC-face node sets; merging coincident vertices stitches the shell). Confirmed on both single-solid test files.
- **Face budget** (`MeshSizeMax ~ diag/200`) keeps typical parts in the low-tens-of-thousands of faces. It does **not** by itself stop an assembly (curvature refinement on many small bodies still exploded AS1 to 8.5 M) — the hard stop is the **triangle cap** (A.4) plus the **timeout** (A.5). Both are mandatory.
- **`Geometry.OCCTargetUnit="MM"`** makes the mm assumption explicit; the engine treats geometry as mm.

## A.3 Plug into `_parse_mesh` — `backend/src/api/routes.py`

Replace the STEP branch (currently `is_step_supported()` → 501 / `parse_step_from_bytes`). Change the import and the branch only; **STL branch and the magic/cap calls are unchanged**.

Current imports:
```python
from src.parsers.step_parser import is_step_supported, parse_step_from_bytes
```
Change to:
```python
from src.parsers.step_mesher import is_step_supported, step_to_trimesh_from_bytes
```

Current STEP branch inside `_parse_mesh`:
```python
        if not is_step_supported():
            raise HTTPException(
                status_code=501,
                detail="STEP parsing requires cadquery. Install with: pip install cadquery",
            )
        mesh = parse_step_from_bytes(data, filename)
        enforce_triangle_cap(mesh)
        return mesh, suffix
```
Replace with:
```python
        if not is_step_supported():
            raise HTTPException(
                status_code=501,
                detail="STEP parsing is unavailable on this server (gmsh not installed).",
            )
        mesh = step_to_trimesh_from_bytes(data, filename)
        enforce_triangle_cap(mesh)   # 400 if tessellation exceeded MAX_TRIANGLES
        return mesh, suffix
```

Routing-by-extension + magic is **already correct and untouched**:
- `_parse_mesh` already rejects suffixes outside `{.stl,.step,.stp}` with a 400.
- `validate_magic(data, suffix)` already requires the `ISO-10303-21` header for `.step/.stp` (verified: both test files start with `ISO-10303-21;`). Keep it — it is the cheap pre-parse guard before handing bytes to the OCC reader.
- `.stp.*` / compound suffixes: `Path(filename).suffix` returns the **last** suffix only, so `foo.stp.bak` → `.bak` → 400 (correct: we do not parse renamed files). A real `part.STP` → `.stp` (lowercased) → parsed. No change needed; `.stp.gz` etc. are intentionally unsupported (we never decompress untrusted input in-path).

## A.4 Triangle caps — reuse, no new code
- `enforce_triangle_cap(mesh)` (post-mesh, `MAX_TRIANGLES` default **2,000,000**) already runs after parse for both STL and STEP. For STEP it is the **hard stop** for runaway tessellation (the AS1 assembly's 8.5 M faces are rejected here as a clean 400 `FILE_TOO_LARGE`/`BAD_REQUEST`).
- `enforce_stl_triangle_count_cap` (pre-parse, binary STL only) **does not apply to STEP** — there is no declared triangle count in a STEP file before meshing. This is expected; the post-mesh cap covers STEP. Document it; do not try to fake a pre-count for STEP.
- Demo endpoint already passes the tighter `DEMO_MAX_TRIANGLES` (500k) cap to `enforce_triangle_cap`; STEP through `/validate/demo` inherits it automatically.

## A.5 Reliability gap found — STEP meshing MUST run under the executor + timeout (mandatory)

**Gap (verified by code reading + the 76.7 s AS1 run):** in both `validate_cost` and `validate_demo`, `_parse_mesh(...)` is currently called **synchronously in the request coroutine, BEFORE** the `asyncio.wait_for(loop.run_in_executor(...))` block. For STL this is fine (trimesh.load is sub-second). For STEP, gmsh meshing can take **tens of seconds and blocks the event loop**, with **no timeout** — a single big STEP upload would stall the whole worker. This must be fixed as part of A (it is the difference between "works on my cube" and "production-safe").

**Fix:** offload `_parse_mesh` to the analysis executor under the existing timeout. Add one helper in `routes.py`:
```python
async def _parse_mesh_async(data: bytes, filename: str):
    """Run _parse_mesh off the event loop, bounded by ANALYSIS_TIMEOUT_SEC.
    gmsh STEP meshing is CPU-bound and can be slow on complex parts; this keeps
    the worker responsive and turns a runaway tessellation into a clean 504."""
    import asyncio
    loop = asyncio.get_event_loop()
    timeout = _analysis_timeout_sec()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _parse_mesh, data, filename),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"File parsing exceeded {timeout:.0f}s timeout.",
        )
```
Then in `validate_cost` and `validate_demo`, replace the synchronous `mesh, suffix = _parse_mesh(data, ...)` with `mesh, suffix = await _parse_mesh_async(data, ...)`. (STL is unaffected functionally; it just runs in a thread now.) The downstream `_run` executor block is unchanged.

Because `_GMSH_LOCK` serializes gmsh and the default `ThreadPoolExecutor` may run several requests, **concurrent STEP uploads queue** rather than corrupt the global context — correct and safe, at the cost of throughput. Acceptable for V1; note in `outputs/c5-architect-log.md` if a process-pool is wanted later.

## A.6 Real test file — open-licensed, verified end-to-end

**Primary (explicitly OSI-licensed):** `eight_cyl.stp` from **pythonocc-core** (license confirmed via GitHub API: `spdx_id: "LGPL-3.0"`).
```
https://raw.githubusercontent.com/tpaviot/pythonocc-core/master/test/test_io/eight_cyl.stp
```
Verified locally: gmsh → 6738 faces, watertight, vol 1167.35 cm³ → engine OK → cost `make_now=cnc_turning / 6061-T6 Aluminum`, crossover_qty 45.7, `unit_cost==Σ(line_items)` holds.

**Secondary (single solid, larger):** `face_recognition_sample_part.stp`
```
https://raw.githubusercontent.com/tpaviot/pythonocc-demos/master/assets/models/face_recognition_sample_part.stp
```
(repo license is unset — use only as a smoke fixture, not as a license-of-record; prefer the LGPL pythonocc-core file for the committed test.)

**Negative/cautionary (assembly → must be refused):** `as1_pe_203.stp`
```
https://raw.githubusercontent.com/tpaviot/pythonocc-core/master/test/test_io/as1_pe_203.stp
```
Verified: non-watertight multi-body → either trips the 2 M triangle cap (400) or, if cap raised, G1 returns `GEOMETRY_INVALID` (400). Use it to assert the refusal path.

> Committing binaries: prefer **not** committing STEP blobs into git. Add a `tests/fixtures/step/` with a tiny generated solid (a gmsh-built box exported to STEP at test-collection time) for the always-on unit test, and gate the network-fetched real-file tests behind an env flag (`STEP_NETWORK_TESTS=1`) so CI without egress still passes. See A.8.

## A.7 Explicit scope boundary (put in code docstring + UI copy)
- **In scope (this cycle):** STEP/STP → triangulated mesh → existing geometry/feature engine → existing cost/decision layer. Single solids cost cleanly; assemblies and non-watertight bodies are refused via G1 with the standard structured 400.
- **Out of scope / BLOCKED:** B-rep face graph, exact analytic surfaces, GD&T/PMI/tolerance extraction from STEP AP242. Requires cadquery/OCP (not installable here). The cost numbers from a STEP-derived mesh carry the **same ±40–60% absolute band** as STL-derived ones (already disclosed in `report.notes`); the crossover/make-vs-buy direction remains robust.

## A.8 Tests (builder A must add) — `backend/tests/`
1. `test_step_mesher.py` (always-on, no network):
   - `test_gmsh_available()` → `is_step_supported() is True` (skip with reason if gmsh missing).
   - `test_box_step_meshes_watertight()` → generate a 10 mm box STEP via gmsh in a tmp file, feed bytes to `step_to_trimesh_from_bytes`, assert `is_watertight`, `volume>0`, `1000 cm³`-ish, faces in (hundreds … <2M).
   - `test_empty_step_raises_valueerror()` → garbage-after-magic bytes → `ValueError` (route maps to 400). Reuse the temp-file-cleanup assertion pattern from existing `test_step_parser.py`.
   - `test_no_temp_file_leak()` → mirror `test_step_parse_leaves_no_temp_files`.
2. `test_cost_api.py` (extend): add a STEP case using the tiny generated-box fixture (not network):
   - `POST /api/v1/validate/cost` with `("part.step", box_step_bytes)` → 200, `status=="OK"`, every estimate satisfies `abs(unit_cost_usd - sum(line_items.values())) < 0.02`, every driver carries a `provenance` in {MEASURED,USER,DEFAULT}.
   - assembly/non-watertight STEP → 400 with `code=="GEOMETRY_INVALID"`.
   - unsupported/renamed suffix `("x.stp.bak", b"...")` → 400.
   - STEP without `ISO-10303-21` header → 400 (magic guard).
3. `test_step_network.py` (gated `@pytest.mark.skipif(os.getenv("STEP_NETWORK_TESTS")!="1")`): fetch the LGPL `eight_cyl.stp`, assert full cost path 200 + invariant. Keeps CI green without egress.

## A.9 Dependency wiring
- Add `gmsh>=4.13` to `backend/requirements.txt` (or pyproject deps). Wheel is `py2.py3-none-<platform>`; works on macOS arm64 (verified) and standard Linux x86_64 CI runners (manylinux wheels exist). If the deploy target is Linux arm64 or musl, confirm a wheel exists at build time; if not, the route already degrades to a clean **501** via `is_step_supported()` (no crash). State this in the PR.
- Size: the gmsh wheel is ~36 MB. Acceptable; note it in the image-size budget.

---

# B. FRONTEND COST-DECISION SURFACE (builder B)

## B.1 Reuse map (do not re-invent)
| Need | Reuse | File |
|---|---|---|
| Drag/drop upload | `FileDropZone` (props `onFileSelect`, `isLoading`) | `frontend/src/components/FileDropZone.tsx` |
| STL 3D preview | `ModelViewer` (STL only; STEP shows its built-in "STEP preview requires backend conversion" placeholder — leave as-is) | `frontend/src/components/ModelViewer.tsx` |
| Auth + rate-limit + error handling fetch | `apiClient` pattern (Bearer from `localStorage["cadverify_api_key"]`, 429 toast, 5xx retry/Sentry, 4xx throw) | `frontend/src/lib/api.ts` |
| API base join | `API_BASE` (`/api/v1`) | `frontend/src/lib/api-base.ts` |
| Page shell + nav | `(dashboard)/layout.tsx` `NAV_ITEMS` | `frontend/src/app/(dashboard)/layout.tsx` |
| Verdict/severity badge styling, provenance-tag rendering idiom | copy the small badge helpers from `AnalysisDashboard.tsx` | `frontend/src/components/AnalysisDashboard.tsx` |

The cost surface is a sibling to the existing analysis dashboard, not a rewrite of it.

## B.2 API client — extend `frontend/src/lib/api.ts`

The endpoint takes **multipart Form fields** (not query params). Add types matching `report_to_dict` exactly (verified against `src/costing/report.py` + `estimate.py` + `decision.py`). Note `recommendation`/`if_redesigned` are keyed by quantity but JSON-serialize the int keys as **strings** → `Record<string, …>`.

```ts
/* ---- Cost decision types (POST /validate/cost) — Cycle 5 ---- */
export type Provenance = "MEASURED" | "USER" | "DEFAULT";

export interface CostDriver {
  name: string; value: number; unit: string;
  provenance: Provenance; source: string;
  error_band_pct: number | null;
}
export interface CostLeadTime {
  low_days: number; high_days: number; mid_days: number;
  components: Record<string, number>;
  capacity: { n_machines?: number; machine_hours_per_day?: number; provenance?: string } | Record<string, never>;
}
export interface CostEstimate {
  process: string; material: string; quantity: number;
  unit_cost_usd: number; fixed_cost_usd: number; variable_cost_usd: number;
  est_error_band_pct: number;
  dfm_ready: boolean; dfm_verdict: "pass" | "issues" | "fail";
  dfm_score: number; dfm_blockers: string[];
  line_items: Record<string, number>;
  drivers: CostDriver[];
  lead_time: CostLeadTime;
}
export interface CostRecommendation {
  process: string; material: string; unit_cost_usd: number;
  dfm_ready: boolean; dfm_verdict: string;
  lead_low_days: number | null; lead_high_days: number | null;
}
export interface CostRedesigned {
  process: string; material: string; unit_cost_usd: number; caveat: string;
}
export interface CostDecision {
  make_now_process: string; make_now_material: string;
  tooling_process: string | null; tooling_dfm_ready: boolean;
  crossover_qty: number | null;
  recommendation: Record<string, CostRecommendation>;
  if_redesigned: Record<string, CostRedesigned | null>;
  note: string;
}
export interface CostAssumption {
  name: string; value: number; unit: string; provenance: Provenance; source: string;
}
export interface CostGeometry {
  volume_cm3: number; surface_area_cm2: number;
  bbox_mm: [number, number, number]; watertight: boolean; face_count: number;
}
export interface CostFeasibility { process: string; verdict: string; score: number; costed: boolean; }
export interface CostReport {
  filename: string;
  status: "OK" | "GEOMETRY_INVALID";
  reason: string | null;
  geometry: CostGeometry;
  material_class: string;
  quantities: number[];
  estimates: CostEstimate[];
  engine_feasibility: CostFeasibility[];
  notes: string[];
  assumptions: CostAssumption[];
  decision: CostDecision | null;
}

export interface CostOptions {
  qty: string;            // "50,5000"
  region: string;         // US|EU|MX|CN|IN|SA
  cavities: number;       // >=1
  complexity: string;     // simple|moderate|complex|very_complex
  material_class: string; // polymer|aluminum|steel|stainless|titanium
}

// GEOMETRY_INVALID arrives as a 400 whose JSON is {code,message,geometry,doc_url}.
// apiClient.fetch throws on 4xx with err.detail; for this endpoint we want the
// structured body, so we call fetch directly and branch on status (mirrors the
// landing-page demo handler in app/page.tsx).
export async function costEstimate(file: File, opts: CostOptions): Promise<CostReport> {
  const form = new FormData();
  form.append("file", file);
  form.append("qty", opts.qty);
  form.append("region", opts.region);
  form.append("cavities", String(opts.cavities));
  form.append("complexity", opts.complexity);
  form.append("material_class", opts.material_class);

  const res = await apiClient.fetch(
    `${API_BASE}/validate/cost`,
    { method: "POST", body: form },
    { retries: 0 }     // costing is non-idempotent-priced compute; no auto-retry
  );
  return (await res.json()) as CostReport;
}
```
Note: `apiClient.fetch` already throws on non-OK (429 toast / 5xx Sentry / 4xx Error(detail)). For `GEOMETRY_INVALID` (400) the thrown `Error.message` will be the `message` string from the structured body — sufficient for V1. If builder B wants the structured geometry on invalid, catch and re-fetch is unnecessary; instead read `res` before throw is not possible through the wrapper, so for the richer invalid card, replicate the demo pattern (raw `fetch` + manual `res.ok` branch) — **either is acceptable**; default to the `apiClient` path and show `error.message`.

## B.3 New component — `frontend/src/components/CostDecisionCard.tsx`
Pure presentational, `{ report: CostReport }`. Sections, top to bottom:
1. **Headline (make-vs-buy):** `report.decision.note` rendered prominently; show `make_now_process / make_now_material`. If `crossover_qty != null`, render a one-line "make below ~{crossover_qty} units, tool above" strip.
2. **Per-quantity decision table:** iterate `report.quantities`; for each `q` look up `report.decision.recommendation[String(q)]` → row: qty · process/material · **$ unit_cost_usd/unit** · lead `low–high d`. If `report.decision.if_redesigned[String(q)]` is non-null, add a muted sub-row "cheaper if redesigned: {process} ${unit_cost_usd} ({caveat})".
3. **Process options ($/unit at chosen qty):** group `report.estimates` by `process`; show each process's per-qty unit cost (and a `±est_error_band_pct%` badge). Flag `dfm_ready==false` with a "NOT DFM-ready as-modeled" warning chip and show `dfm_blockers[0]`.
4. **Driver breakdown with provenance (glass-box):** for the headline process's smallest-qty estimate, list `drivers` (name · formatted value+unit · **`[provenance source]` tag**). Reuse a provenance→color map: `MEASURED`=blue, `USER`=green, `DEFAULT`=gray. Also render the `line_items` map and assert visually `Σ line_items == unit_cost_usd` (display the sum). This is the IP/explainability differentiator — keep tags visible.
5. **Lead time:** `low_days–high_days` with the `components` breakdown and, if present, the `capacity` line ("N machines × H hr/day").
6. **Assumptions + notes:** render `report.assumptions` (each with provenance tag) and `report.notes[]` (the ±40–60% + crossover-robustness disclaimer). Add a fixed footnote: "STEP files are costed from a tessellated mesh (DFM + cost), not B-rep/GD&T."
7. **GEOMETRY_INVALID state:** when `report.status!=="OK"` (or the 400 path), show a repair card: `reason` + `geometry` summary (volume/bbox/watertight/face_count) + link to docs. Mirror the engine's G1 message tone.

Reuse the badge/severity helpers from `AnalysisDashboard.tsx` (copy `SeverityBadge`, the citation-color idiom) so styling matches.

## B.4 New route — cost page
Create `frontend/src/app/(dashboard)/cost/page.tsx` and a thin re-export `frontend/src/app/dashboard/cost/page.tsx` (`export { default } from "../(dashboard)/cost/page";`) to match the existing dual-route convention (`dashboard/page.tsx` re-exports `(dashboard)/page.tsx`).

Page behavior (`"use client"`):
- State: `file`, `report`, `loading`, `error`, and a `CostOptions` form (defaults `qty:"50,5000"`, `region:"US"`, `cavities:1`, `complexity:"moderate"`, `material_class:"polymer"` — identical to the backend Form defaults).
- **Override controls:** quantity text input (comma list, client-validate ≤6 ints, 1…10,000,000), region `<select>` (US|EU|MX|CN|IN|SA), cavities number input (≥1), complexity `<select>` (simple|moderate|complex|very_complex), material_class `<select>` (polymer|aluminum|steel|stainless|titanium). These mirror the endpoint's validation exactly so the user never round-trips a 400 for a bad option.
- Two entry modes:
  1. **Upload:** `FileDropZone` → on select, validate extension `{stl,step,stp}` (reuse the check from `app/page.tsx`), then `costEstimate(file, opts)`.
  2. **Re-cost an already-analyzed part:** a "Cost this part" affordance. The cost endpoint requires the **file bytes** (no persistence/no mesh store on the cost path), so re-costing reuses the same `File` the user already uploaded for analysis (keep the `File` in state on the analysis page and pass via router state or a shared client store). **Do not** attempt to cost from an `analysis_id` — there is no server-side mesh to re-fetch on the cost path (by design: zero persistence). Document this in the page: re-cost = re-submit the same file with new options (fast, no re-upload UI friction since the `File` is in memory).
- Layout: left = `ModelViewer file={file}` (STL preview; STEP shows the placeholder — acceptable), right = `<CostDecisionCard report={report} />` + the options form with a "Re-cost" button that re-calls `costEstimate` with the current options (lets the user sweep qty/region/complexity without re-uploading).
- Add `{ href: "/cost", label: "Cost" }` to `NAV_ITEMS` in `(dashboard)/layout.tsx`.

## B.5 Build / typecheck gate (builder B acceptance)
- `cd frontend && npm run build` — Next 16 `next build` runs the TypeScript typecheck and fails on any type error. Must be **green**. (`tsconfig` `@/*` → `./src/*` is already configured.)
- `cd frontend && npm run lint` — eslint must be **green** (no new warnings-as-errors).
- No new runtime deps required (all types are local; fetch reuses existing `apiClient`). Do not add a charting lib — render the table/bars with the existing Tailwind idiom used in `ProcessScoreCard`.

---

# C. OBSERVABILITY / RELIABILITY HARDENING (builder C)

## C.1 What already exists (do not duplicate)
- **Request-ID correlation:** `src/api/middleware.py::RequestIDMiddleware` generates/propagates `X-Request-ID`, binds it to **structlog contextvars** (`merge_contextvars`) and the Sentry scope, echoes it on the response. Added **outermost** in `main.py` (before CORS/ratelimit/routers). Solid — reuse it; every structlog event automatically carries `request_id`.
- **structlog pipeline:** configured in `main.py` (`merge_contextvars → add_log_level → TimeStamper(iso) → scrub_processor → JSONRenderer`), with `scrub_processor` redacting `cv_live_*`/Authorization before stdout/Sentry. JSON logs to stdout.
- **Structured errors:** `src/api/errors.py` maps status→stable code (`BAD_REQUEST`, `FILE_TOO_LARGE`(413), `RATE_LIMITED`(429), `ANALYSIS_TIMEOUT`(504), …) with `{code,message,doc_url}`; passes through any `detail` dict that already has a `code` (this is how `GEOMETRY_INVALID` keeps its geometry payload). Wired for `HTTPException`, `StarletteHTTPException`, `RequestValidationError`. Complete — confirm coverage (C.4), don't rebuild.

## C.2 Gap: cost + corpus endpoints emit no structured request/outcome logs
`routes.py` and `corpus_router.py` use **stdlib** `logging.getLogger(...)`, which bypasses the structlog JSON+scrub+request_id pipeline. The cost path logs nothing about an upload's outcome. Add **structlog** emission (auto-carries `request_id` via contextvars).

In `routes.py`, add a module-level `slog = structlog.get_logger("cadverify.cost")` and, in `validate_cost`, after the report is produced, emit one event with **non-PII** fields only (never the filename raw if it could carry IP — hash it; never mesh bytes):
```python
import hashlib, structlog
slog = structlog.get_logger("cadverify.cost")
# ... after building `report` (and on each terminal branch):
slog.info(
    "cost_estimate",
    file_sha8=hashlib.sha256(data).hexdigest()[:8],  # correlate without storing CAD
    suffix=suffix,
    face_count=report.geometry.get("face_count"),
    status=report.status,                            # OK | GEOMETRY_INVALID
    make_now=(report.decision.make_now_process if report.decision else None),
    crossover_qty=(report.decision.crossover_qty if report.decision else None),
    n_qty=len(quantities), region=region, material_class=material_class,
    duration_ms=round((time.perf_counter() - t0) * 1000, 1),
)
```
(Set `t0 = time.perf_counter()` at handler entry.) Emit the same event with `status="GEOMETRY_INVALID"` before raising the 400, and a `slog.warning("cost_timeout", ...)` on the 504 branch. **Do not log full filenames or any geometry beyond aggregate counts** (IP-local discipline; the scrub processor is a backstop, not a license to log CAD).

In `corpus_router.py`, swap the stdlib `logger` for `structlog.get_logger("cadverify.corpus")` and add request-scoped events on `POST /labels` (`part_id`, `label`, `labeler`, `ts`) and on `stream_mesh` 404s. Corpus is dev-gated (`LABELING_ENABLED=1`) so this is low-risk; it just makes the local tool's logs structured + correlated.

## C.3 Reliability gaps (must close)
1. **STEP parse runs unbounded on the event loop** — fixed in **A.5** (`_parse_mesh_async` + 504). Builder C verifies the 504 path: a STEP that exceeds `ANALYSIS_TIMEOUT_SEC` returns `504 ANALYSIS_TIMEOUT`, not a hang. (Test by monkeypatching `ANALYSIS_TIMEOUT_SEC` very low and feeding a non-trivial STEP, or by patching `_parse_mesh` to sleep.)
2. **gmsh global-context concurrency** — `_GMSH_LOCK` (A.2) serializes the gmsh critical section across the thread-pool executor. Builder C adds a test that fires two concurrent `/validate/cost` STEP requests (TestClient threads) and asserts both return 200 (no segfault / no `gmsh already initialized`). If flakiness appears, escalate to a process-pool and log it in `outputs/c5-architect-log.md` (do not silently degrade).
3. **Triangle caps cover STEP** — confirm `enforce_triangle_cap` runs post-mesh for STEP (it does, A.4) and that an oversize tessellation returns a clean 400 (use the AS1 assembly or a low `MAX_TRIANGLES` monkeypatch).
4. **Timeout already wraps the cost compute** — `validate_cost` wraps `_run` in `asyncio.wait_for(..., _analysis_timeout_sec())` → 504. Keep; just make sure parse is *also* bounded (gap 1).
5. **Zero egress preserved** — the costing layer opens no sockets; gmsh meshing is local (temp file, OCC in-process). Builder C keeps the existing `test_cost_zero_network_egress`-style guard green and adds the STEP case under it (patch `socket.socket` to raise, run a STEP cost, assert 200).

## C.4 Confirm structured-error coverage (checklist, no code unless a gap)
- 400 bad extension / bad magic / empty file → `BAD_REQUEST` ✓ (routes + upload_validation).
- 400 `GEOMETRY_INVALID` (dict with `code`) → passed through with geometry payload ✓ (errors.py branch).
- 413 oversize upload / oversize mesh → `FILE_TOO_LARGE` ✓.
- 422 form validation (bad `cavities` type etc.) → `VALIDATION_ERROR` ✓ (`structured_validation_error_handler`).
- 429 rate limit → `RATE_LIMITED` ✓ (slowapi handler).
- 501 STEP unavailable (gmsh missing) → currently maps to `UNKNOWN_ERROR` (501 not in `ERROR_CODES`). **Add** `501: "NOT_IMPLEMENTED"` to `ERROR_CODES` in `errors.py` so the degraded-no-gmsh response is stable. (One-line change.)
- 504 timeout → `ANALYSIS_TIMEOUT` ✓.

## C.5 Acceptance criteria (all three workstreams)

**A (STEP) is done when:**
- [ ] `pip install gmsh` is in deps; `is_step_supported()` reflects gmsh availability; route returns clean **501** if absent.
- [ ] `POST /api/v1/validate/cost` with a single-solid STEP (generated box fixture) → **200**, `status:"OK"`, every estimate `abs(unit_cost_usd − Σline_items) < 0.02`, every driver/assumption has provenance ∈ {MEASURED,USER,DEFAULT}.
- [ ] Same for `/api/v1/validate` and `/api/v1/validate/demo` (STEP now analyzable, not 501).
- [ ] Assembly / non-watertight STEP → **400 GEOMETRY_INVALID** (G1), oversize tessellation → **400** (cap).
- [ ] STEP parse is bounded by the timeout (504, no event-loop block) and serialized via `_GMSH_LOCK`.
- [ ] `test_step_mesher.py` + extended `test_cost_api.py` green; gated `test_step_network.py` green when `STEP_NETWORK_TESTS=1`.

**B (frontend) is done when:**
- [ ] `/cost` route renders: upload → decision card with per-process $/unit at chosen quantities, lead-time range, make-vs-buy headline + crossover, driver breakdown with **visible provenance tags**, and qty/region/cavities/complexity/material_class overrides that re-cost without re-upload.
- [ ] GEOMETRY_INVALID renders the repair card (reason + geometry), not a stack trace.
- [ ] Reuses `FileDropZone`, `ModelViewer`, `apiClient`, `API_BASE`; nav item added.
- [ ] `npm run build` (typecheck) **green** and `npm run lint` **green**.

**C (hardening) is done when:**
- [ ] `validate_cost` + corpus `POST /labels` emit one structlog event each (JSON, request_id-correlated, no CAD/PII; file hashed).
- [ ] `501` added to `ERROR_CODES`; structured-error checklist (C.4) all ✓.
- [ ] Concurrency test (2 simultaneous STEP costs) → both 200; timeout test → 504; zero-egress test (incl. STEP) → 200 with sockets blocked.
- [ ] **Full backend suite green:** `cd backend && .venv/bin/python -m pytest -q` (the ~80 prior tests + new STEP/cost/hardening tests; **no regressions**).
- [ ] **Frontend build green** (shared gate with B).

## C.6 Commands of record
```bash
# backend
cd /Users/nazeem/Desktop/developer/cadverify/backend
.venv/bin/python -m pip install gmsh
.venv/bin/python -m pytest -q                      # full suite, must be green
STEP_NETWORK_TESTS=1 .venv/bin/python -m pytest -q tests/test_step_network.py

# frontend
cd /Users/nazeem/Desktop/developer/cadverify/frontend
npm run build      # next build == typecheck gate
npm run lint
```

---

## Appendix — exact `report_to_dict` shape (source of truth for B's TS types)
Verified against `src/costing/report.py::report_to_dict`, `estimate.py::_serialize`, `decision.py::Decision`:
- top: `filename, status, reason, geometry{volume_cm3,surface_area_cm2,bbox_mm[3],watertight,face_count}, material_class, quantities[int], estimates[], engine_feasibility[{process,verdict,score,costed}], notes[str], assumptions[{name,value,unit,provenance,source}], decision`.
- `estimates[i]`: `process, material, quantity, unit_cost_usd, fixed_cost_usd, variable_cost_usd, est_error_band_pct, dfm_ready, dfm_verdict, dfm_score, dfm_blockers[str], line_items{name:usd}, drivers[{name,value,unit,provenance,source,error_band_pct}], lead_time{low_days,high_days,mid_days,components{name:num},capacity{...}|{}}`.
- `decision`: `make_now_process, make_now_material, tooling_process|null, tooling_dfm_ready, crossover_qty|null, recommendation{"<q>":{process,material,unit_cost_usd,dfm_ready,dfm_verdict,lead_low_days|null,lead_high_days|null}}, if_redesigned{"<q>":{process,material,unit_cost_usd,caveat}|null}, note`. **Quantity keys are JSON strings.**
- `provenance` ∈ `"MEASURED" | "USER" | "DEFAULT"`.
</content>
</invoke>
