# Phase 7: Async SAM-3D - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area -- see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 7` if desired)

<domain>
## Phase Boundary

This phase enables users to opt into SAM-3D semantic segmentation as an async background job, returning results via polling -- without blocking the synchronous `/validate` path. The existing heuristic segmenter remains the default; SAM-3D is an opt-in upgrade that produces higher-quality manufacturing feature segments.

Deliverables:
1. `backend/src/jobs/` module with `JobQueue` protocol abstraction + arq backend implementation.
2. arq `WorkerSettings` entrypoint that loads SAM-3D model at startup and processes jobs.
3. `POST /api/v1/validate?segmentation=sam3d` async branch: persists sync analysis immediately, enqueues SAM-3D job, returns 202 with `{analysis_id, job_id, poll_url}`.
4. `GET /api/v1/jobs/{id}` polling endpoint returning status transitions and result URL on completion.
5. SAM-3D model weights pre-baked into the worker Docker image (no cold-start download).
6. Embedding cache in blob storage (Fly volume) keyed by mesh hash.
7. Idempotent job keying: duplicate enqueue for same mesh+params returns existing job.
8. Worker visibility timeout >= 10 min with ack-on-completion semantics.
9. Graceful fallback to heuristic segmentation on SAM-3D failure; job marked `partial` not `failed`.

**Explicitly out of scope for this phase:**
- Webhooks for job completion (v2 -- SDK-04)
- Frontend async UX / progress indicators (Phase 8 polish or separate follow-up)
- GPU-backed synchronous SAM-3D (v2 -- ADV-01)
- SAM-3D model fine-tuning or custom training
- Job queue for non-SAM-3D workloads (PDF rendering, mesh repair are sync in their phases)
- Worker autoscaling beyond min-1 machine

</domain>

<decisions>
## Implementation Decisions

### Task Queue Library (ROADMAP research flag #1)

- **D-01:** Use **arq 0.27** with Redis as the job queue backend, wrapped in a thin `JobQueue` protocol so a future swap to TaskIQ or Celery is a single adapter rewrite.
  - **Rationale:** arq is already wired into the project: docker-compose has `worker` service with `arq src.jobs.worker.WorkerSettings`, Phase 6 fly.toml defines dual entrypoints (uvicorn + arq), and research STACK.md selected arq with HIGH confidence. arq is asyncio-native (~700 LOC), ergonomic with FastAPI, and stable despite maintenance-mode status. TaskIQ is the emerging alternative but has less production mileage. At beta scale with one job type (sam3d), arq is the right choice. The `JobQueue` protocol wrapper de-risks the maintenance-mode concern.
  - **Recommended default chosen in auto mode:** arq 0.27 with protocol wrapper.

- **D-02:** `JobQueue` protocol defines: `enqueue(job_type, params, idempotency_key) -> job_id`, `get_status(job_id) -> JobStatus`, `cancel(job_id) -> bool`. arq adapter implements this. All callers go through the protocol, never import arq directly.
  - **Rationale:** Research ARCHITECTURE.md specifies this pattern: "jobs/ (task definitions) vs services/ (business logic) -- arq tasks are thin adapters." Protocol abstraction means swapping arq for TaskIQ later touches one file, not the whole codebase.

### SAM-3D Model Weights (ROADMAP research flag #2)

- **D-03:** Use **SAM-2 Hiera Small** checkpoint (~150 MB) as the default model. Pre-bake weights into the Docker image at build time via a `COPY` from a build-context directory or a multi-stage download layer.
  - **Rationale:** SAM-2 is Apache-2.0 licensed (Meta, `facebookresearch/segment-anything-2`). No license encumbrance for distribution. The Hiera Large checkpoint (~2.5 GB) would blow the 1.2 GB image budget (Phase 6 D-02). Hiera Small balances quality vs image size. Hiera Tiny (~40 MB) is an option if Small proves too large -- leave as a planner/researcher decision.
  - **Provenance:** Official Meta checkpoint from `https://github.com/facebookresearch/segment-anything-2`. Apache-2.0. No LGPL, no GPL, no restrictive clauses.

