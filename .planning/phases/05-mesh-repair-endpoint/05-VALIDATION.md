---
phase: 5
slug: mesh-repair-endpoint
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend), jest/vitest (frontend) |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && python -m pytest tests/test_repair_service.py tests/test_repair_endpoint.py -x -q` |
| **Full suite command** | `cd backend && python -m pytest -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/test_repair_service.py tests/test_repair_endpoint.py -x -q`
- **After every plan wave:** Run `cd backend && python -m pytest -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-A-01 | A | 1 | REPAIR-01 | — | N/A | unit | `pytest tests/test_repair_service.py::test_tier1_fixes_normals -x` | ❌ W0 | ⬜ pending |
| 05-A-02 | A | 1 | REPAIR-01 | — | N/A | unit | `pytest tests/test_repair_service.py::test_tier2_pymeshfix_fallback -x` | ❌ W0 | ⬜ pending |
| 05-A-03 | A | 1 | REPAIR-01 | — | Face-count cap returns 413 | unit | `pytest tests/test_repair_service.py::test_face_count_cap -x` | ❌ W0 | ⬜ pending |
| 05-A-04 | A | 1 | REPAIR-01 | — | Timeout returns original analysis | unit | `pytest tests/test_repair_service.py::test_timeout_graceful -x` | ❌ W0 | ⬜ pending |
| 05-A-05 | A | 1 | REPAIR-02 | — | N/A | integration | `pytest tests/test_repair_endpoint.py::test_repair_returns_b64_stl -x` | ❌ W0 | ⬜ pending |
| 05-A-06 | A | 1 | REPAIR-02 | — | N/A | integration | `pytest tests/test_repair_endpoint.py::test_repair_cache_hit -x` | ❌ W0 | ⬜ pending |
| 05-B-01 | B | 2 | REPAIR-03 | — | N/A | manual | Frontend visual check | — | ⬜ pending |
| 05-B-02 | B | 2 | REPAIR-03 | — | N/A | manual | Frontend visual check | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_repair_service.py` — stubs for REPAIR-01 (tier1, tier2, timeout, face-cap)
- [ ] `backend/tests/test_repair_endpoint.py` — stubs for REPAIR-02 (endpoint integration, cache hit, b64 response)
- [ ] `backend/tests/fixtures/non_watertight.stl` — test fixture: small non-watertight STL for repair tests

*Existing pytest infrastructure covers framework install.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| "Attempt repair" button visibility | REPAIR-03 | Frontend conditional rendering | Load analysis with NON_WATERTIGHT issue -> button appears. Load clean analysis -> button hidden. |
| Before/after comparison layout | REPAIR-03 | Visual UX check | Click "Attempt repair" -> verify two AnalysisDashboard panels render side by side |
| Download repaired file | REPAIR-03 | Browser download behavior | Click "Download Repaired File" -> verify .stl file downloads with correct name |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
