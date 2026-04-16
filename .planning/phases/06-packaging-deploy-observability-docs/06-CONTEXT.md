# Phase 6: Packaging + Deploy + Observability + Docs - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area -- see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 6` if desired)

<domain>
## Phase Boundary

This phase takes CadVerify from "works on localhost" to "live at a public URL with observability, docs, and a self-host path." It is the **beta launch gate** -- nothing ships to real users until this phase completes.

Deliverables:
1. Multi-stage production Dockerfile baking in cadquery + WeasyPrint + pymeshfix on `cadquery-ocp-novtk` base, amd64-only, targeting <1.2 GB compressed. Single image serves both `uvicorn` (web) and `arq worker` via different entrypoints.
2. `docker-compose.yml` for local self-host: backend + worker + Postgres + Redis + frontend in one command, with `.env.example`.
3. `fly.toml` updated for min-1 backend machine + min-1 worker machine with Fly volumes for PDF blob cache.
4. Managed Postgres (Neon preferred, Fly Postgres fallback) with connection pooling.
5. Vercel frontend deployment with `NEXT_PUBLIC_API_BASE=https://api.cadverify.com`.
6. CI pipeline expanded: lint + typecheck + tests + `alembic upgrade head` check + `docker buildx` push on main.
7. `LICENSE`, `NOTICE`, `THIRD_PARTY_LICENSES.md` bundled for LGPL compliance (cadquery/OCP).
8. Sentry integrated (backend + Next.js frontend) with release tagging -- hooks into existing `sentry_before_send` scrubber and `structlog` processors.
9. Request-ID middleware (`X-Request-ID`) threaded through structlog context vars.
10. `/health` endpoint upgraded: returns 200 only when Postgres + Redis are reachable (current `/health` is static).
11. UptimeRobot (or equivalent free-tier monitor) polling `/health` every 1 minute with Slack/email alert.
12. Fly + Neon billing alerts at $50/month threshold.
13. OpenAPI at `/openapi.json`, Scalar docs at `/scalar`, Swagger UI at `/docs` (FastAPI provides Swagger by default; add Scalar).
14. Structured error responses `{code, message, doc_url}` with stable error codes across all endpoints.
15. Landing page with 1-sentence value prop, live demo (public STL upload, no auth required), "Get API key" CTA.
16. Quickstart docs: curl example, Docker Compose self-host path, authenticated request walkthrough.

**Explicitly out of scope for this phase:**
- SAM-3D async worker infrastructure (Phase 7 -- the worker entrypoint is wired but SAM jobs are not processed)
- Performance tuning of analyzers (Phase 8 -- PERF-*)
- Frontend polish beyond landing page and error handling for deploy (Phase 8)
- Custom domain email (Resend transactional is already configured in Phase 2)
- Stripe / billing (v2)
- ARM64 Docker builds (amd64-only for beta; Fly runs amd64)

</domain>

<decisions>
## Implementation Decisions

### Dockerfile Strategy (Highest-Risk Artifact)
- **D-01:** Base image is `cadquery/cadquery-ocp-novtk:latest` (Debian-based, includes OCP + cadquery without VTK). This avoids building cadquery from source and provides the OCCT kernel pre-compiled. WeasyPrint and pymeshfix are pip-installed on top.
  - Rationale (auto): `cadquery-ocp-novtk` is the only maintained pre-built cadquery wheel image that avoids the 2+ hour OCP compile. ROADMAP flagged this as the highest-risk artifact -- using the official image de-risks it. VTK is not needed (headless server).
- **D-02:** Multi-stage build: stage 1 (`builder`) installs all pip deps + compiles C extensions; stage 2 copies only the virtual env + app code. Target <1.2 GB compressed.
  - Rationale (auto): Standard Docker best practice for Python images. The 1.2 GB budget is tight with cadquery (~600 MB base) + WeasyPrint system deps (~100 MB) + pymeshfix (~50 MB) + trimesh + scipy + numpy. Multi-stage avoids shipping build-essential in the final image.
- **D-03:** amd64-only. No ARM64 builds for beta.
  - Rationale (auto): `cadquery-ocp-novtk` does not publish ARM64 wheels. Fly.io runs amd64. ARM64 would require a from-source OCP build (hours, fragile). Defer to v2 if M-series Mac developers need local Docker.
- **D-04:** Single image with dual entrypoint: `CMD ["uvicorn", ...]` for web, override to `CMD ["arq", "src.jobs.worker.WorkerSettings"]` for worker.
  - Rationale (auto): Avoids maintaining two Dockerfiles. Fly.io `[processes]` section allows different commands per machine group from the same image.
