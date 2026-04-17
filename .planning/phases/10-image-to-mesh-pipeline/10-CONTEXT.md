# Phase 10: Image-to-Mesh Pipeline - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area -- see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 10` if desired)

<domain>
## Phase Boundary

This phase enables users to upload photographs of legacy parts and receive a reconstructed 3D mesh with full DFM analysis. The image-to-mesh reconstruction is the competitive moat -- no other DFM tool combines photo-based 3D reconstruction with manufacturability analysis. Target use case: Saudi Aramco engineers photographing legacy parts from their 14M-part inventory where original CAD data is lost.

Deliverables:
1. TripoSR integration module for single-image 3D reconstruction.
2. `POST /api/v1/reconstruct` async endpoint accepting 1-4 images, returning job ID for polling.
3. Quality confidence scoring algorithm (0-1) based on geometric metrics of reconstructed mesh.
4. Auto-feed into existing `/validate` pipeline after reconstruction completes.
5. Frontend: image upload with preview, reconstruction progress indicator, seamless transition to analysis dashboard.
6. Worker configuration for GPU/CPU inference (external API or local).

**Explicitly out of scope for this phase:**
- Multi-view stereo reconstruction (photogrammetry from 20+ images) -- overkill for single-part photos
- Training or fine-tuning reconstruction models on CadVerify data
- Mesh editing or manual correction of reconstructed geometry
- Texture/color preservation on reconstructed mesh (geometry only)
- Real-time/interactive 3D reconstruction preview during upload
- Batch image-to-mesh (use Phase 9 batch pipeline after reconstruction)

</domain>

<decisions>
## Implementation Decisions

### Reconstruction Model

- **D-01:** Use **TripoSR** as the primary reconstruction engine.
  - MIT license (no commercial restrictions).
  - Single-image input (matches legacy part photography use case).
  - ~300M parameters, runs on both CPU (~30-60s) and GPU (~5-10s).
  - Outputs triangle mesh directly (no intermediate NeRF representation).
  - Well-documented, actively maintained by Stability AI / Tripo AI.
  - **Rationale:** TripoSR is the best balance of quality, speed, license, and ease of integration for single-image reconstruction. InstantMesh requires multi-view input generation first (adds complexity). Trellis is larger and slower. OpenLRM has less community support. TripoSR's MIT license eliminates legal risk for enterprise customers (Saudi Aramco).

- **D-02:** Model weights are downloaded at build time and baked into the Docker image (same pattern as SAM-3D from Phase 7). The `TRIPOSR_MODEL_PATH` env var points to the local weights directory. No runtime downloads in production.
  - **Rationale:** Enterprise/air-gapped deployments (Phase 12) cannot fetch weights at startup. Baking into the image ensures reproducibility and eliminates cold-start latency. Docker image size increase: ~600MB (TripoSR weights).

- **D-03:** Model inference abstracted behind a `ReconstructionEngine` protocol (similar to `JobQueue` protocol from Phase 7):
  ```python
  class ReconstructionEngine(Protocol):
      async def reconstruct(self, images: list[bytes], params: ReconstructParams) -> ReconstructResult: ...
  ```
  Two implementations:
  1. `LocalTripoSR` -- runs TripoSR locally (CPU or GPU).
  2. `RemoteTripoSR` -- calls an external GPU inference API (Replicate, Modal, or RunPod).
  - **Rationale:** Protocol pattern allows swapping inference backends without changing the service layer. Local is suitable for development and air-gapped enterprise. Remote is suitable for Fly.io production (no GPU machines needed). The env var `RECONSTRUCTION_BACKEND` selects which implementation to use (`local` or `remote`).

### Single-Image vs Multi-Image

- **D-04:** Primary mode: **single-image reconstruction**. The endpoint accepts 1-4 images but uses only the best one (highest resolution, best lighting) for TripoSR inference. Additional images are stored for future multi-view enhancement.
  - **Rationale:** TripoSR is a single-image model. Supporting "upload up to 4 images" future-proofs the API contract for when multi-view models mature (InstantMesh, Zero123++), but the current implementation uses only one image. Image selection is based on resolution and a basic quality heuristic (blur detection via Laplacian variance).

- **D-05:** Accepted image formats: JPEG, PNG, WebP. Maximum 20MB per image. Images are preprocessed before inference: resized to 512x512, background removed (rembg library), centered on white background.
  - **Rationale:** TripoSR expects a centered object on clean background. Background removal (rembg) is critical for quality -- photos of parts on workbenches produce garbage without it. The preprocessing pipeline runs before inference and adds ~2-5s. 512x512 is TripoSR's native resolution.

