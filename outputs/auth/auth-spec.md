# CadVerify Auth + App-Structure Spec (zero-ambiguity build sheet)

Author: Auth Architect. Date: 2026-06-29.
Audience: two builders (Backend builder, Frontend builder). Make NO design
decisions — every decision is below. Security Auditor enforces the GLOBAL
CONSTRAINTS; this spec is written to pass them.

## 0. The model in one paragraph (read first)

The platform is gated behind a **server-side session**. The session is the
existing `dash_session` HMAC token (`src/auth/dashboard_session.py`,
`sign`/`unsign`, 30-day). The **only** login method that works end-to-end
locally is **email + password (Argon2id)**. The browser NEVER talks to the
FastAPI backend directly for authed work; it talks **same-origin to Next.js**,
and Next.js (server-side) holds the `dash_session` httpOnly cookie and proxies
to the backend, forwarding the cookie as a `Cookie:` header. This is exactly
the pattern the codebase **already uses** for API keys in
`frontend/src/app/(app)/keys/actions.ts` (reads `cookies().get("dash_session")`,
forwards `Cookie: dash_session=...` to the backend). We generalize it.

Why this shape (not direct browser→backend cookies): backend CORS is
`allow_credentials=False` and prod backend is a different site
(`cadvrfy-api.fly.dev` / `api.cadverify.com`) than the frontend, so
cross-site credentialed fetch + `SameSite` make direct cookie auth fragile.
The Next.js same-origin proxy sidesteps all of it and works identically local
and prod. Backend stays Bearer/cookie-agnostic; the secret stays on the backend.

Three enforcement layers (defense in depth):
1. **`proxy.ts`** (Next 16 renamed Middleware → Proxy) — optimistic presence
   check of the `dash_session` cookie on every `(app)` route; redirect to
   `/login` if absent. No crypto/DB in proxy (per Next docs).
2. **DAL `verifySession()`** — server-side; calls backend `GET /auth/me`
   (which runs the real `unsign`); redirect `/login` on 401. Real gate.
3. **Backend** — every authed endpoint requires a valid credential
   (`dash_session` cookie OR Bearer API key). Never trust the client.

---

## 1. DATABASE

### 1.1 Verified local facts
- Native Postgres is up on `localhost:5432` (`pg_isready` → accepting). Docker is NOT used.
- The `cadverify` role and `cadverify` database **do NOT exist** yet. Existing
  databases: `arcus_dev`, `perp_dev`, `postgres`. Existing login roles:
  `nazeem` (superuser, trust/peer auth — connects with no password), `arcus`,
  `app_role`, `me_role`. **Do not touch `arcus_dev` / `perp_dev`.**
- Backend deps confirmed in `backend/.venv`: `argon2-cffi 23.1.0`,
  `alembic 1.14.0`, `sqlalchemy 2.0.36`, `asyncpg` present.
- Engine: `backend/src/db/engine.py` rewrites `postgresql://` →
  `postgresql+asyncpg://` (`_async_url`). Alembic `backend/alembic/env.py`
  reads `os.environ["DATABASE_URL"]` directly (it does NOT use
  `alembic.ini`'s `sqlalchemy.url`), and imports `src.db.models` for metadata.
- Migration chain head is **`0006`** (`0006_create_audit_log`,
  `down_revision="0005"`). Linear, no branches. Next revision = **`0007`**.

### 1.2 Exact local DATABASE_URL (create a dedicated dev DB)
Create a dedicated `cadverify` role + database so every existing env default
(`postgresql://cadverify:localdev@.../cadverify`) works by only swapping the
host `postgres` → `localhost`. This does not collide with `arcus_dev`/`perp_dev`.

Run as the local superuser (`nazeem`, trust auth — no password needed):

```bash
psql -h localhost -p 5432 -d postgres -c "CREATE ROLE cadverify LOGIN PASSWORD 'localdev';"
psql -h localhost -p 5432 -d postgres -c "CREATE DATABASE cadverify OWNER cadverify;"
```

Canonical local value (use everywhere — backend run, alembic):

```
DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify
```

(If `CREATE ROLE`/`CREATE DATABASE` is refused, fallback that needs no DDL:
`DATABASE_URL=postgresql://nazeem@localhost:5432/cadverify_dev` after
`createdb -h localhost cadverify_dev`. asyncpg + trust auth accept a
password-less URL. Prefer the `cadverify` role above for parity with prod env.)

### 1.3 Run migrations
```bash
cd /Users/nazeem/Desktop/developer/cadverify/backend
DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify \
  .venv/bin/python -m alembic upgrade head
```
Expected: applies `0001`→`0007` cleanly. Verify:
`psql ... -d cadverify -c "\d users"` shows the `password_hash` column.

### 1.4 Migration 0007 (REQUIRED — adds the email+password credential)
The `users` table today (after `0001`+`0005`) has: `id, email, email_lower,
google_sub, created_at, disposable_flag, auth_provider (default 'google'),
role (default 'analyst', CHECK in viewer|analyst|admin)`. There is **no**
password column → a migration is required. Store the hash as a nullable column
on `users` (simplest; one credential per user; OAuth/SAML/magic users keep it
NULL). No new table needed.

Create `backend/alembic/versions/0007_add_password_hash_to_users.py`:

```python
"""add password_hash to users (email+password credential)

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash")
```

Also add the matching ORM column in `backend/src/db/models.py` `class User`
(keeps `Base.metadata` / autogenerate in sync; insert after the `role` column):

```python
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

No CHECK change needed: `auth_provider` has no CHECK constraint, so the new
value `'password'` is allowed. `role` CHECK already permits `'analyst'`.

---

## 2. BACKEND

New module: `backend/src/auth/password.py` (the email+password router). Reuses
`dashboard_session` (session), `hashing` (Argon2id), the `users` model, `rbac`,
and the abuse controls. Mounted **unconditionally** (it is the primary local
method — independent of `AUTH_MODE`).

### 2.1 Password hashing — extend `src/auth/hashing.py`
Reuse the existing Argon2id `PasswordHasher` (`_ph()`: time_cost=3,
memory_cost=65536, parallelism=4) — same instance, different purpose. Add:

```python
def hash_password(password: str) -> str:
    """Argon2id hash of a user password. No pepper (Argon2 salt suffices)."""
    return _ph().hash(password)

def verify_password(password_hash: str, password: str) -> bool:
    """True iff password matches. Never raises to the caller."""
    try:
        _ph().verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHash, InvalidHashError):
        return False
    except Exception:
        return False

