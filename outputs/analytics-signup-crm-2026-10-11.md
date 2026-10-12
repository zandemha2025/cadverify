# ScaleCad analytics, signup and CRM

## Implemented

- PostHog JS SDK after explicit analytics consent; Do Not Track respected. Opaque account IDs, sanitized route templates, campaign source, daily/weekly activity, API status/latency, web vitals and redacted errors. No email, phone, password, CAD contents, filenames or report payloads in analytics events.
- Public-page replay only, masking all text, inputs and element attributes. Forms, canvas and private app/auth pages blocked. Network body/header and console recording disabled. Heatmaps restricted to `/`, `/pricing` and `/pilot`.
- Signup requires full name and email/password; phone is optional. Existing API clients remain compatible. Profile metadata validates timezone and bounded attribution; invalid optional attribution is discarded.
- Migration 0050 adds nullable profile fields and durable CRM synchronization markers without replacing any account or changing any password.
- Existing ARQ worker retries Notion sync, recovers accepted-create responses by opaque Account ID, preserves manually managed pipeline Status, and never selects credentials. Signup succeeds during a Notion outage. Existing active accounts are also queued for backfill.
- CRM stores signup timestamp in UTC, sampled last-seen timestamp, browser timezone, optional name/phone and campaign source. Country/region/city fields exist but are not inferred from timezone. Automatic CRM GeoIP enrichment is not connected; approximate GeoIP location is available in PostHog after consenting traffic arrives.

## External configuration completed

PostHog project 654164 has raw IP discard enabled, session replay enabled with total privacy and a global private-page exclusion pattern, console/canvas/network-body capture disabled, and heatmaps enabled for the three public URLs. Exception autocapture, all four web vitals and the ScaleCad web analytics domain are enabled. Existing dashboard 2188568 was updated to ScaleCad and contains 11 charts using implemented events rather than unconnected booking/billing promises. Queries validated. Dashboard defaults to sessions starting on scalecad.ai, excluding localhost setup activity. Production charts remain empty until the instrumented release deploys.

The public write-only POSTHOG_PROJECT_TOKEN is saved on Render cadverify-web for the next deployment. No PostHog secret API key or paid-plan change was made.

Notion CRM: https://www.notion.so/ebb2f38f76f341dba036b7c78b290651
Data source: 487fc305-1834-4b27-959f-767c54e91648

Automatic sync still needs an internal Notion integration shared with this CRM. Add its token as NOTION_INTEGRATION_TOKEN and the data-source UUID as NOTION_CRM_DATA_SOURCE_ID to the ARQ worker, then deploy. The chat connector cannot provide runtime website authentication. Secrets must be entered directly in Render.

## Validation

- 29 password/profile/CRM tests passed against isolated PostgreSQL, including anonymous rejection, metadata persistence, provider failure/retry, successful sync and credential exclusion.
- Full frontend test suite passed: 544 tests, including six focused analytics privacy tests.
- Production build and TypeScript passed; changed-file ESLint has no errors (one pre-existing navigation warning in AuthProvider).
- Chrome verified the four signup fields, required/optional behavior, consent decline, and no horizontal overflow at 320px. No real users or passwords were created for this UI check.
- Consenting Chrome preview sent real events successfully to PostHog. Query-string canary was removed; pageview, pageleave duration and web-vitals ingestion confirmed. Public SDK ingestion token and person-profile control survive scrubbing; private account tokens remain excluded.
- Profile context requests use fetch keepalive so navigation does not cancel CRM metadata updates; full browser CI is rerunning after this repair.
- Evidence: `/tmp/scalecad-analytics-2026-10-11/`.

Production analytics ingestion, a real signup-to-Notion row, password email delivery, and authenticated capability-gap/equipment-ranking workflow remain unverified until deployment and missing provider credentials are supplied. No billing conversion, experiments, surveys, paid upgrade or external alert messages were launched.