### GPU / Inference Infrastructure

- **D-06:** Production inference runs via **external GPU API** (Replicate, Modal, or RunPod) by default. The `RemoteTripoSR` backend sends preprocessed images to the external API and receives mesh bytes back. Fly.io backend machines do NOT require GPUs.
  - **Rationale:** Fly GPU machines are expensive ($2.50/hr for A100) and always-on. External inference APIs charge per-invocation (~$0.01-0.05 per reconstruction) and scale to zero. For the Saudi Aramco use case (millions of parts), external APIs handle burst better. The `LocalTripoSR` backend is available for on-prem/air-gapped deployments where customers provide their own GPU.

- **D-07:** Inference timeout: **120 seconds** maximum. If the external API does not return within 120s, the job is marked `failed` with a timeout error. The user can retry.
  - **Rationale:** TripoSR inference is typically 5-15s on GPU, 30-60s on CPU. 120s provides generous headroom for cold starts on external APIs and network latency. Beyond 120s, something is wrong.

- **D-08:** Worker machine runs reconstruction jobs as arq tasks alongside existing SAM-3D and batch jobs. A new task type `run_reconstruction_job` is registered in `worker.py`. CPU-bound preprocessing (rembg, resize) runs on the worker; GPU inference is delegated to the external API.
  - **Rationale:** Reuses existing arq worker infrastructure. The worker handles orchestration (preprocess, call API, postprocess, score, feed to validate) while the heavy compute (TripoSR inference) runs externally. No new worker type or process needed.

### Mesh Quality Assessment

- **D-09:** After reconstruction, the generated mesh is assessed on 5 geometric quality metrics, combined into a single confidence score (0.0-1.0):
  1. **Watertight ratio** (0-1): is the mesh manifold/closed?
  2. **Degenerate face ratio** (0-1, inverted): percentage of zero-area or malformed faces.
  3. **Self-intersection ratio** (0-1, inverted): percentage of self-intersecting faces.
  4. **Face count adequacy** (0-1): is the face count reasonable for the object (not too sparse, not too dense)?
  5. **Surface smoothness** (0-1): low variance in face normals of adjacent faces indicates coherent surfaces.
  Weights: watertight 0.3, degenerate 0.2, self-intersection 0.2, face count 0.15, smoothness 0.15.
  - **Rationale:** These metrics reuse the existing universal geometry checks from `base_analyzer.py` (Phase 1). No new analysis logic needed -- just score normalization. The weights emphasize watertightness (most important for DFM analysis downstream) and penalize self-intersections (which cause analyzer failures).

- **D-10:** Confidence thresholds:
  - **>= 0.7**: "High confidence" -- mesh is good enough for full DFM analysis. Auto-feed to validate.
  - **0.4 - 0.7**: "Medium confidence" -- mesh has quality issues. Auto-feed to validate but include warning in results: "Reconstruction quality is moderate; results may be less reliable."
  - **< 0.4**: "Low confidence" -- mesh is poor quality. Still feed to validate but prominently warn: "Reconstruction quality is low; consider uploading additional images or a CAD file."
  All thresholds feed to validate regardless -- the user gets analysis results with appropriate confidence caveats. No blocking.
  - **Rationale:** Never block analysis. The user uploaded a photo because they have no CAD file -- any analysis is better than none. The confidence score lets engineers calibrate trust in the results. Thresholds are configurable via env vars: `RECON_CONFIDENCE_HIGH`, `RECON_CONFIDENCE_LOW`.

### Endpoint Shape

- **D-11:** `POST /api/v1/reconstruct` is **async (202 Accepted)**, following the same pattern as SAM-3D (Phase 7):
  - Request: `multipart/form-data` with `images` (1-4 files) + optional `process_types` (comma-separated) + optional `rule_pack`.
  - Response 202:
    ```json
    {
      "job_id": "01HZA...",
      "status": "pending",
      "poll_url": "/api/v1/jobs/01HZA...",
      "estimated_seconds": 30
    }
    ```
  - Job completion adds `reconstruction` object to the job result:
    ```json
    {
      "job_id": "01HZA...",
      "status": "completed",
      "reconstruction": {
        "confidence_score": 0.82,
        "confidence_level": "high",
        "face_count": 24576,
        "mesh_url": "/api/v1/reconstructions/01HZA.../mesh.stl"
      },
      "analysis_id": "01HYB...",
      "analysis_url": "/api/v1/analyses/01HYB..."
    }
    ```
  - **Rationale:** Async matches existing patterns (SAM-3D, batch). Reconstruction takes 10-60s -- too slow for sync HTTP. The response includes both the reconstruction result (confidence, mesh download) and the DFM analysis result (linked via `analysis_id`). The `estimated_seconds` hint helps the frontend set poll interval.

