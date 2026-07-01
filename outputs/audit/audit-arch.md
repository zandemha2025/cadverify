# CadVerify — Platform Architect / Production-Readiness Audit

**Lens:** what is genuinely production-grade vs demoware / fragile / stubbed, from an
architecture + reliability-at-scale point of view.
**Date:** 2026-07-01.
**Method:** read the backend source; ran the cost engine on real corpus parts under
`cProfile` + `/usr/bin/time -l` + `resource.getrusage`; inspected the running processes,
Postgres, Redis, health endpoint, migrations, CI config, deploy scaffolding, and the
batch/webhook/reconstruction/job pipelines; ran the architecture-lens test modules. Every
claim below cites the file/command that proves it. I did **not** try to judge whether the
cost/DFM *numbers* are correct — that is a different lens and needs a real manufacturing
engineer (flagged at the end).

---

## THE ONE-LINE READ

The engine and the API/persistence layer are **real, well-structured code with a genuine test
suite and a correct deploy topology** — but the platform has **one catastrophic scaling defect
(the geometry engine allocates ~19 GB of RAM on an ordinary 37k-face part)** and a cluster of
"looks-wired, isn't-running" gaps (no Redis, no worker, a health check that lies, in-memory rate
limiting) that mean **the async half of the product — batch, webhooks, image-to-mesh — is
non-functional in the currently-running deployment, and the synchronous half would OOM-kill its
own server on the first real production CAD file.**

---

## THE HEADLINE RISK (read this first)

### P0 — The geometry engine's memory scales super-linearly and OOMs on ordinary parts.
Measured, not theorized (`resource.getrusage` around `GeometryContext.build`):

| Part | Faces | Peak RSS | Wall time |
|------|------:|---------:|----------:|
| baseline (imports+load) | — | 85 MB | — |
| `amrikarisma_Mazduino_Bottom_case_v2.stl` (473 KB) | 9,472 | **2,345 MB** | ~2 s |
| corpus `d48a089e…stl` (1.9 MB) | 36,702 | **19,331 MB** | 12.3 s |
| corpus `d778703c…stl` (79 MB) | ~1.5 M | — | **timed out > 120 s** |

Root cause: `src/analysis/context.py::_compute_wall_thickness` fires one inward ray **per face**
with `multiple_hits=True` through `mesh.ray.intersects_location`, and **no fast ray backend is
installed** (`pyembree=False`, `embreex=False` — verified), so trimesh falls back to the
pure-Python `RayMeshIntersector` (`trimesh/ray/ray_triangle.py`), which materialises enormous
(rays × candidate-triangles) intermediate arrays. The profiler confirms the hot frames are
`ray_triangle_id`, `ray_triangle_candidates`, and `rtree index.intersection` (4.96 M `_get_ids`
calls on the 9k-face part).

It gets worse because the guard is **backwards**: `RAYCAST_SAMPLE_THRESHOLD` defaults to
**50,000** (`context.py:34-40`), so the bounded/sampled KDTree path only engages *above* 50k
faces. The entire dangerous zone — ~10k–50k faces, which is *most real CAD* — runs the
un-sampled, unbounded path. The 37k-face part (19 GB) is squarely in that zone.

Why this is fatal in production:
- **`fly.toml` provisions `memory = "1gb"`** per machine. The engine needs 2 GB for a tiny part
  and 19 GB for a normal one. The web machine OOM-kills on essentially the first real upload.
- Analysis runs **in-process in the web worker** via `loop.run_in_executor(None, …)`
  (`analysis_service.py:283-290`), so the OOM takes down the whole web machine and every
  concurrent request with it.
- The 60 s `ANALYSIS_TIMEOUT_SEC` guard is **cooperative-only**: `asyncio.wait_for` cancels the
  *await*, but Python cannot kill the executor thread, so the thread keeps allocating toward OOM
  *after* the client already got its 504. A handful of mid-size uploads = guaranteed OOM.
- `MAX_TRIANGLES` allows **2,000,000** faces (`upload_validation.py:27`). There is **no mesh
  decimation anywhere** (grep for `decimat|simplify_quadric|subdivide` = 0 hits). A 2M-face
  upload is accepted and fed straight into the 19-GB-at-37k engine.

