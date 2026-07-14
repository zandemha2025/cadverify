# ProofShape production launch audit

Date: 2026-07-14

Commercial verdict: **BLOCKED FOR PRODUCTION-LIVE**

Regulated verdict: **BLOCKED; DO NOT INTRODUCE REGULATED DATA**

This audit uses the claim definitions in
`docs/PRODUCTION_ACCEPTANCE_CONTRACT.md`. It does not treat repository code,
static infrastructure validation, or an old deployment as live evidence.

## Claim status

| Claim | Status | Evidence still required |
|---|---|---|
| Product-proven | Not yet recorded | Fresh exact-clean-build browser evidence under the v2 screenshot/DOM contract, full supported journey matrix, representative CAD, roles/tenants, failure/recovery, and mobile proof. |
| Cloud-deploy-ready | Candidate, not yet recorded | Final clean-checkout application/image gates and review of the integrated AWS/workflow changes. Terraform format/validate, actionlint, shellcheck, and script syntax have passed; no account plan/apply occurred. |
| Production-live | No | ProofShape-owned AWS/provider resources, real secrets, staged deployment, live acceptance, recovery/alert evidence, exact-digest production promotion, and human go/no-go. |

No document may convert “candidate” into a stronger claim without the missing
evidence.

## Implemented commercial controls

- `infra/aws` defines isolated staging and production stacks for the
  `proofshape-commercial` boundary. Arcus names and resources are rejected.
- CloudFront is the only public release edge. It reaches an internal ALB through
  an account/VPC CloudFront VPC origin; the ALB defaults to 403 and accepts
  traffic only from the VPC-origin service security group.
- Production/HA fails closed without a custom alias, viewer and origin
  certificates, TLS 1.2, WAF and WAF logs, CloudFront/ALB access logs, and ALB
  deletion protection.
- The frontend is configured with `AUTH_PROXY_CLIENT_IP_SOURCE=cloudfront` and
  accepts the single `CloudFront-Viewer-Address` value. It does not use the ALB
  `X-Forwarded-For` chain as authenticated viewer identity.
- ECS uses digest-pinned Fargate frontend, API, worker, and one-shot Alembic
  task families. Containers are non-root with read-only roots and explicit
  writable scratch/cache mounts. Services have deployment circuit breakers.
- Private RDS and ElastiCache provide the data plane. RDS has encrypted backup/
  PITR controls. Redis requires TLS and out-of-band AUTH before services can be
  enabled.
- Durable customer evidence and transient incoming uploads use separate KMS S3
  buckets. Durable evidence is versioned. Transient uploads are deliberately
  unversioned so successful application deletion is physically truthful;
  lifecycle expiration is only a backstop.
- GitHub deploy roles use exact repository/environment OIDC subjects and
  environment-specific least privilege. No long-lived AWS key is required in
  GitHub.
- `.github/workflows/ci.yml` is build/test proof and has no deploy job or Fly
  registry publication.
- `.github/workflows/aws-commercial-promote.yml` requires exact-SHA successful
  CI, builds one backend/frontend archive set, seals archive hashes, publishes
  the same bytes to staging and production ECR, verifies matching digests, runs
  migration, stabilizes ECS, performs CloudFront deep health, and restores prior
  task definitions after rollout failure.
- The obsolete `.github/workflows/saas-promote.yml` is deleted. Fly files that
  remain are legacy/non-release material and are not called by the canonical
  workflow.
- The application contains fail-closed production auth, tenant isolation,
  transactional audit, worker health, object-store, timeout/cancellation,
  browser security, and release-health controls. These reduce risk but do not
  replace the exact-build and live gates.

## Evidence that does not exist yet

- No Terraform plan or apply against a ProofShape AWS account.
- No AWS ECR push, ECS migration, service rollout, or CloudFront deep-health
  record.
- No real Resend, Turnstile, Sentry/alert, DNS/certificate, budget alarm, or
  external uptime evidence.
