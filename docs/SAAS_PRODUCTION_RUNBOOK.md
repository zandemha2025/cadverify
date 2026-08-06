# ProofShape commercial SaaS production runbook

This document is the production acceptance overlay for
`docs/LAUNCH_RUNBOOK.md`. The canonical platform is AWS commercial
CloudFront/ECS/RDS/ElastiCache/S3. It is not the regulated/CUI plane.

The Fly-era deployment design and files are legacy/non-release references. No
current ProofShape release workflow targets Fly, and the obsolete
`.github/workflows/saas-promote.yml` remains deleted.

## Required environment split

| Resource | Staging | Production |
|---|---|---|
| AWS boundary | isolated account when available, state, VPC, CIDR, keys | separate account when available and independent state/network/keys |
| GitHub environment | `aws-commercial-staging` | `aws-commercial-production`, protected reviewers |
| Public edge | generated CloudFront HTTPS hostname allowed | custom alias, viewer/origin ACM certificates, TLS 1.2 |
| Origin | internal ALB through its CloudFront VPC origin | separate internal ALB/VPC origin, deletion protection |
| ECS | budget profile may run one frontend/API/worker task | HA profile requires at least two of each plus autoscaling floor |
| Postgres | isolated encrypted RDS; restore still required | Multi-AZ, PITR, retained backups/final snapshot/deletion protection |
| Redis | isolated TLS/AUTH node; no HA claim for one node | TLS/AUTH multi-node automatic failover |
| Durable S3 | isolated KMS/versioned evidence bucket | isolated KMS/versioned bucket with production retention |
| Transient S3 | isolated KMS/unversioned incoming-upload bucket | same physical-delete contract with separate lifecycle |
| Providers | staging Resend/Turnstile/Sentry/alerts | independently approved production provider configuration |
| Secrets | unique values | unique values; never copied from staging except release-invariant public browser DSN when approved |

No hostname, account, bucket, repository, key, secret, billing relationship, or
provider project may come from Arcus.

## Production prerequisites

1. `product-proven` and `cloud-deploy-ready` are recorded for one exact clean
   commit under `docs/PRODUCTION_ACCEPTANCE_CONTRACT.md`.
2. Production Terraform/HA preconditions pass without overrides: custom alias,
   viewer and origin certificates, WAF/logging, CloudFront and ALB access logs,
   and ALB deletion protection.
3. RDS Multi-AZ/PITR/recovery controls and Redis TLS/AUTH/failover are enabled.
4. Durable and transient S3 lifecycle contracts are independently reviewed.
5. Every Secrets Manager reference has an `AWSCURRENT` value supplied out of
   band; no secret value exists in Terraform state or GitHub variables.
6. GitHub environment `aws-commercial-production` trusts the exact repository
   and environment OIDC subject, is restricted to protected `main`, and has
   required reviewers.
7. Resend sender/domain, Turnstile pair, backend/browser Sentry, external uptime,
   incident alerting, and budget notifications are real and tested.
8. A licensed customer/supplier CAD-cost holdout and accountable reviewer meet
   `docs/SUPPLIER_HOLDOUT_EVIDENCE.md` for the supported launch scope.
9. ProofShape name/domain/IP, terms/privacy, and commercial launch approval are
   documented.

## Release identity

CI and release are intentionally separate:

- `.github/workflows/ci.yml` tests, builds, scans, and records local image/SBOM
  proof. It has no deployment job and publishes no cloud image.
- `.github/workflows/aws-commercial-promote.yml` requires successful exact-SHA
  CI, builds the backend/frontend archives once, hashes them into one artifact,
  and owns ECR publication and ECS promotion.
- Staging publishes the artifact first. Production downloads the same artifact
  and sets `EXPECTED_BACKEND_DIGEST` and `EXPECTED_FRONTEND_DIGEST` from staging.
  A digest mismatch fails before production rollout.

Do not describe CI's local image IDs as deployed digests. Do not describe a
publish-only ECR seed as a deployment.

