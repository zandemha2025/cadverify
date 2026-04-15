# Codebase Concerns

**Analysis Date:** 2026-04-15

## Tech Debt

**Temporary File Cleanup in STEP Parser:**
- Issue: `parse_step_from_bytes()` creates temporary files but doesn't explicitly clean them up. Files are created with `tempfile.NamedTemporaryFile(delete=False)` in `src/parsers/step_parser.py:102`, relying on OS cleanup at process termination.
- Files: `backend/src/parsers/step_parser.py:90-105`
- Impact: Long-running production instances could accumulate temp files in `/tmp` or system temp directory, potentially filling disk space on extended analysis runs.
- Fix approach: Either use context manager with `delete=True`, or implement explicit cleanup handler. Track temp files and clean up after parse completes. Consider caching parsed results for identical inputs.

**Broad Exception Handling:**
- Issue: Many critical analysis functions use bare `except Exception:` that silently swallow errors and return empty lists/safe defaults. Examples: `check_wall_thickness()` in `src/analysis/additive_analyzer.py:94`, `_compute_wall_thickness()` in `src/analysis/context.py:161`, ray casting in `src/analysis/cnc_analyzer.py:192`.
- Files: `backend/src/analysis/additive_analyzer.py`, `backend/src/analysis/cnc_analyzer.py`, `backend/src/analysis/context.py`, `backend/src/analysis/processes/checks.py`
- Impact: Mesh corruption or numerical edge cases fail silently, producing incomplete analysis results without user awareness. Harder to debug production issues.
- Fix approach: Log exceptions at `warning` level with mesh/geometry context. Consider categorizing failures: "ray_cast_failed", "topology_failed" and returning a clear Issue rather than silently degrading.

**Legacy Process Analyzer Dual Path:**
- Issue: Routes maintain a legacy `PROCESS_ANALYZERS` dictionary alongside new registry-based analyzers in `src/api/routes.py:38-47`. Both paths are invoked with fallback logic at lines 168-183.
- Files: `backend/src/api/routes.py:36-48`, `backend/src/api/routes.py:166-183`
- Impact: Inconsistent behavior if new and legacy analyzers diverge. Hard to deprecate old path without breaking backward compatibility. Test coverage is split between two code paths.
- Fix approach: Complete migration to registry-based analyzers. Remove legacy `PROCESS_ANALYZERS` map and deduplicate logic. Add deprecation notice to old paths.

**Hardcoded Constants Scattered:**
- Issue: Manufacturing constraints are hardcoded in individual analyzer files rather than centralized. E.g., `MAX_POCKET_DEPTH_RATIO` in `cnc_analyzer.py:31-34`, `MIN_WALL_THICKNESS` in `additive_analyzer.py:22-34`, `MAX_WORKPIECE` in `cnc_analyzer.py:23-28`.
- Files: `backend/src/analysis/cnc_analyzer.py`, `backend/src/analysis/additive_analyzer.py`, `backend/src/analysis/molding_analyzer.py`, `backend/src/analysis/casting_analyzer.py`
- Impact: Updating process constraints (e.g., new CNC machine with larger envelope) requires code changes across multiple files. Risk of inconsistency when same threshold appears in multiple places. Rule packs can override but original constants remain.
- Fix approach: Centralize manufacturing constraints in `src/profiles/` or dedicated config module. Make all analyzers read from shared definitions. Store version/source of constraints for audit trail.

## Known Bugs

**Temp File Not Cleaned Up in STEP Parsing:**
- Symptoms: Temp files accumulate in system temp directory (`/tmp` on Unix, `%TEMP%` on Windows) when STEP files are uploaded repeatedly.
- Files: `backend/src/parsers/step_parser.py:102-105`
- Trigger: Upload any .step or .stp file through `/validate` endpoint. Repeat 100+ times, check temp directory.
- Workaround: Manual cleanup of temp files, or restart service to clear OS temp cache. Not blocking in practice for typical usage.

**Wall Thickness Ray Cast May Return inf for All Faces:**
- Symptoms: Some complex non-watertight meshes report `np.inf` for all wall thickness measurements, causing checks to produce empty issue lists even though geometry is problematic.
- Files: `backend/src/analysis/context.py:130-174`, `backend/src/analysis/processes/checks.py:28-58`
- Trigger: Non-manifold or heavily degenerate meshes where inward ray casting fails to find interior wall.
- Workaround: Check `is_watertight` status first in analysis dashboard. Use `/validate/quick` for faster feedback on broken geometry.

