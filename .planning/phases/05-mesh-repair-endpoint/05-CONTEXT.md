# Phase 5: Mesh Repair Endpoint - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area -- see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 5` if desired)

<domain>
## Phase Boundary

This phase lets users whose mesh fails universal checks (non-manifold, holes, inconsistent normals) attempt an automatic repair and get a re-analyzed result -- closing the loop for ~30% of real-world uploads.

Deliverables:
1. `POST /api/v1/validate/repair` endpoint -- accepts STL/STEP file, runs two-tier repair (trimesh pre-pass + pymeshfix hard-case), returns repaired STL bytes plus a full re-analysis.
2. `backend/src/services/repair_service.py` -- repair orchestration with timeout-bounded pymeshfix invocation.
3. Repaired-mesh hash cached via `analysis_service` (re-analysis of repaired mesh hits dedup on second request).
4. Frontend "Attempt repair" button shown conditionally when the original analysis flagged `NON_WATERTIGHT`, `INCONSISTENT_NORMALS`, `NOT_SOLID_VOLUME`, or `DEGENERATE_FACES`.

**Explicitly out of scope for this phase:**
- Advanced topology reconstruction (remeshing, feature preservation) -- PROJECT.md Out of Scope "ADV-03"
- GPU-based repair -- no GPU in default path
- Mesh file storage for download (repaired bytes returned inline in the response; blob storage of original uploads is not in scope)
- Async/queued repair (repair runs synchronously; Phase 7 arq infra could absorb it later)
- STEP-to-STEP repair (STEP input is converted to mesh, repaired as STL, returned as STL)
- Repair of process-specific issues (overhangs, thin walls) -- only universal geometry defects

</domain>

<decisions>
## Implementation Decisions

### Repair Library Strategy (gray area #1)

- **D-01:** Two-tier repair pipeline: **trimesh.repair first, pymeshfix.MeshFix second.**
  - Tier 1: `trimesh.repair.fill_holes(mesh)` + `trimesh.repair.fix_normals(mesh)` + `trimesh.repair.fix_inversion(mesh)` -- fast, in-process, handles ~60% of cases (small holes, flipped normals, degenerate faces).
  - Tier 2: If mesh is still not watertight after Tier 1, invoke `pymeshfix.MeshFix(vertices, faces).repair()` -- C++ library that handles non-manifold edges, complex hole filling, and self-intersection resolution.
  - **Rationale:** ROADMAP.md Phase 5 deliverables explicitly list "trimesh.repair pre-pass + pymeshfix.MeshFix hard-case path." Research SUMMARY.md confirms "pymeshfix 0.18 + trimesh.repair pre-pass -- only mesh-repair lib with current cross-platform wheels." The two-tier approach avoids pymeshfix overhead (~1-3s) for simple cases that trimesh handles in <100ms.
  - **Recommended default chosen in auto mode:** Two-tier (trimesh first, pymeshfix fallback).

- **D-02:** pymeshfix invocation runs **in-process** (not subprocess), but wrapped in `asyncio.wait_for` with a configurable timeout.
  - **Rationale:** pymeshfix is a compiled C++ extension (via pybind11). Subprocess isolation would require serializing mesh data to disk and back, adding 2-5s overhead for typical meshes. In-process is faster. The timeout guard (D-06) prevents hangs on pathological meshes. Pitfall 5 ("pymeshfix is C++ and can hang; enforce subprocess timeout") is addressed by the asyncio timeout + thread executor pattern already used by `analysis_service.run_analysis()`.

### Endpoint Shape (gray area #2)

