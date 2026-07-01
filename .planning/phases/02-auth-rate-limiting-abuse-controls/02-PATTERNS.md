# Phase 2: Auth + Rate Limiting + Abuse Controls — Pattern Map

**Mapped:** 2026-04-15
**Files analyzed:** 18 new/modified files
**Analogs found:** 18 / 18

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/src/auth/__init__.py` (new) | package | — | `backend/src/api/__init__.py` | exact |
| `backend/src/auth/hashing.py` (new) | utility | transform | `backend/src/api/upload_validation.py` | data-flow-match |
| `backend/src/auth/require_api_key.py` (new) | middleware | request-response | `backend/src/api/upload_validation.py::validate_magic` (dependency idiom) | role-match |
| `backend/src/auth/oauth.py` (new) | controller | request-response | `backend/src/api/routes.py` (FastAPI router pattern) | role-match |
| `backend/src/auth/magic_link.py` (new) | controller | request-response | `backend/src/api/routes.py` | role-match |
| `backend/src/auth/rate_limit.py` (new) | middleware | request-response | `backend/src/api/routes.py` (env-reader + decorator wiring) | data-flow-match |
| `backend/src/auth/kill_switch.py` (new) | utility | transform | `backend/src/analysis/constants.py` (env reader + cache) | role-match |
| `backend/src/auth/scrubbing.py` (new) | utility | transform | `backend/src/analysis/processes/checks.py` (stateless processor) | role-match |
| `backend/src/auth/turnstile.py` (new) | utility | request-response | `backend/src/api/routes.py` (httpx client use) | data-flow-match |
| `backend/src/auth/disposable.py` (new) | utility | transform | `backend/src/analysis/constants.py` | role-match |
| `backend/src/auth/models.py` (new) | data/model | — | (no analog — SQLAlchemy arrives in Phase 3) | new-pattern |
| `backend/src/api/routes.py` | controller | request-response | self — targeted edits | exact |
| `backend/alembic/versions/0001_create_users_api_keys.py` (new) | migration | — | (no analog — first migration) | new-pattern |
| `backend/alembic/env.py` (new) | config | — | (no analog) | new-pattern |
| `backend/main.py` | app-init | — | self — add middleware + router includes | exact |
| `frontend/src/app/(auth)/signup/page.tsx` (new) | UI | request-response | `frontend/src/app/page.tsx` | role-match |
| `frontend/src/app/(dashboard)/keys/page.tsx` (new) | UI | request-response | `frontend/src/app/page.tsx` | role-match |
| `frontend/middleware.ts` (new) | middleware | request-response | (no analog — first middleware) | new-pattern |
| `backend/tests/test_auth_*.py` (new) | test | request-response | `backend/tests/test_api.py` | exact |

---

## Pattern Assignments

### `backend/src/auth/hashing.py` (utility, transform)
**Change:** Create HMAC-prefix + Argon2id helpers.
**Analog:** `backend/src/api/upload_validation.py` (module-local helpers + lazy env readers).

**Analog pattern** (`upload_validation.py` lazy env reader):
```python
def _max_triangles() -> int:
    try:
        return max(1, int(os.getenv("MAX_TRIANGLES", "2000000")))
    except ValueError:
        return 2000000
```

**Target shape** (`hashing.py`):
```python
"""API-key hashing: HMAC-SHA256 prefix index + Argon2id secret hash."""
from __future__ import annotations
import base64, hashlib, hmac, os, secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

_PEPPER: bytes | None = None
_PH: PasswordHasher | None = None

def _pepper() -> bytes:
    global _PEPPER
    if _PEPPER is None:
        raw = os.environ["API_KEY_PEPPER"]    # required — fail fast
        _PEPPER = base64.b64decode(raw)
        if len(_PEPPER) < 32:
            raise RuntimeError("API_KEY_PEPPER must decode to >= 32 bytes")
    return _PEPPER

def _ph() -> PasswordHasher:
    global _PH
    if _PH is None:
        _PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4,
                             hash_len=32, salt_len=16)
    return _PH

def mint_token() -> tuple[str, str, str]:
    """Return (full_token, prefix, secret_hash). Caller stores prefix + hmac_index + secret_hash."""
    prefix = secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")[:8]
    secret = secrets.token_urlsafe(24).replace("-", "a").replace("_", "b")[:32]
    token = f"cv_live_{prefix}_{secret}"
    secret_hash = _ph().hash(token)
    return token, prefix, secret_hash

def hmac_index(token: str) -> str:
    return hmac.new(_pepper(), token.encode(), hashlib.sha256).hexdigest()

def verify_token(secret_hash: str, token: str) -> bool:
    try:
        _ph().verify(secret_hash, token)
        return True
    except (VerifyMismatchError, InvalidHash):
        return False
