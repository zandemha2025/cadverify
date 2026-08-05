# CADVerify — OWASP ASVS Level 2 Self-Assessment

**Date:** 2026-07-08
**Scope:** CADVerify backend (`backend/`, FastAPI/Python). Frontend, infra, and
operational controls are referenced only where the backend depends on them.
**Standard:** OWASP ASVS v4.0.3 / v5.0 Level 2 (requirements consolidated by
category).

> **This is a SELF-ASSESSMENT, not a certification.** It is an internal,
> code-grounded review by the engineering team. It has **not** been validated by
> an independent assessor. No penetration test, no SOC 2 audit, and no formal
> threat model back these claims. Items requiring independent verification are
> marked **EXTERNAL-GATE**. Every **COVERED** row cites a real `file:line` or a
> test that runs in CI; anything not directly verified is **PARTIAL**, **N/A**,
> or **EXTERNAL-GATE** — nothing is marked "pass" on faith.

All pointers are relative to `backend/` unless noted. Verified by reading source
on 2026-07-08 at base commit `0e7a7d9`.

## Legend
- **COVERED** — implemented; evidence pointer given.
- **PARTIAL** — partly implemented; the gap is stated.
- **N/A** — not applicable to this system; reason given.
- **EXTERNAL-GATE** — requires an activity outside this codebase (pen-test,
  SOC 2, independent threat model, IdP/edge configuration).

---

## V1 — Architecture, Design & Threat Modeling

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V1.1 Secure SDLC, security in CI | COVERED | CI gates: route-auth invariant (`scripts/ci/check_route_auth.py`), Sentry secret-leak grep (`tests/test_sentry_leak.py`), and now **SAST (bandit)** + **dependency-CVE (pip-audit)** in `.github/workflows/ci.yml` job `security-scan`. |
| V1.2 Authentication architecture | COVERED | Two-axis model documented in `src/auth/rbac.py:1-23` (platform `Role` vs org `OrgRole`); auth entrypoint `src/auth/require_api_key.py`. |
| V1.4 Access-control architecture (tenant isolation) | COVERED | Org boundary is a single correlated subquery `src/auth/org_context.py:60-105` (`caller_org_subquery`), threaded into every org-scoped read; proven by `tests/test_cross_tenant_isolation.py` + `tests/test_cross_tenant_isolation_w4.py`. |
| V1.5 Input/output trust boundaries | COVERED | Upload validation `src/api/upload_validation.py`; pydantic models on request bodies. |
| V1.6 Cryptographic architecture | COVERED | Argon2id for passwords/keys (`src/auth/hashing.py`), HMAC-SHA256 index/session, Fernet for connector secrets at rest. |
| V1.11 Business-logic architecture | COVERED | Kill switch `src/auth/kill_switch.py`; rate limiter `src/auth/rate_limit.py`. |
| Formal threat model / data-flow diagrams | EXTERNAL-GATE | No documented STRIDE/DFD threat model artifact exists. Requires a dedicated threat-modeling exercise. |

## V2 — Authentication

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V2.1 Password strength policy | COVERED | `src/auth/password.py:81-103` `_validate_password` (8–128 chars, ≥1 letter, ≥1 digit). |
| V2.1 Credential storage (Argon2) | COVERED | `src/auth/hashing.py:39-49` Argon2id `time_cost=3, memory_cost=65536, parallelism=4`; `:104-122` hash/verify/rehash. |
| V2.2 No user enumeration on login | COVERED | `src/auth/password.py:186-192` single generic `invalid_credentials` for unknown-user / no-password / wrong-password. |
| V2.2 Anti-automation on auth | PARTIAL | Signup is throttled (`src/auth/signup_limits.py`: 3/IP/hr, 1/email/24h) and gated by Turnstile+disposable checks on magic-link. **Gap:** `POST /auth/login` has **no brute-force rate limit** (no `@limiter.limit` on the login handler). Recommend adding a per-IP/per-account login throttle. |
| V2.3 Credential lifecycle / rotation | COVERED | API keys: mint/rotate/revoke `src/auth/keys_api.py`; opportunistic password rehash `password.py:206-210`. |
| V2.5 Credential recovery (magic link) | COVERED | `src/auth/magic_link.py`: HMAC-SHA256 token, 15-min TTL, single-use via Redis `getdel` (`:140`). |
| V2.7 Out-of-band / OIDC | COVERED | `src/auth/oidc.py`: Auth Code + PKCE (S256), single-use state+nonce (`:172-197,261-264`), id_token RS256/JWKS validation + nonce check (`:360-391`). |
| V2.8 SAML SSO | COVERED | `src/auth/saml.py`: `python3-saml` ACS validates `get_errors()`+`is_authenticated()`; group→role mapping. |
| V2.10 Service authentication (API keys) | COVERED | `cv_live_` bearer, Argon2id secret hash + HMAC-SHA256 lookup index under required ≥32-byte pepper (`src/auth/hashing.py:28-75`). |
| V2 Account deactivation / session revocation | COVERED | `session_version` bump + `is_active` checks in `require_api_key.py:74-81,116-117` and `dashboard_session.py:180-197`. |
| MFA / TOTP | N/A | Not offered as a first-party factor; enterprise MFA is delegated to the IdP (OIDC/SAML). For SSO tenants this is an **EXTERNAL-GATE** (IdP-enforced). |

