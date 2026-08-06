# AWS commercial account bootstrap

This runbook prepares isolated ProofShape commercial staging and production
stacks. It does not authorize or describe Arcus, GovCloud, regulated-customer,
or customer-controlled deployments. Never reuse these state buckets, account
roles, KMS keys, VPCs, repositories, secrets, or GitHub environments across
that boundary.

No secret value belongs in Terraform source, a `.tfvars` file, GitHub variables,
workflow logs, or Terraform state. Terraform creates secret metadata and ECS
references only. Operators populate values through an approved secret channel.

## 1. Account and tool prerequisites

Use separate AWS accounts for staging and production. The promotion workflow
enforces different 12-digit account IDs before requesting production OIDC
credentials. Environment-specific names, CIDRs, state, GitHub subjects, KMS
keys, and data stores remain required inside those account boundaries.

Before the application stack, establish and retain evidence for the account
security baseline under an organization/security owner, not this workload state:

- hardware-backed MFA on each root user, no root access keys, current security/
  billing contacts, and federated operator access with short-lived sessions;
- organization/all-region CloudTrail delivered to a separately administered,
  immutable log archive, with alarms for root use, IAM/KMS/CloudTrail changes,
  console sign-in failures, and network/security-policy changes;
- GuardDuty, IAM Access Analyzer, and the approved Security Hub/Config posture,
  including delegated administration where an AWS Organization is used;
- service-control policies or equivalent controls preventing member accounts
  from disabling audit/detection and constraining deployment to approved regions;
- break-glass access that is tested, monitored, and excluded from normal deploys.

These controls can carry separate service charges. They are production release
prerequisites and must not be silently omitted to make the application budget
look lower.

Required operator tooling:

- Terraform `1.15.8` and AWS provider `6.54.0`, matching the committed main and
  bootstrap lock files. Upgrade those pins and regenerate both platform locks in
  a reviewed change; do not let an operator workstation select a newer provider.
- AWS CLI v2 for account bootstrap and the out-of-band cache AUTH operation.
- Node.js, `jq`, and Bash for the checked-in operator scripts.
- An AWS commercial region currently supporting CloudFront VPC origins. The
  Terraform contract rejects unsupported regions and excluded physical AZ IDs.
- A protected GitHub environment named `aws-commercial-staging` or
  `aws-commercial-production`.

Before every account-changing command, verify the intended profile and account:

```bash
aws sts get-caller-identity
```

Do not run an apply until the returned 12-digit account is the account recorded
in that environment's tfvars.

## 2. Bootstrap remote Terraform state

Copy and edit `infra/aws/bootstrap/bootstrap.tfvars.example`. Use a unique state
bucket per account. Then initialize and apply the bootstrap
stack with an explicitly selected AWS profile:

```bash
terraform -chdir=infra/aws/bootstrap init
AWS_PROFILE=proofshape-staging terraform -chdir=infra/aws/bootstrap plan \
  -var-file=bootstrap.tfvars -out=bootstrap.tfplan
AWS_PROFILE=proofshape-staging terraform -chdir=infra/aws/bootstrap apply \
  bootstrap.tfplan
```

Copy the bootstrap outputs into the matching backend example and keep the
staging and production keys distinct. Backend examples live at:

- `infra/aws/environments/staging.backend.hcl.example`
- `infra/aws/environments/production.backend.hcl.example`

The bootstrap stack enables state-bucket versioning, KMS encryption, public
access blocking, native S3 lockfiles, and deletion protection controls. Restrict
state access to the infrastructure operator role; the GitHub release role does
not need Terraform state access.

## 3. Prepare edge prerequisites

### Staging before a domain exists

Staging may use `cloudfront_alias = ""` and
`cloudfront_origin_protocol_policy = "http-only"`. The released URL is still
HTTPS at the generated `*.cloudfront.net` hostname. Only the private
CloudFront-to-ALB hop is HTTP. The ALB is internal and its security group accepts
only the VPC-origin service security group, so this does not expose an HTTP
release URL.

### Production/HA

Production and every `availability_profile = "ha"` plan fail unless all of the
following are configured:

