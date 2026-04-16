---
phase: 4
slug: shareable-urls-pdf-export
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend), vitest or jest (frontend) |
| **Config file** | backend/pytest.ini or pyproject.toml |
| **Quick run command** | `cd backend && python -m pytest tests/ -x -q --timeout=30` |
| **Full suite command** | `cd backend && python -m pytest tests/ -v --timeout=60` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/ -x -q --timeout=30`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -v --timeout=60`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04.A.1 | A | 1 | SHARE-01 | T-04A-02 | Short ID is 12-char base62 cryptographic random | unit | `pytest tests/test_share_service.py -k test_generate_short_id` | ❌ W0 | ⬜ pending |
| 04.A.2 | A | 1 | SHARE-01,02,03,04 | T-04A-01,03 | PII stripped from public view; ownership enforced | integration | `pytest tests/test_share_api.py` | ❌ W0 | ⬜ pending |
| 04.A.5 | A | 1 | SHARE-03,04 | T-04A-01 | SSR renders OG tags, no PII in HTML | manual | Browser inspect /s/{id} page source | N/A | ⬜ pending |
| 04.A.7 | A | 1 | SHARE-05 | — | Share/unshare buttons render and call API | manual | Click test in browser | N/A | ⬜ pending |
| 04.B.3 | B | 1 | PDF-01,02,03 | T-04B-01,02 | PDF renders with correct sections, no PII, semaphore limits | integration | `pytest tests/test_pdf_service.py` | ❌ W0 | ⬜ pending |
| 04.B.4 | B | 1 | PDF-01 | T-04B-02 | PDF endpoint returns application/pdf with auth | integration | `pytest tests/test_pdf_api.py` | ❌ W0 | ⬜ pending |
| 04.B.7 | B | 1 | PDF-05 | — | Download button triggers blob download | manual | Click test in browser | N/A | ⬜ pending |

*Status: ⬜ pending / ✅ green / ❌ red / ⚠ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_share_service.py` — unit tests for short ID generation + sanitizer
- [ ] `backend/tests/test_share_api.py` — integration tests for share/unshare/public-view endpoints
- [ ] `backend/tests/test_pdf_service.py` — integration tests for PDF generation + cache
- [ ] `backend/tests/test_pdf_api.py` — integration tests for PDF download endpoint
- [ ] `backend/tests/conftest.py` — shared fixtures (if not already present from Phase 3)

*Test files created during execution, not as a separate Wave 0 step.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| OG meta tags render in Slack preview | SHARE-03 | Requires real Slack/unfurl bot | Paste share URL in Slack, verify preview shows filename + verdict |
| PDF visual layout is clean and professional | PDF-02 | Visual inspection required | Open generated PDF, verify sections appear in correct order |
| Copy-to-clipboard works across browsers | SHARE-05 | Browser clipboard API varies | Test in Chrome, Firefox, Safari |
| PDF < 500 KB for typical analysis | PDF-02 | File size depends on content | Check `ls -la` on cached PDF |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
