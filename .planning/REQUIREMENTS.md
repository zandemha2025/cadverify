# Requirements: CadVerify

**Defined:** 2026-04-15
**Core Value:** Upload a CAD file, get back trustworthy, process-aware manufacturability feedback in seconds — with enough specificity that an engineer can act on it.

## v1 Requirements (Public Free Beta)

### Stabilize Core (Engine Trust)

- [ ] **CORE-01**: STEP parser cleans up temp files via context manager (no `/tmp` leakage)
- [x] **CORE-02**: Bare `except Exception:` in analyzers replaced with categorized warnings + explicit `Issue` emission
- [ ] **CORE-03**: Legacy `PROCESS_ANALYZERS` dual path removed; all processes served via registry
- [ ] **CORE-04**: Manufacturing constants centralized in a single config module (not scattered per analyzer file)
- [x] **CORE-05**: Wall-thickness ray-cast returns typed failure (not silent `inf`) and uses scale-aware epsilon for micro/macro parts
- [x] **CORE-06**: Configurable `ANALYSIS_TIMEOUT_SEC` env var returns HTTP 504 on exceed
- [ ] **CORE-07**: File upload validates magic bytes (STEP/STL) and enforces triangle-count cap before parsing
- [x] **CORE-08**: Critical test gaps filled — large mesh (>200k faces), STEP corruption, process-scoring ties, frontend error handling

### Authentication & Abuse Controls

- [x] **AUTH-01**: User can sign up via Google OAuth
- [x] **AUTH-02**: User can sign up via magic link (email) as fallback
- [x] **AUTH-03**: Signup issues an API key of form `cv_live_<prefix>_<secret>`, shown exactly once
- [x] **AUTH-04**: API keys stored hashed (Argon2id) with HMAC-SHA256 prefix index for lookup
- [x] **AUTH-05**: User can create, rotate, and revoke multiple API keys from dashboard
- [x] **AUTH-06**: All protected endpoints require `Authorization: Bearer cv_live_...` via FastAPI `Depends(require_api_key)`
- [x] **AUTH-07**: Per-API-key rate limit enforced (60/hour, 500/day) via slowapi + Redis
- [x] **AUTH-08**: Per-IP signup rate limit; Turnstile challenge on signup form
- [x] **AUTH-09**: `ACCEPTING_NEW_ANALYSES` kill-switch env var halts validation endpoints when disabled
- [x] **AUTH-10**: Logs and Sentry scrub API keys and bearer tokens before transport
- [x] **AUTH-11**: CORS tightened — explicit `allow_headers`, regex origin match, `allow_credentials=False`

### Persistence & History (Keystone)

- [x] **PERS-01**: Postgres schema created via Alembic: `users`, `api_keys`, `analyses`, `jobs`, `usage_events`
- [x] **PERS-02**: Alembic migrations enforce expand-migrate-contract; CI runs `alembic upgrade head` on every PR
- [x] **PERS-03**: `services/analysis_service.py` wraps existing pipeline (hash → cache lookup → run → persist)
- [x] **PERS-04**: Analysis results stored keyed by `(user_id, mesh_hash, analysis_version)`
- [x] **PERS-05**: Identical mesh+process request returns cached result without re-running pipeline
- [x] **PERS-06**: `GET /api/v1/analyses` returns paginated user history
- [x] **PERS-07**: `GET /api/v1/analyses/{id}` returns full stored result
- [x] **PERS-08**: Every analysis writes a `usage_events` row (for dashboard + rate-limit audit)
- [x] **PERS-09**: Usage dashboard UI shows recent analyses, quota consumption, and API-key activity

### Shareable URLs

- [x] **SHARE-01**: `POST /api/v1/analyses/{id}/share` issues a 12-char base62 `share_short_id` and sets `is_public=true`
- [x] **SHARE-02**: `DELETE /api/v1/analyses/{id}/share` revokes (nulls `share_short_id`, sets `is_public=false`)
- [x] **SHARE-03**: Public `GET /s/{short_id}` serves sanitized analysis (no email, no API-key prefix, no user PII)
- [x] **SHARE-04**: Share pages set `X-Robots-Tag: noindex` and `Cache-Control: private, no-store` where appropriate
- [x] **SHARE-05**: Frontend exposes "Share" and "Unshare" controls on analysis view with copy-to-clipboard

### PDF Export

- [x] **PDF-01**: `GET /api/v1/analyses/{id}/pdf` returns a rendered PDF of the analysis
- [x] **PDF-02**: PDF template built with WeasyPrint + Jinja2; includes verdict, issues, process ranking, material/machine recs
- [x] **PDF-03**: PDF footer stamps engine version + mesh SHA + analysis timestamp for reproducibility
- [x] **PDF-04**: PDF bytes cached in blob storage (Tigris/R2/Fly volume) keyed by analysis ID
- [x] **PDF-05**: Frontend exposes "Download PDF" button on analysis view and history items