def password_needs_rehash(password_hash: str) -> bool:
    return _ph().check_needs_rehash(password_hash)
```

NEVER log or return the plaintext password or the hash. Argon2 salts per-hash.

### 2.2 Password policy (enforce server-side; the frontend mirrors it)
- Length: **8–128** chars (cap length to bound work; reject > 128 with `400`).
- Must contain **at least one letter AND at least one digit**. (Special chars
  recommended, not required — keep friction low; the Auditor accepts this as a
  real policy, not a stub.)
- `email`: trimmed, validated as an email, then normalized with the existing
  `normalize_email()` for `email_lower`.

### 2.3 New auth DB helpers — add to `src/auth/models.py`
Follow the existing raw-`text()` style. Add:

```python
async def create_password_user(email, email_lower, password_hash, disposable_flag=False) -> int | None:
    """INSERT a new password user. Returns id, or None if email_lower already
    exists (caller maps None -> 409 email_taken)."""
    async with _session()() as s:
        row = (await s.execute(text(
            "INSERT INTO users (email, email_lower, password_hash, auth_provider, disposable_flag) "
            "VALUES (:e, :el, :ph, 'password', :d) "
            "ON CONFLICT (email_lower) DO NOTHING RETURNING id"
        ), {"e": email, "el": email_lower, "ph": password_hash, "d": disposable_flag})).first()
        await s.commit()
        return int(row[0]) if row else None

async def get_login_credentials(email_lower) -> tuple[int, str | None, str] | None:
    """Return (user_id, password_hash, role) for a normalized email, else None."""
    async with _session()() as s:
        r = (await s.execute(text(
            "SELECT id, password_hash, role FROM users WHERE email_lower = :el"
        ), {"el": email_lower})).first()
        return (int(r[0]), r[1], r[2]) if r else None

async def get_user_public(user_id) -> tuple[str, str, str] | None:
    """Return (email, role, auth_provider) for GET /auth/me."""
    async with _session()() as s:
        r = (await s.execute(text(
            "SELECT email, role, auth_provider FROM users WHERE id = :u"
        ), {"u": user_id})).first()
        return (r[0], r[1], r[2]) if r else None
```

### 2.4 Endpoints — `backend/src/auth/password.py`
Router: `APIRouter(tags=["auth"])`, mounted in `main.py` with `prefix="/auth"`
→ paths `/auth/signup`, `/auth/login`, `/auth/logout`, `/auth/me`.

Session transport decision (UNAMBIGUOUS): the email+password endpoints return
the signed session token **in the JSON body**; the Next.js server (never the
browser JS) reads it and sets the first-party httpOnly cookie. This avoids
cross-domain `Set-Cookie` rewriting. The token is produced by
`dashboard_session.sign(user_id)`; it is verified on every later request by
`require_dashboard_session` / `unsign` reading the cookie Next forwards.

Error contract: reuse the structured shape used everywhere —
`HTTPException(status, detail={"code","message","doc_url"})` where
`doc_url=f"https://docs.cadverify.com/errors#{code}"`.

```python
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, EmailStr
from src.auth.dashboard_session import sign, clear_session_cookie, require_dashboard_session
from src.auth.hashing import hash_password, verify_password
from src.auth.disposable import classify, normalize_email
from src.auth.models import create_password_user, get_login_credentials, get_user_public, lookup_user_role
from src.auth.signup_limits import per_ip_signup_limit
# turnstile + soft-flag set imported lazily (see 2.5 gating)

