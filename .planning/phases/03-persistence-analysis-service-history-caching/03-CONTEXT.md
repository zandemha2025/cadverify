# Phase 3: Persistence + analysis_service + History + Caching - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area -- see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 3` if desired)

<domain>
## Phase Boundary

This phase makes CadVerify a product (not a stateless tool). Every analysis is persisted, deduplicated by mesh hash, and retrievable. This is the **keystone** phase -- Phases 4 (share/PDF), 5 (repair), and 6 (dashboard/deploy) all read from the rows created here.

Deliverables:
1. Full Postgres schema via Alembic: `analyses`, `jobs`, `usage_events` tables (Phase 2 already created `users` + `api_keys`).
2. `services/analysis_service.py` -- thin orchestration layer wrapping the existing analysis pipeline: hash -> cache lookup -> run -> persist.
3. Mesh-hash-based deduplication so identical uploads skip re-analysis.
4. `GET /api/v1/analyses` (paginated user history) and `GET /api/v1/analyses/{id}` (full stored result).
5. `usage_events` writes on every completed analysis (for the Phase 3 dashboard + Phase 2 rate-limit audit).
6. Next.js usage dashboard page showing recent analyses, quota consumption, and API-key activity.

**Explicitly out of scope for this phase:**
- Shareable URLs / public analysis view (Phase 4 -- SHARE-*)
- PDF export (Phase 4 -- PDF-*)
- Mesh repair endpoint (Phase 5 -- REPAIR-*)
- Redis-backed cache layer beyond dedup (performance cache is Phase 8; dedup here uses Postgres only)
- SAM-3D async job execution (Phase 7 -- SAM-*); the `jobs` table schema lands here but job processing does not
- Frontend 3D viewer on history items (Phase 8 polish)

</domain>

<decisions>
## Implementation Decisions

### Database Provider (ROADMAP-flagged gray area #1)

- **D-01:** Use **Neon** (managed Postgres) for production; local dev uses `docker-compose` Postgres container.
  - **Rationale:** PROJECT.md lists "Neon / Supabase / Fly Postgres" as options. Neon wins for single-builder beta: generous free tier (0.5 GB storage, 190 compute-hours/mo), connection pooling built-in (pgbouncer at edge), branching for preview environments later, auto-suspend on idle (cost control). Fly Postgres requires self-managing backups and pg_upgrade. Supabase adds auth/storage surface that conflicts with our own auth layer. PITFALLS.md Integration Gotchas table confirms: "Use pooled URL (pgbouncer/Neon pooler) to survive scale-up bursts."
  - **Recommended default chosen in auto mode:** Neon.

### ORM and Session Management

- **D-02:** Promote Phase 2's raw-SQL `src/auth/models.py` to a proper **SQLAlchemy 2.0 async ORM** registry in `backend/src/db/`. All tables defined as mapped classes with `DeclarativeBase`. Phase 2's `_engine()` / `_session()` singletons move to `db/engine.py`.
  - **Rationale:** Phase 2's `auth/models.py` comment explicitly says "Phase 3 will promote this module to backend/src/db/ and introduce an ORM registry." Alembic env.py comment says "Phase 3 may introduce SQLAlchemy ORM models and promote target_metadata to a real registry." ORM gives autogenerate-capable migrations, typed queries, and relationship loading for the history endpoint's joins.
- **D-03:** Session lifecycle: request-scoped `AsyncSession` via FastAPI `Depends(get_db_session)` with commit-on-success / rollback-on-error middleware pattern.
  - **Rationale:** Standard FastAPI + SQLAlchemy pattern. Avoids Phase 2's pattern of opening a new session per query. The `analysis_service` needs a single session spanning hash-check + persist to avoid race conditions on duplicate uploads.

### Alembic Migration Strategy (Pitfall 7 mitigation)

- **D-04:** Expand-migrate-contract discipline for all migrations. New migration `0002_create_analyses_jobs_usage_events` adds the three new tables. Phase 2's `users`/`api_keys` tables stay untouched.
  - **Rationale:** Pitfall 7 prescribes this pattern. Tables are new (not altering existing), so this migration is safe -- pure additive.
- **D-05:** CI step: `alembic upgrade head` on fresh DB + `alembic downgrade -1` smoke test on every PR.
  - **Rationale:** ROADMAP Success Criterion #1 and Pitfall 7 both mandate this. Cheap to set up, catches migration bugs before merge.
