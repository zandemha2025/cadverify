# ProofShape commercial go-live runbook

This is the canonical top-level runbook for the ProofShape commercial AWS
plane. Use these detailed companions while executing it:

- `docs/AWS_ACCOUNT_BOOTSTRAP.md` for ordered Terraform/account setup;
- `docs/AWS_COMMERCIAL_PRODUCTION.md` for architecture and release contracts;
- `docs/SAAS_PRODUCTION_RUNBOOK.md` for production acceptance;
- `docs/PRODUCTION_ACCEPTANCE_CONTRACT.md` for allowed claims; and
- `docs/PRODUCTION_LAUNCH_AUDIT.md` for the current blockers.

This runbook does not authorize CUI/ITAR data. Use
`docs/REGULATED_PRODUCTION_RUNBOOK.md` only after the regulated boundary has
real legal/security approval.

## 1. Current truth

- No ProofShape AWS environment has been planned/applied or deployed by this
  repository work.
- CI is build/test proof. It does not publish or deploy commercial images.
- The protected AWS workflow owns exact-artifact publication and ECS promotion.
- Staging may use an AWS-generated CloudFront HTTPS hostname before a domain is
  purchased.
- Production/HA requires a custom alias and certificates plus every Terraform
  production precondition.
- Arcus resources are prohibited.

Fly configuration and scripts that remain in the repository are
**legacy/non-release references**. They are not an alternative current
ProofShape runbook. The deleted Fly promotion workflow must remain deleted.

## 2. Entry gate

Choose one exact, clean commit. Before provisioning, record which claims it has
earned under `docs/PRODUCTION_ACCEPTANCE_CONTRACT.md`.

Do not proceed to a customer invitation when either of these is missing:

1. `product-proven`: the exact commit passed the full supported real-browser,
   CAD, role/tenant, artifact/numerical, failure/recovery, and mobile matrix.
2. `cloud-deploy-ready`: the exact commit passed code, migration, image,
   Terraform, workflow, shell, security, restore-procedure, and rollback-
   procedure gates.

Neither claim means production-live.

## 3. Owner-supplied inputs

Create these outside the repository. Never paste secret values into chat, Git,
Terraform source/variables/state, tickets, screenshots, or workflow logs.

| Input | Purpose |
|---|---|
| ProofShape AWS staging and production access | isolated state, network, data, registry, compute, and billing boundaries |
| Approved AWS commercial region | must support CloudFront VPC origins and the selected services |
| Terraform operator/bootstrap identity | state and first-account setup; separate from the GitHub promotion role |
| Protected GitHub environments | exactly `aws-commercial-staging` and `aws-commercial-production` |
| Budget and alarm recipients | cost and incident delivery proof |
| Resend verified sender and inboxes | real magic-link delivery and bounce/failure testing |
| Turnstile site/secret pairs | bot defense for released signup |
| Sentry projects and alert destination | scrubbed application error and paging proof |
| Production domain and ACM certificates | required custom production/HA edge; optional for staging |
| Licensed customer-relevant CAD/cost holdout | supported-input and accuracy acceptance |
| Legal/name/privacy/terms decisions | public commercial authorization |

Use separate AWS accounts for staging and production when available. At minimum
use separate state, VPCs, CIDRs, keys, repositories, data stores, secrets,
GitHub subjects, and approvals.

## 4. Bootstrap each AWS account

Follow `docs/AWS_ACCOUNT_BOOTSTRAP.md` exactly.

1. Verify the selected AWS identity and 12-digit account before every changing
   operation.
2. Apply `infra/aws/bootstrap` to create the environment's encrypted/versioned
   remote state and lock configuration.
3. Create ignored local backend/tfvars files from the matching examples.
4. Keep `enable_workloads=false`, `enable_services=false`, images empty, cache
   authentication unconfirmed, and the transient-upload contract unconfirmed
   on the first environment plan.
5. Run Terraform format/init/validate and save a reviewed plan.
6. Review the plan for the exact account, `Boundary=proofshape-commercial`, two
   eligible AZs, internal ALB, private RDS/Redis, isolated KMS/S3/ECR/secrets,
   and disabled ECS services before apply.

For production/HA, prepare the custom DNS alias, `us-east-1` viewer
certificate, regional ALB certificate, edge-log bucket, WAF/log settings, and
ALB deletion protection before planning. Terraform must fail rather than
silently downgrade these controls.

## 5. Populate secrets and enable Redis AUTH

Terraform creates secret metadata and task references, not values. Populate
every required Secrets Manager entry through an approved out-of-band channel.
Required contracts include:

- pooled and direct TLS Postgres URLs for a least-privilege application user;
- `rediss://` Redis URL containing the environment's AUTH token;
- matching frontend/backend `AUTH_PROXY_SECRET`;
- independent session, dashboard-session, magic-link, pepper, connector, and
  deep-health secrets;
- Resend, Turnstile, and Sentry values; and
- any other ARN listed by Terraform's runtime-secret output.

Enable ElastiCache AUTH with `scripts/ops/aws-enable-cache-auth.sh`. The helper
retrieves the token without printing it, performs `ROTATE` then `SET`, waits for
availability, and verifies transport/auth. Only after that evidence exists may
`cache_authentication_confirmed=true` be set.

Never place the Redis token in Terraform. The GitHub promotion role cannot read
secret values or change ElastiCache.

## 6. Configure protected GitHub delivery

For each environment:

1. Use the exact repository and exact `aws-commercial-<environment>` OIDC
   subject produced by Terraform. Do not add repository or environment
   wildcards.