- No AWS RDS restore, Redis AUTH/queue, durable-version retention, transient
  physical-delete, worker interruption, kill-switch, or prior-digest rollback
  drill.
- No production promotion or production hostname.
- No accountable legal/name/IP or commercial supplier-holdout approval.
- No approved GovCloud/customer regulated boundary or execution evidence.

## Blocking findings

| Severity | Plane | Finding | Required closure evidence |
|---|---|---|---|
| Critical | Regulated | No approved CUI/ITAR classification, system/data-flow boundary, Technology Control Plan, contract scope, or authorized operator roster exists. | Written counsel/security decision, approved boundary and data flow, personnel authorization, and accountable owner approval. |
| Critical | Regulated | No GovCloud/customer-controlled landing zone or approved CI/evidence control plane exists. | Approved account/cluster, private data plane, IdP, registry, runners, telemetry/SIEM, backups, private values, and retained execution evidence. |
| High | Commercial | No ProofShape AWS staging or production stack has been planned/applied. | Reviewed account-bound Terraform plans and applies, distinct state/data boundaries, populated secret versions, verified Redis AUTH, and enabled services. |
| High | Commercial | The exact commit has not completed the fresh product-proven evidence gate. | Clean-commit code gates plus the full human-simulated browser, representative CAD, role/tenant, failure/recovery, artifact/numerical, and mobile evidence set. |
| High | Commercial | No real-provider staging acceptance or operational recovery evidence exists. | Staging workflow evidence, email/Turnstile/Sentry delivery, deep health, multipart S3, restore, alarms, load, interruption, kill switch, and rollback records. |
| High | Commercial | CI scans and generates SBOMs for a CI-local image build, while the AWS promotion workflow creates a separate sealed archive build. Staging and production share exact bytes, but the deployed bytes are not yet cryptographically the same bytes covered by CI's image scan/SBOM. | Either promote a CI-owned sealed image artifact or scan and generate SBOMs for the exact AWS archive hashes before ECR publication, then bind those results to the staged/production ECR digests. |
| High | Commercial | Customer-relevant supplier/CAD accuracy approval is external and is not currently enforced by the AWS promotion workflow. | Licensed/provenance-locked holdout satisfying `docs/SUPPLIER_HOLDOUT_EVIDENCE.md`, accountable review, exact-release binding, and a protected production approval that cannot be bypassed. Automating this gate remains source work unless the owner accepts a documented manual control. |
| High | Commercial | The checked-in kill-switch helper is Fly-specific; the AWS stack has rollout rollback but no proved AWS-native command/control for stopping new analyses without an ad hoc task-definition edit. | Implement and stage-test an AWS-scoped, account/boundary-checked kill switch with retained evidence, plus a safe restore procedure. |
| High | Commercial | ProofShape name/domain/IP and launch legal documents are not approved. | Documented name/IP clearance, domain ownership, terms/privacy decisions, and accountable approval. |

## Commercial go/no-go rule

Commercial production remains blocked until:

1. `product-proven` and `cloud-deploy-ready` are recorded for one exact clean
   commit;
2. isolated AWS staging passes every live gate in
   `docs/PRODUCTION_ACCEPTANCE_CONTRACT.md`;
3. the supplier/customer and legal/name approvals are retained;
4. production uses the exact staged artifact digests through the protected
   `aws-commercial-production` environment; and
5. a human owner reviews the complete evidence and records go/no-go.

A successful CI run, Terraform validation, publish-only ECR seed, or reachable
CloudFront page is not a go-live decision.

## Regulated go/no-go rule

Do not upload, process, log, back up, or support CUI/ITAR data until an
authorized legal/security owner approves the boundary and data flow, every
dependency and operator is in scope, regulated staging passes the dedicated
runbook, and the protected production promotion is independently approved.

## Current decision

**Do not claim production-live and do not introduce regulated data.** Continue
engineering proof locally, then provision only new ProofShape-owned commercial
AWS resources. Arcus remains prohibited.
