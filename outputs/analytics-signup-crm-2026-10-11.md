# ScaleCad analytics, signup and CRM

## Implemented

- PostHog JS SDK after explicit analytics consent; Do Not Track respected. Opaque account IDs, sanitized route templates, campaign source, daily/weekly activity, API status/latency, web vitals and redacted errors. No email, phone, password, CAD contents, filenames or report payloads in analytics events.
- Supplied RB2B loader for account E63P0HY01JOW, with the request CSP nonce. Loads only after consent on public scalecad.ai URLs. Private paths and arbitrary queries/fragments are excluded. A follow-up permits only the vendor's homepage verification markers (`verifyge=true` and a 32-hex `ec_b2b` value). Consent is requested again because it now includes business visitor identification. Full document navigation clears the vendor runtime before app/auth links, and withdrawing consent reloads the document. The privacy page names RB2B and links its opt-out. Preview/local hosts do not load this vendor.
- Public-page replay only, masking all text, inputs and element attributes. Forms, canvas and private app/auth pages blocked. Network body/header and console recording disabled. Heatmaps restricted to `/`, `/pricing` and `/pilot`.
- Signup requires full name and email/password; phone is optional. Existing API clients remain compatible. Profile metadata validates timezone and bounded attribution; invalid optional attribution is discarded.
- Migration 0050 adds nullable profile fields and durable CRM synchronization markers without replacing any account or changing any password.
- Existing ARQ worker retries Notion sync, recovers accepted-create responses by opaque Account ID, preserves manually managed pipeline Status, and never selects credentials. Signup succeeds during a Notion outage. Existing active accounts are also queued for backfill.
- CRM stores signup timestamp in UTC, sampled last-seen timestamp, browser timezone, optional name/phone and campaign source. Country/region/city are approximate GeoIP context, never inferred from timezone or used for access decisions. A follow-up adds a dedicated-token callback and emits `account_context_synced` only after profile context succeeds, avoiding a consent persistence race. The callback validates the four allowed fields, requires an active consenting account, and requeues the existing worker only when nonempty location values change. Activation still needs the shared callback token and Notion runtime token.

## External configuration completed

PostHog project 654164 has raw IP discard enabled, session replay enabled with total privacy and a global private-page exclusion pattern, console/canvas/network-body capture disabled, and heatmaps enabled for the three public URLs. Exception autocapture, all four web vitals and the ScaleCad web analytics domain are enabled. Existing dashboard 2188568 was updated to ScaleCad and contains 11 charts using implemented events rather than unconnected booking/billing promises. Queries validated. Dashboard defaults to sessions starting on scalecad.ai, excluding localhost setup activity. Production pageviews and web vitals were verified in PostHog after deployment.

PR124 passed all nine CI checks and merged as e972561d9bc31e2b3ccda4d2b275f3d0c5d65ece. Render API, ARQ worker and web are Live on that commit; API logs confirm migration 0050 ran. The public write-only POSTHOG_PROJECT_TOKEN is active on cadverify-web. No PostHog secret API key or paid-plan change was made.

Notion CRM: https://app.notion.com/p/Client-List-CRM-176703f90aae83c58df8817e043c20f9
Workspace: Nazeem Ahmed’s Space under nazeem@scalecad.ai. Use the existing Clients database, not the earlier empty CRM created in Arcus.
Clients data source: 6e8703f9-0aae-8263-b7b8-070691bd03f0 (copied from Notion’s data-source actions; distinct from its database page ID).

The existing Contact Person, Email and Phone fields are reused. New accounts start in the existing native Status option New Lead. Company initially uses the individual’s name or email because signup does not collect a company; subsequent sync preserves Company and Status managed by sales. Ten tracking fields were added without replacing the template’s contacts, views or pipeline.

The approved ScaleCad CRM internal connection was created in the correct workspace, with read/update/insert capabilities, no Notion user information, and only the Clients database selected for content access. The correct data-source UUID is saved on the Render ARQ worker. The user still needs to copy the new integration token into the prepared NOTION_INTEGRATION_TOKEN field and save it directly in Render before sync can run. The chat connector cannot provide runtime website authentication.

## Validation

- 29 password/profile/CRM tests passed against isolated PostgreSQL, including anonymous rejection, metadata persistence, provider failure/retry, successful sync and credential exclusion.
- Full frontend test suite passed: 544 tests, including six focused analytics privacy tests.
- Production build and TypeScript passed; changed-file ESLint has no errors (one pre-existing navigation warning in AuthProvider).
- Chrome verified the four signup fields, required/optional behavior, consent decline, and no horizontal overflow at 320px. No real users or passwords were created for this UI check.
- Consenting Chrome preview sent real events successfully to PostHog. Query-string canary was removed; pageview, pageleave duration and web-vitals ingestion confirmed. Public SDK ingestion token and person-profile control survive scrubbing; private account tokens remain excluded.
- Five CRM tests passed against isolated PostgreSQL after adapting the existing Clients schema, including new-lead creation, duplicate prevention, sales-edit preservation and credential exclusion.
- Signup metadata retains PostgreSQL JSONB and uses the standard JSON type for SQLite-based SAML tests; all four SAML service tests pass.
- Profile context requests use fetch keepalive and consume the response stream so navigation does not cancel CRM metadata updates; full browser CI must pass after this repair.
- Evidence: `/tmp/scalecad-analytics-2026-10-11/`.

The location follow-up passes 54 backend tests (one Redis-dependent reset test skipped locally), all 547 frontend tests, build/TypeScript and changed-file lint with zero errors. Its authorization/consent/retry behavior was checked against isolated PostgreSQL. CI and deployment for this follow-up remain pending.

A real signup-to-Notion row, password email delivery, and authenticated capability-gap/equipment-ranking workflow remain unverified. Notion needs its runtime token; recovery is blocked by Turnstile 110200 (production hostname not authorized). No billing conversion, experiments, surveys, paid upgrade or external alert messages were launched.

## Location destination contract

Use a disabled HTTP Webhook destination until the callback release is live. Match only `account_context_synced`, `$current_url` starting with `https://scalecad.ai/`, and `distinct_id` matching `^scalecad-user-[1-9][0-9]{0,17}$`. POST to `https://cadverify-api.onrender.com/auth/crm/location`. Send only `account_id` from `event.distinct_id` and country/region/city from the corresponding `$geoip_country_name`, `$geoip_subdivision_1_name`, and `$geoip_city_name` event properties (empty string if unavailable). Keep response logging off.

The user must create a dedicated random token of at least 32 characters, enter it into API environment `POSTHOG_CRM_WEBHOOK_TOKEN`, and enter the same value in the destination's `Authorization: Bearer …` header. Do not reuse a Notion token or broad API credential. No raw IP, full event, person object, email, phone, password or CAD data belongs in this payload.

RB2B setup already lists scalecad.ai and the supplied account key, with status Not verified. Its exact CloudFront script URL currently returns HTTP 403 (including with a scalecad.ai referrer). Loader and URL/consent exclusions have focused tests; production RB2B activation and downstream CSP requirements remain unverified until the vendor serves the script. Existing CSP has not been broadly relaxed to unknown vendor endpoints.