```

### `backend/src/auth/require_api_key.py` (middleware, request-response)
**Change:** FastAPI dependency returning `AuthedUser`.
**Analog:** `backend/src/api/upload_validation.py::validate_magic` (raises `HTTPException` from a dependency).

**Target shape:**
```python
from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel
from src.auth.hashing import hmac_index, verify_token
from src.auth.models import lookup_api_key, touch_last_used

class AuthedUser(BaseModel):
    user_id: int
    api_key_id: int
    key_prefix: str

def _401(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": code, "message": message, "doc_url": "https://docs.cadverify.com/errors#" + code},
    )

async def require_api_key(request: Request,
                          authorization: str | None = Header(None)) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer cv_live_"):
        raise _401("auth_missing", "Authorization: Bearer cv_live_... header required")
    token = authorization[len("Bearer "):].strip()
    row = await lookup_api_key(hmac_index(token))
    if row is None or row.revoked_at is not None:
        raise _401("auth_invalid", "Invalid or revoked API key")
    if not verify_token(row.secret_hash, token):
        raise _401("auth_invalid", "Invalid or revoked API key")
    user = AuthedUser(user_id=row.user_id, api_key_id=row.id, key_prefix=row.prefix)
    request.state.authed_user = user
    await touch_last_used(row.id)
    return user
```

### `backend/src/auth/rate_limit.py` (middleware)
**Change:** slowapi Limiter + 429 handler emitting GitHub-style headers.
**Analog:** `backend/src/api/routes.py` env-reader pattern + decorator wiring.

**Target shape:**
```python
import os, time
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

def _api_key_id(request: Request) -> str:
    u = getattr(request.state, "authed_user", None)
    return f"key:{u.api_key_id}" if u else f"ip:{request.client.host}"

limiter = Limiter(
    key_func=_api_key_id,
    storage_uri=os.getenv("REDIS_URL", "memory://"),
    strategy="fixed-window",
    headers_enabled=True,
    in_memory_fallback_enabled=True,
)

def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # slowapi stores reset epoch on the exception context; fallback to 3600.
    reset = int(time.time()) + getattr(exc, "retry_after", 3600)
    return JSONResponse(
        status_code=429,
        headers={
            "Retry-After": str(int(reset - time.time())),
            "X-RateLimit-Limit": str(exc.limit.limit) if getattr(exc, "limit", None) else "60",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(reset),
        },
        content={"code": "rate_limited",
                 "message": "Rate limit exceeded. Retry after the X-RateLimit-Reset timestamp.",
                 "doc_url": "https://docs.cadverify.com/errors#rate_limited"},
    )
```

### `backend/src/auth/kill_switch.py` (utility)
**Change:** Env-backed kill-switch with 30-s process cache.
**Analog:** `backend/src/analysis/constants.py` (env reader + module-level cache, per Phase 1 Plan 01.B).

**Target shape:**
```python
import os, threading, time
_LOCK = threading.Lock()
_CACHE_TS = 0.0
_CACHE_VAL = True
def is_accepting() -> bool:
    global _CACHE_TS, _CACHE_VAL
    now = time.time()
    if now - _CACHE_TS < 30.0:
        return _CACHE_VAL
    with _LOCK:
        if now - _CACHE_TS < 30.0:
            return _CACHE_VAL
        _CACHE_VAL = os.getenv("ACCEPTING_NEW_ANALYSES", "true").strip().lower() not in ("false", "0", "no")
        _CACHE_TS = now
        return _CACHE_VAL
```

### `backend/src/auth/scrubbing.py` (utility)
**Change:** structlog processor + Sentry `before_send`.
**Analog:** `backend/src/analysis/processes/checks.py` (stateless processor signature).

**Target shape:**
```python
import re
_KEY_RE = re.compile(r"cv_live_[A-Za-z0-9_]+")
_REDACTED = "cv_live_***REDACTED***"
_AUTH_KEYS = {"authorization", "x-api-key"}

def scrub_processor(_, __, event_dict):
    for k, v in list(event_dict.items()):
        if k.lower() in _AUTH_KEYS:
            event_dict[k] = "***REDACTED***"
        elif isinstance(v, str):
            event_dict[k] = _KEY_RE.sub(_REDACTED, v)
    return event_dict

def sentry_before_send(event, hint):
    s = __import__("json").dumps(event)
    if "cv_live_" in s:
        s = _KEY_RE.sub(_REDACTED, s)
        event = __import__("json").loads(s)
    return event
```

### `backend/src/api/routes.py` (controller — targeted edits)
**Change:** Add `Depends(require_api_key)` to every protected route; add kill-switch guard to validate routes; install rate-limit decorators.
**Analog:** self. The route signature pattern already in the file:
```python
@router.post("/validate", response_model=AnalysisResponse)
async def validate_endpoint(file: UploadFile = File(...),
                            processes: list[str] = Query(None)) -> AnalysisResponse:
```
**Target pattern** (after Phase 2):
```python
from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.auth.kill_switch import is_accepting