**Fix direction (all three needed):** install `embreex` (fast, low-memory ray backend);
drop `RAYCAST_SAMPLE_THRESHOLD` to ~5,000 (or make it memory-aware); and move analysis out of
the web process into a separate, memory-capped, cgroup-limited worker so an OOM kills one job,
not the API. This is the single biggest thing standing between the demo and "survives one real
user."

---

## REAL — works, verified how

- **The synchronous analysis + cost engine is real and IP-local.** Ran the cost CLI on real
  parts: full 18-process DFM feasibility matrix + itemized should-cost with provenance +
  make-vs-buy crossover in ~2 s for a small part, "zero network calls". Not a mock.
- **Persistence + migrations are real and clean.** 7 Alembic migrations
  (`0001`→`0007`); live DB is at head `0007` (`alembic current` == `alembic heads`). Real
  Postgres schema with proper indexes, a partial unique index on `share_short_id`
  (`postgresql_where=…`), a dedup `UniqueConstraint(user_id, mesh_hash, process_set_hash,
  analysis_version)`, JSONB result storage. Postgres is up and the app is connected
  (`/health` → `postgres:true`, verified via a running query).
- **The mesh-hash dedup cache is real and the IntegrityError race is correctly handled.**
  `analysis_service.run_analysis` hashes raw bytes *before* parsing, checks the dedup key, and on
  a concurrent-insert `IntegrityError` rolls back and re-queries the winning row
  (`analysis_service.py:390-415`). Both `run_analysis` and `run_quick_analysis` implement it.
- **The batch pipeline is real code (not a stub) and well-modeled.** ULID-keyed `batches` /
  `batch_items` / `webhook_deliveries` tables, a coordinator that drip-feeds items respecting a
  per-batch `concurrency_limit`, priority ordering, cursor pagination, CSV streaming export,
  cancel semantics, ZIP path-traversal guard (`os.path.basename`), and **atomic** counter
  increments via raw `UPDATE … SET completed_items = completed_items + 1`
  (`batch_service.py:363-379`) — no read-modify-write race. Ownership checks return 404-not-403.
- **Webhooks are real and correctly built.** Stripe-style `t=…,v1=hmac_sha256` signing,
  timing-safe verification, replay-window rejection, exponential backoff `[10,30,90,270,810]s`
  with jitter, 5-attempt cap (`webhook_service.py`). This is production-grade design.
- **Idempotent job enqueue.** `ArqJobQueue.enqueue` uses the idempotency key as the arq job id
  and short-circuits on an existing DB row (`arq_backend.py:36-59`).
- **A substantial, passing test suite.** 68 backend test files; the architecture-lens subset
  (batch tasks/service, webhook service, reconstruction, dedup, jobs, analysis_service) is
  **85 passed in 0.34 s**. Tests cover the race path, webhook signing, batch counters,
  path-traversal, etc.
- **Deploy topology is correct on paper.** `fly.toml` defines *separate* `web`
  (`uvicorn … --workers 2`) and always-on `worker` (`arq src.jobs.worker.WorkerSettings`)
  processes, a `release_command` running `alembic upgrade head`, and per-role auto-stop.
  `docker-compose.yml` wires backend + worker + Postgres 16 (with healthcheck) + Redis. The CI
  pipeline builds/pushes a Docker image to Fly and deploys on `main`.
- **Structured error envelope.** Stable error codes with `doc_url`s (`errors.py`), broken
  geometry → `400 GEOMETRY_INVALID` not a 500, oversize → `413`, timeout → `504`.
- **Good security-hygiene CI gates.** `check_route_auth.py` asserts every `/api/v1/*` handler
  has `require_api_key`; a `sentry-leak-grep` job fails the build if `cv_live_…` ever appears in
  a captured Sentry payload. These are thoughtful.
- **The eval/corpus system is real and honestly gated.** 667 real parts in
  `data/corpus/manifest.jsonl`; `src/eval/run.py` refuses to emit headline accuracy until ≥30
  human labels exist and stamps everything `PROVISIONAL`/`SMOKE` until then. Labeling is a
  local-only tool gated behind `LABELING_ENABLED=1` so CAD never egresses.

---

## STUBBED / FRAGILE — looks done, isn't

### F-ARCH-1 — The whole async tier is non-functional in the running deployment (no Redis, no worker).
- Redis is **down**: `localhost:6379` refuses connections (verified via socket), no `redis-server`
  process, no `arq` worker process (only `uvicorn` + `next-server` are running).
