# CadVerify — Production Deploy Handoff (for Cowork)

**Paste this whole file to Cowork as the task.** It's the context + decisions +
acceptance bar. The step-by-step commands live in **`docs/LAUNCH_RUNBOOK.md`** —
this document tells you how to use it and what must not be missed.

---

## 0. What you're doing (read first)

You are deploying **CadVerify** — a CAD manufacturing-cost / DFM / makeability
platform (FastAPI backend + gmsh geometry engine + arq worker + Next.js frontend
+ Postgres + Redis) — to production so **10 real organizations** (oil & gas,
automotive, aerospace/defense, job-shops) can sign up and use it. Auth is
**password + magic-link (no Google)**.

The application has strong test and isolation evidence, but the production
program is not complete until the commercial or regulated runbook passes. Use
`docs/DUAL_PRODUCTION_ARCHITECTURE.md` to select the plane. Specifically, in the current
branch:
- Backend and frontend regression gates are wired into CI; use the current
  commit's CI evidence rather than this document as a test-count claim.
- Auth: password + magic-link works without Google. The magic token is exchanged
  server-to-server into a first-party dashboard session, and a signed client-IP
  handoff keeps Redis abuse limits correct behind the web proxy. Missing or
  mismatched launch secrets fail deployment/handshake, not the first login.
  Released session checks also fail closed when database-backed revocation state
  is unavailable.
