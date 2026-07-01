# Phase 3: Persistence + analysis_service + History + Caching — Research

**Researched:** 2026-04-15
**Status:** Complete
**Scope:** SQLAlchemy 2.0 async, Alembic migrations, ULID generation, cursor pagination, analysis_service design, JSONB indexing, Neon connection pooling

---

## 1. Neon Connection Pooling

Neon provides built-in PgBouncer-based connection pooling at the edge. Key findings:

- **Pooled URL format:** Replace the standard `postgresql://` host with the `-pooler` variant: `postgresql://user:pass@ep-xxx-pooler.us-east-2.aws.neon.tech/db`
- **Transaction mode** is the default pooling mode — session-level features (LISTEN/NOTIFY, prepared statements, advisory locks) do NOT work through the pooler
- **SQLAlchemy pool_size:** When using Neon's pooler, set `pool_size=5` on the SQLAlchemy side (matching Phase 2's existing config). Neon's pooler handles the multiplexing; over-pooling on the client side wastes connections
- **`pool_pre_ping=True`:** Essential — Neon auto-suspends idle compute after 5 minutes. `pool_pre_ping` ensures stale connections are detected and replaced
- **`connect_args={"server_settings": {"statement_timeout": "5000"}}`:** Set at engine level for safety (D-06)

**Recommendation:** Use `DATABASE_URL` pointing to Neon's pooled endpoint. Keep `pool_size=5` and `pool_pre_ping=True` from Phase 2. Add `statement_timeout=5s` via connect_args.

---

## 2. SQLAlchemy 2.0 Async Patterns

Phase 2 established `create_async_engine` + `async_sessionmaker` in `auth/models.py`. Phase 3 promotes this to a proper ORM registry.

### Engine + Session Factory (`db/engine.py`)

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

_engine = None
_session_factory = None

def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            os.environ["DATABASE_URL"],
            pool_pre_ping=True,
            pool_size=5,
        )
    return _engine

def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory

