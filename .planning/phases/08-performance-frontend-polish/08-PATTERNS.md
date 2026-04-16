# Phase 8: Performance + Frontend Polish — Pattern Map

**Generated:** 2026-04-15

## Files to Create/Modify

### Backend Files

| File | Role | Closest Analog | Data Flow |
|------|------|----------------|-----------|
| `backend/src/analysis/context.py` | MODIFY — add face sampling + KDTree propagation to `_compute_wall_thickness()` | Self (existing ray-cast logic at lines 150-203) | mesh -> sampled centroids -> ray cast -> KDTree -> full thickness array |
| `backend/src/services/analysis_service.py` | MODIFY — add `analysis_context()` contextmanager for mesh cleanup | `backend/src/services/repair_service.py` (timeout pattern) | mesh lifecycle: parse -> analyze -> persist -> cleanup |
| `backend/tests/test_geometry_context_batching.py` | CREATE — test that verifies single GeometryContext.build per multi-process request | `backend/tests/test_analysis_service.py` (monkeypatch patterns) | test -> monkeypatch counter -> run_analysis(5 procs) -> assert count==1 |
| `backend/tests/test_wall_thickness_sampling.py` | CREATE — performance + correctness tests for sampled ray-cast | `backend/tests/test_large_mesh.py` (large mesh test patterns) | test -> generate mesh -> timed ray-cast -> assert <3s + accuracy |
| `.github/dependabot.yml` | CREATE — Dependabot configuration | Standard GitHub template | GitHub -> weekly PR -> pip + npm |

### Frontend Files

| File | Role | Closest Analog | Data Flow |
|------|------|----------------|-----------|
| `frontend/src/lib/api.ts` | MODIFY — refactor all functions to use centralized apiClient wrapper | Self (existing `authHeaders()` + `extractRateLimits()` at lines 223-257) | apiClient.fetch -> auth header -> response -> extract rate limits -> structured errors |
| `frontend/src/app/error.tsx` | CREATE — root error boundary | Next.js 16 `error.tsx` convention (see `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md`) | rendering error -> Error component -> Sentry.captureException -> retry button |
| `frontend/src/app/(dashboard)/error.tsx` | CREATE — dashboard error boundary | Same convention as root error.tsx | dashboard error -> contextual fallback -> retry |
| `frontend/src/app/layout.tsx` | MODIFY — add `<Toaster />` for sonner | Self (existing root layout) | layout -> Toaster component -> toast notifications |

---

## Pattern Excerpts

### 1. Env Var Configuration Pattern (backend)

**Source:** `backend/src/api/routes.py:56-58`
```python
def _analysis_timeout_sec() -> float:
    """Read ANALYSIS_TIMEOUT_SEC lazily so tests can override via monkeypatch."""
    with contextlib.suppress(Exception):
        return max(0.1, float(os.getenv("ANALYSIS_TIMEOUT_SEC", "60")))
    return 60.0
```

**Reuse for:** `RAYCAST_SAMPLE_THRESHOLD` (default 50000) and `FORCE_GC_AFTER_ANALYSIS` (default "false"). Same lazy-read + monkeypatchable pattern.

### 2. Auth Headers Pattern (frontend)

**Source:** `frontend/src/lib/api.ts:223-227`
```typescript
function authHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const key = localStorage.getItem("cadverify_api_key");
  return key ? { Authorization: `Bearer ${key}` } : {};
}
```

**Reuse for:** The new `apiClient` wraps this into every request. Already exists — centralize into the wrapper and replace all direct `authHeaders()` calls.

### 3. Rate-Limit Extraction Pattern (frontend)

**Source:** `frontend/src/lib/api.ts:229-237`
```typescript
function extractRateLimits(headers: Headers): RateLimits | undefined {
  const remaining = headers.get("X-RateLimit-Remaining");
  const limit = headers.get("X-RateLimit-Limit");
  if (!remaining || !limit) return undefined;
  return {
    remaining: parseInt(remaining, 10),
    limit: parseInt(limit, 10),
    reset: parseInt(headers.get("X-RateLimit-Reset") || "0", 10),
  };
}
```

**Reuse for:** Already correct — move into apiClient internals and apply to ALL responses, not just `fetchAnalyses`.

### 4. Error Throwing Pattern (frontend)

**Source:** `frontend/src/lib/api.ts:131-134`
```typescript
if (!res.ok) {
  const err = await res.json().catch(() => ({ detail: res.statusText }));
  throw new Error(err.detail || "Validation failed");
}
```

**Replace with:** Structured error handler in apiClient that differentiates timeout/malformed/5xx/429/4xx.

### 5. Next.js 16 Error Boundary Pattern

**Source:** `frontend/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md`
```tsx
'use client'
export default function Error({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string }
  unstable_retry: () => void
}) { ... }
```

**Key:** Next.js 16 uses `unstable_retry` not `reset`. Must be `'use client'`. `error.digest` is the server-side hash.

### 6. Sentry Integration Pattern

**Source:** `@sentry/nextjs ^10.49.0` is installed. No existing error boundary wiring.

**Reuse for:** `Sentry.captureException(error)` in error.tsx `useEffect`.

---

## PATTERN MAPPING COMPLETE