### Mesh Repair

- [x] **REPAIR-01**: `POST /api/v1/validate/repair` accepts STL/STEP, runs `trimesh.repair` pre-pass + `pymeshfix.MeshFix` for hard cases
- [x] **REPAIR-02**: Endpoint returns repaired STL bytes plus a re-analysis of the repaired mesh
- [x] **REPAIR-03**: Frontend offers "Attempt repair" action when original analysis flags non-manifold or holes

### Async SAM-3D

- [x] **SAM-01**: `JobQueue` protocol implemented with arq as default backend; Redis configured
- [x] **SAM-02**: `POST /api/v1/validate?segmentation=sam3d` persists sync portion, returns 202 + `{analysis_id, job_id, poll_url}`
- [x] **SAM-03**: `GET /api/v1/jobs/{id}` returns job status + result URL when complete
- [ ] **SAM-04**: SAM-3D model weights pre-baked into worker image (no cold-start download)
- [ ] **SAM-05**: Embedding cache in blob storage keyed by mesh hash
- [x] **SAM-06**: Jobs idempotent (keyed by mesh hash + params); duplicate enqueue returns existing job
- [ ] **SAM-07**: Worker visibility timeout ≥ 10 min; ack-on-completion only
- [ ] **SAM-08**: Graceful fallback to heuristic segmentation on SAM-3D failure; job marked `partial` not `failed`

### Packaging & Deployment

- [ ] **PKG-01**: Multi-stage Dockerfile built on `cadquery-ocp-novtk`; amd64-only; <1.2 GB compressed
- [ ] **PKG-02**: Single image serves both web and worker via different entrypoints (`uvicorn`, `arq worker`)
- [x] **PKG-03**: `docker-compose.yml` for local dev — backend, worker, Postgres, Redis, frontend in one command
- [x] **PKG-04**: Fly.io `fly.toml` with min-1 backend machine + min-1 worker machine
- [x] **PKG-05**: Managed Postgres provisioned (Neon or Fly Postgres) with connection pooling
- [x] **PKG-06**: Frontend deployed to Vercel with custom `api.cadverify.com` backend origin
- [x] **PKG-07**: CI pipeline runs lint, typecheck, tests, Alembic upgrade check, and buildx push on main
- [ ] **PKG-08**: `LICENSE`, `NOTICE`, and `THIRD_PARTY_LICENSES.md` bundled in image (LGPL compliance for cadquery/OCP)

### Observability

- [x] **OBS-01**: Sentry integrated in backend + Next.js frontend with release tagging
- [x] **OBS-02**: structlog + request-ID middleware; every log line carries request ID and user ID (when authed)
- [x] **OBS-03**: `/health` endpoint reports DB + Redis reachability and reports 200 only when both healthy
- [x] **OBS-04**: UptimeRobot (or equivalent) polls `/health` every 1 min with alerting
- [x] **OBS-05**: Billing alerts configured on Fly + Neon at $50/month threshold

### Docs & Landing

- [x] **DOC-01**: OpenAPI schema served at `/openapi.json`; Scalar docs at `/scalar`; Swagger UI at `/docs`
- [x] **DOC-02**: Error responses use structured format `{code, message, doc_url}` with stable error codes
- [x] **DOC-03**: Landing page with 1-sentence value prop, live demo (public STL), "Get API key" CTA
- [x] **DOC-04**: Quickstart docs — curl example, Docker Compose path, authenticated request walkthrough

### Performance & Frontend Polish

- [ ] **PERF-01**: Batched analyzer run shares a single `GeometryContext` across requested processes
- [ ] **PERF-02**: Sampled / BVH-accelerated ray-casting for meshes > 50k faces
- [ ] **PERF-03**: Request-level mesh cleanup releases memory after analysis persists
- [x] **PERF-04**: Frontend API client attaches `Authorization` header, surfaces rate-limit headers in UI
- [x] **PERF-05**: Frontend handles network timeout, malformed response, and server 5xx gracefully (no unhandled rejections)
- [x] **PERF-06**: Dependabot (or equivalent) configured for frontend + backend dependency updates

## v2.0 Requirements (Enterprise)

### Batch API + Webhook Pipeline