- Multi-tenant isolation is verified (cross-org reads → 404, no leaks).
- Per-org rate limits + daily quota (fail-open) guard against noisy neighbors.
- A load-critical bug (one heavy STEP freezing all tenants) is fixed + verified.
- **10-org concurrency load-tested + verified:** a burst of 70 concurrent uploads
  across 10 orgs returns **0% 5xx** — excess load gets an honest, retryable
  **429 + Retry-After** (admission control), `/health` stays responsive, and no
  org can starve the others (per-org concurrency cap). (Before this fix the same
  burst 500'd 55% of requests via DB-pool exhaustion.)
- Deploy config, secrets gate, and health gates are wired.
- Protected CI now fails on any unapproved pytest skip, including collection-
  time/module skips. The only allowlisted
  skips are the operator-owned local corpus assertion and two optional OCP-XDE
  checks; costing, AS1 assembly, NIST STEP, and cleanup coverage run from
  reproducible fixtures. The costing suite is generated from internally authored
  regression geometry; the historical third-party geometry archive is never
  fetched or vendored without per-model license review. GitHub corpus imports
  resolve mutable refs to commits, verify and hash the license artifact at that
  same commit, and persist immutable source/license provenance. These coupons are not
  supplier quotes and cannot satisfy the production-accuracy gate. That gate
  requires a provenance-locked holdout of at least 20 independently quoted
  parts with MAPE ≤30%, P90 absolute error ≤50%, and every process median bias
  within ±25%.
- OIDC token verification uses the maintained `joserfc` API with an explicit
  RS256 allowlist and required issuer/subject/audience/expiry/issued-at claims,
  not-before enforcement, nonce validation, userinfo-subject matching, and
  multi-audience coverage. Discovery requires an exact non-empty issuer and
  validates every authorization, token, JWKS, and userinfo endpoint before use:
  HTTPS, no embedded credentials, a reviewed origin, and no private, loopback,
  link-local, metadata, or reserved destination. OIDC accounts bind to immutable
  `(issuer, subject)` rows; verified email may bootstrap only a brand-new account
  and can never silently rebind an existing one. This does not change the
  regulated plane's SAML-only launch boundary.
- Compliance-audit rows commit in the same database transaction as protected
  mutations; OIDC, SAML, and magic-link provisioning, membership/key state, and
  login events commit once before a session is issued. API-key rotation revokes,
  replaces, and audits in one transaction. Magic-link token rotation and failure
  cleanup use cluster-safe atomic Redis compare-and-set state, so delayed provider
  failures cannot revoke a newer link. There is no detached audit queue to
  lose at shutdown. Timed-out or abandoned untrusted CAD workers are hard-killed;
  the application lifespan prevents parse-pool recreation during bounded teardown,
  disposes the DB, and performs one bounded tracing shutdown off the event loop.
  Runtime/unawaited-coroutine warnings are blocking test failures rather than
  ignorable CI noise.

**Honest capacity note:** the commercial baseline runs two API and two worker
Machines. Each API Machine still has a finite CPU-bound analysis ceiling;
overload is admitted as retryable 429 rather than 5xx. Prove the launch workload
in isolated staging before promotion. S3 is mandatory and all Fly-local files
are disposable scratch/cache, so no Machine volume is a data source of truth.

## 1. Current code state

- The production-hardening work is on **`codex/dual-production-readiness`** and
  is not merged to `main`. Draft PR **#24** targets `main`; the obsolete PR #23
  targets `prod` and must not be used for release.
- A push to protected `main` runs CI and creates scanned digest/SBOM release
  evidence. It does **not** deploy production. Commercial deployment is the
  protected staging-then-production workflow; regulated release and deployment
  use their separate protected workflows and require green CI for the exact
  regulated source SHA.
- The regression gate for ANY code change is the full backend suite
  (`cd backend && .venv/bin/python -m pytest -q`). Do not ship a red suite.

## 2. Decisions to confirm with the human BEFORE provisioning

1. **Where to host.** The repo default is **Fly.io** (`backend/fly.toml` app
   `cadvrfy-api`, `frontend/fly.toml` app `cadvrfy-web`) — fastest to stand up,
   the commercial SaaS path. Alternatives already supported by the repo:
   - **Kubernetes** (AWS EKS / GCP GKE / Azure AKS / on-prem) via the Helm chart
     in `charts/cadverify/` — the enterprise-standard path.
   - **Self-host** via `docker-compose.yml`, or the air-gapped
     `cadverify-enterprise/` bundle (SAML) — **likely required for a
     defense/ITAR customer** that can't use public multi-tenant cloud.
   Use **AWS GovCloud EKS or an approved customer-controlled Kubernetes target**
   for regulated/CUI/ITAR workloads; do not mix those workloads into Fly SaaS.
2. **Object store.** **S3 is mandatory in production.** Fly-local files are
   ephemeral scratch/cache only.
3. **Domain** for `DASHBOARD_ORIGIN` (magic-link URLs + cookie origin + CORS).

## 3. Prerequisites the HUMAN must supply (you can't create these)

| What | Where to get it | Env var(s) |
|---|---|---|
| Fly.io account + `flyctl` auth | fly.io | (login) |
| Managed Postgres (Neon / RDS / Cloud SQL) — **pooled + direct URLs** | provider | `DATABASE_URL`, `DATABASE_URL_DIRECT` |
| Redis (Upstash / Fly Redis / ElastiCache) | provider | `REDIS_URL` |
| Resend account + **verified sending domain** | resend.com | `RESEND_API_KEY`, `RESEND_FROM` |
| Cloudflare Turnstile | cloudflare | API `TURNSTILE_SECRET`; web `TURNSTILE_SITE_KEY` |
| A domain | registrar/DNS | `DASHBOARD_ORIGIN` |
| S3 bucket + least-privilege creds | AWS/approved compatible provider | `OBJECT_STORE_BACKEND=s3`, `OBJECT_STORE_S3_*` |
| Sentry projects and alert path | sentry.io | `SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_DSN` |
| GovCloud/customer regulated landing zone + authorized U.S.-person operators | AWS/customer + legal/security owners | EKS/RDS/Redis/S3/KMS/ECR/IdP/OTLP/private values/runner evidence |
| CUI/ITAR scope, system boundary, data flow, and authorization | export-control counsel + accountable security owner | written approval/evidence, not an application env var |
| Licensed supplier-quote accuracy holdout | launch customers / sourcing owner | 20+ provenance-locked parts, 3+ suppliers, reviewed approval, and release-bound evidence meeting `docs/SUPPLIER_HOLDOUT_EVIDENCE.md` |

Note: **Neon is just managed Postgres and Fly is just a container host — neither
is load-bearing in the code.** Swapping Postgres providers is a connection-string
change; moving off Fly is the Helm/compose path above.

## 4. The deploy sequence — follow `docs/LAUNCH_RUNBOOK.md` exactly

That runbook is authoritative. The spine:

1. **Provision** isolated staging and production Fly API/frontend apps and the
   external Postgres, Redis, S3, email, DNS, and monitoring resources. Do not
   provision a shared `/data` volume as a durability mechanism.
2. **Secrets**: run
   `CADVERIFY_FLY_APP=<target-api-app> CADVERIFY_FLY_WEB_APP=<target-web-app>
   bash scripts/ops/gen-launch-secrets.sh`
   — it generates the
   random secrets (`os.urandom(32)`) as ready-to-paste `fly secrets set` lines and
   marks the external ones `<FILL_ME: ...>`. Set them all (runbook §4).
3. **Object store** (runbook §4) — configure mandatory production S3.
4. **Release**: merge to protected `main`; CI builds/scans and records the exact
   release SHA and image digests.
5. **Accuracy evidence and promotion**: evaluate that exact release against the
   frozen holdout, then place the reviewed base64 summary from
   `docs/SUPPLIER_HOLDOUT_EVIDENCE.md` in both protected environment secrets
   named `CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_B64`. Run **Commercial SaaS
   Promotion** with the same SHA. Staging and production independently revalidate
   the evidence; production also requires its digest to match staging. Either
   job refuses to deploy missing, stale, changed, or failing evidence. Staging
   must pass before protected production approval is available. Migrations run
   via `release_command`; break-glass direct deploy is not the normal path.
6. **Verify** (runbook §7) — see acceptance bar below.

## 5. Acceptance criteria — do NOT declare "done" until ALL pass

- [ ] `FLY_APP_NAME=<target-api-app> node scripts/ops/fly-required-secrets-gate.mjs`
      passes with production
      storage and observability requirements enabled.
- [ ] The web secret gate requires `AUTH_PROXY_SECRET,TURNSTILE_SITE_KEY`, and
      `GET /api/auth/proxy-health` passes after deploy.
- [ ] `CADVERIFY_DEEP_HEALTH_TOKEN=<matching monitor secret> node
      scripts/ops/fly-live-health-gate.mjs` passes, and authenticated
      `GET /health/deep`
      shows **postgres + redis + worker all green** (not degraded).
- [ ] A real person can **sign up by verified magic link, set an initial password
      in Settings → Security, sign out, and log in by password.** Public direct
      password signup remains disabled. (If no email arrives, inspect Resend.)
- [ ] A real **STEP upload returns a cost/verdict** (upload `cube.step` or any
      real part).
- [ ] `python -m src.costing.harness --require-production-evidence` passes on
      the licensed supplier-quote holdout. Internally authored coupons and the
      historical geometry-only archive are regression evidence only.
- [ ] **Two different orgs cannot see each other's data** (spot-check a
      cost-decision id across two accounts → 404).
