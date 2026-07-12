# Mutation-safe parsed-mesh cache — 2026-07-08

## What it does
`backend/src/api/routes.py::_parse_mesh(data, filename)` is the single RAW parse
seam: it turns upload bytes into a trimesh (gmsh/OCC tessellation for STEP/IGES,
`parse_stl_from_bytes` for STL) BEFORE any units scaling, decimation, or analysis.
The SAME part is parsed independently by `/validate`, `/validate/cost`,
`/validate/cost/demo`, and `/validate/preview-mesh` (all via `_parse_mesh_async`),
plus the sync callers in `jobs/batch_tasks.py`, `services/repair_service.py`, and
`services/analysis_service.py`.

The cache (`backend/src/parsers/mesh_cache.py`) is an in-process LRU keyed by
`(sha256(raw bytes), suffix)` mapping to the parsed trimesh. It is wired INSIDE
`_parse_mesh`, so every caller (async routes and sync jobs) benefits with zero
change to call sites. On a hit, a STEP part that costs ~4 s to re-tessellate is
served as a ~4 ms deep copy.

## Copy-on-hit correctness argument (the crux)
The cache stores a deep copy it makes itself (`put` copies before storing) and
hands out a deep copy (`get` returns `mesh.copy()`) on every hit. No caller ever
shares an object with the cache, so mutating a returned mesh (units
`scale_mesh_to_mm`, DFM/analysis touches, decimation) can never corrupt the
cached copy or any other caller. On a MISS the caller receives the freshly
parsed original — byte-identical to pre-cache behavior — while the cache retains
an independent copy. Therefore cache-enabled and cache-disabled produce
byte-identical geometry and cost output. This is proven by
`tests/test_mesh_parse_cache.py`:
- `test_step_hit_equals_cold_but_distinct` — hit geometry equals a cold parse
  (same vertices/faces, exact volume, exact bounds) but is a distinct object.
- `test_mutating_returned_mesh_does_not_corrupt_cache` — scale a returned mesh
  ×25.4, re-fetch, assert the cached mesh is still UNSCALED.
- `test_cost_output_identical_enabled_vs_disabled` — `/validate/cost/demo`
  decision JSON is identical across a miss, a served hit, and a disabled run.

## Bounds + opt-out
- Capped by BOTH entry count (`MESH_PARSE_CACHE_MAX_ENTRIES`, default 16) and
  approximate resident bytes (`MESH_PARSE_CACHE_MAX_BYTES`, default 256 MiB =
  vertex+face array nbytes summed), evicting least-recently-used first. Never
  unbounded. Proven by `test_eviction_by_entry_count`, `test_lru_recency_on_get`,
  `test_eviction_by_bytes`.
- Opt-out: `MESH_PARSE_CACHE_DISABLED=1` restores exactly today's behavior (no
  cache). Default is ENABLED. Proven by `test_disabled_switch_skips_cache`.
- Thread-safety: a single `threading.Lock` guards get/put; the expensive parse
  runs OUTSIDE the lock. Two racing requests at worst both re-parse (last put
  wins with an independent copy) — never corruption.

## Real cold-vs-warm numbers (single container)
From `outputs/perf-proof/mesh-cache-2026-07-08.txt`, genuine
`time.perf_counter()` measurements (no extrapolation), part = the committed
185,308-face `tests/assets/cube.step`:

- cold (miss, gmsh/OCC tessellation): **4.14 s**
- warm (hit, deep copy): **3.15 ms best / 4.56 ms avg (N=10)** → ~1314× on hit
- verify-flow burst (same part, 3 endpoints): parses ONCE (3.88 s), then
  `/validate/cost` and `/validate/preview-mesh` served from cache at ~2.6 ms
  each — 3.88 s total vs ~12.4 s if each endpoint re-parsed.

## Honest limitation
This is a PER-PROCESS cache: each uvicorn worker / replica has its own copy;
there is no cross-worker or cross-replica sharing. A user's burst that lands on
different workers can still re-parse once per worker. Cross-worker sharing would
require the existing blob store / redis and is out of scope here. The cache is
also purely opportunistic — cold-start and single-shot parses see today's
latency; the win is entirely on repeat parses of the same bytes.
