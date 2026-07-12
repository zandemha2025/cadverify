# Commercial SaaS Production Runbook

This tightens `LAUNCH_RUNBOOK.md` from beta-ready to production-required. The
existing Fly deployment is staging until every gate below passes.

## Required environment split

| Resource | Staging | Production |
|---|---|---|
| Fly apps | separate API/web app names | separate production API/web app names |
| Postgres | separate project/database | production project with PITR |
| Redis | separate instance | production TLS instance with persistence/HA as supported |
| Object store | separate bucket/prefix | versioned encrypted production bucket |
| Email | test sender/domain | verified production domain |
| Sentry | isolated backend environment | production backend environment; shared browser project tagged by runtime origin |
| Secrets | unique values | unique production values; never copied from staging |

## Production prerequisites

1. Custom frontend and API HTTPS domains with DNS ownership.
   Route the frontend directly through Fly Proxy. If another reverse proxy is
   introduced, do not launch until its trusted-client-IP parsing and direct-
   origin bypass controls are explicitly designed and tested; the default
   auth handoff intentionally trusts only Fly's `Fly-Client-IP` header.
2. Managed Postgres pooled and direct TLS URLs; PITR and automated backups enabled.
3. Managed Redis using a `rediss://` URL, sized for queue/rate-limit traffic.
4. S3-compatible bucket with encryption, versioning, lifecycle rules, access
   logging, and least-privilege credentials.
5. Resend verified sender domain and Cloudflare Turnstile widget.
6. Backend and frontend Sentry DSNs plus external uptime/paging.
7. Protected GitHub environments `saas-staging` and `saas-production`. In each,
   set environment variables `FLY_API_APP`, `FLY_WEB_APP`,
   `CADVERIFY_PUBLIC_API_BASE`, and `CADVERIFY_DASHBOARD_ORIGIN`, plus an
   environment-scoped `FLY_API_TOKEN` and `CADVERIFY_DEEP_HEALTH_TOKEN`
   secrets. The latter must match the target API app's `DEEP_HEALTH_TOKEN`.
   Values must identify isolated
   resources; the production workflow rejects staging app/origin reuse.
8. Repository secret `NEXT_PUBLIC_SENTRY_DSN`. It is baked into the single
   commercial browser image; events carry the immutable release SHA and runtime
   origin tag. Backend Sentry DSNs remain unique Fly secrets per environment.
9. Required reviewers and deployment-branch protection on `saas-production`;
   protect `main` with the complete CI workflow as a required check.
10. A licensed, provenance-locked supplier holdout and accountable reviewer
    satisfying `SUPPLIER_HOLDOUT_EVIDENCE.md`. The reviewed summary for each
    exact release is stored under the same
    `CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_B64` secret name in both protected
    environments so production can revalidate freshness after its approval wait.

## Pre-deploy

1. Resolve and review the canonical promotion PR to protected `main`.
2. Generate production-only random secrets:

   ```bash
   CADVERIFY_FLY_APP=<target-api-app> \
   CADVERIFY_FLY_WEB_APP=<target-web-app> \
   bash scripts/ops/gen-launch-secrets.sh
   ```

   Fill the external placeholders locally and set them directly in Fly. The
   generated `AUTH_PROXY_SECRET` must be identical on that API/web pair. Do not
   paste values into chat, issues, commits, CI logs, or runbooks.

3. Run the mandatory secret gate:

   ```bash
   CADVERIFY_REQUIRE_PRODUCTION_STORAGE=1 \
   CADVERIFY_REQUIRE_OBSERVABILITY=1 \
   CADVERIFY_FORBIDDEN_FLY_SECRETS=DASHBOARD_ORIGIN,AUTH_MODE,MAGIC_LINK_ENABLED,PASSWORD_LOGIN_ENABLED,PUBLIC_PASSWORD_SIGNUP_ENABLED,SESSION_COOKIE_DOMAIN,OBJECT_STORE_BACKEND,RELEASE,DEPLOYMENT_ENVIRONMENT,SECRET_ENFORCEMENT_ENABLED,WEBHOOK_SSRF_GUARD_ENABLED,SECURITY_HEADERS_ENABLED,RECONSTRUCTION_BACKEND,RECONSTRUCTION_ALLOW_REMOTE_EGRESS,PRODUCTION_STORAGE_REQUIRED,PRODUCTION_OBSERVABILITY_REQUIRED,PRODUCTION_TLS_REQUIRED,PRODUCTION_DEEP_HEALTH_AUTH_REQUIRED,PRODUCTION_AUTH_PROXY_REQUIRED,PRODUCTION_VERIFIED_SIGNUP_REQUIRED,PRODUCTION_HOST_ONLY_SESSION_COOKIE_REQUIRED,PRODUCTION_CRYPTO_SECRET_QUALITY_REQUIRED,PRODUCTION_SSRF_GUARD_REQUIRED,PRODUCTION_SECURITY_HEADERS_REQUIRED,ASYNC_STRICT_HEALTH,WORKER_STRICT_HEALTH,RATE_LIMIT_ALLOW_MEMORY,PARSE_PROCESS_POOL_DISABLED,DB_REQUIRE_TLS,NODE_ENV \
   FLY_APP_NAME=<target-api-app> \
   node scripts/ops/fly-required-secrets-gate.mjs

   FLY_APP_NAME=<target-web-app> \
   CADVERIFY_REQUIRED_FLY_SECRETS=AUTH_PROXY_SECRET,TURNSTILE_SITE_KEY \
   CADVERIFY_FORBIDDEN_FLY_SECRETS=AUTH_MODE,MAGIC_LINK_UI_ENABLED,PUBLIC_PASSWORD_SIGNUP_ENABLED,API_BASE,RELEASE,DEPLOYMENT_ENVIRONMENT,SSO_LOGIN_PATH,PRODUCTION_PUBLIC_API_TLS_REQUIRED,PRODUCTION_AUTH_PROXY_REQUIRED,PRODUCTION_VERIFIED_SIGNUP_REQUIRED,NODE_ENV \
   node scripts/ops/fly-required-secrets-gate.mjs
   ```

