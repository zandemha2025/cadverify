# CadVerify — Enterprise Buyer + Security / Compliance Audit

**Lens:** What an enterprise / aerospace procurement + security review (Zoox, Aramco) requires that CadVerify lacks.
**Auditor stance:** Inspected the real code, ran the live stack (uvicorn :8000 + Postgres, Next.js :3000), exercised endpoints, and read every file in `backend/src/auth`, `backend/src/db`, deploy scaffolding (`Dockerfile`, `fly.toml`, `charts/`, `cadverify-enterprise/`), and the frontend session gate.
**Date:** 2026-07-01
**Bottom line:** The *authentication core for a single-user SaaS* is genuinely solid and better than typical demoware. But the *enterprise/on-prem/compliance story is a scaffold* — SAML is wired-but-unproven and its config path is broken, there is **no multi-tenant org model**, **no encryption at rest**, **no SOC2/pen-test artifacts**, and **no SLA/observability**. Several concrete security defects (webhook SSRF, no security headers, unbounded SSO key minting, non-revocable sessions) would surface in any competent procurement security review. **This does not yet pass a Zoox/Aramco vendor security gate.**

Evidence paths are absolute. "Live:" means I hit the running server.

---

## 1. REAL — works, verified how

### R1. Email+password auth, end-to-end (the one login that fully works locally)
- Argon2id via `argon2-cffi`, `time_cost=3, memory_cost=65536, parallelism=4` — `/Users/nazeem/Desktop/developer/cadverify/backend/src/auth/hashing.py:39-49`.
- Generic failure for unknown-user / OAuth-only-account / wrong-password (no user enumeration, no provider leak) — `backend/src/auth/password.py:182-188`.
- Server-side password policy (8–128, letter+digit), opportunistic re-hash on parameter upgrade — `password.py:79-101,192-197`.
- **Live-verified** (prior orchestrator run + my probes): `GET /auth/me` → 200 with cookie, 401 without. Tests green: `pytest tests/test_auth_password.py` passes (1 skipped needs Postgres).

### R2. API-key auth — HMAC index + Argon2id secret, fails closed
- Token = `cv_live_<prefix8>_<secret32>`; DB lookup by HMAC-SHA256 index under `API_KEY_PEPPER`, secret verified with Argon2id — `hashing.py:61-88`, `backend/src/auth/require_api_key.py:54-78`.
- Pepper **required**: missing/short pepper → 500 `server_config`, not an auth bypass — `hashing.py:28-36`, `require_api_key.py:57-66`.
- Full key lifecycle scoped to the owning user: list/create/rotate/revoke/rename, all `WHERE user_id = :u` — `backend/src/auth/keys_api.py`. Plaintext delivered once via 60-second `cv_mint_once` cookie.

### R3. Dashboard session — signed, expiring, httpOnly, fails safe
- `dash_session` = base64(`{uid}.{iat}` + HMAC-SHA256/16B) under `DASHBOARD_SESSION_SECRET`; 30-day hard expiry enforced on unsign — `backend/src/auth/dashboard_session.py:28-49`.
- Secret must base64-decode to ≥32 bytes or the process refuses to sign (fails safe) — `dashboard_session.py:21-25`.
- Cookie is httpOnly, Secure (prod), SameSite=Lax — `dashboard_session.py:52-62`, mirrored first-party in `frontend/src/lib/session.ts`.
- **Real server-side gate:** the authed app shell is a *server* component that calls `verifySession()` → backend `/auth/me` → redirect `/login` on failure — `frontend/src/app/(app)/layout.tsx`, `frontend/src/lib/dal.ts`. This is not client-side theater.

### R4. RBAC — 3 hierarchical roles, enforced on every sensitive route
- `viewer(1) < analyst(2) < admin(3)`, dependency-composed with `require_api_key` — `backend/src/auth/rbac.py`.
- Applied broadly: `/validate*` and cost routes require analyst; history/jobs/pdf require viewer; `/api/v1/admin/*` require admin — grep across `backend/src/api/*`.
- **Live-verified:** `GET /api/v1/admin/users` → 401, `GET /api/v1/admin/audit-log` → 401 `auth_missing` without credentials.
- **CI guardrail (real):** `.github/workflows/ci.yml` runs `scripts/ci/check_route_auth.py` asserting *every* `/api/v1/*` handler carries an auth dependency, plus a Sentry-leak grep for `cv_live_`.