- **D-05:** LGPL compliance: `NOTICE` file in repo root listing cadquery + OCP LGPL-2.1 status. `THIRD_PARTY_LICENSES.md` generated from `pip-licenses`. Both copied into Docker image at `/app/NOTICE` and `/app/THIRD_PARTY_LICENSES.md`.
  - Rationale (auto): cadquery is LGPL-2.1, OCP is LGPL-2.1. CadVerify uses them as libraries (not modifying source), so LGPL requires: (a) notice of use, (b) copy of LGPL text, (c) ability for user to relink (Docker image satisfies this). Bundling NOTICE + license list is the standard compliance posture.

### Docker Compose (Self-Host Path)
- **D-06:** `docker-compose.yml` with services: `backend` (web), `worker`, `postgres` (postgres:16-alpine), `redis` (redis:7-alpine), `frontend` (node:20-alpine with Next.js standalone). Shared `.env` file.
  - Rationale (auto): Matches production topology. Postgres 16 is current stable. Redis 7 for rate limiting + future arq. Frontend as a separate service mirrors Vercel in prod.
- **D-07:** `.env.example` consolidated: all backend + frontend env vars documented with comments, grouped by concern (DB, Redis, auth, Sentry, Fly, Vercel).
  - Rationale (auto): Current `.env.example` files are split and incomplete (missing `DATABASE_URL`, `REDIS_URL`, `SENTRY_DSN`, `RELEASE`). A single consolidated template with grouping makes self-host setup copy-paste easy.

### Fly.io Deployment
- **D-08:** `fly.toml` updated with `[processes]` section: `web` (uvicorn, min 1 machine) and `worker` (arq, min 1 machine). Shared image, different commands. `auto_stop_machines = "suspend"` for the web process (faster wake than stop).
  - Rationale (auto): Current `fly.toml` has `min_machines_running = 0` which means cold starts on first request. For a beta launch gate, min-1 web machine avoids the first-user penalty. Worker needs to be always-on for background jobs.
- **D-09:** Fly volume (`cadverify_data`, 1 GB) mounted at `/data` for PDF blob cache. Environment variable `BLOB_STORAGE_PATH=/data/blobs`.
  - Rationale (auto): Phase 4 PDF service needs blob storage. Fly volumes are the simplest option (no Tigris/R2 setup for beta). 1 GB is generous for PDF caches at beta scale.
- **D-10:** Secrets managed via `fly secrets set`: `DATABASE_URL`, `REDIS_URL`, `SENTRY_DSN`, `SESSION_SECRET`, `RESEND_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `TURNSTILE_SECRET_KEY`, `HMAC_SECRET`. Never in `fly.toml` or `.env`.
  - Rationale (auto): Standard Fly.io secrets management. All sensitive values are already environment-variable-driven in the codebase.

### Managed Postgres
- **D-11:** Neon Postgres (free tier) as primary. Connection string via `DATABASE_URL` env var. Neon's built-in connection pooling (PgBouncer) enabled.
  - Rationale (auto): Neon free tier offers 0.5 GB storage, autoscale compute, built-in pooling, and a generous free plan for beta. Fly Postgres requires manual volume management and has no built-in pooling. Neon is the lower-ops choice.
- **D-12:** Alembic `upgrade head` runs as a CI step and as a pre-deploy hook (Fly `[deploy]` release_command).
  - Rationale (auto): Phase 3 established Alembic. Running migrations in CI catches schema drift. Running as release_command ensures prod DB is always current before new code serves traffic.

### Vercel Frontend
- **D-13:** Frontend deployed to Vercel via GitHub integration (auto-deploy on push to main). `NEXT_PUBLIC_API_BASE=https://api.cadverify.com` set in Vercel env vars. No `vercel.json` needed (Next.js auto-detected).
  - Rationale (auto): Vercel is already the decided platform (PROJECT.md). GitHub integration is zero-config for Next.js. The frontend `.env.example` already has `NEXT_PUBLIC_API_BASE`.