- **D-04:** Model weights stored at `/app/models/sam2_hiera_small.pt` inside the image. `SAM3D_MODEL_PATH` env var defaults to this path. Override possible for custom weights.
  - **Rationale:** Pre-baking avoids Pitfall 6 (cold-start download on ephemeral Fly machines). The env var override preserves flexibility for development (point to local checkout) or future model upgrades.

### Worker Architecture

- **D-05:** Worker entrypoint: `backend/src/jobs/worker.py` exports `WorkerSettings` (arq convention). Worker loads SAM-3D model into memory at startup (module-level singleton). Job functions are thin adapters that call `segment_sam3d()` from the existing pipeline.
  - **Rationale:** Research ARCHITECTURE.md: "Load once at worker startup; pin min-1-worker-running." Module-level singleton matches the existing `_backbone` pattern in `segmentation/sam3d/pipeline.py`. Model load happens once, not per-job.

- **D-06:** Worker runs min-1 machine on Fly with `auto_stop_machines = false` for the worker process group. Visibility timeout set to 10 minutes (arq `job_timeout`). Jobs use ack-on-completion semantics (arq default).
  - **Rationale:** Pitfall 6 prescribes: disable auto-stop for workers, visibility timeout >> max job duration (60s inference), ack-on-completion prevents lost jobs on crash. Cost: ~$5/mo for a persistent worker machine at beta scale.

- **D-07:** Job processing flow: (1) Dequeue job from Redis, (2) load mesh bytes from analysis (via `analysis_id` FK), (3) parse mesh with trimesh, (4) run `segment_sam3d()`, (5) on success: write `result_json` to `jobs` row, set status=`done`, (6) on SAM-3D failure: run `segment_heuristic()` fallback, write fallback result, set status=`partial`, (7) update `completed_at` timestamp.
  - **Rationale:** SAM-08 requires graceful fallback -- never `failed` from the user's perspective. The heuristic fallback (`segmentation/fallback.py`) already exists and is CPU-only. Writing to the `jobs` row (not `analyses.result_json`) keeps SAM-3D results separate from the sync analysis.

### Async Submit Endpoint

- **D-08:** `POST /api/v1/validate?segmentation=sam3d` runs the normal sync analysis pipeline first (geometry checks, process scoring, etc.), persists the result as an `analyses` row, then enqueues a SAM-3D job linked via `jobs.analysis_id`. Returns HTTP 202 with:
  ```json
  {
    "analysis_id": "01HYX...",
    "job_id": "01HYZ...",
    "poll_url": "/api/v1/jobs/01HYZ...",
    "result": { ... sync analysis result ... }
  }
  ```
  - **Rationale:** SAM-02 specifies this flow. The user gets immediate sync results (geometry checks, process scores) and can poll for the enhanced segmentation. This is strictly additive -- the sync path is not degraded.

- **D-09:** Idempotent job keying: jobs are keyed by `(analysis_id, job_type)`. If a job already exists for that analysis + type, return the existing `job_id` instead of enqueuing a duplicate.
  - **Rationale:** SAM-06 requires idempotency. Prevents duplicate work when a client retries the request. Keying by `analysis_id` (not mesh_hash) is simpler and sufficient -- the analysis already dedups by mesh hash (Phase 3 D-11).

### Job Status Polling

- **D-10:** `GET /api/v1/jobs/{id}` returns:
  ```json
  {
    "job_id": "01HYZ...",
    "status": "running",
    "job_type": "sam3d",
    "created_at": "2026-04-15T12:00:00Z",
    "started_at": "2026-04-15T12:00:01Z",
    "completed_at": null,
    "result_url": null
  }
  ```
  On completion (`status: "done"` or `"partial"`):
  ```json
  {
    "job_id": "01HYZ...",
    "status": "done",
    "result_url": "/api/v1/jobs/01HYZ.../result",
    "completed_at": "2026-04-15T12:01:05Z"
  }
  ```
  - **Rationale:** SAM-03 specifies this endpoint. Status transitions: `queued -> running -> done` (or `partial`). `result_url` appears only on completion. Separate `/result` endpoint keeps the status response lightweight.

- **D-11:** `GET /api/v1/jobs/{id}/result` returns the full SAM-3D segmentation result (the `result_json` from the `jobs` row). Returns 404 if job not complete.
  - **Rationale:** Separating status from result keeps polling cheap. The result payload can be large (segment arrays with face indices).

