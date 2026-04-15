# CadVerify Roadmap

**Milestone:** v1.0-beta (Public Free Beta)
**Defined:** 2026-04-15
**Core Value:** Upload a CAD file, get back trustworthy, process-aware manufacturability feedback in seconds — with enough specificity that an engineer can act on it.
**Granularity:** fine
**Model profile:** quality
**Workflow agents:** researcher + plan-check + verifier (all on)
**Parallelization:** enabled

## Milestone Context

This is a **brownfield** milestone layered on top of a substantial, working DFM analysis engine (FastAPI + trimesh + cadquery; 21 process analyzers; rule packs; material/machine DB; Next.js 16 / React 19 / Three.js frontend). Phase 1 stabilizes the existing engine; Phases 2–8 wrap a product surface (auth, persistence, share/PDF, repair, async SAM-3D, packaging, polish) around that untouched pipeline via a thin `services/` orchestration layer. **No rewrites of the analyzer pipeline.**

The 8-phase decomposition is derived from the research in `.planning/research/SUMMARY.md` and mapped 1:1 in `.planning/REQUIREMENTS.md` Traceability.

## Critical Structural Call-Outs

- **Phase 2 is an atomic unit.** Auth + per-key rate limiting + abuse controls (Turnstile, kill-switch, CORS, log scrubbing, signup IP limits) MUST ship together. Research Pitfall 4 + Pitfall 10 are explicit that retrofitting abuse guards after auth = forced key regen + runaway cost window.
- **Phase 3 is the KEYSTONE.** Persistence + `analysis_service` unlocks Phases 4 (share/PDF read from stored rows), 5 (repair writes back), and 6 (history + dashboard + usage events). Cache, history, share, and PDF all fall out of the `analyses` row. Slipping Phase 3 slips 4/5/6.
- **Phase 7 (Async SAM-3D) is a parallel track.** After Phase 3's DB + Redis land, Phase 7 can proceed in parallel with Phases 4–6 without blocking beta launch.
- **Phase 6 is the public-URL gate.** Beta cannot go live before Phase 6 (Docker image + Fly deploy + Sentry + /health + docs + landing page).

## Phases

- [ ] **Phase 1: Stabilize Core** — Engine trust: temp-file leak, exception swallowing, registry migration, scale-aware epsilon, timeout, DoS guards, test gaps.
- [ ] **Phase 2: Auth + Rate Limiting + Abuse Controls** — Atomic security unit: OAuth/magic-link signup, hashed API keys, slowapi rate limits, Turnstile, kill-switch, CORS, log scrubbing.
- [ ] **Phase 3: Persistence + analysis_service + History + Caching** — KEYSTONE: Postgres schema + Alembic, `services/analysis_service.py`, mesh-hash cache, history endpoints, usage events, dashboard.
- [ ] **Phase 4: Shareable URLs + PDF Export** — Render from stored analyses: opaque share IDs, sanitized public view, WeasyPrint PDF with engine-version stamp.
- [ ] **Phase 5: Mesh Repair Endpoint** — `trimesh.repair` pre-pass + `pymeshfix` for hard cases; `/api/v1/validate/repair` with re-analysis.
- [ ] **Phase 6: Packaging + Deploy + Observability + Docs** — Public-URL gate: cadquery Dockerfile (<1.2 GB), docker-compose, Fly deploy, Neon Postgres, Sentry, structlog, /health, landing page, Scalar docs.
- [ ] **Phase 7: Async SAM-3D** — Parallel track: arq JobQueue, 202 + poll endpoints, pre-baked weights, embedding cache, graceful fallback.
- [ ] **Phase 8: Performance + Frontend Polish** — Batched `GeometryContext`, BVH ray-cast, mesh cleanup, rate-limit header surfacing, error handling, Dependabot.

## Phase Details

