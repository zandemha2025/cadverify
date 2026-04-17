# Phase 10: Image-to-Mesh Pipeline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 10-image-to-mesh-pipeline
**Mode:** --auto (all decisions auto-selected with recommended defaults)
**Areas discussed:** Model choice, Single vs multi-image, GPU/inference infrastructure, Mesh quality assessment, Endpoint shape, Storage, Frontend UX, Confidence scoring

---

## Reconstruction Model

| Option | Description | Selected |
|--------|-------------|----------|
| TripoSR | MIT license, single-image, ~300M params, CPU+GPU, 5-60s inference | ✓ |
| InstantMesh | Multi-view required, higher quality but more complex pipeline | |
| Trellis | Larger model, slower, newer/less documented | |
| OpenLRM | Less community support, fewer deployment examples | |

**User's choice:** [auto] TripoSR (recommended default)
**Notes:** MIT license is critical for enterprise customers. Single-image input matches the legacy part photography use case. Model abstracted behind protocol for future swapping.

---

## Single vs Multi-Image

| Option | Description | Selected |
|--------|-------------|----------|
| Single-image primary | TripoSR uses one image; accept up to 4, store extras for future | ✓ |
| Multi-image required | Require 3+ images for better quality; limits accessibility | |
| Multi-image fusion | Use multi-view model (InstantMesh) for all inputs | |

**User's choice:** [auto] Single-image primary (recommended default)
**Notes:** Engineers often have only one photo of a legacy part. Accepting 1-4 images future-proofs API.

---

## GPU / Inference Infrastructure

| Option | Description | Selected |
|--------|-------------|----------|
| External inference API | Replicate/Modal/RunPod; pay-per-use; no GPU on Fly machines | ✓ |
| Fly GPU machines | Always-on A100; $2.50/hr; simplest but expensive | |
| CPU-only local | 30-60s per inference; viable for low volume only | |

**User's choice:** [auto] External inference API with local fallback (recommended default)
**Notes:** External API scales to zero and handles burst for Saudi Aramco volume. Local backend available for air-gapped enterprise.

---

## Mesh Quality Assessment

| Option | Description | Selected |
|--------|-------------|----------|
| Multi-metric scoring | 5 geometric metrics weighted into 0-1 score | ✓ |
| Binary pass/fail | Watertight check only; simple but loses nuance | |
| ML-based scoring | Train a quality predictor; accurate but needs training data | |

**User's choice:** [auto] Multi-metric scoring (recommended default)
**Notes:** Reuses existing universal geometry checks from base_analyzer.py. No new analysis code needed.

---

## Endpoint Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Async 202 + polling | Same pattern as SAM-3D; return job ID immediately | ✓ |
| Sync with timeout | Block until reconstruction completes; simpler client code | |
| WebSocket streaming | Real-time progress; complex but better UX | |

**User's choice:** [auto] Async 202 + polling (recommended default)
**Notes:** Reconstruction takes 10-60s; too slow for sync. Matches existing SAM-3D pattern exactly.

---

## Storage

| Option | Description | Selected |
|--------|-------------|----------|
| Fly volume /data/blobs/ | Consistent with Phase 7/9 pattern; 30-day retention | ✓ |
| Object storage (Tigris/R2) | Better for scale; more setup | |
| Ephemeral (no storage) | Delete after analysis; saves space but no re-download | |

**User's choice:** [auto] Fly volume with 30-day retention (recommended default)
**Notes:** Matches existing blob storage conventions. Longer retention than batch (30 vs 7 days) because reconstruction is harder to reproduce.

---

## Frontend UX

| Option | Description | Selected |
|--------|-------------|----------|
| 4-step wizard | Upload -> processing -> preview -> analysis; guided flow | ✓ |
| Single-page inline | Upload area on existing analyze page; minimal navigation | |
| Separate app section | Full reconstruction management interface | |

**User's choice:** [auto] 4-step wizard (recommended default)
**Notes:** Wizard keeps user informed through multi-step process. Reuses existing analysis dashboard for results.

---

## Confidence Scoring

| Option | Description | Selected |
|--------|-------------|----------|
| Geometric quality metrics | 5 metrics, 0.7/0.4 thresholds, never blocks analysis | ✓ |
| Simple face count check | Quick but misses quality issues | |
| Comparison-based | Compare to known-good reconstructions; needs reference data | |

**User's choice:** [auto] Geometric quality metrics with thresholds (recommended default)
**Notes:** Never blocks analysis -- user uploaded a photo because they have no CAD. Any analysis is better than none.

---

## Claude's Discretion

- Exact external inference API provider selection (Replicate vs Modal vs RunPod)
- rembg model variant (u2net vs isnet-general-use)
- Image quality heuristic details (blur detection threshold)
- Preprocessing pipeline order
- Three.js preview component for reconstruction result
- Poll interval optimization
- Confidence score normalization formula
- Worker memory management for local inference
- Cleanup task scheduling

## Deferred Ideas

- Multi-view reconstruction (InstantMesh/Zero123++) -- future enhancement when models mature
- Batch image-to-mesh -- combine with Phase 9 batch pipeline
- Model fine-tuning on manufacturing parts -- needs training data
- Auto mesh repair after reconstruction -- combine with Phase 5
- Video-to-mesh from turntable rotation -- consumer-friendly but complex
- Reconstructed vs original CAD comparison -- quality validation
