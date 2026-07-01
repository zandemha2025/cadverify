# Backend Email + Password Auth — Build & Acceptance Notes

Author: Backend Auth Builder. Date: 2026-06-29. Status: **DONE / VERIFIED against real local Postgres.**

Implements the email+password credential, server-side sessions, and the DB per
`outputs/auth/auth-spec.md` §1–§2. Reuses the existing `dashboard_session` (HMAC
session), `hashing` (Argon2id), `users` model, and `rbac`. OAuth / magic-link /
SAML stay mounted, provider-cred-gated (not exercised locally).

---

## 1. DATABASE

### DATABASE_URL used (local dev)
```
DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify
```
Created a dedicated dev role + database (does not touch `arcus_dev` / `perp_dev`,
which belong to other projects and have their own `users` tables):
```bash
psql -h localhost -p 5432 -d postgres -c "CREATE ROLE cadverify LOGIN PASSWORD 'localdev';"
psql -h localhost -p 5432 -d postgres -c "CREATE DATABASE cadverify OWNER cadverify;"
```

### Migration 0007 (adds the credential)
`backend/alembic/versions/0007_add_password_hash_to_users.py` (`down_revision="0006"`)
adds a nullable `password_hash TEXT` column to `users`. OAuth/SAML/magic users keep
it NULL; no new table. ORM mirror added to `backend/src/db/models.py::User`.

Applied with:
```bash
cd backend
DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify .venv/bin/python -m alembic upgrade head
```
`\d users` now shows `password_hash | text | nullable`; `alembic_version = 0007`.

### Two environment fixes required to actually run (both real, both committed)
1. **`greenlet` was missing from `backend/.venv`** — SQLAlchemy's async engine
   requires it for ANY real DB connection. The ~537 tests never caught this
   because they mock all sessions. Installed `greenlet==3.2.5`. Added `greenlet`
   to `backend/requirements.txt` so prod/CI install it (asyncpg + SQLAlchemy
   async both need it).
2. **`backend/alembic/env.py` never committed migrations** — its async
   `run_migrations_online()` omitted `context.begin_transaction()`, so the DDL
   ran and then rolled back on connection close (the DB stayed empty even though
   alembic logged "Running upgrade …"). This latent bug was invisible because
   the migration tests mock `alembic.op` and never run a live `alembic upgrade`.
   Fixed by wrapping `context.run_migrations()` in `with context.begin_transaction():`
   (the canonical async-alembic pattern). Without this, NO migration on a fresh
   DB persists.

---

## 2. ENDPOINTS (`backend/src/auth/password.py`, mounted `prefix="/auth"`, UNCONDITIONAL)

| Method | Path | Auth | Behavior |
|---|---|---|---|
| POST | `/auth/signup` | none | Validate email + password policy, disposable hard-reject, `create_password_user` (Argon2 hash), → `200 {user, session}` or `409 email_taken` / `400 weak_password`/`invalid_email`/`email_domain_blocked`. |
| POST | `/auth/login` | none | Generic `401 invalid_credentials` for unknown email / no-password (OAuth) / wrong password (no enumeration). Success → `200 {user, session}`. Opportunistic Argon2 re-hash. |
| POST | `/auth/logout` | none | Stateless HMAC session — nothing to revoke. `clear_session_cookie` (harmless) → `200 {ok:true}`. |
| GET | `/auth/me` | `dash_session` cookie | `require_dashboard_session` → `unsign` → user; → `200 {id,email,role,auth_provider}` or `401 dashboard_auth_required`. |

**Session transport:** signup/login return the signed token in the JSON `session`
field. The Next.js server (not browser JS) sets the first-party httpOnly
`dash_session` cookie; every later request is verified by `unsign`. No
cross-domain `Set-Cookie`. Token = `dashboard_session.sign(user_id)` (30-day HMAC).

**Password policy (server-enforced, `_validate_password`):** 8–128 chars, ≥1
letter AND ≥1 digit. `400 weak_password` otherwise.

**Argon2id (`hashing.hash_password`/`verify_password`/`password_needs_rehash`):**
reuses the existing `PasswordHasher` (`t=3, m=65536, p=4`). Hash stored inline
with a per-call random salt. Plaintext/hash are never logged or returned.