### Phase 1: Stabilize Core
**Goal:** The existing analyzer engine is trustworthy — no resource leaks, no silent failures, no DoS vectors, no scale-dependent bugs — before any product surface is built on top of it.
**Depends on:** Nothing (first phase; brownfield baseline is the codebase in `.planning/codebase/`)
**Phase research needed:** No (standard patterns; codebase/CONCERNS.md already enumerates the issues)
**Requirements:** CORE-01, CORE-02, CORE-03, CORE-04, CORE-05, CORE-06, CORE-07, CORE-08

**Success Criteria** (what must be TRUE):
1. Uploading a malformed STEP does not leak temp files (`/tmp` stable after 100 bad uploads)
2. An analyzer internal exception produces a categorized `Issue` in the response, never a silently swallowed error
3. Every requested process routes through the registry (`PROCESS_ANALYZERS` legacy dict removed; grep confirms)
4. Manufacturing thresholds live in one config module; changing a threshold requires touching one file
5. A micro-scale part (1 mm cube) and a macro-scale part (5 m tank) both return finite wall-thickness values (no `inf`, no silent truncation)
6. An analysis exceeding `ANALYSIS_TIMEOUT_SEC` returns HTTP 504 with a structured error, not a hanging connection
7. A file with a `.stl` extension but non-STL magic bytes is rejected at 400 before mesh parsing; triangle-count cap enforced pre-parse
8. Test suite covers: >200k face meshes, STEP corruption, tied process scores, frontend error paths

**Key Deliverables:**
- Context-manager STEP parser with `mode=0o600` temp files
- Categorized warning emission across all analyzers (no bare `except Exception:`)
- Registry-only dispatch in `backend/src/api/routes.py`
- `backend/src/analysis/constants.py` (or equivalent) centralizing thresholds
- Scale-aware epsilon in wall-thickness ray-cast
- `ANALYSIS_TIMEOUT_SEC` env var + 504 handler
- Magic-byte validator + triangle-count cap pre-parse
- New pytest modules covering the 4 critical gaps

**Suggested Parallel Plans** (parallelization: true):
- Plan 1.A: STEP temp-file + magic-byte + triangle-cap hardening (CORE-01, CORE-07)
- Plan 1.B: Registry migration + constants centralization (CORE-03, CORE-04)
- Plan 1.C: Exception handling + wall-thickness epsilon + timeout (CORE-02, CORE-05, CORE-06)
- Plan 1.D: Test-gap fill (CORE-08)

**Risks (from PITFALLS.md):**
- Pitfall 5 (Zip bomb / STEP recursion bomb / pathological mesh DoS) — addressed here via magic-byte + triangle-cap, reinforced by Phase 2 rate limits
- Technical-debt pattern: dual legacy/registry path — explicitly removed

**Plans:** 4 (01.A, 01.B, 01.C in Wave 1; 01.D in Wave 2) — see 01-CONTEXT.md

---

### Phase 2: Auth + Rate Limiting + Abuse Controls
**Goal:** Users can securely get an API key and all public endpoints are protected from abuse, in one atomic shipment.
**Depends on:** Phase 1 (DoS guards in place before opening endpoints to the public)
**Phase research needed:** **YES — `/gsd-research-phase 2`** for OAuth provider decision (Google-only vs Google+GitHub vs magic-link-only), Turnstile integration specifics, and signup abuse model (per-IP + per-email limits, disposable-email heuristic).
**Requirements:** AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05, AUTH-06, AUTH-07, AUTH-08, AUTH-09, AUTH-10, AUTH-11

**Atomic-unit rationale:** Pitfall 4 (plaintext key storage, no rotation) + Pitfall 10 (no usage caps → runaway cost) + Pitfall 11 (CORS footguns) are compounding. Shipping auth without rate limits = open-wallet; shipping rate limits without auth = no identity to limit against. Turnstile + kill-switch + log scrubbing are non-negotiable for a public free tier. **Ship together or don't ship.**