- [x] **BATCH-01**: User can submit a ZIP archive or S3 bucket reference with CSV manifest to `POST /api/v1/batch`, receiving a batch job ID
- [x] **BATCH-02**: Batch processor decompresses archive, validates manifest, and enqueues each part for parallel analysis via arq
- [x] **BATCH-03**: User can configure webhook URL per batch; system sends POST callback on batch completion and per-item completion
- [x] **BATCH-04**: User can poll `GET /api/v1/batch/{id}` for real-time progress (items total, completed, failed, in-progress)
- [x] **BATCH-05**: User can view batch progress dashboard in frontend with per-item status drill-down
- [x] **BATCH-06**: Admin can configure per-tenant concurrency limits (max parallel workers per batch) via environment or API

### Image-to-Mesh Pipeline

- [x] **IMG-01**: User can upload single or multiple images to `POST /api/v1/reconstruct`; system reconstructs 3D mesh via TripoSR or InstantMesh
- [x] **IMG-02**: Reconstruction endpoint returns generated STL bytes plus a full DFM analysis of the reconstructed mesh
- [x] **IMG-03**: System assigns a quality confidence score (0-1) to each reconstructed mesh based on reconstruction metrics
- [x] **IMG-04**: Reconstructed mesh is automatically fed into the existing `/validate` pipeline without manual re-upload
- [x] **IMG-05**: Frontend provides image upload with preview, reconstruction progress indicator, and seamless transition to analysis dashboard

### STEP AP242 + GD&T/PMI Extraction

- [x] **STEP-01**: System parses STEP AP242 files using OpenCascade (cadquery/OCP) to extract B-rep geometry and topology
- [x] **STEP-02**: System extracts GD&T annotations (tolerances, datums, surface finish) from PMI data embedded in STEP AP242
- [x] **STEP-03**: System validates extracted tolerances against manufacturing process capability tables (can this process hold this tolerance?)
- [x] **STEP-04**: Analysis pipeline uses parametric B-rep features (exact geometry) instead of mesh approximation when STEP AP242 is provided
- [ ] **STEP-05**: Analysis report includes extracted tolerances table and per-process tolerance achievability assessment

### On-Premise Deployment Hardening

- [ ] **ONPREM-01**: System supports SSO/SAML authentication with configurable Identity Provider (replacing or augmenting Google OAuth)
- [ ] **ONPREM-02**: RBAC enforced with three roles (viewer, analyst, admin) and a permission matrix governing API access
- [ ] **ONPREM-03**: Full audit log records every analysis action (who analyzed what file, when, what result) for compliance trails
- [ ] **ONPREM-04**: Air-gapped Docker Compose deployment bundles all dependencies with zero external network calls at runtime
- [ ] **ONPREM-05**: Helm chart provided for Kubernetes deployment with configurable replicas, resource limits, and persistent volumes
- [ ] **ONPREM-06**: Enterprise configuration guide documents SSO setup, RBAC configuration, audit log export, and air-gapped installation

### Deferred from v2.0

- **SDK-01**: Python SDK (auto-generated from OpenAPI)
- **SDK-02**: CLI for upload + analyze workflows
- **SDK-03**: GitHub Action example for CAD validation in CI
- **BILL-01**: Stripe integration; usage-based + seat-based plans
- **BILL-02**: Paid tier unlocks higher rate limits, longer history retention, team seats
- **ORG-01**: Multi-user organizations with role-based access (partially addressed by ONPREM-02 RBAC)
- **ORG-02**: Shared API keys + per-member audit log
- **ADV-01**: Synchronous SAM-3D mode (GPU-backed, paid tier only)
- **ADV-02**: Custom rule-pack builder UI

## Out of Scope

