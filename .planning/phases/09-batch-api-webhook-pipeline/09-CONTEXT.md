# Phase 9: Batch API + Webhook Pipeline - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area -- see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 9` if desired)

<domain>
## Phase Boundary

This phase enables enterprise customers to submit large batches of CAD parts (ZIP archives or S3 bucket references with CSV manifests) for parallel DFM analysis, receive results via webhook callbacks, and track progress in real time. Target use case: Saudi Aramco processing millions of legacy parts.

Deliverables:
1. `POST /api/v1/batch` endpoint accepting ZIP archive upload or S3 bucket reference with CSV manifest.
2. Batch job orchestrator: decompress/fetch, validate manifest, enqueue each part for parallel analysis via arq.
3. Webhook dispatch service: POST callback on each item completion and batch completion with structured payload and exponential backoff retry.
4. `GET /api/v1/batch/{id}` progress endpoint with real-time counts (total, completed, failed, in-progress).
5. Per-tenant concurrency configuration (max parallel workers per batch).
6. Postgres schema additions: `batches` and `batch_items` tables.
7. Frontend batch progress dashboard with per-item status drill-down.

**Explicitly out of scope for this phase:**
- Real-time streaming progress via WebSockets/SSE (polling is sufficient for batch workflows)
- Batch scheduling/recurring batches (future phase)
- Batch-level pricing or usage-based billing (deferred per PROJECT.md)
- Multi-tenant queue isolation (separate Redis instances per tenant) -- soft limits only
- Batch result PDF aggregation report (individual PDFs via Phase 4 are reused)
- CLI or SDK for batch submission (deferred to SDK-01/SDK-02)

</domain>

<decisions>
## Implementation Decisions

### Batch Input Format

- **D-01:** `POST /api/v1/batch` accepts two input modes:
  1. **ZIP upload** -- multipart/form-data with a ZIP archive containing CAD files (STEP/STL) plus an optional CSV manifest mapping filenames to per-part parameters (process types, rule pack).
  2. **S3 reference** -- JSON body with `{"s3_bucket": "...", "s3_prefix": "...", "manifest_url": "..."}` pointing to files already in S3.
  - **Rationale:** BATCH-01 requires both ZIP and S3. ZIP is simpler for customers with <10k parts. S3 is mandatory for Saudi Aramco's 14M parts (shipping 14M files over HTTP is infeasible). Supporting both modes on the same endpoint keeps the API surface small. S3 integration uses `boto3` with IAM role credentials or customer-provided access keys stored per-tenant.

- **D-02:** CSV manifest schema:
  ```csv
  filename,process_types,rule_pack,priority
  bracket.stl,"fdm,sla",aerospace,normal
  housing.step,"cnc_3axis,cnc_5axis",,high
  ```
  Columns: `filename` (required, matches ZIP entry or S3 key), `process_types` (optional comma-separated, defaults to all), `rule_pack` (optional, defaults to none), `priority` (optional: `normal`|`high`, defaults to `normal`).
  - **Rationale:** CSV is universally accessible (Excel, Google Sheets, scripting). The manifest is optional for ZIP mode -- without it, all files in the ZIP are analyzed with default parameters. The `priority` column enables high-priority items to be enqueued first (processed before normal items in the arq queue). Keeping the schema minimal with only 4 columns reduces onboarding friction.

- **D-03:** When no CSV manifest is provided with a ZIP upload, the system auto-discovers all `.stl` and `.step`/`.stp` files in the archive (recursing into subdirectories) and analyzes each with default parameters (all processes, no rule pack, normal priority).
  - **Rationale:** Lowers the barrier for simple batch jobs. An enterprise uploading 500 STL files in a ZIP should not need to write a CSV for the common case.

### Batch Size Limits

- **D-04:** Limits enforced at batch submission:
  - Maximum **10,000 parts per batch** (items in manifest or files in ZIP).
  - Maximum **5 GB total ZIP upload size** (enforced via `Content-Length` check before streaming).
  - Maximum **100 MB per individual file** within the batch (consistent with existing single-file upload limit).
  - S3 mode has no total size limit (files are fetched individually by workers), but the 10,000 items-per-batch cap still applies.
  - **Rationale:** 10k parts per batch keeps the `batch_items` table manageable per batch and prevents a single batch from monopolizing the queue for days. For Saudi Aramco's 14M parts, they submit ~1,400 batches (parallelizable). The 5 GB ZIP limit prevents memory exhaustion during decompression on Fly machines (1-2 GB RAM). S3 mode bypasses this because files are fetched one at a time by workers. These limits are configurable via env vars: `BATCH_MAX_ITEMS`, `BATCH_MAX_ZIP_BYTES`, `BATCH_MAX_FILE_BYTES`.