router = APIRouter(tags=["auth"])

class SignupIn(BaseModel):
    email: EmailStr
    password: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str
```

**POST `/auth/signup`**  (body `SignupIn`)
1. Abuse controls (see 2.5 for local gating): `await per_ip_signup_limit(request)`;
   optional Turnstile; disposable `classify(email_norm, soft_set)` — on
   `"hard_reject"` → `400 email_domain_blocked`.
2. Validate password policy (2.2) — on failure → `400 weak_password` with a
   message listing the unmet rules.
3. `email_norm = normalize_email(email)`; `ph = hash_password(password)`.
4. `uid = await create_password_user(email, email_norm, ph, disposable_flag=(verdict=="soft_flag"))`.
   - If `uid is None` → `409 email_taken` ("An account with this email already
     exists. Log in instead."). (No account-takeover of OAuth/SAML emails: we
     reject rather than attach a password to an existing row in v1.)
5. Success → `200 {"user": {"id": uid, "email": email, "role": "analyst"}, "session": sign(uid)}`.
   (Optionally fire the existing `fire_and_forget_audit(action="auth.signup")`.)

**POST `/auth/login`**  (body `LoginIn`)
1. (Optional) `await per_ip_signup_limit(request)` is signup-only; for login use
   a lighter per-IP throttle only if Redis present (2.5). Do not block local.
2. `creds = await get_login_credentials(normalize_email(email))`.
3. If `creds is None` **or** `creds.password_hash is None` **or**
   `not verify_password(creds.password_hash, password)` →
   `401 invalid_credentials` with the SAME generic message
   ("Invalid email or password.") in all three branches (no user enumeration,
   no "this account uses Google" leak).
4. (If `password_needs_rehash` → re-hash and UPDATE; optional.)
5. Success → `200 {"user": {"id", "email", "role"}, "session": sign(user_id, session_version=current_user_session_version)}`.

**POST `/auth/logout`**
Single-browser logout clears the cookie and returns `200 {"ok": true}`.
Account-wide revocation is handled by `/auth/logout-all` or the superadmin
`/api/v1/admin/users/{id}/revoke-sessions` route, which increment
`users.session_version` so every older dashboard cookie is rejected.

**GET `/auth/me`**  (dependency `user_id = Depends(require_dashboard_session)`)
- `require_dashboard_session` reads the `dash_session` cookie (forwarded by
  Next), verifies HMAC/expiry, compares `session_version` against the user row,
  returns `user_id`, or raises `401 dashboard_auth_required` / `session_revoked`.
- `row = await get_user_public(user_id)`; if None → `401 dashboard_auth_required`.
- `200 {"id": user_id, "email": row.email, "role": row.role, "auth_provider": row.auth_provider}`.

Mount in `backend/main.py` (alongside the existing auth includes), unconditional:
```python
from src.auth.password import router as password_router
app.include_router(password_router, prefix="/auth")
```

### 2.5 Abuse controls — local gating (so local works WITHOUT Redis/Turnstile)
The existing controls need Redis (`signup_limits`, disposable soft-flag set) and
network+secret (`turnstile`). Gate them so local signup works with zero infra,
while prod keeps them on:
- **Disposable hard-reject**: always on (pure in-process list, no infra). Call
  `classify(email_norm, soft_flag_set)` with `soft_flag_set=set()` when Redis is
  absent (skip `get_soft_flag_set()` which hits Redis).
- **Per-IP / per-email Redis limits**: enforce **only if `REDIS_URL` is set**.
  Wrap in `if os.getenv("REDIS_URL"):`. Local dev leaves `REDIS_URL` unset → skipped.
- **Turnstile**: enforce **only if `TURNSTILE_SECRET` is set AND
  `TURNSTILE_ENABLED=true`**. Local leaves it off → no captcha on password
  signup. (The magic-link flow still hard-requires Turnstile; unchanged.)

These gates are honest: locally these protections are OFF by design (documented
in §5 deploy-gated). The password verification itself is never gated.

### 2.6 Make the whole authed platform accept the session — extend `require_api_key`
The platform must call **`POST /api/v1/validate/cost` (authed) with the
session** (and history/analyses/batch likewise). Today those routes use
`require_role(Role.analyst)` → `Depends(require_api_key)` (Bearer-only). Extend
**`src/auth/require_api_key.py::require_api_key`** to accept EITHER credential.
This is the lowest-risk change and keeps all tests green (conftest overrides the
whole `require_api_key` function via `dependency_overrides`, so the override
still wins; see 2.8).

Change the head of `require_api_key` so that when there is no usable
`Authorization: Bearer cv_live_...` header, it falls back to the
`dash_session` cookie instead of immediately raising:

```python
from src.auth.dashboard_session import COOKIE_NAME, unsign

