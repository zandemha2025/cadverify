# CadVerify Commercial Go-Live Runbook

This is the detailed Fly.io procedure for the commercial SaaS plane. It does
not authorize CUI/ITAR workloads; use `REGULATED_PRODUCTION_RUNBOOK.md` for that
plane. `SAAS_PRODUCTION_RUNBOOK.md` defines the acceptance bar and
`PRODUCTION_LAUNCH_AUDIT.md` records the current go/no-go verdict.

Production means isolated staging and production resources, immutable digest
promotion, successful automated and human acceptance tests, reviewed evidence,
and a non-blocking launch verdict. A running Fly app is not sufficient.

## 1. Accounts and owner-supplied inputs

Create or obtain these outside the repository. Set secrets directly in the
provider or GitHub/Fly secret store; never paste values into chat, source,
issues, logs, artifacts, or Helm values.

| Input | Purpose |
|---|---|
| Fly organization, four isolated app names, and scoped tokens | staging API/web and production API/web |
| Managed Postgres pooled and direct TLS URLs per environment | application traffic and migrations |
| TLS Redis URL per environment | arq, sessions, rate limits, worker health |
| Versioned/encrypted S3-compatible bucket and least-privilege credentials per environment | durable CAD/object data |
| Verified Resend sender/domain and Turnstile widget per environment | password/magic-link signup protection |
| Custom API and dashboard HTTPS domains per environment | runtime routing, cookies, magic links, monitoring |
| Backend Sentry DSN per environment and one commercial browser Sentry project | errors, release correlation, paging |
| External uptime/paging and accountable on-call owner | operational response |

Choose regions deliberately and record the latency, residency, backup, and
support implications. Do not put regulated data in these commercial resources.

## 2. Protect GitHub delivery

1. Protect `main`: require pull requests, complete CI, resolved conversations,
   no force pushes, and the repository's chosen approval count.
2. Create protected environments `saas-staging` and `saas-production`.
3. Require independent reviewers and deployment-branch protection on
   `saas-production`. Prevent self-review where the GitHub plan supports it.
4. In each environment set:

   - secret `FLY_API_TOKEN`, scoped to that environment's apps where possible;
   - secret `CADVERIFY_DEEP_HEALTH_TOKEN`, identical to that API app's
     `DEEP_HEALTH_TOKEN` Fly secret and used only by protected deploy gates;
   - variable `FLY_API_APP`;
   - variable `FLY_WEB_APP`;
   - variable `CADVERIFY_PUBLIC_API_BASE`, a canonical custom HTTPS API origin;
   - variable `CADVERIFY_DASHBOARD_ORIGIN`, a canonical custom HTTPS dashboard
     origin.

5. Set repository secrets:

   - `FLY_REGISTRY_TOKEN` for CI image publication, separate from deployment
     tokens; and
   - `NEXT_PUBLIC_SENTRY_DSN` for the commercial browser image.

The browser DSN is a build-time value. Staging and production promote the same
frontend digest, so browser events share a commercial project and are separated
by immutable release SHA plus runtime origin. Backend Sentry remains isolated by
environment and is tagged with `DEPLOYMENT_ENVIRONMENT`.

## 3. Provision isolated Fly apps

Create distinct names; the checked-in app names are defaults, while the
promotion workflow always passes the environment-specific `--app` value.

```bash
fly apps create <staging-api-app>
fly apps create <staging-web-app>
fly apps create <production-api-app>
fly apps create <production-web-app>
```

Do not create a shared durability volume. `backend/fly.toml` requires S3 and
uses `/tmp/cadverify/*` only for disposable scratch/cache. The promotion pins two
API, two worker, and two frontend Machines in each environment.

Configure custom certificates/DNS for both API and dashboard apps. Confirm the
custom origins are canonical HTTPS origins with no path, query, fragment, or
credentials:

```bash
node scripts/ops/validate-https-origin.mjs https://api.example.com
node scripts/ops/validate-https-origin.mjs https://app.example.com
```

## 4. Configure runtime secrets

Generate the random values locally:

```bash
CADVERIFY_FLY_APP=<target-api-app> \
CADVERIFY_FLY_WEB_APP=<target-web-app> \
bash scripts/ops/gen-launch-secrets.sh
```

The output is sensitive even though the script does not save it. Replace every
external placeholder and set values directly on the applicable app. Each
environment needs unique values. The generator writes the same newly generated
`AUTH_PROXY_SECRET` to the API and web apps; do not generate those separately.

Required base keys:

```text
DATABASE_URL
DATABASE_URL_DIRECT
REDIS_URL
SESSION_SECRET
DASHBOARD_SESSION_SECRET
AUTH_PROXY_SECRET
API_KEY_PEPPER
CONNECTOR_SECRET_KEY
CONNECTOR_FINGERPRINT_KEY
DEEP_HEALTH_TOKEN
MAGIC_LINK_SECRET
RESEND_API_KEY
RESEND_FROM
TURNSTILE_SECRET
```

Production storage/observability additionally requires:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
OBJECT_STORE_S3_BUCKET
OBJECT_STORE_S3_REGION
SENTRY_DSN
```

The web app requires `AUTH_PROXY_SECRET` and runtime `TURNSTILE_SITE_KEY`.
`TURNSTILE_SITE_KEY` is public, but runtime injection keeps the image digest
environment-neutral. `DASHBOARD_ORIGIN` is the protected GitHub environment
variable `CADVERIFY_DASHBOARD_ORIGIN`. Do not store deployment/auth mode flags
as Fly secrets: Fly secrets override reviewed deploy configuration, and the
gate rejects the complete shadowing list below.

Optional `OBJECT_STORE_S3_ENDPOINT` must be HTTPS. Omit it for AWS S3. Scope S3
credentials to the named bucket/prefix and only list/read/write/delete/multipart
operations needed by the application. Enforce bucket encryption, versioning,
public-access block, lifecycle/retention, and access logging outside the app.

The production startup guard also requires a 32+ character deep-health token,
canonical HTTPS `DASHBOARD_ORIGIN`,
`rediss://` Redis, and HTTPS Sentry/custom S3 endpoints. The migration uses
`DATABASE_URL_DIRECT`; the app uses the pooled URL.

Validate secret names without printing values:

```bash
FLY_APP_NAME=<target-api-app> \
CADVERIFY_REQUIRE_PRODUCTION_STORAGE=1 \
CADVERIFY_REQUIRE_OBSERVABILITY=1 \
CADVERIFY_FORBIDDEN_FLY_SECRETS=DASHBOARD_ORIGIN,AUTH_MODE,MAGIC_LINK_ENABLED,PASSWORD_LOGIN_ENABLED,PUBLIC_PASSWORD_SIGNUP_ENABLED,SESSION_COOKIE_DOMAIN,OBJECT_STORE_BACKEND,RELEASE,DEPLOYMENT_ENVIRONMENT,SECRET_ENFORCEMENT_ENABLED,WEBHOOK_SSRF_GUARD_ENABLED,SECURITY_HEADERS_ENABLED,RECONSTRUCTION_BACKEND,RECONSTRUCTION_ALLOW_REMOTE_EGRESS,PRODUCTION_STORAGE_REQUIRED,PRODUCTION_OBSERVABILITY_REQUIRED,PRODUCTION_TLS_REQUIRED,PRODUCTION_DEEP_HEALTH_AUTH_REQUIRED,PRODUCTION_AUTH_PROXY_REQUIRED,PRODUCTION_VERIFIED_SIGNUP_REQUIRED,PRODUCTION_HOST_ONLY_SESSION_COOKIE_REQUIRED,PRODUCTION_CRYPTO_SECRET_QUALITY_REQUIRED,PRODUCTION_SSRF_GUARD_REQUIRED,PRODUCTION_SECURITY_HEADERS_REQUIRED,ASYNC_STRICT_HEALTH,WORKER_STRICT_HEALTH,RATE_LIMIT_ALLOW_MEMORY,DB_REQUIRE_TLS,NODE_ENV \
node scripts/ops/fly-required-secrets-gate.mjs

FLY_APP_NAME=<target-web-app> \
CADVERIFY_REQUIRED_FLY_SECRETS=AUTH_PROXY_SECRET,TURNSTILE_SITE_KEY \
CADVERIFY_FORBIDDEN_FLY_SECRETS=AUTH_MODE,MAGIC_LINK_UI_ENABLED,PUBLIC_PASSWORD_SIGNUP_ENABLED,API_BASE,RELEASE,DEPLOYMENT_ENVIRONMENT,SSO_LOGIN_PATH,PRODUCTION_PUBLIC_API_TLS_REQUIRED,PRODUCTION_AUTH_PROXY_REQUIRED,PRODUCTION_VERIFIED_SIGNUP_REQUIRED,NODE_ENV \
node scripts/ops/fly-required-secrets-gate.mjs
```

The API captcha key is `TURNSTILE_SECRET`; the matching public web key is
`TURNSTILE_SITE_KEY`. `CONNECTOR_SECRET_KEY` must be a Fernet key; the generator
emits the correct format. Promotion calls `/api/auth/proxy-health` after both
deployments, proving the API/web HMAC secrets match without exposing them.

## 5. Build the release

Merge the reviewed change to protected `main`. `.github/workflows/ci.yml` then:

1. runs backend, frontend, auth, browser, migration, restore, static-analysis,
   and dependency gates;
