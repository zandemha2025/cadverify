# Phase 5: Mesh Repair Endpoint - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 05-mesh-repair-endpoint
**Mode:** --auto (all gray areas auto-resolved with recommended defaults)
**Areas discussed:** Repair library strategy, Endpoint shape, Re-analysis flow, Repair timeout and limits, Frontend repair CTA, Dedup/caching

---

## Repair Library Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| trimesh.repair only | Fast, in-process, handles simple cases (~60%) but fails on complex non-manifold | |
| pymeshfix only | C++ library, handles hard cases, 1-5s overhead per mesh, adds Docker image weight | |
| Two-tier (trimesh first, pymeshfix fallback) | Best of both: fast for simple cases, robust for hard cases | ✓ |

**User's choice:** [auto] Two-tier (recommended default)
**Notes:** ROADMAP.md explicitly specifies this approach. Research confirms pymeshfix 0.18 has cross-platform wheels.

---

## Endpoint Shape

| Option | Description | Selected |
|--------|-------------|----------|
| POST /api/v1/validate/repair (file upload) | Standalone endpoint matching /validate pattern; no mesh storage dependency | ✓ |
| POST /api/v1/analyses/{id}/repair (by ID) | Requires stored mesh files (not in scope); avoids re-upload | |
| POST /api/v1/repair (separate namespace) | Breaks away from /validate grouping | |

**User's choice:** [auto] File-upload endpoint at /api/v1/validate/repair (recommended default)
**Notes:** REQUIREMENTS.md REPAIR-01 locks this URL. Phase 3 does not store mesh files, only result_json.

---

## Re-analysis Flow

| Option | Description | Selected |
|--------|-------------|----------|
| Call analysis_service.run_analysis() with repaired bytes | Reuses full pipeline + dedup + persist; repaired mesh gets its own hash | ✓ |
| Return repaired file only (no re-analysis) | Simpler but doesn't close the loop -- user must re-upload manually | |
| Inline analysis (bypass analysis_service) | Loses dedup, persistence, usage tracking | |

**User's choice:** [auto] Call analysis_service.run_analysis() (recommended default)
**Notes:** Phase 3's analysis_service is the single entry point for all analysis operations. Reusing it is the correct architectural choice.

---

## Repair Timeout and Limits

| Option | Description | Selected |
|--------|-------------|----------|
| 30s timeout + 500k face cap | Conservative; prevents hangs and OOM on modest instances | ✓ |
| 60s timeout + 1M face cap | More permissive; risks OOM on small Fly instances | |
| No cap (rely on existing upload size limit) | 100 MB upload = ~1.2M faces; pymeshfix could OOM | |

**User's choice:** [auto] 30s timeout + 500k face cap (recommended default)
**Notes:** Pitfall 5 warns about pymeshfix hangs. asyncio.wait_for() pattern matches existing analysis timeout approach.

---

## Frontend Repair CTA

| Option | Description | Selected |
|--------|-------------|----------|
| Conditional button on universal-check issues + before/after comparison | Shows only when repair might help; provides clear before/after UX | ✓ |
| Always-visible repair button | Confusing for meshes with no defects | |
| Repair as a separate page/flow | More friction; breaks the analysis detail page context | |

**User's choice:** [auto] Conditional button + before/after comparison (recommended default)
**Notes:** REPAIR-03 specifies conditional display. Trigger codes: NON_WATERTIGHT, INCONSISTENT_NORMALS, NOT_SOLID_VOLUME, DEGENERATE_FACES, MULTIPLE_BODIES.

---

## Dedup/Caching for Repair

| Option | Description | Selected |
|--------|-------------|----------|
| Rely on analysis_service dedup only | Repaired mesh hash cached via analyses table; repair step itself not cached | ✓ |
| Separate repairs cache table | Cache (original_hash -> repaired_bytes); avoids re-running pymeshfix | |
| Full Redis cache for repair results | Fastest but most complex; adds Redis dependency for repair path | |

**User's choice:** [auto] Rely on analysis_service dedup (recommended default)
**Notes:** ROADMAP Success Criterion #2 is satisfied by analysis_service's hash-based dedup on the repaired mesh.

---

## Claude's Discretion

- Exact trimesh.repair function call sequence
- Base64 encoding variant (standard vs URL-safe)
- pymeshfix import error handling
- Repair service module structure
- HTTP status code for repair response
- Frontend comparison layout details

## Deferred Ideas

- Async repair via arq worker (Phase 7)
- Mesh file storage for download-without-reupload
- Repair history linking (original -> repaired analysis)
- STEP-to-STEP repair (ADV-03)
- Repair quality scoring (Hausdorff distance)
- Batch repair
- Repair on shared pages (unauthenticated)