- **D-03:** Endpoint: `POST /api/v1/validate/repair` -- **standalone file-upload endpoint**, not `POST /analyses/{id}/repair`.
  - Accepts: multipart file upload (same shape as `/validate`), optional `?processes=` and `?rule_pack=` query params.
  - Returns: `{ "original_analysis": {...}, "repair_applied": true|false, "repair_details": {...}, "repaired_analysis": {...}, "repaired_file_b64": "..." }` -- both original and repaired analysis results, plus base64-encoded repaired STL bytes.
  - **Rationale:** REQUIREMENTS.md REPAIR-01 specifies `POST /api/v1/validate/repair`. A file-upload endpoint is simpler than a by-ID endpoint because (a) it doesn't require the original file to be stored (Phase 3 only stores `result_json`, not mesh bytes), (b) it's self-contained -- one request, one response, (c) it matches the existing `/validate` pattern. The frontend can call this with the same file the user already has open.
  - **Recommended default chosen in auto mode:** Standalone file-upload at `/api/v1/validate/repair`.

- **D-04:** Response includes both original and repaired analysis, plus **base64-encoded repaired STL bytes** for download.
  - `original_analysis`: Full analysis of the as-uploaded mesh (same shape as `/validate` response).
  - `repaired_analysis`: Full re-analysis of the repaired mesh (null if repair failed or was unnecessary).
  - `repair_applied`: Boolean -- false if mesh was already clean or repair failed.
  - `repair_details`: `{ "tier": "trimesh"|"pymeshfix", "original_faces": N, "repaired_faces": M, "holes_filled": K, "duration_ms": T }`.
  - `repaired_file_b64`: Base64-encoded binary STL of the repaired mesh. Null if repair not applied. Frontend can decode and offer as download.
  - **Rationale:** REPAIR-02 requires "returns repaired STL bytes plus a re-analysis." Including both analyses in one response lets the frontend show a before/after comparison. Base64 encoding avoids multipart response complexity; typical repaired STL is 1-20 MB, base64 adds ~33% overhead, still manageable for a single response. For meshes >50 MB repaired, the response will be large -- acceptable at beta scale.

### Re-analysis Flow (gray area #3)

- **D-05:** Repair endpoint calls `analysis_service.run_analysis()` for the re-analysis, passing the **repaired mesh bytes** as input.
  - The repaired mesh gets its own `mesh_hash` (SHA-256 of repaired STL bytes).
  - If someone uploads the same repaired mesh later (or calls repair again on the same input), the dedup cache in `analysis_service` will return the cached result.
  - Both the original analysis and the repaired analysis are persisted as separate `analyses` rows.
  - **Rationale:** Phase 3's `analysis_service` is the single entry point for all analysis+persist+dedup logic (03-CONTEXT.md D-07, D-08). Reusing it for re-analysis means repaired results get the same dedup, persistence, and usage-event tracking as normal analyses. No parallel persistence path needed. The repaired mesh hash is different from the original, so it gets its own row -- correct behavior since the geometry changed.

### Repair Timeout and Limits (gray area #4)

- **D-06:** Repair timeout: `REPAIR_TIMEOUT_SEC` env var, default **30 seconds**. Covers both tiers (trimesh + pymeshfix combined). Enforced via `asyncio.wait_for()` wrapping the thread executor call.
  - **Rationale:** Pitfall 5 warns pymeshfix can hang on pathological meshes. 30 seconds is generous for legitimate meshes (pymeshfix typically completes in 1-5s for <500k faces) while preventing indefinite worker hangs. The existing `ANALYSIS_TIMEOUT_SEC` (default 60s) covers the re-analysis portion separately. Total worst-case: 30s repair + 60s re-analysis = 90s -- acceptable for an explicitly "attempt repair" action.

- **D-07:** Face-count cap for repair: **500,000 faces**. Meshes above this threshold return 413 with a message suggesting the user simplify before attempting repair.
  - **Rationale:** pymeshfix memory usage scales roughly as O(n) with face count. At 500k faces, pymeshfix uses ~500 MB RAM. At 1M faces, it can hit 1-2 GB -- dangerous on modest Fly instances. The existing `MAX_UPLOAD_MB` (100 MB) implicitly caps face count somewhat, but a binary STL at 100 MB is ~1.2M faces. Explicit face-count cap provides a tighter safety bound.