- `REDIS_URL` is **unset** in the live backend's env (`ps eww` on pid 31026).
- Consequence: `POST /api/v1/batch` commits the `Batch` row and *then* calls `get_arq_pool()`,
  which I confirmed **raises `ConnectionError` after retries** with no Redis. So a batch created
  right now is committed as `pending`, the enqueue 500s, and the batch is **orphaned forever** in
  `pending` (no worker, no coordinator, no cleanup sweep). Same for reconstruction jobs.
- There is **no in-memory / synchronous fallback** for job execution despite the health check
  pretending one exists (see F-ARCH-2). Batch, webhooks, and image-to-mesh are only reachable in
  a full docker-compose/Fly deploy — none of which is what's actually running.

### F-ARCH-2 — `/health` lies about Redis.
`health.py:42-44`: if `REDIS_URL` is unset or `memory://`, the probe sets `checks["redis"] = True`
unconditionally and returns `status:ok`. That is exactly the current state — Redis is down, yet
`/health` returns `{"status":"ok","redis":true}`. A load balancer or uptime monitor would **never
detect the outage**, and the async tier would silently swallow every job. A health check that
reports a dead dependency as healthy is worse than no health check.

### F-ARCH-3 — Rate limiting is in-memory and per-worker (ineffective).
`rate_limit.py:31`: `storage_uri = os.getenv("REDIS_URL", "memory://")`. With `REDIS_URL` unset
(current state) and `uvicorn --workers 2`, each worker keeps its **own** counter, so a client
gets Nx the intended limit and every limit resets on restart/redeploy. Real distributed rate
limiting requires the Redis backend that isn't running.

### F-ARCH-4 — Image-to-mesh reconstruction is a hosted-API integration, not a local model, and can't run here.
- `torch` and `tsr` (TripoSR) are **not installed** (verified). So `LocalTripoSR` cannot run at
  all in this environment.
- The default backend is `remote` (`reconstruction_service.py:20`), i.e. `RemoteTripoSR` →
  **Replicate's hosted `stability-ai/triposr`**, which hard-requires a paid `REPLICATE_API_TOKEN`
  (`remote_triposr.py:36-38` raises `RuntimeError` without it). No token is set.
- The reconstruction *code* (image validation, blob storage, confidence scoring, arq job,
  polling) is real and reasonable — but "image-to-mesh" is **not a self-hosted capability**; it's
  an outbound dependency on a third-party GPU API that (a) isn't wired up and (b) sends customer
  images to Replicate (an ITAR/data-residency problem the moment a real defense/aero customer
  appears). The confidence score (`scoring.py`) is a legitimate heuristic on the *output* mesh,
  not a validation of reconstruction *correctness*.

### F-ARCH-5 — S3 batch input is a `NotImplementedError`.
`batch_tasks.py:218-220`: the `s3` input mode raises `NotImplementedError("S3 item fetch not yet
implemented")`. The `POST /batch` endpoint *advertises* `s3_bucket`/`s3_prefix`/`manifest_url`
(`batch_router.py:44-46,106-112`) and will happily create the batch — which then fails on every
item when the coordinator runs. Half-built path that looks like a feature.

### F-ARCH-6 — The batch coordinator pins one DB connection for up to 4 hours.
`run_batch_coordinator` opens a single session and holds it open in a `while True: … await
asyncio.sleep(2)` loop for the life of the batch (worker `job_timeout`/registration ≈ 4 h),
calling `session.refresh(batch)` every 2 s (`batch_tasks.py:35,68-122`). The engine is
`pool_size=5` with default overflow (`db_engine.py:45-49`). So **5 concurrent batches exhaust the
worker's entire connection pool**, and the per-item tasks (which also need sessions) starve. The
coordinator is also a busy-poll (DB round-trip every 2 s per batch) rather than event-driven.

### F-ARCH-7 — Tests and CI run against SQLite, not Postgres/Redis.
`conftest.py:32-34` defaults `TEST_DATABASE_URL` to `sqlite+aiosqlite://`; `ci.yml` installs only
`pip install pytest httpx`, spins up **no `services:` (no Postgres, no Redis)**, and runs
`pytest -v` + `pytest tests/test_migration_*.py`. So:
- The 0.34 s suite runtime is because it's unit-level against in-memory SQLite with auth
  auto-bypassed (`_bypass_api_key_auth`, autouse).
