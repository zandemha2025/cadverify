# Phase 7: Async SAM-3D - Research

**Completed:** 2026-04-15
**Requirements addressed:** SAM-01, SAM-02, SAM-03, SAM-04, SAM-05, SAM-06, SAM-07, SAM-08

## RESEARCH COMPLETE

## 1. Task Queue: arq 0.27 (Recheck Confirmed)

**Decision:** arq 0.27 remains the correct choice. No switch needed.

**arq maintenance status (2026):** Still maintenance-mode. Last release 0.27.0 (2024-12). No breaking changes, no security advisories. GitHub: ~1.7k stars, issues are minor. The library is ~700 LOC of stable asyncio code.

**TaskIQ comparison:**
| Dimension | arq 0.27 | TaskIQ 0.11+ |
|-----------|----------|-------------|
| Asyncio native | Yes | Yes |
| Redis backend | Built-in | Via taskiq-redis |
| Maintenance | Maintenance-only | Active development |
| Maturity | 5+ years, stable | 2+ years, API still evolving |
| LOC | ~700 | ~3000+ with plugins |
| FastAPI integration | Manual (simple) | Official plugin |
| Job result storage | Redis (TTL-based) | Pluggable backends |
| Worker health check | Manual | Built-in |
| Community | Smaller but stable | Growing |

**Verdict:** arq is already wired into docker-compose and fly.toml. Switching to TaskIQ would require rewriting the worker entrypoint, changing the docker-compose command, and updating fly.toml processes -- for no clear benefit at beta scale with one job type. The `JobQueue` protocol wrapper mitigates future risk.

**Implementation pattern (from .planning/research/ARCHITECTURE.md):**
```
backend/src/jobs/
  __init__.py
  protocols.py    # JobQueue protocol (ABC)
  arq_backend.py  # arq implementation of JobQueue
  worker.py       # arq WorkerSettings + task function registration
  tasks.py        # Task function definitions (thin adapters)
```

## 2. SAM-3D Model Weights (Provenance Confirmed)

**Model:** Segment Anything 2 (SAM-2) by Meta AI
**Repository:** `facebookresearch/segment-anything-2` (GitHub)
**License:** Apache-2.0 (confirmed via repo LICENSE file)
**No LGPL, GPL, or restrictive clauses.**

**Checkpoint options:**
| Model | Size | Parameters | Quality | Inference (CPU) |
|-------|------|-----------|---------|-----------------|
| sam2_hiera_tiny | ~40 MB | 19M | Good | ~15s |
| sam2_hiera_small | ~150 MB | 46M | Better | ~30s |
| sam2_hiera_base_plus | ~350 MB | 80M | Best without GPU | ~45s |
| sam2_hiera_large | ~2.5 GB | 312M | Best | ~90s (needs GPU) |

**Recommendation:** `sam2_hiera_small` (~150 MB). Fits within the Phase 6 image budget (1.2 GB compressed target with cadquery base ~600 MB + WeasyPrint ~100 MB + pymeshfix ~50 MB + app deps ~100 MB = ~850 MB base, leaving ~350 MB for model weights + overhead).

**Provenance chain:**
1. Official Meta release at `https://dl.fbaipublicfiles.com/segment_anything_2/`
2. Checkpoints are PyTorch `.pt` files
3. Download URL is stable and versioned
4. No authentication required for download

**Dockerfile integration:**
```dockerfile
# In builder stage:
ADD https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt /app/models/sam2_hiera_small.pt
```

**Python dependency:** `segment-anything-2` pip package (or vendored from GitHub). Requires PyTorch. CPU-only PyTorch (`torch-cpu`) is sufficient and smaller than full CUDA torch.

## 3. Worker Architecture

### Worker Lifecycle
1. **Startup:** Import `WorkerSettings`, which triggers module-level SAM-2 backbone loading via the existing `_get_backbone()` singleton in `pipeline.py`.
2. **Job pickup:** arq dequeues from Redis. Worker calls `run_sam3d_job(ctx, job_id)`.
3. **Processing:** Task function reads job params from DB, retrieves mesh data, calls `segment_sam3d()`.
4. **Completion:** Write `result_json` + update `status` + set `completed_at` in `jobs` table.
5. **Failure:** Catch exceptions, run `segment_heuristic()` fallback, write partial result, set `status='partial'`.

### arq WorkerSettings Configuration
```python
class WorkerSettings:
    functions = [run_sam3d_job]
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL"))
    max_jobs = 2          # Concurrent jobs per worker
    job_timeout = 600     # 10 min visibility timeout (SAM-08)
    health_check_interval = 30
    retry_jobs = True
    max_tries = 2         # One retry on failure before marking partial
```

### Mesh Bytes Retrieval Strategy
The worker needs the original mesh bytes to run SAM-3D. Options analyzed:

1. **Store file bytes in blob storage during upload (recommended):** Add a `mesh_blob_path` column to `analyses` or store at `/data/blobs/meshes/{mesh_hash}.bin`. The sync analysis already has the bytes; write them to blob storage before returning. Worker reads from blob storage by mesh hash.

2. **Pass bytes inline in arq job params:** Redis payload limit is configurable but passing multi-MB mesh files through Redis is wasteful and slow.

3. **Re-upload required:** Terrible UX.