## V3 — Session Management

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V3.1 Session generation | COVERED | Signed stateless session `src/auth/dashboard_session.py:64-77` (HMAC-SHA256, 128-bit tag) carrying user_id + session_version. |
| V3.2 Session binding / integrity | COVERED | Tamper → unsign fails closed `:80-102`; legacy blob cookies rejected. |
| V3.3 Session termination | COVERED | Logout clears cookie `:138-143`; logout-all bumps `session_version` (`password.py:237-245`) invalidating all outstanding cookies. |
| V3.4 Cookie attributes | COVERED | `set_session_cookie:120-135`: `Secure`, `HttpOnly`, `SameSite=Lax`, 30-day max-age enforced on unsign (`:104`). |
| V3.5 Token-based session | COVERED | session_version re-validated against DB on every authed request. |
| Note: signing library | (informational) | `itsdangerous>=2.2.0` is declared in `requirements.txt` but unused; signing is hand-rolled HMAC-SHA256. Functionally sound (constant-time compare, versioned, expiring); flagged so reviewers don't assume itsdangerous. Independent crypto review = EXTERNAL-GATE. |

## V4 — Access Control

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V4.1 General access control (deny by default) | COVERED | CI invariant `scripts/ci/check_route_auth.py` fails the build if any `/api/v1` route lacks an auth dependency; explicit `PUBLIC_ALLOWLIST`. Runs as CI job `route-auth-coverage` (154 routes verified). |
| V4.1 RBAC enforcement | COVERED | `src/auth/rbac.py:56-83` `require_role` (platform), `:120-170` `require_org_role` (org). |
| V4.2 Object-level auth / IDOR | COVERED | Org-scoping subquery on every read (`org_context.py:60-105`); adversarial proof incl. **sequential-int IDOR probes** in `tests/test_cross_tenant_isolation_w4.py` (governance `request_id`, rate/shop/material `version_id`). |
| V4.3 Multi-tenant isolation | COVERED | `tests/test_cross_tenant_isolation.py` (W1 routes) + `tests/test_cross_tenant_isolation_w4.py` (machine-inventory, manifest, catalog, ground-truth, governance, 3 libraries, part-context, RFQ). Cross-org read/list/get/update/delete/export all 404; lists never include the other org; no 404-vs-403 existence oracle. Both run against **live Postgres** in CI. |
| V4.3 Admin surface separation | COVERED | SCIM + admin routes gated by `require_org_role(admin)` (`src/api/scim.py:18`); platform `superadmin` is provisioned out-of-band only. |
| Independent access-control pen-test | EXTERNAL-GATE | No third-party authorization pen-test performed. |

## V5 — Validation, Sanitization & Encoding

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V5.1 Input validation | COVERED | Pydantic request models throughout (e.g. `password.py:63-71`, `keys_api.py:48-53`). |
| V5.1 File-upload validation | COVERED | `src/api/upload_validation.py`: magic-byte type checks (STEP/STL/IGES), cross-type rejection, triangle-count cap (`MAX_TRIANGLES` 2,000,000); streamed size cap → 413 (`routes.py:84-100`). |
| V5.3 Output encoding / injection defense (XSS) | COVERED | PDF templates now escape by default: `src/services/pdf_service.py:37-39` and `src/services/cost_pdf_service.py:37-39` use `autoescape=select_autoescape(("html","xml"))`. **Verified**: a `<script>` filename renders escaped (`&lt;script&gt;`) in a real WeasyPrint render (11 KB PDF). Fixed this cycle (bandit B701). |
| V5.3 SQL injection defense | COVERED | SQLAlchemy 2.0 ORM + `text()` with bound params everywhere. The one f-string-into-SQL (`batch_service.py:744`) interpolates an allowlist-validated column name (`:738-739`), `batch_id` bound. Key SQL uses a module-constant fragment + bound params. Confirmed by bandit (B608 findings triaged as false positives with `# nosec` + reason). |
| V5.5 Deserialization | COVERED | JSON via pydantic/stdlib; no `pickle`/`yaml.load(Loader=)` of untrusted input found. |