- [ ] (Recommended) run `node scripts/ops/load-profile.mjs` with
      `CADVERIFY_API_URL=<deployed url>` and confirm `/health` p95 stays low and
      the cost path completes without 5xx.
- [ ] `docs/PRODUCTION_LAUNCH_AUDIT.md` no longer has a blocking finding for
      the target plane, with closure evidence reviewed by the accountable owner.

## 6. Critical gotchas (these silently break a launch)

1. **Real secrets, not the dev stubs.** The dev runbook uses well-known
   `base64('a'/'b'/'c'*32)` and `SESSION_SECRET=dev` / `TURNSTILE_SECRET=test`.
   These are PUBLIC. Use the values from `gen-launch-secrets.sh`. Released
   startup now rejects absent, malformed, short, common-development, and obvious
   repeated-byte/low-entropy cryptographic stubs; do not weaken or bypass that
   gate.
2. **Magic-link needs email.** It's enabled via `AUTH_MODE=password` +
   `MAGIC_LINK_ENABLED=true` (already set in `backend/fly.toml`) **plus** the
   Resend pair (`RESEND_API_KEY`, `RESEND_FROM`) and protected runtime
   `CADVERIFY_DASHBOARD_ORIGIN`. No email
   creds ⇒ no login links go out ⇒ users can't get in.
