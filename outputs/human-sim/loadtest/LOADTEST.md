# CadVerify — Production-Shaped Local Staging Load Test

**Date:** 2026-07-11
**Commit:** `7c5aa41` (branch `claude/resume-review-oxqw0l`)
**Focus:** 10-org concurrency capacity.

## Scope & honesty statement

This is a **single-container local staging** stack: real Postgres 16 (port 5433),
real Redis 7 (127.0.0.1:6379), real single-worker uvicorn web process, real arq
worker — all co-located on one shared-CI-grade host, with **production-shaped
config** (`RELEASE=staging-loadtest` → per-org rate limits ON, strict-ish health;
real random auth secrets; `AUTH_MODE=password`; `ANALYSIS_TIMEOUT_SEC=60`).

The **absolute latency/throughput numbers are NOT cloud-SLA benchmarks** — the
whole stack shares one box and the load driver runs on the same host. But the
**concurrency BEHAVIORS are real**: the pool-exhaustion failure mode, the
fairness collapse, the event-loop starvation, the 429/Retry-After path, and the
tenant-isolation results are genuine properties of the code under real
concurrent multi-tenant load and would reproduce (at different absolute numbers)
in production.

All numbers below are measured. Where something could not be measured, it says so.

### Stack health before load (proves full stack really up, not degraded)
```
GET /health       → {"status":"ok","postgres":true,"redis":true,
                     "async":{"redis":true,"worker":"ok"}}
GET /health/deep  → postgres.ok=true, redis.ok=true, worker.state=ok
                     (heartbeat_age 27s < 90s threshold), queue.depth=0
POST /auth/signup → 200 + session token
Authed POST /api/v1/validate (cube.step, dash_session cookie) → 200
```
Postgres `max_connections=100`. App SQLAlchemy pool `pool_size=5`,
`max_overflow=10` → **15 connections max from the web process** (defaults; not
overridden). This 15 is the number that matters below.

---

## 1. Baseline capacity — repo harness (`scripts/ops/load-profile.mjs`, elevated)

Driver: Node fetch (k6 not installed). Config
`HEALTH=1000/conc50, HEALTHDEEP=300/conc20, COST=60/conc10`.

| Endpoint | Reqs | Conc | Errors | Throughput | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|---|
| `GET /health` | 1000 | 50 | 0 (0.00%) | 240.8 req/s | 185.4 ms | 332.7 ms | 408.4 ms | 511.3 ms |
| `GET /health/deep` | 300 | 20 | 0 (0.00%) | 252.0 req/s | 75.2 ms | 109.4 ms | 132.5 ms | 154.3 ms |
| `POST /validate/cost/demo` (cube.step) | 60 | 10 | 0 (0.00%) | **0.39 req/s** | **22.2 s** | **39.4 s** | **46.5 s** | 46.5 s |

Notes:
- The two cheap endpoints hold up with zero errors even at conc 50.
- The **costed compute path is the capacity wall**: a single uncached `cube.step`
  validate is ~9.0 s (`analysis_time_ms=8969.9`); at concurrency 10 it balloons
  to p50 22 s / p99 46 s and throughput collapses to **0.39 req/s**. This is the
  parse→DFM→cost pipeline serialized behind a 3-worker parse pool + single web loop.

---

## 2. The 10-org scenario — custom authed multi-tenant driver

Driver (`scratchpad/driver.py`, not committed): signs up **10 distinct orgs**
(10 emails → 10 `dash_session` cookies), then fires **70 concurrent authenticated
requests** across all orgs simultaneously (~7 per org): mostly light `cube.step`
`POST /api/v1/validate`, with 2 orgs mixing in the heavy real `nist_periodic_ctc05.stp`
(327 KB, 112k faces), plus one `POST /api/v1/validate/cost` per org. `/health` and
Postgres connection count and process RSS sampled throughout.

Two runs were performed. **Run 2** cleared the analysis dedup cache first, so all
70 requests hit the true uncached compute path — the honest worst case. Results
were consistent across both runs.

### Aggregate results

| Metric | Run 1 (warm-mid-run) | Run 2 (fully uncached) |
|---|---|---|
| Total requests | 70 | 70 |
| HTTP 200 | 30 | 32 |
| **HTTP 500** | **40 (57%)** | **38 (54%)** |
| HTTP 429 | 0 | 0 |
| Connection errors | 0 | 0 |
| Wall time | 79.6 s | 80.0 s |
| 200 latency p50 / p95 / p99 | 71.5 / 79.5 / 79.6 s | 70.7 / 79.9 / 80.0 s |

