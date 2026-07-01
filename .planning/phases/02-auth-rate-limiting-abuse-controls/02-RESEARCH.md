# Phase 2: Auth + Rate Limiting + Abuse Controls — Research

**Researched:** 2026-04-15
**Mode:** Bundled with /gsd-plan-phase 2 (CONTEXT.md already resolved 10 gray areas in --auto mode; this research supplies the how-to details the planner needs).

---

## 1. Token Format & Storage (D-04, D-05, D-06)

### Generating `cv_live_<prefix>_<secret>`
- **Prefix (8 chars base62):** `secrets.token_urlsafe(6)` yields ~8 base64-urlsafe chars; strip `-_=` and re-roll to enforce base62. Stored plaintext in `api_keys.prefix` for lookup + UI "last 8".
- **Secret (32 chars base62):** `secrets.token_urlsafe(24)` → 32 chars after strip. `secrets` uses `os.urandom` (CSPRNG); `random` must NOT be used.
- Full token shown ONCE at issuance.

### HMAC prefix index (fast lookup)
```python
import hmac, hashlib
def hmac_index(token: str, pepper: bytes) -> str:
    return hmac.new(pepper, token.encode(), hashlib.sha256).hexdigest()
```
- `pepper` = `API_KEY_PEPPER` env var (required, 32+ random bytes base64). NEVER stored in DB.
- Column `api_keys.hmac_index` (TEXT, indexed UNIQUE) — O(1) lookup.
- Why HMAC (not plain sha256): prevents attacker with DB dump from enumerating candidate hashes offline without the pepper.

### Argon2id verification (collision defense)
```python
from argon2 import PasswordHasher
ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
secret_hash = ph.hash(full_token)              # at issuance
ph.verify(secret_hash, full_token_from_request)  # in require_api_key
```
- Parameters match argon2-cffi defaults for server-auth (RFC 9106 "second choice"). At ~40 ms per verify on modern hardware, 60 req/hr/key = 2.4 s/hr CPU — negligible.
- Store in `api_keys.secret_hash` (TEXT).

### Lookup flow
1. Parse `Authorization: Bearer cv_live_<prefix>_<secret>` → extract full token.
2. `idx = hmac_index(token, PEPPER)`.
3. `SELECT user_id, id AS api_key_id, prefix, secret_hash, revoked_at FROM api_keys WHERE hmac_index = $1`.
4. If row missing OR `revoked_at IS NOT NULL` → 401.
5. `ph.verify(row.secret_hash, token)` → if `VerifyMismatchError` → 401.
6. If `ph.check_needs_rehash(row.secret_hash)`: async rehash + update (non-blocking).
7. Fire-and-forget `UPDATE api_keys SET last_used_at = now() WHERE id = $1`.

---

## 2. Rate Limiting (D-07, D-08)

### slowapi + Redis
```python
from slowapi import Limiter
from slowapi.util import get_remote_address
limiter = Limiter(
    key_func=lambda: "anonymous",          # overridden per-route
    storage_uri=os.environ["REDIS_URL"],
    strategy="fixed-window",
)
```
Per-key limits via dependency that returns the key func closure:
```python
def per_key_limits(user: AuthedUser = Depends(require_api_key)):
    return user
@router.post("/validate")
@limiter.limit("60/hour;500/day", key_func=lambda req: req.state.authed_user.api_key_id)
async def validate(...): ...
```
- slowapi stores counters under `LIMITER/{key_func_result}/60/hour`. Redis TTL auto-expires keys.
- `fixed-window` is simpler than sliding-window and the AUTH-07 numbers are coarse enough that window-edge bursts don't matter.

### Response headers (GitHub-style)
On 429: slowapi's `_rate_limit_exceeded_handler` → custom handler emits:
- `Retry-After: <seconds>`
- `X-RateLimit-Limit: 60`
- `X-RateLimit-Remaining: 0`
- `X-RateLimit-Reset: <unix-seconds>`
- JSON body: `{"code": "rate_limited", "message": "...", "doc_url": "..."}`

On happy-path responses, slowapi's middleware auto-attaches `X-RateLimit-*` headers if `headers_enabled=True`.