| Feature | Reason |
|---------|--------|
| Email + password login | API-key-only simpler; OAuth + magic link covers signup |
| Stripe / billing | Free beta; monetize after demand validation |
| Multi-user orgs / RBAC | Partially addressed by ONPREM-02 in v2.0; full org model deferred |
| AWS / GCP full deployment | Vercel + Fly + Neon is cheap and sufficient; avoid devops overhead |
| Synchronous SAM-3D | 30–60s inference unsuitable for sync HTTP |
| Advanced mesh reconstruction | `pymeshfix` covers ~80% of repair value at a fraction of the effort |
| CAD authoring / editing | Out of domain — we analyze, we don't author |
| Real-time collaboration | Not a collaborative product |
| New analyzer categories | 21 existing analyzers; harden rather than expand in this milestone |
| TypeScript SDK | Defer until demand from JS users |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CORE-01 | Phase 1 | Pending |
| CORE-02 | Phase 1 | Complete |
| CORE-03 | Phase 1 | Pending |
| CORE-04 | Phase 1 | Pending |
| CORE-05 | Phase 1 | Complete |
| CORE-06 | Phase 1 | Complete |
| CORE-07 | Phase 1 | Pending |
| CORE-08 | Phase 1 | Complete |
| AUTH-01 | Phase 2 | Complete |
| AUTH-02 | Phase 2 | Complete |
| AUTH-03 | Phase 2 | Complete |
| AUTH-04 | Phase 2 | Complete |
| AUTH-05 | Phase 2 | Complete |
| AUTH-06 | Phase 2 | Complete |
| AUTH-07 | Phase 2 | Complete |
| AUTH-08 | Phase 2 | Complete |
| AUTH-09 | Phase 2 | Complete |
| AUTH-10 | Phase 2 | Complete |
| AUTH-11 | Phase 2 | Complete |
| PERS-01 | Phase 3 | Complete |
| PERS-02 | Phase 3 | Complete |
| PERS-03 | Phase 3 | Complete |
| PERS-04 | Phase 3 | Complete |
| PERS-05 | Phase 3 | Complete |
| PERS-06 | Phase 3 | Complete |
| PERS-07 | Phase 3 | Complete |
| PERS-08 | Phase 3 | Complete |
| PERS-09 | Phase 3 | Complete |
| SHARE-01 | Phase 4 | Complete |
| SHARE-02 | Phase 4 | Complete |
| SHARE-03 | Phase 4 | Complete |
| SHARE-04 | Phase 4 | Complete |
| SHARE-05 | Phase 4 | Complete |
| PDF-01 | Phase 4 | Complete |
| PDF-02 | Phase 4 | Complete |
| PDF-03 | Phase 4 | Complete |
| PDF-04 | Phase 4 | Complete |
| PDF-05 | Phase 4 | Complete |
| REPAIR-01 | Phase 5 | Complete |
| REPAIR-02 | Phase 5 | Complete |
| REPAIR-03 | Phase 5 | Complete |
| PKG-01 | Phase 6 | Pending |
| PKG-02 | Phase 6 | Pending |
| PKG-03 | Phase 6 | Complete |
| PKG-04 | Phase 6 | Complete |
| PKG-05 | Phase 6 | Complete |
| PKG-06 | Phase 6 | Complete |
| PKG-07 | Phase 6 | Complete |
| PKG-08 | Phase 6 | Pending |
| OBS-01 | Phase 6 | Complete |
| OBS-02 | Phase 6 | Complete |
| OBS-03 | Phase 6 | Complete |
| OBS-04 | Phase 6 | Complete |
| OBS-05 | Phase 6 | Complete |
| DOC-01 | Phase 6 | Complete |
| DOC-02 | Phase 6 | Complete |
| DOC-03 | Phase 6 | Complete |
| DOC-04 | Phase 6 | Complete |
| SAM-01 | Phase 7 | Complete |
| SAM-02 | Phase 7 | Complete |
| SAM-03 | Phase 7 | Complete |
| SAM-04 | Phase 7 | Pending |
| SAM-05 | Phase 7 | Pending |
| SAM-06 | Phase 7 | Complete |
| SAM-07 | Phase 7 | Pending |
| SAM-08 | Phase 7 | Pending |
| PERF-01 | Phase 8 | Pending |
| PERF-02 | Phase 8 | Pending |
| PERF-03 | Phase 8 | Pending |
| PERF-04 | Phase 8 | Complete |
| PERF-05 | Phase 8 | Complete |
| PERF-06 | Phase 8 | Complete |

| BATCH-01 | Phase 9 | Complete |
| BATCH-02 | Phase 9 | Complete |
| BATCH-03 | Phase 9 | Complete |
| BATCH-04 | Phase 9 | Complete |
| BATCH-05 | Phase 9 | Complete |
| BATCH-06 | Phase 9 | Complete |
| IMG-01 | Phase 10 | Complete |
| IMG-02 | Phase 10 | Complete |
| IMG-03 | Phase 10 | Complete |
| IMG-04 | Phase 10 | Complete |
| IMG-05 | Phase 10 | Complete |
| STEP-01 | Phase 11 | Complete |
| STEP-02 | Phase 11 | Complete |
| STEP-03 | Phase 11 | Complete |
| STEP-04 | Phase 11 | Complete |
| STEP-05 | Phase 11 | Pending |
| ONPREM-01 | Phase 12 | Pending |
| ONPREM-02 | Phase 12 | Pending |
| ONPREM-03 | Phase 12 | Pending |
| ONPREM-04 | Phase 12 | Pending |
| ONPREM-05 | Phase 12 | Pending |
| ONPREM-06 | Phase 12 | Pending |

**Coverage:**
- v1 requirements: 70 total (mapped to Phases 1-8)
- v2.0 requirements: 22 total (mapped to Phases 9-12)
- Grand total: 92
- Mapped to phases: 92
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-15*
*Last updated: 2026-04-15 after v2.0 Enterprise milestone definition*
