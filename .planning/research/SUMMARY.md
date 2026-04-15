# Project Research Summary — CadVerify

**Project:** CadVerify
**Domain:** DFM / CAD analysis SaaS — productization of existing analysis engine for public free beta
**Researched:** 2026-04-15
**Confidence:** HIGH

## Executive Summary

CadVerify is a dev-first, multi-process DFM API on a substantial and working engine (FastAPI + trimesh + cadquery; 21 process analyzers; Next.js 16 / React 19 / Three.js; rule packs and material/machine DB). This milestone is **not** about new analyzers — it is about turning the engine into a product: API-key auth, Postgres persistence with history + shareable URLs + PDF export, `pymeshfix` mesh repair, async SAM-3D via Redis-backed job queue, production Dockerfile with cadquery baked in, Vercel + Fly.io deploy. Research across four tracks converges on the same shape: a thin `services/` orchestration layer between existing routes and the untouched analyzer pipeline, with Postgres + Redis + an `arq` worker added alongside — no rewrites.

Prescriptive stack: SQLAlchemy 2.0 async + Alembic + asyncpg; DIY API keys (Argon2id/HMAC, no third-party IdP); `arq` wrapped in a thin `JobQueue` interface; WeasyPrint for PDFs; `pymeshfix` for repair; `slowapi` + Redis for rate limiting; Fly.io for backend + worker on a single Docker image with two entrypoints; Vercel frontend; Neon (or Fly) Postgres. **Keystone:** build the persistence + `analysis_service` layer first — once `analyses` rows exist, cache, history, shareable URLs, and PDF export all drop out of the same record.

Dominant risks cluster in three places: the **cadquery/OCP Docker image** (easily 2–4 GB and breaks cold starts — fixable with `cadquery-ocp-novtk`, multi-stage, amd64-only); the **async worker story on Fly** (auto-stop + ephemeral FS + visibility-timeout traps); and **abuse/cost control on a free tier** (per-key rate limits, Turnstile, kill-switch, magic-byte + triangle-cap DoS guards — must ship together with auth, not later). Observability (Sentry + structured logs + `/health` + uptime monitor) must land with deploy.

## Recommended Stack (canonical picks)

- **SQLAlchemy 2.0 async + asyncpg + Alembic** — ORM / driver / migrations; skip SQLModel.
- **DIY API keys** (`secrets.token_urlsafe` + Argon2id via `pwdlib`, HMAC-SHA256 prefix lookup) — ~60 LOC; no Auth0/Clerk in beta.
- **arq 0.27 on Redis** — asyncio-native queue, wrapped behind `JobQueue` protocol.
- **WeasyPrint 68.1 + Jinja2** — HTML → PDF, no Chromium.
- **pymeshfix 0.18 + `trimesh.repair` pre-pass** — only mesh-repair lib with current cross-platform wheels.
- **slowapi + Redis** — per-API-key rate limiting.
- **Fly.io** (backend + worker, same image, two entrypoints) + **Neon Postgres** + **Vercel** frontend.
- **`cadquery-ocp-novtk` wheel, multi-stage Dockerfile, amd64-only** — target <1.2 GB compressed.
- **Scalar at `/scalar`** for public API docs (keep default Swagger UI for try-it-out).

## Table-Stakes Feature Cut (launch with)

- API-key signup (Google OAuth + magic-link fallback; no passwords)
- Per-key rate limiting + usage dashboard + API-key management (rotate/revoke)
- Persistent analysis history (Postgres, keyed by user + mesh hash)
- Shareable analysis URL (opaque 12-char base62 ID, read-only)
- PDF export (engine version + mesh hash stamped)
- Mesh repair endpoint (`/api/v1/validate/repair`, `pymeshfix`)
- OpenAPI + Scalar docs; structured errors with codes + doc-links
- Result caching by mesh hash (falls out of persistence)
- Docker Compose quickstart + landing page with public demo

## Deferrables (v1.x / v2+)

- Python SDK, CLI, GitHub Action example
- Webhooks, billing (Stripe), multi-user orgs/RBAC, TypeScript SDK, CAD plugins
- SOC2/audit logging, sync SAM-3D, GPU default path, custom rule-pack UI

## Architecture Approach

