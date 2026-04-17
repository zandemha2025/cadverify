# Phase 10: Image-to-Mesh Pipeline - Research

**Researched:** 2026-04-15
**Phase:** 10 — Image-to-Mesh Pipeline
**Requirements:** IMG-01, IMG-02, IMG-03, IMG-04, IMG-05

## Research Summary

This phase adds single-image 3D reconstruction via TripoSR, integrated into the existing async job pipeline. The architecture mirrors the SAM-3D async pattern (Phase 7) with a `ReconstructionEngine` protocol abstraction, `reconstruction_service.py` orchestration layer, and new arq task type. Key findings: TripoSR integration requires `tsr` Python package + `rembg` for preprocessing; the existing `run_universal_checks()` in `base_analyzer.py` provides 4 of 5 quality metrics for confidence scoring; the `Job` ORM model already supports `type='reconstruction'` without schema changes; frontend follows the existing `(dashboard)/batch/` directory pattern.

## 1. TripoSR Integration Architecture

### Python Package

TripoSR is distributed as the `tsr` Python package (MIT license). Core API:

```python
from tsr.system import TSR

model = TSR.from_pretrained(
    "stabilityai/TripoSR",
    config_name="config.yaml",
    weight_name="model.ckpt"
)
model.renderer.set_chunk_size(8192)

# Inference
with torch.no_grad():
    scene_codes = model([image], device="cuda")  # or "cpu"

# Export to mesh
meshes = model.extract_mesh(scene_codes, resolution=256)
mesh = meshes[0]  # trimesh.Trimesh
```

**Key details:**
- `model.from_pretrained()` downloads from HuggingFace (~600MB)
- Set `TRIPOSR_MODEL_PATH` to local cache dir; set `HF_HOME` or `TRANSFORMERS_CACHE` env var
- Model loading takes ~5s on GPU, ~15s on CPU
- Inference: ~5-10s GPU (A10G), ~30-60s CPU
- Output resolution configurable: 128 (fast/coarse), 256 (default), 512 (slow/fine)
- Output is `trimesh.Trimesh` -- directly compatible with existing analysis pipeline

### Dependencies to Add

```
tsr>=1.0.0         # TripoSR model (MIT)
rembg[gpu]>=2.0    # Background removal (MIT) -- use [cpu] variant for non-GPU builds
Pillow>=10.0       # Image processing (already in requirements via trimesh)
torch>=2.0         # PyTorch (already required by SAM-3D)
```

**Note:** `torch` is already in the worker image for SAM-3D. `Pillow` is already a transitive dependency. Net new deps: `tsr`, `rembg`.

### Local vs Remote Backend

**LocalTripoSR:**
- Loads model into memory at worker startup (same as SAM-3D backbone loading in `worker.py:startup()`)
- Holds ~1.2GB GPU VRAM or ~2.4GB CPU RAM
- Suitable for: dev, on-prem enterprise, air-gapped deployments
- Risk: OOM on small Fly machines (1GB RAM). Must be opt-in via `RECONSTRUCTION_BACKEND=local`

**RemoteTripoSR (Replicate):**
- Replicate has `stability-ai/triposr` model deployed
- API: `replicate.run("stability-ai/triposr", input={"image": base64_image})`
- Returns mesh as OBJ or GLB bytes
- Cost: ~$0.02-0.05 per prediction (A40 GPU, ~10s)
- Cold start: first call ~30s, subsequent ~5-10s
- Rate limit: 100 concurrent predictions (can request increase)

**RemoteTripoSR (Modal):**
- Deploy custom container with TripoSR baked in
- More control over GPU type and scaling
- Cost: ~$0.01-0.03 per prediction (A10G, ~8s)
- No cold start if keep-warm enabled (~$0.10/hr idle)

**Recommendation:** Start with Replicate (simplest integration, TripoSR already deployed). Add Modal support later if cost or control becomes an issue. Both implement the same `ReconstructionEngine` protocol.

## 2. Image Preprocessing Pipeline

### Pipeline Steps (order matters)

1. **Format validation**: Check magic bytes for JPEG/PNG/WebP. Reject other formats.
2. **Size validation**: Reject images > 20MB.
3. **Image loading**: `PIL.Image.open()` → convert to RGB.
4. **Background removal**: `rembg.remove(image, model_name="isnet-general-use")` → RGBA with transparent background.
   - `isnet-general-use` is faster (~1s) and more accurate for objects than `u2net` (~2s).
   - First call downloads model (~170MB). Bake into Docker image.
