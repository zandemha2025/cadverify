# Phase 7: Async SAM-3D - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 07-async-sam-3d
**Mode:** --auto (all decisions auto-selected by Claude)
**Areas discussed:** Task queue library, SAM-3D model weights, Worker architecture, Async submit endpoint, Job status polling, Embedding cache backend

---

## Task Queue Library

| Option | Description | Selected |
|--------|-------------|----------|
| arq 0.27 + JobQueue protocol | Asyncio-native, ~700 LOC, already wired in docker-compose and fly.toml. Wrap in protocol for future swap. | ✓ |
| TaskIQ | Emerging async-native alternative. Less production mileage, no existing integration in project. | |
| Celery | Heavyweight, sync-first, complex ops. Wrong shape for async FastAPI + one job type. | |

**User's choice:** [auto] arq 0.27 + JobQueue protocol (recommended default)
**Notes:** ROADMAP flagged arq-vs-TaskIQ for recheck. arq maintenance-mode is mitigated by protocol wrapper. Project already has arq wired into docker-compose worker service and Fly process groups. No compelling reason to switch at beta scale.

---

## SAM-3D Model Weights

| Option | Description | Selected |
|--------|-------------|----------|
| SAM-2 Hiera Small (~150 MB) | Good quality/size balance. Fits 1.2 GB image budget. Apache-2.0, Meta official. | ✓ |
| SAM-2 Hiera Tiny (~40 MB) | Smallest, fastest. Lower segmentation quality. | |
| SAM-2 Hiera Large (~2.5 GB) | Best quality. Blows image size budget. Needs GPU for reasonable speed. | |
| SAM-2 Hiera Base (~350 MB) | Middle ground. May strain image budget. | |

**User's choice:** [auto] SAM-2 Hiera Small (recommended default)
**Notes:** ROADMAP flagged weight size/license/provenance. SAM-2 is Apache-2.0 (Meta, facebookresearch/segment-anything-2). No license encumbrance. Pre-baked into image per Pitfall 6.

---

## Worker Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Model at startup + thin adapter tasks + ack-on-completion | Load model once, process jobs as thin adapters calling segment_sam3d(), always-on worker. | ✓ |
| Model loaded per-job | Simpler code but 30s+ model load per job. Anti-pattern per PITFALLS. | |
| Fly Machines ad-hoc spawning | Spawn machine per job. More complex ops, auth, lifecycle management. | |

**User's choice:** [auto] Model at startup + thin adapter tasks (recommended default)
**Notes:** Existing `_backbone` singleton pattern in pipeline.py already supports this. Pitfall 6 prescribes always-on worker with ack-on-completion.

---

## Async Submit Endpoint

| Option | Description | Selected |
|--------|-------------|----------|
| Sync analysis first, then enqueue SAM-3D | User gets immediate DFM results; SAM-3D is layered enhancement. 202 response includes both. | ✓ |
| Fully async (both analysis + SAM-3D) | User waits for everything. Worse UX -- blocks for 30-60s+. | |
| SAM-3D only (no sync analysis in 202) | Missing core DFM results in initial response. | |

**User's choice:** [auto] Sync analysis first, then enqueue SAM-3D (recommended default)
**Notes:** SAM-02 specifies this flow. Idempotent by (analysis_id, job_type).

---

## Job Status Polling

| Option | Description | Selected |
|--------|-------------|----------|
| GET /api/v1/jobs/{id} polling + separate /result | Lightweight status checks; full result on separate endpoint. | ✓ |
| Webhooks | Push-based notification on completion. v2 feature (SDK-04). | |
| Long polling / SSE | Real-time status updates. Over-engineered for beta. | |

**User's choice:** [auto] Polling + separate /result (recommended default)
**Notes:** SAM-03 specifies polling endpoint. Webhooks deferred to v2.

---

## Embedding Cache Backend

| Option | Description | Selected |
|--------|-------------|----------|
| Fly volume (/data/blobs/sam3d_cache) | Persistent across worker restarts. Phase 6 already provisions volume. | ✓ |
| S3-compatible (Tigris/R2) | More durable. Overkill for beta cache. | |
| /tmp filesystem | Ephemeral. Lost on restart per Pitfall 6. | |

**User's choice:** [auto] Fly volume (recommended default)
**Notes:** Pitfall 6 says no /tmp. Phase 6 D-09 already provisions Fly volume at /data.

---

## Claude's Discretion

- arq WorkerSettings configuration details (max_jobs, job_timeout, health_check_interval)
- Convenience endpoint for segmentation results via analysis ID
- SAM-2 checkpoint download URL for Dockerfile
- Redis connection pool configuration for arq
- Worker health check endpoint shape
- Mesh bytes retrieval strategy in worker
- SAM-3D result serialization format in jobs.result_json

## Deferred Ideas

- Webhooks for job completion (v2 SDK-04)
- Frontend async UX (progress indicators, SAM-3D badge)
- GPU-backed synchronous SAM-3D (v2 ADV-01)
- Job queue for PDF rendering
- Worker autoscaling
- SAM-2 Hiera Large model
- Job cancellation