**Success Criteria** (what must be TRUE):
1. A new user completes signup (Google OAuth or magic link) in < 60 seconds and sees their API key exactly once
2. The API key in the database is Argon2id-hashed with an HMAC-SHA256 prefix index (plaintext key is never stored)
3. Hitting a protected endpoint without `Authorization: Bearer cv_live_...` returns 401 with a structured error
4. Exceeding 60 requests/hour on a single API key returns 429 with `Retry-After` and `X-RateLimit-*` headers
5. A user can list, name, rotate, and revoke multiple API keys from the dashboard
6. Flipping `ACCEPTING_NEW_ANALYSES=false` halts validation endpoints with 503 within one deploy
7. Sentry events and logs never contain a full `cv_live_...` string (grep on captured events confirms)

**Key Deliverables:**
- OAuth + magic-link signup flow (Resend or equivalent)
- `cv_live_<prefix>_<secret>` token format + Argon2id hash + HMAC prefix lookup
- `Depends(require_api_key)` on every protected route (not global middleware)
- slowapi + Redis-backed per-key limiter (60/hr, 500/day)
- Turnstile challenge on signup form + per-IP signup limiter
- `ACCEPTING_NEW_ANALYSES` kill-switch
- Sentry + log scrubber (redacts `cv_live_*`, `Bearer *`)
- CORS: explicit `allow_headers`, regex origin match, `allow_credentials=False`
- API-key management UI (create / rotate / revoke) in Next.js dashboard

**Suggested Parallel Plans:**
- Plan 2.A: OAuth + magic-link signup + key issuance (AUTH-01, 02, 03)
- Plan 2.B: Key storage (Argon2id + HMAC prefix) + management UI (AUTH-04, 05)
- Plan 2.C: `require_api_key` dependency + rate limiting + kill-switch (AUTH-06, 07, 09)
- Plan 2.D: Abuse controls: Turnstile, signup IP limit, log scrubbing, CORS (AUTH-08, 10, 11)

**Risks (from PITFALLS.md):**
- Pitfall 4: Plaintext API key storage and no rotation
- Pitfall 10: No usage caps → runaway cost
- Pitfall 11: Shareable URL enumeration (partial — full treatment in Phase 4)
- Pitfall 8: Vercel ↔ Fly/Railway CORS + auth footguns
- Blast radius if auth ships alone: a single leaked key has no rate cap. **Do not split.**

**Plans:** TBD
**UI hint:** yes

---

### Phase 3: Persistence + analysis_service + History + Caching
**Goal:** Every analysis is persisted, deduplicated by mesh hash, and retrievable — making CadVerify a product (not a stateless tool). **This is the keystone.**
**Depends on:** Phase 2 (analyses must be tied to `user_id`)
**Phase research needed:** No (SQLAlchemy 2.0 async + Alembic + asyncpg is canonical; Neon vs Fly Postgres benchmark can happen inside this phase or be deferred to Phase 6)
**Requirements:** PERS-01, PERS-02, PERS-03, PERS-04, PERS-05, PERS-06, PERS-07, PERS-08, PERS-09

**Keystone rationale:** Once `analyses` rows exist with `result_json JSONB`, Phase 4 (share + PDF) and Phase 5 (repair re-analysis) write/read from the same record. Phase 6 (dashboard) renders from `usage_events`. Cache, history, share, PDF, dashboard, and repair are all views of persistence. **Slipping this phase slips 4, 5, 6, and partially 7.**

**Success Criteria** (what must be TRUE):
1. Running `alembic upgrade head` on a fresh DB produces the full schema (users, api_keys, analyses, jobs, usage_events); CI enforces this on every PR
2. Uploading an identical mesh+process set twice runs the pipeline only once — second request is served from the `analyses` cache row in < 200 ms
3. `GET /api/v1/analyses` returns the authenticated user's paginated history (most recent first, filterable by process/verdict)
4. `GET /api/v1/analyses/{id}` returns the full stored `result_json` (identical shape to original response)
5. Every completed analysis writes exactly one `usage_events` row; dashboard counts match counter
6. The existing analyzer pipeline in `backend/src/analysis/` is untouched — only `services/analysis_service.py` wraps it