## V6 — Stored Cryptography

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V6.2 Algorithms | COVERED | Argon2id (`argon2-cffi==23.1.0`), HMAC-SHA256, Fernet (AES-128-CBC + HMAC). |
| V6.2 Secrets at rest | COVERED | Connector credentials encrypted with Fernet `src/services/connector_credentials_service.py:81-98`; key required in prod (`:43-55`), HMAC fingerprint index (`:73-78`). |
| V6.3 Random values | COVERED | `secrets` module for token/state/nonce minting (`hashing.py:52-58`, `oidc.py`, `magic_link.py`). |
| V6.4 Key management (rotation, HSM/KMS) | PARTIAL | Keys are env-injected (`API_KEY_PEPPER`, `CONNECTOR_SECRET_KEY`, session/magic secrets) with ≥32-byte enforcement. **Gap:** no automated rotation or KMS/HSM integration; rotation is manual redeploy. KMS adoption = EXTERNAL-GATE. |

## V7 — Error Handling & Logging

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V7.1 Log content (no secrets/PII) | COVERED | `src/auth/scrubbing.py`: structlog `scrub_processor` + Sentry `before_send` redact `cv_live_*` and `Bearer` tokens; `send_default_pii=False` (`main.py:165-173`). Proven by `tests/test_sentry_leak.py` (CI job `sentry-leak-grep`) + `tests/test_auth_scrubbing.py`. |
| V7.2 Log integrity (audit trail) | COVERED | Append-only audit events `src/services/audit_service.py:54-92`, org-scoped, fired from auth/provisioning paths. |
| V7.4 Error handling (no leakage) | COVERED | Stable `{code,message,doc_url}` envelope `src/api/errors.py`; no stack traces returned; generic 500 handler. |
| V7 Centralized log shipping / SIEM | EXTERNAL-GATE | Depends on the deployment's log pipeline (Fly → sink); not a code control. |

## V8 — Data Protection

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V8.2 Client-side data protection headers | PARTIAL | `src/api/security_headers.py:21-27`: HSTS, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, neutral Server header. **Gap:** **no Content-Security-Policy** header is emitted by the backend. (Frontend/CDN may set one — not verified here.) Recommend adding a backend CSP for API-served HTML (docs, share pages). |
| V8.3 Sensitive-data-in-use (reveal-once) | COVERED | API-key plaintext delivered once via short-lived path-scoped cookie `keys_api.py:56-65`; secret hash never returned. |
| V8.1 Data caching / at-rest | COVERED (app layer) | Secrets encrypted at rest (V6); DB-at-rest encryption is provider-managed = EXTERNAL-GATE. |

## V9 — Communications

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V9.1 TLS everywhere | COVERED | `fly.toml:27` `force_https = true`; HSTS `max-age=63072000; includeSubDomains`; all session/reveal cookies `Secure`. SAML honors `x-forwarded-proto` (`saml.py:53-54`). |
| V9.2 TLS configuration (ciphers, cert validity) | EXTERNAL-GATE | Terminated at the Fly edge; cipher-suite/cert posture is verified by external TLS scanning (e.g. SSL Labs), not this codebase. |

## V11 — Business Logic

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V11.1 Business-logic limits / anti-automation | COVERED | slowapi limiter on ~114 routes keyed by api_key→user→IP, Redis-backed, fails closed in prod without Redis (`src/auth/rate_limit.py:36-104`). |
| V11.1 Service pause / kill switch | COVERED | `src/auth/kill_switch.py` `ACCEPTING_NEW_ANALYSES` → 503 + Retry-After. |
| V11 Sequencing / anti-replay (SSO) | COVERED | OIDC state+nonce single-use (`oidc.py:261-264`); magic-link single-use. |