- **D-06:** `statement_timeout = '5s'` set in migration context for safety. `CREATE INDEX CONCURRENTLY` for any index on potentially large tables (not needed at beta scale, but establish the pattern now).
  - **Rationale:** Pitfall 7 mitigation. Cheap insurance.

### analysis_service Architecture (ROADMAP-flagged gray area #2)

- **D-07:** `backend/src/services/analysis_service.py` is a **stateless function module** (not a class). Exports `async def run_analysis(file_bytes, filename, processes, rule_pack, user) -> AnalysisResponse`. Internally: (1) compute mesh hash, (2) check `analyses` table for cache hit on `(user_id, mesh_hash, process_set_hash, analysis_version)`, (3) if miss, call existing pipeline from `routes.py`, (4) persist result as `analyses` row, (5) write `usage_events` row, (6) return.
  - **Rationale:** ROADMAP Success Criterion #6 says "The existing analyzer pipeline in backend/src/analysis/ is untouched -- only services/analysis_service.py wraps it." A function module (not a class) matches the codebase convention -- routes.py uses functions, not controllers. The service extracts the pipeline logic currently inline in `validate_file()` without rewriting the analysis engine.
- **D-08:** `routes.py` `validate_file()` becomes a thin HTTP adapter: parse request -> call `analysis_service.run_analysis()` -> serialize response. All persistence logic lives in the service, not in the route handler.
  - **Rationale:** Separation of concerns. The route handler currently contains ~60 lines of pipeline orchestration that should live in the service layer. This also makes the pipeline testable without HTTP.

### Mesh Hash Algorithm (ROADMAP-flagged gray area #3)

- **D-09:** **SHA-256 of the raw uploaded file bytes.** Not trimesh's internal hash, not a geometry-based hash.
  - **Rationale:** File-bytes hash is deterministic, fast (hashlib.sha256 is C-accelerated), and matches what the user uploaded -- two identical file uploads produce the same hash regardless of trimesh version or parsing nondeterminism. trimesh's `mesh.identifier` changes across versions and is not guaranteed stable. REQUIREMENTS.md PERS-04 keys by `(user_id, mesh_hash, analysis_version)` -- file-bytes SHA-256 satisfies "mesh_hash" cleanly. PITFALLS.md Performance Traps table uses "SHA256(mesh_bytes)" explicitly.
