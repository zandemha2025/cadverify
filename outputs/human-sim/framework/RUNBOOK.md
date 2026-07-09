# Human-Sim — Local Live-Stack Launch Runbook

Standing up the real app for a persona run requires a specific env set. Missing it
manifests as a **signup 500** (`KeyError: DASHBOARD_SESSION_SECRET` in `sign()`),
which blocks auth and every downstream flow — a whole run wasted. This is the recipe
that actually works in-container (verified: signup → 200 + session).

> Note: this is a **launch-config** requirement, not a product bug — the product
> correctly refuses to sign a session without a real secret. Tests set these via
> `conftest.py`; a manual `uvicorn` launch must set them explicitly. (A real
> self-hoster hits the same gate — worth surfacing in deploy docs; see finding.)

## Backend (uvicorn) — required env
```
DATABASE_URL=postgresql://postgres@localhost:5433/<utf8_db>   # createdb -E UTF8 -T template0, then: alembic upgrade head
API_KEY_PEPPER=$(python -c "import base64;print(base64.b64encode(b'a'*32).decode())")
MAGIC_LINK_SECRET=$(python -c "import base64;print(base64.b64encode(b'b'*32).decode())")
DASHBOARD_SESSION_SECRET=$(python -c "import base64;print(base64.b64encode(b'c'*32).decode())")
TURNSTILE_SECRET=test
DASHBOARD_ORIGIN=http://localhost:<frontend_port>
SESSION_SECRET=dev
AUTH_MODE=password
# then: uvicorn main:app --host 127.0.0.1 --port <backend_port>
```

## Frontend (next dev) — required env
The server-side proxy reads **`API_BASE`** (NOT `NEXT_PUBLIC_API_URL`); the client
reads **`NEXT_PUBLIC_API_BASE`**. Both must point at the backend, or signup/login
(server-side cookie-set) and all proxied calls fail.
```
API_BASE=http://localhost:<backend_port>
NEXT_PUBLIC_API_BASE=http://localhost:<backend_port>
PORT=<frontend_port>
# then: npm run dev   — and DRIVE via http://localhost:<frontend_port> (never 127.0.0.1: Next 16 blocks cross-origin dev → breaks hydration)
```

## Smoke before driving Playwright
```
curl -s http://localhost:<backend_port>/health           # {"status":"ok","postgres":true}
curl -s -X POST http://localhost:<backend_port>/auth/signup \
  -H 'Content-Type: application/json' -d '{"email":"smoke@acme-eng.com","password":"Testpass123"}'
# expect HTTP 200 with a "session" token — if 500, an auth secret is missing
```
Auth routes are mounted at `/auth/*` (NOT `/api/v1/auth/*`). Health at `/health`.
The httpOnly `dash_session` cookie is set by the Next server route on the localhost
response, so a real browser on `http://localhost:<frontend_port>` carries it.