### R5. Audit log — append-only table, admin query + CSV export
- `audit_log` table with timestamp/user/action/resource/detail_json/ip/file_hash indexes — `backend/src/db/models.py:359-383`, migration `0006_create_audit_log.py`.
- Admin `GET /api/v1/admin/audit-log` with time-range (90-day cap), user/action filters, cursor pagination, and `format=csv` export — `backend/src/api/admin_routes.py:172-213`, `backend/src/services/audit_service.py`.
- Events fired on signup, login, api_key.created, user.role_changed, SAML user.provisioned — `password.py`, `models.py:138-146`, `admin_routes.py:147-156`, `saml.py:124-132`.

### R6. Per-user data isolation on queries
- Analyses/jobs/history are all filtered `WHERE user_id = :self`; others' resources return **404 not 403** (no existence leak) — `backend/src/api/history.py:39,88-91`, `backend/src/services/job_service.py:96-110`.

### R7. Secret scrubbing in logs + Sentry
- structlog processor + Sentry `before_send` redact `cv_live_*` tokens and `Authorization`/`x-api-key` headers — `backend/src/auth/scrubbing.py`, wired in `backend/main.py:68-91`. CI proves no `cv_live_` reaches a captured Sentry payload.

### R8. Deployment hardening basics
- Non-root container user, multi-stage build, runtime-only deps — `backend/Dockerfile`.
- HTTPS forced at the edge (`force_https = true`) — `backend/fly.toml`, `frontend/fly.toml`.
- Helm chart with liveness/readiness probes on `/health`, TLS-capable ingress, SAML config/secret templates — `charts/cadverify/templates/*`.
- On-prem bundle exists: `cadverify-enterprise/` (docker-compose + `.env.example` + `docs/ENTERPRISE-SETUP.md`) and AUTH_MODE gating (google|saml|hybrid) — `backend/main.py:154-162`.

---

## 2. STUBBED / FRAGILE — looks done, isn't

### S1. SAML is wired but UNPROVEN — 100% mocked, not active, never IdP-tested  ⚠️ P0
- `backend/tests/test_saml.py:1-5` states outright: *"All python3-saml internals are mocked so tests run without a real IdP."* The tests assert routing (login 302, ACS 303, metadata returns XML) but **never exercise real assertion signature validation, xmlsec1, cert trust, replay/InResponseTo, audience restriction, or clock skew** — the exact things that make SAML secure.
- **Live:** `GET /auth/saml/metadata` → **404** because the running app is `AUTH_MODE=google` (SAML router not mounted). SAML has never run in this deployment.
- `cadverify-enterprise/docs/ENTERPRISE-SETUP.md` claims Okta/Azure AD/PingFederate are "tested providers." **No evidence of any real SSO round-trip exists.** This is a correctness claim that needs real-expert validation (see V1).

### S2. SAML config env-var substitution is BROKEN — the documented path doesn't work  ⚠️ P0
- `saml/settings.json.template` uses `${SAML_SP_ENTITY_ID}`, `${SAML_IDP_X509_CERT}`, etc., and `cadverify-enterprise/.env.example` + `ENTERPRISE-SETUP.md` instruct operators to set those env vars.
- But `_load_saml_settings()` does a plain `json.load()` with **no `os.path.expandvars` / substitution** — `backend/src/auth/saml.py:84-92`. An operator who follows the docs ships literal `"${SAML_SP_ENTITY_ID}"` strings into python3-saml → invalid SP/IdP config, SSO fails. The template and loader disagree.

### S3. Every SSO/passwordless login mints a NEW API key — unbounded key growth  ⚠️ P1
- SAML ACS mints a key on **every** callback — `saml.py:116-120` (docstring says "if none present," code has no such check).
- Google OAuth callback mints a "Default" key on **every** login — `backend/src/auth/oauth.py:78-81`.
- Magic-link verify mints a key on **every** use — `backend/src/auth/magic_link.py:139-141`.
- Result: each repeated SSO login leaves an orphan, never-revoked, fully-valid credential. This is both an operational mess and a credential-sprawl security finding.