### Platform gating — `require_api_key` session fallback (`src/auth/require_api_key.py`)
When there is no `Authorization: Bearer cv_live_...`, it now falls back to the
`dash_session` cookie: `unsign` → `AuthedUser(api_key_id=0, key_prefix="session",
role=lookup_user_role(uid))`. Zero route changes — every `require_role`/
`require_api_key` route (incl. `POST /api/v1/validate/cost`, history, batch) now
accepts the session. Cookie access is defensive (`getattr`) so the existing
unit tests' fake request objects still raise `auth_missing` cleanly.

### Abuse controls — local gating (auth-spec §2.5)
- Disposable **hard-reject**: always on (pure in-process list).
- Per-IP Redis limit: only if `REDIS_URL` is set (unset locally → skipped).
- Turnstile: not applied to the password path (deploy-gated; magic-link still
  requires it, unchanged).

---

## 3. REAL CAPTURED CURL TRANSCRIPT (live uvicorn on 127.0.0.1:8000, real Postgres)

Server launched with:
```bash
DASHBOARD_SESSION_SECRET=<openssl rand -base64 32> API_KEY_PEPPER=<openssl rand -base64 32> \
ACCEPTING_NEW_ANALYSES=true LABELING_ENABLED=1 \
DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify \
backend/.venv/bin/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

### 1) SIGNUP → 200 (session token in body, role=analyst)
```
$ curl -is :8000/auth/signup -H 'content-type: application/json' -d '{"email":"nazeem+livetest@anodeadvisory.com","password":"Passw0rd123"}'
HTTP/1.1 200 OK
content-type: application/json

{"user":{"id":5,"email":"nazeem+livetest@anodeadvisory.com","role":"analyst"},
 "session":"NS4xNzgyNzc2MDM1LmdNP-HpX04oesdUsOhXzeg"}
```

### 2) LOGIN → 200 (new session token)
```
$ curl -s :8000/auth/login -H 'content-type: application/json' -d '{"email":"nazeem+livetest@anodeadvisory.com","password":"Passw0rd123"}'
{"user":{"id":5,"email":"nazeem+livetest@anodeadvisory.com","role":"analyst"},
 "session":"NS4xNzgyNzc2MDM2Lt-OgNlVBpA8mTO9AofY6No"}
```

### 3) GET /auth/me WITH cookie → 200 user
```
$ curl -is :8000/auth/me -H 'Cookie: dash_session=NS4xNzgyNzc2MDM2Lt-OgNlVBpA8mTO9AofY6No'
HTTP/1.1 200 OK
{"id":5,"email":"nazeem+livetest@anodeadvisory.com","role":"analyst","auth_provider":"password"}
```

### 4) GET /auth/me WITHOUT cookie → 401 (rejected)
```
$ curl -is :8000/auth/me
HTTP/1.1 401 Unauthorized
{"code":"dashboard_auth_required","message":"Dashboard session required.","doc_url":".../errors#dashboard_auth_required"}
```

### 5) PROTECTED POST /api/v1/validate/cost WITHOUT cookie → 401 auth_missing (rejected)
```
$ curl -is -X POST :8000/api/v1/validate/cost -F 'file=@<part>.stl' -F 'qty=50' -F 'region=US'
HTTP/1.1 401 Unauthorized
{"code":"auth_missing","message":"Authorization: Bearer cv_live_... header or dashboard session required","doc_url":".../errors#auth_missing"}
```

### 6) PROTECTED POST /api/v1/validate/cost WITH session cookie → 200 (authed via session)
```
$ curl -is -X POST :8000/api/v1/validate/cost -H 'Cookie: dash_session=NS4x...6No' -F 'file=@<part>.stl' -F 'qty=50' -F 'region=US'
HTTP/1.1 200 OK
x-ratelimit-limit: 60
x-ratelimit-remaining: 59
content-type: application/json
{"filename":"...EK_0BD1_ECU_Firewall_mount.stl","status":"OK","geometry":{"volume_cm3":66.79,"watertight":true,"face_count":1586}, ... full glass-box cost decision ...}
```
(200 + rate-limit headers ⇒ the request passed `require_role(Role.analyst)` →
`require_api_key` via the `dash_session` cookie, `api_key_id=0` session sentinel.)

### 7) LOGOUT → 200
```
$ curl -is -X POST :8000/auth/logout
HTTP/1.1 200 OK
set-cookie: dash_session=""; ... Max-Age=0; Path=/; SameSite=lax
{"ok":true}
```

### DB proof — Argon2 hash, NO plaintext
```
$ psql ... -d cadverify -c "SELECT id,email,email_lower,auth_provider,role,left(password_hash,40),length(password_hash) FROM users WHERE id=5;"
 id | email                              | email_lower               | auth_provider | role    | left                                     | length
  5 | nazeem+livetest@anodeadvisory.com  | nazeem@anodeadvisory.com  | password      | analyst | $argon2id$v=19$m=65536,t=3,p=4$c2YFwY601 |     97

