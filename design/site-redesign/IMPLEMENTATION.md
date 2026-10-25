# A · Precise implementation

Implemented on `claude/site-redesign`. This PR is a separate marketing release; merge/deploy only after the product release.

Confirmed decisions from Nazeem:
- Logo C: turned-part mark, no period.
- Pro remains “Contact us”; the bracketed $149 / 50-check proposal is not published.
- Include backend enforcement of 15 lifetime work-email checks and 3 personal-email checks.

The public homepage, pricing, shared navigation/footer and magic-link signup use local Funnel Display, Funnel Sans and Martian Mono. Existing public routes retain their content and canonical URLs. The shared orange, white and motion tokens match the v4 object system. The real checked-in sample-part render replaces the canvas blob URL. Existing app fonts are also vendored to eliminate root-layout Google fetches.

Signup retains CAPTCHA, server proxy validation, rate limiting and managed-access configuration. `MAGIC_LINK_UI_ENABLED=1` and the existing Turnstile/email configuration are required for email signup; unavailable environments show an explicit fallback. Public-password signup remains available in development or where explicitly enabled.

The header verifies the session on the server and reads actual usage; it never substitutes example quotas. CAD selected on the homepage is kept in the same browser's IndexedDB for the email handoff, bound to the sign-in email and valid for two hours, removed on handoff or cancellation, then sent through the normal authenticated Verify flow. Opening the email in a different browser cannot transfer the local file; use the normal file picker there.

The product release merged during implementation already supplies backend 15/3 grants, shared email classification and account-bound file handoff. This branch reuses those implementations. Existing recorded grants are preserved by the product migration; paid/pilot entitlements and recheck exemptions are retained. Public allowance copy reads the backend plans configuration. The personal-domain list is curated, not employer verification.

Validation includes frontend unit tests/build/lint, database-backed quota concurrency/refund checks, the existing public-site journey across desktop/390px/320px, and a new isolated session/signup boundary test. The boundary test uses CAPTCHA/email fixtures and sends no real email. CI's full human/enterprise journeys remain required.

Local validation after integrating the product release: production builds with v4 off and on; lint with no errors; 1,209 frontend tests in UTC; 35 database-backed quota/tier tests on Python 3.12; public-route desktop/mobile journey; and signup/session/CAD/logout boundary checks with v4 both off and on. No tests were skipped. CI remains the release gate.

Pre-merge native coverage follow-up: XDE parsing now uses OCP 7.x static APIs
and retrieves the shape/GDT tools populated by the native STEP reader.
The test dependency set pins cadquery-ocp and its type stubs to 7.9.3.1.1 so the draft and both XDE
checks execute in CI; production dependencies are unchanged. Smoke-seed selection
uses a checked-in six-record public BCN3D manifest excerpt instead of requiring
private local data, and requires all six ontology keys. CI rejects every skipped
test, with session-local tracking that survives nested pytester runs. Merge and
deployment remain on hold until this follow-up passes all required checks.
