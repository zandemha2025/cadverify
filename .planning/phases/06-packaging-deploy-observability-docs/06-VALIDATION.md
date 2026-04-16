---
phase: 6
slug: packaging-deploy-observability-docs
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend), Docker CLI (integration), curl (smoke) |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && pytest tests/ -x -q` |
| **Full suite command** | `cd backend && pytest tests/ -v && docker compose -f docker-compose.yml config --quiet` |
| **Estimated runtime** | ~30 seconds (pytest) + ~5 min (Docker build) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && pytest tests/ -x -q`
- **After every plan wave:** Run full suite + Docker compose config validation
- **Before `/gsd-verify-work`:** Full suite must be green + Docker build succeeds
- **Max feedback latency:** 30 seconds (unit tests), 5 min (Docker build)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| TBD | 06.A | 1 | PKG-01 | integration | `docker build -t cadverify-api backend/ && docker image inspect cadverify-api --format '{{.Size}}'` | pending |
| TBD | 06.A | 1 | PKG-02 | integration | `docker run cadverify-api arq --help` (worker entrypoint works) | pending |
| TBD | 06.A | 1 | PKG-08 | file-check | `docker run cadverify-api cat /app/NOTICE` | pending |
| TBD | 06.B | 1 | PKG-03 | integration | `docker compose config --quiet` (valid compose file) | pending |
| TBD | 06.B | 1 | PKG-04 | file-check | `grep -q '\[processes\]' backend/fly.toml` | pending |
| TBD | 06.B | 1 | PKG-05 | config | Verify `DATABASE_URL` and `DATABASE_URL_DIRECT` in .env.example | pending |
| TBD | 06.C | 1 | PKG-06 | file-check | Verify `NEXT_PUBLIC_API_BASE` in frontend/.env.example | pending |
| TBD | 06.C | 1 | PKG-07 | CI | `grep -q 'alembic upgrade' .github/workflows/ci.yml` | pending |
| TBD | 06.D | 2 | OBS-01 | unit | `cd backend && pytest tests/test_sentry_leak.py -q` | pending |
| TBD | 06.D | 2 | OBS-02 | unit | `grep -q 'request_id' backend/main.py` (request-ID middleware) | pending |
| TBD | 06.D | 2 | OBS-03 | unit | `cd backend && pytest tests/test_health.py -q` (health check with mocked failures) | pending |
| TBD | 06.E | 2 | DOC-01 | integration | `curl -s localhost:8000/scalar \| grep -q 'scalar'` | pending |
| TBD | 06.E | 2 | DOC-02 | unit | Assert error response contains `{code, message, doc_url}` keys | pending |

---

## Wave Execution Order

| Wave | Plans | Gate |
|------|-------|------|
| 1 | 06.A, 06.B, 06.C | Docker builds, compose validates, fly.toml valid, CI expanded |
| 2 | 06.D, 06.E | Observability wired, docs served, errors structured |

---

*Validation strategy created: 2026-04-15*
