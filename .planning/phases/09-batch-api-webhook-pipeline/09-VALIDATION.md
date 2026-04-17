---
phase: 9
slug: batch-api-webhook-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && python -m pytest tests/ -x -q --timeout=30` |
| **Full suite command** | `cd backend && python -m pytest tests/ -v --timeout=60` |
| **Estimated runtime** | ~45 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/ -x -q --timeout=30`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -v --timeout=60`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 45 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-A-01 | A | 1 | BATCH-01 | T-09-01 | ZIP bomb rejection at >100:1 ratio | unit | `pytest tests/test_batch_service.py -k test_zip_bomb` | ❌ W0 | ⬜ pending |
| 09-A-02 | A | 1 | BATCH-02 | — | N/A | unit | `pytest tests/test_batch_service.py -k test_manifest_parsing` | ❌ W0 | ⬜ pending |
| 09-A-03 | A | 1 | BATCH-01 | — | N/A | unit | `pytest tests/test_batch_models.py` | ❌ W0 | ⬜ pending |
| 09-B-01 | B | 1 | BATCH-03 | T-09-02 | HMAC signature verified before processing | unit | `pytest tests/test_webhook_service.py -k test_hmac_signing` | ❌ W0 | ⬜ pending |
| 09-B-02 | B | 1 | BATCH-04 | — | N/A | integration | `pytest tests/test_batch_router.py -k test_progress` | ❌ W0 | ⬜ pending |
| 09-B-03 | B | 1 | BATCH-02 | — | N/A | unit | `pytest tests/test_batch_tasks.py -k test_coordinator` | ❌ W0 | ⬜ pending |
| 09-B-04 | B | 1 | BATCH-03 | — | N/A | unit | `pytest tests/test_webhook_service.py -k test_retry` | ❌ W0 | ⬜ pending |
| 09-C-01 | C | 2 | BATCH-05 | — | N/A | manual | Browser test | N/A | ⬜ pending |
| 09-C-02 | C | 2 | BATCH-06 | — | N/A | unit | `pytest tests/test_batch_service.py -k test_concurrency_limit` | ❌ W0 | ⬜ pending |
| 09-C-03 | C | 2 | BATCH-04 | — | N/A | integration | `pytest tests/test_batch_router.py -k test_csv_export` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending / ✅ green / ❌ red / ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_batch_service.py` — stubs for BATCH-01, BATCH-02, BATCH-06
- [ ] `backend/tests/test_batch_models.py` — model validation tests
- [ ] `backend/tests/test_batch_router.py` — endpoint integration tests for BATCH-04
- [ ] `backend/tests/test_batch_tasks.py` — arq task unit tests for BATCH-02
- [ ] `backend/tests/test_webhook_service.py` — HMAC signing + retry tests for BATCH-03
- [ ] `backend/tests/conftest.py` — batch-specific fixtures (mock arq pool, test DB session)

*Existing pytest infrastructure covers framework install.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Frontend batch dashboard renders progress | BATCH-05 | React/Next.js UI components | Open batch dashboard, upload ZIP, verify progress bar updates |
| Frontend drill-down to individual analysis | BATCH-05 | UI navigation flow | Click batch item, verify analysis detail loads |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
