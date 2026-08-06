# Regulated / CUI / ITAR Production Runbook

This runbook covers unclassified regulated workloads. Classified data is out of
scope. Infrastructure capability is not legal certification: confirm export
classification, contractual CUI/CMMC scope, registrations/authorizations, and
personnel eligibility with qualified counsel and the customer.

## 1. No-go conditions

Do not provision customer data or declare production when any condition holds:

- Data classification, contract clauses, CMMC level, or system boundary is
  unknown.
- The account/operator/support population is not approved for the data.
- Any production dependency, log sink, support tool, backup, or identity system
  sits outside the approved boundary.
- Images are mutable/unsigned, secrets are in Helm/Git, or the chart is using
  local blob storage.
- IdP negative tests, tenant isolation, deep health, backup restore, incident
  response, load/soak, or penetration-test conditions are unresolved.

## 2. Preferred hosted landing zone

Use a dedicated AWS GovCloud (US) organization/account and approved U.S.-person
operators. The baseline is:

- Private EKS worker nodes distributed across at least two availability zones.
- Encrypted RDS PostgreSQL Multi-AZ with customer-managed KMS key, PITR, AWS
  Backup, and direct/pooled endpoints where applicable.
- TLS/auth-enabled ElastiCache Redis with replication and encrypted snapshots.
- S3 bucket with customer-managed KMS encryption, versioning, access logging,
  public-access block, lifecycle, and approved retention/Object Lock policy.
- ECR with immutable tags, enhanced scanning, SBOMs, and signature verification.
- Secrets Manager synchronized to Kubernetes by an approved External Secrets
  mechanism; workload identity for S3/KMS instead of static AWS keys.
- CloudTrail, Config, GuardDuty, Security Hub, VPC flow logs, centralized logs,
  and in-boundary OpenTelemetry/SIEM alerting.
- Deny-by-default security groups and Kubernetes NetworkPolicies; approved VPC
  endpoints for AWS services; controlled egress only.
- Namespace-wide service-mesh mTLS or equivalent evidenced pod-to-pod encryption.
  The chart requires `regulatedControls.inClusterEncryption=true`, which is an
  operator assertion backed by landing-zone evidence, not a control by itself.

Customer-managed/on-prem Kubernetes may replace GovCloud only when it supplies
equivalent identity, encryption, network, logging, backup, supply-chain, and
personnel controls.

## 3. Secret contract

