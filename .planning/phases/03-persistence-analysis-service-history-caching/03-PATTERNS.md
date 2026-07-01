# Phase 3: Persistence + analysis_service + History + Caching — Pattern Map

**Mapped:** 2026-04-15
**Files analyzed:** 14 new/modified files
**Analogs found:** 14 / 14

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/src/db/__init__.py` (new) | package | — | `backend/src/auth/__init__.py` | exact |
| `backend/src/db/engine.py` (new) | infra | lifecycle | `backend/src/auth/models.py` (engine/session singletons) | exact |
| `backend/src/db/models.py` (new) | data/model | — | `backend/src/analysis/models.py` (dataclasses) + `backend/alembic/versions/0001_*.py` (table defs) | role-match |
| `backend/src/services/__init__.py` (new) | package | — | `backend/src/auth/__init__.py` | exact |
| `backend/src/services/analysis_service.py` (new) | service | orchestration | `backend/src/api/routes.py::validate_file` (pipeline orchestration) | exact |
| `backend/src/__init__.py` (modify) | config | — | self — add `__version__` | exact |
| `backend/src/api/routes.py` (modify) | controller | request-response | self — refactor to delegate to analysis_service | exact |
| `backend/alembic/env.py` (modify) | config | — | self — add target_metadata | exact |
| `backend/alembic/versions/0002_create_analyses_jobs_usage_events.py` (new) | migration | — | `backend/alembic/versions/0001_create_users_api_keys.py` | exact |
| `backend/src/auth/models.py` (modify) | data/model | — | self — redirect engine imports to db/engine.py | exact |
| `backend/requirements.txt` (modify) | config | — | self — add python-ulid | exact |
| `backend/tests/test_analysis_service.py` (new) | test | — | `backend/tests/test_api.py` | role-match |
| `backend/tests/test_history_api.py` (new) | test | — | `backend/tests/test_api.py` | role-match |
| `backend/tests/test_dedup.py` (new) | test | — | `backend/tests/test_api.py` | role-match |

---

## Pattern Assignments

### `backend/src/db/engine.py` (infra, lifecycle)
**Change:** Promote Phase 2's `_engine()` / `_session()` singletons to a proper module with `DeclarativeBase`, plus a `get_db_session` FastAPI dependency.
**Analog:** `backend/src/auth/models.py` lines 24-37.

**Analog pattern** (current `auth/models.py` singletons):
```python
_ENGINE = None
_SESSION: Optional[async_sessionmaker[AsyncSession]] = None

def _engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_async_engine(
            os.environ["DATABASE_URL"], pool_pre_ping=True, pool_size=5
        )
    return _ENGINE

def _session() -> async_sessionmaker[AsyncSession]:
    global _SESSION
    if _SESSION is None:
        _SESSION = async_sessionmaker(_engine(), expire_on_commit=False)
    return _SESSION
```

**Target shape** (`db/engine.py`):
```python
"""Async engine + session factory + FastAPI dependency."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

_ENGINE = None
_SESSION_FACTORY = None

def get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_async_engine(
            os.environ["DATABASE_URL"],
            pool_pre_ping=True,
            pool_size=5,
        )
    return _ENGINE

def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _SESSION_FACTORY

async def get_db_session():
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

---

### `backend/src/db/models.py` (data/model)
**Change:** Define ORM mapped classes for all 5 tables (users, api_keys, analyses, jobs, usage_events).
**Analog:** `backend/alembic/versions/0001_create_users_api_keys.py` (table structure) + `backend/src/analysis/models.py` (dataclass patterns).

**Analog pattern** (0001 migration table def):
```python
op.create_table(
    "users",
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("email", sa.Text, unique=True, nullable=False),
    ...
)
```

**Target shape** (`db/models.py`):
```python
from sqlalchemy import BigInteger, Boolean, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.engine import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # ... relationships to api_keys, analyses

class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ulid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # ...
```

---

### `backend/src/services/analysis_service.py` (service, orchestration)
**Change:** Extract pipeline orchestration from `routes.py::validate_file()` into a service function.
**Analog:** `backend/src/api/routes.py` lines 170-233 (the `_run_analysis_sync` + surrounding logic).

**Analog pattern** (current `routes.py` pipeline):
```python
def _run_analysis_sync():
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    features = detect_features(mesh)
    ctx.features = features
    universal_issues = run_universal_checks(mesh)
    target_processes = _resolve_target_processes(processes)
    process_scores = []
    for proc in target_processes:
        new_analyzer = get_analyzer(proc)
        ...
    return geometry, ctx, features, universal_issues, process_scores
```

**Target shape** (`analysis_service.py`):
```python
async def run_analysis(
    file_bytes: bytes,
    filename: str,
    processes: str | None,
    rule_pack: str | None,
    user: AuthedUser,
    session: AsyncSession,
) -> dict:
    mesh_hash = compute_mesh_hash(file_bytes)
    proc_list = _resolve_target_processes(processes)
    pset_hash = compute_process_set_hash([p.value for p in proc_list])
    
    # Cache check
    cached = await _check_cache(session, user.user_id, mesh_hash, pset_hash)
    if cached:
        await _write_usage_event(session, user, "analysis_cached", cached.id, ...)
        return cached.result_json
    
    # Run pipeline (existing code, extracted from routes.py)
    mesh, suffix = _parse_mesh(file_bytes, filename)
    result_dict = await _run_pipeline(mesh, suffix, filename, proc_list, rule_pack)
    
    # Persist
    analysis = await _persist_analysis(session, user, mesh_hash, pset_hash, ...)
    await _write_usage_event(session, user, "analysis_complete", analysis.id, ...)
    return result_dict
```

---

### `backend/alembic/versions/0002_create_analyses_jobs_usage_events.py` (migration)
**Change:** Add three new tables.
**Analog:** `backend/alembic/versions/0001_create_users_api_keys.py` — identical pattern.

**Analog pattern** (0001 migration structure):
```python
revision = "0001_create_users_api_keys"
down_revision = None

def upgrade() -> None:
    op.create_table("users", ...)
    op.create_table("api_keys", ...)
    op.create_index(...)

def downgrade() -> None:
    op.drop_index(...)
    op.drop_table(...)
```

---

### `backend/src/api/routes.py` (modify — thin adapter)
**Change:** Replace inline pipeline logic in `validate_file()` with a call to `analysis_service.run_analysis()`. Add `GET /api/v1/analyses` and `GET /api/v1/analyses/{id}` endpoints.
**Analog:** Self — the existing `validate_file` function becomes the pattern for how services are called.

---

## PATTERN MAPPING COMPLETE