- A custom DNS alias.
- A matching ACM viewer certificate in `us-east-1`.
- A matching ACM certificate in the application's region for the private ALB.
- `cloudfront_origin_protocol_policy = "https-only"`.
- WAF and WAF logging enabled.
- A CloudFront access-log bucket domain.
- An ALB access-log bucket name.
- ALB deletion protection.
- CloudFront `retain_on_delete`.

The custom alias is forwarded as the origin `Host`, so the regional ALB
certificate must cover that exact hostname. CloudFront uses TLS 1.2 to the ALB;
the custom viewer policy is `TLSv1.2_2021`.

The edge expects a pre-created S3 logging bucket. CloudFront uses its domain
(for example `proofshape-production-edge-logs.s3.amazonaws.com`) and the ALB
uses its bucket name. Prepare the bucket for both CloudFront standard logging
and regional ELB log delivery, including the required CloudFront ACL support,
the `logdelivery.elasticloadbalancing.amazonaws.com` bucket policy, and a
retention policy. Block all public access, enable delivery-compatible encryption
and versioning, restrict human/object-read access to the approved security and
incident roles, and alert on policy/public-access changes. CloudFront standard
logs include request query strings, so classify this bucket as sensitive even
though cookies are excluded and WAF separately redacts authorization, cookies,
and query strings. Do not use the customer evidence or transient-upload buckets
for edge logs.

DNS may be external. When Route 53 owns the zone, set `route53_zone_id` and the
stack creates A/AAAA aliases. Otherwise create the alias only after CloudFront
reports deployed.

## 4. Initialize the environment stack

Copy the matching tfvars/backend examples to ignored local files. Replace every
account, repository, certificate, logging bucket, email, and DNS placeholder.
Keep workloads and services disabled on the first apply:

```hcl
enable_workloads = false
enable_services  = false
backend_image    = ""
frontend_image   = ""
initial_release_id = "bootstrap"
transient_upload_contract_confirmed = false
```

Initialize, format, validate, and save a reviewed plan:

```bash
terraform -chdir=infra/aws init \
  -backend-config=environments/staging.backend.hcl
terraform -chdir=infra/aws fmt -check -recursive
terraform -chdir=infra/aws validate
AWS_PROFILE=proofshape-staging terraform -chdir=infra/aws plan \
  -var-file=environments/staging.tfvars -out=staging.tfplan
```

Review the plan for the exact account, `Boundary=proofshape-commercial`, two
AZs, environment CIDRs, private ALB/RDS/cache, and disabled ECS services before
applying the saved plan.

## 5. Populate runtime secrets outside Terraform

The `runtime_secret_arns` output lists every ECS secret reference. Metadata-only
placeholders have no `AWSCURRENT` version and cannot start a task until an
operator populates them. Supply values with an approved secrets process. If the
AWS CLI is used, read from a protected file or stdin instead of placing the
secret on the command line.

Important contracts include:

- `DATABASE_URL` and `DATABASE_URL_DIRECT` use TLS and the private RDS endpoint.
- `REDIS_URL` uses `rediss://` and includes the ElastiCache AUTH token.
- Frontend and backend `AUTH_PROXY_SECRET` values match.
- `DASHBOARD_SESSION_SECRET`, `SESSION_SECRET`, signing/pepper keys, and
  `DEEP_HEALTH_TOKEN` are independent high-entropy values.
- Email, Turnstile, and Sentry values are real environment-specific values.

RDS creates its administrator password in an RDS-managed Secrets Manager secret.
That administrator credential is not the application's routine database URL.

## 6. Enable ElastiCache AUTH

The AWS provider's ElastiCache `auth_token` field persists the token in state.
This stack deliberately does not use it. Terraform creates or references a
dedicated Secrets Manager secret and blocks API/worker service creation until
the operator attests that AUTH is active.

Put a 16–128 character ElastiCache-compatible token into the secret named by
`elasticache.auth_secret_arn`, then run:

```bash
export AWS_REGION=us-east-1
export EXPECTED_AWS_ACCOUNT_ID=111111111111
export AWS_COMMERCIAL_BOUNDARY=proofshape-commercial
export AWS_CACHE_REPLICATION_GROUP_ID=proofshape-commercial-staging
export AWS_CACHE_AUTH_TOKEN_SECRET_ARN='arn:aws:secretsmanager:...'
bash scripts/ops/aws-enable-cache-auth.sh
```