**Scale-Aware Epsilon May Be Incorrect for Micro Parts:**
- Symptoms: Very small parts (sub-millimeter) or very large assemblies (multi-meter) may have scale-dependent numerical issues in wall thickness calculation.
- Files: `backend/src/analysis/context.py:75-78`
- Trigger: Upload STL/STEP with bounding box diagonal < 1mm or > 1000mm.
- Cause: Epsilon calculation uses `max(bbox_diag * 1e-5, 1e-5)` which assumes reasonable scale. For ultra-precision micro parts, 1e-5 may be too large. For huge assemblies, it may be too small.
- Workaround: Normalize input geometry to expected mm scale before upload. Future: implement configurable scale hints via API.

## Security Considerations

**File Upload Without Type Validation Beyond Extension:**
- Risk: Although file extension is checked (`.stl`, `.step`, `.stp`), the actual MIME type or content is not verified before passing to parsers. A malformed STEP file or binary blob masquerading as STL could trigger parsing library crashes or memory issues.
- Files: `backend/src/api/routes.py:84-107`
- Current mitigation: File size limit (configurable `MAX_UPLOAD_MB`), exception handling in parser, and analysis wraps in try-catch.
- Recommendations: Validate MIME type or file magic bytes (first 4-8 bytes) before parsing. Consider sandboxing mesh parsing (e.g., subprocess or container). Add rate limiting per IP to prevent DoS via large files.

**CORS Configuration Allows All Headers:**
- Risk: `allow_headers=["*"]` in FastAPI CORS middleware at `backend/main.py:51` accepts any request header. Combined with stateless API (no auth), this is currently safe but fragile if auth is added later.
- Files: `backend/main.py:46-53`
- Current mitigation: No authentication exists, so header forgery has limited impact. Comment acknowledges the tradeoff.
- Recommendations: If auth is added (API keys, JWT), tighten `allow_headers` to specific values. Consider implementing rate limiting middleware to mitigate abuse.

**Temp File Disclosure (Low Risk):**
- Risk: Temporary STEP files written to system `/tmp` are readable by any user on the system. If the temp filename is predictable, another user could potentially read temp files before cleanup.
- Files: `backend/src/parsers/step_parser.py:102-105`
- Current mitigation: `tempfile.NamedTemporaryFile()` generates cryptographically random names, making prediction infeasible.
- Recommendations: Use `mode=0o600` (read/write only by owner) when creating temp files if CAD data is considered sensitive. This is automatic with `tempfile` but worth documenting.

## Performance Bottlenecks

**Ray Casting in Wall Thickness Calculation:**
- Problem: `_compute_wall_thickness()` fires one ray per face (N = face_count) with `multiple_hits=True`, which is O(N log N) in trimesh. For dense meshes (100k+ faces), this is the slowest operation in analysis.
- Files: `backend/src/analysis/context.py:156-172`
- Cause: `mesh.ray.intersects_location()` scales with mesh complexity. No spatial optimization (e.g., grid subdivision).
- Measurement: Typical 50k-face mesh: 2-5 seconds ray casting out of 6-8s total analysis time.
- Improvement path: 
  1. Sample faces instead of checking all (e.g., every 10th face for wall estimation).
  2. Use spatial accelerators (BVH trees) if trimesh exposes them.
  3. Cache wall thickness results in `GeometryContext` (already done, but could cache across requests for identical mesh hash).
  4. Parallelize ray casting if trimesh supports multi-threaded calls.

**Process Analyzer Fallthrough Loop:**
- Problem: `src/api/routes.py:166-183` loops over all target processes, instantiates new analyzer per process, and runs analysis. For 20+ processes, this multiplies work even though much precomputation is shared.
- Files: `backend/src/api/routes.py:163-189`
- Cause: Each `get_analyzer(proc)` or legacy fallback creates fresh context and runs checks, re-reading from shared `ctx`.
- Measurement: Analysis of single geometry for all 21 processes: ~8-10s.
- Improvement path:
  1. Batch analyzers: create context once, pass to all process-specific analyzers as read-only.
  2. Lazy evaluation: only run analyzers for requested processes (already done with `_resolve_target_processes()`).
  3. Parallelize: use `ProcessPoolExecutor` to run independent analyzers concurrently (requires pickling support for `GeometryContext`).