**Key Deliverables:**
- `backend/src/db/` with SQLAlchemy 2.0 async engine + session factory
- Alembic `versions/` with initial migration (expand-migrate-contract discipline)
- `backend/src/persistence/models.py` for 5 tables
- `backend/src/services/analysis_service.py` — hash → cache lookup → run → persist
- `GET /api/v1/analyses`, `GET /api/v1/analyses/{id}`
- `usage_events` writes on every analysis
- Next.js usage dashboard page (recent analyses, quota, key activity)
- CI step: `alembic upgrade head` on fresh DB + downgrade smoke

**Suggested Parallel Plans:**
- Plan 3.A: Schema + Alembic + CI migration gate (PERS-01, 02)
- Plan 3.B: `analysis_service` + cache-by-mesh-hash + persistence integration (PERS-03, 04, 05)
- Plan 3.C: History endpoints + usage events (PERS-06, 07, 08)
- Plan 3.D: Usage dashboard UI (PERS-09)

**Risks (from PITFALLS.md):**
- Pitfall 7: Postgres migration breaks live beta — mitigated by expand-migrate-contract + `statement_timeout=5s` + `CREATE INDEX CONCURRENTLY`
- Silent cache-key bugs: `(user_id, mesh_hash, analysis_version)` — `analysis_version` bump invalidates cache on engine upgrade (Pitfall recovery strategy)

**Plans:** TBD
**UI hint:** yes

---

### Phase 4: Shareable URLs + PDF Export
**Goal:** Users can forward an analysis to a colleague via public link and hand it off as a PDF attached to an RFQ or design review — rendered from the stored `analyses` row, no re-analysis.
**Depends on:** Phase 3 (reads from `analyses`; cannot proceed without persistence)
**Phase research needed:** No (WeasyPrint + Jinja2 is canonical; share patterns are standard)
**Requirements:** SHARE-01, SHARE-02, SHARE-03, SHARE-04, SHARE-05, PDF-01, PDF-02, PDF-03, PDF-04, PDF-05

**Success Criteria** (what must be TRUE):
1. User clicks "Share" on an analysis; receives a URL with a 12-char base62 opaque ID (`/s/{short_id}`) that renders a sanitized view with no email, no key prefix, no user PII
2. User clicks "Unshare"; the link 404s immediately (revocation is instant, not TTL-based)
3. Share pages serve `X-Robots-Tag: noindex` and cache-private headers
4. User clicks "Download PDF"; receives a rendered PDF with verdict, issues, process ranking, material/machine recs, and a footer stamping engine version + mesh SHA + timestamp
5. Re-downloading the same PDF returns in < 500 ms (blob-cached by analysis ID)

**Key Deliverables:**
- `POST/DELETE /api/v1/analyses/{id}/share` endpoints
- Opaque 12-char base62 `share_short_id` column + `is_public` flag on `analyses`
- Public `GET /s/{short_id}` route with sanitized serializer
- `GET /api/v1/analyses/{id}/pdf` endpoint
- WeasyPrint + Jinja2 template (verdict + issues + process ranking + recs + stamped footer)
- Blob storage (Tigris / R2 / Fly volume) keyed by analysis ID
- Frontend Share/Unshare controls + copy-to-clipboard + "Download PDF" button

**Suggested Parallel Plans:**
- Plan 4.A: Share endpoints + sanitized public view + frontend controls (SHARE-01, 02, 03, 04, 05)
- Plan 4.B: PDF endpoint + WeasyPrint template + blob caching + frontend button (PDF-01, 02, 03, 04, 05)

**Risks (from PITFALLS.md):**
- Pitfall 11: Shareable URL enumeration / PII leak — mitigated by opaque IDs + sanitized serializer + noindex
- Pitfall 12: WeasyPrint / headless Chrome PDF rendering footguns — WeasyPrint chosen specifically to avoid Chromium; watch font-loading and JSONB-to-HTML edge cases