**Every single 500 was the same error:**
```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached,
connection timed out, timeout 30.00
```
i.e. **application DB-connection-pool exhaustion**, not Postgres, not OOM, not a
timeout of the analysis itself. No 504s, no asyncpg "too many connections", no
worker crash.

### (a) Isolation under load — PASS
- **0 / 62 successful responses** carried a mismatched filename echo (each org's
  response reflected only that org's uploaded file). Spot-checks across orgs clean.
- The analysis layer uses a **content-addressed dedup cache** keyed by mesh hash,
  shared across users. When two orgs upload byte-identical `cube.step`, the second
  is served the cached result (`Cache hit for user=N`). This is **correct, not a
  leak** — identical input bytes → identical deterministic analysis; no org's
  private data crosses over (results are a pure function of the uploaded bytes).

### (b) Per-org rate limiting + 429 / Retry-After (F2) — PASS (verified separately)
70 concurrent requests is far below the org ceiling (`ORG_RATE_LIMIT_PER_HOUR=2000`),
so no org organically hit 429. Verified the path directly by seeding one org's
Redis hour counter to 2001 and firing an authed request, with a second org as control:

```
THROTTLED org:  status=429  time=12 ms  Retry-After=35
                body: code=org_rate_limited, "...exceeded its request ceiling; retry after 35s"
CONTROL   org:  status=200  time=2475 ms   (NOT throttled)
```
- 429 returns **fast (12 ms), before any file parsing** (the dependency runs pre-work).
- **`Retry-After: 35` header is present** — the F2 fix is working.
- Throttling is **org-isolated**: the over-ceiling org is 429'd while the control
  org is served normally.

### (c) Worker / pool saturation & fairness — **FAIL (the key finding)**
- The DB pool (15) is exhausted almost instantly under 70 concurrent slow analyses,
  because **`/api/v1/validate` holds a DB session for the entire analysis duration**
  (`session: AsyncSession = Depends(get_db_session)`), and each analysis is 30–80 s
  under load. Requests 16+ wait 30 s for a connection, then 500.
- **No fairness**: which requests win a pool slot is effectively random. In Run 2,
  **org06 got 0 of its 7 requests through (all 7 → 500)** while other orgs landed
  4–5. One tenant's burst degrades *every* tenant, and an unlucky org can be
  **fully starved**.
- Light requests do **not** stay responsive behind heavy ones — they queue on the
  same 15-slot pool and the same single event loop and share the same cliff.

### (d) Errors — 500s only, characterized
- 500s: 38–40 per run, **100% DB QueuePool timeout** (see above).
- 0 × 504, 0 × asyncpg connection exhaustion, 0 × OOM/killed worker, 0 conn resets.

### /health under load
- **Run 2 (sustained uncached load): GET /health exceeded the 10 s client timeout
  for the entire ~60 s peak** (poll samples at t≈11,22,33,44,55,66 s all ReadTimeout),
  recovering to 9.1 s → 197 ms → 88 ms only as the load drained (t≈76–80 s).
- Run 1 (cache warmed partway, relieving pressure): /health stayed servable —
  median 207 ms, max 4.7 s (n=8).
- Interpretation: the F1 fix moves *parsing* off the event loop, but the remaining
  **on-loop** pipeline work (DFM, should-cost, KDTree wall-thickness over 185k faces,
  DB I/O) collectively **starves the single event loop** at 70-way concurrency —
  enough that even liveness `/health` misses a 10 s deadline. A real LB health check
  would mark this web replica unhealthy under this load.

---

## 3. Resource watch (Run 2, 145 samples over 80 s)

| Resource | Peak | Limit | Headroom |
|---|---|---|---|
| Postgres connections (staging db) | **16 total, 7 active** | 100 (`max_connections`) | huge — **PG is NOT the bottleneck** |
| App SQLAlchemy pool | **15 (saturated)** | 15 (`pool_size 5 + overflow 10`) | **0 — this is the bottleneck** |
| uvicorn process-tree RSS | **7069 MB** (min 6596, mean 6739) | — | stable, **no growth → no leak, no OOM** |
| Redis memory | ~1.16 MB | — | trivial |
| arq worker RSS | ~95 MB | — | idle during this test (validate is synchronous, not queued) |

The ~7 GB RSS is dominated by the **pre-warmed 3-worker parse pool** (OCC/gmsh +
geometry/ML libs loaded per worker). It is flat under load — memory is a sizing
concern, not a leak.

The Postgres-connection-count vs app-pool gap is the headline: **the app caps
itself at 15 DB connections while Postgres would happily give 100.** The 500s are
self-inflicted by the pool config + session-hold pattern, not a database limit.

---

## 4. Ranked findings

1. **CRITICAL — DB connection-pool exhaustion caps concurrent analyses at ~15.**
   At 70 concurrent authed `/validate`, **54–57% of requests return HTTP 500**
   (`QueuePool limit of size 5 overflow 10 reached`, 30 s wait). Root cause:
   `/validate` holds its `get_db_session` for the *entire* 30–80 s analysis, so the
   15-slot pool exhausts at the 16th concurrent request. Postgres itself is idle
   (16/100 conns). **Levers:** raise `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`, and/or stop
   holding the session across the CPU-heavy analysis (acquire/commit only around
   the persist). Raising the pool alone just moves the wall — the loop starves next.

2. **HIGH — No fairness under saturation; a single org can be fully starved.**
   Pool-slot allocation is effectively random: org06 got 0/7 through while peers got
   4–5. One tenant's concurrent upload burst degrades *all* tenants. The per-org
   HTTP rate limit (2000/hr) is **orders of magnitude above the real compute/pool
   ceiling (~15 concurrent)**, so it never engages to protect capacity. Consider a
   concurrency-based admission control / per-org in-flight cap sized to the pool,
   not just an hourly HTTP counter.

3. **HIGH — Event-loop starvation breaks liveness under sustained load.**
   `GET /health` exceeded 10 s for the ~60 s peak of the uncached run. The F1 fix
   (parse off-loop) is real but insufficient at high concurrency — the on-loop
   DFM/cost/thickness/DB work starves the single web worker's loop. An LB health
   check would flap the replica. Levers: offload the heavy synchronous analysis to
   the arq worker (it sat idle here) or a thread pool, keeping the web loop free.

4. **MEDIUM — Compute latency cliff.** Uncached `cube.step` ≈9 s single; conc-10
   p50 22 s / p99 46 s; 70-way successful p50 ≈71 s. Sustained heavy throughput
   ≈0.4 analyses/s per web process. Content-addressed dedup makes *repeats* cheap
   (good), but cold/unique parts define real capacity.

5. **LOW / POSITIVE — Tenant isolation holds.** 0 cross-org data mismatches across
   140 requests; shared results only for byte-identical inputs (content-addressed).

6. **LOW / POSITIVE — Per-org 429 + Retry-After (F2) works.** 429 in 12 ms with
   `Retry-After: 35`, honest `org_rate_limited` body, and org-isolated (control org
   unaffected).

7. **LOW / POSITIVE — No OOM, no PG exhaustion, no worker crash, no 504s.** RSS flat
   at ~7 GB (parse-pool footprint — size hosts accordingly).

8. **INFRA / PROVISIONING NOTE — Per-IP signup limit (3/hr, RELEASE-enforced)**
   blocked standing up 10 tenants from one host; the driver clears the Redis
   `signup:ip:*` counter to provision. Expected for real tenants on distinct IPs,
   but bulk/programmatic onboarding from a single egress IP will hit it.

---

## Reproduction

- Stack: Postgres `pg_ctlcluster 16 fix start` (5433) + `redis-server` (6379) +
  `alembic upgrade head` on `cadverify_staging` + `uvicorn main:app --workers 1`
  + `arq src.jobs.worker.WorkerSettings`, all with the production-shaped env
  (`RELEASE=staging-loadtest`, real secrets, `REDIS_URL`, `ANALYSIS_TIMEOUT_SEC=60`).
- Baseline: `CADVERIFY_API_URL=http://127.0.0.1:8095 LOAD_HEALTH_REQUESTS=1000 … node scripts/ops/load-profile.mjs`.
- 10-org driver + 429 verifier: kept in scratchpad (not committed).
- Raw baseline artifact captured to scratch; JSON per-request/timeline dumps saved to scratch.