Create `cadverify-runtime` outside Helm with these keys:

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
DASHBOARD_ORIGIN
DEEP_HEALTH_TOKEN
```

The approved regulated baseline does not accept password/hybrid or magic-link
keys. Create `cadverify-saml` with
`settings.json` and `advanced_settings.json`. Do not put CAD data, credentials,
or private keys in resource names, values files, CI output, or support tickets.
Create `cadverify-otel-ca` with the approved collector CA as `ca.crt`.

`SESSION_SECRET` must be a strong 32+ character value. The dashboard, auth
proxy, API-key, connector fingerprint, deep-health, and (exactly 32-byte)
Fernet connector secrets must be base64-encoded random material; released
startup rejects repeated-byte handoff stubs and malformed values.

The runtime-secret gate also rejects static AWS session/access keys, external
Sentry/Resend/Google/OIDC/Replicate credentials, and Turnstile/magic-link keys.
Use EKS Pod Identity and the in-boundary OTLP path; remove stale keys instead of
assuming an unused environment variable is harmless.

Validate key presence without printing values:

```bash
CADVERIFY_NAMESPACE=cadverify \
CADVERIFY_RUNTIME_SECRET=cadverify-runtime \
CADVERIFY_AUTH_MODE=saml \
CADVERIFY_SAML_SECRET=cadverify-saml \
CADVERIFY_OTEL_CA_SECRET=cadverify-otel-ca \
bash scripts/ops/k8s-required-secrets-gate.sh
```

For SAML, this gate also validates the private JSON profile without printing it:
strict mode, signed messages and assertions, SHA-256 signature/digest
algorithms, HTTPS SP and IdP endpoints, one SP origin, and a real IdP signing
certificate are mandatory. The application additionally binds each production
ACS response and SP-initiated logout response to a one-time, Redis-backed
request ID/RelayState and rejects missing, expired, or replayed state. The SLS
accepts the configured HTTP-Redirect binding as well as POST.

## 4. Build and promote images

1. Build from the reviewed, protected `main` SHA in the approved supply chain.
2. Build the environment-neutral frontend; backend routing is runtime-only and
   browser data calls remain same-origin through the Next proxy.
3. Generate an SBOM, scan OS/application dependencies, sign both images, and
   store evidence by SHA.
4. Copy/promote the exact digests into GovCloud/customer ECR. Do not rebuild
   between staging and production.
5. Configure admission policy to accept only the approved registry and signed
   digests.

The manual GitHub workflow `.github/workflows/regulated-release.yml` implements
this build/scan/SBOM/provenance/KMS-signing path. It runs only from `main`, uses
the protected `regulated-release` environment, GitHub OIDC, GovCloud ECR,
and disables public transparency-log upload. It independently requires a
successful push-triggered CI run for the exact source SHA before obtaining
GovCloud credentials or building. Configure its documented repository variables
and `AWS_GOVCLOUD_RELEASE_ROLE_ARN` secret before use.

Both regulated workflows require an ephemeral self-hosted runner labeled
`govcloud` and `us-person`, located inside the approved boundary. Its image,
egress, action sources, logs, support model, and GitHub control plane must all be
explicitly approved; never replace it with `ubuntu-latest` for regulated work.

Run `.github/workflows/regulated-promote.yml` with the release SHA and signed
digests. It invokes the reusable `.github/workflows/regulated-deploy.yml` first
for `regulated-staging` and only after success for `regulated-production`; the
deployment workflow cannot be dispatched directly. Each invocation verifies
the signed digests again, reads approved private values from GovCloud Secrets
Manager, validates external Kubernetes secrets, performs server-side dry run and
manifest policy checks, deploys atomically, exercises the actual TLS ingress,
and records non-secret evidence.
Configure each protected deployment environment with:

- secret `AWS_GOVCLOUD_DEPLOY_ROLE_ARN`;
- variables `AWS_GOVCLOUD_EKS_CLUSTER`, `AWS_GOVCLOUD_HELM_VALUES_SECRET_ID`,
  `AWS_GOVCLOUD_BACKEND_REPOSITORY`, `AWS_GOVCLOUD_FRONTEND_REPOSITORY`,
  `AWS_GOVCLOUD_COSIGN_KMS_URI`, `AWS_GOVCLOUD_ACCOUNT_ID`,
  `CADVERIFY_BOUNDARY_ENVIRONMENT`, `CADVERIFY_NAMESPACE`, and
  `CADVERIFY_RELEASE_NAME`. Set `CADVERIFY_BOUNDARY_ENVIRONMENT` exactly to the
  protected environment name (`regulated-staging` or `regulated-production`).

The workflow verifies the OIDC account and EKS ARN, hashes the account/cluster/
namespace tuple after staging, and refuses production if it resolves to the
same tuple. This is a deployment guard, not a substitute for the approved
landing-zone boundary and environment-specific IAM/network review.

The release workflow also signs a custom attestation binding each digest to the
reviewed commit. The deploy workflow refuses a digest/SHA combination that does
not match those signed predicates.

Configure the separate `regulated-release` environment with the release role and
release variables. Require independent reviewers on `regulated-production` and
review all staging acceptance evidence before approval. The deploy role must be
separate from the image-release role and limited to the named cluster, namespace,
values secret, verification key, and read-only ECR operations.

## 5. Prepare private values

Copy `charts/cadverify/values-regulated.yaml` to a private operational repository
and replace every example account, hostname, bucket, role, image tag, and CIDR.
The checked-in overlay deliberately uses documentation-only placeholders.
It cannot pass a real deployment render unless those placeholders are replaced
and in-cluster encryption is acknowledged. `production.documentationRenderOnly`
exists solely for CI's non-deploying example render and is prohibited elsewhere.
Define exact `networkPolicy.backendEgressRules`, `workerEgressRules`, and
`migrationEgressRules` for each workload. Migration should reach only DNS and
its database endpoint; it must not inherit S3, IdP, Redis, or workload-identity
destinations it does not use. Do not use a blanket VPC or internet CIDR.

For EKS Pod Identity over IPv4, the AWS-documented credential endpoint is
`169.254.170.23:80`; include only that link-local `/32` and port. Confirm the
cluster's approved identity mode and IPv4/IPv6 configuration before rendering.

Use `rediss://` for Redis, TLS-enabled PostgreSQL URLs, HTTPS S3-compatible
endpoints, HTTPS SAML URLs, and an HTTPS in-boundary OTLP collector. Mount its
approved CA from `cadverify-otel-ca`; the application refuses a regulated OTLP
configuration without both HTTPS and the CA path.

Bind the workload identity to only the required bucket/prefix operations:
bucket-level prefix-constrained `s3:ListBucket`, and object-level `s3:GetObject`,
`s3:PutObject`, `s3:DeleteObject`, and multipart-upload operations. Allow only
the named customer-managed KMS key actions required for S3 encryption/decryption
and data-key generation, constrained through the S3 service and approved
encryption context. Prohibit public ACLs, unencrypted puts, cross-account access,
and access outside the regulated prefix. Retain the IAM policy, bucket policy,
KMS policy, and access-test evidence with the boundary package.

The frontend image is intentionally environment-neutral:

```bash
docker build frontend \
  --build-arg NEXT_PUBLIC_SENTRY_DSN= \
  --tag <approved-registry>/cadverify-frontend:<git-sha>
```