**SAM-3D Segmentation Not Production-Ready:**
- Problem: SAM-3D model loading and inference is slow (30-60s for typical mesh). Feature detection (`detect_all()` in `src/analysis/features/`) uses heuristics that are also CPU-intensive.
- Files: `backend/src/segmentation/sam3d/` (entire module), `backend/src/analysis/features/`
- Cause: PyTorch model loading + CUDA/CPU inference; fallback heuristics are complex ray-casting operations.
- Measurement: SAM-3D inference on 50k-face mesh: 45-60s (disabled in Phase 1, optional).
- Improvement path:
  1. Make SAM-3D inference async (Celery task, not blocking HTTP).
  2. Pre-load model weights on startup to avoid cold-start penalty.
  3. Cache embeddings by mesh hash (already done in `cache.py`).
  4. Offer fast/slow modes: heuristic-only vs. AI-assisted segmentation.

## Fragile Areas

**Complex Intersection Logic in Sheet Metal & Molding:**
- Files: `backend/src/analysis/processes/formative/sheet_metal.py`, `backend/src/analysis/processes/formative/injection_molding.py`
- Why fragile: Edge detection and dihedral angle analysis rely on mesh topology being well-formed. Non-manifold edges or degenerate faces cause silent failures.
- Safe modification: Add topology validation step in `GeometryContext.build()` before consuming topology data. Test on suite of degenerate meshes (T-junctions, holes, self-intersecting).
- Test coverage: Minimal tests for edge cases; mostly happy-path tests.

**Feature Detection Heuristics (Cylinders, Flats, etc.):**
- Files: `backend/src/analysis/features/cylinders.py`, `backend/src/analysis/features/flats.py`
- Why fragile: Heuristics detect features by pattern-matching (e.g., circular edges → cylinder). Small changes to threshold or edge ordering break detection.
- Safe modification: Add explicit test cases for borderline geometry (e.g., nearly-circular, slanted cylinder). Document threshold rationale.
- Test coverage: `tests/test_features.py` exists but coverage is low (basic sanity checks).

**Rule Pack Override Logic:**
- Files: `backend/src/analysis/rules/__init__.py`
- Why fragile: Rule packs overlay severity escalation and custom checks on top of core analysis. Interaction between multiple rule packs (if chained) is untested.
- Safe modification: Add validation in `RulePack.apply()` to ensure overrides don't reference undefined issue codes. Test with multiple rule packs simultaneously.
- Test coverage: `tests/test_rule_packs.py` tests individual packs but not interactions.

## Scaling Limits

**Backend Memory for Large Meshes:**
- Current capacity: Tested up to ~200k-face mesh on 8GB RAM machine.
- Limit: Context build stores full mesh + all numpy arrays in memory. 500k+ face meshes may cause OOM.
- Scaling path: 
  1. Implement streaming mesh parsing (load in chunks, analyze incrementally).
  2. Use memory-mapped numpy arrays for large geometry data.
  3. Offload segmentation (SAM-3D) to GPU worker pool (Phase 3 roadmap).
  4. Add request-level cleanup to release mesh after analysis completes.

**API Request Timeout:**
- Current capacity: Most analyses complete in < 10s; large meshes + all processes may take 30-60s.
- Limit: No explicit timeout configured in FastAPI. Deployment proxy (nginx, Gunicorn) may enforce own limits.
- Scaling path: Add configurable `ANALYSIS_TIMEOUT_SEC` env var (default 60). Return 504 if analysis exceeds limit. Offer quick endpoint for interactive use.

**Concurrent Analysis Requests:**
- Current capacity: Single Uvicorn worker handles ~1 request at a time (CPU-bound analysis blocks I/O).
- Limit: CPU-bound workload doesn't scale horizontally without async-ifying mesh parsing and ray casting.
- Scaling path:
  1. Run multiple Uvicorn workers behind load balancer.
  2. Extract heavy lifting (context build, feature detection) into background task (Celery).
  3. Cache analysis results by mesh hash to skip redundant work.

## Dependencies at Risk

**cadquery (Optional but Heavy):**
- Risk: STEP parsing depends on `cadquery` + OpenCascade C++ libraries, which are hard to install in some environments (Windows, M1 Mac, Alpine Linux). Not listed in `requirements.txt`; installed separately via pip.
- Impact: If cadquery is not installed, STEP parsing fails with 501 error. Users see "requires cadquery" message but install is non-trivial.
- Migration plan: Offer pre-built Docker image with cadquery baked in. Or switch to lightweight STEP parser library (e.g., `pyassimp`). Document installation steps prominently.

