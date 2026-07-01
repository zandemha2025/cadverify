# Frontend Auth + Gating — Build & Acceptance Notes

Author: Frontend Auth + Gating Builder. Date: 2026-06-29. Status: **DONE / VERIFIED end-to-end against the real local backend + Postgres.**

Builds the Marketing → Log in / Sign up → gated Platform structure on the
glass-box design system, against the email+password backend (Wave 2). The whole
`(app)` platform now requires a real server-side session; there is no anonymous
demo and API keys are demoted to Settings → Developer.

---

## 1. The protection mechanism (how the gate actually works)

Three layers, all server-side. A logged-out user can never reach the workspace.

1. **Edge gate — `frontend/src/proxy.ts`** (Next 16's renamed Middleware).
   Optimistic presence check of the httpOnly `dash_session` cookie on every
   gated path (`/analyze /cost /batch /history /analyses /label /reconstruct
   /keys /settings /design-system`). No cookie → `307` redirect to
   `/login?next=<path>` BEFORE the page renders. Authed users hitting
   `/login` / `/signup` are bounced to `/analyze`. (HMAC can't be validated at
   the edge — Next forbids crypto/DB there — so this is the cheap check.)

2. **Authoritative gate — `frontend/src/lib/dal.ts` + the `(app)` server layout.**
   `verifySession()` forwards the cookie to the backend `GET /auth/me`, which
   validates the HMAC signature + 30-day expiry and returns the user (or 401).
   The `(app)/layout.tsx` is now an **async server component** that calls
   `verifySession()` and redirects to `/login` on any invalid/missing session —
   so even if the edge check were bypassed, the layout refuses to render.

3. **Backend gate.** Every authed API call is relayed (see §4) with the cookie;
   the backend's `require_api_key` session fallback rejects anything without a
   valid `dash_session`. The cost call returns `401` with no cookie (proven §6).

The session cookie is **httpOnly** (no JS access), `SameSite=Lax`, `Path=/`,
30-day `Max-Age`, and `Secure` in production (`NODE_ENV==="production"`; off on
http://localhost so the dev cookie isn't dropped). The session token is **never**
returned to browser JS or stored in localStorage — the Next server owns it.

---

## 2. Routes & files ADDED

| File | Purpose |
|---|---|
| `frontend/src/lib/session.ts` | First-party cookie helpers (`setSession`/`clearSession`/`getSessionToken`); server-only via `next/headers`. |
| `frontend/src/lib/dal.ts` | `getUser()` / `verifySession()` → backend `/auth/me`, memoized with React `cache`. |
| `frontend/src/proxy.ts` | Server-side route protection (the edge gate). |
| `frontend/src/app/api/auth/login/route.ts` | POST `{email,password}` → backend `/auth/login`, sets the httpOnly cookie, returns `{user}` only. |
| `frontend/src/app/api/auth/signup/route.ts` | POST `{email,password}` → backend `/auth/signup`, sets the cookie (auto-login). |
| `frontend/src/app/api/auth/logout/route.ts` | POST → clears the cookie (+ best-effort backend logout). |
| `frontend/src/app/api/proxy/[...path]/route.ts` | **Same-origin authed proxy** — forwards `/api/proxy/*` → backend `/api/v1/*` with `Cookie: dash_session=<token>`, relaying status/body/rate-limit headers verbatim. Makes the whole platform session-authed. |
| `frontend/src/app/(auth)/login/page.tsx` | Glass-box email+password login form → `/api/auth/login`. |
| `frontend/src/app/(app)/settings/developer/page.tsx` | API keys live here now (moved from `/keys`). |

## 3. Routes & files CHANGED

| File | Change |
|---|---|
| `frontend/src/app/(app)/layout.tsx` | Now an async **server** component: `verifySession()` gate → `AuthProvider user={…}` + `AppShell`. |
| `frontend/src/app/layout.tsx` | Removed the localStorage `AuthProvider` from root (auth context now lives in the `(app)` layout only). |
| `frontend/src/components/ui/auth-provider.tsx` | Rewritten: holds the session `user` + `signOut()` (POST `/api/auth/logout` → hard-nav `/login`). No more `hasKey`/localStorage. |
| `frontend/src/components/ui/topbar.tsx` | Account menu shows `user.email` + role; "Settings · Developer" + working "Sign out". Removed the "Local demo · no key" pill. |
| `frontend/src/components/ui/sidebar.tsx` | "API keys" → "Developer" → `/settings/developer`. |
| `frontend/src/app/(auth)/signup/page.tsx` | Rewritten: PRIMARY = email+password → `/api/auth/signup` → `/analyze`. Google + magic-link kept below a divider (deploy-gated). Heading "Create your account". |
| `frontend/src/components/ui/public-chrome.tsx` | Removed `useAuth`/`hasKey`. `PrimaryCta` = "Sign up" → `/signup`; header shows **Log in** + **Sign up**. ("Get API Key" front door removed.) |
| `frontend/src/app/page.tsx` | Removed the anonymous `#demo` `PartWorkspace` section + the "Run a real part" hero button; replaced with a "Sign up to run your part" CTA. |
| `frontend/src/app/method/page.tsx` | `/#demo` CTAs → `/signup` / `/login`. |
| `frontend/src/lib/api-base.ts` | `API_BASE` → `"/api/proxy"` (same-origin). `publicBackendOrigin`/`backendUrl` kept for server proxying + the public share route. |
| `frontend/src/lib/api.ts` | Dropped `authHeaders()` (Bearer), `hasApiKey()`, `costEstimateDemo()`, and the `/validate/cost/demo` branch. All data calls go same-origin (cookie forwarded by the proxy). |
| `frontend/src/lib/api/batch.ts` | Dropped the localStorage `authHeaders()`. |
| `frontend/src/components/workspace/PartWorkspace.tsx` | Always uses the authed `costEstimate` + `validateFile`; removed the `hasApiKey()` demo switch + the public-demo STL cap. |
| `frontend/src/app/(app)/{history,reconstruct,batch,batch/[id],analyses/[id]}/page.tsx` | Removed the `RequireKey` client wrapper — server gating replaces it. |
| `frontend/next.config.ts` | Added redirects `/keys → /settings/developer`, `/settings → /settings/developer`; `/dashboard/keys → /settings/developer`. |
| `backend/tests/test_frontend_api_config.py` | Updated the legacy route-shim assertions: the deleted physical shim pages are now next.config redirects (the test asserts those mappings). This fixes the 1 pre-existing failure noted by the backend builder. |

## 4. Files DELETED

- `frontend/src/components/ui/require-key.tsx` (client API-key gate — replaced by server gating).
- `frontend/src/app/(app)/keys/page.tsx` (moved to `/settings/developer`; `keys/actions.ts` kept — still cookie-proxied).

---

## 5. Why a same-origin proxy (not direct browser→backend)

The backend runs `CORSMiddleware(allow_credentials=False)`, so the browser
cannot send the cookie cross-origin with `credentials:'include'`. Routing every
data call through `/api/proxy/*` (same-origin) lets the Next server forward the
httpOnly cookie server-side — this works **locally and in production** (where the
frontend and backend are different origins) without any backend CORS change, and
keeps mesh/PDF/CSV URLs working. (Deploy note: the proxy buffers upload bodies in
the serverless function; large CAD uploads on Vercel hit the ~4.5 MB function
body limit — fine locally; for prod, large uploads want a direct/presigned path.)

---

## 6. Honesty run — REAL transcript (frontend dev :3000 → backend :8000 → Postgres)

Backend: `uvicorn main:app` with `DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify`
+ `DASHBOARD_SESSION_SECRET`/`API_KEY_PEPPER` (`openssl rand -base64 32`).
Frontend: `API_BASE=http://localhost:8000 NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev`.

```
# 1) Logged-out platform URL → redirected to /login (server-side gate)
GET /analyze                          → 307  Location: /login?next=%2Fanalyze

# 2) Sign up (same-origin) → httpOnly cookie set, NO token in the body
POST /api/auth/signup {email,password:"Passw0rd123"}
  → 200  set-cookie: dash_session=…; Path=/; Max-Age=2592000; HttpOnly; SameSite=lax
  → body: {"user":{"id":9,"email":"febuild…@anodeadvisory.com","role":"analyst"}}
  cookie jar: #HttpOnly_127.0.0.1 … dash_session …   (HttpOnly confirmed)

# 3) Platform URL WITH the session → loads (no redirect)
GET /analyze            (cookie)      → 200

# 4) Authed cost via the session proxy → full glass-box report + rate-limit header relayed
POST /api/proxy/validate/cost (cookie, file=ECU_Firewall_mount.stl, qty=50, region=US)
  → 200  x-ratelimit-limit: 60
  → {"status":"OK", … decision: make by mjf (PP) $44.13/unit, crossover ~739 …}
# 4b) Same call WITHOUT the cookie → rejected (relayed)
POST /api/proxy/validate/cost (no cookie) → 401

# 5) Logout → cookie cleared
POST /api/auth/logout                 → 200  set-cookie: dash_session=; Expires=1970
# 6) Platform URL after logout → redirected again
GET /analyze            (cleared)     → 307  /login?next=%2Fanalyze

# 7) Login: wrong then right password
POST /api/auth/login {…,"WrongPass9"} → 401 {"code":"invalid_credentials","message":"Invalid email or password."}
POST /api/auth/login {…,"Passw0rd123"}→ 200  set-cookie: dash_session=… HttpOnly; body {"user":…}
GET /analyze            (new cookie)  → 200
```

DB proof (Argon2id, never plaintext):
```
SELECT id, auth_provider, left(password_hash,22), (password_hash LIKE '%Passw0rd123%')
 9 | password | $argon2id$v=19$m=65536 | f      -- is_argon2id=true, contains_plaintext=false
```

---

## 7. Build / typecheck / tests

```
$ cd frontend && npm run build      # ✓ Compiled successfully; TypeScript ✓; 18 routes generated
                                     #   /analyze /cost /history … are ƒ (dynamic, session-gated)
                                     #   /api/auth/{login,signup,logout}, /api/proxy/[...path] present
$ npx tsc --noEmit                   # ✓ clean
$ npx eslint src                     # 0 errors (1 pre-existing data-table warning, not ours)
$ pytest backend/tests/test_frontend_api_config.py test_frontend_errors.py -q   # 10 passed
```

(Full backend suite re-run after the one test fix; no backend source files were
changed by this task — only `test_frontend_api_config.py`, which now passes.)

---

## 8. How to create an account + log in locally (user steps)

Prereq: local Postgres on :5432 with the dev DB + migrations applied
(`DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify`,
`alembic upgrade head` → head `0007`; `users.password_hash` exists).

1. **Start the backend** (from the repo root):
   ```bash
   export DASHBOARD_SESSION_SECRET=$(openssl rand -base64 32)
   export API_KEY_PEPPER=$(openssl rand -base64 32)
   export DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify
   ACCEPTING_NEW_ANALYSES=true LABELING_ENABLED=1 \
     backend/.venv/bin/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
   ```
2. **Start the frontend** (new shell):
   ```bash
   cd frontend
   API_BASE=http://localhost:8000 NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
   ```
3. Open **http://localhost:3000**. The marketing site shows **Log in** / **Sign up**
   (no "Get API Key", no anonymous demo).
4. Click **Sign up** → enter an email + a password (≥8 chars, with a letter and a
   digit, e.g. `Passw0rd123`). On success you land on **/analyze** — you're in the
   gated platform. (Use a unique local-part; note the backend strips `+tags` when
   de-duping, so `you+a@x.com` and `you+b@x.com` collide.)
5. Upload a STEP/STL on **/cost** → the should-cost decision renders (authed via
   your session, no API key).
6. Account menu (top-right) → **Sign out** → back to `/login`; visiting `/analyze`
   now redirects to `/login`. Log back in with the same email+password.
7. API keys: account menu → **Settings · Developer** (`/settings/developer`) — for
   programmatic API access only; they are no longer how you sign in.

---

## 9. Honest deploy-gated (NOT claimed to work locally)

| Capability | Local? | Still requires |
|---|---|---|
| Email + password signup/login/logout + session gating | **YES** | Postgres + `DASHBOARD_SESSION_SECRET` |
| Google OAuth ("Continue with Google" button) | NO | `GOOGLE_CLIENT_ID/SECRET`, redirect URI, `AUTH_MODE=google\|hybrid` |
| Magic-link ("Email me a magic link") | NO | `RESEND_API_KEY`, `REDIS_URL`, `MAGIC_LINK_SECRET`, `TURNSTILE_SECRET` |
| SAML SSO | NO | `AUTH_MODE=saml\|hybrid`, IdP metadata, `python3-saml` |
| Turnstile on the magic form | OFF locally | `NEXT_PUBLIC_TURNSTILE_SITEKEY` + backend `TURNSTILE_SECRET` |

The Google/magic buttons stay wired (integration points intact) and link to the
existing backend routes; they simply need the credentials above to function.
Production cookie is `Secure` automatically; large CAD uploads through the proxy
need a direct/presigned path on serverless (see §5).