The AWS workflow closes the build-to-deploy supply-chain boundary: it loads the
sealed archive images, fails on every fixed or unfixed HIGH/CRITICAL finding,
generates CycloneDX SBOMs from those same images, and binds archive hashes,
image IDs, scan evidence, and SBOM hashes into the manifest that publication
re-verifies before ECR push.

## Pre-production sequence

1. Complete the account/state/secret/Redis AUTH/bootstrap sequence in
   `docs/AWS_ACCOUNT_BOOTSTRAP.md`.
2. Seed staging ECR with `publish-staging-only`, activate services through a
   reviewed Terraform apply, and run `staging-only`.
3. Retain migration, ECS stability, expected-release, deep-health, object-store,
   worker, and auth-proxy evidence through the canonical CloudFront hostname.
4. Complete every staging human/operational journey in
   `docs/LAUNCH_RUNBOOK.md`, including restore, rollback, alert delivery, load,
   two organizations, production-size multipart S3, and mobile interaction.
5. Seed the isolated production ECR boundary when required, activate production
   services by digest through reviewed Terraform, and verify all HA controls.
6. Present the exact staging evidence, supplier/customer holdout, legal/name
   approval, migration compatibility plan, and rollback plan to the protected
   production reviewer.
7. Run `staging-and-production` on the same release SHA.

The AWS workflow verifies artifact identity and environment boundaries and
validates the confidential supplier holdout before staging mutation. Production
independently validates the holdout and requires its evidence digest to match
staging. The accountable protected-environment reviewer still owns the final
business acceptance decision.

## Production-live acceptance

The release remains blocked until all rows pass on the production hostname and
the retained evidence names the exact release SHA/digests.

| Area | Required production evidence |
|---|---|
| Edge | Canonical custom CloudFront hostname, TLS 1.2, WAF, edge/ALB logs, raw ALB not reachable as a release origin |
| Runtime | Migration exit zero; frontend/API/worker stable on expected digests; read-only root and health controls active |
| Dependencies | `/health`, token-authenticated `/health/deep`, Postgres, Redis, worker, durable S3, and auth-proxy handshake pass |
| Identity | Real Turnstile and email-first magic link, one-time initial password, login/logout/logout-all/revocation/expiry pass |
| Product | Onboarding, Design Studio, representative CAD analysis, cost/DFM, decision, compare, RFQ, export, batch, and reconstruction golden paths pass |
| Authorization | Full role matrix and two-organization reads/mutations/artifacts/upload identifiers fail closed without existence leakage |
| Large files | Production-size direct multipart upload, URL refresh, terminal processing, correct result, retry/cancel, and no cloud credentials in browser storage/logs |
| Data truth | Durable versions satisfy retention; consumed transient objects are physically absent; public/cross-account access fails |
| Failure/recovery | Worker/queue/kernel/storage/network interruption, timeout, cancellation, refresh/restart, kill switch, prior-digest rollback, and RDS restore meet recorded outcomes |
| Operations | Sentry event and page, uptime page, budget alarm, WAF/access logs, backup status, capacity/load, certificate and on-call checks reach accountable humans |
| Customer/legal | Supported-file scope and holdout accuracy are approved; name/domain/IP, terms/privacy, and launch approval are retained |

Overload must be bounded and retryable. An unexplained 5xx, indefinite spinner,
placeholder success, silent data loss, cross-tenant inference, or result that
does not match its golden contract blocks launch.

## Operations after go-live

- Review failed auth, privileged access, tenant-denial, 5xx/429, queue age,
  worker health, DB/Redis/S3 health, alarms, backup status, certificate expiry,
  and spend daily during launch.
- Scale ECS services before raising compute concurrency. Keep total database
  pools under the RDS connection budget.
- Perform recurring scratch restores and prior-digest rollback drills; measure,
  do not assume, RPO/RTO.
- Rotate secrets immediately after suspected exposure and on the approved
  schedule.
- Preserve exact release, deployment, alert, acceptance, and human-approval
  evidence.

## Go/no-go

Only an accountable human may change the commercial verdict after every
applicable blocker in `docs/PRODUCTION_LAUNCH_AUDIT.md` is closed. A successful
CI run, Terraform validation/apply, ECR publication, ECS stabilization, or one
happy-path browser test is not sufficient alone.
