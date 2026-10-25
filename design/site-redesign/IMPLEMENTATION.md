# A · Precise implementation

Implemented on `claude/site-redesign`. This PR is a separate marketing release; merge/deploy only after the product release.

Confirmed decisions from Nazeem:
- Logo C: turned-part mark, no period.
- Pro remains “Contact us”; the bracketed $149 / 50-check proposal is not published.
- Include backend enforcement of 15 lifetime work-email checks and 3 personal-email checks.

The public homepage, pricing, shared navigation/footer and magic-link signup use local Funnel Display, Funnel Sans and Martian Mono. Existing public routes retain their content and canonical URLs. The shared orange, white and motion tokens match the v4 object system. The real checked-in sample-part render replaces the canvas blob URL. Existing app fonts are also vendored to eliminate root-layout Google fetches.

Signup retains CAPTCHA, server proxy validation, rate limiting and managed-access configuration. `MAGIC_LINK_UI_ENABLED=1` and the existing Turnstile/email configuration are required for email signup; unavailable environments show an explicit fallback. Public-password signup remains available in development or where explicitly enabled.

The header verifies the session on the server and reads actual usage; it never substitutes example quotas. CAD selected on the homepage is kept in the same browser's IndexedDB for the email handoff, valid for one hour, removed on handoff or cancellation, then sent through the normal authenticated Verify flow. Opening the email in a different browser cannot transfer the local file; use the normal file picker there.

The backend derives the cap from the stored account email. Completed checks and saved results are not reset; paid/pilot entitlement is unchanged. Existing trial accounts receive the new tier too, so a personal account with three or more completed/reserved checks has no remaining free checks. No schema migration is required. Personal-domain recognition is shared by behavior with a frontend/backend parity test; it is a curated domain list, not employer verification.

Validation includes frontend unit tests/build/lint, database-backed quota concurrency/refund checks, the existing public-site journey across desktop/390px/320px, and a new isolated session/signup boundary test. The boundary test uses CAPTCHA/email fixtures and sends no real email. CI's full human/enterprise journeys remain required.
