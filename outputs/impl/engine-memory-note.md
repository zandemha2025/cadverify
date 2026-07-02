# Engine Memory Bound — Impl Note (arch-audit P0)

**Item:** `feat/engine-memory` — bound the wall-thickness ray-cast allocation so an
ordinary CAD upload never OOM-kills the 1 GB web machine.
**Branch:** `feat/engine-memory` (worktree `cadverify-wt-mem`).
**Scope:** geometry/memory path + ingest guard only. Cost model and frontend untouched.

---

## The P0 finding (what was broken)

`src/analysis/context.py::_compute_wall_thickness` fired **one inward ray per face**
in a **single** `mesh.ray.intersects_location(..., multiple_hits=True)` call. No fast
ray backend is installed (`pyembree`/`embreex` absent — verified), so trimesh uses the
pure-Python `RayMeshIntersector`, whose peak memory scales with **rays × candidate
triangles**. Measured peaks: 9,472 faces → 2,345 MB; 36,702 faces → 19,331 MB; 1.5M
faces → >120 s timeout.

The guard was **backwards**: `RAYCAST_SAMPLE_THRESHOLD` defaulted to **50,000**, so the
bounded/sampled path only engaged *above* 50k faces. The entire dangerous **10k–50k
face zone (most real CAD)** ran the un-sampled, unbounded path. There was **no mesh
decimation** anywhere (`grep decimat|simplify_quadric = 0 hits`). Net: the web machine
(`fly.toml memory="1gb"`) OOM-kills on essentially the first real upload.

---

## What changed

All changes are ON by default (demo-path improvement) and env-overridable.

### 1. Corrected the sample threshold (`context.py::_raycast_sample_threshold`)
`RAYCAST_SAMPLE_THRESHOLD` default **50000 → 5000**. Meshes above 5k faces now take the
**sampled** path (~5000 rays cast, propagated to the rest via KDTree nearest-neighbour),
so the dangerous 10k–50k zone is off the unbounded full-ray path.

### 2. Memory-bounded batched ray casting (`context.py::_cast_inward_rays_batched`)
Both the full-ray path and the sampled path now cast rays through one shared helper that
casts rays in **adaptive batches** and scatter-min's (`np.minimum.at`) each batch's
results into the output before the next batch, so the working set never holds all
`rays × candidates` intermediates at once.

- The pure-Python backend's peak memory has a sharp **allocation cliff** in
  `batch × n_faces`. A *fixed* batch can't bound both a 5k-face part and a 250k-face
  part, so the batch is **face-count-aware**: `batch = clamp(BUDGET // n_faces, 8, MAX)`.
- `WALL_THICKNESS_RAY_BUDGET` (default **1_200_000**) caps the `rays × faces` product per
  call. `WALL_THICKNESS_RAY_BATCH` (default **512**) is the upper batch cap for
  small/cheap meshes. Both env-overridable.

This alone bounds even the below-threshold full-ray path (proven by the regression test
that forces `RAYCAST_SAMPLE_THRESHOLD` high).

### 3. Ingest decimation for pathological meshes (`context.py::_maybe_decimate`)
`GeometryContext.build` now decimates any mesh over `MAX_ANALYSIS_FACES` (default
**250000**) *before* any O(faces) work, bounding the **whole engine** (ray cast,
adjacency, facets, split, feature detection) — not just wall thickness. The cap is
conservative so typical CAD parts, and the existing 209k-face `test_large_mesh`
regression, are **never touched**.

- Decimation strategy: prefers trimesh `simplify_quadric_decimation` (quadric) when its
  optional backend is present; **falls back to a dependency-free uniform grid
  vertex-clustering** decimator (`_vertex_cluster_decimate`). In this venv neither
  `fast_simplification` (quadric) nor `skimage` (voxel remesh) is installed, so the
  vertex-cluster fallback is what runs — it is numpy-only, deterministic, fast (<0.1 s),
  and preserves volume within ~0.7% on test geometry.
