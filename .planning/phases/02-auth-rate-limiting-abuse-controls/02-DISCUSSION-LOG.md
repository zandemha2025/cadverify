# Phase 2: Auth + Rate Limiting + Abuse Controls - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 02-auth-rate-limiting-abuse-controls
**Mode:** `--auto` (no user interaction; Claude selected recommended defaults)
**Areas discussed:** OAuth provider, Magic-link details, Key storage & issuance, Rate limiting, Signup abuse model, Kill-switch, Authorization enforcement, CORS, Logging/scrubbing, Dashboard auth surface

---

## OAuth Provider Choice (ROADMAP gray area #1)

| Option | Description | Selected |
|--------|-------------|----------|
| Google OAuth only + magic link | Simplest test matrix; covers most devs | ✓ |
| Google + GitHub + magic link | Broader reach; +30% test surface | |
| Magic link only | Zero OAuth surface; slowest UX | |

**Auto-selected:** Google + magic link (no GitHub at launch).
**Rationale:** PROJECT.md Key Decisions + REQUIREMENTS.md AUTH-01/02. Target audience is mechanical engineers, not primarily GitHub-native developers. GitHub deferred (tracked as deferred idea).

---

## Magic-link Provider

| Option | Description | Selected |
|--------|-------------|----------|
| Resend | Named in ROADMAP key deliverables; simple | ✓ |
| Postmark | Strong deliverability; slightly pricier | |
| AWS SES | Cheapest; more setup | |

**Auto-selected:** Resend. **Rationale:** Explicitly named in ROADMAP.md.

---

## Magic-link Token TTL

| Option | Description | Selected |
|--------|-------------|----------|
| 15 minutes, single-use | Standard for passwordless | ✓ |
| 1 hour | More forgiving | |
| 24 hours | Widens replay window | |

**Auto-selected:** 15 minutes. **Rationale:** Matches Auth0/Clerk/Supabase defaults.

---

## Signup Abuse Model (ROADMAP gray area #3)

| Option | Description | Selected |
|--------|-------------|----------|
| Turnstile only | Bot challenge | |
| Turnstile + per-IP limit | Blocks naive scripting | |
| Turnstile + per-IP + per-email + disposable blocklist | Defense in depth | ✓ |
| reCAPTCHA v3 | Google tracking, similar UX | |

**Auto-selected:** Turnstile + per-IP (3/hr) + per-email (1/24h) + disposable-email blocklist.
**Rationale:** Pitfall 10. IP-only bypassable via proxy; email-only bypassable via `+tag` aliases. Combination closes the trivial abuse paths.

---

## Turnstile Integration (ROADMAP gray area #2)

| Option | Description | Selected |
|--------|-------------|----------|
| Cloudflare Turnstile | Privacy-friendly, free, managed challenge | ✓ |
| reCAPTCHA v3 | Google tracking | |
| hCaptcha | Paid for enterprise features | |

**Auto-selected:** Cloudflare Turnstile. **Rationale:** Named in ROADMAP; privacy posture aligns with beta.

---

## Disposable-email Heuristic

| Option | Description | Selected |
|--------|-------------|----------|
| Curated blocklist (disposable-email-domains) | Blocks 80% cheaply | ✓ |
| DNS MX-record heuristic | More dynamic; false positives | |
| Third-party service (ZeroBounce, Kickbox) | Accurate; paid | |

**Auto-selected:** Curated blocklist cached in Redis with 24h TTL.

---

## Kill-switch Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Env var + 30s in-process cache | `fly secrets set && fly deploy` | ✓ |
| DB-backed flag, instant toggle | Dashboard admin UI needed | |
| Redis flag | Instant, no admin UI | |

**Auto-selected:** Env var. **Rationale:** Single-builder operator; Fly deploy is <2 min. DB flag tracked as deferred.

---

## Authorization Enforcement Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Per-route `Depends(require_api_key)` | Explicit; accurate OpenAPI | ✓ |
| Global middleware with path exemption list | DRY; drift-prone | |

**Auto-selected:** Per-route `Depends`. **Rationale:** ROADMAP deliverable says "not global middleware."

---

## Dashboard Auth Surface

| Option | Description | Selected |
|--------|-------------|----------|
| Dashboard session cookie (API stays Bearer-only) | Normal web UX | ✓ |
| localStorage API key, re-sent each request | Fully stateless; XSS exposure | |
| Re-prompt for key each visit | Safest; worst UX | |

**Auto-selected:** Dashboard-only session cookie. **Flagged for user review.**

---

## Rate-limit Header Names

| Option | Description | Selected |
|--------|-------------|----------|
| GitHub-style `X-RateLimit-*` | Dev-recognized | ✓ |
| RFC draft `RateLimit-*` (no X-) | Future-standard | |

**Auto-selected:** GitHub-style. **Rationale:** Developer familiarity.

---

## CORS Configuration

| Option | Description | Selected |
|--------|-------------|----------|
| Regex: prod + Vercel preview, credentials=false | Safe for Bearer auth | ✓ |
| Wildcard + credentials=true | Insecure | |
| Explicit origins list, manually maintained | Drift-prone | |

**Auto-selected:** Regex `^https://(cadverify\.com|.*\.vercel\.app)$`, `allow_credentials=False`.

---

## Log/Sentry Scrubbing

| Option | Description | Selected |
|--------|-------------|----------|
| structlog processor + CI grep test | Catches accidental logs + drift | ✓ |
| Sentry-native scrubber only | Misses stdout logs | |
| Manual audit per log statement | Doesn't scale | |

**Auto-selected:** structlog processor + CI grep test on captured Sentry event.

---

## Claude's Discretion

Areas left to researcher/planner with standard patterns:
- slowapi storage key format
- Argon2id cost parameters (start with RFC defaults)
- OAuth state/nonce storage (Redis, 10-min TTL)
- Exact DB schema for `users`/`api_keys` tables
- Turnstile widget placement/styling (UI plan)
- Sentry DSN wiring (Phase 6 owns full config)

## Deferred Ideas

- GitHub OAuth — revisit at beta+30 days
- API-key scopes — v2
- Webhook key-compromise notifications — out of scope
- SSO/SAML — enterprise (v2+)
- Admin panel kill-switch — v2
- Formal `audit_events` table — v2/ORG-*
- Password reset — permanently out of scope

---

*Auto-mode note: Zero AskUserQuestion calls were made. All selections driven by PROJECT.md "Key Decisions," REQUIREMENTS.md locked values (AUTH-01..11), and ROADMAP.md Phase 2 deliverables. User should review the "Decisions to Revisit" section in 02-CONTEXT.md.*
