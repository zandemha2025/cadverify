# Phase 2: Auth + Rate Limiting + Abuse Controls - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area — see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 2` if desired)

<domain>
## Phase Boundary

This phase delivers the atomic security unit for CadVerify's public free beta:

1. A signup flow that lets a new user obtain a `cv_live_<prefix>_<secret>` API key in under 60 seconds (Google OAuth primary, email magic link fallback).
2. Secure storage and management of those keys (Argon2id hashed + HMAC-SHA256 prefix index, create/rotate/revoke UI).
3. Enforcement: `Depends(require_api_key)` on every protected route, slowapi+Redis per-key rate limits (60/hr, 500/day), per-IP signup limits, Turnstile on the signup form, and a global `ACCEPTING_NEW_ANALYSES` kill-switch.
4. Hardening: CORS tightened (explicit `allow_headers`, regex origin, `allow_credentials=False`), Sentry + log scrubbing so no `cv_live_*` or `Bearer *` ever leaves the process.

All of these MUST ship together (Pitfall 4 + Pitfall 10 + Pitfall 11 compound — auth without rate-limits = open wallet; rate-limits without auth = nothing to limit against).

**Explicitly out of scope for this phase:**
- Persistence of analyses themselves (Phase 3 keystone)
- Per-user usage *dashboard* rendering (Phase 3 — PERS-09 reads `usage_events`); this phase emits the *events* that dashboard will later render
- Paid-tier quotas / Stripe (v2)
- Multi-user orgs / RBAC (v2)
- Email+password auth (permanently out of scope — PROJECT.md)

</domain>

<decisions>
## Implementation Decisions

### OAuth Provider Choice (ROADMAP-flagged gray area #1)

- **D-01:** Ship Google OAuth + email magic link at launch. GitHub OAuth is **deferred** to a later phase unless early beta telemetry shows demand.
  - **Rationale:** REQUIREMENTS.md AUTH-01/AUTH-02 already lock Google + magic link. PROJECT.md "Key Decisions" row: "API-key-only auth … avoids session/password/OAuth complexity." Adding GitHub triples the test matrix (three success paths + six failure paths) for a target audience (mechanical engineers, not primarily GitHub-native developers). Magic link covers the "I don't want to use Google" escape hatch.
  - **Recommended default chosen in auto mode:** Google-only OAuth + magic link.
- **D-02:** Magic link provider: **Resend** (as named in ROADMAP Key Deliverables).
  - **Rationale:** Explicitly called out in ROADMAP.md Phase 2 deliverables. Transactional-only, simple DNS setup, Python SDK, reasonable free tier for beta. Postmark is a fallback if Resend deliverability is poor; decision revisitable mid-phase.
- **D-03:** Magic-link token TTL: **15 minutes**, single-use, rotating secret stored server-side (HMAC of email + nonce + expiry).
  - **Rationale:** Standard for passwordless flows (Auth0, Clerk, Supabase all default 10–15 min). Longer TTLs widen replay window; shorter TTLs frustrate users on slow email delivery.

### API Key Format & Storage (locked by REQUIREMENTS.md)

- **D-04:** Token shape: `cv_live_<8-char-prefix>_<32-char-secret>` (base62). Prefix is stored plaintext + indexed; secret is Argon2id-hashed.
  - **Rationale:** Matches AUTH-03. The `cv_live_` namespace leaves room for future `cv_test_` sandbox keys without format churn.
- **D-05:** Lookup flow: HMAC-SHA256 of the full token with a server-side pepper → compared against `api_keys.hmac_index` column; on match, Argon2id verify against `api_keys.secret_hash`.
  - **Rationale:** AUTH-04 locks Argon2id + HMAC prefix index. HMAC gives O(1) lookup (indexable), Argon2id gives brute-force resistance if the DB leaks. Pepper (env var, not in DB) prevents offline cracking even with full DB+code exfil.
- **D-06:** Key is shown to the user **exactly once** (dashboard modal at creation + on explicit rotate). After dismissal, only the prefix is retrievable.
  - **Rationale:** AUTH-03 mandates this. Aligns with Stripe/GitHub/Vercel UX — users expect "save this now, we can't show it again."

### Rate Limiting (locked numerics from AUTH-07)

