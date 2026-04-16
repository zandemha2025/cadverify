# Phase 8: Performance + Frontend Polish - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area -- see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 8` if desired)

<domain>
## Phase Boundary

This phase makes the beta feel fast and robust under real-world meshes and flaky networks -- the last-mile polish pass. It covers three backend performance optimizations (batched GeometryContext verification, BVH/sampled ray-casting, mesh cleanup) and three frontend hardening items (auth header + rate-limit surfacing, error handling, dependency hygiene).

Deliverables:
1. Verified single-`GeometryContext` build per multi-process request (PERF-01).
2. Sampled / BVH-accelerated ray-casting for meshes >50k faces (PERF-02).
3. Request-level mesh cleanup releasing memory after analysis persists (PERF-03).
4. Frontend API client attaches `Authorization` header, surfaces rate-limit headers in UI (PERF-04).
5. Frontend handles network timeout, malformed response, and server 5xx gracefully (PERF-05).
6. Dependabot configured for weekly dependency updates (PERF-06).

**Explicitly out of scope for this phase:**
- Global (cross-user) dedup cache optimization (backlog; per-user cache is sufficient for beta)
- Frontend 3D viewer performance (Three.js rendering optimizations)
- New analyzer categories or scoring changes
- Bundle splitting / code splitting (Next.js defaults are sufficient for beta)
- Accessibility audit (deferred to post-beta)
- Upload progress UX (current fetch-based upload is adequate for beta file sizes)

</domain>

<decisions>
## Implementation Decisions

### GeometryContext Batching Verification (PERF-01)

- **D-01:** The current `analysis_service.py` `_run_analysis_sync()` already builds a single `GeometryContext` (line 250: `ctx = GeometryContext.build(mesh, geometry)`) and passes it to all process analyzers in the loop. **No architectural change needed.** The deliverable is a test assertion that verifies exactly one `GeometryContext.build()` call per multi-process request (via monkeypatch counter).
  - **Rationale:** Code inspection confirms the batching is already correct. The ROADMAP success criterion says "verified via context-build counter" -- that's a test, not a code change. Avoids unnecessary refactoring of working code.

### BVH / Sampled Ray-Casting (PERF-02)

- **D-02:** For meshes with >50k faces, use **face sampling** in `_compute_wall_thickness()`: compute stride as `max(1, n_faces // 5000)`, fire rays only for sampled faces, then broadcast the nearest-neighbor thickness to unsampled faces using a KDTree on face centroids. Below 50k faces, keep the existing full ray-cast.
  - **Rationale:** CONCERNS.md Performance Bottlenecks section says "Sample faces instead of checking all (e.g., every 10th face for wall estimation)" as improvement path #1. Face sampling is the simplest approach, avoids introducing a new BVH library dependency, and the 5000-face sample target keeps wall-thickness analysis under 1s for 200k+ face meshes (vs. current 2-5s for 50k faces). KDTree from scipy (already a dependency) handles nearest-neighbor propagation efficiently.
- **D-03:** The 50k-face threshold is configurable via an environment variable `RAYCAST_SAMPLE_THRESHOLD` (default 50000) so it can be tuned in production without a code change.
  - **Rationale:** Different deployment environments may have different CPU profiles. An env var keeps the threshold adjustable without redeployment.

### Request-Level Mesh Cleanup (PERF-03)

- **D-04:** After `_run_analysis_sync()` completes and the result is persisted, explicitly delete the mesh, GeometryContext, and numpy arrays via `del` statements in a `finally` block within `run_analysis()`. Follow with `gc.collect()` only in production (controlled by `FORCE_GC_AFTER_ANALYSIS=true` env var, default false -- gc.collect() is expensive and usually unnecessary with proper del).
  - **Rationale:** ROADMAP success criterion says "Peak memory after 100 sequential analyses stays flat (no leak)." Explicit `del` breaks reference cycles (mesh holds trimesh internals that reference numpy arrays). gc.collect() is the nuclear option and should be opt-in; most memory will be reclaimed by CPython refcount on `del`. The env var lets operators enable forced GC if monitoring reveals leaks.