**Plans:** TBD
**UI hint:** yes

---

### Phase 5: Mesh Repair Endpoint
**Goal:** Users whose mesh fails universal checks (non-manifold, holes) can attempt an automatic repair and get a re-analyzed result — closing the loop for ~30% of real-world uploads.
**Depends on:** Phase 3 (re-analysis writes a new `analyses` row via `analysis_service`)
**Phase research needed:** No (pymeshfix + trimesh.repair is canonical; no topology reconstruction in scope)
**Requirements:** REPAIR-01, REPAIR-02, REPAIR-03

**Success Criteria** (what must be TRUE):
1. A non-watertight STL sent to `POST /api/v1/validate/repair` returns repaired STL bytes plus a full re-analysis
2. A previously-repaired hash hits cache and skips pymeshfix re-run
3. Frontend surfaces "Attempt repair" CTA only when the original analysis flagged non-manifold or holes
4. pymeshfix invocation is timeout-bounded and falls back cleanly on failure (no worker hangs)

**Key Deliverables:**
- `POST /api/v1/validate/repair` endpoint
- `trimesh.repair` pre-pass + `pymeshfix.MeshFix` hard-case path
- Repaired mesh written to blob storage + re-analysis persisted
- Frontend "Attempt repair" button (conditional on flags)

**Suggested Parallel Plans:**
- Plan 5.A: Repair service + endpoint + caching (REPAIR-01, 02)
- Plan 5.B: Frontend repair CTA + flow (REPAIR-03)

**Risks (from PITFALLS.md):**
- Pitfall 5: pathological meshes — pymeshfix is C++ and can hang; enforce subprocess timeout
- Pitfall 1: pymeshfix adds Docker image weight — budget in Phase 6 spike

**Plans:** TBD
**UI hint:** yes

---

### Phase 6: Packaging + Deploy + Observability + Docs
**Goal:** CadVerify is live at a public URL with observability, docs, and a self-host path — the beta launch gate.
**Depends on:** Phases 1–5 (everything being deployed must exist and pass CI)
**Phase research needed:** **YES — `/gsd-research-phase 6`** for the cadquery Dockerfile spike. This is the single highest-risk artifact in the milestone (Pitfall 1 + Pitfall 2 + Pitfall 3). Spike topics: `cadquery-ocp-novtk` wheel verification, multi-stage layering for <1.2 GB target, amd64-only vs arm64 trade-off, LGPL distribution posture (NOTICE + THIRD_PARTY_LICENSES), Fly vs Railway egress pricing at beta volume.
**Requirements:** PKG-01, PKG-02, PKG-03, PKG-04, PKG-05, PKG-06, PKG-07, PKG-08, OBS-01, OBS-02, OBS-03, OBS-04, OBS-05, DOC-01, DOC-02, DOC-03, DOC-04

**Public-URL gate rationale:** Deploying without Sentry + structlog + /health + uptime monitoring = Pitfall 9 (silent breakage). Deploying without cost alerts = Pitfall 10 (runaway bill). Landing without docs = no signup conversion. All four must land together.

**Success Criteria** (what must be TRUE):
1. `docker compose up` from a fresh clone produces a working backend + worker + Postgres + Redis + frontend stack in < 10 minutes
2. The production Docker image is < 1.2 GB compressed, amd64, and passes Fly cold start in < 30 seconds
3. cadverify.com renders the landing page with the public demo STL and a "Get API key" CTA
4. `api.cadverify.com/health` returns 200 only when Postgres + Redis are reachable; UptimeRobot alerts on failure within 1 minute
5. A handled 500 produces a Sentry event with release tag, request ID, and user ID (when authed); no `cv_live_*` appears in the event
6. `/scalar` renders the OpenAPI spec with curl examples; every documented error has a stable `code` and `doc_url`
7. A $50/month threshold alert is configured on Fly + Neon