- **D-10:** Hash computed in `analysis_service` **before** parsing. If a cache hit is found, parsing is also skipped (fast path < 200ms per Success Criterion #2).
  - **Rationale:** Computing hash before parse means the dedup check happens at minimum cost. The hash is of the raw bytes, so no parse needed.

### Deduplication Strategy (ROADMAP-flagged gray area #4)

- **D-11:** Cache key is the composite `(user_id, mesh_hash, process_set_hash, analysis_version)`. `process_set_hash` is SHA-256 of the sorted, comma-joined process type values (e.g., `sha256("cnc_3axis,fdm,sla")`). `analysis_version` is a semver string from `backend/src/__init__.py` (bumped on engine changes that affect output).
  - **Rationale:** PERS-04 specifies `(user_id, mesh_hash, analysis_version)`. Adding `process_set_hash` prevents false cache hits when the same user uploads the same mesh but requests different process subsets. `analysis_version` ensures engine upgrades invalidate stale cached results (Pitfall recovery strategy from ROADMAP).
- **D-12:** On cache hit, return the stored `result_json` directly without re-running the pipeline. No TTL-based expiry -- cache is invalidated only by `analysis_version` bump.
  - **Rationale:** Success Criterion #2 requires < 200ms for cached responses. DFM analysis is deterministic for the same mesh + processes + engine version, so TTL adds complexity with no value. Version bumps are the correct invalidation signal.
- **D-13:** Cache is **per-user** (not global). Two different users uploading the same file each get their own `analyses` row.
  - **Rationale:** Per-user isolation simplifies access control (no cross-user data leakage), aligns with PERS-04's `user_id` in the key, and means each user's history is complete. At beta scale, the duplication cost is negligible. Global dedup can be a Phase 8 optimization if needed.

### Cache Layer (ROADMAP-flagged gray area #5)

- **D-14:** **Postgres-only for dedup in this phase.** No Redis cache layer. The `analyses` table with a unique index on `(user_id, mesh_hash, process_set_hash, analysis_version)` serves as the cache. Lookup is a single indexed SELECT.
  - **Rationale:** Redis is already in the stack (Phase 2 rate-limiting), but adding a Redis cache layer for analysis results introduces cache-invalidation complexity (two sources of truth). At beta scale (<1000 analyses/day), an indexed Postgres lookup is sub-5ms. Redis-backed result cache is explicitly a Phase 8 (PERF) optimization if needed. KISS for the keystone phase.

### analyses Table Schema (ROADMAP-flagged gray area #6)

- **D-15:** Schema for `analyses` table:
  ```
  analyses:
    id              BIGINT PRIMARY KEY (GENERATED ALWAYS AS IDENTITY)
    ulid            TEXT UNIQUE NOT NULL        -- public-facing opaque ID (Pitfall 11)
    user_id         BIGINT NOT NULL FK(users.id ON DELETE CASCADE)
    api_key_id      BIGINT NULL FK(api_keys.id ON DELETE SET NULL)
    mesh_hash       TEXT NOT NULL               -- SHA-256 hex of file bytes
    process_set_hash TEXT NOT NULL              -- SHA-256 of sorted process list
    analysis_version TEXT NOT NULL              -- engine semver
    filename        TEXT NOT NULL
    file_type       TEXT NOT NULL               -- 'stl' or 'step'
    file_size_bytes BIGINT NOT NULL
    result_json     JSONB NOT NULL              -- full analysis response
    verdict         TEXT NOT NULL               -- 'pass', 'issues', 'fail'
    face_count      INTEGER NOT NULL
    duration_ms     REAL NOT NULL
    is_public       BOOLEAN NOT NULL DEFAULT false   -- Phase 4 share flag (schema-only)
    share_short_id  TEXT UNIQUE NULL                 -- Phase 4 (schema-only, 12-char base62)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  ```
  - **Rationale:** ULID for public-facing IDs per Pitfall 11 (not autoincrement int). `result_json JSONB` stores the full response -- PITFALLS.md Technical Debt table says "OK for beta phase 1" and aligns with ROADMAP's "identical shape to original response" Success Criterion #4. Denormalized `verdict`, `face_count`, `duration_ms` enable efficient filtering/sorting on the history endpoint without parsing JSONB. `is_public` and `share_short_id` are schema-only placeholders for Phase 4 (avoid a migration just to add columns).
  - **Indexes:** `(user_id, created_at DESC)` for history pagination. `(user_id, mesh_hash, process_set_hash, analysis_version)` UNIQUE for dedup. `(share_short_id)` UNIQUE WHERE NOT NULL for Phase 4.
- **D-16:** `result_json` stores the exact dict that `_to_response()` currently returns. No transformation, no separate normalization.
  - **Rationale:** Success Criterion #4 requires "identical shape to original response." Storing the response dict as-is means `GET /api/v1/analyses/{id}` just returns the JSONB column. Future normalization (v2) can backfill from JSONB without data loss.

### jobs Table Schema

- **D-17:** Schema for `jobs` table (schema-only in this phase; Phase 7 populates):
  ```
  jobs:
    id              BIGINT PRIMARY KEY (GENERATED ALWAYS AS IDENTITY)
    ulid            TEXT UNIQUE NOT NULL
    user_id         BIGINT NOT NULL FK(users.id ON DELETE CASCADE)
    analysis_id     BIGINT NULL FK(analyses.id ON DELETE SET NULL)
    job_type        TEXT NOT NULL               -- 'sam3d' initially
    status          TEXT NOT NULL DEFAULT 'queued'  -- queued, running, done, partial, failed
    params_json     JSONB NULL
    result_json     JSONB NULL
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    started_at      TIMESTAMPTZ NULL
    completed_at    TIMESTAMPTZ NULL
  ```
  - **Rationale:** PERS-01 specifies this table. Landing the schema now means Phase 7 only adds the job-processing logic, not a schema migration. Keeps the DB schema cohesive in one migration.

### usage_events Table Schema

- **D-18:** Schema for `usage_events` table:
  ```
  usage_events:
    id              BIGINT PRIMARY KEY (GENERATED ALWAYS AS IDENTITY)
    user_id         BIGINT NOT NULL FK(users.id ON DELETE CASCADE)
    api_key_id      BIGINT NULL FK(api_keys.id ON DELETE SET NULL)
    event_type      TEXT NOT NULL               -- 'analysis_complete', 'analysis_cached', 'analysis_failed'
    analysis_id     BIGINT NULL FK(analyses.id ON DELETE SET NULL)
    mesh_hash       TEXT NULL
    duration_ms     REAL NULL
    face_count      INTEGER NULL
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  ```
  - **Rationale:** PERS-08 requires every analysis to write a usage_events row. `event_type` distinguishes fresh analyses from cache hits from failures -- essential for the dashboard (PERS-09) and for rate-limit audit (02-CONTEXT.md deferred usage_events to Phase 3).
  - **Index:** `(user_id, created_at DESC)` for dashboard queries. `(api_key_id, created_at DESC)` for per-key activity.

### GeometryContext Serialization (ROADMAP-flagged gray area #8)

- **D-19:** GeometryContext is **not serialized to DB**. Only the final `result_json` (the HTTP response dict) is stored. GeometryContext is an ephemeral in-memory object that exists only during analysis.
  - **Rationale:** GeometryContext contains numpy arrays (face normals, wall thickness samples, edge data) that are expensive to serialize and meaningless outside the analysis pipeline. The only consumer of stored results is the history API and future share/PDF views -- they all need the response dict, not the raw geometry arrays. Storing GeometryContext would bloat the DB with multi-MB binary blobs per analysis for zero consumer benefit.

### History API Shape (ROADMAP-flagged gray area #7)

- **D-20:** `GET /api/v1/analyses` returns cursor-paginated results (not offset-based):
  ```json
  {
    "analyses": [
      {
        "id": "01HYX...",
        "filename": "bracket.stl",
        "file_type": "stl",
        "verdict": "issues",
        "face_count": 52340,
        "duration_ms": 4231.2,
        "created_at": "2026-04-15T12:00:00Z",
        "process_count": 3,
        "best_process": "fdm"
      }
    ],
    "next_cursor": "01HYX...",
    "has_more": true
  }
  ```
  Query params: `?cursor=`, `?limit=20` (default 20, max 100), `?verdict=pass|issues|fail`, `?process=fdm`.
  - **Rationale:** Cursor pagination (by ULID which is time-sortable) avoids the "page drift" problem with offset pagination when new analyses are added. PITFALLS.md Performance Traps warns about N+1 on analysis list -- cursor + index on `(user_id, created_at DESC)` gives stable O(1) pagination. The list response is a summary (not full result_json) to keep payloads small.
- **D-21:** `GET /api/v1/analyses/{id}` returns the full stored `result_json` plus metadata:
  ```json
  {
    "id": "01HYX...",
    "filename": "bracket.stl",
    "file_type": "stl",
    "created_at": "2026-04-15T12:00:00Z",
    "result": { ... full result_json ... }
  }
  ```
  Returns 404 if the analysis belongs to a different user.
  - **Rationale:** Success Criterion #4 -- identical shape to original response. Wrapping in a metadata envelope gives the client creation timestamp and ID without polluting the result shape.

### analysis_version Tracking

- **D-22:** `analysis_version` is read from a `__version__` string in `backend/src/__init__.py` (e.g., `"0.3.0"`). Bumped manually when engine changes affect analysis output.
  - **Rationale:** Simple, explicit, no magic. The version string in the dedup key means old cached results are automatically bypassed when the engine improves. Semver communicates intent (patch = bugfix, minor = new checks, major = breaking output shape).

### Frontend Usage Dashboard

- **D-23:** New Next.js page at `/dashboard` showing:
  1. **Recent analyses** -- table with filename, verdict badge, process count, duration, timestamp. Click to view full result.
  2. **Quota consumption** -- progress bars for hourly (X/60) and daily (X/500) rate limits (read from `X-RateLimit-*` response headers cached client-side).
  3. **API key activity** -- list of keys with last-used timestamp and analysis count (from `usage_events` aggregate).
  - **Rationale:** PERS-09 requires this. Reuses the existing `/dashboard/keys` page structure from Phase 2. Quota display reads rate-limit headers already emitted by Phase 2 (D-08 in 02-CONTEXT.md) -- no new backend endpoint needed for quota.
- **D-24:** Analysis history on dashboard fetches from `GET /api/v1/analyses` with infinite scroll. Click-through to `GET /api/v1/analyses/{id}` renders the same `AnalysisDashboard` component used for fresh analysis results.
  - **Rationale:** Reusing the existing `AnalysisDashboard` component avoids building a second result view. The stored `result_json` has the same shape as the live response, so the component works unchanged.

### Claude's Discretion

The following are left to the researcher / planner to resolve with standard patterns and no further user input:

- Exact ULID generation library (`python-ulid` vs `ulid-py` vs inline implementation).
- `analysis_version` initial value and bump policy documentation.
- Exact cursor encoding format (raw ULID string vs base64-wrapped).
- `usage_events` aggregation query shape for the dashboard (simple COUNT/GROUP BY is fine).
- Whether `validate_quick()` also persists (recommendation: yes, as a lightweight `analyses` row with `result_json` containing the quick response).
- SQLAlchemy relationship definitions and eager/lazy loading strategy for joins.
- Exact Pydantic response models for the history endpoints (derive from the shapes in D-20/D-21).
- Database connection pool size tuning (start with Phase 2's `pool_size=5`; tune if needed).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase-level requirements and roadmap
- `.planning/ROADMAP.md` S"Phase 3: Persistence + analysis_service + History + Caching" -- goal, success criteria, key deliverables, suggested parallel plans (3.A-3.D), keystone rationale.
- `.planning/REQUIREMENTS.md` S"Persistence & History" (PERS-01..09) -- locked schema tables, service layer spec, cache-by-hash, history endpoints, usage events, dashboard.
- `.planning/PROJECT.md` S"Key Decisions" and S"Constraints" -- managed Postgres, Vercel + Fly stack, no rewrites of analyzer pipeline.

### Pitfalls research (from Phase 0 research)
- `.planning/research/PITFALLS.md` -- Pitfall 7 (Postgres migration breaks live beta: expand-migrate-contract, statement_timeout, CI check), Pitfall 11 (shareable URL enumeration: ULID/opaque IDs, sanitized serializer), Performance Traps (mesh-hash cache, N+1 on analysis list, result_json JSONB pattern).
- `.planning/research/PITFALLS.md` S"Technical Debt Patterns" -- "Store analysis results as JSONB blob: OK for beta phase 1."

### Brownfield codebase map
- `.planning/codebase/ARCHITECTURE.md` -- current pipeline data flow (steps 1-20); integration point for analysis_service between routes and analyzers.
- `.planning/codebase/STRUCTURE.md` -- `backend/src/` layout; where `services/` and `db/` modules slot in.
- `.planning/codebase/CONVENTIONS.md` -- snake_case, logger naming, HTTPException patterns, env-var config.
- `.planning/codebase/CONCERNS.md` S"Missing Critical Features: Persistent Storage" -- confirms this is the #1 missing feature.

### Prior phase context
- `.planning/phases/01-stabilize-core/01-CONTEXT.md` -- Phase 1 parallelization strategy and shared-file merge discipline (pattern reference for Phase 3 plans).
- `.planning/phases/02-auth-rate-limiting-abuse-controls/02-CONTEXT.md` -- Phase 2 auth decisions: `AuthedUser` model (D-14), `require_api_key` dependency, rate-limit headers (D-08), session management, `usage_events` deferred to Phase 3 (Deferred Ideas section).

### Existing Phase 2 code to integrate with
- `backend/src/auth/models.py` -- current raw-SQL engine/session singletons to promote to `db/engine.py`. Contains `ApiKeyRow`, `upsert_user()`, `create_api_key()`, `lookup_api_key()`, `touch_last_used()`.
- `backend/src/auth/hashing.py` -- API key hashing (Argon2id + HMAC). Not modified by Phase 3.
- `backend/alembic/versions/0001_create_users_api_keys.py` -- existing migration creating `users` + `api_keys`. Phase 3 migration is `0002_*`.
- `backend/alembic/env.py` -- currently uses `target_metadata = None` (no autogenerate). Phase 3 promotes to real ORM metadata.
- `backend/src/api/routes.py` -- current `validate_file()` containing inline pipeline logic to extract into `analysis_service`.
- `backend/src/analysis/models.py` -- `AnalysisResult`, `ProcessScore`, `Issue`, `GeometryInfo` dataclasses. The `_to_response()` serializer output is what gets stored as `result_json`.

### External docs agents should consult during research
- SQLAlchemy 2.0 async ORM: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Alembic autogenerate with async: https://alembic.sqlalchemy.org/en/latest/autogenerate.html
- FastAPI + SQLAlchemy session dependency: https://fastapi.tiangolo.com/tutorial/sql-databases/
- Neon Postgres connection pooling: https://neon.tech/docs/connect/connection-pooling
- python-ulid: https://pypi.org/project/python-ulid/

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`_to_response()` serializer** (`routes.py:355-416`) -- produces the exact dict to store as `result_json`. analysis_service calls this after pipeline execution, stores the dict, and returns it.
- **`_run_analysis_sync()` inner function** (`routes.py:170-195`) -- contains the full pipeline: geometry -> context -> features -> checks -> scoring. Extract to `analysis_service` as the core pipeline function.
- **`AuthedUser` model** (from `require_api_key`) -- provides `user_id` and `api_key_id` needed for `analyses` and `usage_events` foreign keys.
- **Phase 2's `_engine()` / `_session()` singletons** (`auth/models.py:24-37`) -- promote to `db/engine.py` with ORM support; all Phase 2 auth queries migrate to use ORM models.
- **Alembic infrastructure** (`alembic/env.py`, `alembic.ini`) -- already configured for async; add `target_metadata` from ORM base.

### Established Patterns
- **Env-var config via `os.getenv()` with lazy read** -- used for `MAX_UPLOAD_MB`, `ANALYSIS_TIMEOUT_SEC`, `DATABASE_URL`. Phase 3 adds `ANALYSIS_VERSION` (or reads from `__version__`).
- **`Depends()` injection in route handlers** -- Phase 2 established `Depends(require_api_key)` and `Depends(require_kill_switch_open)`. Phase 3 adds `Depends(get_db_session)` for session injection.
- **Structured error format** -- `{code, message, doc_url}` per DOC-02 (not yet formalized but Phase 2 emits structured HTTPException details). Phase 3 history endpoints follow the same pattern.
- **Registry-based dispatch** -- `get_analyzer(ProcessType)` pattern. analysis_service uses the same registry, not a parallel mechanism.

### Integration Points
- `backend/src/api/routes.py` -- `validate_file()` and `validate_quick()` refactored to call `analysis_service.run_analysis()` and `analysis_service.run_quick_analysis()`.
- New module: `backend/src/db/` -- `engine.py` (async engine + session factory), `models.py` (ORM mapped classes for all 5 tables).
- New module: `backend/src/services/` -- `analysis_service.py` (pipeline orchestration + persistence).
- New migration: `backend/alembic/versions/0002_create_analyses_jobs_usage_events.py`.
- `backend/src/auth/models.py` -- raw SQL queries replaced with ORM model usage; module may be retained as a thin wrapper or deprecated in favor of `db/models.py`.
- Next.js: new route `app/(dashboard)/page.tsx` (or `app/(dashboard)/analyses/page.tsx`) for history view; reuses `AnalysisDashboard` component for detail view.
- `backend/src/__init__.py` -- add `__version__ = "0.3.0"` for analysis_version tracking.

</code_context>

<specifics>
## Specific Ideas

- **Cache hit response should be indistinguishable from fresh analysis** -- the client never knows it was cached. No `X-Cache-Hit` header or "cached" flag in the response body. The only observable difference is speed (< 200ms vs 4-8s).
- **History list should feel like GitHub's repository list** -- compact rows, scannable at a glance, with verdict badges (green/yellow/red), filename, face count, and relative timestamps ("2 hours ago").
- **Dashboard reuses Phase 2's key management page** -- same nav shell, just new tabs/sections. Not a separate app.
- **Operator workflow for cache invalidation:** Bump `__version__` in `backend/src/__init__.py` and deploy. All subsequent analyses bypass old cache rows. No manual DB cleanup needed.
- **ULID generation should be done server-side** (not client-supplied) to prevent ID collision/forgery.
- **The `analyses` table is append-only** -- no UPDATE except for Phase 4's `is_public`/`share_short_id` fields. This simplifies reasoning about data integrity.

</specifics>

<deferred>
## Deferred Ideas

All surfaced during auto-mode analysis; parked for future phases or post-beta iteration:

- **Redis-backed result cache** -- a Redis layer in front of Postgres for sub-1ms cache hits at scale. Deferred to Phase 8 (PERF) if Postgres dedup latency becomes a bottleneck. At beta scale, indexed Postgres is sufficient.
- **Global (cross-user) dedup** -- two users uploading the same file could share analysis results. Deferred due to access-control complexity (who owns the shared row?). Revisit in v2 if storage becomes expensive.
- **Mesh file storage (blob)** -- storing the original uploaded file bytes for re-analysis or download. Not in scope for Phase 3; Phase 5 (repair) may need this. For now, only the hash and result are stored.
- **Background analysis (async)** -- submitting analysis as a background job and polling for results. Deferred to Phase 7 (SAM-3D), which introduces the job queue. Phase 3 analyses remain synchronous.
- **Analysis diffing** -- comparing two analyses of the same part (before/after design change). Cool feature, but v2+.
- **Batch upload** -- uploading multiple files in one request. v2+.
- **Analysis retention policy / auto-delete** -- keeping analyses forever for beta; add TTL-based cleanup post-beta if storage grows.
- **Frontend: 3D viewer on history items** -- rendering the mesh in the history detail view requires storing the mesh file. Deferred until mesh file storage is decided.
- **Webhook on analysis complete** -- SDK-04 in v2 requirements.

</deferred>

---

## Gray Areas Resolved in Auto Mode -- Summary Table

| # | Gray area | Auto-selected default | Decision ID(s) |
|---|-----------|----------------------|----------------|
| 1 | DB provider: Neon vs Fly Postgres vs Supabase | Neon (managed, free tier, built-in pooling) | D-01 |
| 2 | analysis_service architecture: class vs function module | Stateless function module exporting `run_analysis()` | D-07, D-08 |
| 3 | Mesh hash algorithm: SHA-256 of file bytes vs trimesh hash vs geometry hash | SHA-256 of raw uploaded file bytes | D-09 |
| 4 | Deduplication strategy: return cached vs re-analyze, TTL vs version-based | Return cached result; version-based invalidation, no TTL | D-11, D-12 |
| 5 | Cache layer: Redis, in-memory, Postgres, or both | Postgres-only (indexed unique constraint as cache) | D-14 |
| 6 | analyses table schema: JSONB blob vs normalized columns | JSONB blob with denormalized filter columns | D-15, D-16 |
| 7 | History API shape: offset pagination vs cursor, response shape | Cursor pagination by ULID, summary list + full detail | D-20, D-21 |
| 8 | GeometryContext serialization to DB | Not serialized; only response dict stored | D-19 |
| 9 | Public-facing ID format: autoincrement, UUID, ULID | ULID (time-sortable, opaque, no enumeration) | D-15 |
| 10 | ORM vs raw SQL | SQLAlchemy 2.0 async ORM (promoted from Phase 2 raw SQL) | D-02 |
| 11 | Per-user vs global dedup cache | Per-user (each user gets own row) | D-13 |

## Decisions the User Should Revisit Before `/gsd-plan-phase 3`

These auto-selections are the most consequential to downstream planning. Worth a glance before committing:

1. **D-01 (Neon over Fly Postgres).** Neon's free tier is generous but has a 0.5 GB storage limit. If analyses accumulate fast (large `result_json` blobs averaging 10-50 KB each), 0.5 GB holds ~10k-50k analyses. Sufficient for beta, but worth confirming Neon's paid tier pricing ($19/mo for 10 GB) is acceptable if beta grows. Fly Postgres is an alternative with more control but requires self-managed backups.

2. **D-09 (SHA-256 of file bytes, not geometry).** This means two structurally identical meshes saved from different software (different byte ordering, different header) will NOT dedup. This is the conservative choice -- it avoids false positives (treating different files as identical when they're not). If geometric dedup is important, a trimesh-derived canonical hash could be added later as a secondary key.

3. **D-13 (Per-user dedup, not global).** Two users uploading the same file each run the full pipeline independently. At beta scale this is fine; at 10k users it wastes compute. Easy to add a global cache layer later without schema changes.

4. **D-15 (JSONB blob for result storage).** This is explicitly flagged in PITFALLS.md as "OK for beta phase 1, migrate to normalized by phase 2 of persistence." If you anticipate needing to query individual issues or process scores across analyses (e.g., "find all analyses with wall-thickness errors"), normalized tables would be better. JSONB with GIN index is a middle ground but adds complexity.

5. **D-14 (No Redis cache, Postgres-only).** Redis is already deployed (Phase 2 rate-limiting). Adding a Redis result cache is low effort and would reduce DB load. Deferred to Phase 8 for simplicity, but could be pulled into Phase 3 if preferred.

---

*Phase: 03-persistence-analysis-service-history-caching*
*Context gathered: 2026-04-15*
*Mode: --auto (all gray areas resolved with recommended defaults; see each D-## "Rationale" line)*