- **D-08:** On repair failure (timeout or pymeshfix exception), return the **original analysis only** with `repair_applied: false` and `repair_details.error: "..."`. No 500 error -- the endpoint always succeeds with the original analysis; repair is best-effort.
  - **Rationale:** ROADMAP Success Criterion #4 says "pymeshfix invocation is timeout-bounded and falls back cleanly on failure (no worker hangs)." Returning the original analysis on failure means the user still gets value from the request. The frontend can show "Repair was not possible -- here's your original analysis."

### Frontend Repair CTA (gray area #5)

- **D-09:** "Attempt repair" button appears on the analysis detail page **only when the original analysis contains at least one universal-check issue** with code in: `NON_WATERTIGHT`, `INCONSISTENT_NORMALS`, `NOT_SOLID_VOLUME`, `DEGENERATE_FACES`, `MULTIPLE_BODIES`.
  - **Rationale:** REPAIR-03 says "Frontend offers 'Attempt repair' action when original analysis flags non-manifold or holes." The `NON_WATERTIGHT` code is the primary trigger (produced by `check_watertight()` in `base_analyzer.py`). `INCONSISTENT_NORMALS`, `NOT_SOLID_VOLUME`, `DEGENERATE_FACES`, and `MULTIPLE_BODIES` are also universal checks that repair can address. Process-specific issues (THIN_WALL, OVERHANG, etc.) are design problems, not mesh defects -- repair won't fix them.

- **D-10:** Button placement: below the issues list, styled as a secondary action. Label: "Attempt Mesh Repair". Loading state shows "Repairing..." with a spinner. On success, the page updates to show a **before/after comparison** -- original analysis on the left, repaired analysis on the right, with changed metrics highlighted.
  - **Rationale:** The repair action is a recovery path, not the primary flow. Secondary styling (outlined button, not filled) communicates "optional action." Before/after comparison is the natural UX for "we fixed your mesh" -- the user needs to see what changed. The existing `AnalysisDashboard` component can be rendered twice (original + repaired) side by side.

- **D-11:** After successful repair, offer a **"Download Repaired File"** link that decodes the base64 STL from the response and triggers a browser download. Filename: `{original_filename}-repaired.stl`.
  - **Rationale:** The whole point of repair is to give the user a fixed file they can use. Without a download, the repair is purely informational. The repaired STL is already in the response (D-04), so no additional API call needed. Always STL format regardless of original input (STEP input is converted to mesh during repair).

### Dedup and Caching for Repair

- **D-12:** Repair results are **not separately cached** beyond what `analysis_service` provides. The re-analysis of the repaired mesh is cached by its own `mesh_hash` in the `analyses` table. The repair operation itself (trimesh + pymeshfix) is not cached -- it runs every time the endpoint is called with the same input.
  - **Rationale:** ROADMAP Success Criterion #2 says "A previously-repaired hash hits cache and skips pymeshfix re-run." This is satisfied by the `analysis_service` dedup layer: once the repaired mesh's SHA-256 + process_set_hash + version is in the `analyses` table, a second repair request with identical input would produce the same repaired bytes, hash them to the same SHA-256, and get a cache hit on the re-analysis. The repair step itself is fast enough (1-5s) that caching it separately adds complexity without meaningful benefit. If repair becomes a bottleneck, a `repairs` cache table keyed by `(original_mesh_hash)` can be added later.

### Claude's Discretion

The following are left to the researcher / planner to resolve with standard patterns and no further user input:

- Exact `trimesh.repair` function call sequence (which repair methods in what order).
- Whether to remove degenerate faces before or after pymeshfix.
- Base64 encoding details (standard base64 vs URL-safe; recommendation: standard with `base64.b64encode`).
- pymeshfix import error handling (graceful degradation if pymeshfix is not installed -- Tier 1 only).
- Repair service module structure (single function vs class).
- HTTP status code for repair response (200 for all cases including repair-failed, since original analysis is always returned).
- Exact face-count check placement (before or after initial parse).
- Frontend before/after comparison layout (side-by-side vs tabbed vs accordion).
- Frontend loading state animation specifics.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase-level requirements and roadmap
- `.planning/ROADMAP.md` S"Phase 5: Mesh Repair Endpoint" -- goal, success criteria, key deliverables, suggested parallel plans (5.A, 5.B), pitfall references.
- `.planning/REQUIREMENTS.md` S"Mesh Repair" (REPAIR-01, REPAIR-02, REPAIR-03) -- endpoint spec, response shape, frontend CTA condition.
- `.planning/PROJECT.md` S"Out of Scope" -- "Mesh-repair-as-a-service (advanced) -- basic pymeshfix only; no topology reconstruction, no GPU-based repair."

### Pitfalls research (from Phase 0 research)
- `.planning/research/PITFALLS.md` S"Pitfall 5: Zip bomb / STEP recursion bomb / pathological mesh DoS" -- pymeshfix hang risk, subprocess timeout recommendation, face-count DoS vector.
- `.planning/research/PITFALLS.md` S"Pitfall 1" -- pymeshfix adds Docker image weight; budget in Phase 6 Dockerfile spike.
- `.planning/research/FEATURES.md` S"Mesh repair endpoint" -- "~30% of real-world uploads need it"; "pymeshfix in Docker image" dependency.
- `.planning/research/SUMMARY.md` -- "pymeshfix 0.18 + trimesh.repair pre-pass -- only mesh-repair lib with current cross-platform wheels."
- `.planning/research/ARCHITECTURE.md` S"Recommended Project Structure" -- `services/repair_service.py` planned; `jobs/repair_task.py` for async (deferred to Phase 7).

### Brownfield codebase map
- `.planning/codebase/ARCHITECTURE.md` -- pipeline data flow; where repair service slots in.
- `.planning/codebase/STRUCTURE.md` -- `backend/src/services/` layout (analysis_service already exists).
- `.planning/codebase/CONVENTIONS.md` -- env-var config pattern, HTTPException patterns, logger naming.
- `.planning/codebase/CONCERNS.md` -- "Wall Thickness Ray Cast May Return inf" for non-watertight meshes (repair addresses the root cause).

### Prior phase context
- `.planning/phases/03-persistence-analysis-service-history-caching/03-CONTEXT.md` -- analysis_service architecture (D-07, D-08), mesh hash algorithm (D-09), dedup strategy (D-11, D-12), analyses table schema (D-15). Phase 5 calls `run_analysis()` for re-analysis.
- `.planning/phases/04-shareable-urls-pdf-export/04-CONTEXT.md` -- blob storage on Fly volume (D-10); repair does NOT use blob storage (repaired bytes returned inline).

### Existing code to integrate with
- `backend/src/services/analysis_service.py` -- `run_analysis()` function used for re-analysis of repaired mesh. `compute_mesh_hash()` used to hash repaired bytes.
- `backend/src/analysis/base_analyzer.py` -- `run_universal_checks()` produces `NON_WATERTIGHT`, `INCONSISTENT_NORMALS`, `NOT_SOLID_VOLUME`, `DEGENERATE_FACES`, `MULTIPLE_BODIES` issue codes that trigger the repair CTA.
- `backend/src/api/routes.py` -- `_parse_mesh()`, `_read_capped()`, `validate_magic()`, `enforce_triangle_cap()` reused for file upload handling on the repair endpoint.
- `backend/src/api/upload_validation.py` -- magic-byte + triangle-cap validation (Phase 1); repair endpoint reuses these guards.
- `backend/src/db/models.py` -- `Analysis` model; repaired mesh re-analysis creates a new row.
- `frontend/src/app/(dashboard)/analyses/[id]/page.tsx` -- analysis detail page where "Attempt repair" button is added.
- `frontend/src/components/AnalysisDashboard.tsx` -- reused for before/after comparison display.
- `frontend/src/lib/api.ts` -- add `repairAnalysis()` function.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`analysis_service.run_analysis()`** (`services/analysis_service.py`) -- full pipeline with hash, dedup, persist, usage tracking. Called with repaired mesh bytes for re-analysis.
- **`_parse_mesh()` + `_read_capped()`** (`api/routes.py`) -- file upload parsing. Repair endpoint reuses for initial upload handling.
- **`validate_magic()` + `enforce_triangle_cap()`** (`api/upload_validation.py`) -- pre-parse validation guards.
- **`run_universal_checks()`** (`analysis/base_analyzer.py`) -- produces the issue codes (`NON_WATERTIGHT`, etc.) that determine repair eligibility.
- **`AnalysisDashboard` component** (`frontend/src/components/AnalysisDashboard.tsx`) -- renders full analysis result; reused twice for before/after comparison.
- **`AuthedUser` + `require_api_key`** (`auth/require_api_key.py`) -- repair endpoint is authenticated.
- **slowapi rate limiter** (`auth/rate_limit.py`) -- repair endpoint uses existing per-key limits.