5. **Resize**: Resize to 512x512 maintaining aspect ratio, pad with white.
6. **Center**: Ensure object is centered in frame (rembg handles this via foreground detection).
7. **Quality check**: Compute Laplacian variance for blur detection. Threshold: var > 100 = acceptable, < 100 = warn user "image may be too blurry".

### Image Selection (multi-upload)

When user uploads 2-4 images, select the best one:
1. Score each by: resolution (width * height), Laplacian variance (sharpness), foreground area after rembg (larger = better framing)
2. Pick highest composite score
3. Store all images in blob storage; use only the best for inference

### rembg Model Baking

```dockerfile
# In Dockerfile, after pip install
RUN python -c "from rembg import new_session; new_session('isnet-general-use')"
```

This downloads the model at build time and caches it in `~/.u2net/`.

## 3. Confidence Scoring Algorithm

### Metrics from Existing Code

The following functions in `backend/src/analysis/base_analyzer.py` provide metrics:

| Metric | Source Function | How to Score |
|--------|----------------|-------------|
| Watertight | `check_watertight()` / `mesh.is_watertight` | 1.0 if watertight, 0.0 if not |
| Degenerate faces | `check_degenerate_faces()` | `1.0 - (degen_count / total_faces)` |
| Self-intersections | `check_self_intersections()` | `1.0 - (intersect_count / total_faces)` |
| Face count | `len(mesh.faces)` | Sigmoid around expected range (1000-100000) |
| Surface smoothness | Custom: `np.std(face_normals_diff)` | `1.0 - min(1.0, std / threshold)` |

### Scoring Function

```python
def compute_reconstruction_confidence(mesh: trimesh.Trimesh) -> float:
    """Score reconstructed mesh quality 0.0-1.0."""
    total_faces = len(mesh.faces)
    if total_faces == 0:
        return 0.0
    
    # 1. Watertight (0.3 weight)
    w_watertight = 1.0 if mesh.is_watertight else 0.0
    
    # 2. Degenerate faces (0.2 weight)
    degen_count = int(np.sum(mesh.area_faces < 1e-10))
    w_degenerate = 1.0 - (degen_count / total_faces)
    
    # 3. Self-intersections (0.2 weight) -- sampled for speed
    try:
        intersections = mesh.ray.intersects_id(...)  # sampled check
        w_intersect = 1.0 - min(1.0, len(intersections) / (total_faces * 0.1))
    except Exception:
        w_intersect = 0.5  # Unknown -- neutral score
    
    # 4. Face count adequacy (0.15 weight)
    # TripoSR at resolution=256 produces ~50k-100k faces
    ideal_range = (5000, 200000)
    if ideal_range[0] <= total_faces <= ideal_range[1]:
        w_facecount = 1.0
    elif total_faces < ideal_range[0]:
        w_facecount = total_faces / ideal_range[0]
    else:
        w_facecount = max(0.0, 1.0 - (total_faces - ideal_range[1]) / ideal_range[1])
    
    # 5. Surface smoothness (0.15 weight)
    face_normals = mesh.face_normals
    adjacency = mesh.face_adjacency
    if len(adjacency) > 0:
        normal_diffs = np.abs(np.sum(
            face_normals[adjacency[:, 0]] * face_normals[adjacency[:, 1]], axis=1
        ))
        smoothness = float(np.mean(normal_diffs))  # 1.0 = perfectly smooth
        w_smoothness = smoothness
    else:
        w_smoothness = 0.0
    
    score = (
        0.30 * w_watertight +
        0.20 * w_degenerate +
        0.20 * w_intersect +
        0.15 * w_facecount +
        0.15 * w_smoothness
    )
    return round(max(0.0, min(1.0, score)), 3)
```

### Confidence Levels

```python
RECON_CONFIDENCE_HIGH = float(os.getenv("RECON_CONFIDENCE_HIGH", "0.7"))
RECON_CONFIDENCE_LOW = float(os.getenv("RECON_CONFIDENCE_LOW", "0.4"))

def confidence_level(score: float) -> str:
    if score >= RECON_CONFIDENCE_HIGH:
        return "high"
    elif score >= RECON_CONFIDENCE_LOW:
        return "medium"
    return "low"
```

## 4. Endpoint Design

### POST /api/v1/reconstruct

Follows the exact same pattern as the SAM-3D endpoint in `routes.py`:

