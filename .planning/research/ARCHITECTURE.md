# Architecture Research

**Domain:** DFM SaaS — beta productization of existing layered pipeline
**Researched:** 2026-04-15
**Confidence:** HIGH (primary patterns verified against FastAPI docs + ecosystem; application to existing codebase has HIGH fit)

## Scope

This document addresses how to integrate **new architectural surfaces** (auth, persistence, job queue, caching, packaging, PDF export, shareable URLs) into the **existing layered pipeline** (routes → parsers → GeometryContext → universal checks → analyzer registry → rule packs → scoring). The analyzer registry is explicitly out of scope — it works and should not be redesigned.

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Client (Vercel — Next.js)                        │
│  Browser UI · API client w/ X-API-Key header · Three.js viewer          │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │ HTTPS (CORS: explicit origins)
                              │ X-API-Key: ck_...
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (Fly.io / Railway)                    │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Middleware chain (order matters):                                │  │
│  │  CORSMiddleware → RequestIDMiddleware → RateLimitMiddleware       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Routes (api/v1/*)                                                │  │
│  │    Public:  /health, /signup, /processes, /materials, /machines,  │  │
│  │             /rule-packs, /share/{short_id}                        │  │
│  │    Auth'd:  /validate, /validate/quick, /validate/repair,         │  │
│  │             /analyses, /analyses/{id}, /analyses/{id}/pdf,        │  │
│  │             /jobs/{id}, /usage                                    │  │
│  │    Each auth'd route: Depends(require_api_key) → user_id + key_id │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│             │                                  │                         │
│             ▼                                  ▼                         │
│  ┌─────────────────────────┐    ┌────────────────────────────────────┐  │
│  │ Sync Analysis Service   │    │ Async Job Service                  │  │
│  │  parse → GeometryCtx →  │    │  enqueue(kind, payload) → job_id   │  │
│  │  universal → registry → │    │  returns 202 + Location header     │  │
│  │  rules → score → persist│    │                                    │  │
│  └──────────┬──────────────┘    └────────┬───────────────────────────┘  │
│             │                             │                              │
│             │  (cache lookup / write)     │  (enqueue)                   │
└─────────────┼─────────────────────────────┼──────────────────────────────┘
              │                             │
              ▼                             ▼
   ┌──────────────────────┐      ┌─────────────────────────────────────┐
   │  Postgres (managed)  │      │  Redis (managed)                    │
   │  users, api_keys,    │      │  arq queue · rate-limit counters    │
   │  analyses, jobs,     │      │  mesh-hash cache pointer (optional) │
   │  usage_events        │      └──────────────┬──────────────────────┘
   └──────────────────────┘                     │
              ▲                                 ▼
              │                      ┌──────────────────────────────────┐
              │                      │  Worker process (same image,     │
              └──────────────────────┤  different entrypoint)            │
                                     │   arq worker: sam3d, mesh_repair,│
                                     │   pdf_render                      │
                                     └──────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| Auth dependency | Resolve `X-API-Key` → `(user_id, key_id)`; 401 on miss/revoked | `APIKeyHeader` + `Depends(require_api_key)` per protected route |
| Rate limiter | Per-key quota (requests/min, bytes/day) | Middleware or `Depends`; Redis INCR with TTL |
| Sync analysis service | Current pipeline + cache lookup/write + analysis persistence | Thin wrapper around existing `validate_file` logic |
| Job service | Enqueue → return job id; expose status/result endpoints | `arq` client; `jobs` table mirrors queue state for durable history |
| Worker | Run SAM-3D, mesh-repair, PDF rendering | Same Docker image, `arq worker settings.WorkerSettings` entrypoint |
| Cache | Mesh-hash keyed result lookup | Postgres `analyses` table indexed by `(user_id, mesh_hash, analysis_version)` — no separate cache layer needed for beta |
| Share service | Resolve short ID → analysis (read-only, no auth) | Opaque random short id + `is_public` flag |
| PDF renderer | Render `AnalysisResult` → PDF | WeasyPrint or ReportLab, worker-invoked on demand |

## Recommended Project Structure

Additions on top of existing layout (unchanged modules omitted):

```
backend/
├── main.py                           # + mount new routers, init db + redis pool
├── worker.py                         # NEW: arq WorkerSettings entrypoint
├── src/
│   ├── api/
│   │   ├── routes.py                 # existing validate routes — refactor to use services
│   │   ├── auth_routes.py            # NEW: /signup, /keys/*, /usage
│   │   ├── analysis_routes.py        # NEW: /analyses, /analyses/{id}, /analyses/{id}/pdf
│   │   ├── job_routes.py             # NEW: /jobs/{id}
│   │   ├── share_routes.py           # NEW: /share/{short_id} (public)
│   │   └── deps.py                   # NEW: require_api_key, get_db, get_redis, rate_limit
│   ├── auth/                         # NEW
│   │   ├── models.py                 # User, ApiKey SQLAlchemy models
│   │   ├── keys.py                   # generate(), hash(), verify() — HMAC-SHA256 lookup
│   │   └── service.py                # signup, rotate, revoke
│   ├── db/                           # NEW
│   │   ├── base.py                   # SQLAlchemy engine, session factory
│   │   ├── session.py                # FastAPI Depends session
│   │   └── migrations/               # Alembic
│   ├── persistence/                  # NEW
│   │   ├── analyses.py               # Analysis ORM model + repo (CRUD + mesh_hash lookup)
│   │   ├── jobs.py                   # Job ORM model + repo
│   │   └── usage.py                  # UsageEvent model + repo
│   ├── services/                     # NEW — orchestration layer (thin)
│   │   ├── analysis_service.py       # wraps existing pipeline: hash → cache → run → persist
│   │   ├── repair_service.py         # pymeshfix invocation (sync for small, async for large)
│   │   ├── pdf_service.py            # renders AnalysisResult → PDF bytes
│   │   └── share_service.py          # short id mint / resolve
│   ├── jobs/                         # NEW — arq task definitions
│   │   ├── queue.py                  # arq client (enqueue helpers)
│   │   ├── sam3d_task.py             # run_sam3d(job_id, mesh_hash, payload_ref)
│   │   ├── repair_task.py            # run_repair(job_id, ...)
│   │   └── pdf_task.py               # render_pdf(analysis_id)
│   ├── storage/                      # NEW
│   │   └── blob.py                   # upload bytes storage — Fly volume / Tigris S3 / local
│   ├── middleware/                   # NEW
│   │   ├── request_id.py
│   │   └── rate_limit.py
│   └── settings.py                   # NEW: pydantic-settings; DATABASE_URL, REDIS_URL, etc.
│
├── Dockerfile                        # modified: multi-stage, cadquery baked in
├── Dockerfile.worker                 # optional: same image, CMD=worker.py
└── docker-compose.yml                # NEW: backend + worker + postgres + redis + frontend

frontend/
└── src/lib/
    ├── api.ts                        # + attach X-API-Key header from localStorage / env
    ├── auth.ts                       # NEW: signup flow, key storage
    └── history.ts                    # NEW: list analyses, share links
```

### Structure Rationale

- **services/ layer isolates new surfaces from analyzer internals.** Routes orchestrate services; services call into the existing analyzer pipeline without modifying it. Keeps the "do not redesign the registry" constraint.
- **auth/ and db/ are new top-level packages** rather than stuffed into `api/` — they are cross-cutting and will be imported by services, workers, and routes alike.
- **jobs/ (task definitions) vs services/ (business logic)** — arq tasks are thin adapters: pull payload, call a service, write result. Tests hit services directly, not tasks.
- **Single Docker image for web + worker** — smaller surface, cadquery/torch installed once, entrypoint selects role. This is the standard Railway/Fly pattern.

## Component Boundaries (authoritative — answer to downstream question)

| Boundary | Direction | Transport | Notes |
|----------|-----------|-----------|-------|
| Browser → Backend | one-way request | HTTPS + `X-API-Key` header | CORS allow-list: `https://<vercel-domain>`, `http://localhost:3000` |
| Routes → Services | direct call | in-process | Routes own HTTP concerns; services own orchestration |
| Services → Analyzer pipeline | direct call | in-process | **Untouched** — existing `GeometryContext.build`, `run_universal_checks`, `get_analyzer` |
| Services → Postgres | ORM | SQLAlchemy async | All DB access via repos in `persistence/` |
| Services → Redis / Queue | client | `arq.create_pool` | Only job service enqueues; workers consume |
| Worker → Postgres | ORM | same SQLAlchemy engine | Workers update `jobs` + `analyses` tables |
| Worker → Storage (blobs) | S3 / Fly volume | boto3 / path | Upload bytes + generated PDFs live here |
| Public → Share | one-way | HTTPS, no auth | `/share/{short_id}` — read-only projection |

**Key rule:** Routes never touch Postgres or Redis directly — always through a service or repo. Services never construct HTTP responses — they return domain objects or raise domain errors. This keeps the new code testable without a live HTTP client.

## Data Flow

### Sync Validate (primary path, unchanged latency budget)

```
POST /api/v1/validate (multipart + X-API-Key)
  ↓
CORSMiddleware → require_api_key → rate_limit
  ↓  (user_id, key_id)
stream-read bytes  →  mesh_hash = sha256(bytes)
  ↓
analysis_service.get_or_run(user_id, mesh_hash, opts)
  ├── repo.find_by_hash(user_id, mesh_hash, version)   ── HIT → return cached
  └── MISS:
        parse_mesh → GeometryContext.build → universal → registry → rules → score
        ↓
        repo.insert(Analysis)  +  usage.record(key_id, "validate", bytes)
        ↓
        return AnalysisResult
  ↓
JSON response (200)
```

### Async Job (SAM-3D, heavy repair)

```
POST /api/v1/validate?segmentation=sam3d
  ↓ require_api_key
  (sync path runs universal + registry)
  ↓
job_service.enqueue("sam3d", {mesh_hash, blob_ref, analysis_id})
  ↓
INSERT jobs (status='queued', kind='sam3d', user_id, analysis_id)
arq.enqueue_job('run_sam3d', job_id)
  ↓
return 202 + { analysis_id, job_id, poll_url: "/api/v1/jobs/{id}" }

── meanwhile ──
Worker picks up run_sam3d(job_id)
  ↓
UPDATE jobs SET status='running'
  load mesh from blob_ref → SAM-3D inference
  UPDATE analyses SET segments=..., updated_at=now()
  UPDATE jobs SET status='completed', result_ref=...

── client polls ──
GET /api/v1/jobs/{id} → {status, progress?, analysis_id}
when completed, client re-fetches GET /api/v1/analyses/{id}
```

### Shareable URL

```
POST /api/v1/analyses/{id}/share  (owner, auth'd)
  ↓ mint short_id = base62(12)   + set is_public=true
  ↓ return https://app.cadverify.com/s/{short_id}

GET /s/{short_id}                 (anyone, no auth)
  ↓ route handler resolves → 404 if not public / expired
  ↓ returns read-only AnalysisResult (no user PII)
```

**Decision:** opaque random short id (12 chars base62, ~71 bits entropy), opt-in per analysis, soft-revocable via `is_public=false`. No signed tokens — short id *is* the capability. Simpler, cacheable, easy to rotate by nulling the column.

## Data Model (minimum viable schema)

```sql
-- users
CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         CITEXT UNIQUE NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ
);

-- api_keys  (never store plaintext; lookup by HMAC of the key)
CREATE TABLE api_keys (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key_hash      BYTEA NOT NULL,              -- HMAC-SHA256(secret, key)
  key_prefix    TEXT NOT NULL,               -- first 8 chars shown to user ("ck_abc12")
  label         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at  TIMESTAMPTZ,
  revoked_at    TIMESTAMPTZ
);
CREATE UNIQUE INDEX api_keys_hash_idx ON api_keys(key_hash) WHERE revoked_at IS NULL;

-- analyses  (doubles as cache + history)
CREATE TABLE analyses (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  mesh_hash         BYTEA NOT NULL,          -- sha256 of input bytes
  filename          TEXT NOT NULL,
  file_size_bytes   BIGINT NOT NULL,
  analysis_version  TEXT NOT NULL,           -- bump invalidates cache (e.g. "2026.04.a")
  rule_pack         TEXT,
  processes_req     TEXT[],                  -- requested subset, NULL = all
  result_json       JSONB NOT NULL,          -- full AnalysisResult
  duration_ms       INTEGER,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  share_short_id    TEXT UNIQUE,             -- nullable; present => shareable
  is_public         BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX analyses_cache_idx   ON analyses(user_id, mesh_hash, analysis_version);
CREATE INDEX analyses_history_idx ON analyses(user_id, created_at DESC);

-- jobs  (durable mirror of queue state; queue is ephemeral)
CREATE TABLE jobs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  analysis_id   UUID REFERENCES analyses(id) ON DELETE SET NULL,
  kind          TEXT NOT NULL,               -- 'sam3d' | 'repair' | 'pdf'
  status        TEXT NOT NULL,               -- queued|running|completed|failed|cancelled
  progress      SMALLINT,                    -- 0..100, nullable
  payload_ref   TEXT,                        -- blob pointer / small JSON
  result_ref    TEXT,                        -- pointer to result blob or analyses.id
  error         TEXT,
  enqueued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ
);
CREATE INDEX jobs_user_status_idx ON jobs(user_id, status, enqueued_at DESC);

-- usage_events  (keep append-only; drives /usage dashboard + rate-limit auditing)
CREATE TABLE usage_events (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  api_key_id  UUID REFERENCES api_keys(id) ON DELETE SET NULL,
  kind        TEXT NOT NULL,                 -- 'validate'|'quick'|'repair'|'sam3d'|'pdf'
  bytes_in    BIGINT,
  duration_ms INTEGER,
  status_code SMALLINT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX usage_user_time_idx ON usage_events(user_id, created_at DESC);
```

**Notes:**
- `result_json JSONB` keeps the full `AnalysisResult` cacheable without blob storage. Typical size <200KB; Postgres handles this fine. Use `jsonb_path_ops` GIN only if querying into it (unlikely for beta).
- `mesh_hash` is sha256 of the *raw uploaded bytes*. This is simple and correct — identical file upload returns cached result. Cross-user cache is intentionally NOT used: privacy > efficiency.
- `analysis_version` must bump when the pipeline output shape or key thresholds change. This invalidates the cache without needing a migration.
- `api_keys.key_hash` uses HMAC with a server secret so lookups are O(1) by indexed hash — bcrypt would require scanning.

## Answers to Specific Integration Questions

### 1. Where does auth middleware sit?

**Decision:** `Depends(require_api_key)` per protected route (or per-router via `APIRouter(dependencies=[...])`), **not** a global middleware.

- Public endpoints exist (`/health`, `/signup`, `/share/{id}`, `/processes`, `/materials`, `/machines`, `/rule-packs`) — global middleware would force opt-out lists, which is error-prone.
- FastAPI's `APIKeyHeader` security utility auto-documents in OpenAPI and integrates cleanly with `Depends`.
- Group protected routes under a router: `router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])`.

```python
# api/deps.py
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def require_api_key(
    key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if not key:
        raise HTTPException(401, "Missing X-API-Key")
    key_hash = hmac_sha256(settings.API_KEY_SECRET, key)
    row = await db.scalar(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    )
    if row is None:
        raise HTTPException(401, "Invalid or revoked API key")
    return AuthContext(user_id=row.user_id, key_id=row.id)
```

### 2. Job queue — sync vs async vs opt-in

**Decision:** Sync-by-default with opt-in async. `/validate` stays synchronous for the 95% case (<10s). SAM-3D and large-mesh repair opt in via query flag or dedicated endpoint.

- `POST /validate` — sync, returns 200 with full result
- `POST /validate?segmentation=sam3d` — sync universal+registry analysis persists immediately; returns 202 with `{analysis_id, job_id, poll_url}`; segments get added to the analysis when the job finishes
- `POST /validate/repair` — if mesh is small (<50k faces), sync; otherwise 202
- `GET /jobs/{id}` — polling endpoint, cheap

**Why not WebSockets / SSE for beta:** adds infra complexity (sticky sessions, proxy support). Polling every 2s is fine for 30–60s jobs. Can upgrade later.

### 3. Queue library: arq

**Decision:** `arq` (Redis-backed, asyncio-native). HIGH confidence.

- FastAPI is async; arq tasks are `async def`, share SQLAlchemy async session with web process naturally.
- Smaller operational surface than Celery (one Redis, no result backend, no Flower). Durable state lives in the `jobs` table, not the queue.
- ~7x faster than RQ for short jobs; plenty fast for 30–60s SAM-3D jobs.
- Celery is overkill for beta scale (Railway/Fly single-box) and its sync-first design conflicts with async FastAPI.

Fallback: if arq is abandoned / unsuitable, `dramatiq` is the next choice. Not RQ (sync, fork-per-job).

### 4. Mesh repair: flag or endpoint?

**Decision:** Dedicated endpoint `POST /api/v1/validate/repair`, not a flag on `/validate`.

- Different response shape: repair returns a repaired-mesh download reference **plus** re-analysis results. Cramming into `/validate` response muddles contract.
- Different failure modes: repair can fail with "unrepairable" while analysis would succeed with warnings.
- Different billing/rate-limit tier likely in the future (repair is expensive).
- Accepts same multipart file + optional process filter; internally uses the same analysis_service after `pymeshfix` runs.

### 5. Shareable URLs

**Decision:** Opaque random short id (base62, 12 chars), opt-in per analysis, no signing.

- `POST /analyses/{id}/share` → mints short id, flips `is_public=true`. `DELETE` revokes.
- `GET /s/{short_id}` (frontend route) → fetches `GET /api/v1/share/{short_id}` (backend, no auth) → returns sanitized `AnalysisResult` (strip `user_id`, `filename` optional).
- Default: private. No accidental exposure.
- No signed tokens (JWT/HMAC): adds complexity, key rotation pain; revoking a signed token needs a blocklist anyway. A random id in the DB is simpler and revocation is a column flip.

### 6. PDF rendering location

**Decision:** On-demand, worker-rendered, cached.

- `GET /analyses/{id}/pdf` — if cached blob exists, stream it; else enqueue `pdf_task`, return 202 + poll URL.
- Synchronous inline rendering would block workers and can take 2–10s for heavy reports with mesh thumbnails. Not web-dyno-friendly.
- WeasyPrint (HTML→PDF, better layout) or ReportLab (programmatic, smaller deps). Prefer WeasyPrint if HTML template reuse between dashboard and PDF is desired; ReportLab if Docker image size matters (WeasyPrint pulls cairo/pango).
- Cache rendered PDF alongside the analysis; invalidate when `analysis_version` bumps.

### 7. Frontend (Vercel) → Backend (Fly/Railway) auth

**Decision:** `X-API-Key` header + explicit CORS allow-list.

- CORSMiddleware first in the middleware stack.
- `allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"]` — **no wildcards**, no `allow_credentials` (we don't use cookies).
- `allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"]` — tighten from current `["*"]`.
- `allow_methods=["GET", "POST", "DELETE", "OPTIONS"]`.
- Frontend stores key in `localStorage` keyed by user (after signup flow returns it once), attaches via `fetch` `headers`.
- Vercel preview deployments: support a regex-matched allow-origin (`cadverify-*.vercel.app`) OR route previews through a single stable subdomain. The regex approach is simpler.

**Known gotcha:** Fly.io CORS preflights can fail if OPTIONS isn't explicitly handled by a middleware that runs before auth. Ensure CORSMiddleware precedes `require_api_key` (dependencies don't run on OPTIONS if middleware short-circuits).

### 8. Local dev: docker-compose layout

```yaml
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: cadverify
    volumes: [ "pgdata:/var/lib/postgresql/data" ]
    ports: [ "5432:5432" ]

  redis:
    image: redis:7-alpine
    ports: [ "6379:6379" ]

  backend:
    build: { context: ./backend }
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:dev@postgres/cadverify
      REDIS_URL: redis://redis:6379/0
      ALLOWED_ORIGINS: http://localhost:3000
      API_KEY_SECRET: dev-secret-change-me
    volumes: [ "./backend:/app" ]
    ports: [ "8000:8000" ]
    depends_on: [ postgres, redis ]

  worker:
    build: { context: ./backend }
    command: arq worker.WorkerSettings
    environment:  # same as backend
      DATABASE_URL: postgresql+asyncpg://postgres:dev@postgres/cadverify
      REDIS_URL: redis://redis:6379/0
    volumes: [ "./backend:/app" ]
    depends_on: [ postgres, redis ]

  frontend:
    build: { context: ./frontend }
    command: npm run dev
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000/api/v1
    volumes: [ "./frontend:/app", "/app/node_modules" ]
    ports: [ "3000:3000" ]
    depends_on: [ backend ]

volumes: { pgdata: {} }
```

**Rationale:** backend and worker share the image (same build context, different command). cadquery and pymeshfix install once. Self-hosters get the full stack with `docker compose up`.

### 9. Request lifecycle for large-mesh stability

| Concern | Mechanism |
|---------|-----------|
| Upload size | Streamed chunked read w/ cap (existing), 413 on overflow |
| Parse timeout | `asyncio.wait_for(parse_in_threadpool, timeout=PARSE_TIMEOUT_SEC)` |
| Analysis timeout | Configurable `ANALYSIS_TIMEOUT_SEC`, 504 on exceed (already in Active requirements) |
| Memory | Explicit `del mesh, ctx; gc.collect()` in `finally`; consider `resource.setrlimit` for worker processes |
| Temp file cleanup | Context manager with `delete=True` + `mode=0o600` in STEP parser (listed concern) |
| Worker isolation | CPU-bound parse+analyze runs in `run_in_threadpool` or `ProcessPoolExecutor` with `max_workers=N_CPUS-1`; prevents blocking event loop |
| Rate limits | Redis sliding window per `api_key_id`; also byte-quota per day |
| Back-pressure | If Redis queue depth > threshold, return 503 for new async jobs |
| Observability | `X-Request-ID` middleware; log with request id, user_id, mesh_hash, duration_ms |

## Build Order / Dependencies (answer to downstream question)

Dependencies drive the ordering. `[→ X]` means X is a prerequisite.

```
 1. Settings + config module (pydantic-settings)                    [no deps]
 2. DB infrastructure (SQLAlchemy async, Alembic, connection pool)  [→ 1]
 3. Auth: users + api_keys tables + require_api_key dep + signup    [→ 2]
 4. Tighten CORS + X-Request-ID middleware                          [→ 3]
 5. Analyses table + analysis_service wrapping existing pipeline    [→ 2]
    └── cache lookup by mesh_hash; persist result
 6. History API (/analyses, /analyses/{id}) + frontend list view    [→ 5, 3]
 7. Shareable URLs (share_short_id column + public route)           [→ 5]
 8. Rate limiting + usage_events                                    [→ 3, Redis]
 9. Redis + arq wiring + jobs table + /jobs/{id}                    [→ 2, Redis]
10. Mesh repair service + /validate/repair (sync path first)        [→ 5, 9]
11. SAM-3D async task (opt-in flag on /validate)                    [→ 9, 5]
12. PDF render service + /analyses/{id}/pdf                         [→ 5, 9]
13. Docker + docker-compose + Dockerfile hardening                  [→ all services exist]
14. Deploy: Vercel frontend + Fly/Railway backend + managed PG      [→ 13]
15. Frontend polish: API-key-aware client, history UI, share UI     [→ 3, 6, 7]
```

**Critical path:** 1 → 2 → 3 → 5 unlocks most beta value (auth + persistence + cache). Steps 9–12 cluster on the Redis/arq foundation. Step 13 can overlap with 10–12.

**Phases that merit independent research later:**
- SAM-3D integration (model packaging, cold-start, blob storage strategy)
- Mesh repair success criteria and failure taxonomy
- PDF rendering library choice (WeasyPrint footprint in Docker vs ReportLab)
- Rate-limiting algorithm precision needed at beta scale

## Architectural Patterns

### Pattern 1: Thin Service Layer over Untouched Engine

**What:** New route handlers call into a `services/` module that orchestrates persistence + pipeline. The analyzer pipeline itself (registry, `GeometryContext`, rule packs) is called unmodified.

**When:** Productizing a working engine with new cross-cutting concerns.

**Trade-offs:** + preserves the "don't redesign registry" constraint; + easy to test services in isolation; − adds one layer of indirection.

```python
# services/analysis_service.py
async def validate_and_store(
    ctx: AuthContext, mesh_bytes: bytes, filename: str, opts: AnalyzeOpts, db: AsyncSession
) -> Analysis:
    mesh_hash = sha256(mesh_bytes).digest()
    if cached := await analyses_repo.find(db, ctx.user_id, mesh_hash, ANALYSIS_VERSION, opts):
        return cached
    mesh = parse_mesh(mesh_bytes, filename)            # existing
    geom_ctx = GeometryContext.build(mesh, analyze_geometry(mesh))  # existing
    result = run_pipeline(geom_ctx, opts)              # existing (registry + rules + score)
    return await analyses_repo.insert(db, ctx.user_id, mesh_hash, filename, result)
```

### Pattern 2: Cache-as-Table

**What:** The `analyses` table doubles as both history and result cache. No separate Redis/memcached layer.

**When:** Results are content-addressable (mesh hash) and reasonably sized (<1MB JSON). Beta scale.

**Trade-offs:** + one system; + inherently durable; + queryable history for free; − Postgres fetch is slower than Redis (~5ms vs <1ms, negligible here); − large `result_json` can bloat row-level storage (solve with TOAST + JSONB compression).

### Pattern 3: Durable Job Mirror

**What:** Every enqueued async job has a row in `jobs` table. Queue (Redis) is treated as ephemeral scheduler; DB is source of truth for status and history.

**When:** Polling APIs + user-visible "my jobs" views + compliance / audit.

**Trade-offs:** + survives Redis restart / eviction; + simple user-visible state; + one place to query; − requires dual-write (task updates DB + finishes); − status drift possible if worker crashes mid-task (mitigate with heartbeat / timeout sweeper).

### Pattern 4: Single-Image Web+Worker

**What:** One Docker image, entrypoint selects role (`uvicorn` vs `arq`). Same dependencies, same code paths.

**When:** Single-team project with moderate scale; shared heavy deps (cadquery, torch).

**Trade-offs:** + smaller deploy surface; + workers can call service-layer functions directly; − can't scale web and worker images independently at the container-registry level (fine at beta scale — use separate Fly apps or Railway services for horizontal scaling).

## Scaling Considerations

| Scale | Adjustment |
|-------|------------|
| 0–100 users / 100 analyses/day | Single Fly VM (web+worker) + Neon starter PG. No changes. |
| 100–1k users / 10k analyses/day | Split web and worker into separate Fly apps. 2 web instances behind LB. PG: Neon/Supabase Pro tier. |
| 1k–10k users / 100k analyses/day | Offload blob storage to S3/Tigris. Add PgBouncer. Dedicated GPU worker for SAM-3D. Consider moving hot cache lookups to Redis. |
| 10k+ | Revisit architecture — not a beta concern. |

### First bottlenecks to watch

1. **cadquery STEP parsing CPU** — already the slowest step. Watch worker CPU; if saturated, add web instances.
2. **Large-mesh memory** — 500k-face meshes push 2–4GB. Limit concurrent analyses per web instance via semaphore; spill large ones to worker queue.
3. **Redis connection fanout** — arq + rate-limit sharing one Redis; watch `connected_clients`. Use PgBouncer-equivalent (connection pool) from web + worker.

## Anti-Patterns

### Anti-Pattern 1: Global auth middleware with opt-out list

**What people do:** Register `AuthMiddleware` globally, exempt `/health`, `/signup`, `/share/*` via allow-list.
**Why wrong:** Every new public route requires updating the allow-list; forgetting causes silent 401s in prod.
**Instead:** `Depends(require_api_key)` per route or per `APIRouter(dependencies=[...])`. Public routes have no dep — secure-by-omission.

### Anti-Pattern 2: Sync SAM-3D in HTTP request

**What people do:** Add `?sam3d=true` flag and await the inference in the request handler.
**Why wrong:** 30–60s hold on a worker; proxy timeouts (Fly/Cloudflare default ~60s); poor UX.
**Instead:** 202 + job id + poll. Already decided.

### Anti-Pattern 3: Storing raw API keys

**What people do:** Save the key string in `api_keys.key`.
**Why wrong:** DB breach → all keys compromised. Can't rotate without full reset.
**Instead:** HMAC-SHA256 with server secret; show plaintext to user once at creation.

### Anti-Pattern 4: Putting `analysis_id` in the share URL

**What people do:** `https://app.cadverify.com/s/{analysis_uuid}` and toggle is_public.
**Why wrong:** UUIDs are sequential-ish in practice; leaking an analysis_id anywhere (logs, screenshots) exposes a capability. Revocation requires re-minting the whole analysis.
**Instead:** Separate `share_short_id` column; revoke by nulling. analysis_id stays private.

### Anti-Pattern 5: Caching across users

**What people do:** Key cache by mesh_hash only — "same file should return same result regardless of user."
**Why wrong:** (a) privacy: reveals that user B uploaded a file user A has; (b) rule pack / process options can differ; (c) audit trail expects per-user records.
**Instead:** Key by `(user_id, mesh_hash, analysis_version, options_hash)`.

### Anti-Pattern 6: Coupling worker code to FastAPI

**What people do:** Import `routes.py` into worker, reuse HTTP request logic.
**Why wrong:** Worker can't construct a `Request` object; pulls in CORS/middleware that don't apply; startup slowdown.
**Instead:** Workers call `services/` directly with plain Python args.

## Integration Points

### External services

| Service | Pattern | Notes |
|---------|---------|-------|
| Managed Postgres (Neon / Supabase / Fly Postgres) | `asyncpg` via SQLAlchemy async | Prefer Neon for branching in dev/CI |
| Managed Redis (Upstash / Fly Redis) | `arq.create_pool` | Single Redis for queue + rate-limit OK at beta |
| Blob storage (Tigris / S3 / Fly volume) | presigned URLs or server-side | Only needed for SAM-3D payloads + PDF output; lives behind `storage/blob.py` abstraction |
| Error tracking (Sentry) | SDK | Optional but cheap; helps during beta |

### Internal boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| routes → services | function call | Services raise domain errors; routes translate to HTTP |
| services → pipeline | function call | Pipeline modules **unchanged** from current impl |
| services → repos | function call | Repos own SQL; services never write raw queries |
| web ↔ worker | via DB + Redis | No direct calls |
| frontend ↔ backend | HTTPS + X-API-Key | No cookies, no CSRF, stateless |

## Sources

- [FastAPI Security — API Key patterns](https://fastapi.tiangolo.com/tutorial/security/) — HIGH
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/) — HIGH
- [arq docs — async job queue for FastAPI](https://arq-docs.helpmanual.io/) — HIGH
- [FastAPI background tasks vs ARQ vs Celery comparison (2026)](https://medium.com/@komalbaparmar007/fastapi-background-tasks-vs-celery-vs-arq-picking-the-right-asynchronous-workhorse-b6e0478ecf4a) — MEDIUM
- [Fly.io + Vercel CORS gotchas (community)](https://community.fly.io/t/cors-error-vercel-frontend-to-fly-io-backend/22603) — MEDIUM
- [fastapi-key-auth reference impl](https://pypi.org/project/fastapi-key-auth/) — MEDIUM
- Existing codebase docs: `.planning/codebase/ARCHITECTURE.md`, `CONCERNS.md`, `INTEGRATIONS.md`, `STRUCTURE.md`, `.planning/PROJECT.md` — HIGH

---
*Architecture research for: CadVerify beta productization*
*Researched: 2026-04-15*
