# Phase 6: Packaging + Deploy + Observability + Docs - Research

**Researched:** 2026-04-15
**Status:** Complete

## RESEARCH COMPLETE

## 1. cadquery Dockerfile Spike (Highest-Risk Artifact)

### Key Finding: cadquery-ocp-novtk is a pip-installable wheel, NOT a Docker base image

The CONTEXT.md assumed `cadquery-ocp-novtk` is a Docker base image. **It is not.** It is a PyPI package (latest: v7.9.3.1, Feb 2026) providing pre-compiled OCP wheels:

- **manylinux_2_31 x86_64 wheel:** ~67.5 MB
- **Supports Python 3.10-3.14** on Linux x86_64
- Requires glibc 2.31+ (Debian Bullseye+ or Ubuntu 20.04+)

**Corrected Dockerfile strategy:** Use `python:3.12-slim` (Debian Bookworm, glibc 2.36) as base. Install `cadquery-ocp-novtk` and `cadquery` via pip. No need for a special Docker Hub base image.

### Image Size Budget

| Component | Estimated Size (compressed) |
|-----------|---------------------------|
| python:3.12-slim base | ~50 MB |
| cadquery-ocp-novtk wheel | ~67 MB |
| cadquery + deps | ~15 MB |
| trimesh + numpy + scipy + shapely | ~120 MB |
| WeasyPrint + system deps (libpango, libcairo, libgdk-pixbuf, fonts) | ~80-100 MB |
| pymeshfix | ~20 MB |
| SQLAlchemy + asyncpg + alembic + redis + other app deps | ~30 MB |
| Application code | ~5 MB |
| **Total estimated** | **~390-410 MB compressed** |

**Verdict:** Well under 1.2 GB compressed target. The key risk was that cadquery/OCP required a massive base image or from-source compile -- the pre-built wheel eliminates this.

### Multi-Stage Build Strategy

```
Stage 1 (builder): python:3.12-slim
  - Install build-essential, libgl1, libglib2.0, WeasyPrint system deps
  - Create venv, pip install all requirements
  
Stage 2 (runtime): python:3.12-slim  
  - Install only runtime libs (no build-essential)
  - Copy venv from builder
  - Copy app code
  - ~300-400 MB compressed
```

### ARM64 Status

cadquery-ocp-novtk **does** publish ARM64 Linux wheels (manylinux_2_31_aarch64). However, the CONTEXT.md decision D-03 says amd64-only for beta (Fly.io runs amd64). ARM64 is feasible for v2 if needed.

### WeasyPrint System Dependencies

WeasyPrint requires these Debian packages at runtime:
- `libpango-1.0-0`, `libpangocairo-1.0-0`, `libpangoft2-1.0-0`
- `libcairo2`, `libgdk-pixbuf-2.0-0`
- `libffi8`, `fonts-dejavu-core` (for PDF rendering)

These must be in both builder and runtime stages (runtime deps, not build deps).

### LGPL Compliance

- `cadquery`: Apache-2.0 (no copyleft concern)
- `cadquery-ocp-novtk` (OCP bindings): LGPL-2.1
- CadVerify uses OCP as a library (dynamic linking via Python wheel). LGPL requires:
  1. Notice of LGPL-licensed components (NOTICE file)
  2. Copy of LGPL-2.1 text (LICENSE-LGPL-2.1)
  3. Ability for user to relink (satisfied by pip -- user can `pip install` a different version)
- Action: `pip-licenses --format=markdown > THIRD_PARTY_LICENSES.md`, create NOTICE file listing cadquery-ocp-novtk LGPL status.

## 2. Fly.io Configuration

### Process Groups (fly.toml)

Fly.io supports multiple process groups from the same image via `[processes]` section:

```toml
[processes]
  web = "uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2"
  worker = "arq src.jobs.worker.WorkerSettings"

[http_service]
  processes = ["web"]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "suspend"
  auto_start_machines = true
  min_machines_running = 1
  
  [http_service.concurrency]
    type = "requests"
    hard_limit = 50
    soft_limit = 25
```