2. Copy Terraform's non-secret promotion outputs into the matching GitHub
   environment variables.
3. Store `CADVERIFY_DEEP_HEALTH_TOKEN` as an environment secret matching the
   target runtime value.
4. Set repository variable `AWS_COMMERCIAL_NEXT_PUBLIC_SENTRY_DSN` only if
   browser Sentry is enabled. It must be release-invariant because staging and
   production receive the same frontend bytes.
5. Restrict the production environment to protected `main`, require reviewers,
   and prevent self-approval when the GitHub plan supports it.

The OIDC role may publish only to that environment's exact backend/frontend ECR
repositories and promote only its exact ECS services/task roles.

## 7. Seed images and enable services

`AWS Commercial Promotion` has explicit bootstrap and promotion scopes.

For the first staging setup:

1. Run `publish-staging-only` with a reviewed 40-character SHA that is reachable
   from protected `main` and has successful exact-SHA CI.
2. Retain the non-secret image publication artifact and copy its digest-
   qualified image URIs into staging tfvars.
3. Review the exact backend image's use of the dedicated
   `DIRECT_UPLOAD_S3_*` contract. Do not infer this from Terraform alone.
4. Set `transient_upload_contract_confirmed=true`, retain the review evidence,
   and enable workloads/services in a reviewed Terraform plan.
5. Apply only after all Secrets Manager entries have current versions and Redis
   AUTH is confirmed.

For initial production, use `publish-staging-and-production` to seed both
isolated ECR boundaries from the same workflow artifact, then activate
production services by digest through reviewed Terraform.

Publish-only is not a deployment and does not run live health.

## 8. Promote staging

Run `staging-only` on the exact release SHA. The workflow must:

1. require successful CI for that SHA;
2. build backend/frontend archives once and seal their SHA-256 manifest;
3. publish the exact archives to staging ECR;
4. verify account, region, cluster, repository, secret-version, and boundary
   contracts;
5. register and run a one-shot `alembic upgrade head` Fargate task;
6. register digest-qualified API, worker, and frontend revisions;
7. wait for all services to stabilize; and
8. pass `/health`, authenticated `/health/deep`, object-store/worker checks,
   expected release ID, and `/api/auth/proxy-health` through CloudFront.

Retain the workflow's non-secret publication and deployment evidence. If
promotion fails, verify the script restored every service it had changed to its
prior task definition.

## 9. Staging human and operational acceptance

Run against real staging providers and at least two real test organizations:

- email-first signup, Turnstile, magic-link delivery/consume, initial password,
  logout/login, logout-all, expiry, and revocation;
- onboarding and every navigation entry into Design Studio and Verify;
- supported Design Studio create/revise/history/preview/STEP/Verify flows;
- representative STEP/IGES analyses with expected geometry, DFM, numerical
  cost, persistence, PDF/CSV/STEP downloads, and deletion;
- production-size browser multipart ZIP directly to S3, URL refresh, processing,
  result download, retry, cancellation, and physical transient cleanup;
- batch priority/concurrency/retry/cancel and reconstruction worker paths;
- viewer/auditor/analyst/admin mutation matrix and cross-organization 404
  behavior for records, artifacts, upload IDs, and object keys;
- refresh/restart durability, queue/worker/kernel/object-store/network failure,
  timeout, stale-state, and recovery actions;
- desktop and mobile interaction with no dead controls, hidden required action,
  indefinite spinner, placeholder success, or unexplained busy state;
- backend/browser Sentry delivery, external uptime alert, WAF/edge logs, budget
  notification, and on-call receipt;
- RDS restore to scratch, Redis interruption, durable S3 version retention,
  transient S3 deletion, kill switch, and prior-digest rollback; and
- production-like load/soak with no unexplained 5xx and bounded retryable
  overload.

Evidence must name the same commit and deployed digests. A technically loaded
page or automated API-only test is not a substitute.

## 10. Production promotion

Production remains blocked until staging evidence, legal/name approval, and the
customer/supplier holdout are reviewed by accountable owners.

Run `staging-and-production` on the same release SHA only after:

- production/HA Terraform preconditions pass;
- custom DNS and both certificates are active;
- WAF and CloudFront/ALB logs are producing retained records;
- production RDS/Redis/S3/secrets/alarms are independently configured; and
- the protected production reviewer has the staging evidence and rollback plan.

Production downloads the same archives built before staging and requires its
ECR digests to equal staging. It must use a different account/cluster/repository
boundary. After promotion, re-run smoke, auth, tenant isolation, representative
STEP, export, observability, and rollback-readiness checks on the production
hostname.

The current AWS workflow does not itself validate the confidential supplier
holdout. Until that gate is automated, the protected production approval must
record the exact-release holdout decision as a manual control; this limitation
must remain visible in the launch audit.

## 11. Rollback and recovery

- Application rollback selects retained prior digest-qualified task definitions;
  never a mutable tag.
- The promotion script automatically restores updated ECS services if rollout
  or health fails.
- Database migrations are not automatically reversed. Every migration needs a
  backward-compatible rollout and explicit compensating plan.
- The application kill switch may stop new analyses, but the legacy Fly-oriented
  helper is not the AWS release mechanism. Exercise the actual AWS runtime
  configuration path in staging and document it before launch.
- Restore only into an approved scratch target and measure RPO/RTO.

## 12. Go/no-go

The target remains blocked while any applicable row in
`docs/PRODUCTION_LAUNCH_AUDIT.md` is open. Only an accountable human may record
production-live after reviewing exact-build product evidence, AWS deployment
evidence, live-provider acceptance, recovery, customer/supplier accuracy, and
legal/name approval.