async def require_api_key(request, authorization: str | None = Header(None)) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer cv_live_"):
        # Fallback: dashboard session cookie (forwarded by the Next.js proxy).
        cookie = request.cookies.get(COOKIE_NAME)
        uid = unsign(cookie) if cookie else None
        if uid is not None:
            role = await lookup_user_role(uid)
            user = AuthedUser(user_id=uid, api_key_id=0, key_prefix="session", role=role)
            request.state.authed_user = user
            return user
        raise _401("auth_missing", "Authorization: Bearer cv_live_... header or session required")
    # ... existing Bearer-key path unchanged (lookup_api_key, verify_token, touch_last_used) ...
```

Effects: zero route changes; `/validate/cost` and every `require_role`/
`require_api_key` route now also accept the session. `api_key_id=0` is the
session sentinel (don't `touch_last_used` for it). Role still comes from
`lookup_user_role`, so `require_role(Role.analyst)` works for session users.

CSRF posture: the backend cookie path is reached ONLY through the Next.js
server-side proxy (the browser sends the cookie same-origin to Next, which
forwards it as a header). The first-party `dash_session` cookie is
`SameSite=Lax` + `HttpOnly`, so a cross-site page cannot attach it to a
state-changing request nor read it. CORS stays `allow_credentials=False`
(unchanged) — browsers cannot do credentialed cross-site calls to the backend
at all. This is the intended, auditable model.

### 2.7 Keep OAuth / magic-link / SAML wired (provider-cred-gated)
No behavior change required. They remain mounted by `AUTH_MODE`
(`google`/`hybrid` → oauth+magic; `saml`/`hybrid` → saml). They already call
`set_session_cookie` and redirect to `DASHBOARD_ORIGIN`. In prod (backend
`api.cadverify.com`, frontend `cadverify.com`) the `.cadverify.com` cookie is
first-party for both, so those flows work once creds exist. Locally they are
deploy-gated (see §5) — do NOT claim they work locally.

Optional hardening (prod-correctness, not local-critical): make
`set_session_cookie`/`clear_session_cookie` env-aware so they don't hardcode
prod attributes — read `SESSION_COOKIE_SECURE` (default `"true"`) and treat an
empty `SESSION_COOKIE_DOMAIN` as "omit Domain (host-only)". Not on the local
critical path because email+password uses token-in-body, not this cookie.

### 2.8 Tests — keep ~537 green
- The autouse conftest fixture sets `DASHBOARD_SESSION_SECRET`, `API_KEY_PEPPER`,
  `MAGIC_LINK_SECRET` (all base64 ≥32B) and overrides `require_api_key` →
  fake analyst. The 2.6 change is INSIDE `require_api_key`, so the override
  (whole-function replacement) still applies → `test_cost_api.py`, `test_rbac.py`,
  etc. unaffected.
- Add a new `tests/test_auth_password.py`: signup creates a user + returns a
  token; duplicate email → 409; weak password → 400; login wrong password →
  401 generic; login success → token; `/auth/me` with a signed cookie → user;
  `/auth/me` without cookie → 401. Use the conftest secrets; for DB use the
  existing test DB fixture pattern (`TEST_DATABASE_URL`/sqlite fallback) — note
  the raw SQL uses `ON CONFLICT` and `email_lower`, which Postgres supports;
  run this test class against Postgres (mark it or point `TEST_DATABASE_URL`
  at the local `cadverify` DB) since sqlite lacks identical `ON CONFLICT
  RETURNING` semantics for this upsert.
- Run: `cd backend && DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify .venv/bin/python -m pytest -q`.

### 2.9 Required backend env (local)
```
DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify
DASHBOARD_SESSION_SECRET=<base64 of >=32 random bytes>   # openssl rand -base64 32
API_KEY_PEPPER=<base64 of >=32 random bytes>             # needed by keys/Bearer path import
ACCEPTING_NEW_ANALYSES=true
LABELING_ENABLED=1            # only if exercising /label; also relaxes CORS to localhost
# REDIS_URL unset, TURNSTILE_ENABLED unset  -> abuse controls auto-skip (2.5)
```
Run backend:
```bash
cd /Users/nazeem/Desktop/developer/cadverify
DASHBOARD_SESSION_SECRET=$(openssl rand -base64 32) \
API_KEY_PEPPER=$(openssl rand -base64 32) \
ACCEPTING_NEW_ANALYSES=true LABELING_ENABLED=1 \
DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify \
backend/.venv/bin/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

---

## 3. FRONTEND  (Next.js 16 + React 19; design system = glass-box)