The helper retrieves the value without printing it, performs `ROTATE` followed
by `SET`, waits for availability, and verifies both AUTH and transport
encryption. If the secret stores JSON, the default field is `token`; override
`AWS_CACHE_AUTH_TOKEN_JSON_KEY` when required. Update `REDIS_URL` with the same
token, then set `cache_authentication_confirmed = true`. This boolean is an
operator attestation, not a secret and not a substitute for the verification
output.

Before any ElastiCache replacement, set
`cache_authentication_confirmed = false`. Terraform cannot observe whether the
replacement has AUTH; rerun the helper and authenticated queue probe before
setting it true again.

Run the helper under a separately approved operator principal restricted to
`GetSecretValue` on this one token secret and modify/describe access on this one
replication group. The GitHub image/promotion role deliberately cannot read the
token or change ElastiCache.

## 7. Configure GitHub OIDC and protected environments

An AWS account can have only one provider for
`https://token.actions.githubusercontent.com`. Set
`create_github_oidc_provider = true` in exactly one stack per account; other
stacks use its ARN through `github_oidc_provider_arn`.

The role trust requires both the exact repository and exact GitHub environment
subject. It accepts no repository, branch, or environment wildcard. The role
can:

- obtain an ECR authorization token;
- upload layers and put images only in this environment's backend/frontend
  repositories;
- inspect required secret versions without reading values;
- register task definitions, run the migration family, and update only the
  three exact ECS services;
- pass only this stack's ECS task/execution roles.

Copy `promotion_environment_variables` from Terraform output into the matching
protected GitHub environment. The four `AWS_ECS_*_BASE_TASK_DEFINITION` values
are empty until `enable_workloads = true`; copy the output again after that apply
so promotion can clone only Terraform-reviewed baselines. Store
`CADVERIFY_DEEP_HEALTH_TOKEN` as an environment secret.

Create the confidential, exact-release supplier evidence described by
`docs/SUPPLIER_HOLDOUT_EVIDENCE.md`, base64-encode the reviewed JSON without
changing it, and set `CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_B64` independently in
both protected environments. Staging migration/promotion validates every field
and records only its SHA-256. Production revalidates after its approval wait and
must produce the same digest; a missing, stale, release-mismatched, failing, or
changed approval blocks AWS mutation.

Set the repository-level `AWS_COMMERCIAL_NEXT_PUBLIC_SENTRY_DSN` to the public
HTTPS DSN for browser Sentry. It is mandatory and release-invariant because
staging and production promote the exact same frontend image bytes. Keep alert
routing and environment/domain filtering configured in Sentry; a syntactically
valid DSN is not evidence that an alert reaches a human.

Require reviewers for the production environment and restrict deployment
branches to protected `main`.

## 8. Seed immutable images, migrate safely, enable services, and promote

Starting services before the initial schema exists is forbidden. Use this order:

1. Run `AWS Commercial Promotion` with `publish-staging-only`. It requires a
   successful protected-main push CI, builds the release archives once, executes
   the exact-image storage/read-only/CSP gate, scans those same loaded images for
   HIGH/CRITICAL findings, retains and hashes the machine-readable reports,
   generates exact CycloneDX SBOMs, seals all hashes, and publishes staging ECR
   digests. Publish-only makes no database/runtime change.
2. Read the digest-qualified image URIs from image-publication evidence. In
   staging tfvars set those URIs, set `initial_release_id` to the exact 40-character
   SHA, keep `enable_services = false`, set `enable_workloads = true`, review the
   plan, and apply. This creates reviewed task definitions but starts nothing.
3. Copy `promotion_environment_variables` again so GitHub receives all four exact
   baseline task-definition ARNs. Confirm every runtime secret is `AWSCURRENT`,
   cache AUTH is verified, and the staging supplier-holdout secret validates for
   this exact SHA.
