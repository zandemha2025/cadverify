# Phase 8: Performance + Frontend Polish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 08-performance-frontend-polish
**Mode:** --auto (all decisions auto-selected)
**Areas discussed:** GeometryContext batching, BVH ray-cast sampling, Mesh cleanup, Frontend error handling, Rate-limit UX, Dependabot config

---

## GeometryContext Batching (PERF-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Verify single-build + add test assertion | Code already builds once; add monkeypatch counter test | :heavy_check_mark: |
| Refactor to explicit batch API | Create GeometryContext.build_batch() method | |
| Add caching layer in context.py | LRU cache on build() keyed by mesh hash | |

**User's choice:** [auto] Verify single-build + add test assertion (recommended default)
**Notes:** Code inspection of analysis_service.py confirms GeometryContext.build() is called once at line 250, then ctx is passed to all analyzers in the loop. No refactoring needed -- just test verification.

---

## BVH / Sampled Ray-Casting (PERF-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Face sampling with KDTree propagation | Stride = max(1, n//5000); propagate via scipy KDTree | :heavy_check_mark: |
| trimesh BVH accelerator | Use trimesh's internal ray acceleration | |
| Parallel ray-casting via ProcessPool | Multi-threaded ray cast for all faces | |

**User's choice:** [auto] Face sampling with KDTree propagation (recommended default)
**Notes:** CONCERNS.md recommends sampling as improvement path #1. KDTree from scipy (already a dependency) handles propagation. 5000-face sample target keeps analysis under 1s for 200k+ meshes. Threshold configurable via RAYCAST_SAMPLE_THRESHOLD env var.

---

## Mesh Cleanup (PERF-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Context manager + explicit del + opt-in gc | analysis_context() CM with del in finally; gc.collect() via env var | :heavy_check_mark: |
| WeakRef-based cleanup | Use weakref.finalize() on mesh objects | |
| No explicit cleanup | Rely on CPython refcount and scope exit | |

**User's choice:** [auto] Context manager + explicit del + opt-in gc (recommended default)
**Notes:** Context manager ensures cleanup even on exceptions. gc.collect() is expensive so opt-in via FORCE_GC_AFTER_ANALYSIS env var. Matches Phase 1 STEP parser cleanup pattern.

---

## Frontend Error Handling (PERF-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Error boundary + structured handler + backoff retry | Route-level error.tsx + 3-tier fetch error handling + max 2 retries on 5xx | :heavy_check_mark: |
| Global error handler only | window.onerror + unhandledrejection listeners | |
| Per-component try/catch | Each component handles its own errors | |

**User's choice:** [auto] Error boundary + structured handler + backoff retry (recommended default)
**Notes:** No ErrorBoundary exists yet (confirmed by grep). Next.js error.tsx is framework-standard. Three-tier handler covers timeout/malformed/5xx. No retry on 4xx (client errors). Structured error format from Phase 6 DOC-02 surfaced to users.

---

## Rate-Limit UX (PERF-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Inline quota bar + 429 toast with countdown | Read X-RateLimit-* headers; QuotaDisplay reads from store; toast on 429 | :heavy_check_mark: |
| Banner notification only | Show persistent banner when approaching limit | |
| Console warning only | Log rate-limit info to console | |

**User's choice:** [auto] Inline quota bar + 429 toast with countdown (recommended default)
**Notes:** QuotaDisplay component already exists. Rate-limit headers already emitted by slowapi from Phase 2. Zero-cost to read from responses. No auto-retry on 429 (intentional limit).

---

## Dependabot Config (PERF-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Weekly pip + npm, 5 PR limit | .github/dependabot.yml with Monday schedule | :heavy_check_mark: |
| Daily updates | More frequent but noisier | |
| Monthly updates | Less noise but stale deps longer | |

**User's choice:** [auto] Weekly pip + npm, 5 PR limit (recommended default)
**Notes:** Standard config. Weekly is sufficient for beta. 5 PR limit prevents dashboard clutter.

---

## Claude's Discretion

- Toast component library choice (sonner, react-hot-toast, or hand-rolled)
- KDTree parameters for nearest-neighbor propagation
- Error boundary visual design
- Exponential backoff timing details
- Zustand vs React context for rate-limit state

## Deferred Ideas

None.
