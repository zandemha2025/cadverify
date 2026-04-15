# CadVerify

## What This Is

CadVerify is a Design-for-Manufacturing (DFM) analysis service that ingests CAD files (STEP/STL), runs universal geometry checks plus 21 process-specific analyzers (additive, subtractive, formative), overlays industry rule packs (aerospace, automotive, medical, oil & gas), and recommends viable processes, materials, and machines. It's built for mechanical engineers, manufacturers, and developers who need automated manufacturability feedback before committing to tooling or print runs.

## Core Value

Upload a CAD file, get back trustworthy, process-aware manufacturability feedback in seconds — with enough specificity that an engineer can act on it.

## Requirements

### Validated

<!-- Inferred from existing codebase (see .planning/codebase/) -->

- ✓ FastAPI backend with `/api/v1/validate` and `/validate/quick` endpoints — existing
- ✓ STEP + STL parsing (cadquery optional, trimesh-based) — existing
- ✓ Universal geometry checks (watertight, normals, degenerate faces, self-intersection) — existing
- ✓ `GeometryContext` shared precomputation across analyzers — existing
- ✓ 21 process-specific analyzers via `@register` decorator registry (additive/subtractive/formative) — existing
- ✓ Legacy analyzer fallback path — existing (to be deprecated)
- ✓ Industry rule packs (aerospace, automotive, medical, oil & gas) — existing
- ✓ Feature detection (cylinders, flats, detector orchestrator) — existing
- ✓ Profile database (41 materials, 19 machines) + profile matcher — existing
- ✓ SAM-3D segmentation module (heuristic fallback) — existing, not production-ready
- ✓ Next.js 16 + React 19 + Three.js frontend with analysis dashboard — existing
- ✓ Fly.io deploy scaffolding for backend — existing

### Active

<!-- "Finish the product and make it usable" — public free beta, API-key auth, Vercel + Railway/Fly deploy -->

**Stabilize core (priority 1):**
- [ ] Fix STEP temp-file leak (explicit cleanup, `mode=0o600`)
- [ ] Replace silent `except Exception:` swallowing with categorized warnings + `Issue` emission
- [ ] Complete migration to registry-based analyzers; remove legacy `PROCESS_ANALYZERS` dual path
- [ ] Centralize manufacturing constants (move scattered thresholds into `profiles/` or dedicated config)
- [ ] Fix wall-thickness ray-cast `inf` case + scale-aware epsilon for micro/macro parts
- [ ] Configurable `ANALYSIS_TIMEOUT_SEC`; return 504 on exceed
- [ ] Fill critical test gaps (large meshes, STEP corruption, scoring ties, frontend error handling)

**Security & reliability:**
- [ ] File magic-byte / MIME validation beyond extension
- [ ] Rate limiting per API key
- [ ] Tighten CORS `allow_headers` once auth is in place
- [ ] Sandboxed / resource-limited mesh parsing path

**API-key authentication & tenancy:**
- [ ] Signup flow that issues API keys (no passwords, no web-app login required)
- [ ] Per-key usage tracking + rate limits
- [ ] Usage dashboard (read-only) for each key

**Persistence & history:**
- [ ] Postgres-backed analysis storage keyed by mesh hash + user
- [ ] User history UI with shareable analysis URLs
- [ ] PDF report export per analysis
- [ ] Result caching for identical inputs

**Mesh repair:**
- [ ] Integrate `pymeshfix` (or equivalent) for basic healing
- [ ] `/api/v1/validate/repair` endpoint — returns repaired mesh + re-analysis

**SAM-3D segmentation (async):**
- [ ] Background job queue (Celery / RQ / Fly machines) for SAM-3D inference
- [ ] Opt-in flag per analysis request; poll endpoint for results
- [ ] Pre-loaded model weights, embedding cache by mesh hash
- [ ] Graceful fallback to heuristic segmentation on failure

**Performance:**
- [ ] Batch analyzers with shared `GeometryContext` (single context, all requested processes)
- [ ] Sampled / BVH-accelerated ray casting for large meshes
- [ ] Request-level mesh cleanup; streaming or mmap for 500k+ face meshes

**Frontend polish:**
- [ ] API-key-aware client (auth header, rate-limit surfacing)
- [ ] History view + shareable URLs
- [ ] Report export UI
- [ ] Robust error handling (timeouts, malformed responses)
- [ ] Next.js/React dependency hygiene (Dependabot)