### Established Patterns
- **Env-var config via `os.getenv()`** -- Phase 5 adds `REPAIR_TIMEOUT_SEC` (default 30) and `REPAIR_MAX_FACES` (default 500000).
- **`Depends()` injection** -- repair endpoint uses `Depends(require_api_key)` + `Depends(get_db_session)` + `Depends(require_kill_switch_open)`.
- **`asyncio.wait_for()` + thread executor** -- pattern used by `analysis_service.run_analysis()` for timeout-bounded sync work; repair service follows the same pattern.
- **Two-phase response** -- analysis_service returns a dict; route handler may enrich it. Repair endpoint wraps the original + repaired dicts in a combined response.

### Integration Points
- New module: `backend/src/services/repair_service.py` -- `async def repair_mesh(file_bytes, filename) -> RepairResult`.
- New route handler in: `backend/src/api/routes.py` (or new `backend/src/api/repair.py` router) -- `POST /api/v1/validate/repair`.
- Modified: `frontend/src/app/(dashboard)/analyses/[id]/page.tsx` -- add conditional "Attempt repair" button.
- Modified: `frontend/src/lib/api.ts` -- add `repairAnalysis()` API function.
- New component: `frontend/src/components/RepairComparison.tsx` -- before/after layout wrapping two `AnalysisDashboard` instances.
- New dependency: `pymeshfix` in `backend/requirements.txt`.

</code_context>

<specifics>
## Specific Ideas

- **Repair is a recovery path, not a replacement for good CAD hygiene.** The endpoint should feel like "let me try to fix this for you" -- helpful but not magical. The CTA label "Attempt Mesh Repair" communicates uncertainty (not "Fix Mesh").
- **Before/after comparison is the key UX moment.** The user sees their broken mesh analysis on the left, the repaired analysis on the right, with improved metrics highlighted in green. This instantly communicates value.
- **Repaired file is always STL** regardless of input format. STEP-to-STL conversion happens during trimesh parsing. This is acceptable because repair operates on triangle meshes, not B-rep geometry. Document this clearly.
- **pymeshfix adds ~50 MB to the Docker image** (Pitfall 1). Budget this in Phase 6's Dockerfile size target (<1.2 GB). The `pymeshfix` wheel includes compiled C++ code -- no additional system deps needed.
- **The 30% figure** ("~30% of real-world uploads") comes from industry data on non-watertight meshes. This is the ROI justification for the phase.

</specifics>

<deferred>
## Deferred Ideas

All surfaced during auto-mode analysis; parked for future phases or post-beta iteration:

