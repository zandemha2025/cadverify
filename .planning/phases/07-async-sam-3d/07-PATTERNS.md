# Phase 7: Async SAM-3D - Pattern Map

**Generated:** 2026-04-15
**Source:** 07-CONTEXT.md + 07-RESEARCH.md + codebase analysis

## Files to Create/Modify

### New Files

| File | Role | Closest Analog | Pattern Source |
|------|------|---------------|----------------|
| `backend/src/jobs/__init__.py` | Package init | `backend/src/services/__init__.py` | Empty `__init__.py` with docstring |
| `backend/src/jobs/protocols.py` | Protocol/ABC definition | `backend/src/analysis/models.py` | Enum + dataclass + ABC pattern |
| `backend/src/jobs/arq_backend.py` | Queue adapter | `backend/src/services/analysis_service.py` | Service module with FastAPI dependency |
| `backend/src/jobs/worker.py` | arq entrypoint | N/A (new pattern) | arq `WorkerSettings` convention |
| `backend/src/jobs/tasks.py` | Task definitions | `backend/src/services/analysis_service.py` | Thin adapter calling pipeline functions |
| `backend/src/api/jobs_router.py` | API endpoints | `backend/src/api/history.py` | Router with auth + session deps |
| `backend/src/services/job_service.py` | Business logic | `backend/src/services/analysis_service.py` | Service module with session-based ops |
| `backend/alembic/versions/0003_add_jobs_idempotency_index.py` | Migration | `backend/alembic/versions/0002_create_analyses_jobs_usage_events.py` | Alembic migration with upgrade/downgrade |
| `backend/tests/test_jobs_endpoints.py` | API tests | `backend/tests/` (existing test files) | pytest with FastAPI TestClient |
| `backend/tests/test_sam3d_worker.py` | Worker tests | `backend/tests/` (existing test files) | pytest with mocks |

### Modified Files

| File | Change Type | Analog Change |
|------|------------|---------------|
| `backend/src/segmentation/sam3d/config.py` | Update defaults | Config already uses `os.getenv` pattern |
| `backend/src/api/routes.py` | Add query param + 202 branch | Similar to existing `processes` query param |
| `backend/main.py` | Register new router | Same as `share_router`, `pdf_router` registrations |
| `backend/Dockerfile` | Add model download + ENV | Existing multi-stage build pattern |
| `backend/fly.toml` | Worker process config | Existing `[processes]` section |
| `backend/.env.example` | Add SAM-3D env vars | Existing env var documentation pattern |
| `backend/src/db/engine.py` | Add init/dispose lifecycle | Extend existing lazy singleton pattern |
| `backend/requirements.txt` | Add arq dependency | Existing dependency list |

## Pattern Excerpts

### 1. Service Module Pattern (analog: `analysis_service.py`)

```python
# From backend/src/services/analysis_service.py lines 1-19
"""Analysis service — pipeline orchestration with hash, dedup, persist."""
from __future__ import annotations
import asyncio, hashlib, logging, time
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID
```

**Apply to:** `job_service.py` — same imports, same session-based patterns, same IntegrityError handling for idempotency (mirrors `_persist_analysis` race-condition handling).

### 2. Router Registration Pattern (analog: `main.py`)

```python
# From backend/main.py lines 24-29
from src.api.history import router as history_router
from src.api.pdf import router as pdf_router
from src.api.share import public_share_router, share_router
```

**Apply to:** Add `from src.api.jobs_router import router as jobs_router` and `app.include_router(jobs_router, prefix="/api/v1")`.

### 3. Auth-Protected Endpoint Pattern (analog: `history.py` or `share.py`)

```python
# Standard pattern across all protected endpoints
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session

@router.get("/endpoint")
async def handler(
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
```

**Apply to:** Both `get_job_status` and `get_job_result` endpoints in `jobs_router.py`.

### 4. Module-Level Singleton Pattern (analog: `pipeline.py`)

```python
# From backend/src/segmentation/sam3d/pipeline.py lines 24-35
_backbone: SAM2Backbone | None = None

def _get_backbone(config: SAM3DConfig) -> SAM2Backbone:
    global _backbone
    if _backbone is None:
        _backbone = SAM2Backbone()
    if not _backbone.is_loaded and config.model_path:
        _backbone.load(config.model_path)
    return _backbone
```

**Apply to:** Worker startup calls `_get_backbone()` to pre-load model. Same lazy singleton pattern used in `engine.py` for `_ENGINE`.

### 5. Env-Var Config Pattern (analog: `sam3d/config.py`)

```python
# From backend/src/segmentation/sam3d/config.py lines 25-38
@classmethod
def from_env(cls) -> SAM3DConfig:
    return cls(
        enabled=os.getenv("SAM3D_ENABLED", "false").lower() == "true",
        model_path=os.getenv("SAM3D_MODEL_PATH", ""),
        cache_dir=os.getenv("SAM3D_CACHE_DIR", "/tmp/cadverify_sam3d_cache"),
    )
```

**Apply to:** Update defaults to production values (`/app/models/sam2_hiera_small.pt`, `/data/blobs/sam3d_cache`).

### 6. DB Engine Lazy Init Pattern (analog: `engine.py`)

```python
# From backend/src/db/engine.py lines 26-50
_ENGINE = None
_SESSION_FACTORY: Optional[async_sessionmaker[AsyncSession]] = None

def get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_async_engine(os.environ["DATABASE_URL"], ...)
    return _ENGINE
```

**Apply to:** Add explicit `init_engine()` and `dispose_engine()` for worker lifecycle (worker doesn't use FastAPI lifespan).

### 7. Alembic Migration Pattern (analog: `0002_create_analyses_jobs_usage_events.py`)

```python
# Standard Alembic pattern used in existing migration
revision = "0002"
down_revision = "0001"

def upgrade() -> None:
    op.create_table(...)

def downgrade() -> None:
    op.drop_table(...)
```

**Apply to:** Migration `0003` adds UNIQUE index on `(analysis_id, job_type)`.

### 8. Heuristic Fallback Pattern (analog: `segmentation/fallback.py`)

```python
# From backend/src/segmentation/fallback.py line 16
def segment_heuristic(mesh: trimesh.Trimesh) -> list[FeatureSegment]:
```

**Apply to:** Worker task catches SAM-3D exceptions and falls back to `segment_heuristic()`, setting status to `"partial"`.

## Data Flow

```
Client → routes.py (validate_file + segmentation=sam3d)
  → analysis_service.run_analysis() [sync analysis]
  → job_service.create_sam3d_job() [idempotent job creation]
  → job_service.save_mesh_blob() [persist mesh for worker]
  → arq_backend.enqueue() [Redis enqueue]
  → 202 response with job_id + poll_url

Worker (arq) → tasks.run_sam3d_job()
  → Read job from DB
  → Read mesh from blob storage
  → segment_sam3d() || segment_heuristic() fallback
  → Write result to jobs table

Client → jobs_router.get_job_status() [polling]
Client → jobs_router.get_job_result() [fetch result]
```

---

*Pattern map generated: 2026-04-15*
*Phase: 07-async-sam-3d*