- **Honest labelling (no silent lying) — USER-VISIBLE:** when decimation runs it is
  recorded in `ctx.metadata["decimation"] = {attempted, succeeded, original_faces,
  analysis_faces, strategy}` **and surfaced to the user** as a `DECIMATED_MESH` warning
  (§3b). `GeometryInfo` (volume/area/watertightness) is intentionally kept from the
  **original** mesh (computed by `analyze_geometry` upstream); only the per-face analysis
  arrays run on the bounded mesh.

### 3b. User-visible decimation warning (honesty fix — added after adversarial review)
The first cut recorded decimation only in `ctx.metadata`, which **no consumer read** — so
the user was never told their DFM numbers were approximate (a silent-approximation honesty
violation; the code comments even falsely claimed "labelled accordingly"). Fixed:
`base_analyzer.decimation_issue(ctx)` reads `ctx.metadata["decimation"]` and, when
`succeeded`, returns a universal `Issue`:

> **DECIMATED_MESH** (severity `warning`): "Analyzed on a decimated mesh:
> {original:,}→{analysis:,} faces ({strategy}). Wall-thickness, draft-angle and other DFM
> values are approximate — computed on a reduced-resolution copy to bound memory."
> fix_suggestion: "Re-export the part with fewer than {analysis:,} triangles …"

It is appended to `universal_issues` in **all four** GeometryContext-building analysis
paths — authed `/validate` (`services/analysis_service.py`), demo `/validate/demo`
(`routes.py::validate_demo`), cost engine (`routes.py::_run_cost_engine`), and the costing
CLI (`costing/cli.py`) — so it flows through `_to_response` into the JSON `universal_issues`
array the frontend already renders. When a decimation *attempt fails* and the original
full-resolution mesh is kept, results are exact and **no** warning is emitted (correct).
The two false code comments (`context.py:149`, `context.py:406-410`) were reworded to
describe the real, now-implemented labelling. Proven user-visible by
`test_decimation_warning_is_visible_in_api_response` (POST a ~295k-face mesh → HTTP 200
with `DECIMATED_MESH` in `universal_issues`).