- **D-05:** Zip bomb protection: decompress with a streaming extractor that enforces per-file and total size limits. Use `zipfile.ZipFile` with `ZipInfo.file_size` pre-check before extraction. Reject archives with compression ratio > 100:1 on any single file.
  - **Rationale:** Pitfall 5 from v1.0 research (Zip bomb / pathological mesh DoS). The existing Phase 1 magic-byte validator runs on each extracted file. Streaming extraction avoids loading the full decompressed archive into memory.

### Concurrency Control

- **D-06:** Per-tenant concurrency limit controls how many batch items can be processed simultaneously. Default: **10 concurrent workers per tenant**. Configurable via a `tenant_concurrency_limit` column on the `users` table (or env var `DEFAULT_BATCH_CONCURRENCY` for global default).
  - **Rationale:** BATCH-06 requires per-tenant concurrency configuration. 10 concurrent items means a 10k-part batch completes in ~1000 rounds at ~5-10s per analysis = ~2-3 hours. This prevents one enterprise tenant from starving other users. The limit is enforced by the batch orchestrator (not arq itself) -- the orchestrator only enqueues up to N items at a time, feeding more as items complete.

- **D-07:** Batch orchestrator pattern: a **coordinator job** runs as a single arq task per batch. The coordinator:
  1. Extracts/fetches all files and validates the manifest.
  2. Creates all `batch_items` rows with status `pending`.
  3. Enqueues the first N items (up to concurrency limit) as individual arq tasks.
  4. As each item task completes (callback to coordinator), enqueues the next pending item.
  5. When all items complete, fires the batch-completion webhook and marks the batch `complete`.
  - **Rationale:** A coordinator job avoids a "thundering herd" where 10k arq tasks are enqueued at once (which would exhaust Redis memory and starve other job types). The coordinator drip-feeds work respecting the concurrency limit. This pattern is standard in batch processing systems (AWS Batch, Celery Canvas). The coordinator itself is lightweight (database operations only, no analysis compute).

- **D-08:** Individual item analysis reuses `analysis_service.run_analysis()` with the same hash-based dedup. If a part was previously analyzed (same file bytes + processes + engine version), the cached result is returned without re-running the pipeline.
  - **Rationale:** Enterprise customers re-uploading parts across batches (common in iterative workflows) should benefit from the existing dedup cache (Phase 3 D-11/D-12). This could reduce processing time dramatically for repeat uploads.

### Webhook Payload and Retry Policy

- **D-09:** Webhook configuration is per-batch (not per-tenant): `POST /api/v1/batch` accepts an optional `webhook_url` and `webhook_secret` in the request body. The secret is used to sign payloads via HMAC-SHA256 in an `X-CadVerify-Signature` header.
  - **Rationale:** Per-batch webhooks are more flexible than per-tenant -- different batches can callback to different services (QA system, ERP, monitoring). HMAC signing prevents spoofed callbacks. The pattern matches Stripe/GitHub webhook conventions.

- **D-10:** Webhook payload for **item completion**:
  ```json
  {
    "event": "batch_item.completed",
    "batch_id": "01HYX...",
    "item_id": "01HYZ...",
    "filename": "bracket.stl",
    "status": "completed",
    "verdict": "issues",
    "analysis_id": "01HYA...",
    "analysis_url": "/api/v1/analyses/01HYA...",
    "timestamp": "2026-04-15T12:01:05Z"
  }
  ```
  Webhook payload for **batch completion**:
  ```json
  {
    "event": "batch.completed",
    "batch_id": "01HYX...",
    "status": "completed",
    "summary": {
      "total": 500,
      "completed": 487,
      "failed": 13,
      "pass": 312,
      "issues": 175,
      "fail": 0,
      "duration_sec": 3421
    },
    "results_url": "/api/v1/batch/01HYX.../results",
    "timestamp": "2026-04-15T13:00:00Z"
  }
  ```
  - **Rationale:** Structured event types enable webhook consumers to filter/route. Including `analysis_id` + `analysis_url` in item events lets consumers fetch full results on demand without parsing the webhook body. The batch summary gives aggregate stats without requiring the consumer to count items. This mirrors the event-driven pattern used by Stripe and GitHub.

