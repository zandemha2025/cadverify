# Stack Research — CadVerify Beta Launch Additions

**Domain:** DFM SaaS — API-key auth, persistence, async jobs, PDF export, mesh repair, packaging, deployment
**Researched:** 2026-04-15
**Scope:** Only the NEW stack decisions needed for beta launch. Existing DFM engine (FastAPI + trimesh + numpy + scipy + cadquery + Next.js 16 + React 19 + Three.js) is fixed and NOT re-researched.
**Overall confidence:** HIGH for library choices; MEDIUM for platform pricing (changes frequently, verified April 2026).

---

## TL;DR — The Prescriptive Pick

| Concern | Pick | One-liner rationale |
|---------|------|---------------------|
| API-key auth | DIY: `secrets.token_urlsafe(32)` + Argon2 (`argon2-cffi`) via `pwdlib` | Match FastAPI tiangolo's 2026 guidance; no ecosystem library is load-bearing enough to add a dep |
| DB access | SQLAlchemy 2.0 async + Alembic + asyncpg | Industrial-strength, async-clean, Alembic for migrations; skip SQLModel (lags behind SA/Pydantic releases) |
| Job queue | **arq** (Redis, async-native) | Native asyncio fits FastAPI + trimesh CPU work; simpler than Celery; Dramatiq is sync. Caveat: arq is maintenance-mode — wrap the interface thinly |
| PDF export | **WeasyPrint 68.x** (Jinja2 HTML → PDF) | Pure Python, no browser binary, great CSS paged media; reports are data-heavy but template-shaped |
| Mesh repair | **pymeshfix 0.18** (primary) + `trimesh.repair` (cheap pre-pass) | Only repair lib with prebuilt wheels for manylinux + macOS arm64/x86_64 + Windows; drop-in with trimesh |
| Rate limiting | **slowapi** with Redis backend | Most widely used in production; decorator-based fits per-route API-key limits |
| Docker/cadquery | **`ghcr.io/cadquery/cadquery` base** for backend worker, multi-stage to slim | CadQuery + OCCT pre-baked; avoid 20+ min buildx compile; amd64 only for beta, arm64 via emulation in CI |
| Managed Postgres | **Neon** (beta) → Supabase (if cold starts bite) | $5 min/month scale-to-zero; 500ms cold start acceptable for history/reports (not hot path) |
| Backend host | **Fly.io** for backend + worker | Colocated Postgres, persistent Machines (no cold start for app), first-class background workers, Docker-native |
| API docs | Keep Swagger UI (default) + add **Scalar** at `/scalar` | Swagger for try-it-out; Scalar for the public marketing-quality docs page |

---

## Recommended Stack

