# Auth Security Audit — orchestrator-run (2026-06-30)

The Phase-4 Security-Auditor **agent failed to serialize** its structured output (StructuredOutput
retry cap exceeded) — a harness serialization failure, NOT a work failure. All three builders
(architect, backend, frontend) completed and self-verified. The orchestrator ran the security audit
directly against the live stack (uvicorn :8000 + real local Postgres; Next.js :3000). **Verdict: PASS.**

## Checks (run by the orchestrator)

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Real accounts, Argon2id, no plaintext | **PASS** | DB: `auth_provider=password`, hash `$argon2id$v=19$m=65536,t=3,p…`, `plaintext_present=false`. |
| 2 | Real DB-backed sessions | **PASS** | login → signed `dash_session`; `GET /auth/me` **200** with cookie, **401** without. |
| 3 | Platform gated server-side (no bypass) | **PASS** | `POST /api/v1/validate/cost` **401** without session, **200** with session (make_now=mjf, routing present). Frontend logged-out `/analyze` → **307 → /login**; `/login` 200. |
| 4 | Front-door restructured | **PASS** | marketing `/` shows **Log in / Sign up**, no "Get API Key"; no anonymous demo; API keys moved to `/settings/developer`. |
| 5 | (bonus) Weak session secret refused | **PASS** | backend 500s if `DASHBOARD_SESSION_SECRET` doesn't base64-decode to ≥32 bytes — fails safe. |
| 6 | No regression | **PASS** | builders' suite 551 passed / 1 pre-existing test now fixed / 5 env-skipped; frontend `npm run build` + `tsc` green. |
| 7 | Honesty: OAuth/magic-link/SAML | **PASS** | present + wired but correctly NOT claimed to work locally (need deploy creds); not faked. |

## Real latent bugs the build caught + fixed (not theater)
- **`greenlet` missing from the venv** — SQLAlchemy async needs it for ANY real DB connection; the ~537 tests never caught it because they mock sessions. Added to `requirements.txt`.
- **`alembic/env.py` missing `begin_transaction()`** — migrations ran then silently rolled back on a fresh DB. Fixed (canonical async-alembic pattern). Would have broken every fresh deploy.

## Notes
- Two transient red flags during my audit (a 500, a 422) were **my own harness errors** (a too-weak test secret; malformed JSON from shell escaping), not product bugs — confirmed by re-running cleanly.
- Seeded local account for testing: `nazeem+livetest@anodeadvisory.com` / `Passw0rd123`.
- The local stack now requires Postgres + `DASHBOARD_SESSION_SECRET`; `scripts/run-local-app.sh` was updated to set these (persisted secret) + run migrations + open the marketing front door.
