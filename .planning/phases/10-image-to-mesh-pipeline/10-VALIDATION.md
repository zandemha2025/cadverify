---
phase: 10
slug: image-to-mesh-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend), vitest (frontend) |
| **Config file** | `backend/pytest.ini` / `frontend/vitest.config.ts` |
| **Quick run command** | `cd backend && python -m pytest tests/test_reconstruction.py -x -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~30 seconds (backend), ~15 seconds (frontend) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/test_reconstruction.py -x -q`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-A-01 | A | 1 | IMG-01 | — | N/A | unit | `pytest tests/test_reconstruction.py::test_preprocessing_pipeline -x` | ❌ W0 | ⬜ pending |
| 10-A-02 | A | 1 | IMG-01 | — | N/A | unit | `pytest tests/test_reconstruction.py::test_engine_protocol -x` | ❌ W0 | ⬜ pending |
| 10-A-03 | A | 1 | IMG-03 | — | N/A | unit | `pytest tests/test_reconstruction.py::test_confidence_scoring -x` | ❌ W0 | ⬜ pending |
| 10-B-01 | B | 1 | IMG-02 | — | Auth required for reconstruct endpoint | integration | `pytest tests/test_reconstruct_api.py::test_reconstruct_endpoint_202 -x` | ❌ W0 | ⬜ pending |
| 10-B-02 | B | 1 | IMG-04 | — | N/A | integration | `pytest tests/test_reconstruct_api.py::test_auto_feed_to_validate -x` | ❌ W0 | ⬜ pending |
| 10-B-03 | B | 1 | IMG-02 | — | Auth prevents unauthorized mesh download | integration | `pytest tests/test_reconstruct_api.py::test_mesh_download -x` | ❌ W0 | ⬜ pending |
| 10-C-01 | C | 2 | IMG-05 | — | N/A | e2e | Manual: verify image upload wizard flow | — | ⬜ pending |

---

## Wave 0 Requirements

- [ ] `backend/tests/test_reconstruction.py` — stubs for preprocessing, engine protocol, confidence scoring
- [ ] `backend/tests/test_reconstruct_api.py` — stubs for endpoint contract, auto-feed, mesh download
- [ ] `backend/tests/conftest.py` — mock `ReconstructionEngine` fixture returning a known trimesh sphere
- [ ] `backend/tests/fixtures/test_image.jpg` — small test image (100x100 white with centered black circle)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Image upload wizard UI flow | IMG-05 | Frontend UX requires browser interaction | 1. Navigate to /reconstruct 2. Upload test image 3. Verify progress indicator 4. Verify mesh preview with confidence badge 5. Verify redirect to analysis dashboard |
| Three.js mesh preview renders correctly | IMG-05 | Visual rendering cannot be automated | Verify 3D mesh rotates, confidence badge shows correct color |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
