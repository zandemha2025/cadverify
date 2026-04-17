---
phase: 10
plan: "01"
subsystem: reconstruction
tags: [image-to-mesh, triposr, preprocessing, scoring]
dependency_graph:
  requires: []
  provides: [reconstruction-engine, preprocessing-pipeline, confidence-scoring]
  affects: [10-02-api-endpoint, 10-03-frontend]
tech_stack:
  added: [tsr, rembg, Pillow]
  patterns: [ABC protocol, lazy model loading, thread-pool inference, Replicate API polling]
key_files:
  created:
    - backend/src/reconstruction/__init__.py
    - backend/src/reconstruction/engine.py
    - backend/src/reconstruction/preprocessing.py
    - backend/src/reconstruction/scoring.py
    - backend/src/reconstruction/local_triposr.py
    - backend/src/reconstruction/remote_triposr.py
    - backend/tests/test_reconstruction.py
  modified:
    - backend/requirements.txt
decisions:
  - ABC protocol for ReconstructionEngine (mirrors JobQueue pattern)
  - Laplacian blur detection via scipy convolution (avoids OpenCV dependency)
  - AST-based protocol compliance tests (avoids importing tsr/torch in CI)
metrics:
  duration: 223s
  completed: "2026-04-17T01:28:56Z"
  tasks: 6
  files: 8
---

# Phase 10 Plan 01: Reconstruction Engine + Preprocessing + Confidence Scoring Summary

ReconstructionEngine ABC with LocalTripoSR (GPU, lazy-loaded) and RemoteTripoSR (Replicate API with polling/timeout) backends; rembg preprocessing pipeline with blur detection and best-image selection; 5-metric weighted confidence scoring (watertight, degenerate, intersections, face count, smoothness).

## Task Completion

| Task | Title | Commit | Key Files |
|------|-------|--------|-----------|
| 10-01-01 | ReconstructionEngine protocol | 6d4e254 | engine.py, __init__.py |
| 10-01-02 | Image preprocessing pipeline | c96bb5d | preprocessing.py |
| 10-01-03 | Confidence scoring algorithm | 14f4b55 | scoring.py |
| 10-01-04 | LocalTripoSR backend | c7919e4 | local_triposr.py |
| 10-01-05 | RemoteTripoSR backend (Replicate) | 1995991 | remote_triposr.py |
| 10-01-06 | Tests and dependencies | 10611af | test_reconstruction.py, requirements.txt |

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

1. Used ABC (not Protocol) for ReconstructionEngine to match existing JobQueue pattern in protocols.py
2. Implemented blur detection via scipy.ndimage.convolve with Laplacian kernel instead of OpenCV to avoid adding cv2 dependency
3. Used AST parsing for engine protocol compliance tests so tsr/torch are not required in CI

## Verification

- All 6 import checks pass
- 24/24 pytest tests pass (0.03s)

## Known Stubs

None. All functions contain real implementations. LocalTripoSR and RemoteTripoSR require their respective backends (GPU/API token) at runtime but are fully implemented.

## Threat Flags

None. No new network endpoints introduced (engine module only; API endpoint is plan 10-02). Replicate API token handling includes header redaction per threat model.
