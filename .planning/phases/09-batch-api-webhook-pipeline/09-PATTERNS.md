# Phase 9: Batch API + Webhook Pipeline - Pattern Map

**Mapped:** 2026-04-15

## Files to Create/Modify

### New Files

| File | Role | Closest Analog | Pattern Source |
|------|------|---------------|----------------|
| `backend/src/db/models.py` (extend) | ORM models for Batch, BatchItem, WebhookDelivery | `Analysis`, `Job`, `UsageEvent` in same file | Extend existing file |
| `backend/alembic/versions/0004_create_batches_batch_items_webhook_deliveries.py` | Alembic migration | `0002_create_analyses_jobs_usage_events.py` | Same migration pattern |
| `backend/src/services/batch_service.py` | Batch CRUD, progress, CSV export | `backend/src/services/analysis_service.py` | Service layer pattern |
| `backend/src/services/webhook_service.py` | HMAC signing, dispatch, retry | `backend/src/services/job_service.py` | Service layer pattern |
| `backend/src/api/batch_router.py` | REST endpoints for batch operations | `backend/src/api/history.py`, `backend/src/api/jobs_router.py` | Router pattern |
| `backend/src/jobs/batch_tasks.py` | arq task functions (coordinator, item, webhook) | `backend/src/jobs/tasks.py` | Task function pattern |

### Modified Files

| File | What Changes | Why |
|------|-------------|-----|
| `backend/src/jobs/worker.py` | Add batch task functions to `WorkerSettings.functions`, increase `max_jobs` | New task types need registration |
| `backend/src/api/__init__.py` or main app | Register `batch_router` | New route group |

## Pattern Excerpts

### Pattern 1: ORM Model (from `backend/src/db/models.py`)

Analog: `Job` model (lines 142-172)

```python
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ulid: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=lambda: str(ULID())
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="queued"
    )
    params_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
```

**Apply to:** `Batch`, `BatchItem`, `WebhookDelivery` models. Follow same conventions: `BigInteger` PK, `Text` ULID, `TIMESTAMP(timezone=True)`, `JSONB` for structured data, `ForeignKey` with `ondelete`.

### Pattern 2: Service Layer (from `backend/src/services/job_service.py`)

Analog: `create_sam3d_job()` (lines 31-85)

```python
async def create_sam3d_job(
    session: AsyncSession,
    analysis_id: int,
    user_id: int,
    mesh_hash: str,
) -> Job:
    existing = (await session.execute(
        select(Job).where(Job.analysis_id == analysis_id, Job.job_type == "sam3d")
    )).scalars().first()
    if existing is not None:
        return existing

    job = Job(ulid=str(ULID()), ...)
    session.add(job)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        # Re-query on race condition
```

**Apply to:** `batch_service.create_batch()` -- same pattern of check-existing, create, handle IntegrityError race.

### Pattern 3: Router with Auth (from `backend/src/api/jobs_router.py`)

Analog: Jobs router endpoint pattern

```python
from fastapi import APIRouter, Depends, HTTPException
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_session

router = APIRouter(prefix="/api/v1", tags=["batch"])

@router.post("/batch", status_code=202)
async def create_batch(
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
):
    ...
```

**Apply to:** All batch endpoints. Use `Depends(require_api_key)` for auth, `Depends(get_session)` for DB.

### Pattern 4: arq Task Function (from `backend/src/jobs/tasks.py`)

Analog: `run_sam3d_job` task pattern

```python
async def run_sam3d_job(ctx: dict, job_ulid: str) -> None:
    """arq task: runs SAM-3D segmentation for a queued job."""
    from src.db.engine import get_session_factory
    async with get_session_factory()() as session:
        job = (await session.execute(
            select(Job).where(Job.ulid == job_ulid)
        )).scalars().first()
        if job is None:
            return
        job.status = "running"
        job.started_at = datetime.utcnow()
        await session.commit()
        # ... do work ...
        job.status = "done"
        job.completed_at = datetime.utcnow()
        await session.commit()
```

**Apply to:** `run_batch_coordinator`, `run_batch_item`, `dispatch_webhook` task functions. Same session factory pattern, same status lifecycle updates.

### Pattern 5: Worker Registration (from `backend/src/jobs/worker.py`)

```python
class WorkerSettings:
    functions = [run_sam3d_job]
    max_jobs = 2
    job_timeout = 600
```

**Extend to:** Add `run_batch_coordinator`, `run_batch_item`, `dispatch_webhook` to `functions` list. Increase `max_jobs` to 12. Note coordinator needs longer timeout -- use `@func(timeout=14400)` decorator on the coordinator function.

### Pattern 6: Cursor Pagination (from Phase 3 history API)

Analog: `GET /api/v1/analyses` uses ULID-based cursor pagination

```python
@router.get("/api/v1/analyses")
async def list_analyses(
    cursor: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    ...
):
    stmt = select(Analysis).where(Analysis.user_id == user.user_id)
    if cursor:
        stmt = stmt.where(Analysis.ulid < cursor)
    stmt = stmt.order_by(Analysis.created_at.desc()).limit(limit)
```

**Apply to:** `GET /api/v1/batch/{id}/items` endpoint. Same cursor pattern with ULID, same limit defaults (50, max 200).

### Pattern 7: Blob Storage (from `backend/src/services/job_service.py`)

```python
MESH_BLOB_DIR = os.getenv("MESH_BLOB_DIR", "/data/blobs/meshes")

async def save_mesh_blob(mesh_hash: str, file_bytes: bytes) -> str:
    blob_dir = os.getenv("MESH_BLOB_DIR", MESH_BLOB_DIR)
    os.makedirs(blob_dir, exist_ok=True)
    blob_path = os.path.join(blob_dir, f"{mesh_hash}.bin")
    if not os.path.exists(blob_path):
        with open(blob_path, "wb") as f:
            f.write(file_bytes)
    return blob_path
```

**Apply to:** Batch file storage at `/data/blobs/batch/{batch_ulid}/{filename}`. Same `os.makedirs` + idempotent write pattern. Add cleanup function for retention (D-17).

## Data Flow

```
POST /api/v1/batch (ZIP or S3 ref)
  -> batch_service.create_batch()
    -> INSERT batches row (status=pending)
    -> arq.enqueue("run_batch_coordinator", batch_ulid)
    -> return 202 {batch_id, status_url}

run_batch_coordinator(batch_ulid):
  -> UPDATE batches SET status=extracting
  -> extract ZIP / parse manifest
  -> INSERT batch_items rows (status=pending)
  -> UPDATE batches SET status=processing, total_items=N
  -> LOOP: enqueue up to concurrency_limit items
    -> run_batch_item(item_ulid):
      -> analysis_service.run_analysis(file_bytes, ...)
      -> UPDATE batch_items SET status=completed, analysis_id=...
      -> UPDATE batches SET completed_items += 1
      -> INSERT webhook_deliveries (item event)
      -> arq.enqueue("dispatch_webhook", delivery_id)
  -> When all complete: fire batch.completed webhook
  -> UPDATE batches SET status=completed

GET /api/v1/batch/{id}
  -> SELECT * FROM batches WHERE ulid = :id AND user_id = :uid
  -> return {status, total, completed, failed, ...}

GET /api/v1/batch/{id}/items?status=&cursor=&limit=
  -> SELECT * FROM batch_items WHERE batch_id = :id [AND status = :s]
  -> cursor pagination

GET /api/v1/batch/{id}/results/csv
  -> StreamingResponse with paginated batch_items + joined analyses
```

## PATTERN MAPPING COMPLETE