- **D-05:** Add a `@contextlib.contextmanager` wrapper (`analysis_context()`) in analysis_service that yields the parsed mesh and cleans up on exit. This replaces the current inline pattern where mesh lives in local scope until function return.
  - **Rationale:** Context manager pattern ensures cleanup even on exceptions. Matches the STEP parser cleanup pattern from Phase 1 (CORE-01).

### Frontend Auth Client + Rate-Limit Surfacing (PERF-04)

- **D-06:** Centralize all API calls through a single `apiClient` wrapper in `frontend/src/lib/api.ts` that automatically attaches the `Authorization: Bearer` header from the session token. Currently, `validateFile()`, `validateQuick()`, `getProcesses()`, etc. use raw `fetch()` with no auth header.
  - **Rationale:** Phase 2 implemented auth on the backend, but the frontend API client was not updated to send auth headers on every request. A centralized wrapper avoids duplicating header logic across 8+ API functions.
- **D-07:** The `apiClient` wrapper reads `X-RateLimit-Remaining`, `X-RateLimit-Limit`, and `X-RateLimit-Reset` from every response and stores them in a lightweight Zustand store (or React context if Zustand is not already a dependency). The `QuotaDisplay` component (already exists at `frontend/src/components/QuotaDisplay.tsx`) reads from this store to show an inline quota bar.
  - **Rationale:** Rate-limit headers are already emitted by the slowapi middleware from Phase 2. Reading them from every response is zero-cost. QuotaDisplay already exists -- it just needs a real data source instead of mock/placeholder data.
- **D-08:** On 429 response, show a **toast notification** with a human-readable countdown ("Rate limit exceeded. Try again in {seconds}s") parsed from `Retry-After` header. Do not retry automatically on 429.
  - **Rationale:** ROADMAP success criterion says "a 429 shows a human-readable countdown, not a console error." No auto-retry on 429 because rate limits are intentional -- retrying would just hit the limit again.

### Frontend Error Handling (PERF-05)

- **D-09:** Add a **React error boundary** at the route/layout level (Next.js `error.tsx` convention) that catches unhandled rendering errors and shows a structured fallback UI with "Something went wrong" + retry button + Sentry event ID for support.
  - **Rationale:** No error boundary exists in the frontend (confirmed by codebase search). Next.js error.tsx is the framework-standard approach and integrates with the Sentry setup from Phase 6.
- **D-10:** For API fetch errors, implement a **structured error handler** in the `apiClient` wrapper: (a) network timeout -> show "Connection timed out. Check your network." with retry; (b) malformed JSON -> show "Unexpected server response" with Sentry report; (c) 5xx -> show "Server error. We've been notified." with exponential backoff retry (max 2 retries, 1s/2s delays). No retry on 4xx.
  - **Rationale:** ROADMAP success criterion says "Frontend handles network timeout, malformed JSON, and 5xx without unhandled promise rejections." The three-tier approach (timeout/malformed/5xx) covers all cases. Max 2 retries with backoff is standard -- more retries would annoy users. No retry on 4xx because those are client errors (bad input, auth failure).
- **D-11:** All error toasts and fallback UIs use the `{code, message, doc_url}` structured error format from Phase 6 (DOC-02) when available. Unknown errors fall back to generic messages.
  - **Rationale:** Phase 6 standardized error responses with stable codes and doc_url links. The frontend should surface these to users rather than showing raw HTTP status codes.

### Dependabot Configuration (PERF-06)

- **D-12:** Create `.github/dependabot.yml` with two package ecosystems: `pip` (directory: `/backend`, schedule: weekly, Monday) and `npm` (directory: `/frontend`, schedule: weekly, Monday). Limit open PRs to 5 per ecosystem to avoid PR flood.
  - **Rationale:** Standard Dependabot config. Weekly cadence is sufficient for a beta -- daily would be noisy. Monday schedule gives the week to review. 5 PR limit prevents dashboard clutter.