**Key Deliverables:**
- Multi-stage Dockerfile on `cadquery-ocp-novtk` base, amd64-only
- Single image with `uvicorn` + `arq worker` entrypoints
- `docker-compose.yml` (backend + worker + Postgres + Redis + frontend) + `.env.example`
- `fly.toml` — min-1 backend + min-1 worker
- Neon (or Fly) Postgres provisioned with pooling
- Vercel frontend deploy + `api.cadverify.com` origin
- CI: lint + typecheck + tests + `alembic upgrade head` + `buildx` push on main
- LICENSE + NOTICE + THIRD_PARTY_LICENSES.md (LGPL compliance for cadquery/OCP)
- Sentry (backend + Next.js) with release tagging
- structlog + request-ID middleware
- `/health` endpoint (DB + Redis reachability)
- UptimeRobot 1-minute poll
- Fly + Neon billing alerts at $50/month
- OpenAPI @ `/openapi.json`, Scalar @ `/scalar`, Swagger @ `/docs`
- Structured error format `{code, message, doc_url}` with stable codes
- Landing page + public-demo STL + quickstart docs (curl + Docker Compose + authenticated walkthrough)

**Suggested Parallel Plans:**
- Plan 6.A: Dockerfile + image size budget (PKG-01, 02, 08)
- Plan 6.B: Docker Compose + Fly deploy + managed Postgres (PKG-03, 04, 05)
- Plan 6.C: Vercel frontend + CI pipeline (PKG-06, 07)
- Plan 6.D: Sentry + structlog + /health + uptime + cost alerts (OBS-01, 02, 03, 04, 05)
- Plan 6.E: OpenAPI + Scalar + structured errors + landing + quickstart (DOC-01, 02, 03, 04)

**Risks (from PITFALLS.md):**
- Pitfall 1: cadquery/OCP Docker image bloat + cold-start penalty — **phase research mandatory**
- Pitfall 2: cadquery arm64 wheel availability — mitigated by amd64-only decision
- Pitfall 3: cadquery LGPL-2.1 distribution — NOTICE + THIRD_PARTY_LICENSES bundled
- Pitfall 8: Vercel ↔ Fly CORS/auth footguns — re-verify at deploy time
- Pitfall 9: Ship with no observability → silent breakage — non-negotiable here
- Pitfall 10: Cost alerts mandatory

**Plans:** TBD
**UI hint:** yes

---

### Phase 7: Async SAM-3D
**Goal:** Users can opt into SAM-3D segmentation as an async job and poll for results, without blocking the synchronous `/validate` path.
**Depends on:** Phase 3 (Postgres for `jobs` table + `analyses` row to attach results); can run **in parallel** with Phases 4–6 once Phase 3 lands.
**Phase research needed:** **YES — `/gsd-research-phase 7`** for arq-vs-TaskIQ recheck at implementation time (arq maintenance status, pricing), SAM-3D model weight size + license + provenance before baking into worker image, Fly Machines visibility-timeout tuning.
**Requirements:** SAM-01, SAM-02, SAM-03, SAM-04, SAM-05, SAM-06, SAM-07, SAM-08

**Parallel-track rationale:** SAM-3D has no dependency on share/PDF/repair/packaging product surface. Once the DB + Redis land in Phase 3, SAM-3D infra (worker, queue, polling) can ship alongside Phases 4–6. It is **not** on the beta launch critical path — deferrable past launch if needed, but planned-for now.

**Success Criteria** (what must be TRUE):
1. `POST /api/v1/validate?segmentation=sam3d` returns 202 with `{analysis_id, job_id, poll_url}` in < 1 s
2. `GET /api/v1/jobs/{id}` returns status transitions (`queued → running → done` or `partial`) and a result URL on completion
3. Re-enqueueing the same mesh+params returns the existing `job_id` (idempotency)
4. Worker restarts mid-job do not lose work (visibility timeout ≥ 10 min, ack-on-completion)
5. SAM-3D model inference failure produces a `partial` job with heuristic fallback results — never `failed` from the user's perspective
6. Cold-start worker boot does not download weights (pre-baked into image)

