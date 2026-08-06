# ProofShape production launch audit

Date: 2026-07-14

Commercial software verdict: **PRODUCT-PROVEN AND CLOUD-DEPLOY-READY**

Commercial live verdict: **BLOCKED FOR PRODUCTION-LIVE**

Regulated verdict: **BLOCKED; DO NOT INTRODUCE REGULATED DATA**

This audit uses the claim definitions in
`docs/PRODUCTION_ACCEPTANCE_CONTRACT.md`. It does not treat repository code,
static infrastructure validation, or an old deployment as live evidence.

## Claim status

| Claim | Status | Evidence still required |
|---|---|---|
| Product-proven | Recorded | The current clean release manifest reports `LOCAL_GATE_PASS`: 64/64 canonical browser and recovery contracts across ten suites, with aligned mobile, direct-S3, manufacturing/import, representative-CAD, role/notification, training-guide, and interactive-deck evidence. This claim must be regenerated after any repository change. |
| Cloud-deploy-ready | Recorded | Reproducible production builds, migration chain, validated AWS IaC, exact OIDC subjects, exact-image scan/SBOM binding, supplier-holdout gate, AWS kill switch, deep health, restore/rollback procedures, alarms, and operator runbooks are present and statically validated. No account plan/apply is implied. |
| Production-live | No | ProofShape-owned AWS/provider resources, real secrets, staged deployment, live acceptance, recovery/alert evidence, exact-digest production promotion, and human go/no-go. |

No local evidence may convert `production-live` into a stronger claim without
the external evidence below.

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
  the same bytes to staging and production ECR, scans and generates CycloneDX
  SBOMs from those exact loaded images, verifies matching digests, validates the
  exact-release supplier holdout in both environments, runs migration,
  stabilizes ECS, performs CloudFront deep health and a staging AWS kill-switch
  drill, and restores prior task definitions after rollout failure.
- The obsolete `.github/workflows/saas-promote.yml` is deleted. Fly files that
  remain are legacy/non-release material and are not called by the canonical
  workflow.
- The application contains fail-closed production auth, tenant isolation,
  transactional audit, worker health, object-store, timeout/cancellation,
  browser security, and release-health controls. These reduce risk but do not
  replace the exact-build and live gates.

## External evidence that does not exist yet

- No account-bound Terraform plan or apply against a ProofShape AWS account.
- No AWS ECR push, ECS migration, service rollout, or CloudFront deep-health
  record.
- No real Resend, Turnstile, Sentry/alert, DNS/certificate, budget alarm, or
  external uptime evidence.
- No AWS RDS restore, Redis AUTH/queue, durable-version retention, transient
  physical-delete, worker interruption, kill-switch, or prior-digest rollback
  drill.
- No production promotion or production hostname.
- No accountable legal/name/IP approval or real customer/supplier holdout
  evidence has been supplied to the implemented release gate.
- No approved GovCloud/customer regulated boundary or execution evidence.

## Blocking findings

| Severity | Plane | Finding | Required closure evidence |
|---|---|---|---|
| Critical | Regulated | No approved CUI/ITAR classification, system/data-flow boundary, Technology Control Plan, contract scope, or authorized operator roster exists. | Written counsel/security decision, approved boundary and data flow, personnel authorization, and accountable owner approval. |
| Critical | Regulated | No GovCloud/customer-controlled landing zone or approved CI/evidence control plane exists. | Approved account/cluster, private data plane, IdP, registry, runners, telemetry/SIEM, backups, private values, and retained execution evidence. |
| High | Commercial | No ProofShape AWS staging or production stack has been planned/applied. | Reviewed account-bound Terraform plans and applies, distinct state/data boundaries, populated secret versions, verified Redis AUTH, and enabled services. |
| High | Commercial | No real-provider staging acceptance or operational recovery evidence exists. | Staging workflow evidence, email/Turnstile/Sentry delivery, deep health, multipart S3, restore, alarms, load, interruption, kill switch, and rollback records. |
| High | Commercial | No licensed customer-relevant supplier/CAD accuracy evidence or accountable approval has been supplied. The workflow gate exists but cannot fabricate its confidential input. | Provenance-locked holdout satisfying `docs/SUPPLIER_HOLDOUT_EVIDENCE.md`, accountable review, exact-release binding, and protected production approval. |
| High | Commercial | ProofShape name/domain/IP and launch legal documents are not approved. | Documented name/IP clearance, domain ownership, terms/privacy decisions, and accountable approval. |

## Commercial go/no-go rule

Commercial production remains blocked until:

1. the recorded `product-proven` and `cloud-deploy-ready` claims are regenerated
   for the final exact clean commit after any change;
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

**The software is product-proven and cloud-deploy-ready; do not claim
production-live and do not introduce regulated data.** Provision only new
ProofShape-owned commercial AWS/provider resources, run credentialed staging,
and retain every live acceptance artifact before production promotion. Arcus
remains prohibited.