- **Postgres-only behavior is never exercised in CI**: JSONB queries, the partial unique index on
  `share_short_id`, the `text()` raw-SQL counter increments, real `IntegrityError` semantics, and
  the migrations themselves (which declare `JSONB`, `postgresql_where`, etc.). A migration or query
  that's valid on SQLite but broken on Postgres would pass CI green and break in prod. This is
  false confidence, not coverage.
- `pyright` typecheck is `continue-on-error: true` (non-blocking).

### F-ARCH-8 — The running app is a large, uncommitted working-tree diff.
Last commit is `2026-06-18` (13 days stale). The working tree has **74 files changed
(+4,936 / −5,086)**, 30 deletions, and 61 untracked files — a whole frontend dashboard
restructure (`(dashboard)/*` and `dashboard/*` routes deleted, `components/instrument/*` added)
plus backend edits (`analysis_service`, `routes`, `db/models`, `auth/*`, `alembic/env.py`) sitting
uncommitted. There is no checkpoint of the state that's actually running, can't bisect, can't PR-
review, and one `git checkout .` loses ~2 weeks of work. (The prompt's "nothing committed" is an
overstatement — there are 302 commits — but the *current running state* is unversioned.)

### F-ARCH-9 — ZIP is fully buffered in memory before the size check.
`batch_router.py:78-79`: `zip_bytes = await file.read()` reads the **entire** upload into RAM,
*then* compares to `BATCH_MAX_ZIP_BYTES` (default **5 GB**). A single 5 GB (or malicious) upload is
resident in memory before rejection; `extract_zip_to_items` then holds the whole thing plus the
extracted files. Combined with the 1 GB Fly machines, this is a trivial memory-DoS. Also,
`os.path.basename` de-duplication means two zip entries `a/part.stl` and `b/part.stl` collapse to
one filename and silently overwrite.

---

## MISSING — gaps to be a credible enterprise platform

- **No horizontal-scale story for the engine.** It's CPU- and memory-bound, in-process, single-
  threaded per request, un-decimated, with a memory profile that OOMs a normal box. Before any of
  the below matters, the engine must run in a bounded, cancellable, resource-capped worker with
  mesh decimation and a fast ray backend. (See P0.)
- **No real observability.** Only stdlib `logging` + optional Sentry error capture + a `request_id`
  tag (`middleware.py`, `main.py:84`). **No metrics** (no Prometheus/StatsD), **no tracing** (no
  OpenTelemetry), no per-process latency/percentile/queue-depth/OOM dashboards, no alerting. You
  cannot see p95 analysis time, queue backlog, webhook failure rate, or memory pressure. For an
  enterprise buyer this is table stakes and it's absent.
- **No dead-letter / sweeper for stuck work.** Orphaned `pending` batches (F-ARCH-1), webhook
  `next_retry_at` rows (the `ix_webhook_deliveries_retry` index exists but nothing sweeps it — all
  retries ride on arq `_defer_by`; if the deferred job is lost, the retry is lost), and jobs stuck
  in `processing` have no reconciliation loop. There is a retry index but no reaper.
- **No blob-storage abstraction / lifecycle.** Batch and reconstruction blobs are written to a
  local `BATCH_BLOB_DIR` / `RECON_BLOB_DIR` on the worker's filesystem (`batch_tasks.py:214`,
  `reconstruction_service.py`). No object store (S3 is stubbed), no retention/GC, no cross-machine
  access — so on Fly's multi-machine, ephemeral-disk model, the web machine that later serves the
  result mesh may not have the file the worker machine wrote. Storage is not durable or shared.
- **No autoscaling / backpressure / queue-depth limits.** `arq max_jobs=12`, `concurrency_limit`
  default 10, but nothing rejects or sheds load when the queue is deep; a large batch just piles
  up. No priority isolation between interactive analysis and batch grind.
- **Connection-pool sizing is a single hardcoded `pool_size=5`** with no env override and no
  separate sizing for web vs the connection-hungry coordinator (F-ARCH-6).
- **No integration/load test tier.** Everything is unit-level on SQLite. There is no test that
  exercises API → Postgres → Redis → arq worker → webhook end-to-end, and no load test establishing
  throughput/latency/memory envelopes. So "reliability at scale" is entirely unmeasured.