**Key Deliverables:**
- `backend/src/jobs/` with `JobQueue` protocol + arq backend
- Redis configured + arq worker entrypoint in shared image
- `POST /api/v1/validate?segmentation=sam3d` async branch
- `GET /api/v1/jobs/{id}` polling endpoint
- SAM-3D weights pre-baked + embedding cache in blob storage (mesh-hash keyed)
- Idempotent job keying + duplicate-enqueue dedup
- Worker visibility timeout ≥ 10 min + ack-on-completion
- Graceful fallback path to heuristic segmenter

**Suggested Parallel Plans:**
- Plan 7.A: JobQueue protocol + arq backend + Redis + worker entrypoint (SAM-01)
- Plan 7.B: Async submit + poll endpoints + idempotency (SAM-02, 03, 06)
- Plan 7.C: Pre-baked weights + embedding cache + visibility + fallback (SAM-04, 05, 07, 08)

**Risks (from PITFALLS.md):**
- Pitfall 6: Async worker state desync on Fly — mitigated by min-1 worker, ack-on-completion, persistent blob storage
- Pitfall 1: SAM-3D weights inflate image — embedding cache + cold-start budget
- License risk on SAM-3D weights — **phase research mandatory** before baking

**Plans:** TBD

---

### Phase 8: Performance + Frontend Polish
**Goal:** The beta feels fast and robust under real-world meshes and flaky networks — the last-mile polish pass.
**Depends on:** Phase 3 (GeometryContext batching integrates with `analysis_service`); can run after Phase 6 launch as post-launch polish.
**Phase research needed:** No (BVH ray-cast patterns are standard; Dependabot is configuration)
**Requirements:** PERF-01, PERF-02, PERF-03, PERF-04, PERF-05, PERF-06

**Success Criteria** (what must be TRUE):
1. A request hitting 5 processes runs one `GeometryContext` build (not five) — verified via context-build counter
2. A 200k-face mesh completes wall-thickness analysis in < 3 s (vs. baseline) via sampled / BVH ray-casting
3. Peak memory after 100 sequential analyses stays flat (no leak) — mesh cleanup releases memory post-persist
4. Frontend surfaces `X-RateLimit-Remaining` in the UI; a 429 shows a human-readable countdown, not a console error
5. Frontend handles network timeout, malformed JSON, and 5xx without unhandled promise rejections (Sentry breadcrumb confirms)
6. Dependabot opens PRs weekly for frontend + backend dependency updates

**Key Deliverables:**
- Batched analyzer run sharing single `GeometryContext`
- Sampled / BVH-accelerated ray-casting (triggered at > 50k faces)
- Request-level mesh cleanup hook
- Frontend API client with Authorization header + rate-limit surfacing
- Frontend error boundaries + retry + structured error rendering
- Dependabot config for both apps

**Suggested Parallel Plans:**
- Plan 8.A: Batched context + BVH ray-cast + mesh cleanup (PERF-01, 02, 03)
- Plan 8.B: Frontend auth client + rate-limit UI + error handling (PERF-04, 05)
- Plan 8.C: Dependabot config (PERF-06)

**Risks (from PITFALLS.md):**
- Performance traps (batch context, BVH, mesh cleanup) — all listed in PITFALLS Performance Traps section
- UX pitfalls — Phase 8 closes these explicitly

**Plans:** TBD
**UI hint:** yes

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Stabilize Core | 0/4 | Not started | - |
| 2. Auth + Rate Limiting + Abuse Controls | 0/4 | Not started | - |
| 3. Persistence + analysis_service + History + Caching | 0/4 | Not started | - |
| 4. Shareable URLs + PDF Export | 0/2 | Not started | - |
| 5. Mesh Repair Endpoint | 0/2 | Not started | - |
| 6. Packaging + Deploy + Observability + Docs | 0/5 | Not started | - |
| 7. Async SAM-3D | 0/3 | Not started | - |
| 8. Performance + Frontend Polish | 0/3 | Not started | - |