- **D-07:** Backend: **slowapi + Redis** (fixed-window per key). Limits: 60/hour, 500/day.
  - **Rationale:** Named in ROADMAP Key Deliverables. slowapi is FastAPI-idiomatic (decorator + dependency). Redis is already required for Phase 3 (cache) and Phase 7 (arq queue) — no new infra.
- **D-08:** 429 response emits `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers + structured error body `{code: "rate_limited", message, doc_url}`.
  - **Rationale:** Success Criterion #4. Frontend surfacing of these headers is Phase 8 (PERF-04); Phase 2 just emits them correctly.
- **D-09:** Signup rate limit: **per-IP + per-email** — 3 signup attempts per IP per hour, 1 completed signup per email per 24h.
  - **Rationale:** Defense in depth. IP-only is bypassable via IPv6 rotation or cheap proxy; email-only is bypassable via `user+1@…` aliases. Combining both, with email normalization (lowercase, strip `+tags` for gmail-style addresses), kills the trivial abuse paths without blocking legitimate corporate shared-IP signups.

### Turnstile / Signup Abuse Model (ROADMAP-flagged gray area #2 + #3)

- **D-10:** **Cloudflare Turnstile** on the signup form, verified server-side before any OAuth redirect or magic-link email is sent.
  - **Rationale:** ROADMAP Key Deliverables name Turnstile explicitly. Privacy-friendlier than reCAPTCHA (no Google tracking), free, managed challenge (most users see nothing). Verification happens server-side against `siteverify` endpoint — never trust the client token alone.
- **D-11:** Disposable-email heuristic: reject signups where the email domain matches a curated blocklist (seed from `disposable-email-domains` npm list, check on signup, cache the list in Redis with 24h TTL for refresh).
  - **Rationale:** Covers the 80% case cheaply. Not perfect (new throwaway domains appear daily) but raises the cost of mass-signup abuse. Rejection message is neutral ("This email address can't be used for signup — try a permanent address") to avoid confirming the list to attackers.
- **D-12:** `ACCEPTING_NEW_ANALYSES` kill-switch: **env var checked on every protected-route request**, with a 30-second in-process cache to avoid env-read overhead. Reading `false` returns HTTP 503 + `Retry-After: 3600`.
  - **Rationale:** AUTH-09 + Success Criterion #6 ("within one deploy"). Env-var is simpler than a DB flag for a single-builder operator — `fly secrets set ACCEPTING_NEW_ANALYSES=false && fly deploy` is one command. A future phase can promote this to a DB-backed flag if multi-instance coordination becomes an issue.

### Authorization Enforcement

- **D-13:** `Depends(require_api_key)` on **every protected route individually**, not a global middleware.
  - **Rationale:** Success Criterion implicit + ROADMAP deliverable says "not global middleware." Per-route dependencies make public routes (signup, healthcheck, landing, public share page in Phase 4) explicit-by-absence, avoiding the classic "forgot to exempt /health from auth" class of bugs. Also makes FastAPI's OpenAPI schema accurate out of the box.
- **D-14:** The dependency returns a lightweight `AuthedUser` pydantic model `{user_id, api_key_id, key_prefix}`. No session, no cookie, no DB round-trip beyond the one key lookup.
  - **Rationale:** Stateless, matches "API-key-only, no sessions" constraint in PROJECT.md. `user_id` + `api_key_id` are what downstream handlers and Phase 3's `usage_events` writer need.

### CORS (locked by AUTH-11)

- **D-15:** CORS config: `allow_origins_regex=r"^https://(cadverify\.com|.*\.vercel\.app)$"`, `allow_methods=["GET","POST","DELETE","OPTIONS"]`, `allow_headers=["Authorization","Content-Type","X-Request-ID"]`, `allow_credentials=False`.
  - **Rationale:** AUTH-11 + Pitfall 8. Regex covers prod + Vercel preview deployments without opening wildcard. `allow_credentials=False` is safe because auth is via `Authorization: Bearer` header (not cookies) — never flip to True while still using wildcard-ish regex.

### Logging & Scrubbing (locked by AUTH-10)

- **D-16:** A structlog processor runs before Sentry transport + before stdout log sink. It redacts any string matching `/cv_live_[A-Za-z0-9_]+/` or a header named `authorization` to `cv_live_***REDACTED***`.
  - **Rationale:** AUTH-10 + Success Criterion #7. Processor-based redaction catches accidental `logger.info("request with key %s", key)` usages. A separate post-capture test (grep the captured Sentry event payload for `cv_live_` prefix) runs in CI to catch drift.

### Frontend Surface (Next.js dashboard)

- **D-17:** Signup page: Google OAuth button (primary, top) + email input + "Send magic link" button (secondary). After first successful signup, redirect to `/dashboard/keys` with the newly-minted key shown in a dismissable modal with copy-to-clipboard.
  - **Rationale:** Matches the "< 60 seconds" success criterion. Two-button layout signals Google as the expected happy path while keeping magic link as equal-weight fallback.
- **D-18:** `/dashboard/keys` shows: list of existing keys (name, prefix, last used, created date), "Create key" button, per-row "Rotate" and "Revoke" actions with confirm modals.
  - **Rationale:** AUTH-05. "Last used" column requires a `last_used_at` touch on every authenticated request — cheap update (`UPDATE api_keys SET last_used_at = now() WHERE id = $1`), batched or fire-and-forget.
- **D-19:** No client-side OAuth library — backend handles the full OAuth dance, frontend just redirects to `/auth/google/start` and receives a redirect back to `/dashboard/keys` with a session cookie scoped to the dashboard subdomain only (API stays header-auth).
  - **Rationale:** Dashboard session cookie is acceptable and simpler than re-prompting for a key on every dashboard visit. The cookie only authorizes dashboard routes, never the `/api/v1/*` surface — that remains Bearer-only. This preserves the "no sessions on the API" constraint while giving normal web-app UX on the dashboard.

### Claude's Discretion

The following are left to the researcher / planner to resolve with standard patterns and no further user input:

- Exact slowapi storage key format (e.g., `key:{api_key_id}` vs `key:{hmac_index}`) and the key-expiry strategy (Redis TTL vs slowapi's fixed-window bookkeeping).
- Argon2id cost parameters — start with `time_cost=3, memory_cost=65536 KiB, parallelism=4` (Argon2 RFC sensible default) and tune if auth p99 exceeds 200ms.
- OAuth state/nonce storage (Redis with 10-minute TTL is the default).
- Exact DB schema shapes for `users` and `api_keys` tables (Phase 3 owns the schema file; Phase 2 ships the first migration that creates these two tables under Phase 3's Alembic discipline).
- Structured error response shape — follow DOC-02's `{code, message, doc_url}` locked in Phase 6; Phase 2 emits the same shape pre-docs.
- Sentry DSN wiring, release tagging — Phase 6 owns; Phase 2 adds the scrubber processor.
- Turnstile widget placement and styling — UI plan (see `gsd-ui-phase 2`) owns visual details.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase-level requirements and roadmap
- `.planning/ROADMAP.md` §"Phase 2: Auth + Rate Limiting + Abuse Controls" — goal, success criteria, key deliverables, suggested parallel plans (2.A–2.D), atomic-unit rationale.
- `.planning/REQUIREMENTS.md` §"Authentication & Abuse Controls" (AUTH-01..11) — locked numerics (60/hr, 500/day), token format, hashing algo, kill-switch, CORS shape, log scrubbing requirements.
- `.planning/PROJECT.md` §"Key Decisions" and §"Constraints" — API-key-only, no passwords, no sessions on API, Vercel + Fly.io stack.

### Pitfalls research (from Phase 0 research)
- `.planning/research/PITFALLS.md` — Pitfall 4 (plaintext key storage, no rotation), Pitfall 8 (Vercel↔Fly CORS/auth footguns), Pitfall 10 (no usage caps → runaway cost), Pitfall 11 (shareable URL enumeration, partial in Phase 2).
- `.planning/research/SUMMARY.md` — cross-cutting rationale for the atomic-unit decomposition.

### Brownfield codebase map
- `.planning/codebase/ARCHITECTURE.md` — current FastAPI route layout; where `Depends(require_api_key)` hooks in.
- `.planning/codebase/STRUCTURE.md` — backend/src/api/routes.py integration points.
- `.planning/codebase/CONVENTIONS.md` — existing error-response shape; frontend Next.js app router layout.
- `.planning/codebase/CONCERNS.md` — CORS currently wildcard-open; current logging has no redaction.
- `.planning/codebase/INTEGRATIONS.md` — existing external deps (none for auth yet — greenfield).

### Prior phase context
- `.planning/phases/01-stabilize-core/01-CONTEXT.md` — Phase 1 completed hardening the analyzer pipeline (DoS guards in place before opening public endpoints).

### External docs agents should consult during research
- FastAPI Security → Dependencies: https://fastapi.tiangolo.com/tutorial/security/ — `Depends`-based auth pattern.
- slowapi docs: https://slowapi.readthedocs.io/ — FastAPI + Starlette rate limiting.
- Argon2-cffi: https://argon2-cffi.readthedocs.io/ — Python Argon2id bindings with sane defaults.
- Cloudflare Turnstile server verification: https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
- Resend magic-link sending: https://resend.com/docs/send-with-python
- OWASP Session Management Cheat Sheet — applies to the dashboard cookie (not the API).
- OWASP ASVS v4 §2.2 (Authentication) + §4.1 (Access Control) — acceptance-criteria sanity check.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **FastAPI app factory** (`backend/src/api/routes.py` + app init module) — already wired; adding `Depends(require_api_key)` is a drop-in pattern.
- **Env-var config module** (introduced in Phase 1: `backend/src/analysis/constants.py` pattern) — extend or parallel for auth config (`ANALYSIS_TIMEOUT_SEC` lives here; `ACCEPTING_NEW_ANALYSES` joins it).
- **structlog-ready logging** — Phase 1 did not install structlog yet; this phase introduces it *only for the scrubber hook*, full structlog rollout is Phase 6 (OBS-02). Recommendation: install it now so OBS-02 just configures sinks.
- **Next.js 16 / React 19 dashboard shell** — existing analysis dashboard. New pages slot in as `/auth/*` and `/dashboard/keys`.

### Established Patterns
- **Registry-based analyzers** (`@register` decorator, Phase 1) — not directly reused, but confirms the codebase prefers explicit registration over magic middleware. Aligns with D-13's "per-route dependency, not global middleware."
- **Categorized `Issue` emission** (Phase 1, CORE-02) — auth errors should emit a structured error following the same shape (`{code, message, doc_url}`), not raw `HTTPException(detail="Invalid key")`.
- **Fly.io deploy scaffolding exists** — `fly secrets set` is the kill-switch operator workflow; no new deploy patterns needed.

### Integration Points
- `backend/src/api/routes.py` — every `@router.post("/validate")` etc. gets `user: AuthedUser = Depends(require_api_key)` appended to its signature.
- New module: `backend/src/auth/` — `require_api_key.py`, `oauth.py` (Google), `magic_link.py`, `hashing.py` (Argon2id + HMAC), `rate_limit.py` (slowapi config), `scrubbing.py` (log processor).
- New migration: `backend/alembic/versions/xxxx_create_users_api_keys.py` — creates the two tables Phase 2 needs; Phase 3 adds `analyses`, `jobs`, `usage_events`.
- Next.js: new routes under `app/(auth)/` and `app/(dashboard)/keys/`.
- Redis client: new dependency — used here for rate-limit counters and OAuth state; Phase 3 will reuse for cache; Phase 7 for arq.

</code_context>

<specifics>
## Specific Ideas

- **Key issuance UX reference:** Stripe's "reveal once" modal — grey background, monospace key, copy-to-clipboard button, "I've saved it" confirmation before dismiss enables.
- **Rate-limit headers:** Match GitHub's header names (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` with unix-seconds value) — developers recognize them.
- **Signup copy:** Keep it single-screen. Two buttons, one email field. Avoid an account-creation form — there are no fields to fill in beyond email.
- **Kill-switch operator workflow:** One command — `fly secrets set ACCEPTING_NEW_ANALYSES=false -a cadverify-api && fly deploy -a cadverify-api`. Optionally a helper script in `scripts/ops/kill-switch.sh`.
- **Deferred defense:** CAPTCHA escalation (Turnstile → Invisible reCAPTCHA → hard challenge) is *not* in this phase; single Turnstile level is enough for beta.

</specifics>

<deferred>
## Deferred Ideas

All surfaced during auto-mode analysis; parked for future phases or post-beta iteration:

- **GitHub OAuth provider** — revisit at beta+30 days if signup analytics show demand (track `oauth_provider_requested` events even when unavailable).
- **API-key scopes / permissions** — single-scope keys for v1 beta; scoped keys are a v2 need (probably with ORG-* requirements).
- **Per-user usage dashboard rendering** — Phase 3 (PERS-09). Phase 2 emits `usage_events`-shaped records but may write them to a stub table or skip until Phase 3 creates the real table. **Decision to defer:** Phase 3 owns the `usage_events` schema; Phase 2 rate-limiter writes only to Redis for enforcement; `usage_events` DB writes begin in Phase 3. This avoids a throw-away Alembic migration.
- **Webhook-based key-compromise notifications** — out of scope; the "rotate" UI is the v1 mitigation.
- **SSO / SAML** — enterprise (ENT-*), v2+.
- **Session timeout / inactivity lockout on dashboard** — dashboard cookie gets a 30-day rolling expiry; no inactivity lockout for beta.
- **Admin panel to flip kill-switch without a deploy** — explicit v2 need; `fly secrets set` is the operator workflow for beta.
- **Audit log for key operations (create/rotate/revoke)** — emit to stdout + Sentry breadcrumb for now; formal `audit_events` table is a v2/ORG-* concern.
- **Password reset flow** — permanently out of scope (no passwords exist to reset).

</deferred>

---

## Gray Areas Resolved in Auto Mode — Summary Table

| # | Gray area (ROADMAP-flagged or inferred) | Auto-selected default | Decision ID(s) |
|---|-----------------------------------------|-----------------------|----------------|
| 1 | OAuth provider: Google-only, Google+GitHub, or magic-link-only | Google OAuth + magic link (no GitHub at launch) | D-01 |
| 2 | Magic-link email provider | Resend | D-02 |
| 3 | Magic-link token TTL | 15 minutes, single-use | D-03 |
| 4 | Signup abuse model | Turnstile + per-IP (3/hr) + per-email (1/24h) + disposable-email blocklist | D-09, D-10, D-11 |
| 5 | Kill-switch mechanism | Env var + 30s in-process cache | D-12 |
| 6 | `require_api_key` as middleware or per-route dependency | Per-route `Depends` (not global middleware) | D-13 |
| 7 | Dashboard session: cookie or always re-auth with key | Dashboard-only session cookie, API stays Bearer-only | D-19 |
| 8 | Rate-limit header names | GitHub-style `X-RateLimit-*` | D-08 + specifics |
| 9 | Sentry/log redaction mechanism | structlog processor + CI grep test | D-16 |
| 10 | CORS origins | Regex: prod + Vercel preview subdomains, no credentials | D-15 |

## Decisions the User Should Revisit Before `/gsd-plan-phase 2`

These auto-selections are the most consequential to downstream planning. Worth a glance before committing:

1. **D-01 (Google-only at launch).** If the target audience skews more GitHub-native than PROJECT.md assumes, adding GitHub OAuth now is cheaper than adding it in v2 (same OAuth library, ~30% extra test surface). Easy to flip.
2. **D-11 (disposable-email blocklist).** This **can** reject legitimate users on niche email providers (privacy-focused ones like proton.me, tuta.io are usually *not* on the list, but fringe cases exist). Alternative: soft-flag instead of hard-reject and route to extra Turnstile challenge.
3. **D-19 (dashboard session cookie).** Introduces a small stateful surface (the session store) into an otherwise stateless API. Alternative: frontend stores API key in `localStorage` and re-sends on every dashboard request. More stateless, but `localStorage` + auth is a known XSS hazard. Staying with cookie is the safer default but worth an explicit ack.
4. **D-12 (env-var kill-switch vs DB flag).** Forces a deploy to toggle. A DB-flag would allow instant toggle from the dashboard. For a single-builder beta, deploys are fast (< 2 min on Fly) and this is fine; at scale it's a real limit.
5. **D-07 rate limit numerics (60/hr, 500/day).** Locked by AUTH-07. Worth sanity-checking against anticipated beta usage — if a single CI pipeline fires 10 analyses per commit, 60/hr gets tight fast. Easy to raise before launch; harder to tighten after.

---

*Phase: 02-auth-rate-limiting-abuse-controls*
*Context gathered: 2026-04-15*
*Mode: --auto (all gray areas resolved with recommended defaults; see each D-## "Rationale" line)*