- **D-12:** `GET /api/v1/reconstructions/{job_id}/mesh.stl` serves the reconstructed mesh file for download. Requires authentication (same user who submitted the job).
  - **Rationale:** Users may want to download the reconstructed mesh separately from the analysis -- e.g., to import into CAD software for editing. Authentication prevents unauthorized mesh access.

- **D-13:** Reconstruction jobs are tracked in the existing `jobs` table (same as SAM-3D). Job type: `reconstruction`. No new database table needed for the job lifecycle -- only the job result payload includes reconstruction-specific data.
  - **Rationale:** Reuses Phase 7 infrastructure entirely. The `jobs` table already has `type`, `status`, `result_json`, `user_id` columns. Adding `type='reconstruction'` is sufficient.

### Storage

- **D-14:** Input images stored at `/data/blobs/reconstruct/{job_ulid}/input/` (1-4 image files). Output mesh stored at `/data/blobs/reconstruct/{job_ulid}/output/mesh.stl`. Reuses existing Fly volume storage pattern from Phase 7 and Phase 9.
  - **Rationale:** Consistent with the established blob storage convention. Images are retained for debugging and potential future re-reconstruction with improved models. The job_ulid namespace prevents collisions.

- **D-15:** Retention: reconstruction files follow the same retention policy as batch files (D-17 from Phase 9) -- configurable via `RECON_FILE_RETENTION_DAYS` env var, default 30 days. Cleanup task deletes expired reconstruction directories.
  - **Rationale:** 30 days (longer than batch's 7 days) because reconstruction results are harder to reproduce (depends on model version, preprocessing). Gives engineers time to download meshes. Configurable for enterprise customers who want longer retention.

### Frontend UX

- **D-16:** Frontend flow: 4-step wizard integrated into the existing dashboard:
  1. **Upload**: Drag-and-drop or file picker for 1-4 images. Live preview thumbnails. "Reconstruct" button.
  2. **Processing**: Progress indicator with estimated time. Shows preprocessing status, then reconstruction status. Poll `GET /api/v1/jobs/{id}` every 3 seconds.
  3. **Reconstruction result**: Show 3D preview of reconstructed mesh (Three.js) + confidence score badge (green/yellow/red). "Analyze" button (auto-fires, user sees it happening).
  4. **Analysis dashboard**: Redirect to existing analysis view (same as `/validate` results). Includes a "Reconstructed from image" badge and confidence score.
  - **Rationale:** The wizard keeps the user informed throughout the multi-step process. Reusing the existing analysis dashboard (step 4) avoids building a new results view. The 3D preview in step 3 gives the user a chance to see the mesh before analysis -- builds trust.

- **D-17:** New frontend route: `/reconstruct` under `app/(dashboard)/reconstruct/`. Page includes the upload wizard and links to past reconstruction jobs in the user's history.
  - **Rationale:** Separate route from `/validate` because the input is fundamentally different (images vs CAD files). But the results flow into the same analysis system.

- **D-18:** Navigation: add "Image to 3D" entry in the sidebar/header nav, between "Analyze" and "History". Icon: camera or image icon.
  - **Rationale:** The feature is a primary workflow, not buried in a submenu. "Image to 3D" is clearer than "Reconstruct" for engineers who may not know the technical term.

### Claude's Discretion

The following are left to the researcher/planner to resolve with standard patterns:

- Exact Replicate/Modal/RunPod API integration details (which provider, API key management, error handling).
- rembg model variant selection (u2net vs isnet-general-use -- both work, isnet is faster).
- Image quality heuristic implementation details (Laplacian variance threshold for blur detection).
- Exact preprocessing pipeline order (resize then remove background, or vice versa).
- Three.js mesh preview component design for reconstruction result step.
- Poll interval optimization (start at 3s, back off to 5s after 30s).
- Whether to show "similar reconstructions" from other users (privacy concern -- probably no).
- Exact confidence score normalization formula (linear combination vs learned weights).
- Worker memory management during TripoSR local inference (model loading/unloading strategy).
- Cleanup task scheduling mechanism (cron arq job or on-demand).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase-level requirements and roadmap
- `.planning/ROADMAP.md` "Phase 10: Image-to-Mesh Pipeline" -- goal, success criteria, key deliverables, suggested plans (10.A-10.C), dependencies.
- `.planning/REQUIREMENTS.md` "Image-to-Mesh Pipeline" (IMG-01..05) -- locked requirements for reconstruct endpoint, quality scoring, auto-feed, frontend.
- `.planning/PROJECT.md` "Key Decisions" -- image-to-mesh as competitive moat, enterprise target Saudi Aramco.

### Prior phase context (infrastructure this phase builds on)
- `.planning/phases/07-async-sam-3d/07-CONTEXT.md` -- D-01/D-02: arq + `JobQueue` protocol, D-05/D-06: worker architecture, D-13/D-14: Fly volume blob storage, D-08: async 202 pattern. Phase 10 reuses this entire pattern.
- `.planning/phases/09-batch-api-webhook-pipeline/09-CONTEXT.md` -- D-07: coordinator job pattern, D-16/D-17: blob storage and retention cleanup. Phase 10 follows same storage conventions.
- `.planning/phases/03-persistence-analysis-service-history-caching/03-CONTEXT.md` -- D-07/D-08: `analysis_service.run_analysis()` (called after reconstruction to analyze the mesh), D-09/D-11: hash dedup.

### Existing code to integrate with
- `backend/src/services/analysis_service.py` -- `run_analysis()` for post-reconstruction DFM analysis.
- `backend/src/jobs/worker.py` -- arq `WorkerSettings` with existing task types. Add `run_reconstruction_job`.
- `backend/src/jobs/protocols.py` -- `JobQueue` protocol for enqueue/status/cancel. Reconstruction jobs use this.
- `backend/src/jobs/arq_backend.py` -- `ArqJobQueue` implementation. Register reconstruction task.
- `backend/src/services/job_service.py` -- `save_mesh_blob()` for file storage. Extend for reconstruction blobs.
- `backend/src/analysis/base_analyzer.py` -- `run_universal_checks()` for quality scoring metrics.
- `backend/src/analysis/context.py` -- `GeometryContext` for mesh quality assessment.
- `backend/src/db/models.py` -- `Job` model (type='reconstruction'), `Analysis` model (linked from reconstruction).
- `backend/src/api/routes.py` -- existing validate endpoint pattern for reference.

### Brownfield codebase map
- `.planning/codebase/ARCHITECTURE.md` -- pipeline data flow, service layer pattern, jobs module.
- `.planning/codebase/CONVENTIONS.md` -- snake_case, env-var config, HTTPException patterns, ULID for public IDs.
- `.planning/codebase/STACK.md` -- Python 3, FastAPI, trimesh, numpy, scipy, arq, Redis.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`JobQueue` protocol** (`jobs/protocols.py`): `enqueue()`, `get_status()`, `cancel()` -- reconstruction jobs use this directly.
- **`ArqJobQueue`** (`jobs/arq_backend.py`): Register `run_reconstruction_job` task alongside existing SAM-3D and batch tasks.
- **`analysis_service.run_analysis()`**: Called after reconstruction to run full DFM pipeline on the generated mesh. No new analysis code needed.
- **`run_universal_checks()`** (`base_analyzer.py`): Provides watertight, degenerate face, self-intersection checks that feed into confidence scoring.
- **`GeometryContext`** (`context.py`): Precomputes geometry data for quality assessment.
- **`job_service.save_mesh_blob()`**: Saves files to Fly volume. Extend path structure for reconstruction blobs.
- **`Job` ORM model**: Existing job lifecycle tracking with `type`, `status`, `result_json` fields.
- **Three.js viewer** (frontend): Existing 3D mesh renderer on analysis dashboard. Reuse for reconstruction preview.

### Established Patterns
- **Async 202 pattern**: SAM-3D endpoint returns 202 + job ID + poll URL. Reconstruction follows identical pattern.
- **arq task registration**: `worker.py` `functions` list. Add reconstruction task.
- **ULID for public IDs**: All user-facing IDs are ULIDs.
- **Env-var configuration**: `os.getenv()` with lazy read for all configurable values.
- **Service layer abstraction**: Routes call service functions; services orchestrate infrastructure.

### Integration Points
- New module: `backend/src/services/reconstruction_service.py` -- image preprocessing, inference dispatch, quality scoring, auto-feed to analysis.
- New module: `backend/src/reconstruction/` -- TripoSR engine wrapper, preprocessing pipeline, `ReconstructionEngine` protocol.
- New task: `run_reconstruction_job` in `backend/src/jobs/worker.py`.
- New route: `POST /api/v1/reconstruct`, `GET /api/v1/reconstructions/{id}/mesh.stl` in a new `reconstruct_router`.
- Frontend: new page under `app/(dashboard)/reconstruct/` with upload wizard.
- Dependencies to add: `triposr` (or vendor the inference code), `rembg`, `Pillow`.

</code_context>

<specifics>
## Specific Ideas

- **"The competitive moat"** -- this feature is what differentiates CadVerify from every other DFM tool. No competitor combines image-to-mesh reconstruction with manufacturability analysis. Marketing should emphasize this.
- **Saudi Aramco use case**: engineers photograph legacy parts on the shop floor. Often a single photo from a smartphone. The preprocessing pipeline (background removal, centering) must handle noisy real-world photos, not just clean studio shots.
- **Trust through transparency**: the confidence score and quality warnings let engineers calibrate trust. "We reconstructed your part with 82% confidence -- here are the DFM results" is more honest than silently analyzing a potentially poor reconstruction.
- **Seamless flow**: the user should never feel like they are using two separate tools (reconstruction + analysis). Upload an image, get a DFM report. The reconstruction is an implementation detail, not a user concern.

</specifics>

<deferred>
## Deferred Ideas

- **Multi-view reconstruction (InstantMesh/Zero123++)** -- when multi-view models mature, accept 4+ images and generate higher-quality meshes. The API contract (1-4 images) already supports this without breaking changes.
- **Batch image-to-mesh** -- process hundreds of part photos via the Phase 9 batch pipeline. Would need a batch-aware reconstruction coordinator. Not in Phase 10 scope.
- **Reconstruction model fine-tuning** -- train TripoSR on manufacturing part datasets for better quality on industrial parts (brackets, housings, gears). Requires labeled training data.
- **Mesh repair after reconstruction** -- auto-apply Phase 5 mesh repair to reconstructed meshes before analysis. Could improve confidence scores.
- **Video-to-mesh** -- accept a short video (turntable rotation) for multi-view reconstruction. Consumer-friendly but complex.
- **Comparison: reconstructed vs original CAD** -- if the customer later finds the original CAD file, overlay and compare. Quality validation use case.

</deferred>

---

## Gray Areas Resolved in Auto Mode -- Summary Table

| # | Gray area | Auto-selected default | Decision ID(s) |
|---|-----------|----------------------|----------------|
| 1 | Reconstruction model | TripoSR (MIT license, single-image, fast, well-documented) | D-01, D-02, D-03 |
| 2 | Single vs multi-image | Single-image primary, multi-image stored for future | D-04, D-05 |
| 3 | GPU / inference infra | External API (Replicate/Modal) for prod, local for dev/air-gap | D-06, D-07, D-08 |
| 4 | Mesh quality assessment | 5-metric weighted score (watertight, degenerate, self-intersect, face count, smoothness) | D-09, D-10 |
| 5 | Endpoint shape | Async 202 + job polling (same as SAM-3D) | D-11, D-12, D-13 |
| 6 | Storage | Fly volume /data/blobs/reconstruct/{ulid}/, 30-day retention | D-14, D-15 |
| 7 | Frontend UX | 4-step wizard: upload -> processing -> preview -> analysis | D-16, D-17, D-18 |
| 8 | Confidence scoring | Geometric quality metrics with 0.7/0.4 thresholds, never blocks analysis | D-09, D-10 |

## Decisions the User Should Revisit Before `/gsd-plan-phase 10`

1. **D-01 (TripoSR model choice).** TripoSR is the recommended default but the 3D reconstruction space moves fast. By April 2026, newer models (Trellis 2.0, Meta's 3D Gen) may offer better quality. The researcher should evaluate current state-of-the-art during the research phase and confirm TripoSR is still optimal.

2. **D-06 (External inference API).** The choice between Replicate, Modal, and RunPod affects cost and latency. Replicate has TripoSR pre-deployed. Modal offers custom container builds. RunPod is cheapest for sustained GPU use. The researcher should price out the Saudi Aramco scale (millions of reconstructions).

3. **D-02 (Model weights in Docker image).** Adding ~600MB to the Docker image is significant. If `LocalTripoSR` is rarely used (production uses `RemoteTripoSR`), consider making local weights optional (separate Docker image tag) to keep the standard image lean.

4. **D-10 (Confidence thresholds 0.7/0.4).** These thresholds are educated guesses. After initial deployment, calibrate against real-world reconstruction quality. The env-var configurability (D-10) enables tuning without code changes.

5. **D-04 (Single-image only for now).** If early users consistently upload multiple images expecting better results, prioritize the multi-view upgrade. The API contract supports it -- only the backend inference needs to change.

---

*Phase: 10-image-to-mesh-pipeline*
*Context gathered: 2026-04-15*
*Mode: --auto (all gray areas resolved with recommended defaults; see each D-## "Rationale" line)*