2. validates Compose and renders/policy-checks Helm;
3. builds the Linux images from pinned bases and locked dependencies;
4. scans the exact image digests for high/critical vulnerabilities;
5. emits CycloneDX SBOMs; and
6. uploads `commercial-release-<sha>`, containing the SBOMs and a manifest that
   binds the commit to both digest-qualified images.

CI deliberately does not deploy production. Do not promote a SHA unless its
push-triggered CI workflow succeeded and its release artifact exists.

## 6. Promote staging, then production

From the Actions page on `main`, run **Commercial SaaS Promotion** with the exact
40-character release SHA. `.github/workflows/saas-promote.yml`:

1. finds the successful CI run for that SHA and downloads the CI-owned manifest;
2. validates the SHA, immutable digest references, origins, app isolation, and
   required backend secrets before mutation;
3. deploys the backend digest with a rolling strategy. The Fly release command
   runs `alembic upgrade head` using the direct DB URL;
4. pins two API and two worker Machines and requires Postgres, Redis, S3, queue,
   and worker-heartbeat deep health;
5. deploys the same release's frontend digest with runtime `API_BASE`, pins two
   frontend Machines, and probes the custom dashboard origin;
6. uploads a non-secret staging record; and
7. waits for the protected production approval. Production must use distinct
   apps/origins and exactly the staged image digests.

Database migrations are not undone by an application rollback. Review every
migration for backward compatibility and a compensating plan before approving
production.

Direct `fly deploy` is break-glass only because it bypasses staging evidence and
the digest linkage. Record incident/change approval before using it.

## 7. Acceptance evidence

Automated gates are necessary but not sufficient. In staging, then against the
production candidate where safe, retain evidence for all of the following:

- `GET /health` and token-authenticated `GET /health/deep` pass with Postgres,
  Redis, S3 write/read/list/delete, queue, and worker healthy. Keep deep health
  off public uptime checks; use `/health` for ordinary external liveness.
- Custom-domain TLS and required HTTP security headers pass inspection.
- A real user signs up, completes Turnstile, receives a magic link, logs in,
  logs out, and exercises logout-all/session revocation.
- A real STEP file completes upload, parsing, makeability/cost, persistence,
  PDF/export, and authorized deletion.
- Batch ZIP and reconstruction paths complete through S3 and workers.
- Two real organizations cannot read, mutate, download, or infer one another's
  objects; cross-tenant identifiers return the documented 404 behavior.
- S3 write/read/list/delete and lifecycle behavior match the intended prefix;
  public and cross-account access fail.
- A scrubbed test event reaches backend and browser Sentry, and an uptime alert
  reaches the on-call owner.
- Launch-profile load/soak has no 5xx and meets approved latency/queue targets;
  overload produces retryable 429 responses.
- Kill switch, prior-digest rollback, worker loss, and restore drills achieve
  the recorded RPO/RTO.

Re-run the live dependency gate when investigating or recording evidence:

```bash
CADVERIFY_API_URL=https://<target-api-domain> \
CADVERIFY_REQUIRE_WORKER=1 \
CADVERIFY_REQUIRE_WORKER_STRICT=1 \
CADVERIFY_REQUIRE_DEEP=1 \
CADVERIFY_DEEP_HEALTH_TOKEN=<matching-monitor-secret> \
node scripts/ops/fly-live-health-gate.mjs
```

## 8. Backups and operations

- Enable and monitor Postgres PITR/automated backups. Run
  `scripts/ops/postgres-restore-drill.sh` only against an approved scratch
  target; never use its in-place mode on production.
- Enable S3 versioning/lifecycle and test authorized deletion/restore behavior.
- Monitor auth failures, 5xx/429s, queue depth, worker heartbeat, DB/Redis/S3
  health, backup status, latency, certificate expiry, and spend.
- Review privileged access weekly during launch and monthly thereafter. Rotate
  immediately on suspected exposure.
- Patch critical issues within the approved emergency SLA; preserve review,
  test, and evidence even for emergency changes.

## 9. Rollback and kill switch

Use the previous known-good digest from a retained release/deployment record,
not a mutable tag. Confirm schema compatibility first, then deploy that digest
through an approved change or break-glass process. For immediate containment:

```bash
FLY_APP_NAME=<target-api-app> bash scripts/ops/kill-switch.sh off
```

This stops new analyses while preserving existing sessions/data. Restore with
`on` only after the incident owner accepts the recovery evidence.

## 10. Go/no-go

The target remains **BLOCKED** while any applicable finding in
`PRODUCTION_LAUNCH_AUDIT.md` is open. Only the accountable owner may change the
verdict after reviewing CI, staging, security, data-safety, operational, and
human acceptance evidence.