### S4. SAML has no group→role mapping and no deprovisioning
- Provisioned users are hard-coded `viewer` (`saml.py:102-134`); there is **no mapping from IdP groups/attributes to analyst/admin**. Admins must be promoted manually via the DB/admin API.
- No SCIM, no JIT-disable, no deprovisioning when an employee leaves the IdP — orphaned access.

### S5. Google OAuth + OAuth-state CSRF are dev-defaulted
- `GOOGLE_CLIENT_ID/SECRET` default to `"dummy"` — `oauth.py:25`. Not exercised locally (needs real Google creds).
- Starlette `SessionMiddleware` (which persists OAuth `state`/`nonce` for CSRF protection) uses `secret_key=os.environ.get("SESSION_SECRET", "dev-only")` — `backend/main.py:136-139`. If `SESSION_SECRET` is unset in a deploy, OAuth CSRF protection is signed with a public constant.

### S6. No HTTP security headers anywhere  ⚠️ P1
- **Live:** backend `/health` response carries **no** `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, or `Permissions-Policy`; it does leak `server: uvicorn`.
- Frontend has no `headers()` in `frontend/next.config.ts` and `frontend/vercel.json` is `{"framework":"nextjs"}` only.
- Exposure: clickjacking, MIME-sniffing, TLS downgrade, referrer leakage. Trivial to add; currently absent.

### S7. Webhook delivery is a Server-Side Request Forgery (SSRF) vector  ⚠️ P1
- Batch `webhook_url` is taken from a form field with **no validation** (`backend/src/api/batch_router.py:41,70`) and POSTed by the worker via `httpx.AsyncClient` straight to that URL — `backend/src/services/webhook_service.py:145-170`.
- No scheme/host allowlist, no block on private/link-local ranges (`127.0.0.1`, `169.254.169.254`, `10./172./192.168.`). An `analyst` can make the server sign-and-POST to internal services or the cloud metadata endpoint. Classic SSRF; a security review will flag it immediately.

### S8. Rate limiting silently degrades to per-process memory
- slowapi uses `REDIS_URL` if set, else `memory://`, with in-memory fallback if Redis drops — `backend/src/auth/rate_limit.py`. The web process runs `uvicorn --workers 2` (`backend/Dockerfile`, `fly.toml`) and multiple machines — so without Redis, each worker/machine counts independently and global limits are not enforced. Abuse/brute-force protection is only real when Redis is up.

### S9. Audit log is not tamper-evident and swallows write failures
- `log_action()` wraps everything in `try/except` and logs-and-continues on failure — `audit_service.py:64-86`. A DB/audit outage is invisible to the caller (the action still succeeds, unlogged).
- No hash chaining, no WORM/append-only storage guarantee, no external SIEM sink. An admin or DB owner can `DELETE FROM audit_log`. This is **not** sufficient for SOC2/ITAR chain-of-custody.

### S10. Helm SAML secret ships empty; config drift in env examples
- `charts/cadverify/templates/secret-saml.yaml` sets `sp-key.pem: ""` / `sp-cert.pem: ""` — signed AuthnRequests/metadata won't work out of the box.
- Root `/.env.example` lists `SESSION_SECRET` / `HMAC_SECRET`, but the code requires `API_KEY_PEPPER` + `DASHBOARD_SESSION_SECRET` (absent from that file). An operator copying it gets a backend that 500s on the first auth call. (`cadverify-enterprise/.env.example` is closer but still omits `DASHBOARD_SESSION_SECRET`.)

### S11. Sessions can now be revoked by version
- Resolved in Cycle 6: dashboard cookies remain HMAC tokens, but carry `users.session_version`. `/auth/logout-all`, superadmin `revoke-sessions`, and account deactivation increment the user-row version, so older cookies are rejected as `session_revoked`.

---

## 3. MISSING — gaps to be a credible enterprise / aerospace platform