Key points:
- Process group commands supersede Docker CMD (not ENTRYPOINT)
- `http_service.processes = ["web"]` limits HTTP to web machines only
- `min_machines_running = 1` keeps one web machine always warm (no cold start)
- Worker machines do not receive HTTP traffic

### Volumes for PDF Cache

```toml
[[mounts]]
  source = "cadverify_data"
  destination = "/data"
  processes = ["web"]
  initial_size = "1gb"
```

Volumes are per-machine and persist across restarts. 1 GB is generous for beta PDF cache.

### Release Command for Migrations

```toml
[deploy]
  release_command = "alembic upgrade head"

[deploy.release_command_vm]
  size = "shared-cpu-1x"
  memory = "512mb"
```

Release command runs in a temporary VM before the new version serves traffic. Ideal for Alembic migrations.

### Secrets

All sensitive values via `fly secrets set`:
- `DATABASE_URL` (Neon pooled connection string)
- `REDIS_URL`
- `SENTRY_DSN`
- `SESSION_SECRET`
- `RESEND_API_KEY`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `TURNSTILE_SECRET_KEY`
- `HMAC_SECRET`
- `RELEASE` (set to git SHA via CI)

### VM Sizing

```toml
[[vm]]
  memory = "1gb"
  cpu_kind = "shared"
  cpus = 2
```

Existing config is reasonable for beta. 1 GB RAM handles cadquery + WeasyPrint rendering. 2 shared CPUs sufficient for <100 concurrent users.

## 3. Neon Postgres

### Free Tier (2026)

- 0.5 GB storage
- 100 compute-hours/month
- Up to 2 Compute Units
- Scale-to-zero always active
- One project

### Connection Pooling

Built-in PgBouncer in transaction mode. Two connection string variants:
- Direct: `postgresql://user:pass@ep-xyz.region.neon.tech/dbname` (for Alembic migrations)
- Pooled: `postgresql://user:pass@ep-xyz-pooler.region.neon.tech/dbname` (for app queries)

**Important:** Use direct connection for `alembic upgrade head` (DDL requires persistent session). Use pooled connection for application `DATABASE_URL`.

Environment variable pattern:
- `DATABASE_URL` = pooled connection (app)
- `DATABASE_URL_DIRECT` = direct connection (migrations)

### Alembic Migration Strategy

The `[deploy] release_command` should use `DATABASE_URL_DIRECT`:
```bash
DATABASE_URL=$DATABASE_URL_DIRECT alembic upgrade head
```

Or set `sqlalchemy.url` in `alembic.ini` to read from a separate env var.

## 4. Sentry Integration

### Backend (Existing)

Already implemented in `main.py`:
- Conditional on `SENTRY_DSN` env var
- `sentry_before_send` scrubber from `src/auth/scrubbing.py`
- `send_default_pii=False`
- `release` tag from `RELEASE` env var

**Needed additions:**
- Set `RELEASE` to git SHA in CI/CD
- Add `sentry_sdk.set_user({"id": user_id})` after `require_api_key` resolves (user ID only, never email/key)
- Bind request ID to Sentry scope via `sentry_sdk.set_tag("request_id", request_id)`

### Frontend (New)

`@sentry/nextjs` v10.x (latest: 10.48.0):
- Install: `npm install @sentry/nextjs`
- Wizard creates: `instrumentation-client.ts`, `sentry.server.config.ts`, `sentry.edge.config.ts`
- Auto-creates `app/global-error.tsx` for React rendering errors
- Release tagging: `SENTRY_RELEASE` env var in Vercel

### Request-ID Middleware