- **D-12:** Jobs endpoint is auth-protected: only the owning user can see their jobs. Returns 404 (not 403) for other users' jobs to prevent enumeration.
  - **Rationale:** Consistent with Phase 3 D-21 (analyses endpoint returns 404 for other users). ULID-based IDs prevent sequential enumeration (Pitfall 11).

### Embedding Cache

- **D-13:** SAM-3D embedding cache uses the Fly volume at `/data/blobs` (Phase 6 D-09), keyed by mesh hash (SHA-256 of vertices+faces, matching the existing `sam3d/cache.py` `_mesh_hash` function). Stored as JSON files.
  - **Rationale:** Pitfall 6 says no `/tmp` for worker caches. The existing `sam3d/cache.py` module already implements content-addressable caching with JSON serialization. Migrating it from `/tmp/cadverify_sam3d_cache` to `/data/blobs/sam3d_cache` requires changing the default `SAM3D_CACHE_DIR` env var.

- **D-14:** For production, `SAM3D_CACHE_DIR` defaults to `/data/blobs/sam3d_cache` (Fly volume). For local dev, defaults to `/tmp/cadverify_sam3d_cache` (existing behavior). The env var override handles both cases.
  - **Rationale:** Local dev doesn't need persistent cache. Production needs it to survive worker restarts.

### Claude's Discretion

The following are left to the researcher/planner to resolve with standard patterns:

- Exact arq `WorkerSettings` configuration (max_jobs, job_timeout, health_check_interval, retry settings).
- Whether to add a `GET /api/v1/analyses/{id}/segmentation` convenience endpoint that reads from the linked job result.
- Exact SAM-2 Hiera Small checkpoint filename and download URL for the Dockerfile `ADD` or `COPY` step.
- arq Redis connection pool configuration (reuse Phase 2 Redis or separate database number).
- Worker health check endpoint shape (Pitfall 6 mentions `{"status":"ok","jobs_in_progress":N}`).
- How mesh bytes are passed to the worker (re-read from blob storage vs inline in job params vs re-fetch from analysis).
- SAM-3D result serialization format in `jobs.result_json` (reuse existing `SemanticSegment` schema or flatten).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase-level requirements and roadmap
- `.planning/ROADMAP.md` "Phase 7: Async SAM-3D" -- goal, success criteria, key deliverables, suggested plans (7.A-7.C), parallel-track rationale, risks.
- `.planning/REQUIREMENTS.md` "Async SAM-3D" (SAM-01..08) -- locked requirements for JobQueue, 202 endpoint, polling, pre-baked weights, embedding cache, idempotency, visibility timeout, graceful fallback.
- `.planning/PROJECT.md` "Key Decisions" -- SAM-3D async only (30-60s inference unsuitable for sync HTTP).

### Pitfalls research
- `.planning/research/PITFALLS.md` "Pitfall 6: Async worker state desync on Fly Machines" -- visibility timeout, ack-on-completion, persistent storage, pre-baked weights, idempotent jobs, disable auto-stop for worker.
- `.planning/research/PITFALLS.md` "Pitfall 1" -- image size concerns when baking SAM-3D weights.
- `.planning/research/PITFALLS.md` "Performance Traps" table -- model weights re-loaded per job anti-pattern.

### Stack and architecture research
- `.planning/research/STACK.md` "Job Queue -- arq (with abstraction layer)" -- arq selection rationale, maintenance-mode caveat, `JobQueue` protocol pattern, deployment as separate process group.
- `.planning/research/ARCHITECTURE.md` "Queue library: arq" -- architecture decision, job service pattern, worker entrypoint, thin adapter pattern for arq tasks.
- `.planning/research/ARCHITECTURE.md` file tree -- `jobs/queue.py`, `jobs/worker.py` placement.

### Existing SAM-3D code (to integrate with)
- `backend/src/segmentation/sam3d/` -- full pipeline: `pipeline.py` (orchestrator), `backbone.py` (SAM-2 wrapper), `config.py` (env-var config), `cache.py` (content-addressable cache), `renderer.py`, `lifter.py`, `classifier.py`.
- `backend/src/segmentation/sam3d_segmenter.py` -- legacy entry point delegating to `sam3d` package.
- `backend/src/segmentation/fallback.py` -- heuristic segmenter (`segment_heuristic()`) used as graceful fallback.