3. **Turnstile uses two keys:** API `TURNSTILE_SECRET` and web
   `TURNSTILE_SITE_KEY`. Do not use `TURNSTILE_SECRET_KEY`.
4. **Deployment controls must not be Fly secrets.** Fly secrets override
   `fly.toml` and deploy-time `--env` values. The promotion gate rejects stale
   shadowing secrets, including `DASHBOARD_ORIGIN`, auth/storage/release mode,
   every `PRODUCTION_*` guard, strict-health controls, reconstruction egress,
   `RATE_LIMIT_ALLOW_MEMORY`, `PARSE_PROCESS_POOL_DISABLED`, and `NODE_ENV`. Keep
   `CADVERIFY_DASHBOARD_ORIGIN` as the protected GitHub environment variable
   and remove every forbidden name reported by the gate before promotion.
5. **`AUTH_PROXY_SECRET` must be identical on the API and web apps.** Generate
   it once with the launch generator; promotion proves the pair with the
   proxy-health handshake.
6. **Enable Postgres backups (Neon PITR / RDS automated backups)** — this is a
   provider dashboard toggle, not in the repo. Then run
   `scripts/ops/postgres-restore-drill.sh` against a scratch DB to prove restore.
7. **Frontend availability**: `frontend/fly.toml` is set to
   `min_machines_running = 2`; do not reduce it for production.
8. **Regulated auth is SAML-only in the approved baseline.** The application
   contains OIDC code, but the protected regulated workflow and manifest gate
   intentionally require SAML until a separate OIDC boundary/release review is
   completed. Do not relabel an unreviewed OIDC overlay as production-ready.

## 7. Post-launch

- Uptime monitor on `/health`; billing alerts on Fly + the DB provider; confirm
  Sentry is receiving (if DSN set).
- **Per-org rate tunables** (adjust from real usage via the admin usage summary):
  `ORG_RATE_LIMIT_PER_HOUR` (2000), `ORG_RATE_LIMIT_PER_DAY` (20000),
  `ORG_ANALYSES_PER_DAY` (5000). Kill-switch: `ORG_RATE_LIMIT_DISABLED` (only
  bypasses outside a real `RELEASE`).
- **Capacity / concurrency tunables** (the load-tested admission gate):
  `MAX_CONCURRENT_ANALYSES` (8 per web machine — keep it under `DB_POOL_SIZE +
  DB_MAX_OVERFLOW`), `MAX_CONCURRENT_ANALYSES_PER_ORG` (3 — fairness),
  `DB_POOL_SIZE` (10 → 20 slots), `DB_POOL_TIMEOUT` (10s), `DB_POOL_RECYCLE`
  (300s). Kill-switch: `ADMISSION_DISABLED` (bypass only outside `RELEASE`).
- **If users see "server busy, retry" (429 `server_busy`) too often** under real
  load, in order: (1) `fly scale count web=N` (linear capacity — each machine adds
  ~8 concurrent), (2) raise `MAX_CONCURRENT_ANALYSES` **and** `DB_POOL_SIZE`
  together (keep the cap under the pool, and the pool under the DB provider's
  connection budget × machines), (3) implement the staged "release DB session
  during compute" follow-up to admit more per machine. **Never** raise the cap
  above the pool — that reintroduces the 500s the admission gate exists to prevent.

## 8. Rollback

- Use the previous retained digest through the approved rollback process
  (runbook §9). Kill-switch
  script: `scripts/ops/kill-switch.sh`.

---

**Summary for the human:** the repository contains production gates, but no
environment is production until its runbook and security verdict pass with real
infrastructure. Give the operator access to the accounts in §3 without pasting
credentials into chat, follow the applicable runbook, and hold the release to the
§5 acceptance bar.
