# ProofShape commercial production deploy handoff

Status date: 2026-07-14

Active branch: `codex/proofshape-scalecad-staging`

Current verdict: **not production-live**

This handoff is the starting point for a ProofShape commercial deployment. The
canonical architecture and operator details are:

- `docs/PRODUCTION_ACCEPTANCE_CONTRACT.md`
- `docs/AWS_COMMERCIAL_PRODUCTION.md`
- `docs/AWS_ACCOUNT_BOOTSTRAP.md`
- `docs/LAUNCH_RUNBOOK.md`
- `docs/PRODUCTION_LAUNCH_AUDIT.md`

## Ownership boundary

ProofShape must use newly created ProofShape-owned AWS, GitHub, DNS, email,
Turnstile, Sentry, and billing resources.

Arcus is a different company. Its Vercel `eager-euler` project, accounts,
teams, domains, deployments, secrets, billing, and source settings are
prohibited. Do not inspect or modify them as part of a ProofShape release.

The repository still contains Fly configuration and operator scripts from an
older deployment design. They are **legacy/non-release references**. The
deleted `.github/workflows/saas-promote.yml` must not be restored, and no Fly
resource is part of the current ProofShape commercial launch path.

## What is being deployed

ProofShape is one application, not a CAD app beside a verification app:

- Next.js web application and same-origin auth/API proxy;
- FastAPI API;
- ARQ background worker;
- Postgres system of record;
- TLS/authenticated Redis for queues, sessions, rate limits, and worker health;
- deterministic OpenCASCADE/gmsh CAD processing;
- durable and transient S3 object-storage paths; and
- email, Turnstile, Sentry, CloudWatch, WAF, and external alerting.

The commercial AWS release edge is CloudFront. CloudFront reaches an internal
ALB through a VPC origin. The ALB is not a release URL and its default action is
403. ECS Fargate runs separate frontend, API, worker, and migration task
families. RDS and ElastiCache remain private.

The working product name is ProofShape. A public name/domain launch still
requires ownership and legal clearance. Repository identifiers that still say
CadVerify are implementation history, not proof that the name is owned.

## Use the three claims correctly

| Claim | Meaning | Current status |
|---|---|---|
| Product-proven | The exact clean commit passes the supported browser journeys, numerical/artifact checks, role/tenant matrix, and failure/recovery paths. | Recorded. The current release manifest reports `LOCAL_GATE_PASS` for all 64 canonical contracts; the aligned mobile, S3, representative-CAD, manufacturing, role, guide, and deck supplements also pass. Re-run after any repository change. |
| Cloud-deploy-ready | The same commit has reproducible images, valid migrations, validated AWS IaC, OIDC delivery, restore/rollback procedures, and an operator contract. | Recorded. IaC, exact-image build/scan/SBOM binding, migrations, OIDC promotion, rollback, AWS kill switch, and runbooks are implemented and statically validated. This does not mean an account has been applied. |
| Production-live | The exact digests are running in ProofShape-owned AWS and all real-provider/live gates passed. | No. No AWS plan/apply or live deployment evidence has been produced. |

Do not collapse these claims into “production-ready.” A green unit suite is not
product proof, Terraform validation is not a deployment, and a reachable page
is not a production launch.

## Canonical commercial architecture

Use `infra/aws` for both commercial environments:

| Layer | Staging | Production |
|---|---|---|
| GitHub environment | `aws-commercial-staging` | `aws-commercial-production` with required reviewers |
| Public edge | generated HTTPS `*.cloudfront.net` hostname is allowed | custom DNS alias and viewer/origin certificates are required |
| Compute | budget profile may use one task per service | HA profile requires at least two frontend/API/worker tasks |
| Database | isolated encrypted RDS; honest single-AZ budget profile allowed | isolated Multi-AZ RDS, PITR, deletion protection, final snapshot |
| Queue/cache | isolated TLS Redis with out-of-band AUTH | isolated multi-node TLS Redis with AUTH/failover |
| Durable objects | isolated KMS/versioned S3 evidence bucket | isolated KMS/versioned S3 evidence bucket with production retention |
| Incoming uploads | isolated KMS, deliberately unversioned transient bucket | same contract; immediate delete is tested, lifecycle is only a backstop |
| Delivery | exact-repository/environment GitHub OIDC role | separate exact-repository/environment OIDC role and approval |

Commercial AWS and the regulated plane are separate systems. CUI/ITAR work
requires the GovCloud/customer-controlled boundary in
`docs/REGULATED_PRODUCTION_RUNBOOK.md`; commercial AWS approval never
authorizes regulated data.

## Inputs the owner must supply

Do not put any secret value in chat, Git, issue text, workflow logs, Terraform
variables, or Terraform state.

1. ProofShape AWS staging and production account access, billing, launch region,
   and budget-notification addresses.
2. A GitHub OIDC bootstrap/operator path and protected environments named
   `aws-commercial-staging` and `aws-commercial-production`.
3. Real runtime secret values for database application users, Redis AUTH,
   session/signing/pepper keys, deep health, connectors, email, Turnstile, and
   Sentry.
4. A Resend account, verified sender, and real delivery inboxes.
5. Cloudflare Turnstile site/secret pairs and Sentry projects with a real alert
   destination.