`API_BASE` is injected at runtime by the chart and public browser reads use a
narrow same-origin proxy. Regulated telemetry should remain inside the approved
boundary; leave external browser Sentry disabled unless explicitly in scope.
The ingress sends only `/api/v1`, `/auth`, `/scim/v2`, and `/health` to FastAPI.
Next.js owns public `/s/*` pages plus `/api/auth`, `/api/proxy`, and
`/api/public-share` through the `/` frontend rule; its server reads sanitized
share JSON from FastAPI over the private Service URL. Never widen the backend
rule to `/api` or route `/s` directly to FastAPI.

## 6. Render and policy-check

```bash
helm lint charts/cadverify

helm template cadverify charts/cadverify \
  --namespace cadverify \
  --values <private-regulated-values.yaml> \
  --set production.operatorAcknowledgement=CONFIGURED_EXTERNAL_DEPENDENCIES \
  > /tmp/cadverify-regulated.yaml
```

Run the approved Kubernetes policy scanner against the rendered manifest. Confirm
immutable images, non-root/read-only containers, seccomp, dropped capabilities,
no service-account token, S3 storage, TLS ingress, PDBs, topology spread, HPAs,
resource limits, and deny-by-default networking.

The landing zone must place a namespace-level default-deny policy before the first
Helm install. Helm migration hooks run before ordinary chart resources, so the
pre-existing boundary—not a not-yet-created chart policy—must protect the first
migration Job.

## 7. Deploy staging

```bash
helm upgrade --install cadverify charts/cadverify \
  --namespace cadverify \
  --create-namespace \
  --values <private-regulated-values.yaml> \
  --set production.operatorAcknowledgement=CONFIGURED_EXTERNAL_DEPENDENCIES \
  --atomic \
  --timeout 20m
```

The pre-install/pre-upgrade migration uses `DATABASE_URL_DIRECT` when present.
`--atomic` rolls application resources back on failure; it does not reverse a
database migration. Every migration therefore needs a compatibility/rollback
decision before promotion.

## 8. Acceptance evidence

- Deep health shows Postgres, Redis, worker heartbeat, and queue state healthy.
- The same-host `/api/auth/proxy-health` handshake passes, proving the frontend
  can forward ingress-observed client IPs to API abuse controls with the shared
  `AUTH_PROXY_SECRET` without trusting browser-supplied forwarding headers.
- Real approved IdP login and Redirect-bound logout work; forged, unsigned,
  replayed, expired, wrong-audience, and deactivated-user cases fail.
- The frontend exposes the configured SAML initiation path, while direct
  password login, public password signup, password initialization, magic-link
  auth, external Sentry, and remote reconstruction remain disabled in the
  approved baseline. OIDC needs a separately reviewed release overlay.
- SCIM create/group-change/deactivate revokes access as designed.
- Real STEP upload/cost/export succeeds using the regulated S3 bucket.
- Cross-organization object IDs return 404 with no timing/body existence leak.
- Network tests prove prohibited egress and metadata-service access are denied.
- KMS/S3/RDS/Redis encryption, key separation, and audit logs are evidenced.
- Eight-hour and 24-hour soak tests pass defined thresholds.
- Backup restore and worker/DB/AZ failure drills meet the approved RPO/RTO.
- Incident exercises cover leaked credentials, unauthorized export/access,
  tenant exposure, failed migration, corrupted CAD, and region outage.
- Independent penetration test and required CMMC/customer assessment conditions
  are closed or formally accepted by the authorized owner.

## 9. Production promotion

Promote only the exact signed staging digests. Repeat secret, manifest-policy,
migration, deep-health, IdP, object-store, tenant-isolation, and alert-delivery
gates. Record image digests, chart/values hashes (without secrets), approvers,
test evidence, database migration head, and rollback image in the release record.

## 10. Operations

- Separate production roles for platform, security, key, database, and audit
  administration; review access at least monthly and on every personnel change.
- Monitor auth failures, privilege changes, object access, egress, queue depth,
  worker heartbeat, database/cache health, backup status, and key changes.
- Restore drills at least quarterly and after material backup architecture changes.
- Patch and rotate under documented SLAs; emergency changes retain two-person
  approval and post-incident evidence.
- Reassess the boundary whenever a connector, support tool, AI service, telemetry
  destination, region, or subprocess is added.

## Official anchors

- NIST SP 800-171 Rev. 3: https://csrc.nist.gov/pubs/sp/800/171/r3/final
- NIST SP 800-171A Rev. 3: https://csrc.nist.gov/pubs/sp/800/171a/r3/final
- CMMC program rule, 32 CFR part 170: https://www.ecfr.gov/current/title-32/subtitle-A/chapter-I/subchapter-D/part-170
- ITAR, 22 CFR parts 120-130: https://www.ecfr.gov/current/title-22/chapter-I/subchapter-M
- AWS GovCloud compliance guidance: https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-compliance.html