- **CI does not gate on the real database or on the engine's resource envelope.** No Postgres/Redis
  service containers, no memory/timeout regression test on a representative mesh. The 19 GB
  behavior would sail through CI.
- **SOC2 / ITAR / data-residency controls absent** (audit_log table exists and is real, which is a
  start) — but reconstruction ships customer imagery to Replicate, blobs sit on local disk
  unencrypted, and there's no tenancy isolation beyond `user_id` row scoping.

---

## WHAT BREAKS WITH REAL USERS / VOLUME (prioritized)

| Pri | Failure | Trigger | Blast radius |
|-----|---------|---------|--------------|
| **P0** | OOM kill of the web machine | Any real CAD upload >~15k faces (37k → 19 GB) | Whole web machine + all in-flight requests; not cancellable |
| **P0** | Async tier silently dead | Redis/worker not running (current state), `/health` still says OK | Batch/webhooks/reconstruction never execute; batches orphaned in `pending`; no alert |
| **P1** | Connection-pool exhaustion | ≥5 concurrent batches (coordinator pins 1 conn each, pool=5) | Item processing starves; batches hang |
| **P1** | Rate limits ineffective | Multi-worker deploy with in-memory limiter | Abuse controls bypassed (Nx limit); reset on redeploy |
| **P1** | Memory-DoS via upload | 5 GB ZIP or 2M-face STL (no decimation) | Buffered fully in RAM before rejection → OOM |
| **P2** | Prod-only query/migration break | Postgres-specific SQL untested in CI (SQLite) | Green CI, red prod |
| **P2** | Lost result blobs | Worker writes blob on machine A, web serves from machine B | 404 on completed results in multi-machine deploy |
| **P2** | Reconstruction unavailable / data-egress | No `REPLICATE_API_TOKEN`; or, once set, images leave to Replicate | Feature 500s, or ITAR/data-residency violation |

---

## NEEDS REAL-HUMAN / OPS VALIDATION (cannot self-certify)

These are correctness/operational questions I can *find* but not *answer* from code alone:

1. **Load/soak test on real hardware** — the only way to convert my single-part memory numbers
   into a capacity plan. *What to run:* the corpus's face-count distribution through the API
   against a real Postgres+Redis+worker Fly deploy, measuring p50/p95 latency, peak RSS, OOM rate,
   and queue depth vs concurrency. *What to decide:* machine memory sizing, `RAYCAST_SAMPLE_THRESHOLD`,
   and whether embreex alone fixes it. (I've shown it *will* break; the exact envelope needs a run.)
2. **Do the DFM/cost numbers survive the new fast-ray/sampled path?** If you install embreex or
   lower the sample threshold to fix the memory bomb, wall-thickness/draft results may shift.
   *Ask a manufacturing engineer:* are the recomputed thickness/draft values still right? (This is
   the cost-correctness lens's gate; flagging that my perf fix touches their numbers.)
3. **Disaster/outage runbook review** — an SRE should confirm behavior when Redis dies mid-batch,
   when the worker crashes with jobs in `processing`, and when a webhook target is down for hours.
   Today there's no reconciliation loop; a human needs to decide the recovery policy.

---

## TOP-5 FIX ORDER (my recommendation)

1. **(P0) Contain the engine's memory:** install `embreex`, set `RAYCAST_SAMPLE_THRESHOLD≈5000`,
   add mesh decimation on ingest, and move analysis into a memory-capped, killable subprocess/worker
   (not the web thread pool). Add a memory/latency regression test on a 40k-face fixture in CI.
2. **(P0) Make the async tier real or fail loud:** run Redis + the arq worker (they're already in
   `docker-compose`/`fly.toml`), fix `/health` to actually probe Redis and 503 when it's down, and
   make `POST /batch` reject (not orphan) when the queue is unreachable.
3. **(P1) Fix rate limiting + pool sizing:** require the Redis storage backend for the limiter in
   prod; make `pool_size` env-driven; make the batch coordinator event-driven or at least not hold a
   connection open for hours.
4. **(P1) Real CI:** add Postgres + Redis service containers so migrations and PG-only SQL are
   actually tested; add one true end-to-end (API→worker→webhook) integration test.
5. **(P1) Commit the working tree** and re-establish a versioned, reviewable baseline; then add
   metrics/tracing (OTel + a metrics endpoint) so scale problems are visible before they page you.