4. Run `migrate-staging-only`. It republishes the sealed bytes, validates the
   holdout, clones the exact Terraform migration baseline, runs only `alembic
   upgrade head` on the pinned Fargate platform/network, retains evidence, and
   exits without querying or changing a service.
5. Only after migration succeeds, set
   `transient_upload_contract_confirmed = true` (the exact-image gate is
   non-waivable), set `enable_services = true`, review the plan, and apply. The
   first service revision is now the exact SHA against an already-migrated schema.
6. Run `staging-only`. The idempotent migration runs again, task revisions are
   cloned from Terraform baselines rather than deployed drift, services stabilize,
   deep health proves API/worker/storage/frontend/CSP, and the AWS-native intake
   kill switch performs off/on/restore probes followed by deep health.
7. Complete the real browser, direct-upload cleanup, email, Turnstile, Sentry,
   alarm, restore, and customer/supplier acceptance gates before production.
8. For first production setup, use `publish-staging-and-production`, activate
   production workloads only (`enable_workloads = true`, services false, exact
   images/SHA), recopy outputs, then run `migrate-staging-and-production`. After
   the production migration succeeds, enable production services and run
   `staging-and-production`. Production approval, account/cluster/repository
   isolation, identical ECR digests, and equal holdout evidence are all mandatory.

The exact archive/scan/SBOM artifact is retained for 90 days and production
downloads the same bytes built before staging in that workflow run; it never
rebuilds after staging. Copy evidence to the approved immutable record system
when policy requires longer retention.

Service rollback does not reverse Alembic. Production migrations must be
backward-compatible expand/contract changes so the prior task revision can still
run against the migrated schema.

## 9. Operate and drill the AWS-native intake kill switch

Use only the protected workflow scopes, supplying the exact live release SHA:

- `kill-switch-staging-off`
- `kill-switch-staging-on`
- `kill-switch-staging-test`
- `kill-switch-production-off`
- `kill-switch-production-on`

The script refuses a mismatched account, region, cluster, service family, release
SHA, non-digest image, non-Fargate task, unexpected role account, or writable root.
It changes only `ACCEPTING_NEW_ANALYSES`, waits for service stability, and probes
the public demo mutation. Off must return `503 service_paused` with
`Retry-After: 3600`; on must reach normal application validation. A failed
`on`/`test` restores the prior task definition; a failed `off` probe remains
failed closed on the off revision. The staging test is disruptive and is
therefore refused in production; every normal staging promotion runs it and
restores the original state automatically.

The switch stops new guarded mutations but does not cancel in-flight analyses or
drain queued work. Promotion preserves the live switch state, so a deployment
cannot silently reopen intake. Record a separate queue-drain/cancellation decision
when incident response requires more than admission control.

## 10. Required live evidence

Before declaring an environment released, retain:

- reviewed Terraform plan/apply output for the exact commit;
- CloudFront distribution, VPC-origin, WAF/log, and certificate evidence;
- cache AUTH helper result and an authenticated queue/deep-health result;
- RDS backup/PITR and restore-test evidence;
- durable-evidence and transient-upload S3 lifecycle/delete tests;
- ECR publication evidence, Alembic exit zero, stable ECS services, and deep
  health JSON from the workflow;
- exact archive hashes, Trivy HIGH/CRITICAL pass, CycloneDX SBOM hashes, equal
  staging/production ECR digests, and equal supplier-holdout evidence digests;
- staging AWS kill-switch off/on/restore evidence and the final post-restore
  deep-health record;
- an exact-image/browser feature-availability record that does not advertise
  image-to-mesh reconstruction until the local GPU/inference dependency and
  capacity contract in `AWS_COMMERCIAL_PRODUCTION.md` is implemented and proven;
- budget/alarms subscription confirmation and application observability alert
  delivery.

The raw ALB DNS name is never a release URL. A successful ALB-origin probe does
not replace CloudFront deep health.

The staging `$150` budget is an account-wide alert, not a hard cap. This always-on
ALB/RDS/Redis/ECS design cannot honestly promise a `$100` monthly usage total;
credits change the bill, not the resource cost. Review Cost Explorer after the
first 24–72 hours and resize from observed memory/CPU/storage/transfer without
removing the release, recovery, or isolation controls above.