### Claude's Discretion
- Exact toast component library choice (sonner, react-hot-toast, or hand-rolled)
- KDTree parameters for nearest-neighbor thickness propagation (leaf_size, metric)
- Error boundary visual design (copy, layout, illustration)
- Specific exponential backoff timing (1s/2s is a guideline, not a constraint)
- Whether to use Zustand or React context for rate-limit state (depends on existing dependency tree)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Backend performance
- `.planning/codebase/CONCERNS.md` -- Performance Bottlenecks section: ray-casting O(N log N), process analyzer fallthrough loop, improvement paths
- `backend/src/analysis/context.py` -- GeometryContext.build() and _compute_wall_thickness() are the primary optimization targets
- `backend/src/services/analysis_service.py` -- run_analysis() pipeline: hash -> cache -> parse -> analyze -> persist. Cleanup hook goes here.

### Frontend
- `frontend/src/lib/api.ts` -- All API client functions; auth header and error handling wraps go here
- `frontend/src/components/QuotaDisplay.tsx` -- Existing quota display component; needs real rate-limit data source
- `frontend/src/components/AnalysisHistoryTable.tsx` -- References rate-limit patterns

### Requirements
- `.planning/REQUIREMENTS.md` -- PERF-01 through PERF-06 definitions
- `.planning/ROADMAP.md` -- Phase 8 success criteria and key deliverables

### Prior phase decisions
- `.planning/phases/03-persistence-analysis-service-history-caching/03-CONTEXT.md` -- D-07 (analysis_service architecture), D-13 (per-user cache), D-14 (Postgres-only cache)
- `.planning/phases/02-auth-rate-limiting-abuse-controls/02-CONTEXT.md` -- Auth + slowapi rate limiting implementation
- `.planning/phases/06-packaging-deploy-observability-docs/06-CONTEXT.md` -- Sentry integration, structured error format, DOC-02

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `GeometryContext.build()` in `backend/src/analysis/context.py` -- already builds once per request; optimization is in `_compute_wall_thickness()` internal to the build
- `QuotaDisplay` component in `frontend/src/components/QuotaDisplay.tsx` -- exists, needs wiring to real rate-limit data
- `apiClient` pattern -- does not exist yet; currently 8+ raw `fetch()` calls in `api.ts` need centralization
- `scipy.spatial.KDTree` -- scipy is already a backend dependency; no new dependency for nearest-neighbor propagation

### Established Patterns
- `analysis_service.py` uses `asyncio.wait_for` + `loop.run_in_executor` for sync pipeline execution -- cleanup hooks must work within this pattern
- Frontend uses raw `fetch()` without a wrapper -- Phase 8 introduces the centralized `apiClient` pattern
- Backend env vars for configuration (e.g., `ANALYSIS_TIMEOUT_SEC`, `MAX_UPLOAD_MB`) -- new thresholds follow this pattern

### Integration Points
- `_compute_wall_thickness()` in `context.py:150+` -- sampling logic inserted here
- `run_analysis()` in `analysis_service.py:168+` -- cleanup hook wraps the pipeline execution
- `frontend/src/lib/api.ts` -- all API functions refactored to use centralized client
- `.github/dependabot.yml` -- new file at repo root

</code_context>

<specifics>
## Specific Ideas

No specific requirements -- open to standard approaches. Key performance targets from ROADMAP success criteria:
- 5-process request builds one GeometryContext (not five) -- verified via counter
- 200k-face mesh completes wall-thickness in <3s via sampling
- Memory stays flat after 100 sequential analyses
- 429 shows human-readable countdown in frontend
- No unhandled promise rejections (Sentry confirms)

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 08-performance-frontend-polish*
*Context gathered: 2026-04-15*