```python
# In reconstruct_router.py
@router.post("/reconstruct", status_code=202)
async def reconstruct(
    images: list[UploadFile] = File(...),
    process_types: Optional[str] = Query(None),
    rule_pack: Optional[str] = Query(None),
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    # 1. Validate images (format, size, count 1-4)
    # 2. Read image bytes
    # 3. Create Job row (type='reconstruction', status='queued')
    # 4. Save images to blob storage
    # 5. Enqueue arq task
    # 6. Return 202 with job_id and poll_url
```

### GET /api/v1/reconstructions/{job_id}/mesh.stl

```python
@router.get("/reconstructions/{job_id}/mesh.stl")
async def download_mesh(
    job_id: str,
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    # 1. Load Job by ulid, verify user owns it
    # 2. Read mesh.stl from blob storage
    # 3. Return StreamingResponse with content-type application/sla
```

### Job Polling

Existing `GET /api/v1/jobs/{id}` (in `jobs_router.py`) already handles all job types. The reconstruction job result JSON extends the standard response:

```json
{
  "status": "done",
  "result": {
    "reconstruction": {
      "confidence_score": 0.82,
      "confidence_level": "high",
      "face_count": 52480,
      "mesh_url": "/api/v1/reconstructions/01HZA.../mesh.stl"
    },
    "analysis_id": "01HYB...",
    "analysis_url": "/api/v1/analyses/01HYB..."
  }
}
```

## 5. Worker Task Architecture

### Task Registration

In `worker.py`, add alongside existing tasks:

```python
from src.jobs.reconstruction_tasks import run_reconstruction_job

# In WorkerSettings.functions:
functions = [
    run_sam3d_job,
    run_batch_coordinator,
    run_batch_item,
    dispatch_webhook,
    run_reconstruction_job,  # NEW
]
```

### Task Flow

```python
async def run_reconstruction_job(ctx: dict, job_ulid: str) -> dict:
    """
    1. Load Job from DB
    2. Read images from blob storage
    3. Preprocess: validate, rembg, resize, select best
    4. Dispatch to ReconstructionEngine (local or remote)
    5. Convert result to trimesh.Trimesh
    6. Compute confidence score
    7. Save mesh to blob storage
    8. Auto-feed: call analysis_service.run_analysis() on the mesh
    9. Update Job with result (confidence + analysis_id)
    """
```

### Worker Startup Extension

If `RECONSTRUCTION_BACKEND=local`, load TripoSR model at startup (alongside SAM-3D):

```python
async def startup(ctx: dict) -> None:
    # ... existing SAM-3D loading ...
    
    # TripoSR (if local backend)
    backend = os.getenv("RECONSTRUCTION_BACKEND", "remote")
    if backend == "local":
        from src.reconstruction.local_triposr import LocalTripoSR
        ctx["reconstruction_engine"] = LocalTripoSR.load()
        logger.info("TripoSR model loaded for local inference")
```

## 6. Service Layer Design

### reconstruction_service.py

```
backend/src/services/reconstruction_service.py
├── create_reconstruction_job()  -- validate images, create Job, save blobs, enqueue
├── get_reconstruction_engine()  -- factory for Local/RemoteTripoSR based on env
└── process_reconstruction()     -- called by arq task: preprocess → infer → score → analyze
```

### reconstruction/ module

```
backend/src/reconstruction/
├── __init__.py
├── engine.py          -- ReconstructionEngine Protocol + ReconstructParams/Result dataclasses
├── local_triposr.py   -- LocalTripoSR implementation
├── remote_triposr.py  -- RemoteTripoSR (Replicate API) implementation
├── preprocessing.py   -- Image preprocessing pipeline (rembg, resize, quality check)
└── scoring.py         -- compute_reconstruction_confidence() + confidence_level()
```

## 7. Frontend Architecture

### Route Structure

```
frontend/src/app/(dashboard)/reconstruct/
├── page.tsx           -- Main reconstruction wizard page
├── components/
│   ├── ImageUploader.tsx    -- Drag-and-drop + file picker + preview thumbnails
│   ├── ReconstructionProgress.tsx  -- Progress indicator with job polling
│   ├── MeshPreview.tsx      -- Three.js viewer for reconstructed mesh + confidence badge
│   └── ConfidenceBadge.tsx  -- Green/yellow/red badge component
└── actions.ts         -- Server actions for upload + polling
```

### Existing Components to Reuse