**Decision:** Option 1. The sync upload path writes mesh bytes to `/data/blobs/meshes/{mesh_hash}.bin` (Fly volume). Worker reads from the same volume. File-bytes hash (SHA-256) is the key, computed by `analysis_service.compute_mesh_hash()`.

## 4. Async Submit Flow (202 Response)

```
Client                    Backend                     Worker (arq)
  │                         │                            │
  │ POST /validate          │                            │
  │ ?segmentation=sam3d     │                            │
  │────────────────────────>│                            │
  │                         │ 1. Run sync analysis       │
  │                         │    (geometry, scoring)      │
  │                         │ 2. Persist analyses row     │
  │                         │ 3. Save mesh bytes to blob  │
  │                         │ 4. Check idempotency        │
  │                         │    (analysis_id + job_type) │
  │                         │ 5. Create jobs row          │
  │                         │ 6. Enqueue arq job          │
  │   202 Accepted          │                            │
  │<────────────────────────│                            │
  │ {analysis_id, job_id,   │                            │
  │  poll_url, result}      │                            │
  │                         │                            │
  │                         │   arq dequeues             │
  │                         │────────────────────────────>│
  │                         │                     run SAM-3D
  │                         │                     update jobs row
  │                         │<────────────────────────────│
  │                         │                            │
  │ GET /jobs/{id}          │                            │
  │────────────────────────>│                            │
  │ {status: "done",        │                            │
  │  result_url: ...}       │                            │
  │<────────────────────────│                            │
```

## 5. Idempotency Strategy

**Key:** `(analysis_id, job_type)` — unique constraint on `jobs` table.

**Flow:**
1. Before creating a new job, query: `SELECT * FROM jobs WHERE analysis_id = ? AND job_type = 'sam3d'`
2. If found: return existing `job_id` and `poll_url` (no enqueue)
3. If not found: INSERT + enqueue

**Race condition:** Two concurrent requests for the same analysis could both pass the SELECT. Mitigate with:
- UNIQUE constraint on `(analysis_id, job_type)` — second INSERT fails with IntegrityError
- Catch IntegrityError, re-query to get the winning row's job_id

This mirrors the pattern in `analysis_service._persist_analysis()` (T-03B-01 race condition handling).

## 6. Embedding Cache Migration

**Current state:** `sam3d/cache.py` uses `/tmp/cadverify_sam3d_cache` (local filesystem, ephemeral).

**Target:** `/data/blobs/sam3d_cache` (Fly volume, persistent).

**Change required:** Update `SAM3DConfig.cache_dir` default from `/tmp/cadverify_sam3d_cache` to the value of `SAM3D_CACHE_DIR` env var, which defaults to `/data/blobs/sam3d_cache` in production. No code changes to the cache module itself -- only config.

**Cache key:** `_mesh_hash()` in `cache.py` uses geometry-based hash (vertices + faces bytes), NOT file-bytes hash. This is correct for embedding caching -- same geometry from different file formats shares embeddings.

## 7. Graceful Fallback (SAM-08)

**Trigger conditions:**
- SAM-2 library not installed (`is_backbone_available() == False`)
- Model weights missing or corrupt (`SAM2Backbone.load()` fails)
- Inference exception (timeout, OOM, bad mesh)

**Fallback chain:**
1. `segment_sam3d()` fails or returns empty → catch in worker task
2. Worker calls `segment_heuristic()` from `segmentation/fallback.py`
3. Worker writes heuristic result to `jobs.result_json`
4. Worker sets `jobs.status = 'partial'` (not `'failed'`)
5. `GET /api/v1/jobs/{id}` returns `status: "partial"` with result_url

**User experience:** User always gets segmentation data. Quality differs:
- `status: "done"` → SAM-3D quality (semantic labels, high confidence)
- `status: "partial"` → Heuristic quality (geometric labels, lower confidence)

## 8. Database Schema Notes

The `jobs` table is already created by Phase 3 migration `0002_create_analyses_jobs_usage_events.py`. ORM model exists at `db/models.py:142-173`. No new migration needed.

**Schema addition needed:** Add UNIQUE constraint on `(analysis_id, job_type)` for idempotency. This requires a new Alembic migration (`0003_add_jobs_idempotency_index`).

**Mesh blob path:** Either add a `mesh_blob_path TEXT NULL` column to `analyses`, or use a convention-based path (`/data/blobs/meshes/{mesh_hash}.bin`). Convention-based is simpler -- no schema change.

## Validation Architecture

### Risk Dimensions
1. **Integration:** arq worker connects to same Redis + Postgres as web process
2. **Data integrity:** Job idempotency, race conditions, partial results
3. **Performance:** Worker model load time, inference time, queue throughput
4. **Resilience:** Worker crash recovery, visibility timeout, fallback chain
5. **Security:** Job access control (user can only see own jobs)

### Test Strategy
- **Unit:** JobQueue protocol methods, idempotency keying, fallback trigger logic
- **Integration:** arq enqueue/dequeue round-trip, job status transitions, DB persistence
- **Smoke:** End-to-end: POST with segmentation=sam3d → poll → get result (with mock SAM-2)
- **Failure:** Worker crash mid-job (visibility timeout re-queue), SAM-2 failure (fallback to heuristic)

---

*Research completed: 2026-04-15*
*Phase: 07-async-sam-3d*