### Signup rate limit (D-09)
- `@limiter.limit("3/hour", key_func=get_remote_address)` on `POST /auth/signup/start`.
- `@limiter.limit("1/day", key_func=lambda req: _normalize_email(req.form["email"]))` on the email-bound step.
- `_normalize_email("User+tag@Gmail.com")` → `"user@gmail.com"` (strip `+tags`, lowercase, collapse dots for gmail subdomain).

---

## 3. OAuth (Google) + Magic Link (D-01, D-02, D-03)

### Google OAuth (authorization code + PKCE)
Library: `authlib` (Python) — battle-tested, FastAPI-friendly, no client-side SDK needed (aligns with D-19).
```python
from authlib.integrations.starlette_client import OAuth
oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
```
Endpoints:
- `GET /auth/google/start` — `return await oauth.google.authorize_redirect(request, redirect_uri)` (sets state+nonce in Redis via a custom storage).
- `GET /auth/google/callback` — `token = await oauth.google.authorize_access_token(request)`; `userinfo = token["userinfo"]`; upsert user by `google_sub` (preferred) or lowercased email; mint API key; set dashboard cookie; redirect to `/dashboard/keys?new=1`.

**State/nonce storage:** Redis with `SETEX oauth_state:<state> 600 <nonce>` (10-min TTL per D-Discretion). Validate-and-delete on callback to prevent replay.

### Magic link (Resend)
```python
import resend, hmac, base64, time
def mint_magic_token(email: str, secret: bytes) -> str:
    nonce = secrets.token_urlsafe(16)
    exp = int(time.time()) + 900  # 15 min per D-03
    payload = f"{email}|{nonce}|{exp}"
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).rstrip(b"=").decode()
```
Storage: `SETEX magic_link:<hmac(token)> 900 <email>` (single-use enforced by `DEL` on first verify).

Send via Resend:
```python
resend.api_key = os.environ["RESEND_API_KEY"]
resend.Emails.send({
    "from": "login@cadverify.com",
    "to": email,
    "subject": "Your CadVerify login link",
    "html": f'<a href="{link}">Sign in to CadVerify</a> (expires in 15 min)',
})
```

Verify endpoint `GET /auth/magic/verify?token=...`: decode + HMAC-check + Redis-GET-and-DEL; if valid, upsert user, mint key, set cookie, redirect.

---

## 4. Turnstile (D-10) + Disposable-Email Soft-Flag (D-11)

### Cloudflare Turnstile server verification
Frontend renders widget → user solves → widget emits `cf-turnstile-response` token. Backend POSTs to siteverify:
```python
async with httpx.AsyncClient(timeout=5.0) as client:
    r = await client.post(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data={"secret": os.environ["TURNSTILE_SECRET"], "response": client_token, "remoteip": request.client.host},
    )
    if not r.json().get("success"):
        raise HTTPException(400, detail={"code": "captcha_failed", ...})
```
Verify BEFORE enqueueing OAuth redirect or magic-link send.

### Disposable-email soft-flag
- Seed list: `disposable-email-domains` npm list (MIT-licensed JSON, ~3800 domains). Cache in Redis `disposable_domains` SET, 24 h TTL, re-fetch daily from GitHub raw URL.
- **Soft-flag tier:** if domain ∈ list → force `interactive` Turnstile action (`action=signup-strict`), tighten per-email limit to 1/7d in Redis.
- **Hard-reject tier:** sub-list of ~20 known-throwaway domains (mailinator.com, 10minutemail.com, guerrillamail.com, yopmail.com, temp-mail.org, …) hard-coded in config → 400 `{"code": "email_domain_blocked"}`.

Provider allowlist overrides (D-11 user override): proton.me, protonmail.com, tuta.io, fastmail.com, fastmail.fm are NEVER blocked even if they appear on a third-party list.

---

## 5. CORS (D-15)

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https://(cadverify\.com|www\.cadverify\.com|[a-z0-9-]+\.vercel\.app)$",
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    allow_credentials=False,    # Bearer auth, no cookies on API
    max_age=600,
)
```
- Regex (not wildcard) so Vercel previews work without `allow_origins=["*"]` (which is incompatible with `allow_credentials=True` anyway, but we stay False).
- The **dashboard** session cookie (D-19) is set on `dashboard.cadverify.com` origin and never traverses the API CORS boundary; API remains stateless.

---

## 6. Kill-switch (D-12)

```python
# backend/src/auth/kill_switch.py
_cache_ts = 0.0
_cache_val = True
_LOCK = threading.Lock()
def is_accepting() -> bool:
    global _cache_ts, _cache_val
    now = time.time()
    if now - _cache_ts < 30:
        return _cache_val
    with _LOCK:
        if now - _cache_ts < 30:
            return _cache_val
        _cache_val = os.getenv("ACCEPTING_NEW_ANALYSES", "true").lower() != "false"
        _cache_ts = now
    return _cache_val