```python
import uuid
from starlette.middleware.base import BaseHTTPMiddleware

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

Integrates with existing structlog `merge_contextvars` processor.

## 5. Health Check Endpoint

Current `/health` is static. Upgrade to check DB + Redis:

```python
@app.get("/health")
async def health_check():
    checks = {"postgres": False, "redis": False}
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception:
        pass
    try:
        redis = get_redis()
        await redis.ping()
        checks["redis"] = True
    except Exception:
        pass
    
    status = "ok" if all(checks.values()) else "degraded"
    code = 200 if status == "ok" else 503
    return JSONResponse(
        {"status": status, **checks, "version": app.version},
        status_code=code,
    )
```

Fly.io uses this for machine health checks. UptimeRobot polls externally.

## 6. Scalar API Docs

`scalar-fastapi` v1.8.2 (Apr 2026, MIT license):

```python
from scalar_fastapi import get_scalar_api_reference

@app.get("/scalar", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
    )
```

Serves alongside existing Swagger UI at `/docs`. No conflict.

## 7. CI Pipeline Expansion

Current `.github/workflows/ci.yml` has:
- Backend tests (pytest)
- Route auth coverage check
- Sentry leak grep
- Frontend build + lint
- Fly.io deploy (builds on Fly remote builder)

**Additions needed:**

### Alembic Migration Check
```yaml
- name: Check Alembic migrations
  run: |
    pip install -r requirements.txt
    alembic upgrade head
    alembic downgrade -1
    alembic upgrade head
  env:
    DATABASE_URL: sqlite:///test.db
```

### Docker Build + Push
```yaml
- name: Build and push Docker image
  uses: docker/build-push-action@v5
  with:
    context: backend
    push: ${{ github.ref == 'refs/heads/main' }}
    tags: registry.fly.io/cadverify-api:${{ github.sha }}
    platforms: linux/amd64
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

### Deploy Using Pre-Built Image
```yaml
- name: Deploy backend to Fly.io
  run: flyctl deploy --image registry.fly.io/cadverify-api:${{ github.sha }} --config backend/fly.toml
  env:
    FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

This avoids rebuilding the image on Fly's remote builder (5-10 min saved).

## 8. Structured Error Responses

Pattern for all HTTPException raises:

```python
ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    413: "FILE_TOO_LARGE",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
    504: "ANALYSIS_TIMEOUT",
}

class StructuredHTTPException(HTTPException):
    def __init__(self, status_code, code, message, doc_url=None):
        self.code = code
        self.doc_url = doc_url or f"https://docs.cadverify.com/errors/{code}"
        super().__init__(status_code=status_code, detail={
            "code": code,
            "message": message,
            "doc_url": self.doc_url,
        })
```

## 9. Docker Compose for Self-Host

```yaml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [postgres, redis]
    
  worker:
    build: ./backend
    command: arq src.jobs.worker.WorkerSettings
    env_file: .env
    depends_on: [postgres, redis]
    
  postgres:
    image: postgres:16-alpine
    volumes: [pgdata:/var/lib/postgresql/data]
    environment:
      POSTGRES_DB: cadverify
      POSTGRES_USER: cadverify
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-localdev}
    
  redis:
    image: redis:7-alpine
    
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000/api/v1

volumes:
  pgdata:
```

## 10. Landing Page + Quickstart

### Landing Page Structure
- Route: `/` in Next.js app
- Above fold: headline + 1-sentence value prop + public demo upload
- Below fold: "How it works" 3-step, "Get API key" CTA
- Public demo uses `/api/v1/validate/quick` (no auth required -- already exists)

### Quickstart Docs
- Route: `/docs` in Next.js app (static MDX page or React component)
- Sections: (1) curl example, (2) Docker Compose self-host, (3) authenticated request

## Validation Architecture

### Test Strategy
- Dockerfile: build succeeds, image size < 1.2 GB (CI gate)
- Docker Compose: `docker compose up -d && curl localhost:8000/health` (integration test)
- Health endpoint: unit test with mocked DB/Redis failures
- Sentry: existing `test_sentry_leak.py` covers scrubbing; add frontend Sentry init test
- Structured errors: unit tests asserting `{code, message, doc_url}` shape
- Fly deploy: smoke test via `flyctl ssh console` after deploy

---

*Research completed: 2026-04-15*
