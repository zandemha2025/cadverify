# Password recovery

The login page now links to `/forgot-password`. Turnstile and per-IP/email
throttles protect reset requests; the response does not disclose account state.
Existing active password accounts receive a 15-minute, single-use link to
`/reset-password#token=…`. Only a hash of the random bearer token is stored in
Redis. The page removes the token from the URL and consumes it only on submit.

Completion reuses the existing atomic password update, audit event and session
revocation. All previous dashboard sessions and other outstanding reset links
become invalid. The user then logs in normally. SSO-only accounts must recover
through their identity provider. No account, quota or CAD data is recreated.
Validation errors omit rejected input values, including passwords and tokens.

Production needs `RESEND_API_KEY`, a verified `RESEND_FROM` sender,
`DASHBOARD_ORIGIN=https://scalecad.ai`, `REDIS_URL` and `TURNSTILE_SECRET` on the
API, plus the matching real `TURNSTILE_SITE_KEY` on the web service. No magic-link
secret or UI flag is needed. Missing configuration fails closed with an honest
unavailable message. Deploy the API and web changes after required CI passes.

Read-only Render inspection found Redis, Turnstile and dashboard-origin keys
present, with no Resend key or sender. Values stayed masked. Email delivery and
the founder's actual account reset remain unverified until provider setup and
deployment. Local tests send no real emails and use only fixture credentials.

Validation: 52 focused backend tests passed, including real PostgreSQL/Redis
reset, old-password rejection, session revocation, audit and new login. The
frontend proxy/telemetry tests, production build/TypeScript, changed-file lint,
Bandit scan and focused mypy check passed. The desktop/mobile site browser
journey passed with email and CAPTCHA fixtures, including request retry,
generic acknowledgement, missing/expired links, URL scrubbing, confirmation,
same-tab link navigation and success. Artifacts:
`/tmp/scalecad-password-recovery-2026-10-11/`.