- **D-11:** Webhook retry policy: **exponential backoff with jitter**, 5 retries maximum. Delays: 10s, 30s, 90s, 270s, 810s (~13.5 min). A 2xx response from the webhook URL is considered success; anything else (4xx, 5xx, timeout, connection error) triggers retry. After 5 failures, the webhook is marked `failed` on the batch record and no further retries are attempted.
  - **Rationale:** Exponential backoff with jitter prevents thundering herd on the webhook consumer. 5 retries over ~23 minutes gives the consumer time to recover from transient outages. Matching industry standard patterns (Stripe retries 3 times over 48h, but our use case is more urgent). The retry state is tracked in a `webhook_deliveries` table for auditability.

- **D-12:** Webhook dispatch is fire-and-forget from the item processing perspective -- webhook failures never block batch progress. Webhook retries are processed by a separate arq task (`dispatch_webhook`) that reads from the `webhook_deliveries` table.
  - **Rationale:** Decoupling webhook delivery from analysis processing means a slow/down webhook endpoint cannot stall the entire batch. This is critical for the Saudi Aramco use case where batches contain thousands of items.

### Batch Status Model (DB Schema)

- **D-13:** New `batches` table:
  ```
  batches:
    id              BIGINT PRIMARY KEY (GENERATED ALWAYS AS IDENTITY)
    ulid            TEXT UNIQUE NOT NULL
    user_id         BIGINT NOT NULL FK(users.id ON DELETE CASCADE)
    api_key_id      BIGINT NULL FK(api_keys.id ON DELETE SET NULL)
    status          TEXT NOT NULL DEFAULT 'pending'
        -- pending, extracting, processing, completed, failed, cancelled
    input_mode      TEXT NOT NULL         -- 'zip' or 's3'
    manifest_json   JSONB NULL            -- parsed manifest (filename -> params)
    webhook_url     TEXT NULL
    webhook_secret  TEXT NULL              -- HMAC key for signing
    total_items     INTEGER NOT NULL DEFAULT 0
    completed_items INTEGER NOT NULL DEFAULT 0
    failed_items    INTEGER NOT NULL DEFAULT 0
    concurrency_limit INTEGER NOT NULL DEFAULT 10
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    started_at      TIMESTAMPTZ NULL
    completed_at    TIMESTAMPTZ NULL
  ```
  - **Rationale:** Denormalized counters (`total_items`, `completed_items`, `failed_items`) enable O(1) progress queries without counting `batch_items` rows. Status transitions: `pending -> extracting -> processing -> completed` (or `failed`/`cancelled`). `webhook_secret` is stored encrypted at rest (or as raw text for beta -- Claude's discretion on encryption implementation).

- **D-14:** New `batch_items` table:
  ```
  batch_items:
    id              BIGINT PRIMARY KEY (GENERATED ALWAYS AS IDENTITY)
    ulid            TEXT UNIQUE NOT NULL
    batch_id        BIGINT NOT NULL FK(batches.id ON DELETE CASCADE)
    filename        TEXT NOT NULL
    status          TEXT NOT NULL DEFAULT 'pending'
        -- pending, queued, processing, completed, failed, skipped
    process_types   TEXT NULL              -- comma-separated or NULL for all
    rule_pack       TEXT NULL
    priority        TEXT NOT NULL DEFAULT 'normal'
    analysis_id     BIGINT NULL FK(analyses.id ON DELETE SET NULL)
    error_message   TEXT NULL
    file_size_bytes BIGINT NULL
    duration_ms     REAL NULL
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    started_at      TIMESTAMPTZ NULL
    completed_at    TIMESTAMPTZ NULL
  ```
  Indexes: `(batch_id, status)` for progress queries, `(batch_id, created_at)` for ordered listing.
  - **Rationale:** Each batch item tracks its own lifecycle and links to the resulting `analyses` row via `analysis_id` FK. The `skipped` status handles files that fail validation (wrong format, over size limit) without failing the entire batch. `error_message` captures per-item failure reasons for debugging.

- **D-15:** New `webhook_deliveries` table:
  ```
  webhook_deliveries:
    id              BIGINT PRIMARY KEY (GENERATED ALWAYS AS IDENTITY)
    batch_id        BIGINT NOT NULL FK(batches.id ON DELETE CASCADE)
    event_type      TEXT NOT NULL          -- 'batch_item.completed', 'batch.completed'
    payload_json    JSONB NOT NULL
    status          TEXT NOT NULL DEFAULT 'pending'
        -- pending, delivered, failed
    attempts        INTEGER NOT NULL DEFAULT 0
    last_attempt_at TIMESTAMPTZ NULL
    next_retry_at   TIMESTAMPTZ NULL
    response_code   INTEGER NULL
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  ```
  - **Rationale:** Audit trail for webhook delivery. Enables retry logic and debugging ("why didn't our system receive the callback?"). Separate table keeps `batches` clean.

### Batch Upload Storage

- **D-16:** ZIP archives are extracted to a temporary directory during batch creation, then each individual file is stored in the Fly volume at `/data/blobs/batch/{batch_ulid}/{filename}`. After all items are enqueued, the temporary extraction directory is deleted. S3 mode does not store files locally -- workers fetch directly from S3.
  - **Rationale:** Reusing the existing Fly volume (`/data/blobs` from Phase 7 D-13) avoids introducing a new storage backend. Organizing by `batch_ulid/filename` keeps batch files isolated and enables easy cleanup. Workers need file bytes to pass to `analysis_service.run_analysis()` -- reading from the volume is fast. For S3 mode, workers use `boto3` to fetch directly, avoiding double-storage.

- **D-17:** Batch file cleanup: after a batch reaches terminal status (`completed`, `failed`, `cancelled`), a cleanup task deletes the `/data/blobs/batch/{batch_ulid}/` directory after a configurable retention period (default: 7 days, env var `BATCH_FILE_RETENTION_DAYS`).
  - **Rationale:** Fly volumes have limited space (typically 1-10 GB). Retaining files for 7 days allows re-processing or debugging. Automated cleanup prevents volume exhaustion. The retention period is a safety window, not permanent storage.

### Batch Result Aggregation

- **D-18:** `GET /api/v1/batch/{id}` returns progress and summary:
  ```json
  {
    "batch_id": "01HYX...",
    "status": "processing",
    "input_mode": "zip",
    "total_items": 500,
    "completed_items": 312,
    "failed_items": 3,
    "in_progress_items": 10,
    "pending_items": 175,
    "created_at": "2026-04-15T12:00:00Z",
    "started_at": "2026-04-15T12:00:05Z",
    "completed_at": null,
    "summary": null
  }
  ```
  On completion, `summary` is populated with aggregate stats (pass/issues/fail counts, avg duration, total duration).
  - **Rationale:** BATCH-04 requires real-time progress. Denormalized counters on the `batches` row make this a single-row SELECT. The `summary` field is null until completion, then computed once and cached on the row.

- **D-19:** `GET /api/v1/batch/{id}/items` returns paginated batch items (cursor-based, matching Phase 3 history pattern):
  ```json
  {
    "items": [
      {
        "item_id": "01HYZ...",
        "filename": "bracket.stl",
        "status": "completed",
        "verdict": "issues",
        "analysis_id": "01HYA...",
        "duration_ms": 4231.2,
        "error_message": null
      }
    ],
    "next_cursor": "01HYZ...",
    "has_more": true
  }
  ```
  Query params: `?status=failed` (filter), `?cursor=`, `?limit=50` (default 50, max 200).
  - **Rationale:** Cursor pagination (Phase 3 D-20 pattern) for consistent UX. Status filtering lets the frontend show "failed items only" drill-down. The response includes `analysis_id` so the frontend can link to the existing analysis detail view.

- **D-20:** `GET /api/v1/batch/{id}/results/csv` returns a downloadable CSV of all batch results:
  ```csv
  filename,status,verdict,best_process,issue_count,duration_ms,analysis_url,error
  bracket.stl,completed,issues,fdm,3,4231.2,/api/v1/analyses/01HYA...,
  housing.step,failed,,,,,,Invalid STEP file
  ```
  - **Rationale:** Enterprise customers need batch results in a format they can import into their PLM/ERP systems. CSV is universal. This is a convenience endpoint that reads from `batch_items` + linked `analyses` rows.

### Tenant Isolation

- **D-21:** Tenant isolation is via **soft concurrency limits** (D-06), not separate queues. All tenants share a single arq Redis instance and a single worker pool. The batch orchestrator enforces per-tenant concurrency by limiting how many items it enqueues at a time.
  - **Rationale:** Separate Redis instances or arq queues per tenant adds operational complexity disproportionate to beta needs. Soft concurrency limits achieve the same fairness goal. A single worker pool processes items from all tenants in FIFO order (with high-priority items enqueued ahead of normal). At enterprise scale, dedicated worker pools per tenant could be added as a future enhancement.

- **D-22:** Priority support: high-priority batch items are enqueued with arq's `_defer_by=0` and normal items with `_defer_by=1` (1-second defer). This ensures high-priority items are picked up first without a separate queue.
  - **Rationale:** The `priority` column in CSV manifest (D-02) maps to arq's built-in defer mechanism. Simple, no queue management overhead. True priority queues would require separate arq workers per priority level -- overkill for beta.

### Claude's Discretion

The following are left to the researcher/planner to resolve with standard patterns:

- Exact S3 credential management (customer-provided keys vs IAM role assumption per batch).
- Batch coordinator job's arq `job_timeout` value (should be generous -- hours, not minutes).
- Whether to add `PATCH /api/v1/batch/{id}` for cancellation or use `DELETE`.
- Exact webhook HMAC signature header format (follow Stripe's `t=timestamp,v1=signature` pattern or simpler).
- Frontend batch dashboard component design (table vs card layout, refresh polling interval).
- Whether `webhook_secret` needs encryption at rest in the `batches` table for beta.
- Batch cleanup task scheduling mechanism (cron arq job vs on-demand after completion + delay).
- Error handling for partial ZIP extraction (some files valid, some corrupt).
- S3 authentication flow (per-batch credentials in request body vs pre-configured tenant S3 settings).
- `usage_events` tracking for batch analyses (one event per item, or one per batch, or both).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase-level requirements and roadmap
- `.planning/ROADMAP.md` "Phase 9: Batch API + Webhook Pipeline" -- goal, success criteria, key deliverables, suggested plans (9.A-9.C), dependency on v1.0.
- `.planning/REQUIREMENTS.md` "Batch API + Webhook Pipeline" (BATCH-01..06) -- locked requirements for batch endpoint, manifest parsing, webhooks, progress tracking, dashboard, concurrency limits.
- `.planning/PROJECT.md` "Key Decisions" -- arq as job queue (validated), enterprise target Saudi Aramco (14M parts).

### Pitfalls research (from v1.0)
- `.planning/research/PITFALLS.md` "Pitfall 5" -- Zip bomb / pathological mesh DoS. Directly relevant to ZIP batch upload handling.
- `.planning/research/PITFALLS.md` "Pitfall 6" -- Async worker state desync on Fly. Relevant to batch coordinator and item worker patterns.
- `.planning/research/PITFALLS.md` "Performance Traps" -- Mesh-hash cache reuse pattern for batch dedup.

### Prior phase context (infrastructure this phase builds on)
- `.planning/phases/07-async-sam-3d/07-CONTEXT.md` -- D-01/D-02: arq 0.27 + `JobQueue` protocol (reuse and extend), D-05/D-06: worker architecture patterns, D-13/D-14: Fly volume blob storage at `/data/blobs`.
- `.planning/phases/03-persistence-analysis-service-history-caching/03-CONTEXT.md` -- D-07/D-08: `analysis_service.run_analysis()` function module (reused per batch item), D-09/D-11: mesh hash + dedup strategy, D-15: `analyses` table schema (batch items link here), D-20: cursor pagination pattern.

### Existing code to integrate with
- `backend/src/jobs/protocols.py` -- `JobQueue` protocol: `enqueue()`, `get_status()`, `cancel()`. Batch orchestrator extends this.
- `backend/src/jobs/arq_backend.py` -- `ArqJobQueue` implementation. New batch task types registered here.
- `backend/src/jobs/worker.py` -- arq `WorkerSettings`. Add batch coordinator and batch item task functions.
- `backend/src/services/analysis_service.py` -- `run_analysis()` called per batch item for analysis + dedup + persistence.
- `backend/src/services/job_service.py` -- `save_mesh_blob()` for file storage at `/data/blobs`. Reuse for batch file storage.
- `backend/src/db/models.py` -- existing `Analysis`, `Job`, `User` models. Add `Batch`, `BatchItem`, `WebhookDelivery` models.

### Brownfield codebase map
- `.planning/codebase/ARCHITECTURE.md` -- pipeline data flow, service layer pattern, jobs module placement.
- `.planning/codebase/CONVENTIONS.md` -- snake_case, env-var config, HTTPException patterns, ULID for public IDs.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`JobQueue` protocol** (`jobs/protocols.py`): Abstract `enqueue()`, `get_status()`, `cancel()`. Batch coordinator uses `enqueue()` to submit individual item analysis tasks.
- **`ArqJobQueue`** (`jobs/arq_backend.py`): arq adapter with Redis pool singleton. Register new task types (`run_batch_coordinator`, `run_batch_item`, `dispatch_webhook`) alongside existing `run_sam3d_job`.
- **`analysis_service.run_analysis()`**: Complete pipeline orchestration (hash, dedup, analyze, persist). Each batch item calls this -- no new analysis logic needed.
- **`job_service.save_mesh_blob()`**: Saves file bytes to Fly volume at `/data/blobs`. Extend path structure for batch files.
- **`Job` ORM model** (`db/models.py`): Existing job tracking. Batch coordinator job uses this for its own lifecycle tracking. Individual batch items tracked in the new `batch_items` table (not the `jobs` table).
- **Cursor pagination pattern** (Phase 3): History API uses ULID-based cursor pagination. Batch items endpoint reuses same pattern.

### Established Patterns
- **arq task registration**: `worker.py` exports `WorkerSettings` with `functions` list. Add batch task functions to this list.
- **ULID for public IDs**: All user-facing IDs are ULIDs (Phase 3 convention). Batches and batch items follow suit.
- **Env-var configuration**: `os.getenv()` with lazy read for all configurable values. Batch limits follow same pattern.
- **Service layer abstraction**: Routes call service functions, services call infrastructure. Batch routes call batch_service, which orchestrates arq + DB.
- **Auth via `Depends(require_api_key)`**: All batch endpoints require authentication (same as existing endpoints).

### Integration Points
- New module: `backend/src/services/batch_service.py` -- batch creation, progress queries, result aggregation, CSV export.
- New module: `backend/src/services/webhook_service.py` -- webhook dispatch, HMAC signing, retry logic.
- New task types in `backend/src/jobs/worker.py`: `run_batch_coordinator`, `run_batch_item`, `dispatch_webhook`.
- New routes: `POST /api/v1/batch`, `GET /api/v1/batch/{id}`, `GET /api/v1/batch/{id}/items`, `GET /api/v1/batch/{id}/results/csv` in a new `batch_router`.
- New ORM models: `Batch`, `BatchItem`, `WebhookDelivery` in `backend/src/db/models.py`.
- New Alembic migration: `0003_create_batches_batch_items_webhook_deliveries`.
- Frontend: new batch upload page and batch progress dashboard (new Next.js routes under `app/(dashboard)/batch/`).

</code_context>

<specifics>
## Specific Ideas

- **Batch creation should feel instant** -- the 202 response returns within 2 seconds regardless of batch size. All heavy work (extraction, validation, enqueuing) happens in the coordinator job. The user immediately gets a batch ID and progress URL.
- **Dedup across batches is automatic** -- if a customer re-uploads the same parts in a new batch, `analysis_service.run_analysis()` serves cached results in <200ms per item. A 10k-part re-upload batch could complete in minutes instead of hours.
- **Webhook reliability is visible** -- customers can see webhook delivery status (pending/delivered/failed) via the batch progress API. This prevents the "did our system receive it?" debugging nightmare.
- **CSV export matches enterprise workflows** -- PLM systems (Teamcenter, Windchill) and ERP systems (SAP) import CSV. The results CSV is designed to be directly importable with actionable columns (filename, verdict, best process, issue count).
- **The coordinator pattern prevents Redis exhaustion** -- a naive approach of enqueuing 10k arq tasks at once would consume ~100MB of Redis memory and create head-of-line blocking for all other jobs (SAM-3D, etc.). The coordinator drip-feeds work, keeping Redis lean.

</specifics>

<deferred>
## Deferred Ideas

- **Real-time progress via WebSocket/SSE** -- Polling `GET /api/v1/batch/{id}` every 5-10 seconds is sufficient for batch workflows where processing takes hours. WebSocket push would be nice for the dashboard but adds infrastructure complexity. Consider for a future polish pass.
- **Batch scheduling (cron batches)** -- "Process this S3 bucket every night at 2am." Useful for enterprise CI/CD integration. Not in Phase 9 scope.
- **Dedicated worker pools per tenant** -- true tenant isolation via separate arq workers per customer. Overkill for beta; soft concurrency limits (D-06) are sufficient. Revisit if tenant count grows beyond 10.
- **Batch result PDF summary report** -- aggregated PDF showing all batch results with charts (pass/fail distribution, process recommendations). Enterprise would love this, but individual PDFs (Phase 4) cover immediate needs.
- **SDK batch submission** -- Python SDK with `cadverify.batch.submit(files=...)`. Deferred to SDK-01.
- **S3 result export** -- write batch results directly to the customer's S3 bucket. Useful for large batches where downloading CSVs is impractical. Future enhancement.
- **Batch comparison** -- compare results between two batches of the same parts (e.g., before/after design revision). v2+ feature.

</deferred>

---

## Gray Areas Resolved in Auto Mode -- Summary Table

| # | Gray area | Auto-selected default | Decision ID(s) |
|---|-----------|----------------------|----------------|
| 1 | Batch input format | ZIP upload + S3 reference, both with optional CSV manifest | D-01, D-02, D-03 |
| 2 | Batch size limits | 10k items/batch, 5 GB ZIP, 100 MB/file, env-var configurable | D-04, D-05 |
| 3 | Concurrency control | 10 concurrent workers/tenant, coordinator drip-feed pattern | D-06, D-07, D-08 |
| 4 | Webhook payload + retry | HMAC-signed, structured events, 5 retries with exp backoff | D-09, D-10, D-11, D-12 |
| 5 | Batch status model (DB) | `batches` + `batch_items` + `webhook_deliveries` tables | D-13, D-14, D-15 |
| 6 | Batch upload storage | Fly volume `/data/blobs/batch/{ulid}/`, 7-day retention, S3 direct-fetch | D-16, D-17 |
| 7 | Result aggregation | Progress API with denormalized counters, paginated items, CSV export | D-18, D-19, D-20 |
| 8 | Tenant isolation | Soft concurrency limits, shared queue, priority via arq defer | D-21, D-22 |

## Decisions the User Should Revisit Before `/gsd-plan-phase 9`

1. **D-04 (10k items per batch cap).** Saudi Aramco has 14M parts. At 10k per batch, that is 1,400 batches. If they want fewer, larger batches, bump `BATCH_MAX_ITEMS` to 100k. The trade-off: larger batches mean longer coordinator jobs and bigger `batch_items` tables to query. 10k is conservative; 50-100k may be fine with proper indexing.

2. **D-06 (10 concurrent workers per tenant).** This controls throughput. At 10 concurrent with ~5s per analysis, a 10k-part batch takes ~83 minutes. Bumping to 50 concurrent would finish in ~17 minutes but requires more worker machines. The default is configurable per tenant, so the planner can set Saudi Aramco's limit higher.

3. **D-09 (Webhook secret stored in batches table).** For beta, storing the HMAC secret as plaintext in Postgres is acceptable. For production, it should be encrypted at rest (application-level encryption with a key from env var). Left to Claude's discretion for now.

4. **D-16 (Fly volume for batch file storage).** Fly volumes are limited (typically 1-10 GB provisioned). A single 5 GB batch could fill the volume. For the Saudi Aramco scale, **object storage (Tigris/R2/S3)** would be more appropriate. The 7-day retention (D-17) mitigates this, but simultaneous large batches could exhaust space. Consider using Tigris (Fly's native object storage) as an upgrade path.

5. **D-01 (S3 credential management).** How customers provide S3 access (per-batch credentials in request body vs pre-configured per-tenant settings) is left to Claude's discretion. Per-batch is more flexible; per-tenant is more secure (secrets stored once, not sent per request).

---

*Phase: 09-batch-api-webhook-pipeline*
*Context gathered: 2026-04-15*
*Mode: --auto (all gray areas resolved with recommended defaults; see each D-## "Rationale" line)*