**trimesh Dependency on scipy:**
- Risk: `trimesh[easy]` in `requirements.txt:4` pins scipy>=1.13.0 but dihedral angle computation and ray casting may be slow with older scipy versions. No version upper bound.
- Impact: Future scipy major version may break ray-casting API or change numerical behavior.
- Migration plan: Pin scipy version range (e.g., `>=1.13.0,<2.0`). Add integration test that exercises ray casting to catch scipy breaking changes early.

**Next.js 16.2.3 (Frontend):**
- Risk: Next.js is at version 16.x; breaking changes between major versions are common. React 19 and TypeScript 5 are also recent.
- Impact: Dependencies may have security patches that are incompatible. Upgrading requires careful testing of 3D viewer and form interactions.
- Migration plan: Set up automated dependency updates (Dependabot). Regular upgrades of React/TS every 2-3 minor versions.

## Missing Critical Features

**User Authentication & Authorization:**
- Problem: API has no auth; any client can call `/validate` and `/rule-packs`. Suitable for public SaaS but not for internal enterprise use.
- Blocks: Multi-tenancy, audit logging, rate limiting per user, usage billing.
- Recommendation: Add API key authentication (simple) or JWT (complex but flexible) before production deployment.

**Persistent Storage of Analysis Results:**
- Problem: Analysis results are returned but never stored. If user loses browser tab, analysis is gone.
- Blocks: Building a history/dashboard feature, exporting reports, A/B testing analysis improvements.
- Recommendation: Add optional result archival to database (PostgreSQL/SQLite). Offer `/history` endpoint to retrieve past analyses.

**Mesh Repair/Healing:**
- Problem: When mesh is non-manifold or has holes, analysis detects it but doesn't offer repair. Users must fix in CAD software.
- Blocks: Improving success rate for broken files, reducing friction in design iteration.
- Recommendation: Integrate lightweight mesh repair library (e.g., `pyfqmr`, `pymeshfix`) as optional post-processing step. Offer in `/validate/repair` endpoint.

## Test Coverage Gaps

**SAM-3D Segmentation Edge Cases:**
- What's not tested: Model loading failures, CUDA/CPU fallback, corrupted cache files, model version mismatches.
- Files: `backend/src/segmentation/sam3d/`
- Risk: SAM-3D is an optional module (disabled in Phase 1) but will be critical in Phase 3. Lack of error handling means failures silently degrade to empty segmentation.
- Priority: Medium (not yet production, but plan ahead).

**Large Mesh Performance:**
- What's not tested: Ray casting on meshes > 200k faces, memory usage under load, timeout behavior.
- Files: `backend/src/analysis/context.py`, `backend/src/api/routes.py`
- Risk: Production deployment may encounter large assemblies that crash or timeout without warning.
- Priority: High (affects production uptime).

**Rule Pack Interactions:**
- What's not tested: Chaining multiple rule packs, conflicting overrides, custom issue codes not in base analysis.
- Files: `backend/src/analysis/rules/__init__.py`, `backend/tests/test_rule_packs.py`
- Risk: Complex rule packs may produce unexpected verdict changes or missing issues.
- Priority: Medium (rule packs are extensibility point).

**Frontend Error Handling:**
- What's not tested: Network timeouts, partial response corruption, API returning malformed JSON.
- Files: `frontend/src/lib/api.ts`, `frontend/src/app/page.tsx`
- Risk: Frontend assumes well-formed responses; bad API response causes unhandled promise rejection.
- Priority: Medium (UX degradation, not data loss).

**STEP Parser on Corrupted Files:**
- What's not tested: Truncated STEP files, malformed headers, binary STEP (not ASCII), extremely large assembly trees.
- Files: `backend/src/parsers/step_parser.py`
- Risk: cadquery may hang or crash on malformed input.
- Priority: High (user-facing, security concern).

**Process Scoring Logic:**
- What's not tested: All-fail case (no viable processes), ties in scoring, edge cases in `rank_processes()`.
- Files: `backend/src/matcher/profile_matcher.py`, `backend/src/api/routes.py:200-203`
- Risk: `best_process` selection may fail silently or pick arbitrary winner in ambiguous cases.
- Priority: Medium (UX concern).

---

*Concerns audit: 2026-04-15*