Keep existing layered pipeline (routes → parsers → `GeometryContext` → universal → analyzer registry → rules → scoring) untouched. Add a thin `services/` layer that owns orchestration (hash → cache → run → persist). New top-level packages: `auth/`, `db/`, `persistence/`, `jobs/`, `storage/`, `middleware/`. Single Docker image for web + worker with different entrypoints. Auth via `Depends(require_api_key)` per protected route (not global middleware).

Minimum viable schema: 5 tables — `users`, `api_keys`, `analyses` (with `result_json JSONB` doubling as cache + history, `share_short_id` + `is_public` for share), `jobs` (durable mirror of queue state), `usage_events` (append-only, drives dashboard + rate-limit auditing).

## Top Pitfalls That Must Shape the Roadmap

1. **cadquery/OCP Docker image bloat + cold start** — target <1.2 GB compressed; `cadquery-ocp-novtk`, multi-stage, amd64-only. → `packaging-deploy`.
2. **API-key handling** — hash before storing, visible prefix for scanning, show full key once, multiple keys per user, scrub from logs, `Authorization: Bearer`. Retrofit = forced key regen. → `auth`.
3. **No usage caps + no DoS guards on free tier** — magic-byte + triangle-cap + subprocess timeout; per-key rate limit; Turnstile; kill-switch env var; billing alert. Ships with auth, not later. → `auth` + `stabilize-core`.
4. **Async worker state desync on Fly** — min-1 worker machine; ack-on-completion; visibility timeout ≥ 10 min; idempotent jobs keyed by mesh hash; persistent blob storage. → `async-sam3d`.
5. **Postgres migration breaks live beta** — expand-migrate-contract from day one; CI runs `alembic upgrade head`; `statement_timeout=5s`; `CREATE INDEX CONCURRENTLY`. → `persistence`.
6. **Shareable URL enumeration / PII leak** — opaque IDs; sanitized serializer; `X-Robots-Tag: noindex`; signed PDF download URLs. → `persistence` / `share`.
7. **Observability gap at launch** — Sentry, structlog + request-ID middleware, `/health` + UptimeRobot, cost alerts. → `packaging-deploy`.

## Suggested Phase Ordering

1. **Stabilize Core** — STEP temp-file leak, exception handling, registry-only analyzer path, centralized constants, wall-thickness epsilon, timeout, DoS guards, critical test gaps.
2. **Auth + Rate Limiting + Abuse Controls** (atomic unit) — signup, API keys, rate limits, Turnstile, kill-switch, CORS tightening, API-key management UI.
3. **Persistence + `analysis_service` + History + Caching** — **KEYSTONE**; unlocks share, PDF, cache, usage.
4. **Shareable URLs + PDF Export** — render from stored `analyses` row.
5. **Mesh Repair Endpoint** — independent, ~30% of uploads benefit.
6. **Packaging + Deploy + Observability** — public-URL gate; Dockerfile + Sentry non-negotiable.
7. **Async SAM-3D** — parallel track, can defer.
8. **Performance + Frontend Polish** — sampled ray-cast, batched analyzers, thumbnails, rate-limit header surfacing.

## Research Flags for Later Phases

- **Phase 2 (Auth):** OAuth provider choice (Google-only vs GitHub+Google vs magic-link), Turnstile, signup abuse model.
- **Phase 6 (Packaging):** cadquery Dockerfile is highest-risk artifact — dedicated spike.
- **Phase 7 (Async SAM-3D):** arq vs TaskIQ recheck; SAM-3D model weight size + license before baking.

Skip research for: Phases 1, 3, 4, 5, 8 — standard patterns.

## Confidence Assessment

| Area | Confidence |
|------|------------|
| Stack | HIGH (arq maintenance + pricing MEDIUM) |
| Features | MEDIUM-HIGH |
| Architecture | HIGH |
| Pitfalls | HIGH (LGPL interpretation MEDIUM) |

**Overall:** HIGH.

## Open Questions for Phase-Specific Research

- OAuth provider choice (Google-only vs GitHub+Google vs magic-link) — decide in Phase 2.
- Neon vs Fly Postgres — benchmark during Phase 3 or 6.
- SAM-3D model weights: provenance, license, size — confirm before Phase 7.
- arq vs TaskIQ at Phase 7 implementation time.
- Fly vs Railway final pick depends on egress pricing at beta volume — Phase 6 spike.
- OSS license posture for self-host path (Apache-2.0 vs BSL vs source-available).
- SDK strategy (auto-gen Fern vs hand-written) — post-beta.