def require_kill_switch_open():
    if not is_accepting():
        raise HTTPException(503,
            headers={"Retry-After": "3600"},
            detail={"code": "service_paused",
                    "message": "New analyses temporarily disabled.",
                    "doc_url": "https://docs.cadverify.com/errors#service_paused"})

@router.post("/validate", response_model=AnalysisResponse, dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def validate_endpoint(request: Request,
                            file: UploadFile = File(...),
                            processes: list[str] = Query(None),
                            user: AuthedUser = Depends(require_api_key)) -> AnalysisResponse:
    ...
```

### `backend/src/auth/turnstile.py` (utility)
**Target shape:**
```python
import os, httpx
from fastapi import HTTPException

SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

async def verify_turnstile(token: str, remoteip: str | None) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post(SITEVERIFY, data={
            "secret": os.environ["TURNSTILE_SECRET"],
            "response": token,
            **({"remoteip": remoteip} if remoteip else {}),
        })
    ok = r.status_code == 200 and r.json().get("success") is True
    if not ok:
        raise HTTPException(400, detail={"code": "captcha_failed",
                                         "message": "Captcha verification failed.",
                                         "doc_url": "https://docs.cadverify.com/errors#captcha_failed"})
```

### `backend/src/auth/disposable.py` (utility)
```python
import os
_HARD_REJECT = frozenset({
    "mailinator.com", "10minutemail.com", "10minutemail.net", "guerrillamail.com",
    "guerrillamail.net", "guerrillamail.org", "yopmail.com", "temp-mail.org",
    "sharklasers.com", "spam4.me", "getnada.com", "trashmail.com",
    "maildrop.cc", "dispostable.com", "mintemail.com", "tempmail.com",
    "fakeinbox.com", "mytrashmail.com", "mailnesia.com", "throwaway.email",
})
_NEVER_BLOCK = frozenset({
    "proton.me", "protonmail.com", "pm.me", "tuta.io", "tutanota.com",
    "fastmail.com", "fastmail.fm", "gmail.com", "outlook.com", "hotmail.com",
    "icloud.com", "yahoo.com",
})
def classify(email: str, soft_flag_set: set[str]) -> str:
    """Return one of: 'ok', 'soft_flag', 'hard_reject'."""
    domain = email.rsplit("@", 1)[-1].strip().lower()
    if domain in _NEVER_BLOCK:
        return "ok"
    if domain in _HARD_REJECT:
        return "hard_reject"
    if domain in soft_flag_set:
        return "soft_flag"
    return "ok"

def normalize_email(email: str) -> str:
    local, _, domain = email.partition("@")
    local = local.lower()
    domain = domain.lower()
    if domain == "gmail.com":
        local = local.split("+", 1)[0].replace(".", "")
    else:
        local = local.split("+", 1)[0]
    return f"{local}@{domain}"
```

### `frontend/src/app/(auth)/signup/page.tsx`
**Analog:** `frontend/src/app/page.tsx` (Next.js App Router + Tailwind).
**Target shape:** server component renders Turnstile + Google button (links to `/api/auth/google/start` which 302s to backend) + email form posting to a server action.

### `frontend/src/app/(dashboard)/keys/page.tsx`
- Fetches keys via server action calling backend `GET /api/v1/keys` with dashboard session cookie.
- On `?new=1` and a `sessionStorage` `last_minted_token` value, renders a Stripe-style reveal-once modal with a mono block, copy button, "I've saved it" checkbox, then `sessionStorage.removeItem` on dismiss.
- Per-row: "Rotate" + "Revoke" buttons → server actions → optimistic refresh.

### `frontend/middleware.ts`
```ts
import { NextRequest, NextResponse } from "next/server";
import { verify } from "./src/lib/dash_session";
export function middleware(req: NextRequest) {
  if (!req.nextUrl.pathname.startsWith("/dashboard")) return NextResponse.next();
  const cookie = req.cookies.get("dash_session")?.value;
  if (!cookie || !verify(cookie)) return NextResponse.redirect(new URL("/signup", req.url));
  return NextResponse.next();
}
export const config = { matcher: ["/dashboard/:path*"] };
```

---

## Registered Conventions (reused)

- **Structured errors:** `{code, message, doc_url}` — same shape as Phase 1 issue categorization (reused per CONVENTIONS.md).
- **Lazy env readers with module-level cache** — Phase 1 pattern; reused in `kill_switch.py` and `hashing.py`.
- **Per-route `Depends`, not global middleware** — aligns with Phase 1's registry-decorator preference.
- **`from __future__ import annotations` on every new module.**
- **Tests next to module domain:** `backend/tests/test_auth_hashing.py`, `test_auth_require_api_key.py`, `test_auth_rate_limit.py`, `test_auth_scrubbing.py`, `test_auth_turnstile.py`, `test_auth_magic_link.py`, `test_auth_kill_switch.py` — each importable in isolation.

## PATTERN MAPPING COMPLETE