### Prior phase context (dependencies)
- `.planning/phases/03-persistence-analysis-service-history-caching/03-CONTEXT.md` -- D-17: `jobs` table schema (already migrated), D-07/D-08: `analysis_service` function module pattern, D-09: mesh hash algorithm.
- `.planning/phases/06-packaging-deploy-observability-docs/06-CONTEXT.md` -- D-04: single image dual entrypoint (uvicorn + arq), D-06: docker-compose worker service, D-08: Fly processes config, D-09: Fly volume at `/data`.

### Existing infrastructure to integrate with
- `backend/src/db/models.py` lines 142-173 -- `Job` ORM model with ULID, status, params_json, result_json, analysis_id FK.
- `backend/src/services/analysis_service.py` -- pipeline orchestration; the SAM-3D async branch hooks in after `run_analysis()` completes.
- `docker-compose.yml` -- worker service already configured with `arq src.jobs.worker.WorkerSettings`.
- `backend/alembic/versions/0002_create_analyses_jobs_usage_events.py` -- jobs table already created.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`segmentation/sam3d/pipeline.py` `segment_sam3d()`**: Complete pipeline orchestrator (cache check, render views, SAM-2 masks, 2D-to-3D lifting, classification). Worker job calls this directly.
- **`segmentation/sam3d/backbone.py` `SAM2Backbone`**: Lazy-loaded singleton with `load()` and `generate_masks()`. Already handles missing SAM-2 library gracefully.
- **`segmentation/sam3d/cache.py`**: Content-addressable cache with `get(mesh, cache_dir)` / `put(mesh, segments, cache_dir)`. Reuse with updated `SAM3D_CACHE_DIR`.
- **`segmentation/fallback.py` `segment_heuristic()`**: CPU-only heuristic segmenter. Ready to use as the graceful fallback when SAM-3D fails.
- **`segmentation/sam3d/config.py` `SAM3DConfig`**: Env-var-driven config (enabled, model_path, cache_dir). Extend for worker-specific settings.
- **`db/models.py` `Job` class**: ORM model already defined with all needed columns. No schema migration needed.
- **`analysis_service.py` `run_analysis()`**: Returns analysis result + persists to DB. The async branch calls this first, then enqueues the SAM-3D job.
- **`docker-compose.yml` worker service**: Already wired to run `arq src.jobs.worker.WorkerSettings`.

### Established Patterns
- **Env-var feature gating**: `SAM3D_ENABLED` env var controls pipeline availability. Worker sets this to `true`; web process can leave it `false`.
- **Module-level singleton**: `pipeline.py` `_backbone` singleton pattern. Worker job reuses this -- no per-job model loading.
- **Thin adapter pattern**: Research ARCHITECTURE.md says arq tasks are thin adapters calling service functions. Job function calls `segment_sam3d()`, not raw pipeline steps.
- **ULID for public IDs**: Phase 3 established ULID pattern for analyses and jobs.

### Integration Points
- New module: `backend/src/jobs/` with `__init__.py`, `queue.py` (JobQueue protocol + arq adapter), `worker.py` (WorkerSettings + task functions), `tasks.py` (task definitions).
- `backend/src/api/routes.py` -- `validate_file()` gains `segmentation` query param; async branch enqueues job after sync analysis.
- New route: `GET /api/v1/jobs/{id}` and `GET /api/v1/jobs/{id}/result` in a new `jobs_router`.
- `backend/src/segmentation/sam3d/config.py` -- update default `cache_dir` to `/data/blobs/sam3d_cache`.
- `backend/Dockerfile` -- add SAM-2 checkpoint download/copy step in builder stage.
- `backend/fly.toml` -- ensure worker process has `auto_stop_machines = false`.
- `backend/requirements.txt` -- add `arq>=0.27.0` (may already be present from Phase 6 wiring).

</code_context>

<specifics>
## Specific Ideas