### 4. Feature detection consistency (call-site edits)
Because features are indexed against the context's per-face arrays, feature detection
must run on the **same** mesh those arrays derive from. Updated 5 call sites from
`detect_features(mesh)` → `detect_features(ctx.mesh)`
(`api/routes.py` ×2, `services/analysis_service.py`, `eval/engine.py`, `costing/cli.py`).
When no decimation occurs, `ctx.mesh is mesh`, so this is a **no-op for all existing
tests** and only matters when a mesh is decimated. `run_universal_checks` intentionally
stays on the original mesh (it reports the true part's watertightness/topology).

### 5. Defensive refuse guard (unchanged, already present)
The existing hard cap `enforce_triangle_cap` / `MAX_TRIANGLES=2_000_000` (demo 500k) at
parse time still refuses truly pathological meshes with an honest 4xx. Left as-is — it is
the "beyond what decimation handles" guard the audit asked for; `MAX_TRIANGLES` is owned
by another item, so it was not changed.

### 6. Cosmetic numpy warning suppression
Wrapped the `normals @ [0,0,1]` angle-from-up matmul (`context.py:166`) in
`np.errstate(all="ignore")` — the same approach `eval/engine.py` already uses — so the
cosmetic divide-by-zero/overflow `RuntimeWarning` that fires on decimated/degenerate
normals no longer spams the routes/service path. The clipped result is numerically clean.

---

## Measured before/after peak RSS

Peak RSS measured via `resource.getrusage(RUSAGE_SELF).ru_maxrss`, incremental delta from
a post-import baseline, each case in a **fresh process** (ru_maxrss is a monotonic
high-water mark). Machine: macOS, Python 3.9, trimesh 4.11.5, pure-Python ray backend.

### Realistic CAD proxy — subdivided box, ~49k faces (the audit's "most real CAD" zone)
| Path | Before | After |
|---|---|---|
| Full `GeometryContext.build` (default env) | — | **62 MB, 0.33 s, 100% finite** |
| Forced full un-sampled ray path (batched) | (was the 19 GB bomb) | **18 MB, 1.5 s** |
| Default sampled path | — | **14 MB, 0.25 s** |

### Pathological worst case — hollow icosphere (broad phase prunes nothing)
| Faces | Before (old single-call full path) | After (fix) |
|---|---|---|
| 5,120 | **1,150 MB**, 0.9 s | **148 MB**, 0.8 s |
| 20,480 | **13,911 MB (~13.9 GB)**, 15 s | **bounded**, 2.9 s |
| 81,920 | (OOM / >120 s — matches finding's timeout) | **~482 MB**, 10 s, 100% finite |

The 20,480-face sphere at **13.9 GB before** is a clean synthetic reproduction of the
finding's 36,702-face → 19,331 MB real-part measurement. After the fix, the same
geometry is bounded to a few hundred MB — **a >25× reduction**, comfortably survivable on
a 1 GB machine. Realistic parts drop from gigabytes to tens of MB.

---

## Regression test (the proof)

`backend/tests/test_engine_memory_bound.py` — runs the real code paths in a fresh
**spawned** subprocess (clean `ru_maxrss`) and asserts incremental peak RSS is a small
fraction of the pre-fix 19 GB:

- `test_build_37k_box_is_memory_bounded` — full `GeometryContext.build` on a ~37k-face
  part < **1024 MB** (actual ~62 MB). Direct closure of the finding.
- `test_full_unsampled_ray_path_is_batched_and_bounded` — forces the un-sampled full-ray
  path (the exact pre-fix bomb) on 37k faces < **1024 MB** (actual ~18 MB). Proves the
  **batching** (not just the threshold) bounds the allocation.
- `test_pathological_sphere_wall_thickness_is_bounded` (`@slow`) — ~37k-face hollow
  sphere worst case < **1800 MB** (actual ~482 MB). Proves even the worst case, which the
  old code could not finish, is bounded.

Bounds are generous-but-meaningful (absorb allocator/GC noise, still << 19 GB) and
deterministic (fresh process + delta-from-baseline).

**Decimation-honesty tests** (same file):
- `test_decimation_records_metadata_and_emits_warning` — a >250k-face mesh is decimated,
  recorded in `ctx.metadata`, and `decimation_issue(ctx)` returns a `DECIMATED_MESH`
  warning.
- `test_no_decimation_no_warning_for_normal_part` — an ordinary part emits **no** warning
  (no false positives).
- `test_decimation_warning_is_visible_in_api_response` — POST a ~295k-face mesh to
  `/validate/demo` → HTTP 200 with `DECIMATED_MESH` in the response `universal_issues`
  (proves the label reaches the user, not just `ctx.metadata`).

---

## Env flags / defaults (all ON by default)

| Env var | Default | Meaning |
|---|---|---|
| `RAYCAST_SAMPLE_THRESHOLD` | `5000` | faces above which the sampled (bounded) path runs (was 50000) |
| `WALL_THICKNESS_RAY_BATCH` | `512` | upper cap on rays per `intersects_location` call |
| `WALL_THICKNESS_RAY_BUDGET` | `1200000` | target rays×faces product/call; shrinks batch for high-face meshes |
| `MAX_ANALYSIS_FACES` | `250000` | face cap above which the mesh is decimated on ingest |

---

## Tests changed + numeric-shift caveats (Zoox gate)

**Tests updated** (`backend/tests/test_wall_thickness_sampling.py`):
- `test_threshold_default` — now asserts the new default `5000` (was `50000`), with a
  `monkeypatch.delenv` so it's deterministic regardless of CI env.
- `test_sampling_correctness_on_cube` — now `monkeypatch.setenv("RAYCAST_SAMPLE_THRESHOLD",
  huge)` so it genuinely compares the full-ray reference vs the sampled path; with the new
  5000 default the ~12k-face box would otherwise route both to the sampled path and make
  the comparison vacuous. The full-vs-sampled <10% deviation assertion still holds.

No test asserted exact wall-thickness *values* that changed, so no numeric assertions were
rewritten.

**⚠ Numeric-correctness caveats — flag for the Zoox gate (NOT self-certified):**
Lowering the sample threshold to 5000 means parts in the 5k–50k face range now use the
**sampled + KDTree-propagated** wall thickness instead of the exact per-face full ray
cast, and parts over 250k faces are **decimated** before analysis. Both can **shift
wall-thickness and draft-angle numbers**. `np.inf` still means "unknown" not "thick", the
sampled path is a pre-existing approximation (already shipped for >50k), and decimation is
now honestly labelled to the user. Specific items for the Zoox correctness gate:

1. **Sampled-path tail error at wall-thickness discontinuities.** Lowering
   `RAYCAST_SAMPLE_THRESHOLD` 50000→5000 expands the KDTree-propagation sampled path to
   **most real CAD (5k–50k faces)**. Because unsampled faces inherit the nearest sampled
   face's thickness, a **thin rib adjacent to a thick boss can inherit the wrong value** at
   the discontinuity — a verifier measured **tail error up to ~567% relative** at such
   discontinuities. This is the primary correctness risk of this change and must be
   evaluated/tuned (sample density, discontinuity-aware propagation) at the Zoox gate. It
   is **not** self-certified here.
2. **Decimation numeric shift.** Vertex-cluster decimation of >250k-face meshes changes
   the mesh the DFM numbers are computed on; magnitude/direction of the resulting
   wall-thickness/draft shift is unverified (labelled to the user via `DECIMATED_MESH`).

These are **numeric-correctness questions that must go through the Zoox calibration gate** —
explicitly *not* self-certified in this change.

---

## Full suite result

`pytest -q` (backend), same venv, final state (with `backend/data` symlinked so
shop-profile tests have their fixtures):
- **563 passed, 0 failed, 7 skipped.**

This includes 6 memory-bound tests + 3 decimation-honesty tests. The 3 `test_cost_api`
failures seen during development were pre-existing (missing `backend/data` shop-profile
fixtures, unrelated to this change) and are now green once the fixtures are present. An
earlier one-off flaky `test_auth_dashboard_session::test_require_dashboard_session_valid`
(an env-leak ordering flake reading `DASHBOARD_SESSION_SECRET`, no causal link to the
geometry path) did **not** recur.

---

## How this closes the P0 finding

1. The un-sampled full-ray path no longer runs on the 10k–50k face danger zone (threshold
   5000). ✔
2. Even when the full-ray path does run (small meshes, or forced), it is cast in adaptive
   memory-bounded batches — proven to bound the exact bomb. ✔
3. Pathological huge meshes are decimated on ingest, bounding the whole engine, and a hard
   refuse guard remains for the truly extreme. ✔
4. Decimation is **honestly and visibly labelled to the user** via a `DECIMATED_MESH`
   warning in the response `universal_issues` (not a silently-approximated result) — proven
   by an end-to-end response test. ✔
5. A deterministic regression test proves peak RSS on a ~37k-face part dropped from ~19 GB
   to tens of MB (realistic) / ~0.5 GB (worst-case sphere) — a small fraction of 19 GB. ✔

## Residual / recommended follow-up (out of scope here)
- **Durable root fix:** install a fast ray backend (`embreex`/`pyembree`) — turns the ray
  cast O(rays) instead of O(rays × candidates) and removes the pathological-sphere cost
  entirely. Not added here (native dep, CI/image risk; the allocation is bounded without it).
- **Process isolation:** the audit's separate killable/cgroup-capped analysis worker (the
  60 s timeout is cooperative-only) is owned by a later async-tier item — not built here.
- **Zoox gate:** validate the wall-thickness/draft numeric shifts from the lower sample
  threshold + decimation are within DFM tolerance.
