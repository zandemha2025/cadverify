# Auth Architect — work log

Status: **DONE** (spec written; no blocker). `auth-spec.md` is complete.

## Verified facts (read from the repo, not assumed)
- Backend session primitive exists and is reusable: `backend/src/auth/dashboard_session.py`
  (`COOKIE_NAME="dash_session"`, `sign`/`unsign` HMAC over `{user_id}.{iat}`,
  30-day, `require_dashboard_session` -> user_id, env `DASHBOARD_SESSION_SECRET`
  base64 >=32B). Argon2id in `hashing.py` (`_ph()`: t=3, m=65536, p=4).
- `users` table (migrations 0001 + 0005) has NO password column ->
  migration 0007 required (`password_hash TEXT NULL`). Head is 0006 (linear).
- Frontend ALREADY uses the first-party `dash_session` cookie proxied to the
  backend in `(app)/keys/actions.ts` (reads `cookies().get("dash_session")`,
  forwards `Cookie:` header). The spec generalizes this proven pattern.
- Platform gating today = client-side localStorage API key (`RequireKey` +
  `auth-provider.tsx` `cadverify_api_key`). To be replaced by server gating.
- `/api/v1/validate/cost` uses `require_role(Role.analyst)` -> `require_api_key`
  (Bearer). Extended in-place to also accept the session cookie (§2.6) so the
  conftest `dependency_overrides[require_api_key]` keeps ~537 tests green.
- Next.js 16: Middleware is renamed **Proxy** (`src/proxy.ts`,
  `export default proxy` + `config.matcher`); `cookies()` is async. Confirmed in
  `frontend/node_modules/next/dist/docs/.../proxy.md` + `authentication.md`.

## Environment probes (run this session)
- `pg_isready -h localhost -p 5432` -> accepting connections.
- Role `cadverify` and DB `cadverify` DO NOT EXIST. Present DBs: arcus_dev,
  perp_dev, postgres. Superuser role `nazeem` (trust auth). Spec §1.2 creates a
  dedicated `cadverify` role+DB (no collision; arcus_dev/perp_dev untouched).
- `backend/.venv`: argon2-cffi 23.1.0, alembic 1.14.0, sqlalchemy 2.0.36, asyncpg present.

## Key design decisions (made so builders make none)
1. Same-origin Next.js proxy holds the httpOnly `dash_session` cookie; browser
   never calls the backend directly for authed work. (CORS allow_credentials
   stays False; works identical local + prod.)
2. Email+password endpoints return the signed token in the JSON body; the Next
   route handler (server-side) sets the first-party httpOnly cookie. Avoids
   cross-domain Set-Cookie rewriting. Token never reaches client JS.
3. Three enforcement layers: proxy.ts (presence) + DAL verifySession() (calls
   /auth/me) + backend credential check. Argon2id passwords, generic login error
   (no enumeration), duplicate email -> 409 (no OAuth-account takeover).
4. Abuse controls gated for local: disposable hard-reject always on (in-process);
   Redis limits only if REDIS_URL set; Turnstile only if TURNSTILE_ENABLED+secret.
5. OAuth/magic/SAML kept wired, explicitly deploy-gated (see spec §5 table).

## Not blocked
All local prerequisites are satisfiable with the documented DB setup + two
generated secrets (DASHBOARD_SESSION_SECRET, API_KEY_PEPPER). No external
provider secret is needed for the email+password path. If a builder cannot
`CREATE ROLE`/`CREATE DATABASE`, spec §1.2 gives a no-DDL fallback
(`nazeem@localhost/cadverify_dev`).
