---
phase: 10
plan: "02"
title: "Reconstruct endpoint + service + auto-feed to validate pipeline"
subsystem: backend
tags: [reconstruction, api, async, auto-feed]
dependency_graph:
  requires: ["10-01"]
  provides: ["POST /api/v1/reconstruct", "GET /api/v1/reconstructions/{id}/mesh.stl", "run_reconstruction_job arq task"]
  affects: ["worker.py", "main.py"]
tech_stack:
  added: []
  patterns: ["arq async job", "blob storage", "auto-feed pipeline"]
key_files:
  created:
    - backend/src/services/reconstruction_service.py
    - backend/src/jobs/reconstruction_tasks.py
    - backend/src/api/reconstruct_router.py
    - backend/tests/test_reconstruct_api.py
  modified:
    - backend/src/jobs/worker.py
    - backend/main.py
decisions:
  - "ULID regex validation on blob paths to prevent path traversal"
  - "Non-fatal auto-feed: reconstruction succeeds even if analysis pipeline fails"
  - "Mock AuthedUser with api_key_id=0 for system-generated analysis from arq task"
metrics:
  duration_seconds: 200
  completed: "2026-04-17T01:34:15Z"
  tasks: 5
  files_created: 4
  files_modified: 2
  tests_added: 8
  tests_passing: 8
---

# Phase 10 Plan 02: Reconstruct Endpoint + Service + Auto-Feed Summary

**One-liner:** Full backend pipeline from image upload to DFM analysis via POST /api/v1/reconstruct with arq async job, confidence scoring, and auto-feed to analysis_service.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 10-02-01 | Reconstruction service | 795aec1 | backend/src/services/reconstruction_service.py |
| 10-02-02 | Reconstruction arq task | dfb11c7 | backend/src/jobs/reconstruction_tasks.py |
| 10-02-03 | Reconstruct router | adbbdf2 | backend/src/api/reconstruct_router.py |
| 10-02-04 | Worker + router registration | 4709170 | backend/src/jobs/worker.py, backend/main.py |
| 10-02-05 | API integration tests | 7f24172 | backend/tests/test_reconstruct_api.py |

## What Was Built

1. **reconstruction_service.py**: Engine factory (local/remote TripoSR), blob storage (images + mesh), job creation with validation, mesh path retrieval with IDOR protection.

2. **reconstruction_tasks.py**: arq task that loads images from blob, selects best image, preprocesses, reconstructs via engine, scores confidence, saves mesh, and auto-feeds into analysis_service.run_analysis().

3. **reconstruct_router.py**: POST /api/v1/reconstruct (202 async) and GET /reconstructions/{id}/mesh.stl (authenticated download).

4. **Worker + main.py**: run_reconstruction_job registered in WorkerSettings.functions (now 5 total). TripoSR pre-loaded in startup when RECONSTRUCTION_BACKEND=local. Router mounted in app.

5. **8 tests**: Endpoint 202, no-images 422, too-many 400, auth 401, auto-feed analysis_id, mesh download 200, wrong-user 404, job-not-done 404.

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

1. **ULID validation on blob paths**: Added regex check (26 alphanumeric chars) before constructing file paths to prevent path traversal attacks (from threat model).
2. **Non-fatal auto-feed**: If analysis_service.run_analysis() fails after reconstruction, the job still succeeds with analysis_id=None. Logged as warning.
3. **Mock AuthedUser for auto-feed**: arq task creates AuthedUser(api_key_id=0, key_prefix="system") for the system-generated analysis call.

## Verification Results

- `from src.services.reconstruction_service import create_reconstruction_job, get_reconstruction_engine` -- OK
- `from src.jobs.reconstruction_tasks import run_reconstruction_job` -- OK
- `from src.api.reconstruct_router import router` -- OK
- `pytest tests/test_reconstruct_api.py -x -q` -- 8 passed
- `WorkerSettings.functions` length -- 5 (sam3d + 3 batch + reconstruction)