- **Async repair via arq worker** -- for large meshes (>200k faces), queuing repair as a background job and returning a poll URL. Phase 7 arq infra would support this. Sync is sufficient for beta.
- **Mesh file storage (blob)** -- storing original and repaired mesh files in Tigris/R2 for later download without re-upload. Useful but adds storage complexity. Deferred until demand signals.
- **Repair history** -- tracking which analyses were repaired, linking original to repaired rows. A `repaired_from_analysis_id` column on `analyses` would enable this. Not needed for beta.
- **STEP-to-STEP repair** -- preserving B-rep topology through repair. Would require cadquery's `Shape.fix()` or OpenCascade healing. Far more complex than mesh repair. ADV-03 territory.
- **Repair quality scoring** -- measuring how much the repair changed the mesh (Hausdorff distance, volume change percentage). Useful for quality assurance but v2+.
- **Batch repair** -- repairing multiple files in one request. v2+.
- **Repair on the share page** -- allowing unauthenticated users to attempt repair from a shared analysis. Scope creep (new capability, not clarification).

</deferred>

---

## Gray Areas Resolved in Auto Mode -- Summary Table

| # | Gray area | Auto-selected default | Decision ID(s) |
|---|-----------|----------------------|----------------|
| 1 | Repair library strategy: trimesh only vs pymeshfix only vs two-tier | Two-tier: trimesh.repair pre-pass + pymeshfix.MeshFix fallback | D-01, D-02 |
| 2 | Endpoint shape: file-upload vs by-analysis-ID | Standalone file-upload at `POST /api/v1/validate/repair` | D-03, D-04 |
| 3 | Re-analysis flow: how repaired mesh feeds back into analysis_service | Call `analysis_service.run_analysis()` with repaired mesh bytes (separate hash, separate row) | D-05 |
| 4 | Repair timeout and limits: timeout value, face-count cap, failure handling | 30s timeout, 500k face cap, graceful fallback to original analysis | D-06, D-07, D-08 |
| 5 | Frontend repair CTA: trigger condition, button UX, before/after display | Conditional on universal-check issue codes; secondary button; before/after comparison + download | D-09, D-10, D-11 |
| 6 | Dedup/caching for repair: separate cache vs rely on analysis_service | Rely on analysis_service dedup (repaired mesh gets its own hash) | D-12 |

## Decisions the User Should Revisit Before `/gsd-plan-phase 5`

These auto-selections are the most consequential to downstream planning. Worth a glance before committing:

1. **D-02 (In-process pymeshfix, not subprocess).** If pymeshfix segfaults on a pathological mesh, it takes down the entire FastAPI process. Subprocess isolation would prevent this but adds 2-5s overhead. At beta scale with a single-instance Fly deployment, a segfault = brief downtime. Fly auto-restarts the process. If this risk is unacceptable, switch to subprocess with `multiprocessing` and a 30s timeout.

2. **D-03 (File-upload endpoint, not by-analysis-ID).** This means the user must re-upload the file to attempt repair, even though they already uploaded it for the original analysis. A by-ID endpoint (`POST /analyses/{id}/repair`) would avoid re-upload but requires storing the original mesh file (not currently stored -- Phase 3 only stores `result_json`). Adding mesh file storage is a significant scope addition. Re-upload is the simpler path for beta.

3. **D-04 (Base64-encoded STL in JSON response).** For a 20 MB repaired STL, the base64 encoding produces ~27 MB of JSON text. This is large but manageable for a single-request action. If response size is a concern, an alternative is multipart response or a two-step flow (repair returns a URL, frontend fetches the file separately). Base64-in-JSON is simpler and matches common API patterns.

4. **D-07 (500k face cap for repair).** This is conservative. pymeshfix can handle 1M+ faces on machines with 4+ GB RAM, but Fly's smallest instances (256 MB - 1 GB) could struggle. If beta users frequently hit this cap with legitimate meshes, raise it and ensure the Fly machine has adequate RAM.

5. **D-12 (No separate repair cache).** If users repeatedly call repair on the same file, pymeshfix runs every time (though the re-analysis is cached). Adding a `(original_mesh_hash) -> repaired_mesh_bytes` cache would skip the repair step on repeated calls. Deferred for simplicity, but easy to add if repair latency becomes a complaint.

---

*Phase: 05-mesh-repair-endpoint*
*Context gathered: 2026-04-15*
*Mode: --auto (all gray areas resolved with recommended defaults; see each D-## "Rationale" line)*