**Packaging & deployment:**
- [ ] Production Dockerfile with cadquery baked in (arm64 + amd64)
- [ ] `docker-compose.yml` for local dev (backend + Postgres + worker)
- [ ] Frontend deployed on Vercel
- [ ] Backend + worker deployed on Railway or Fly.io
- [ ] Managed Postgres (Neon / Supabase / Fly Postgres)
- [ ] CI pipeline (lint, typecheck, test, build)
- [ ] Landing page + API docs (OpenAPI / docs endpoint)
- [ ] One-command install path for self-hosters

### Out of Scope

- **Billing / paid tiers** — free during beta; monetization deferred until usage validates demand
- **Email/password or OAuth login** — API-key-only simplifies auth surface; web UI authenticates via API key
- **Multi-user orgs / RBAC** — single API key per user for now
- **AWS/GCP full cloud build-out** — Vercel + Railway/Fly is cheap, fast, and enough for beta
- **SAM-3D synchronous inference** — too slow (30–60s) for interactive use; async only
- **Mesh-repair-as-a-service (advanced)** — basic `pymeshfix` only; no topology reconstruction, no GPU-based repair
- **CAD authoring / editing** — we analyze, we don't author
- **Real-time collaboration on analyses** — not a collaborative product
- **On-prem enterprise deployment** — docker-compose reference only, no enterprise SLAs
- **New analyzer categories beyond the existing 21** — fix/harden what's there rather than expand

## Context

**Codebase state (2026-04-15):**
- Substantial existing implementation across backend (FastAPI, trimesh, numpy, scipy, trimesh, cadquery), frontend (Next.js 16, React 19, Three.js), rule packs, material/machine DB, and SAM-3D module.
- Full codebase map in `.planning/codebase/` (ARCHITECTURE, STACK, STRUCTURE, CONVENTIONS, INTEGRATIONS, CONCERNS, TESTING).
- Tech debt surfaced: dual legacy/registry analyzer paths, silent exception swallowing, scattered constants, temp-file leaks, performance hot spots in ray casting.
- No auth, no persistence, no packaging story yet.

**User situation:**
- Single builder shipping a public free beta.
- Wants it "done" and "usable" — not an experiment anymore.
- Prioritizes stabilizing the existing engine over new features.

## Constraints

- **Tech stack:** Python 3 / FastAPI / trimesh / cadquery (backend); Next.js 16 / React 19 / Three.js (frontend) — stack is fixed, no rewrites.
- **Deploy:** Frontend on Vercel, backend+worker on Railway or Fly.io, managed Postgres — avoid AWS/GCP complexity for beta.
- **Auth:** API keys only — no passwords, no OAuth, no sessions.
- **Monetization:** None during beta — must be free to use.
- **Packaging:** Must be installable via Docker / docker-compose for self-hosters and CI reproducibility.
- **cadquery dependency:** Hard to install cross-platform — Docker image must bake it in; document caveats for local-without-Docker.
- **Performance:** Typical analysis should finish in <10s; SAM-3D inference moves async.
- **Resource limits:** Beta runs on modest Railway/Fly instances — no GPU required for default path.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Public free beta, no billing | Validate demand before building payments; keep scope tight | — Pending |
| API-key-only auth | Matches developer-first use case; avoids session/password/OAuth complexity | — Pending |
| Vercel (frontend) + Railway/Fly (backend) + managed Postgres | Cheap, fast, autoscaling, no devops overhead vs. AWS | — Pending |
| Stabilize core before new features | Concerns doc shows real bug risk; trust matters for DFM output | — Pending |
| SAM-3D async only (job queue) | 30–60s inference unsuitable for sync HTTP; opt-in per request | — Pending |
| Include mesh repair via `pymeshfix` | Real friction point; lightweight lib fits beta scope | — Pending |
| Full history + shareable URLs + PDF export | Persistence is table-stakes for a product (vs. tool) | — Pending |
| Fine-grained phase slicing | Scope is broad; smaller phases reduce planning error | — Pending |
| Quality-gate agents on (researcher, plan-check, verifier) | Worth the token cost for a product-grade rollout | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-15 after initialization*
