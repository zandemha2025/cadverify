# Phase 6: Packaging + Deploy + Observability + Docs - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 06-packaging-deploy-observability-docs
**Mode:** --auto (all decisions auto-selected by Claude)
**Areas discussed:** Dockerfile Strategy, Docker Compose, Fly.io Deployment, Managed Postgres, Vercel Frontend, CI Pipeline, Observability, API Docs, Landing Page + Quickstart

---

## Dockerfile Strategy (Highest-Risk Artifact)

| Option | Description | Selected |
|--------|-------------|----------|
| cadquery-ocp-novtk base | Pre-built Debian image with OCP + cadquery, no VTK. Multi-stage build on top. | ✓ |
| Build cadquery from source on python:3.12-slim | Compile OCP + cadquery in Docker build. Full control, smaller if trimmed aggressively. | |
| Conda-based image | Use conda-forge cadquery package. Larger image, different dep management. | |

**User's choice:** [auto] cadquery-ocp-novtk base (recommended default)
**Notes:** ROADMAP flagged this as highest-risk artifact. Pre-built image avoids 2+ hour compile and fragile build deps. VTK not needed for headless server. amd64-only (no ARM64 cadquery wheels).

## Docker Compose (Self-Host Path)

| Option | Description | Selected |
|--------|-------------|----------|
| Full topology (backend + worker + postgres + redis + frontend) | Mirrors production. 5 services in one compose file. | ✓ |
| Minimal (backend + postgres only) | Simpler, but missing worker + redis + frontend. | |

**User's choice:** [auto] Full topology (recommended default)
**Notes:** Self-hosters need the complete stack. `.env.example` consolidates all vars.

## Fly.io Deployment

| Option | Description | Selected |
|--------|-------------|----------|
| Processes section (web + worker from same image) | Single image, dual entrypoint via `[processes]`. Min-1 web machine. | ✓ |
| Separate Fly apps for web and worker | Two fly.toml files, two images. More isolation, more ops. | |

**User's choice:** [auto] Processes section (recommended default)
**Notes:** Single image reduces build time and registry storage. Fly `[processes]` is the standard pattern for web + worker.

## Managed Postgres

| Option | Description | Selected |
|--------|-------------|----------|
| Neon (free tier, built-in pooling) | Serverless Postgres, autoscale, PgBouncer included. | ✓ |
| Fly Postgres (attached volume) | Co-located with app. Manual volume management, no built-in pooling. | |
| Supabase (free tier) | Postgres + auth + realtime. Overkill features, but free tier available. | |

**User's choice:** [auto] Neon (recommended default)
**Notes:** Neon free tier is generous for beta. Built-in pooling avoids deploying PgBouncer. Lower ops than Fly Postgres.

## Vercel Frontend

| Option | Description | Selected |
|--------|-------------|----------|
| Vercel GitHub integration (auto-deploy) | Zero-config for Next.js. Auto-deploy on push to main. | ✓ |
| Manual Vercel CLI deploy in CI | More control, but adds CI complexity. | |

**User's choice:** [auto] Vercel GitHub integration (recommended default)
**Notes:** Already decided in PROJECT.md. Frontend `.env.example` already has Vercel-ready vars.

## CI Pipeline

| Option | Description | Selected |
|--------|-------------|----------|
| Expand existing ci.yml (add migration, Docker build, typecheck) | Incremental improvement. Single workflow file. | ✓ |
| Separate workflows (ci.yml + deploy.yml + docker.yml) | More modular, but more files to maintain. | |

**User's choice:** [auto] Expand existing ci.yml (recommended default)
**Notes:** Current ci.yml is manageable. Adding 3 steps is simpler than splitting into multiple files.

## Observability

| Option | Description | Selected |
|--------|-------------|----------|
| Extend existing Sentry + structlog setup | Backend Sentry 90% done. Add frontend Sentry, request-ID middleware, health upgrade. | ✓ |
| Replace with OpenTelemetry + Grafana | Full observability stack. Overkill for beta, high ops cost. | |

**User's choice:** [auto] Extend existing setup (recommended default)
**Notes:** Sentry and structlog are already integrated. Extending is minimal work. OTel deferred to post-beta.

## API Docs

| Option | Description | Selected |
|--------|-------------|----------|
| Scalar + Swagger (both served) | Scalar at /scalar for modern DX, Swagger at /docs for familiarity. | ✓ |
| Swagger only (FastAPI default) | Already works. Less polished. | |
| Redocly | Alternative to Scalar. Similar features. | |

**User's choice:** [auto] Scalar + Swagger (recommended default)
**Notes:** Scalar is a 3-line addition via `scalar-fastapi`. Both UIs served simultaneously.

## Landing Page + Quickstart

| Option | Description | Selected |
|--------|-------------|----------|
| In-app landing page (Next.js route) | Landing page as `/` in existing frontend. Public demo via `/validate/quick`. | ✓ |
| Separate static site (e.g., Astro, plain HTML) | Faster load, separate deploy. More to maintain. | |

**User's choice:** [auto] In-app landing page (recommended default)
**Notes:** Existing frontend already has upload flow. In-app avoids maintaining a separate site.

---

## Claude's Discretion

- Backend type-checker tool (mypy vs pyright) for CI
- Exact structlog processor ordering for request-ID injection
- UptimeRobot vs Betterstack vs other free uptime monitor
- Scalar vs Redocly for alternative API docs UI
- Exact Docker multi-stage layer ordering for cache efficiency
- Landing page copy and visual design
- Whether to use Fly release_command or CI step for Alembic migrations

## Deferred Ideas

None -- discussion stayed within phase scope.