```
Used as FastAPI dependency:
```python
def require_kill_switch_open():
    if not is_accepting():
        raise HTTPException(503, headers={"Retry-After": "3600"},
                            detail={"code": "service_paused", "message": "New analyses temporarily disabled.", "doc_url": "..."})
```
Attached to `POST /api/v1/validate` and any other analysis-creating route.

Operator: `fly secrets set ACCEPTING_NEW_ANALYSES=false -a cadverify-api && fly deploy -a cadverify-api`. (Deploy reloads env; 30-s cache means worst case 30 s stale.)

---

## 7. Log Scrubbing (D-16)

### structlog processor
```python
# backend/src/auth/scrubbing.py
import re
_KEY_RE = re.compile(r"cv_live_[A-Za-z0-9_]+")
_REDACTED = "cv_live_***REDACTED***"
def scrub(_, __, event_dict):
    for k, v in list(event_dict.items()):
        if isinstance(v, str):
            event_dict[k] = _KEY_RE.sub(_REDACTED, v)
            if k.lower() == "authorization":
                event_dict[k] = "Bearer ***REDACTED***"
    return event_dict
```
structlog config installs `scrub` **before** the Sentry transport and **before** the JSON renderer / stdout sink.

Sentry `before_send` also calls `_KEY_RE.sub` across `event["message"]`, `event["logentry"]["message"]`, breadcrumbs, and request headers (belt + suspenders).

CI test: capture a Sentry event (`sentry_sdk.Hub.capture_event` with a stubbed transport) containing a fake `cv_live_xxx` in the message; assert `cv_live_xxx` NOT in the captured payload.

---

## 8. `require_api_key` Dependency (D-13, D-14)

```python
# backend/src/auth/require_api_key.py
from fastapi import Depends, HTTPException, Request, Header
from pydantic import BaseModel
class AuthedUser(BaseModel):
    user_id: int
    api_key_id: int
    key_prefix: str

async def require_api_key(request: Request, authorization: str = Header(None)) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer cv_live_"):
        raise HTTPException(401, detail={"code": "auth_missing", ...})
    token = authorization.removeprefix("Bearer ").strip()
    row = await _lookup(token)  # HMAC index SELECT
    if not row or row.revoked_at:
        raise HTTPException(401, detail={"code": "auth_invalid", ...})
    try:
        ph.verify(row.secret_hash, token)
    except (VerifyMismatchError, InvalidHash):
        raise HTTPException(401, detail={"code": "auth_invalid", ...})
    user = AuthedUser(user_id=row.user_id, api_key_id=row.id, key_prefix=row.prefix)
    request.state.authed_user = user  # slowapi key_func reads this
    await _touch_last_used(row.id)    # fire-and-forget
    return user
