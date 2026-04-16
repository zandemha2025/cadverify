# Phase 8: Performance + Frontend Polish — Research

**Researched:** 2026-04-15
**Status:** Complete

## 1. Face Sampling + KDTree Propagation for Wall Thickness

### Current State
- `_compute_wall_thickness()` in `context.py:150-203` fires one ray per face via `mesh.ray.intersects_location(multiple_hits=True)`.
- For 50k faces: 2-5s. For 200k faces: estimated 8-20s (O(N log N) in trimesh's embree/pyembree BVH).
- CONCERNS.md lists this as the #1 performance bottleneck.

### Approach: Stride-Based Sampling + KDTree Nearest-Neighbor
1. **Sample selection:** `stride = max(1, n_faces // 5000)`. Sample indices = `np.arange(0, n, stride)`. This yields ~5000 sampled faces regardless of mesh size.
2. **Ray-cast only sampled faces:** Fire rays from `centroids[sample_idx]` with `directions = -normals[sample_idx]`.
3. **KDTree propagation:** Build `scipy.spatial.KDTree(centroids)`, then for unsampled faces, query `tree.query(centroids[unsampled], k=1)` to find the nearest sampled face. Assign that face's thickness.
4. **Threshold:** Apply only when `n_faces > RAYCAST_SAMPLE_THRESHOLD` (env var, default 50000). Below threshold, keep existing full ray-cast.

### Key Parameters
- `scipy.spatial.KDTree` — already a transitive dependency (scipy is in requirements). Default `leafsize=10` is fine for 200k centroids.
- KDTree build: O(N log N), ~50ms for 200k points. Query: O(N log N), ~100ms for 200k queries with k=1.
- Total expected time for 200k faces: ~0.5s sampling + ~0.15s KDTree = ~0.65s vs. ~15s full ray-cast.

### Risks
- Sampled thickness is approximate — thin-wall regions between sampled faces may be missed. Mitigated by the 5000-face sample target (sufficient density for wall-thickness estimation, which is a global metric not a per-face precision requirement).
- KDTree propagation assumes wall thickness varies smoothly across adjacent faces — true for manufactured parts, may be less accurate for artistic/organic meshes (out of scope for DFM).

### Validation Architecture
- **Correctness test:** Run full ray-cast and sampled ray-cast on a known geometry (cube, cylinder). Assert max deviation < 10% for >95% of faces.
- **Performance test:** 200k-face mesh completes `_compute_wall_thickness` in < 3s (ROADMAP SC-2).
- **Threshold test:** Mesh with 49999 faces uses full ray-cast; mesh with 50001 faces uses sampling.

---

## 2. Request-Level Mesh Cleanup

### Current State
- `run_analysis()` in `analysis_service.py:169-367` runs the sync pipeline in `run_in_executor`, builds `GeometryContext` (holds mesh + numpy arrays), and returns `result_dict`. The mesh and ctx objects live in local scope until the executor function returns — CPython refcount *should* free them, but trimesh internals hold circular references (mesh.ray caches, face_adjacency caches).
- No explicit cleanup exists.

### Approach: Context Manager Pattern
1. Create `analysis_context()` contextmanager in `analysis_service.py` that:
   - Yields the parsed mesh
   - In `finally`: `del mesh`, `del ctx`, explicit `del` on large numpy arrays
   - Optionally calls `gc.collect()` when `FORCE_GC_AFTER_ANALYSIS=true` (env var, default false)
2. Wrap the sync pipeline in `_run_analysis_sync()` inside this context manager.
3. The mesh reference must not escape the context manager — `result_dict` (a plain dict) is the only output.

### Trimesh Memory Internals
- `trimesh.Trimesh` caches: `_cache` dict holds ray intersection trees (embree accelerators), face adjacency, convex hull. Calling `mesh._cache.clear()` before `del mesh` helps break cycles.
- `mesh.ray` holds a reference to the pyembree `IntersectorClass` which holds a C-level BVH tree. This is the largest memory consumer for dense meshes (~40 bytes/face for the BVH).
- Explicit `mesh._cache.clear()` + `del mesh` is sufficient to free memory in CPython without `gc.collect()`.

### Validation
- Run 100 sequential analyses in a test, measure peak RSS. Assert delta < 50MB (allows for Python allocator fragmentation but catches leaks).

---

## 3. GeometryContext Batching Verification

### Current State
- `_run_analysis_sync()` in `analysis_service.py:248-273` already builds ONE `GeometryContext` and loops over all target processes. This is correct — no architectural change needed.
- The deliverable is a **test assertion** that verifies exactly one `GeometryContext.build()` call per multi-process request.

### Approach
- Monkeypatch `GeometryContext.build` with a counter in the test.
- Call `run_analysis()` with 5 processes.
- Assert counter == 1.

---

## 4. Next.js 16 Error Boundaries

### Current State
- **No `error.tsx` exists** anywhere in `frontend/src/app/`.
- Next.js 16.2.3 is installed. The error.tsx convention uses `unstable_retry` (not `reset` from older Next.js versions).
- `@sentry/nextjs ^10.49.0` is already installed.

### Next.js 16 error.tsx API
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

Key points:
- Must be `'use client'` component.
- `error.digest` is the server-side error hash — use as Sentry event ID proxy for support.
- `unstable_retry()` re-fetches and re-renders the segment.
- Place at `app/error.tsx` for root-level, `app/(dashboard)/error.tsx` for dashboard-level.

### Error Boundary Strategy
1. **Root `app/error.tsx`:** Catches all unhandled rendering errors. Shows "Something went wrong" + retry + error digest for support.
2. **Dashboard `app/(dashboard)/error.tsx`:** Catches dashboard-specific errors. Shows contextual message + retry.
3. **Sentry integration:** In the `useEffect`, call `Sentry.captureException(error)` with the digest as extra context.

---

## 5. apiClient Centralization + Rate-Limit UX

### Current State
- `frontend/src/lib/api.ts` has 10+ exported functions using raw `fetch()`.
- Some functions (post-Phase 3: `fetchAnalyses`, `shareAnalysis`, etc.) already use `authHeaders()` helper and `extractRateLimits()`.
- Earlier functions (`validateFile`, `validateQuick`, `getProcesses`, `getMaterials`, `getMachines`, `getRulePacks`) do NOT attach auth headers.
- No toast library installed. No zustand.
- `QuotaDisplay.tsx` exists and accepts `RateLimits` prop — currently only wired from `fetchAnalyses` response.

### Approach
1. **`apiClient` wrapper:** Create a `createApiClient()` function that wraps `fetch` with:
   - Auto-attach `Authorization: Bearer` from `localStorage.getItem("cadverify_api_key")`
   - Extract rate-limit headers from every response
   - Store rate limits in a module-level variable (simple closure pattern — no zustand needed since there's no existing state management library)
   - Structured error handling: timeout -> specific message; malformed JSON -> Sentry report; 5xx -> exponential backoff retry (max 2, 1s/2s); 429 -> toast with countdown; 4xx -> throw with structured error
2. **Toast library:** Install `sonner` (lightweight, 3KB, works with React 19, no provider wrapper needed — just `<Toaster />` in root layout). Used only for 429 countdown and 5xx notifications.
3. **Refactor all API functions** to use `apiClient.fetch()` instead of raw `fetch()`.
4. **Wire QuotaDisplay** to read from the shared rate-limit state (exported getter function).

### 429 Handling
- Parse `Retry-After` header (seconds). Show toast: "Rate limit exceeded. Try again in {N}s."
- Do NOT auto-retry on 429 (intentional rate limit).

### 5xx Retry Strategy
- Max 2 retries with exponential backoff: 1s, 2s.
- Show toast on final failure: "Server error. We've been notified."
- Report to Sentry on final failure.

---

## 6. Dependabot Configuration

### Current State
- No `.github/dependabot.yml` exists.
- Backend uses pip (requirements files in `backend/`).
- Frontend uses npm (package.json in `frontend/`).

### Configuration
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/backend"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
```

Straightforward — no research risk.

---

## RESEARCH COMPLETE
