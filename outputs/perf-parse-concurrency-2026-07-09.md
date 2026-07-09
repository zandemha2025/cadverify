# Parallel STEP/IGES parsing via a process pool — design, safety, real numbers

**Date:** 2026-07-09 · **Host:** single-container, x86_64, 4 CPUs, Python 3.11 ·
**Proof artifact:** [`outputs/perf-proof/parse-concurrency-2026-07-09.txt`](perf-proof/parse-concurrency-2026-07-09.txt)

## The problem (measured)

gmsh/OCC STEP/IGES tessellation is CPU-bound. Worse, it is serialized **twice**
in one process:

1. the **GIL** — pure-Python around the tessellation still contends; and
2. `step_mesher._GMSH_LOCK` — gmsh has a single process-global, non-thread-safe
   context, so every parse holds a process-wide lock.

So `_parse_mesh_async` running `_parse_mesh` in the default `ThreadPoolExecutor`
serializes concurrent DISTINCT parts: the load smoke showed ~16s p50 for 4
concurrent 185k-face parts vs ~4s single. The measured thread path here confirms
it: **4 parts take 16.6s ≈ 3.7× a single 4.4s part** — no parallelism at all.

## Design

Only the **pure, expensive, picklable tessellation** is extracted to a
module-level worker entry, `src/parsers/parse_pool.py::tessellate(data, suffix)`.
It does ONLY the raw gmsh/OCC (or STL) parse — no cache, no triangle cap, no
`HTTPException`; it raises plain exceptions the parent maps to the usual codes.

Everything else stays in the **main process** (`routes.py`), unchanged in meaning:

| Stage | Where | Why |
|---|---|---|
| suffix gate | main | cheap |
| `validate_magic` | main | **security gate** — never ship un-validated untrusted bytes to a worker |
| mesh-cache lookup / put / deep-copy-on-hit | main | a warm hit must NEVER touch the pool |
| `enforce_triangle_cap` | main | per-REQUEST policy (MAX_TRIANGLES read per call) |
| raw STEP/IGES tessellation | **pool** | the CPU-bound, GIL-/gmsh-lock-bound work |
| raw STL parse | main (in-thread) | sub-second; pickle round-trip would exceed the parse |

**Pool:** a lazily-created module-level singleton
`ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn"))`.
Workers = `min(cpu_count-1, 8)`, env-overridable via `PARSE_POOL_WORKERS`.
`cpu-1` leaves a core for the event loop so the box stays responsive under a burst.

**Kill switch:** `PARSE_PROCESS_POOL_DISABLED=1` → today's exact in-thread path
(`_parse_mesh` in the thread executor). Default ENABLED.

## Safety story (SAFETY OVER SPEED)

- **spawn, never fork.** Forking a running asyncio process inherits held locks and
  event-loop fds and can deadlock; `spawn` starts a clean interpreter. Enforced by
  `multiprocessing.get_context("spawn")`.
- **Robust fallback.** On `BrokenProcessPool` (a worker segfaults on adversarial
  gmsh input) `submit_async` **recycles the pool AND parses this request in-thread**,
  so the caller still gets a correct mesh — never a 500. Subsequent requests use the
  freshly recreated pool. (Test: `test_broken_pool_falls_back_in_thread` asserts a
  byte-correct mesh, not a 500.)
- **Timeout.** The `asyncio.wait_for → 504` is preserved. A running pool worker
  cannot be cancelled mid-C-tessellation (`future.cancel()` returns False once it is
  running), so on timeout the route **recycles the pool**: `shutdown(wait=False,
  cancel_futures=True)` + drop the singleton, so the next request gets a fresh,
  healthy pool immediately and the runaway is not leaked. (Test:
  `test_timeout_returns_504_and_recycles`.)

Three-line safety argument: **spawn** avoids fork/asyncio deadlock; **any** pool
failure (broken worker) transparently falls back to an in-thread parse so the user
always gets a correct result, never a 500 or hang; **timeout** still returns 504 and
recycles the pool so a runaway C tessellation is reclaimed rather than leaked.

## Correctness (the crux)

A pooled parse is **byte-identical** to the in-thread parse — same
`step_to_trimesh_from_bytes`, round-tripped through pickle:
`test_pool_matches_in_thread_byte_identical` asserts equal vertices, faces, volume
(full precision), and bounds; `test_pooled_async_matches_in_thread` asserts the same
through the real async route. The cache composes (`test_warm_cache_hit_never_
dispatches_to_pool`), the cap still 400s on the pooled path
(`test_triangle_cap_enforced_on_pooled_path`), STL never goes to the pool
(`test_stl_parsed_in_thread_not_pooled`), and the kill switch never even builds the
pool (`test_kill_switch_bypasses_pool`).

## Real concurrency numbers (`time.perf_counter`, this container)

Single part, pooled (warm): **4.435s** (194,454 faces).
Pickle round-trip of that mesh: **dumps 2.2ms + loads 0.8ms**, 8.17 MB blob ≈
**0.07% of the parse** — the boundary cost is negligible vs seconds to tessellate.

| K distinct parts | ThreadPool wall | ProcessPool wall | speedup | waves (K/3) |
|---|---|---|---|---|
| 3 | 12.507s (2.82× single) | **5.193s** (1.17× single) | **2.41×** | 1 |
| 4 | 16.556s (3.73× single) | **8.585s** (1.94× single) | **1.93×** | 2 |

With **K ≤ workers** (K=3, 3 workers) the pool finishes 3 parts in ~one single-part
time (5.2s ≈ 1.17× single) — exactly the goal. With **K > workers** (K=4) it takes
`ceil(4/3)=2` waves (~8.6s), still ~1.9× faster than threads.

## Honest limits

- **Per-process pool.** Like the mesh cache, each uvicorn worker / replica has its
  own pool; no cross-process sharing.
- **spawn startup cost.** The first pooled submit pays a one-time ~5s spawn+import
  (gmsh/OCC import) per worker, amortized over the process lifetime. A production
  deployment can pre-warm on startup.
- **Container CPU count.** 4 CPUs → 3 workers → the demonstrated ceiling is ~3×
  (K ≤ 3). More CPUs widen it; **on a 1-CPU box workers=1 and there is no win** — the
  bench prints that honestly and the concurrency test skips below 3 CPUs.
- **Timeout can't hard-kill a mid-flight C tessellation.** We recycle the pool
  (soft: the runaway worker finishes its current job then exits) rather than
  `SIGKILL` the worker, deliberately, so we never break sibling in-flight requests
  sharing the pool. The next request always gets a fresh pool.