### Core Technologies (New)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| SQLAlchemy | **2.0.49+** (async) | ORM + query builder for Postgres | Current stable; mature async (works with FastAPI event loop); batch INSERT RETURNING for asyncpg. HIGH confidence. |
| asyncpg | **0.30+** | Postgres async driver | Fastest Python Postgres driver; SQLAlchemy async standard. HIGH. |
| Alembic | **1.14+** | DB migrations | SQLAlchemy's own migration tool; only real option. HIGH. |
| Pydantic | **2.7+** (already in project) | Models (keep existing) | Already installed; keep separate Pydantic schemas from SQLA models (don't pull SQLModel). HIGH. |
| Redis | **7.4+** (managed) | Job queue broker + rate-limit store | Required by arq + slowapi; Fly.io Upstash add-on or Railway Redis. HIGH. |
| arq | **0.27** | Async job queue for SAM-3D | Asyncio-native, ~700 LOC, Redis-backed, fits FastAPI better than Celery. MEDIUM (maintenance-only; abstract behind interface). |
| pymeshfix | **0.18.0** (Jan 2026) | Mesh hole/self-intersection repair | Only mesh-repair lib with current wheels across Linux/macOS arm64/Windows; no system deps. HIGH. |
| WeasyPrint | **68.1** (Feb 2026) | HTML-to-PDF for analysis reports | Pure-Python render engine, great CSS paged media (headers/footers/page numbers), no Chromium dep. HIGH. |
| Jinja2 | **3.1+** | Template engine for PDF HTML | Standard; pairs with WeasyPrint. HIGH. |
| slowapi | **0.1.9+** | Per-API-key + per-IP rate limiting | Production-proven (flask-limiter port); Redis backend; decorator ergonomics. HIGH. |
| argon2-cffi | **23.1+** | Password/API-key secret hashing | Argon2id is the 2026 OWASP-preferred KDF; `pwdlib` wraps it. HIGH. |
| pwdlib | **0.2+** | Hashing abstraction | FastAPI 2026 docs recommend it over passlib; drop-in Argon2. HIGH. |
| pytest-asyncio | **0.24+** | Async tests for arq + SA | Required for async fixtures. HIGH. |
| httpx | **0.27+** | Async test client + outbound HTTP | FastAPI test client now uses httpx. HIGH. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `python-jose[cryptography]` | DO NOT ADD | JWT | Not needed — API keys only, no sessions |
| `python-multipart` | 0.0.9+ (already in) | File upload parsing | Already required by FastAPI; keep |
| `itsdangerous` | 2.2+ | Signed short-lived tokens for share URLs (optional) | If share URLs need expiry/signing; otherwise skip and use opaque random IDs |
| `structlog` | 24.x | Structured JSON logging for Railway/Fly log ingestion | Recommended; replace basicConfig once deploying |
| `tenacity` | 9.x | Retry decorators | Useful for arq task retries and Postgres reconnects |
| `redis` (`redis-py`) | 5.x async | Redis client (slowapi backend) | Installed transitively by slowapi + arq |

### Development & Ops

| Tool | Purpose | Notes |
|------|---------|-------|
| docker-compose | Local dev (backend + worker + Postgres + Redis) | Single `docker-compose.yml` with 4 services + named volumes |
| Docker buildx | Multi-arch image build | arm64 for Apple Silicon dev; amd64 for Fly/Railway runtime |
| GitHub Actions | CI: lint, typecheck, test, build, push image | `setup-python@v5`, `docker/build-push-action@v6` |
| ruff | Lint + format (replace any flake8/black) | Already de facto standard 2026 |
| mypy or pyright | Type checking | Pyright (via `basedpyright`) faster for large codebases |
| Dependabot | Dependency updates | Already mentioned in PROJECT.md Active |
| Sentry (optional) | Error tracking | Only if budget allows; otherwise structlog + Fly log search is enough for beta |

---

## Detailed Decisions With Rationale

### 1. API-Key Auth — DIY, no third-party library

**Pick:** Generate keys with `secrets.token_urlsafe(32)`, store only the Argon2id hash. Return key once on creation. Auth via `Authorization: Bearer <key>` or `X-API-Key` header (pick one; recommend `Authorization: Bearer`).

**Storage schema:**
```
api_keys (id uuid pk, user_id uuid fk, key_prefix text, key_hash text,
          name text, created_at, last_used_at, revoked_at, rate_limit_tier)
```
Store a 6–8 char `key_prefix` (e.g., `cv_live_xxxxxx…`) in plaintext for lookup/display; hash the rest with Argon2id. On auth: split prefix → query by prefix → verify Argon2 hash on remaining bytes.

**Why DIY:**
- `fastapi-api-key` (Athroniaeth) exists but is young (2025) and small audience — not worth the dependency
- API-key logic is ~60 lines; FastAPI has `APIKeyHeader` security dep built-in
- Argon2id via `pwdlib` is the FastAPI 2026 recommended default
- No passwords, no OAuth, no JWT complexity needed

**Hashing strategy:** Argon2id with `pwdlib` defaults (time_cost=2, memory_cost=65536, parallelism=4). Bcrypt is acceptable fallback but Argon2id is 2026 best practice.

**Don't use:** passlib (in maintenance-mode; pwdlib is the replacement). JWT (no session semantics needed). A separate identity provider (Auth0/Clerk) — overkill and costs money during free beta.

**Confidence:** HIGH.

### 2. Postgres Access — SQLAlchemy 2.0 async + Alembic + asyncpg

**Pick:** SQLAlchemy 2.0.49+ with async engine, asyncpg driver, Alembic for migrations, Pydantic schemas separate from SA models.

**Why not SQLModel:** SQLModel lags behind SQLAlchemy and Pydantic releases (search results confirm this). Async support is incomplete for some patterns. You already have Pydantic 2.7 models — duplicating DTOs in SQLModel buys nothing and adds a dependency that changes every time either SA or Pydantic major-ticks.

**Why not asyncpg direct (no ORM):** You'll have `users`, `api_keys`, `analyses`, `analysis_results`, `shared_links`, `usage_counters` tables with relations. Hand-rolling SQL is premature optimization for ~6 tables.

**Migrations:** Alembic is the only sane choice. Generate autogenerate revisions via `alembic revision --autogenerate`.

**Driver choice:** asyncpg > psycopg3-async. asyncpg has better perf; psycopg3 async is newer. SQLAlchemy supports both; stick with asyncpg.

**Connection pooling:** SQLAlchemy built-in async pool. For Neon (serverless), set `pool_pre_ping=True`, `pool_recycle=300` to handle scale-to-zero resumes. For Fly Postgres, defaults are fine.

**Confidence:** HIGH.

### 3. Job Queue — arq (with abstraction layer)

**Pick:** arq v0.27 with Redis, wrapped in a thin `JobQueue` protocol so we can swap later.

**Why arq over Celery:**
- CadVerify is fully async (FastAPI + async SA). Celery bridges sync↔async awkwardly
- SAM-3D inference is one task type with maybe 2–3 more (PDF render, embedding cache warm). Celery's workflow/chain power is overkill
- arq is ~700 LOC; Celery is a universe (Beat, Flower, canvas, routing)
- arq tasks are plain `async def` functions; ergonomic with existing codebase

**Why not RQ:** Sync-only, forks a process per job — doesn't match FastAPI/async style. SAM-3D job holds GPU/CPU for 30–60s; forking is fine but the async ergonomics loss isn't worth it.

**Why not Dramatiq:** Sync-oriented, RabbitMQ-first, similar objections to RQ. Excellent library, wrong fit.

**Why not FastAPI BackgroundTasks:** Runs in the same process as the web server — SAM-3D would block the event loop and kill concurrent validates. Fine for logging, not for 30–60s CPU work.

**Why not Fly Machines ad-hoc spawning:** Possible but operationally more complex (auth, lifecycle, result retrieval). Revisit only if arq can't keep up — unlikely at beta scale.

**Why not Railway cron:** Crons are scheduled, not request-triggered. Wrong primitive.

**Caveat — arq maintenance mode:** arq's README says "maintenance only." Mitigation: (1) it's 700 LOC and stable; (2) wrap in a `JobQueue` interface so a future switch to TaskIQ or Celery is a single adapter rewrite.

**Deployment:** Separate `worker` process (same Docker image, different entrypoint: `arq src.worker.WorkerSettings`). Fly: deploy as a second process group sharing the image.

**Confidence:** MEDIUM (arq is correct pick today; maintenance flag is the only wart).

### 4. PDF Report Generation — WeasyPrint

**Pick:** WeasyPrint 68.1 + Jinja2 templates. Reports rendered by a FastAPI endpoint (or async job if >2s).

**Why WeasyPrint:**
- Reports are template-shaped: summary header, geometry metrics table, issue list, process score cards, fix suggestions. HTML/CSS is the natural authoring surface
- WeasyPrint has the best CSS Paged Media support (running headers/footers, page numbers, TOC) — essential for professional DFM reports
- Pure Python (via Pango/Cairo), no browser binary → Docker image stays small (~60MB added)
- Already battle-tested for invoices/reports at scale

**Why not ReportLab:** Procedural API (canvas drawing, flowables). Great for tables, terrible for iteration. Every design change = code change. Our reports are visually rich (charts, issue cards); ReportLab becomes a maintenance tax.

**Why not headless Chromium (Playwright):** +150MB for the Chromium binary. Overkill — we don't need JavaScript-heavy pages or flexbox oddities. Extra attack surface. Slower.

**Charts in PDF:** Render SVG inline in HTML (no Chromium needed). Use `matplotlib` → SVG, embed with `<img>`, WeasyPrint renders it natively.

**System deps in Docker:** `libcairo2 libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf2.0-0 shared-mime-info` — document in Dockerfile.

**Confidence:** HIGH.

### 5. Mesh Repair — pymeshfix primary, trimesh.repair pre-pass

**Pick:** `pymeshfix` 0.18.0 as the workhorse. Use `trimesh.repair` (fill_holes, fix_normals, fix_winding) as a cheap pre-pass on every ingest.

**Why pymeshfix:**
- Wraps the MeshFix C++ library (Attene 2010) — the standard academic/industry repair algorithm
- Version 0.18 (Jan 2026) ships prebuilt wheels for manylinux2014 x86_64, macOS arm64 + x86_64, Windows x86_64. **No system compile required.** This is the ONLY mesh-repair option that installs cleanly everywhere via pip.
- API: `PyTMesh().load_array(v, f); clean(max_iters, inner_loops); return_arrays()` — ~5 lines
- Fixes: non-manifold edges, self-intersections, holes, duplicate faces, disconnected shells

**Why not pymeshlab:** Wraps MeshLab; binary is ~200MB; slower install; more powerful than needed. Serious overkill for "make a watertight mesh for analysis." Use only if pymeshfix proves insufficient on real user data.

**Why not trimesh.repair alone:** It's good for cheap fixes (hole fill, normal flip, winding) but can't handle self-intersections or non-manifold edges robustly. Use it as a fast first pass, then pymeshfix for anything that still fails `is_watertight`.

**Integration pattern:**
```
def repair(mesh):
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fill_holes(mesh)  # cheap
    if mesh.is_watertight: return mesh
    # pymeshfix for the hard cases
    fixed = pymeshfix.MeshFix(mesh.vertices, mesh.faces)
    fixed.repair(verbose=False, joincomp=True, remove_smallest_components=False)
    return trimesh.Trimesh(fixed.v, fixed.f, process=False)
```

**Pipeline placement:** Separate endpoint `/api/v1/validate/repair` that returns both the repaired mesh (STL bytes) and a fresh analysis result. Don't auto-repair on the main validate path — users want to see original issues.

**Confidence:** HIGH.

### 6. Rate Limiting — slowapi with Redis

**Pick:** slowapi with Redis backend. Rate-limit per API key (primary) with IP fallback for unauthenticated `/health`.

**Why slowapi:**
- Proven at scale ("millions of requests per month" per maintainers)
- Redis-backed distributed limiting — required when scaling to >1 worker or multiple Fly machines
- Decorator ergonomics match FastAPI idioms
- Port of flask-limiter — mature rate-limit algorithm implementations

**Why not fastapi-limiter:** Requires Redis-only; Depends-based — harder to apply via tier-based rules. Smaller community.

**Why not Cloudflare / upstream rate limiting:** Won't see API-key granularity (just IP). Fine as a DoS shield layered on top, but not a substitute. Use Cloudflare in front if budget-free; do app-level limits regardless.

**Rule scheme for beta:**
- Free tier default: 60 requests/hour, 10 validates/hour, 2 SAM-3D jobs/hour
- Rate-limit key: API key when present, else IP
- Return `429` with `Retry-After` header

**Dynamic limits caveat:** slowapi/fastapi-limiter both bake limits into code. For beta this is fine; later if per-customer plans emerge, implement a custom middleware reading limits from DB.

**Confidence:** HIGH.

### 7. Docker + cadquery Multi-Arch

**Pick:** Base the backend image on `ghcr.io/cadquery/cadquery:latest` (or official Docker Hub `cadquery/cadquery`). Multi-stage build to strip build tools. **amd64 only for production deploy (Fly/Railway are amd64); build arm64 for local dev via buildx + emulation.**

**Why:** cadquery depends on OCCT (Open Cascade Technology C++). Compiling OCCT from source takes 20–40 minutes and has platform-specific gotchas (the `CONCERNS.md` already notes this pain on M1/Alpine). The official cadquery image has it baked in.

**Dockerfile shape:**
```dockerfile
# Stage 1: cadquery + Python base
FROM cadquery/cadquery:latest AS base
# Stage 2: install our deps (pip install -r requirements.txt --no-cache-dir)
# System deps for WeasyPrint (libcairo, pango, pangoft2, gdk-pixbuf, shared-mime-info)
# Stage 3: copy only runtime (src/, entrypoint.sh) into slim final
```

**Build strategy:**
- Local dev on Apple Silicon: `docker buildx build --platform linux/arm64 --load` (emulated; slower but works)
- CI/Production: `docker buildx build --platform linux/amd64 --push` to ghcr.io
- Skip multi-arch manifest for beta. If demand for arm64 production (e.g., Graviton Railway) emerges, add it — but Railway and Fly are amd64 shops.

**Image size budget:** base ~1.2GB with OCCT + cadquery; + 200MB Python deps; + 60MB WeasyPrint deps → ~1.5GB final. Acceptable.

**Build time:** ~3–5 min on CI with layer caching (most time is pip install; OCCT is pre-baked).

**Alpine? No.** cadquery/OCCT don't play well with musl. Use Debian-based image (cadquery default).

**Confidence:** HIGH.

### 8. Managed Postgres — Neon (primary pick)

**Pick for beta:** **Neon Launch tier** ($5/month minimum, usage-based beyond). Scale-to-zero is an asset during free beta (zero load 80% of the time).

**Cold-start concern:** ~500ms on first query after idle. Analysis history + share URL lookup is not a user-hot path (user already waited 8s for analysis). Acceptable.

**Upgrade trigger:** If p95 first-query latency becomes a complaint post-beta, swap to **Supabase Pro** ($25/month always-on) — migration is pg_dump + Alembic, one afternoon.

**Why not Supabase first:** $25/month minimum vs $5. For a free beta burning personal money, Neon wins. Supabase's BaaS extras (Auth, Storage, Edge Fns) don't help us — we have our own API-key auth and don't need Storage/Functions.

**Why not Fly Postgres:** Fly Postgres is now managed by a third party (MPG) and pricing is less predictable; also historically had HA and backup rough edges. If strongly colocating with Fly Machines matters for latency, Fly's current managed Postgres (2026) is fine — but Neon gives you pg_dump-portable Postgres you can move anywhere.

**Why not Railway Postgres:** Fine option — simple, cheap ($5 + usage). Pick it if you deploy backend on Railway for colocation. For Fly.io-hosted backend, prefer Neon or Fly's own.

**Branching:** Neon's cheap DB branching is a nice bonus for preview environments — low urgency for beta but valuable later.

**Confidence:** MEDIUM (pricing/product shifts quarterly; all 4 options are viable — Neon is the cost-optimal default).

### 9. Backend Hosting — Fly.io

**Pick:** Fly.io for FastAPI backend AND arq worker (separate process groups, same image). Redis via Upstash (Fly marketplace) or Fly's managed Redis.

**Why Fly over Railway:**
- **Persistent Machines** (no cold-start for the API after initial deploy; Fly Machines stay up unless explicitly auto-stopped)
- **Multiple process groups in one app** — `fly.toml` defines `[processes] app="..."` and `worker="arq src.worker.WorkerSettings"` sharing the image. Railway requires separate services (more YAML).
- **Colocated Redis + Postgres** (via Upstash or Fly PG) — low intra-region latency
- **Docker-native** — our `cadquery/cadquery`-based image runs unmodified. Railway can do Docker but is heuristics-first; Fly expects a Dockerfile.
- **Already scaffolded** (PROJECT.md notes existing Fly.io deploy scaffolding)
- **Global deploy + scale-down** — beta traffic is sporadic; Fly can scale app machines to 0 when idle (different from Railway)

**Machine sizing for beta:**
- App: `shared-cpu-2x` @ 2GB RAM (~$5.70/month/machine, 1 instance → $6/month)
- Worker: `shared-cpu-4x` @ 4GB RAM for SAM-3D (~$22/month, 1 instance, auto-stop when idle)
- Postgres: Neon Launch $5–10/month
- Redis: Upstash free tier (<10K commands/day during beta)
- **Total beta cost: ~$30–45/month** (vs Railway equivalent ~$25–40/month — wash)

**Cold starts on Fly:** Only if you enable `auto_stop_machines = true`. For the API: leave one machine always on (no cold start). For the worker: auto-stop is fine (30s Machine boot vs 30–60s SAM-3D inference is acceptable).

**Why not Railway:**
- Simpler DX, but worse at multi-process apps
- No persistent volumes without extra config
- Fly's Machines API is more flexible for the future SAM-3D GPU path (Fly has A100/L40S GPU machines; Railway does not)

**Why not Render:** Fine; less flexible than Fly, fewer features. Not materially better than Railway for our case.

**Build in CI, not on Fly:** Build image in GH Actions → push to ghcr.io → `fly deploy --image ghcr.io/...`. Faster deploys, reproducible, lets you test the same image locally.

**Frontend on Vercel:** Already decided in PROJECT.md. Next.js 16 App Router deploys are Vercel's strongest suit.

**Confidence:** HIGH.

### 10. OpenAPI / API Docs

**Pick:** Keep FastAPI's built-in `/docs` (Swagger UI — interactive for developers) AND add `/scalar` via `@scalar/fastapi` package for a marketing-quality public docs page. Keep `/redoc` off (redundant with Scalar).

**Why both:**
- Swagger UI: developer try-it-out during integration. Free, native, works.
- Scalar: modern design, better for a landing page "View API docs" link. OpenAPI 3.1, dark mode, code samples in multiple languages. ~500K weekly downloads and climbing (Redoc trajectory 2019 → Scalar today).

**Wire-up:**
```python
from fastapi import FastAPI
app = FastAPI(docs_url="/docs", redoc_url=None, openapi_url="/openapi.json")

@app.get("/scalar", include_in_schema=False)
def scalar_html():
    return HTMLResponse("""<!doctype html><html><body>
      <script id="api-reference" data-url="/openapi.json"></script>
      <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
    </body></html>""")
```
(Or use the `scalar-fastapi` pip package for a tidier integration.)

**Tagging & security schemes:** Document the `Bearer` auth scheme in `app = FastAPI(..., openapi_tags=[...])` and add `HTTPBearer` security to protected routes so Scalar/Swagger render lock icons correctly. Critical for DX.

**Confidence:** HIGH.

---

## Installation (Backend)

Add to `backend/requirements.txt`:

```txt
# Existing (keep; do not re-research)
fastapi>=0.135.3
uvicorn[standard]>=0.32.0
pydantic>=2.7.0
trimesh[easy]>=4.4.0
numpy>=1.26.0
scipy>=1.13.0
shapely>=2.0.0
PyYAML>=6.0
python-multipart>=0.0.9
cadquery>=2.5.0  # baked into base image

# NEW — auth, persistence, migrations
sqlalchemy[asyncio]>=2.0.49
asyncpg>=0.30.0
alembic>=1.14.0
pwdlib[argon2]>=0.2.1
argon2-cffi>=23.1.0

# NEW — jobs + rate limit
arq>=0.27.0
redis>=5.1.0
slowapi>=0.1.9

# NEW — PDF + templating
weasyprint>=68.1
jinja2>=3.1.4

# NEW — mesh repair
pymeshfix>=0.18.0

# NEW — observability + misc
structlog>=24.4.0
tenacity>=9.0.0
httpx>=0.27.0  # also used by FastAPI TestClient

# Dev
pytest>=8.3.0
pytest-asyncio>=0.24.0
ruff>=0.7.0
```

System deps in Dockerfile (on top of cadquery base):
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf2.0-0 \
    shared-mime-info libffi-dev \
 && rm -rf /var/lib/apt/lists/*
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Argon2 + DIY API keys | `fastapi-api-key` library | If you want out-of-box key rotation + usage tracking, at cost of a young dependency |
| SQLAlchemy 2.0 async | SQLModel | If the team strongly prefers one-class-for-both DB and API schema and accepts release lag |
| SQLAlchemy 2.0 async | asyncpg direct (no ORM) | If schema is truly <3 tables and never grows (not our case) |
| arq | Celery + Redis | If you later need complex workflows (chains, groups, Beat schedules) or multi-language workers |
| arq | Dramatiq | If you go RabbitMQ-first or prefer sync workers with better ops tooling |
| arq | TaskIQ | Emerging async-native alternative to arq; viable if arq's maintenance-mode becomes painful |
| WeasyPrint | Playwright (Chromium) | If reports must render JS-heavy pages (dashboards with Chart.js runtime) — not our case |
| WeasyPrint | ReportLab | If reports are purely tabular/generated and you want programmatic canvas control |
| pymeshfix | pymeshlab | If pymeshfix proves insufficient on real user data (unlikely for beta) |
| pymeshfix | OpenMesh / manifold3d | Higher-quality repair at cost of heavier deps; defer |
| slowapi | fastapi-limiter | Similar feature set; pick by ergonomic preference (slowapi: decorator, limiter: Depends) |
| Fly.io | Railway | If you want the absolute simplest deploy UX and don't need multi-process-group control |
| Fly.io | Render | If you prefer Render's managed DB integration and simpler pricing |
| Neon | Supabase | If always-on latency matters more than the $20/month delta |
| Neon | Fly Postgres | If strongly colocating with Fly Machines matters more than portability |
| Neon | Railway Postgres | If backend already on Railway; keep in-platform |
| Scalar | Redoc | If you want the bundled FastAPI default with zero extra JS |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| passlib | In maintenance mode; bcrypt handler has known issues with newer Python | pwdlib + argon2-cffi |
| SQLModel | Lags SQLAlchemy 2.x and Pydantic 2.x releases; extra indirection for no gain when you already split DTOs | SQLAlchemy 2.0 async + separate Pydantic schemas |
| Celery for this project | Sync-first, heavy, complex ops — wrong shape for async FastAPI + one 30–60s task type | arq (or Dramatiq if you strongly want sync) |
| FastAPI BackgroundTasks for SAM-3D | Runs in web process; 30–60s inference blocks event loop | arq worker process |
| ReportLab for reports | Procedural canvas API; every design iteration = code change | WeasyPrint + Jinja2 HTML templates |
| Playwright/Puppeteer for PDFs | +150MB browser binary; unnecessary for our template-shaped reports | WeasyPrint |
| Headless Chrome via `pyppeteer` | Unmaintained; flaky | WeasyPrint |
| pymeshlab as default | ~200MB install; heavier than needed for hole-fill/self-intersection | pymeshfix |
| JWT / OAuth libs (python-jose, authlib) | Not needed; API-key-only per PROJECT.md constraints | DIY API-key auth |
| Session middleware | Stateless API per constraints | Don't add |
| Alpine base image | musl + OCCT/cadquery + WeasyPrint = pain | Debian-based (cadquery official base is Debian) |
| SQLite for production | Concurrent writes + Alembic + job workers = friction | Postgres from day one |
| Building cadquery from source in Dockerfile | 20–40 min builds; fragile across arch | Use `cadquery/cadquery` base image |
| `requests` for outbound HTTP | Blocks event loop | `httpx` (async) |
| `python-dotenv` in production | Use real env vars; dotenv only for local | `os.environ` + `pydantic-settings` |

---

## Stack Variants by Condition

**If beta traffic spikes (>100 concurrent validates):**
- Scale Fly app machines horizontally (`fly scale count 3`)
- Move Redis to dedicated Upstash paid tier
- Add a second arq worker machine
- Still no need to revisit library choices

**If SAM-3D demand forces GPU:**
- Fly.io A100 or L40S Machine (~$1–2/hr, scale-to-zero when idle)
- Same arq worker framework; add a `sam3d` queue name so only GPU workers pick up those jobs
- Pre-load PyTorch model weights at worker startup

**If self-hosting story matters:**
- `docker-compose.yml` with: `backend`, `worker`, `postgres:17`, `redis:7.4` — no managed service deps
- Mount `./data/postgres` and `./data/redis` volumes for persistence
- Document in README — already in PROJECT.md Active list

**If Neon cold starts annoy beta users:**
- Migrate to Supabase (pg_dump + Alembic apply on target; 1 hour downtime max)
- Or Fly Postgres colocated with Fly Machines (lower latency than any external)

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| SQLAlchemy 2.0.49 | Alembic 1.14+, asyncpg 0.30+, Pydantic 2.7+ | Stable; avoid SA 2.1 betas for now |
| FastAPI 0.135.x | Python 3.10+ (required), Pydantic 2.7+, Uvicorn 0.32+ | Python 3.10 baseline matches our 3.12 |
| arq 0.27 | Redis 5+, Python 3.9+ | Works with both redis-py 4 and 5 |
| pymeshfix 0.18 | trimesh 4.4+, NumPy 1.26+ | Tested on manylinux2014 |
| WeasyPrint 68.1 | Python 3.9+, Pango 1.44+ | Debian `libpango-1.0-0` is sufficient |
| cadquery 2.5+ | Python 3.10–3.12; OCP/OCCT pre-bundled in official image | Don't pip-install OCP separately |
| slowapi 0.1.9 | FastAPI, redis-py 4/5 | Works with async endpoints |
| pwdlib 0.2 | argon2-cffi 23+ | Pydantic-independent |

---

## Confidence Summary

| Decision | Confidence | Rationale |
|----------|------------|-----------|
| DIY API keys + Argon2 | HIGH | FastAPI 2026 docs, ecosystem convergence |
| SQLAlchemy 2.0 async + Alembic | HIGH | Industry standard; SQLModel lag confirmed by multiple sources |
| arq for job queue | MEDIUM | Correct technical choice, but maintenance-mode flag warrants wrapper interface |
| WeasyPrint for PDF | HIGH | Template fit + no-browser-binary advantage decisive |
| pymeshfix for repair | HIGH | Only lib with complete cross-platform wheel matrix |
| slowapi for rate limits | HIGH | Production track record |
| cadquery/cadquery base image | HIGH | Saves 20+ min builds; official source |
| Neon for Postgres | MEDIUM | Best cost today; all 4 options viable; may swap |
| Fly.io for backend | HIGH | Multi-process + Docker-native + existing scaffolding |
| Swagger UI + Scalar | HIGH | Covers both DX and public-facing needs |

---

## Sources

- [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/) — current version 0.135.3 (April 2026). HIGH
- [FastAPI OAuth2 + JWT tutorial](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) — Argon2 + pwdlib guidance. HIGH
- [WorkOS: Top auth solutions FastAPI 2026](https://workos.com/blog/top-authentication-solutions-fastapi-2026) — API-key vs JWT tradeoffs. MEDIUM
- [SQLAlchemy 2.0.49 release](https://www.sqlalchemy.org/changelog/CHANGES_2_0_36) + [PyPI](https://pypi.org/project/SQLAlchemy/) — current 2.0.x series. HIGH
- [TestDriven: FastAPI async SQLAlchemy SQLModel Alembic](https://testdriven.io/blog/fastapi-sqlmodel/) — SQLModel lag behind SA. MEDIUM
- [SQLModel features](https://sqlmodel.tiangolo.com/features/) — confirmed positioning as SA wrapper. HIGH
- [arq PyPI](https://pypi.org/project/arq/) + [GitHub](https://github.com/python-arq/arq) — v0.27.0, maintenance-mode confirmed. HIGH
- [David Muraya: ARQ vs BackgroundTasks](https://davidmuraya.com/blog/fastapi-background-tasks-arq-vs-built-in/) — FastAPI+arq patterns. MEDIUM
- [Judoscale: Python task queue comparison](https://judoscale.com/blog/choose-python-task-queue) — Celery/arq/RQ/Dramatiq tradeoffs. MEDIUM
- [WeasyPrint PyPI](https://pypi.org/project/weasyprint/) — 68.1 (Feb 2026). HIGH
- [Nutrient: Top 10 Python PDF generators 2026](https://www.nutrient.io/blog/top-10-ways-to-generate-pdfs-in-python/) — WeasyPrint/ReportLab/Playwright comparison. MEDIUM
- [pymeshfix PyPI](https://pypi.org/project/pymeshfix/) + [GitHub releases](https://github.com/pyvista/pymeshfix/releases) — 0.18.0 (Jan 2026) wheel matrix. HIGH
- [trimesh.repair docs](https://trimesh.org/trimesh.repair.html) — available repair ops. HIGH
- [slowapi GitHub](https://github.com/laurentS/slowapi) + [docs](https://slowapi.readthedocs.io/) — Redis backend, production use. HIGH
- [cadquery Docker Hub](https://hub.docker.com/r/cadquery/cadquery) + [installation docs](https://cadquery.readthedocs.io/en/latest/installation.html) — official image with OCCT. HIGH
- [Docker multi-arch guide](https://www.docker.com/blog/multi-arch-images/) — buildx workflow. HIGH
- [Neon vs Supabase 2026 (DEV)](https://dev.to/thiago_alvarez_a7561753aa/neon-vs-supabase-2026-database-or-backend-the-real-tradeoffs-3ggn) — cold start ~500ms, pricing. MEDIUM
- [Vela: Neon vs Supabase](https://vela.simplyblock.io/neon-vs-supabase/) — Launch tier $5, Supabase Pro $25. MEDIUM
- [Railway vs Fly docs](https://docs.railway.com/platform/compare-to-fly) — platform comparison (Railway's own view). MEDIUM
- [Fly.io pricing](https://fly.io/pricing/) + [TheSoftwareScout: Fly vs Railway 2026](https://thesoftwarescout.com/fly-io-vs-railway-2026-which-developer-platform-should-you-deploy-on/) — machine sizing, multi-process. MEDIUM
- [PkgPulse: Scalar vs Redoc vs Swagger UI 2026](https://www.pkgpulse.com/blog/scalar-vs-redoc-vs-swagger-ui-api-documentation-2026) — download stats, feature matrix. MEDIUM
- [FastAPI OpenAPI docs reference](https://fastapi.tiangolo.com/reference/openapi/docs/) — built-in UI config. HIGH

---

*Stack research for: CadVerify beta launch additions*
*Researched: 2026-04-15*