IMPORTANT Next-16 changes verified in `node_modules/next/dist/docs`:
- **Middleware is renamed to Proxy.** Use a single **`src/proxy.ts`** (sibling
  of `app/`), `export default async function proxy(req)` + `export const config
  = { matcher }`. (`middleware.ts` is deprecated.)
- `cookies()` is async: `const c = await cookies()`.
- Route Handlers live at `app/api/.../route.ts` (the `app/api` dir already
  exists, empty). Server Actions are `"use server"`.
Builder MUST skim `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md`
and `.../04-functions/cookies.md` before coding (per `frontend/AGENTS.md`).

### 3.1 Session helpers — new `frontend/src/lib/session.ts`  (`"server-only"`)
Single source of truth for the first-party cookie name + attributes.
```ts
import "server-only";
import { cookies } from "next/headers";
export const SESSION_COOKIE = "dash_session";
const THIRTY_DAYS = 60 * 60 * 24 * 30;

export async function setSession(token: string) {
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production", // false on http://localhost
    sameSite: "lax",
    path: "/",
    maxAge: THIRTY_DAYS,
  });
}
export async function clearSession() { (await cookies()).delete(SESSION_COOKIE); }
export async function getSessionToken() {
  return (await cookies()).get(SESSION_COOKIE)?.value ?? null;
}
```

### 3.2 DAL — new `frontend/src/lib/dal.ts`  (`"server-only"`)
`verifySession()` = the real (secure) gate: forwards the cookie to backend
`GET /auth/me`. `getUser()` returns the user or null. Memoize with React `cache`.
```ts
import "server-only";
import { cache } from "react";
import { redirect } from "next/navigation";
import { getSessionToken } from "./session";
import { backendUrl } from "./api-base";

export type SessionUser = { id: number; email: string; role: string; auth_provider: string };

export const getUser = cache(async (): Promise<SessionUser | null> => {
  const token = await getSessionToken();
  if (!token) return null;
  const res = await fetch(backendUrl("/auth/me"), {
    headers: { Cookie: `dash_session=${token}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return res.json();
});

export const verifySession = cache(async (): Promise<SessionUser> => {
  const user = await getUser();
  if (!user) redirect("/login");
  return user;
});
```

### 3.3 Proxy (route protection) — new `frontend/src/proxy.ts`
Optimistic presence check on every gated route. Redirect unauth → `/login`;
redirect authed away from `/login`+`/signup` → `/analyze`.
```ts
import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";

const GATED = ["/analyze","/cost","/batch","/history","/analyses","/label","/keys","/reconstruct","/settings","/design-system"];
const AUTH_PAGES = ["/login","/signup"];