### M1. No multi-tenant organization model (architectural)  ⚠️ P0
- Zero hits for `tenant` / `organization` / `org_id` / `workspace` / `team_id` in `backend/src`. There is only `users` (and each user is an island). No org boundary, no org-scoped sharing of analyses/history, no org-admin vs super-admin, no seat/entitlement management, no per-customer data segregation.
- `admin` is **global** — an admin can list/patch **all** users and read **all** audit rows (`admin_routes.py`). In a real enterprise deployment shared across customers, that is a cross-tenant data-exposure model. Enterprises expect: one tenant = one company, users grouped under it, data shared within and isolated across tenants. Retrofitting this touches every table (needs `org_id` FKs) and every query.

### M2. No SOC 2 / ISO 27001 / pen-test / questionnaire artifacts  ⚠️ P0
- No security policies, no controls matrix, no pen-test report, no SOC2 (even Type I), no completed CAIQ/SIG. CI has **no** SAST (bandit/semgrep/CodeQL), **no** dependency-vuln scanning (pip-audit/trivy/snyk), **no** secret scanning (gitleaks/trufflehog) — only weekly Dependabot version bumps (`.github/dependabot.yml`). A procurement security team will have nothing to review, which is itself a gating fail.

### M3. No encryption at rest  ⚠️ P0
- Zero hits for `encrypt` / `kms` / `vault` / `pgcrypto` in app/deploy config. Mesh blobs are written plaintext to `MESH_BLOB_DIR` (`backend/src/services/job_service.py:19-30`); `result_json` (derived geometry/DFM/cost) sits unencrypted in Postgres; no field-level encryption, no envelope encryption, no KMS. **ITAR/CUI data handling requires encryption at rest** — this is disqualifying for Aramco/defense-adjacent Zoox workloads until addressed.

### M4. No enforced TLS to the database
- `docker-compose.yml`, `cadverify-enterprise/docker-compose.yml`, and the Helm DB secret use `postgresql://...@postgres:5432/...` with **no `sslmode`**. `backend/src/db/engine.py:30-38` only honors TLS if the operator adds `sslmode=require` to `DATABASE_URL`. Default intra-cluster DB traffic is cleartext.

### M5. No data-residency / air-gap proof / ITAR / FIPS story
- "Air-gapped" is a Helm `pullPolicy: Never` (`charts/cadverify/values-enterprise.yaml`) plus a docs section — not a verified control. No export-control classification, no US-persons access enforcement, no data-residency guarantees, no FIPS-validated crypto module (Argon2/HMAC come from `argon2-cffi`/`hashlib`, not a FIPS boundary).

### M6. No data lifecycle: DSAR / erasure / retention enforcement
- Only `DELETE /api/v1/keys/{id}` exists; there is **no** user-data-deletion / GDPR right-to-erasure endpoint, no analysis/blob purge job. `AUDIT_RETENTION_DAYS` is an env var with **no enforcing job**; blobs are never garbage-collected (only a `# Called by cleanup task after retention` comment in `batch_service.py:390`, with no scheduler). Enterprises require documented retention + deletion-on-request.

### M7. No SLA / observability / DR posture
- Observability is **only** Sentry + `/health` (grep for prometheus/opentelemetry/otel/datadog/metrics = none in app code). No metrics, no distributed tracing, no alerting, no status page, no documented SLO/RTO/RPO, no backup/restore or DR runbook. Enterprise contracts require an SLA and evidence of monitoring behind it.

### M8. No MFA, no password reset, no account lockout
- Grep for `reset.?password|forgot|mfa|totp|2fa|otp|lockout|failed_login` in `backend/src` = **none**. Password accounts have no second factor, no self-serve reset, and no login-attempt lockout (and rate-limit is Redis-dependent per S8). SSO shifts MFA to the IdP, but SSO isn't proven (S1) and password auth is the only working path.

### M9. No SCIM / automated provisioning-deprovisioning
- SAML JIT creates viewers on login (S4) but there is no SCIM endpoint to create/disable/delete users driven by the customer's IdP. Deprovisioning an offboarded employee is manual — a standard audit finding.