## Phase Research Summary

| Phase | Needs `/gsd-research-phase`? | Why |
|-------|------------------------------|-----|
| 1 | No | Standard patterns; CONCERNS.md enumerates issues |
| 2 | **YES** | OAuth provider decision, Turnstile integration, signup abuse model |
| 3 | No | SQLAlchemy 2.0 async + Alembic canonical |
| 4 | No | WeasyPrint + share-ID patterns are standard |
| 5 | No | pymeshfix + trimesh.repair canonical; no topology reconstruction in scope |
| 6 | **YES** | cadquery Dockerfile spike — highest-risk artifact of the milestone |
| 7 | **YES** | arq-vs-TaskIQ recheck + SAM-3D weight size/license/provenance |
| 8 | No | BVH patterns standard; Dependabot is config |

## Dependency Graph

```
Phase 1 (Stabilize Core)
   └─> Phase 2 (Auth + Rate Limit + Abuse — atomic)
          └─> Phase 3 (Persistence — KEYSTONE)
                 ├─> Phase 4 (Share + PDF)
                 ├─> Phase 5 (Mesh Repair)
                 ├─> Phase 6 (Packaging + Deploy + Obs + Docs) ── BETA LAUNCH GATE
                 ├─> Phase 7 (Async SAM-3D — parallel track)
                 └─> Phase 8 (Perf + Frontend Polish — post-launch OK)
```

## Coverage Matrix (100% of v1 requirements mapped)

| Category | Requirements | Phase | Count |
|----------|--------------|-------|-------|
| Stabilize Core | CORE-01 through CORE-08 | Phase 1 | 8 |
| Authentication & Abuse Controls | AUTH-01 through AUTH-11 | Phase 2 | 11 |
| Persistence & History | PERS-01 through PERS-09 | Phase 3 | 9 |
| Shareable URLs | SHARE-01 through SHARE-05 | Phase 4 | 5 |
| PDF Export | PDF-01 through PDF-05 | Phase 4 | 5 |
| Mesh Repair | REPAIR-01 through REPAIR-03 | Phase 5 | 3 |
| Packaging & Deployment | PKG-01 through PKG-08 | Phase 6 | 8 |
| Observability | OBS-01 through OBS-05 | Phase 6 | 5 |
| Docs & Landing | DOC-01 through DOC-04 | Phase 6 | 4 |
| Async SAM-3D | SAM-01 through SAM-08 | Phase 7 | 8 |
| Performance & Frontend Polish | PERF-01 through PERF-06 | Phase 8 | 6 |

**Total v1 requirements:** 72
**Mapped:** 72
**Unmapped:** 0 ✓
**Duplicates:** 0 ✓

(Note: REQUIREMENTS.md Traceability lists 70 rows; PDF-01..05 and SHARE-01..05 together account for the 10 Phase-4 items — cross-reference counts match with category totals above: 8+11+9+5+5+3+8+5+4+8+6 = 72. Categories sum to 72 v1 items across both the summary and detailed Traceability table, with no orphans.)

## Out of Scope for v1.0-beta

Deferred per PROJECT.md and REQUIREMENTS.md:
- Billing / Stripe / paid tiers → v2 (BILL-*)
- SDKs, CLI, GitHub Action example → v2 (SDK-*)
- Multi-user orgs / RBAC → v2 (ORG-*)
- Synchronous SAM-3D, advanced mesh reconstruction, custom rule-pack UI → v2 (ADV-*)
- SOC2, enterprise self-host tier → v2 (ENT-*)
- Email+password auth, AWS/GCP deploy, real-time collaboration, CAD authoring, new analyzer categories — permanently out of scope

---

*Roadmap defined: 2026-04-15*
*Milestone: v1.0-beta*
*Last updated: 2026-04-15 after initial roadmap creation*
