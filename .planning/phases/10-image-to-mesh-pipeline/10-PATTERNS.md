# Phase 10: Image-to-Mesh Pipeline — Pattern Map

**Generated:** 2026-04-15

## File Role Classification

| New File | Role | Closest Analog | Analog Path |
|----------|------|---------------|-------------|
| `src/reconstruction/__init__.py` | Module init | SAM-3D module | `src/segmentation/__init__.py` |
| `src/reconstruction/engine.py` | Protocol + dataclasses | JobQueue protocol | `src/jobs/protocols.py` |
| `src/reconstruction/local_triposr.py` | Local inference backend | SAM-3D pipeline | `src/segmentation/sam3d/pipeline.py` |
| `src/reconstruction/remote_triposr.py` | Remote API backend | (new pattern — HTTP client) | — |
| `src/reconstruction/preprocessing.py` | Image preprocessing | Upload validation | `src/api/upload_validation.py` |
| `src/reconstruction/scoring.py` | Quality confidence scoring | Universal checks | `src/analysis/base_analyzer.py` |
| `src/services/reconstruction_service.py` | Service orchestration | SAM-3D job creation | `src/services/job_service.py` |
| `src/jobs/reconstruction_tasks.py` | arq task definition | SAM-3D task | `src/jobs/tasks.py` |
| `src/api/reconstruct_router.py` | API endpoints | Batch router | `src/api/batch_router.py` |
| `frontend/.../reconstruct/page.tsx` | Page component | Batch page | `frontend/src/app/(dashboard)/batch/page.tsx` |

## Key Pattern Excerpts

### Pattern 1: Protocol Abstraction (from `src/jobs/protocols.py`)

```python
class JobQueue(ABC):
    @abstractmethod
    async def enqueue(self, job_type: str, params: dict, idempotency_key: str) -> str: ...
    @abstractmethod
    async def get_status(self, job_id: str) -> JobInfo: ...
    @abstractmethod
    async def cancel(self, job_id: str) -> bool: ...
```

**Apply to:** `ReconstructionEngine` protocol in `engine.py`. Same pattern: abstract base with `reconstruct()` method, two implementations (Local, Remote).

### Pattern 2: arq Task Definition (from `src/jobs/tasks.py`)

```python
async def run_sam3d_job(ctx: dict, job_ulid: str) -> dict:
    session_factory = get_session_factory()
    async with session_factory() as session:
        job = (await session.execute(select(Job).where(Job.ulid == job_ulid))).scalars().first()
        if job is None:
            logger.error("Job %s not found", job_ulid)
            return {"error": "job_not_found"}
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await session.commit()
        # ... do work ...
        job.status = status
        job.result_json = result
        job.completed_at = datetime.now(timezone.utc)
        await session.commit()
        return result
```

**Apply to:** `run_reconstruction_job` in `reconstruction_tasks.py`. Identical structure: load Job, set running, do work, set result, commit.

### Pattern 3: 202 Async Endpoint (from `src/api/batch_router.py`)

```python
@router.post("/batch", status_code=202)
async def create_batch(
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
    file: Optional[UploadFile] = File(None),
    ...
):
    # validate → create DB row → enqueue arq task → return 202
```

**Apply to:** `POST /api/v1/reconstruct`. Same: validate images → create Job row → save blobs → enqueue → return 202 with job_id.

### Pattern 4: Worker Task Registration (from `src/jobs/worker.py`)

```python
from src.jobs.batch_tasks import dispatch_webhook, run_batch_coordinator, run_batch_item
from src.jobs.tasks import run_sam3d_job

# functions list in WorkerSettings
```

**Apply to:** Add `from src.jobs.reconstruction_tasks import run_reconstruction_job` and append to functions list.

### Pattern 5: Blob Storage (from `src/services/job_service.py`)

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

**Apply to:** Reconstruction blob storage at `/data/blobs/reconstruct/{job_ulid}/input/` and `output/`. Same `os.makedirs` + write pattern.

### Pattern 6: Frontend Dashboard Page (from batch)

```
frontend/src/app/(dashboard)/batch/
├── [id]/       -- dynamic route for batch detail
└── page.tsx    -- batch list page
```

**Apply to:** `(dashboard)/reconstruct/page.tsx` with upload wizard + history. No `[id]` subpage needed (reconstruction detail is the analysis page).

## Data Flow

```
User uploads images
    → POST /api/v1/reconstruct (reconstruct_router.py)
        → reconstruction_service.create_reconstruction_job()
            → Save images to /data/blobs/reconstruct/{ulid}/input/
            → Create Job row (type='reconstruction')
            → Enqueue run_reconstruction_job to arq
        → Return 202 { job_id, poll_url }

Worker picks up job
    → run_reconstruction_job (reconstruction_tasks.py)
        → Load images from blob storage
        → preprocessing.preprocess_image() (rembg, resize, quality check)
        → engine.reconstruct() (LocalTripoSR or RemoteTripoSR)
        → scoring.compute_reconstruction_confidence(mesh)
        → Save mesh to /data/blobs/reconstruct/{ulid}/output/mesh.stl
        → analysis_service.run_analysis(mesh_bytes, ...) → analysis_id
        → Update Job result_json with reconstruction + analysis_id

Frontend polls GET /api/v1/jobs/{id}
    → On "done": show mesh preview, redirect to /analyses/{analysis_id}
```

## PATTERN MAPPING COMPLETE