```

Applied **per-route** (D-13): every protected endpoint adds `user: AuthedUser = Depends(require_api_key)` to its signature. Unprotected routes (signup, health, `/s/{short_id}` once Phase 4 ships) explicitly omit it.

---

## 9. DB Schema (minimal — Phase 3 owns the real migration discipline)

Phase 2 ships the *first* migration under what will become Phase 3's Alembic tree:
```python
# backend/alembic/versions/0001_create_users_api_keys.py
def upgrade():
    op.create_table("users",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("email", sa.Text, unique=True, nullable=False),
        sa.Column("email_lower", sa.Text, unique=True, nullable=False),  # normalized
        sa.Column("google_sub", sa.Text, unique=True, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("disposable_flag", sa.Boolean, server_default="false"),
    )
    op.create_table("api_keys",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False, server_default="Default"),
        sa.Column("prefix", sa.Text, nullable=False),                  # 8-char plaintext
        sa.Column("hmac_index", sa.Text, unique=True, nullable=False), # lookup key
        sa.Column("secret_hash", sa.Text, nullable=False),              # Argon2id
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_hmac_index", "api_keys", ["hmac_index"], unique=True)
```
Phase 3 adds `analyses`, `jobs`, `usage_events` on top of this.

---

## 10. Frontend (Next.js App Router) — D-17, D-18, D-19

Routes to add:
- `app/(auth)/signup/page.tsx` — server component renders Turnstile widget (`<Script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer />` + `<div className="cf-turnstile" data-sitekey={...} />`), Google button, email field + magic-link button.
- `app/(auth)/signup/actions.ts` — server actions that POST to backend `/auth/google/start` (returns 302) or `/auth/magic/start` (200).
- `app/(auth)/magic/verify/page.tsx` — strips `?token=` from URL, POSTs to `/auth/magic/verify`, redirects to `/dashboard/keys?new=1`.
- `app/(dashboard)/keys/page.tsx` — lists keys; `?new=1` triggers reveal-once modal rendering the plaintext token from a `sessionStorage` transfer (not URL, not DOM-rendered before mount).
- `app/(dashboard)/keys/actions.ts` — `createKey`, `rotateKey(id)`, `revokeKey(id)` server actions calling backend.

Dashboard session cookie (D-19):
- `Set-Cookie: dash_session=<hmac-signed user_id>; Domain=.cadverify.com; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=2592000` (30 days rolling per Deferred note).
- Verified by dashboard middleware (`frontend/middleware.ts`), **never** by API routes.

Reveal-once modal: grey monospace block, copy button, unstyled "I've saved it" checkbox that enables the "Done" button — Stripe pattern.

---

## 11. Validation Architecture (Nyquist)

| Dimension | Technique | Tool |
|---|---|---|
| 1. Happy path | Full signup → key issuance → authed request | pytest + httpx TestClient |
| 2. Sad path | Invalid/expired/revoked key | pytest parameterized |
| 3. Boundary | 60th req/hr (OK), 61st (429) | pytest + freezegun |
| 4. Security | JWT-style replay on magic link; wrong pepper; no key; Bearer-less | pytest negative |
| 5. Concurrency | 10 concurrent 60th-req/hr bursts against same key | pytest-asyncio + asyncio.gather |
| 6. Integration | Google OAuth flow via authlib test harness | pytest + respx (httpx mock) |
| 7. Observability | Assert captured Sentry/log payload has no `cv_live_` | pytest with sentry stub transport |
| 8. Regression | CI runs `grep -r "cv_live_[A-Za-z0-9_]\+" <captured_sentry_dump>` | ci.yml |

---

## 12. External Dependencies to Add

Python (`backend/requirements.txt`):
- `argon2-cffi ~= 23.1`
- `slowapi ~= 0.1.9`
- `redis ~= 5.0` (sync + asyncio clients)
- `authlib ~= 1.3`
- `httpx ~= 0.27` (already present)
- `resend ~= 2.0`
- `structlog ~= 24.1`
- `sqlalchemy ~= 2.0` + `asyncpg ~= 0.29` + `alembic ~= 1.13`

Node (`frontend/package.json`):
- `@marsidev/react-turnstile ~= 1.1` (optional; plain `<Script>` works too)

---

## 13. Risks & Mitigations Surfaced During Research

| Risk | Mitigation |
|---|---|
| Argon2 p99 > 200 ms under load | Tune params per D-Discretion; add p99 histogram; drop to `time_cost=2` if needed (still ASVS-compliant) |
| Redis unavailable → slowapi fails open | slowapi `in_memory_fallback_enabled=True`; Sentry alert on Redis ping fail; /health returns 503 if Redis down |
| OAuth state/nonce forgery | Redis-backed state with 10-min TTL; PKCE enforced; state validated-and-deleted |
| Magic-link replay | HMAC(token) as Redis key; DEL on first verify; 15-min TTL hard cap |
| Turnstile bypass via clientside token reuse | siteverify called ONCE per token; token's `cdata` field logged to Redis for dedup 5 min |
| Disposable-email false positive on proton.me | Hard allowlist (D-11 override); only hard-reject on curated sub-list |
| `cv_live_` leaking via exception message | structlog + Sentry `before_send` both scrub; CI regex test on stub Sentry dump |
| Per-route `Depends` forgetfulness | CI job greps every route file; fails if a non-public route lacks `require_api_key` |

---

## RESEARCH COMPLETE