4. Run the full backend suite and frontend type/test/build/lint gates.
5. Restore the latest production-like backup into a scratch database and record
   the measured result.

## Deploy and verify

Merge the reviewed SHA to protected `main`. CI tests the application, builds and
scans both images, creates SBOMs, and uploads a CI-owned release manifest with
their immutable digests. CI does **not** deploy production.

Evaluate that exact 40-character main SHA against the frozen supplier holdout,
retain the confidential artifacts and human approval, and set the base64
summary described in `SUPPLIER_HOLDOUT_EVIDENCE.md` on the protected
`saas-staging` and `saas-production` environments. Then run **Commercial SaaS
Promotion** on `main` with the same SHA and
`promotion_scope=staging-and-production`. The workflow:

1. requires a successful push-triggered CI run for the SHA and downloads its
   immutable release manifest;
2. fails closed unless the protected holdout is recent, release-bound,
   provenance-locked, independently approved, sufficiently sampled per launch
   family, and within every accuracy gate;
3. validates staging HTTPS origins, API/web Fly secrets, the absence of every
   forbidden auth/release/storage/guard shadowing secret, and image manifests;
4. deploys the digest-qualified backend, runs the migration, scales two API and
   two workers, and requires deep health before deploying two frontend Machines;
   it then proves the signed client-IP auth proxy end to end;
5. records staging evidence, including only the holdout summary digest; then
6. pauses at the protected `saas-production` environment. After reviewer
   approval, it revalidates evidence freshness, requires an exact match to the
   staging evidence digest, rejects staging resource reuse, and promotes the
   exact same image digests through the same gates.

The frontend image contains no API hostname. `API_BASE` and the deployment
environment are supplied only at runtime. Fly machine files are disposable
scratch/cache; S3 is the only production object source of truth.

Re-run the live gate with deep dependency checks:

```bash
CADVERIFY_API_URL=https://<production-api-domain> \
CADVERIFY_REQUIRE_WORKER=1 \
CADVERIFY_REQUIRE_WORKER_STRICT=1 \
CADVERIFY_REQUIRE_DEEP=1 \
CADVERIFY_DEEP_HEALTH_TOKEN=<matching-monitor-secret> \
node scripts/ops/fly-live-health-gate.mjs
```

The release remains blocked until all of these pass:

- Custom-domain TLS and HTTP security headers.
- Public `/metrics` returns 404 (`METRICS_ENABLED=0`); SaaS monitoring uses
  Sentry plus token-protected deep health unless a separately reviewed private
  scraper path is introduced.
- `/health` and token-authenticated `/health/deep`: Postgres, Redis, S3, queue,
  and worker healthy.
- Real email-first signup, magic-link delivery/click/login, one-time initial
  password setup under Settings → Security, subsequent password login, and
  logout-all. Public unverified password signup must remain disabled.
- `/api/auth/proxy-health` passes and password/magic abuse limits distinguish
  real client IPs instead of one shared frontend-machine address. Unsigned
  direct calls to session-returning password/magic API endpoints must fail.
- Real STEP upload, cost/verdict, persisted decision, export, and deletion path.
- Protected supplier-quote evidence for the exact release passes the 20+ part,
  3+ supplier, launch-family coverage, MAPE/P90, process-bias, provenance,
  tuning-separation, freshness, and approval gates.
- Two-organization isolation probe returns 404 across tenants.
- S3 write/read/delete and lifecycle evidence.
- Sentry receives a scrubbed test event; uptime alert reaches the on-call path.
- Load profile has no 5xx; overload returns retryable 429.
- Kill switch and previous-image rollback are exercised in staging.
- The staging deployment record and CI digest/SBOM artifact name the same SHA
  and image digests later presented for production approval.

## Production operations

- Weekly access and failed-auth review during launch; monthly thereafter.
- Daily backup status checks and quarterly restore drills.
- Dependency/image patch SLA: critical 24 hours, important 7 days, routine 30
  days, subject to risk review.
- Monthly secret inventory; rotate immediately after suspected exposure.
- Capacity review from queue depth, 429s, database connections, CPU, and worker
  heartbeat. Scale machines before increasing concurrency caps.