async def get_db_session():
    """FastAPI dependency — request-scoped session with auto-rollback."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### ORM Model Registration

All mapped classes inherit from `Base`. The `metadata` object from `Base.metadata` becomes Alembic's `target_metadata` for autogenerate capability.

### Key Pattern: Request-scoped session via `Depends(get_db_session)`

- Single session per request spans the full analysis_service transaction (hash check + persist)
- Avoids Phase 2's pattern of opening a new session per query
- `expire_on_commit=False` prevents lazy-load issues after commit

---

## 3. ULID Generation in Python

Three viable libraries evaluated:

| Library | API | Monotonic | Size | Maintenance |
|---------|-----|-----------|------|-------------|
| `python-ulid` | `ULID()` | Yes (within ms) | Pure Python, small | Active (2024) |
| `ulid-py` | `ulid.new()` | Yes | Pure Python | Active (2024) |
| `uuid6` | `uuid6.uuid7()` | UUID v7 (similar) | Pure Python | Active |

**Recommendation:** `python-ulid` (pip: `python-ulid`). Simple API: `str(ULID())` produces a 26-char Crockford base32 string. Time-sortable. No C dependencies.

```python
from ulid import ULID
analysis_ulid = str(ULID())  # "01HYX4Z5S3..."
```

**Storage:** TEXT column in Postgres. ULID strings are 26 chars, lexicographically sortable, and work directly as cursor tokens for pagination.

---

## 4. JSONB Indexing for Analyses

For Phase 3, JSONB is used as a storage blob (D-16) — not queried at the field level. The denormalized columns (`verdict`, `face_count`, `duration_ms`) handle filtering.

### Indexes needed (from D-15):

1. **Dedup index:** `UNIQUE(user_id, mesh_hash, process_set_hash, analysis_version)` — serves as the cache lookup
2. **History pagination:** `(user_id, created_at DESC)` — cursor pagination scans this
3. **Share lookup (Phase 4 prep):** `UNIQUE(share_short_id) WHERE share_short_id IS NOT NULL` — partial unique index

### JSONB GIN index:

NOT needed in Phase 3. The `result_json` column is read as a whole blob. GIN indexing would be useful only if querying individual issues across analyses (e.g., "find all analyses with THIN_WALL errors") — that's a Phase 8+ optimization.

---

## 5. Alembic Migration Patterns

### Building on Phase 2's `0001`

Phase 2 established: `alembic/env.py` (async), `alembic.ini`, `0001_create_users_api_keys.py`.

Phase 3 migration `0002_create_analyses_jobs_usage_events.py`:
- `down_revision = "0001_create_users_api_keys"`
- Pure additive — three new tables, no alterations to existing tables
- `CREATE INDEX CONCURRENTLY` pattern for future-proofing (not strictly needed at beta scale)
- `statement_timeout = '5s'` set in migration context

### Alembic env.py promotion

Update `target_metadata = None` to `target_metadata = Base.metadata` (from `db/models.py`). This enables `alembic revision --autogenerate` for future phases.

### CI gate

```bash
# In CI pipeline:
alembic upgrade head     # fresh DB schema
alembic downgrade -1     # smoke test rollback
alembic upgrade head     # re-apply (idempotency check)
```

---

## 6. Cursor Pagination Best Practices

### Why cursor > offset for `GET /api/v1/analyses`

- **Stable under inserts:** New analyses don't shift page boundaries (offset pagination breaks when new rows are inserted before the current page)
- **O(1) per page:** Index-backed seek vs. OFFSET N which scans N rows
- **ULID is the natural cursor:** Time-sortable, unique, and lexicographically ordered

### Implementation pattern

```python
async def list_analyses(
    session: AsyncSession,
    user_id: int,
    cursor: str | None = None,
    limit: int = 20,
    verdict: str | None = None,
) -> tuple[list[Analysis], str | None]:
    stmt = select(Analysis).where(Analysis.user_id == user_id)
    if cursor:
        stmt = stmt.where(Analysis.ulid < cursor)  # ULID is reverse-chronological
    if verdict:
        stmt = stmt.where(Analysis.verdict == verdict)
    stmt = stmt.order_by(Analysis.created_at.desc()).limit(limit + 1)
    
    results = (await session.execute(stmt)).scalars().all()
    has_more = len(results) > limit
    items = results[:limit]
    next_cursor = items[-1].ulid if has_more else None
    return items, next_cursor
```

### Cursor encoding

Raw ULID string (no base64 wrapping). The ULID is already opaque to clients and URL-safe.

---

## 7. analysis_service Module Design

### Architecture: Stateless function module (D-07)

```
routes.py (HTTP adapter)
    │
    ▼
analysis_service.py (orchestration)
    │
    ├── hash file bytes (SHA-256)
    ├── compute process_set_hash
    ├── check analyses table for cache hit
    │   └── if hit → return stored result_json
    ├── call existing pipeline (_run_analysis_sync equivalent)
    ├── serialize result via _to_response()
    ├── persist to analyses table
    ├── write usage_events row
    └── return result dict
```

### Key functions

```python
async def run_analysis(
    file_bytes: bytes,
    filename: str,
    processes: str | None,
    rule_pack: str | None,
    user: AuthedUser,
    session: AsyncSession,
) -> dict:
    """Full pipeline: hash → dedup → analyze → persist → return."""

async def run_quick_analysis(
    file_bytes: bytes,
    filename: str,
    user: AuthedUser,
    session: AsyncSession,
) -> dict:
    """Quick universal-checks-only path with persistence."""
```

### Hash computation

```python
import hashlib

def compute_mesh_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()

def compute_process_set_hash(processes: list[str]) -> str:
    canonical = ",".join(sorted(processes))
    return hashlib.sha256(canonical.encode()).hexdigest()
```

### Cache hit path (< 200ms target)

1. Compute `mesh_hash` from raw bytes (< 1ms for 100MB file)
2. Compute `process_set_hash` from sorted process list
3. `SELECT result_json FROM analyses WHERE user_id=:u AND mesh_hash=:h AND process_set_hash=:p AND analysis_version=:v`
4. If row exists → return `result_json` directly (skip all parsing + analysis)

### Version tracking

```python
# backend/src/__init__.py
__version__ = "0.3.0"
```

Read by analysis_service: `from src import __version__ as ANALYSIS_VERSION`

---

## 8. Validation Architecture

### Nyquist sampling dimensions for Phase 3:

1. **Schema correctness:** `alembic upgrade head` on fresh DB produces all 5 tables with correct columns, types, constraints, and indexes
2. **Dedup correctness:** Same file + same processes + same user returns cached result; different file/processes/user does not
3. **Data integrity:** Persisted `result_json` is byte-identical to the original `_to_response()` output
4. **Access isolation:** User A cannot read User B's analyses via history or direct ID lookup
5. **Pagination stability:** Adding new analyses does not shift existing pages; cursor correctly traverses
6. **Usage tracking:** Every completed analysis (fresh or cached) writes exactly one `usage_events` row
7. **Pipeline preservation:** The analysis engine (`backend/src/analysis/`) is unchanged — only wrapped
8. **Migration safety:** `alembic downgrade -1` cleanly removes Phase 3 tables without affecting Phase 2 tables

---

## RESEARCH COMPLETE