### M10. "CAD never leaves" is a deployment promise, not an enforced control
- Partly true: the **sync** analysis path holds raw CAD in memory only and persists derived `result_json` + a SHA-256 `mesh_hash` (not raw geometry) — `backend/src/services/analysis_service.py:47-49,85-130`; the demo path persists nothing.
- **But:** the async SAM-3D path writes the **raw mesh to disk unencrypted** (`routes.py:427` → `job_service.save_mesh_blob`); public sharing can expose an analysis (`is_public` / `share_short_id` in `models.py`, `/s/` router); and nothing technically prevents a cloud-hosted deployment from egressing. There is no DLP, no per-tenant no-egress enforcement, and no proof the pipeline/models don't phone home. It holds only if the customer self-hosts air-gapped — which circles back to S1/M3/M5 not being production-proven.

### M11. Frontend gates on session, not role
- The `(app)` layout enforces a valid session but does not check `role` (`frontend/src/app/(app)/layout.tsx`). Admin surfaces rely solely on backend 403s. Defense-in-depth (hide admin UI from non-admins) is absent; not a data breach (backend enforces) but a review nit.

---

## 4. Needs real-human / expert validation (do NOT self-certify)

- **V1 — SAML correctness against a real IdP.** *What to show:* stand up `AUTH_MODE=saml` with a real Okta/Azure AD/PingFederate app, real SP signing cert, real signed assertions. *What to ask a security engineer:* does it correctly reject unsigned assertions, tampered signatures, replayed responses (InResponseTo), wrong-audience, and expired/clock-skewed assertions? Currently 100% mocked (S1) — **no correctness claim can be made.**
- **V2 — Independent penetration test** by an accredited firm (must cover the SSRF S7, session model S11, RBAC/tenant boundary M1). Required for any enterprise security questionnaire.
- **V3 — SOC 2 Type I/II readiness** assessment by a qualified auditor; today there are zero controls artifacts (M2).
- **V4 — ITAR/export-control legal review** of data handling and US-persons access if targeting defense-adjacent Zoox / Aramco workloads (M3, M5).

---

## 5. What blocks a Zoox / Aramco procurement gate (prioritized)

**P0 — hard blockers (no deal without these):**
1. No SOC2 / pen-test / security-questionnaire artifacts (M2).
2. No multi-tenant org isolation; `admin` is global (M1).
3. No encryption at rest for CAD blobs or Postgres (M3).
4. SAML unproven against a real IdP *and* its documented config path is broken (S1, S2).
5. No SLA / observability / DR evidence (M7).

**P1 — will be flagged and must be fixed before go-live:**
6. Webhook SSRF (S7).
7. No HTTP security headers (S6).
8. Non-revocable 30-day sessions; no MFA / reset / lockout (S11, M8).
9. No DSAR / retention enforcement; blobs never purged (M6).
10. Unbounded API-key minting on every SSO/passwordless login (S3).
11. TLS-to-DB not enforced by default (M4).

**P2 — credibility / hygiene:**
12. Env-example config drift causing first-boot 500s (S10).
13. No SCIM / deprovisioning (M9); no IdP group→role mapping (S4).
14. Audit log not tamper-evident (S9); no SAST/dep-scan/secret-scan in CI (M2).
15. No FIPS-validated crypto boundary (M5).

---

## 6. One-paragraph verdict

CadVerify's **single-user authentication core is real and above-average** — Argon2id, HMAC-indexed API keys that fail closed, signed expiring sessions with a genuine server-side gate, consistently-enforced RBAC with a CI guardrail, and an audit table with admin export. That is a credible foundation. But **"enterprise-ready" is currently a scaffold, not a product:** SAML is entirely mocked and its config substitution is broken, there is no organization/tenant model (so "admin" is global), there is no encryption at rest, no SOC2/pen-test posture, no SLA/observability, and live defects (webhook SSRF, missing security headers, non-revocable sessions, unbounded SSO key minting) that a competent security review will catch on day one. The "CAD never leaves" claim is a self-hosting promise rather than an enforced technical control. **A Zoox/Aramco security gate would stop this at the questionnaire stage.** Closing P0+P1 is on the order of a multi-month, security-led workstream — the org-model (M1) and encryption/compliance items (M2/M3) are the long poles.