## V12 — Files & Resources

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V12.1 File-upload size/count limits | COVERED | Streamed size cap → 413 (`routes.py:84-100`); triangle-count cap (`upload_validation.py:135-164`). |
| V12.2 File-type validation | COVERED | Magic-byte content sniffing + cross-type rejection (`upload_validation.py:53-132`), not extension-trust. |
| V12.3 Path traversal | COVERED | Uploads handled as in-memory/temp CAD payloads keyed by generated ULIDs; no user-controlled filesystem paths in the upload/store path (server-generated names). |
| V12.5 Unintended file execution | N/A | Uploaded CAD is parsed by trimesh/gmsh as geometry, never executed. |

## V13 — API & Web Service

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V13.1 API auth on every route | COVERED | Enforced by CI invariant (`check_route_auth.py`) — see V4.1. |
| V13.2 RESTful method/versioning | COVERED | Versioned `/api/v1/*` prefixes (`main.py:234-341`); SCIM at `/scim/v2`. |
| V13.2 CORS | COVERED | `main.py:212-219`: origin regex allowlist, explicit methods/headers (no wildcard), **`allow_credentials=False`**, localhost only under `LABELING_ENABLED`. |
| V13.1 API schema exposure | PARTIAL | FastAPI default `/docs`, `/redoc`, `/openapi.json` are **publicly exposed** (not disabled or auth-gated). Low risk (no secrets in schema) but recommend gating in production. |

## V14 — Configuration

| Req (theme) | Status | Evidence / Note |
|---|---|---|
| V14.1 Build / dependency management | COVERED | Pinned security-sensitive deps in `requirements.txt`; Dependabot weekly (pip/npm/actions) `.github/dependabot.yml`; **new** CI `pip-audit` gate. |
| V14.2 Dependency CVE scanning | COVERED | `pip-audit` in CI (`security-scan` job). This cycle: **authlib 1.3.2 → 1.7.2** cleared 8 CVEs (PYSEC-2026-25/188/287/1200-1203, CVE-2026-28490); pytest CVE (PYSEC-2026-1845) waived with reason (test-only, not shipped). See `outputs/security-proof/`. |
| V14.2 SAST | COVERED | `bandit` in CI, fails build on medium+ severity. Baseline: 0 medium / 0 high after fixes (3 true positives fixed, 5 false positives suppressed with justified `# nosec`). See `outputs/security-proof/`. |
| V14.3 Prod secret enforcement | COVERED | `main.py:_assert_production_secrets:92-140` refuses to boot in prod if `SESSION_SECRET`/`DASHBOARD_SESSION_SECRET` are missing/weak or `AUTH_MODE` invalid; per-secret ≥32-byte guards. |
| V14.4 Secrets not committed | COVERED | Env-var driven; `.env.example` documents shape only, no live secrets. |
| V14 HTTP security headers | PARTIAL | See V8.2 (CSP gap). |

---

## Consolidated gaps (honest punch-list)

1. **No brute-force throttle on `POST /auth/login`** (V2.2). Signup is limited; login is not. *Recommend a per-IP + per-account login rate limit.*
2. **No Content-Security-Policy header** from the backend (V8.2 / V14). Other hardening headers are present.
3. **`/docs`, `/redoc`, `/openapi.json` publicly exposed** (V13.1). Low sensitivity; recommend gating in production.
4. **Session signing is hand-rolled HMAC** (V3) while `itsdangerous` is declared-but-unused — functionally sound but warrants an independent crypto review.
5. **No automated key rotation / KMS** (V6.4) — secrets are env-injected and rotated by redeploy.
6. **Turnstile not on password signup** (V2.2) — present on magic-link only.

## Items that are EXTERNAL-GATE by nature (cannot be closed in code)

- Independent penetration test (V-level verification, V4/V-full).
- SOC 2 / formal compliance audit.
- Formal, documented threat model (STRIDE/DFD).
- TLS cipher/cert posture at the edge (V9.2).
- Provider-managed database at-rest encryption (V8.1).
- IdP-enforced MFA for SSO tenants (V2 MFA).
- Centralized log shipping / SIEM (V7).

## Evidence index
- Tenant isolation: `backend/tests/test_cross_tenant_isolation.py`, `backend/tests/test_cross_tenant_isolation_w4.py` (live-Postgres; run in CI `backend` job).
- SAST/CVE baselines: `outputs/security-proof/` (bandit + pip-audit real output).
- CI gates: `.github/workflows/ci.yml` jobs `route-auth-coverage`, `sentry-leak-grep`, `security-scan`, `backend`.