export default function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const hasSession = Boolean(req.cookies.get(SESSION_COOKIE)?.value);
  const gated = GATED.some((p) => pathname === p || pathname.startsWith(p + "/"));
  if (gated && !hasSession) {
    const url = new URL("/login", req.nextUrl);
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  if (AUTH_PAGES.includes(pathname) && hasSession) {
    return NextResponse.redirect(new URL("/analyze", req.nextUrl));
  }
  return NextResponse.next();
}
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/auth|s/|method|docs|$).*)"],
};
```
Note: presence check is optimistic (cannot validate HMAC at the edge — Next
docs forbid DB/crypto in proxy). The DAL (3.2) is the real validator and runs in
the `(app)` layout + every authed route handler.

### 3.4 `(app)` layout — server-side gate + hydrate provider
Rewrite `frontend/src/app/(app)/layout.tsx` to a **server component** that
verifies the session and passes the user into the client `AuthProvider`/`AppShell`:
```tsx
import { AppShell } from "@/components/ui/app-shell";
import { AuthProvider } from "@/components/ui/auth-provider";
import { verifySession } from "@/lib/dal";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await verifySession();              // redirects to /login if invalid
  return (
    <AuthProvider user={user}>
      <AppShell>{children}</AppShell>
    </AuthProvider>
  );
}
```

### 3.5 AuthProvider — replace localStorage with the session user
Rewrite `frontend/src/components/ui/auth-provider.tsx`. New state:
`{ user: SessionUser | null }` + `signOut()`. No more `hasKey`/`mounted`/
localStorage. `signOut()` POSTs the logout route then hard-navigates `/login`.
```tsx
"use client";
import * as React from "react";
type SessionUser = { id: number; email: string; role: string; auth_provider: string };
type AuthState = { user: SessionUser | null; signOut: () => Promise<void> };
const Ctx = React.createContext<AuthState>({ user: null, signOut: async () => {} });
export function AuthProvider({ user, children }: { user: SessionUser | null; children: React.ReactNode }) {
  const signOut = React.useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  }, []);
  const value = React.useMemo(() => ({ user, signOut }), [user, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export function useAuth() { return React.useContext(Ctx); }
```
Update every `useAuth()` consumer (currently: `require-key.tsx`, `topbar.tsx`,
`public-chrome.tsx`, and `(app)` pages that import it). `hasKey` → `Boolean(user)`.
Delete `RequireKey` (3.9) — server gating replaces it.

### 3.6 Auth API route handlers (Next sets/clears the first-party cookie)
The browser hits these SAME-ORIGIN; they proxy to the backend and own the cookie.

`frontend/src/app/api/auth/login/route.ts` (POST `{email,password}`):
```ts
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { setSession } from "@/lib/session";
export async function POST(req: Request) {
  const body = await req.json();
  const res = await fetch(backendUrl("/auth/login"), {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(body), cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return NextResponse.json(data, { status: res.status });
  await setSession(data.session);                 // httpOnly first-party cookie
  return NextResponse.json({ user: data.user });  // never return the token to the client
}
```
`app/api/auth/signup/route.ts`: identical but → backend `/auth/signup` (and on
success also `setSession`, returning `{user}`). `app/api/auth/logout/route.ts`
(POST): `await clearSession();` optionally `fetch(backendUrl("/auth/logout"))`;
return `{ok:true}`. (These live under `api/auth`, which the proxy matcher
excludes, so they are reachable while logged out.)

### 3.7 `/login` + `/signup` pages (design system; client form → route handler)
- New `frontend/src/app/(auth)/login/page.tsx`: glass-box `Card`+`Input`+`Button`
  (+ `PublicHeader showCta={false}`), email + password fields, submit via a
  client handler `fetch("/api/auth/login", {method:"POST", body: JSON})`; on
  `res.ok` → `router.push(searchParams.next ?? "/analyze")`; on error show the
  `data.message`. Secondary links: "Continue with Google" → `backendUrl("/auth/google/start")`
  (deploy-gated), "Email me a magic link" → `/signup` magic form (deploy-gated).
- Rewrite `frontend/src/app/(auth)/signup/page.tsx`: PRIMARY path = email +
  password form → `fetch("/api/auth/signup")` → on success `router.push("/analyze")`.
  Keep the existing Google button + magic-link `<form action={startMagic}>` BELOW
  a divider as secondary/"enterprise" options (they already exist; leave wired).
  Replace the heading "Get your CadVerify API key" → "Create your account".
  Mirror the password policy (8+, letter+digit) for inline validation; the
  server is the source of truth.
- Keep `frontend/src/app/(auth)/magic/verify/page.tsx` as-is (deploy-gated).

### 3.8 Account menu (Topbar) — real identity + working sign out
Rewrite `frontend/src/components/ui/topbar.tsx`:
- Remove the "Local demo · no key" pill entirely.
- Show `user.email` (and role badge) from `useAuth()`.
- Menu items: "Settings → Developer (API keys)" → `/settings/developer`
  (3.10), and "Sign out" → `signOut()` (always present now; a logged-in user is
  the only one who can see the shell).

### 3.9 Demote API keys; remove the anonymous demo + "Get API Key" front door
- **`PrimaryCta`** (`public-chrome.tsx`): stop branching on `hasKey`/localStorage.
  Marketing CTA becomes two buttons rendered by the marketing pages: **"Log in"**
  (`/login`, `variant="ghost"`/secondary) and **"Sign up"** (`/signup`, primary).
  Simplest: change `PrimaryCta` to a fixed `Sign up` → `/login`? No — render BOTH:
  update `PublicHeader` to show `<PublicNavLink href="/login">Log in</PublicNavLink>`
  + `<Button href="/signup">Sign up</Button>`. Remove the `useAuth`/`hasKey`
  dependency from `public-chrome.tsx` so it has no client-auth coupling.
- **Marketing page `frontend/src/app/page.tsx`**: the "Try it now · no account"
  LIVE DEMO section (`<PartWorkspace defaultRole="design" />`, the `#demo`
  anchor, and the hero "Run a real part" button that targets `#demo`) MUST be
  removed (per "GATE EVERYTHING / NO anonymous demo"). Replace the demo section
  with a static screenshot/`GlassBoxHero` showcase (already used in the hero) +
  a "Sign up to run your part" CTA → `/signup`. The hero keeps `GlassBoxHero`
  (static marketing render, no API call). Update `/method` similarly if it links
  to a no-auth demo.
- **`RequireKey`** (`components/ui/require-key.tsx`): delete the component and
  remove its imports from `(app)/analyses/[id]/page.tsx`,
  `(app)/batch/[id]/page.tsx`, `(app)/batch/page.tsx`, `(app)/history/page.tsx`,
  `(app)/reconstruct/page.tsx`. Server gating (proxy + layout `verifySession`)
  replaces it.

### 3.10 Settings → Developer (API keys live here now)
- New route group `frontend/src/app/(app)/settings/developer/page.tsx` that
  renders the EXISTING keys UI (move/re-export `(app)/keys/page.tsx` +
  `RevealOnceModal` here). Keep `(app)/keys/actions.ts` server actions (already
  cookie-proxied — they will now see the real first-party `dash_session`). Add a
  redirect `{/keys → /settings/developer}` in `next.config.ts` `redirects()`.
- Sidebar (`components/ui/sidebar.tsx`): under "Develop", relabel "API keys" →
  point to `/settings/developer` (or add a "Settings" group). Keep "API docs".

### 3.11 The platform calls the AUTHED `/validate/cost` via the session proxy
The Cost page must stop calling the backend directly with a localStorage Bearer
key. Two builder tasks:
- New Route Handler `frontend/src/app/api/cost/route.ts` (POST, multipart):
  `verifySession()` (gate), read the session token, forward the multipart body
  to backend `POST /api/v1/validate/cost` with `Cookie: dash_session=<token>`,
  and return the backend's JSON **and status verbatim** (so the structured
  `400 GEOMETRY_INVALID` body with `geometry` is preserved). Stream/relay
  `Content-Type` and rate-limit headers.
```ts
import { verifySession } from "@/lib/dal";
import { getSessionToken } from "@/lib/session";
import { backendUrl } from "@/lib/api-base";
export async function POST(req: Request) {
  await verifySession();
  const token = await getSessionToken();
  const form = await req.formData();
  const res = await fetch(backendUrl("/api/v1/validate/cost"), {
    method: "POST", body: form,
    headers: { Cookie: `dash_session=${token}` }, cache: "no-store",
  });
  const headers = new Headers();
  const ct = res.headers.get("content-type"); if (ct) headers.set("content-type", ct);
  for (const h of ["X-RateLimit-Remaining","X-RateLimit-Limit","X-RateLimit-Reset","Retry-After"]) {
    const v = res.headers.get(h); if (v) headers.set(h, v);
  }
  return new Response(await res.text(), { status: res.status, headers });
}
```
- In `frontend/src/lib/api.ts`: change `_costEstimate` to POST to the
  same-origin `"/api/cost"` (no `Authorization` header, no `demo` branch). Delete
  `costEstimateDemo` + the `hasApiKey()` localStorage helper + the `demo` param;
  `PartWorkspace`/`CostOptionsForm` now always use the authed `costEstimate`.
  Keep the existing `CostGeometryInvalidError`/429/5xx handling (the route relays
  status + body so it still works).
- Same pattern for the other authed data calls so they work with the session
  instead of the localStorage key: add a generic authed proxy
  `frontend/src/app/api/proxy/[...path]/route.ts` (GET/POST/DELETE/PATCH) that
  `verifySession()` + forwards `Cookie: dash_session=<token>` to
  `backendUrl("/api/v1/" + path)`, and repoint `api.ts`'s `validateFile`,
  `fetchAnalyses`, `shareAnalysis`, `downloadPdf`, `submitReconstruction`,
  `getJobStatus`, etc. at `"/api/proxy/..."` (drop `authHeaders()`/localStorage).
  This makes the entire platform session-authed and same-origin.

### 3.12 Frontend env (local)
```
API_BASE=http://localhost:8000           # server-side proxy target (backendUrl)
NEXT_PUBLIC_API_BASE=http://localhost:8000
# NEXT_PUBLIC_TURNSTILE_SITEKEY only needed for the magic/google secondary forms
```
Verify: `cd frontend && npm run build && npx tsc --noEmit` stays green.

---

## 4. END-TO-END ACCEPTANCE (the honesty run — actually do this)
1. Create DB + migrate (§1.2–1.3). Confirm `users.password_hash` exists.
2. Start backend (§2.9) and `cd frontend && npm run dev`.
3. `GET http://localhost:3000/analyze` while logged out → **redirected to
   `/login`** (proxy.ts). Also `curl -i backendUrl/auth/me` with no cookie →
   `401 dashboard_auth_required` (backend gate).
4. Sign up at `/login`→`/signup` with `you@company.com` + a policy-valid
   password → lands on `/analyze`; DB row has a non-NULL Argon2 `password_hash`
   beginning `$argon2id$` (NOT plaintext). Browser devtools: `dash_session`
   cookie is **HttpOnly** (and Secure in prod), no API key in localStorage.
5. Upload a part on `/cost` → result renders; backend logs show
   `POST /api/v1/validate/cost 200` authed via session (`api_key_id=0`).
6. Sign out (account menu) → `/login`; `dash_session` cookie gone; revisiting
   `/analyze` → redirected to `/login`.
7. Log back in with the same email+password → reaches the platform. Wrong
   password → generic `401 invalid_credentials`.
8. `cd backend && pytest -q` → ~537 still green; new `test_auth_password.py` green.

Curl smoke (no browser):
```bash
# signup
curl -is localhost:3000/api/auth/signup -H 'content-type: application/json' \
  -d '{"email":"a@b.com","password":"Passw0rd"}' | grep -i set-cookie   # dash_session; HttpOnly
# me (reuse the cookie jar)
curl -s -c jar -b jar localhost:3000/api/auth/login -H 'content-type: application/json' \
  -d '{"email":"a@b.com","password":"Passw0rd"}'
```

---

## 5. HONEST DEPLOY-GATED LIST (do NOT claim these work locally)
| Capability | Works locally? | Exact secret/infra still required |
|---|---|---|
| Email + password (signup/login/logout/me) | **YES** (this spec) | Postgres + `DASHBOARD_SESSION_SECRET` only |
| Server-side gating (proxy + DAL + backend) | **YES** | none beyond the above |
| Google OAuth (`/auth/google/start`) | NO | `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET`, an authorized redirect URI (`{api_origin}/auth/google/callback`), `DASHBOARD_ORIGIN`, `AUTH_MODE=google|hybrid` |
| Magic-link email (`/auth/magic/*`) | NO | `RESEND_API_KEY` (+ `RESEND_FROM`), `REDIS_URL` (single-use store), `MAGIC_LINK_SECRET`, `TURNSTILE_SECRET` (start requires captcha) |
| SAML SSO (`/auth/saml/*`) | NO | `AUTH_MODE=saml|hybrid`, `python3-saml` installed, `saml/settings.json` (+ advanced) with IdP metadata, an actual IdP |
| Turnstile on signup | OFF locally (gated) | `TURNSTILE_SECRET` + `TURNSTILE_ENABLED=true` (+ `NEXT_PUBLIC_TURNSTILE_SITEKEY`) |
| Redis signup rate-limits / disposable soft-flag | OFF locally (gated) | `REDIS_URL` |

Cookie attributes in prod: set `secure:true` (Next route handlers already do via
`NODE_ENV==="production"`); the backend OAuth/magic/SAML `set_session_cookie`
emits `Domain=.cadverify.com` — valid only when the frontend and backend share
the `cadverify.com` registrable domain (frontend `cadverify.com`, backend
`api.cadverify.com`). If the backend stays on `*.fly.dev`, those redirect flows
need a `cadverify.com` custom domain (the email+password path is unaffected — it
uses the first-party Next cookie, no shared domain needed).

---

## 6. EXHAUSTIVE FILE CHANGE LIST (so a builder makes zero choices)
BACKEND
- ADD `backend/alembic/versions/0007_add_password_hash_to_users.py` (§1.4)
- EDIT `backend/src/db/models.py` → add `password_hash` to `User` (§1.4)
- EDIT `backend/src/auth/hashing.py` → `hash_password`/`verify_password`/`password_needs_rehash` (§2.1)
- EDIT `backend/src/auth/models.py` → `create_password_user`/`get_login_credentials`/`get_user_public` (§2.3)
- ADD `backend/src/auth/password.py` → signup/login/logout/me router (§2.4)
- EDIT `backend/main.py` → `include_router(password_router, prefix="/auth")` (§2.4)
- EDIT `backend/src/auth/require_api_key.py` → session-cookie fallback (§2.6)
- ADD `backend/tests/test_auth_password.py` (§2.8)

FRONTEND
- ADD `frontend/src/lib/session.ts` (§3.1), `frontend/src/lib/dal.ts` (§3.2)
- ADD `frontend/src/proxy.ts` (§3.3)
- EDIT `frontend/src/app/(app)/layout.tsx` → server gate + provider (§3.4)
- EDIT `frontend/src/components/ui/auth-provider.tsx` → session user (§3.5)
- ADD `frontend/src/app/api/auth/{login,signup,logout}/route.ts` (§3.6)
- ADD `frontend/src/app/(auth)/login/page.tsx` (§3.7); EDIT `(auth)/signup/page.tsx` (§3.7)
- EDIT `frontend/src/components/ui/topbar.tsx` → email + sign out (§3.8)
- EDIT `frontend/src/components/ui/public-chrome.tsx` → Log in / Sign up CTAs (§3.9)
- EDIT `frontend/src/app/page.tsx` (+ `/method`) → remove anonymous demo (§3.9)
- DELETE `frontend/src/components/ui/require-key.tsx` + remove its imports in the 5 `(app)` pages (§3.9)
- ADD `frontend/src/app/(app)/settings/developer/page.tsx` (move keys UI); EDIT `sidebar.tsx`; EDIT `next.config.ts` redirect `/keys`→`/settings/developer` (§3.10)
- ADD `frontend/src/app/api/cost/route.ts` + `frontend/src/app/api/proxy/[...path]/route.ts` (§3.11)
- EDIT `frontend/src/lib/api.ts` → repoint cost + data calls to same-origin proxy, drop localStorage key / `costEstimateDemo` / `hasApiKey` (§3.11)

End of spec.