- The sync analysis result is returned immediately in the 202 response -- the user is never left waiting for the async job to see their core DFM feedback. SAM-3D segmentation is a quality enhancement layered on top.
- Worker model loading at startup means the first job after deploy has no cold-start penalty for inference. The only latency is the inference itself (~30-60s).
- The `partial` status for fallback results is important UX: the user still gets segmentation data (heuristic), but the UI can indicate it was not the full SAM-3D quality. This is better than `failed` which implies no data.
- Idempotency keying by `(analysis_id, job_type)` means a user cannot accidentally queue two SAM-3D jobs for the same analysis. The second request gets back the existing job_id and poll_url.
- The existing `sam3d/cache.py` uses geometry-based hashing (vertices+faces), not file-bytes hashing. This is correct for the embedding cache because the same geometry from different file formats should share embeddings.

</specifics>

<deferred>
## Deferred Ideas

- **Webhooks for job completion** -- v2 SDK-04. Polling is sufficient for beta.
- **Frontend async UX** -- progress indicators, "SAM-3D processing" badge, side-by-side heuristic vs SAM-3D comparison. Could be Phase 8 polish or a separate follow-up.
- **GPU-backed synchronous SAM-3D** -- v2 ADV-01 (paid tier only).
- **Job queue for PDF rendering** -- Pitfalls mentions this as a good idea. Not in Phase 7 scope; PDF rendering is fast enough sync for beta.
- **Worker autoscaling** -- scale worker machines based on queue depth. Not needed at beta volume (one worker handles ~60 jobs/hour at 60s each).
- **SAM-2 Hiera Large model** -- better quality but ~2.5 GB. Defer until GPU workers are available or image size budget increases.
- **Job cancellation** -- `JobQueue.cancel()` is in the protocol but implementation can be deferred. Users rarely cancel inference jobs.

</deferred>

---

## Gray Areas Resolved in Auto Mode -- Summary Table

| # | Gray area | Auto-selected default | Decision ID(s) |
|---|-----------|----------------------|----------------|
| 1 | Task queue library (arq vs TaskIQ) | arq 0.27 with `JobQueue` protocol wrapper | D-01, D-02 |
| 2 | SAM-3D model weights (size/license/provenance) | SAM-2 Hiera Small (~150 MB), Apache-2.0, Meta official, pre-baked | D-03, D-04 |
| 3 | Worker architecture (processing flow, startup) | Model loaded at startup; thin adapter tasks; ack-on-completion; min-1 always-on | D-05, D-06, D-07 |
| 4 | Async submit endpoint (202 response shape) | Sync analysis first, then enqueue SAM-3D; return both analysis + job IDs | D-08, D-09 |
| 5 | Job status polling (endpoint shape, transitions) | GET /api/v1/jobs/{id} with status + result_url; separate /result endpoint | D-10, D-11, D-12 |
| 6 | Embedding cache backend (filesystem vs blob) | Fly volume at /data/blobs/sam3d_cache; env-var override for local dev | D-13, D-14 |

## Decisions the User Should Revisit Before `/gsd-plan-phase 7`

1. **D-03 (SAM-2 Hiera Small over Hiera Large).** Hiera Small (~150 MB) fits the image budget but produces lower-quality masks than Hiera Large (~2.5 GB). If segmentation quality is critical for beta, consider Hiera Base (~350 MB) as a middle ground. The existing `backbone.py` accepts any checkpoint path, so switching is trivial.

2. **D-07 (Mesh bytes retrieval in worker).** The job processing flow assumes the worker can retrieve mesh bytes. Options: (a) store original file bytes in blob storage during sync upload (adds Phase 3 scope), (b) pass file bytes inline in arq job params (Redis payload size limit ~512 MB, but wasteful), (c) re-upload is required for SAM-3D (bad UX). Left to Claude's Discretion -- the planner should resolve this based on what Phase 3/5 actually implemented for file storage.

3. **D-06 (min-1 always-on worker).** Costs ~$5/mo on Fly. If budget is tight, `auto_stop_machines = "suspend"` with 5-minute keep-alive is an alternative (adds ~30s cold start for first job after idle). The trade-off is cost vs latency.

---

*Phase: 07-async-sam-3d*
*Context gathered: 2026-04-15*
*Mode: --auto (all gray areas resolved with recommended defaults; see each D-## "Rationale" line)*