6. A custom production domain plus viewer and regional ACM certificates. A
   generated CloudFront hostname is sufficient for staging before purchase.
7. A licensed, customer-relevant CAD/cost holdout and an accountable acceptance
   owner. The current AWS workflow does not fabricate or replace this approval.
8. Name/IP, terms, privacy, export-control, and regulated-data decisions needed
   for the actual launch.

## Exact release contract

`.github/workflows/ci.yml` is build/test proof only. It builds and scans local
production images but does not publish or deploy them.

`.github/workflows/aws-commercial-promote.yml` owns the commercial release:

1. It accepts a reviewed 40-character SHA reachable from protected `main` and
   requires successful CI for that exact SHA.
2. It builds backend and frontend Docker archives once as `linux/amd64`.
3. It scans those exact loaded archive images for every fixed or unfixed
   HIGH/CRITICAL finding, generates CycloneDX SBOMs from the same images, and
   binds image IDs plus archive, scan, and SBOM hashes into a sealed manifest.
4. It validates a confidential, exact-release supplier holdout before staging
   mutation; production independently revalidates it and requires the same
   evidence digest.
5. Staging publishes those exact bytes to its immutable ECR repositories.
6. Production downloads the same artifact and refuses ECR digests that differ
   from staging.
7. Promotion runs Alembic, registers digest-qualified ECS task revisions,
   stabilizes all services, and runs authenticated deep health through the
   canonical CloudFront origin.
8. Staging exercises the AWS-native intake kill switch and restores the exact
   prior task definition before production approval.
9. A failed rollout restores the previous ECS task definitions.

The workflow has four exact-artifact scopes:

- `publish-staging-only`: seed staging ECR during bootstrap;
- `publish-staging-and-production`: seed both isolated ECR boundaries;
- `staging-only`: migrate and promote already-created staging services; and
- `staging-and-production`: promote staging, wait for protected production
  approval, then publish/promote the same artifacts to production.

It also has protected AWS-native operations for
`kill-switch-staging-off`, `kill-switch-staging-on`,
`kill-switch-staging-test`, `kill-switch-production-off`, and
`kill-switch-production-on`.

## Ordered launch sequence

1. Preserve the recorded `product-proven` and `cloud-deploy-ready` gates. Re-run
   them on the final clean commit after any source or documentation change.
2. Bootstrap remote Terraform state separately in the staging and production
   accounts.
3. Plan/apply each `infra/aws` stack with workloads and services disabled.
4. Populate every Secrets Manager value out of band. Enable ElastiCache AUTH
   with `scripts/ops/aws-enable-cache-auth.sh`, verify it, and record the
   attestation.
5. Configure the exact Terraform outputs as variables in the matching protected
   GitHub environment. Store the deep-health token as an environment secret.
6. Run the appropriate publish-only scope to create the first immutable ECR
   digests.
7. Verify the image consumes the separate `DIRECT_UPLOAD_S3_*` contract. Set
   the cache/direct-upload attestations, enable workloads/services, and apply a
   reviewed Terraform plan.
8. Run `staging-only`. Require migration exit zero, ECS stabilization, deep
   health, auth-proxy handshake, and retained non-secret deployment evidence.
9. Run the full product/browser/live-provider acceptance matrix against staging,
   including multipart S3, two organizations, refresh/restart durability,
   email, Turnstile, Sentry, restore, alarms, kill switch, and rollback.
10. Provision the production custom edge and HA profile, complete the protected
    human and supplier-holdout approvals, then run `staging-and-production` on
    the same release SHA.
11. Re-run production smoke/auth/tenant/STEP/export/observability checks. The
    accountable owner records go/no-go only after reviewing all evidence.

## Blocking acceptance bar

Do not report production-live until all of these are true:

- the exact clean commit satisfies `docs/PRODUCTION_ACCEPTANCE_CONTRACT.md`;
- Terraform production/HA preconditions pass without bypasses;
- CloudFront is canonical and the internal ALB is not directly reachable;
- WAF and edge/application logs are retained and alarms reach a human;
- every runtime secret has a real current value and Redis AUTH is verified;
- migration, frontend, API, and worker all serve the expected release SHA;
- `/health`, authenticated `/health/deep`, and `/api/auth/proxy-health` pass;
- real email-first signup, password setup/login, logout, and revocation pass;
- representative STEP, Design Studio, batch, reconstruction, export, and delete
  journeys produce the expected persisted and downloadable outcomes;
- cross-organization reads and mutations fail without existence leakage;
- durable S3 versions survive according to retention while consumed transient
  uploads are physically absent;
- restore, worker interruption, kill switch, and prior-digest rollback meet the
  recorded RPO/RTO;
- load has no unexplained 5xx and overload is bounded/retryable; and
- supplier/customer accuracy evidence and the legal/name launch decision have
  accountable human approval.

## Honest handoff statement

The repository is product-proven and cloud-deploy-ready under the binding claim
definitions. It has not been applied to an AWS account, and no ProofShape
production environment is live. The next action is ProofShape-owned
account/provider provisioning followed by credentialed staging acceptance.
Arcus remains out of scope throughout.
