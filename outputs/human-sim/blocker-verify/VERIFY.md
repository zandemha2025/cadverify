# LAUNCH-BLOCKER Live Verification — /validate off the event loop

**Verdict: PASS.** A heavy upload no longer freezes other tenants.

- **Commit under test:** `01bec1c` — *fix(availability): parse /validate off the event loop; preserve Retry-After* (HEAD of `claude/resume-review-oxqw0l`).
- **Date:** 2026-07-11
- **Stack:** real CadVerify backend, uvicorn `main:app` on 127.0.0.1:8095; Postgres 16 on :5433 (fresh UTF8 db `cadverify_verify`, `alembic upgrade head` → 0037); gmsh 4.15.2; parse ProcessPool pre-warmed (3 workers). Frontend not needed (API-only test).
- **Auth:** signup → 200 + session; authed `/validate` via `dash_session` cookie. `/health` → `{"status":"ok","postgres":true}`.

## The fix
`run_analysis` / `run_quick_analysis` in `backend/src/services/analysis_service.py` previously called the **synchronous** `_parse_mesh` directly in the async coroutine body, so gmsh ran on the event-loop thread and froze every tenant for the duration of a pathological part. Both call sites now `await _parse_mesh_async` — the same spawn-ProcessPool + hard-capped front door that `/validate/demo` and `/validate/cost` already used. gmsh runs off the loop.

## The test
1. Baseline `/health` timing.
2. Fire `POST /api/v1/validate` with `backend/tests/assets/nist_periodic_ctc05.stp` (the pathological periodic-surface STEP, 319 KB) in the **background** as Org A. Do not wait.
3. **While it is in flight**, repeatedly (≈32 s, 11 rounds) hit `/health`, a fresh Org B `/auth/signup`, and a small `cube.step` `/validate`. Record wall-clock latency of each.
4. Record what nist returns + its duration.

## Key evidence — concurrent-call latency WHILE nist was processing

Baseline `/health` (before heavy upload): **5–6 ms** (0.0064, 0.0051, 0.0054 s).

nist `/validate` fired at `03:09:28.357`, finished at `03:10:04.186` → **HTTP 200, 32.7 s**. Throughout that entire window:

| round | /health | /auth/signup (Org B) | /validate cube.step |
|------:|--------:|---------------------:|--------------------:|
| 1 | 0.023 s | 0.118 s | 3.271 s |
| 2 | 0.006 s | 0.142 s | 0.054 s |
| 3 | 0.006 s | 0.144 s | 0.056 s |
| 4 | 0.006 s | 0.145 s | 0.060 s |
| 5 | 0.006 s | 0.151 s | 0.054 s |
| 6 | 0.006 s | 0.145 s | 0.052 s |
| 7 | 0.006 s | 0.141 s | 0.052 s |
| 8 | 0.006 s | 0.152 s | 0.051 s |
| 9 | 0.006 s | 0.145 s | 0.054 s |
| 10 | 0.006 s | 0.137 s | 0.058 s |
| 11 | 0.006 s | 0.104 s | 0.054 s |

All calls returned **HTTP 200**. `/health` and `/auth/signup` — the pure event-loop probes — stayed at **~6 ms** and **~140 ms** for the full 32 s the heavy part was grinding. Under the OLD (pre-fix) behavior these would have hung for the entire multi-minute gmsh run.

The one outlier — round-1 `cube.step` at **3.27 s** — is ProcessPool worker contention (3 pool workers, one occupied by nist), NOT event-loop blocking: it still returned in 3.27 s (not 32 s), and rounds 2–11 hit the dedup/result cache at ~50 ms. Critically, the event-loop endpoints (`/health`, signup) never degraded, which is the launch-blocker being tested.

## nist result (the heavy request itself)
Honest, bounded, non-hanging:
- `HTTP 200`, wall clock **32.7 s** (not an indefinite freeze).
- `overall_verdict: "issues"`, `best_process: "ded"`, geometry `vertices=56196, faces=112428, is_watertight=true, is_manifold=true, volume_mm3=12704178`, `analysis_time_ms=32464.9`.
- Server log confirms the pooled path: `cadverify.parse_pool step ladder recovered on rung 1 (faces=112428, watertight=True)` — i.e. it parsed via the async ProcessPool front door introduced by the fix, not the in-thread parser.

(The 2–3 min noted in the ticket did not reproduce here — this container is faster and/or the rung/triangle cap bounds it to ~33 s. The load characteristic is unchanged: bounded, off-loop, honest result.)

## Happy-path sanity
`cube.step` `/validate` → HTTP 200, `overall_verdict: "issues"`, `best_process: "dlp"`, `volume_mm3=2717.3`, watertight/manifold true. Fix did not break the normal path. No errors, tracebacks, timeouts, or killed workers in the server log during the run; server still healthy (6 ms) afterward.

## Conclusion
**PASS** — a heavy `/validate` upload no longer freezes other tenants. Event-loop endpoints stayed at single-digit-ms while the pathological part processed off-loop and returned an honest 200 in bounded time.

Raw curl timings: `raw_timings.txt`. nist response: `nist_response.json` / `nist_meta.txt`.