$ psql ... -tAc "SELECT password_hash LIKE '%Passw0rd123%', password_hash LIKE '$argon2id$%' FROM users WHERE id=5;"
 f | t        -- contains_plaintext = false, is_argon2id = true
```
(`email_lower` has the `+livetest` tag stripped by `normalize_email`; the raw
`email` column retains it. A reusable local test login is seeded:
`nazeem+livetest@anodeadvisory.com` / `Passw0rd123`.)

---

## 4. TESTS

New `backend/tests/test_auth_password.py` (14 tests): Argon2 hash is `$argon2id$`
and never plaintext; verify roundtrip + never-raises-on-garbage; password policy
(weak/strong); email shape; `require_api_key` session-cookie fallback
(accept valid / reject tampered / reject none); and one self-contained async
integration flow against real Postgres (signup → duplicate 409 → weak 400 →
wrong-password 401 → login 200 → me 200 → me-no-cookie 401 → protected-with-cookie
200 `api_key_id=0` → protected-no-cred 401 → logout 200), with cleanup.

```
$ DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify .venv/bin/python -m pytest tests/test_auth_password.py -q
14 passed in 0.35s
```

Full suite (no regressions from this work):
```
$ DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify .venv/bin/python -m pytest -q
551 passed, 1 failed, 5 skipped in 454.96s
```
The **1 failure is NOT caused by this backend work**:
`test_frontend_api_config.py::test_public_docs_use_live_urls_and_route_shims_exist`
asserts `frontend/src/app/auth/signup/page.tsx` exists. `git status` shows that
file as `D` (deleted) — the concurrent **frontend** builder is restructuring
`app/auth/*` → `app/(auth)/*` per auth-spec §3.7. The test reads only frontend
files; I changed zero frontend files. It fails on the current working tree
independent of the auth backend. (The frontend builder's task updates this test
or its referenced paths.)

---

## 5. FILES CHANGED (backend only — no commit)
- ADD `backend/alembic/versions/0007_add_password_hash_to_users.py`
- ADD `backend/src/auth/password.py` (signup/login/logout/me router)
- ADD `backend/tests/test_auth_password.py`
- EDIT `backend/src/db/models.py` (`User.password_hash`)
- EDIT `backend/src/auth/hashing.py` (`hash_password`/`verify_password`/`password_needs_rehash`)
- EDIT `backend/src/auth/models.py` (`create_password_user`/`get_login_credentials`/`get_user_public`/`update_password_hash`)
- EDIT `backend/src/auth/require_api_key.py` (`dash_session` cookie fallback)
- EDIT `backend/main.py` (`include_router(password_router, prefix="/auth")`, unconditional)
- EDIT `backend/alembic/env.py` (commit migrations — `begin_transaction`)
- EDIT `backend/requirements.txt` (add `greenlet`)

---

## 6. HONEST DEPLOY-GATED (NOT claimed to work locally)
| Capability | Local? | Still requires |
|---|---|---|
| Email+password signup/login/logout/me | **YES** | Postgres + `DASHBOARD_SESSION_SECRET` |
| Session gating of the platform (require_api_key cookie path) | **YES** | as above |
| Google OAuth (`/auth/google/*`) | NO | `GOOGLE_CLIENT_ID/SECRET`, redirect URI, `DASHBOARD_ORIGIN`, `AUTH_MODE=google\|hybrid` |
| Magic-link (`/auth/magic/*`) | NO | `RESEND_API_KEY`, `REDIS_URL`, `MAGIC_LINK_SECRET`, `TURNSTILE_SECRET` |
| SAML SSO (`/auth/saml/*`) | NO | `AUTH_MODE=saml\|hybrid`, `python3-saml`, IdP metadata |
| Turnstile on signup / Redis rate-limits | OFF locally (gated) | `TURNSTILE_SECRET`+`TURNSTILE_ENABLED=true` / `REDIS_URL` |

The OAuth/magic/SAML routers remain mounted (AUTH_MODE default `google`), so the
integration points stay wired — they simply need the credentials above to run.
