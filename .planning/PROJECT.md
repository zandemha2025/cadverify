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

## Current Milestone: v2.0 Enterprise

**Goal:** Enable enterprise-scale DFM analysis — batch processing millions of legacy parts, image-to-mesh reconstruction, STEP AP242 with GD&T extraction, and on-premise deployment hardening for customers like Saudi Aramco.

**Target features:**
- Batch API + Webhook Pipeline (process millions of parts via bulk upload)
- Image-to-Mesh Pipeline (reconstruct 3D geometry from photographs of legacy parts)
- STEP AP242 + GD&T/PMI Extraction (parse real engineering data beyond triangle meshes)
- On-Premise Deployment Hardening (air-gapped, SSO/SAML, RBAC, audit logging)

**Batch API + Webhook Pipeline:**
- [ ] POST /api/v1/batch endpoint accepting ZIP archives or S3 bucket references with CSV manifest
- [ ] Async job queue (arq) processing parts in parallel
- [ ] Webhook callbacks on batch/item completion
- [ ] Batch progress tracking API + dashboard
- [ ] Configurable concurrency limits per tenant

**Image-to-Mesh Pipeline:**
- [ ] TripoSR or InstantMesh integration for single/multi-image 3D reconstruction
- [ ] POST /api/v1/reconstruct endpoint accepting images, returning generated STL + analysis
- [ ] Quality confidence scoring on reconstructed meshes
- [ ] Automatic feed into /validate pipeline after reconstruction
- [ ] Frontend: image upload with preview, reconstruction progress, then analysis dashboard

**STEP AP242 + GD&T/PMI Extraction:**
- [ ] STEP AP242 parser with OpenCascade (cadquery/OCP) for B-rep geometry
- [ ] GD&T extraction (tolerances, datums, surface finish from PMI)
- [ ] Tolerance validation against manufacturing process capabilities
- [ ] Enhanced analysis using parametric features (not just mesh approximation)
- [ ] Report includes extracted tolerances + whether each process can hold them

**On-Premise Deployment Hardening:**
- [ ] SSO/SAML integration (replace Google OAuth with configurable IdP)
- [ ] RBAC (viewer, analyst, admin roles with permission matrix)
- [ ] Full audit logging (who analyzed what, when, compliance trail)
- [ ] Air-gapped Docker Compose with all deps bundled (no external network calls)
- [ ] Helm chart for Kubernetes deployment
- [ ] Configuration guide for enterprise IT

### Out of Scope

- **Billing / paid tiers** — free during beta; monetization deferred until usage validates demand
- **Email/password or OAuth login** — API-key-only simplifies auth surface; web UI authenticates via API key
- **Multi-user orgs / RBAC** — single API key per user for now
- **AWS/GCP full cloud build-out** — Vercel + Railway/Fly is cheap, fast, and enough for beta
- **SAM-3D synchronous inference** — too slow (30–60s) for interactive use; async only
- **Mesh-repair-as-a-service (advanced)** — basic `pymeshfix` only; no topology reconstruction, no GPU-based repair
- **CAD authoring / editing** — we analyze, we don't author
- **Real-time collaboration on analyses** — not a collaborative product
- **New analyzer categories beyond the existing 21** — fix/harden what's there rather than expand

## Context

**Codebase state (2026-04-15):**
- Substantial existing implementation across backend (FastAPI, trimesh, numpy, scipy, trimesh, cadquery), frontend (Next.js 16, React 19, Three.js), rule packs, material/machine DB, and SAM-3D module.
- Full codebase map in `.planning/codebase/` (ARCHITECTURE, STACK, STRUCTURE, CONVENTIONS, INTEGRATIONS, CONCERNS, TESTING).
- Tech debt surfaced: dual legacy/registry analyzer paths, silent exception swallowing, scattered constants, temp-file leaks, performance hot spots in ray casting.
- No auth, no persistence, no packaging story yet.

**User situation:**
- v1.0 milestone complete (8 phases, all deployed). Product is live.
- Now targeting enterprise customers (Saudi Aramco — 14 million legacy parts).
- Building competitive moat via image-to-mesh reconstruction and STEP AP242 parsing.

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
| arq as job queue | Already deployed in Phase 7; reuse for batch pipeline | Validated |
| Enterprise target (Saudi Aramco) | 14M legacy parts validates batch + image-to-mesh need | v2.0 |
| Image-to-mesh as competitive moat | TripoSR/InstantMesh reconstruction from photos is unique in DFM space | v2.0 |
| STEP AP242 over mesh-only analysis | Real engineering data (GD&T, tolerances) needed for enterprise credibility | v2.0 |
| On-prem deployment with SSO/RBAC | Enterprise customers require air-gapped, auditable deployments | v2.0 |

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
*Last updated: 2026-04-15 after v2.0 Enterprise milestone initialization*