### CI Pipeline
- **D-14:** Expand existing `.github/workflows/ci.yml` with: (a) `alembic upgrade head` step in backend job (fresh SQLite or Postgres service container), (b) `docker buildx build` step that builds the production image (no push on PR, push on main), (c) `typecheck` step for backend (mypy or pyright, Claude's discretion on tool choice).
  - Rationale (auto): Current CI runs pytest + lint + frontend build but lacks migration check, Docker build validation, and type checking. Adding these catches the three most common deploy-breaker categories.
- **D-15:** Docker image pushed to Fly.io registry (`registry.fly.io/cadverify-api`) on main branch merge. Fly deploy uses the pre-built image (no build-on-deploy).
  - Rationale (auto): Building the cadquery image takes 5-10 minutes. Building once in CI and deploying the image avoids re-building on every `flyctl deploy`.

### Observability
- **D-16:** Sentry is already initialized in `main.py` (conditional on `SENTRY_DSN` env var) with `sentry_before_send` scrubber and `send_default_pii=False`. Phase 6 adds: (a) `release` tag from git SHA or `RELEASE` env var, (b) Sentry Next.js SDK in frontend with matching release tag, (c) `sentry_sdk.set_user({"id": user_id})` after `require_api_key` resolves.
  - Rationale (auto): Backend Sentry is 90% done. Frontend Sentry is missing. Release tagging enables deploy-correlated error tracking. User context (ID only, never email/key) enables per-user error grouping.
- **D-17:** Request-ID middleware: generate UUID4 `X-Request-ID` if not present in request headers; bind to structlog context vars; include in all response headers. Sentry events tagged with request ID.
  - Rationale (auto): structlog context vars are already configured. Adding request-ID threading is ~20 lines of middleware. Enables correlating a user-reported error to a specific log trail.
- **D-18:** `/health` endpoint upgraded to check Postgres (run `SELECT 1`) and Redis (`PING`). Returns `{"status": "ok", "postgres": true, "redis": true}` on success; HTTP 503 with `{"status": "degraded", ...}` if either fails.
  - Rationale (auto): Current `/health` is a static `{"status": "ok"}` that passes even when the DB is down. A real health check is required for Fly.io machine health and UptimeRobot monitoring.
- **D-19:** UptimeRobot free tier: monitor `https://api.cadverify.com/health` every 1 minute. Alert to Slack webhook (or email fallback).
  - Rationale (auto): UptimeRobot free tier supports 50 monitors with 1-minute intervals. Zero-cost, zero-maintenance external monitoring.
- **D-20:** Fly.io billing alert at $50/month via Fly dashboard. Neon billing alert at $50/month via Neon dashboard.
  - Rationale (auto): ROADMAP Pitfall 10 (no usage caps = runaway cost). $50/month is a reasonable beta-scale alert threshold. Both platforms support dashboard-based alerts.

### API Docs
- **D-21:** FastAPI already serves Swagger UI at `/docs` and OpenAPI JSON at `/openapi.json`. Add Scalar docs at `/scalar` via `scalar-fastapi` package (pip install, 3 lines of code).
  - Rationale (auto): Scalar provides a modern, searchable API docs UI that is superior to Swagger UI for developer experience. Both are served simultaneously (Swagger at `/docs`, Scalar at `/scalar`). Zero conflict.
- **D-22:** Structured error responses: all `HTTPException` raises migrated to return `{"code": "RATE_LIMITED", "message": "...", "doc_url": "https://docs.cadverify.com/errors/RATE_LIMITED"}`. Error codes are UPPER_SNAKE_CASE strings, stable across versions.
  - Rationale (auto): Current error responses are unstructured string messages. Stable error codes enable programmatic error handling by API consumers. `doc_url` is a future link (can 404 initially, but the structure is in place).

### Landing Page + Quickstart
- **D-23:** Landing page is a new Next.js route (`/`) on the existing frontend. Content: 1-sentence value prop ("Upload a CAD file, get manufacturability feedback in seconds"), public demo (hardcoded STL upload with no auth, using a public `/api/v1/validate/quick` endpoint), and "Get API key" CTA linking to `/auth/signup`.
  - Rationale (auto): The frontend already has a file upload flow. Making the landing page a route in the same app avoids a separate static site. The `/validate/quick` endpoint already exists for lightweight checks.
- **D-24:** Quickstart docs: a `/docs` route in the frontend (static MDX or simple React page) with three sections: (a) curl example, (b) Docker Compose self-host walkthrough, (c) authenticated request with API key.
  - Rationale (auto): Inline docs in the app are discoverable from the landing page. MDX or a simple component page is sufficient for beta. Separate docs site (Mintlify, GitBook) is overkill at this stage.

### Claude's Discretion
- Backend type-checker tool (mypy vs pyright) for CI
- Exact structlog processor ordering for request-ID injection
- UptimeRobot vs Betterstack vs other free uptime monitor
- Scalar vs Redocly for the alternative API docs UI
- Exact Docker multi-stage layer ordering for cache efficiency
- Landing page copy and visual design (within "clean, modern, minimal" constraint from prior phases)
- Whether to use Fly `release_command` or a separate CI step for Alembic migrations

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Docker / Packaging
- `.planning/codebase/STACK.md` -- Current Docker setup (python:3.12-slim base, node:20-alpine frontend), dependency list, containerization details
- `.planning/codebase/CONCERNS.md` -- Tech debt items that affect packaging (temp file cleanup, dep weight)
- `backend/Dockerfile` -- Existing backend Dockerfile (to be replaced with multi-stage cadquery build)
- `frontend/Dockerfile` -- Existing frontend Dockerfile (standalone Next.js build)
- `backend/requirements.txt` -- Full Python dependency list including WeasyPrint, pymeshfix, cadquery-adjacent deps

### Fly.io / Deploy
- `backend/fly.toml` -- Existing Fly config (to be updated with processes, volumes, min-machines)
- `.github/workflows/ci.yml` -- Existing CI pipeline (to be expanded with migration check, Docker build, typecheck)

### Observability
- `backend/main.py` -- Existing Sentry init (lines 64-72), structlog config (lines 49-62), static `/health` endpoint (lines 125-127), CORS config, middleware stack
- `backend/src/auth/scrubbing.py` -- Existing `sentry_before_send` + `scrub_processor` for log/Sentry sanitization

### Prior Phase Context
- `.planning/phases/02-auth-rate-limiting-abuse-controls/02-CONTEXT.md` -- Auth decisions (OAuth, Turnstile, rate limits, CORS) that affect deploy config
- `.planning/phases/03-persistence-analysis-service-history-caching/03-CONTEXT.md` -- Postgres/Alembic decisions that affect managed DB + migration deploy
- `.planning/phases/04-shareable-urls-pdf-export/04-CONTEXT.md` -- PDF blob storage decisions that affect Fly volumes
- `.planning/phases/05-mesh-repair-endpoint/05-CONTEXT.md` -- pymeshfix dep that affects Docker image size

### ROADMAP Flags
- `.planning/ROADMAP.md` Phase 6 section -- Success criteria, key deliverables, risk callouts (Pitfalls 1, 2, 3, 8, 9, 10)
- `.planning/REQUIREMENTS.md` PKG-01 through PKG-08, OBS-01 through OBS-05, DOC-01 through DOC-04

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/main.py` Sentry init block (lines 64-72): conditional on `SENTRY_DSN`, uses `sentry_before_send` scrubber, `send_default_pii=False`, `release` tag from env. Extend, don't rewrite.
- `backend/main.py` structlog config (lines 49-62): already has `scrub_processor`, `JSONRenderer`, context vars. Request-ID middleware plugs into `merge_contextvars`.
- `backend/main.py` `/health` endpoint (line 125-127): static response. Upgrade to check DB + Redis.
- `backend/src/auth/scrubbing.py`: `sentry_before_send` and `scrub_processor` -- already production-ready. Reuse as-is.
- `backend/fly.toml`: existing Fly app `cadverify-api` in `iad` region. Update in-place.
- `.github/workflows/ci.yml`: existing jobs for backend tests, route-auth-coverage, sentry-leak-grep, frontend build, Fly deploy. Expand, don't replace.
- `frontend/.env.example`: already has `NEXT_PUBLIC_API_BASE=https://api.cadverify.com`.

### Established Patterns
- Environment-variable-driven config: all secrets and feature flags are env vars (no config files beyond `.env`).
- Conditional feature init: Sentry, SAM-3D, kill-switch all gate on env vars. New features should follow this pattern.
- FastAPI router composition: routers registered via `app.include_router()` with prefix. New routes (Scalar, health upgrade) follow this.
- Alembic migrations with expand-migrate-contract discipline (Phase 3 decision).

### Integration Points
- `backend/Dockerfile` is the primary artifact to replace. The existing `python:3.12-slim` base must change to `cadquery-ocp-novtk`.
- `backend/fly.toml` needs `[processes]`, `[[mounts]]`, `[deploy]` sections added.
- `.github/workflows/ci.yml` deploy job currently builds on Fly (line 119). Change to push pre-built image.
- `backend/main.py` needs: (a) request-ID middleware, (b) `/health` upgrade, (c) Scalar mount, (d) structured error handler.
- `frontend/src/app/page.tsx` is the landing page entry point. Current content is the upload/analysis dashboard -- needs a landing page wrapper or conditional.

</code_context>

<specifics>
## Specific Ideas

- ROADMAP explicitly flags "cadquery Dockerfile spike" as the **single highest-risk artifact** in the milestone. Plan 6.A should be treated as a spike/proof with an explicit size-check gate before proceeding.
- The existing Docker image is `python:3.12-slim` (~150 MB). Switching to `cadquery-ocp-novtk` (~800 MB base) means the image size budget is extremely tight. WeasyPrint system dependencies (libpango, libcairo, libgdk-pixbuf) add ~80-100 MB. Budget must be validated early.
- Current `fly.toml` has `min_machines_running = 0` -- this will cause cold-start latency on first request after idle. For launch, min-1 is necessary.
- The CI deploy job (line 119) currently runs `flyctl deploy --dockerfile` which builds on Fly's remote builder. For a 1.2 GB image with cadquery, this is slow and unreliable. Switching to pre-built image push is essential.

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 06-packaging-deploy-observability-docs*
*Context gathered: 2026-04-15*