- `MeshViewer` (from analysis dashboard) -- Three.js WebGL renderer, already handles STL loading
- `usePolling` hook (from batch dashboard) -- polls API endpoint at configurable interval
- Navigation sidebar (from dashboard layout) -- add "Image to 3D" entry
- Analysis results page -- redirect after reconstruction + analysis completes

### API Client

Existing `frontend/src/lib/api.ts` pattern:

```typescript
export async function submitReconstruction(images: File[], processTypes?: string, rulePack?: string) {
    const form = new FormData()
    images.forEach(img => form.append('images', img))
    if (processTypes) form.append('process_types', processTypes)
    if (rulePack) form.append('rule_pack', rulePack)
    
    const res = await apiClient.post('/api/v1/reconstruct', form)
    return res.data // { job_id, status, poll_url, estimated_seconds }
}
```

## 8. Storage and Retention

### Blob Directory Structure

```
/data/blobs/
├── meshes/              # Existing: analysis mesh blobs
├── batch/               # Phase 9: batch file blobs
└── reconstruct/         # Phase 10: reconstruction blobs
    └── {job_ulid}/
        ├── input/
        │   ├── image_001.jpg
        │   ├── image_002.jpg
        │   └── ...
        └── output/
            └── mesh.stl
```

### Cleanup Task

Same pattern as batch cleanup (Phase 9 D-17):

```python
async def cleanup_reconstruction_blobs(ctx: dict) -> None:
    """Delete reconstruction blobs older than RECON_FILE_RETENTION_DAYS."""
    retention_days = int(os.getenv("RECON_FILE_RETENTION_DAYS", "30"))
    # Walk /data/blobs/reconstruct/, check dir timestamps, remove expired
```

Register as periodic arq cron task:

```python
cron_jobs = [
    cron(cleanup_reconstruction_blobs, hour=3, minute=0),  # Run daily at 3am
]
```

## 9. Database Considerations

### No Schema Migration Needed

The `jobs` table already supports reconstruction:
- `job_type = 'reconstruction'` (TEXT column, no enum constraint)
- `params_json` stores: `{"image_count": 2, "best_image": "image_001.jpg", "process_types": "fdm,sla", "rule_pack": "aerospace"}`
- `result_json` stores: `{"reconstruction": {...}, "analysis_id": "...", "analysis_url": "..."}`
- `analysis_id` FK links to the resulting analysis

The only DB change: add `'reconstruction'` to any application-level enum or validation list for `job_type`. No Alembic migration required.

## 10. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| TripoSR quality insufficient for industrial parts | Low reconstruction confidence, unreliable DFM results | Confidence scoring warns users; preprocessing improves input quality; model is swappable via protocol |
| Replicate cold starts cause timeouts | Jobs fail on first invocation | 120s timeout is generous; retry logic in arq; keep-warm option on Replicate |
| rembg fails on complex backgrounds | Poor reconstruction from workbench photos | Image quality warning on low Laplacian variance; manual background removal instructions |
| Docker image bloat from model weights | Slower deploys, larger image | Optional local weights via separate Docker tag; default build uses remote backend only |
| Worker OOM with local TripoSR | Worker crashes during inference | Default to remote backend; local backend only for explicitly provisioned GPU machines |
| Reconstructed mesh too large (>200k faces) | Slow analysis, memory issues | TripoSR resolution=256 produces ~50k faces; cap at 200k with decimation if needed |

## Validation Architecture

### Testable Boundaries

1. **Preprocessing pipeline**: Input image → preprocessed 512x512 RGBA. Test: various image formats, sizes, backgrounds.
2. **ReconstructionEngine protocol**: Mock engine for testing service layer without real inference.
3. **Confidence scoring**: Known meshes → expected scores. Test: watertight mesh = high score, degenerate mesh = low score.
4. **Endpoint contract**: 202 response shape, 4xx on invalid input, polling lifecycle.
5. **Auto-feed integration**: Reconstructed mesh → analysis_service.run_analysis() → linked analysis_id.
6. **Blob storage**: Files saved/loaded at correct paths; cleanup removes expired dirs.

### Integration Test Strategy

- Use a small test image (100x100 white square with black circle) + mock ReconstructionEngine that returns a known trimesh sphere
- Verify full flow: upload → preprocess → "infer" → score → analyze → job complete with analysis_id
- No GPU required for tests (mock engine or CPU with tiny model)

## RESEARCH COMPLETE
