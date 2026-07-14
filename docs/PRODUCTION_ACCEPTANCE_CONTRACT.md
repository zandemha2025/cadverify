# ProofShape production acceptance contract

Status: binding launch gate

This document defines what ProofShape may call "working," "deploy-ready," and
"live." A passing unit test, a loaded page, or a successful infrastructure
apply is not enough on its own.

## Claims

ProofShape uses three separate claims:

1. **Product-proven** — the exact clean commit completes the supported user
   journeys through a real browser, real Postgres and Redis, real background
   workers, and both local and S3-compatible object-storage paths. Visible,
   persisted, numerical, downloadable, authorization, failure, and recovery
   outcomes must all match their golden-path contracts.
2. **Cloud-deploy-ready** — the same commit has reproducible images, a valid
   migration chain, validated AWS infrastructure code, least-privilege
   deployment identity, secret placeholders, backup/restore procedures,
   rollback procedures, alarms, and an operator runbook. This claim does not
   imply that an AWS account has been provisioned.
3. **Production-live** — the deploy-ready commit is running in a ProofShape-
   owned account on its immutable image digests and has passed the live gates
   in this document using real external providers. This claim cannot be made
   before account access, provider credentials, DNS or an approved AWS-hosted
   HTTPS hostname, and launch evidence exist.

The commercial SaaS and regulated/CUI planes remain separate. Passing this
contract for commercial SaaS does not authorize regulated data or claim CMMC,
FedRAMP, NIST 800-171, ITAR, SOC 2, or legal compliance.

## Product-proven gate

All rows are blocking and evidence must name the same Git commit.

| Area | Required evidence |
|---|---|
| Build identity | Clean checkout; frontend and backend report the exact commit they serve before and after browser testing. |
| Code gates | Backend tests, real Postgres migration upgrade/downgrade/upgrade, type regression gate, frontend tests/typecheck/lint/build, dependency audit, and medium-or-higher static security gate pass. |
| Human journeys | The canonical local browser release gate passes every required public, auth, onboarding, CAD, analysis, cost, decision, compare, export, batch, RFQ, organization, role, tenant, notification, recovery, and mobile contract with no unexpected console, request, or HTTP failure. `LOCAL_GATE_PASS` is necessary but is not by itself the broader product-proven claim. |
| CAD truth | Tracked STEP fixtures and the approved real-CAD corpus produce the expected geometry, DFM, costing, artifact, and failure results. Unsupported, malformed, or unmeshable inputs return actionable truth; they never fabricate success. |
| Large files | A browser uploads a production-sized ZIP directly with multipart S3, refreshes during preparation/processing, reaches one durable terminal batch, downloads the correct result, and can safely retry or abort interrupted uploads. Browser traffic must not expose cloud credentials. |
| Authorization | The full role/tenant matrix passes; cross-organization reads and mutations are denied without leaking record existence. Direct-upload identifiers and object keys are organization scoped. |
| Durability | Customer artifacts use the object-store abstraction; API or worker restart does not lose accepted durable work; retries are idempotent and do not duplicate analyses or batches. |
| Failure/recovery | Queue, worker, CAD kernel, object store, timeout, cancellation, stale decision, session, network, and refresh paths show exact recovery actions and reach a truthful persisted state. |
| Usability | Desktop and mobile journeys have no dead controls, contradictory navigation, hidden required steps, placeholder success, indefinite spinner, or unexplained "temporarily busy" state. |
| Training | The interactive platform guide is tested against the same build. Every instructed action and claimed outcome maps to a passing golden path. |

"All customer CAD files work" is not an acceptable claim: CAD is an open input
space. Launch scope must name supported formats, size/complexity limits, and a
representative customer or licensed holdout corpus. A supported file that fails
its contract is a product defect; an unsupported file must be rejected clearly
before the platform implies a result exists.

## Cloud-deploy-ready gate

| Area | Required evidence |
|---|---|
| Ownership | Every hostname, cloud account, repository environment, registry, bucket, key, provider project, and billing relationship is ProofShape-owned. Arcus resources are prohibited. |
| Isolation | Staging and production use separate state, data stores, cache namespaces, buckets/prefixes, secrets, deployment approvals, and external-provider environments. |
| Network | CloudFront provides the public HTTPS origin, the load balancer accepts only the intended CloudFront origin path, compute has no inbound administrative port, and Postgres/Redis are private. |
| Identity | GitHub deploys through environment-scoped OIDC with exact repository/environment subject conditions. Runtime tasks use separate least-privilege roles; no long-lived AWS access key is stored in GitHub. |
| Data | RDS encryption/backups/PITR, Redis TLS/auth/encryption, S3 block-public-access/versioning/KMS/lifecycle/incomplete-multipart cleanup, and log retention are configured. |
| Compute | Immutable ECR images run as separate frontend, API, and worker services. Health checks, deployment circuit breakers, graceful shutdown, resource limits, and rollback to a prior digest are defined. |
| Secrets | Terraform and Git contain no secret values. Secrets Manager entries are populated out of band and task definitions reference versions/ARNs without printing values. |
| Operations | Deep health, queue/worker health, 5xx/latency/CPU/memory/database alarms, budget alarms, dashboards/logs, a kill switch, database restore, and deploy rollback have executable procedures. |
| Cost mode | Budget staging and high-availability production settings are explicit. A cheaper single-task or single-AZ profile must never be represented as high availability. |
| Validation | Terraform formatting/init/validate and policy checks pass from a clean checkout; workflow and shell syntax pass; production images build for the declared ECS architecture. |

## Production-live gate

The first launch is a staged promotion, not an unobserved `terraform apply`.

1. Provision ProofShape staging and populate real secrets without exposing them
   in chat, Git, shell history, Terraform state, or CI logs.
2. Apply migrations from the immutable backend image, deploy API/worker/web,
   and require healthy ECS stabilization and authenticated deep health.
3. Run the full product-proven browser suite against staging, including direct
   multipart S3 upload, two-organization isolation, refresh/restart durability,
   and real email/Turnstile/Sentry delivery.
4. Exercise database restore into a scratch target, S3 lifecycle/deletion,
   worker interruption/retry, kill switch, and previous-digest rollback. Record
   measured RPO/RTO and the exact image digests.
5. Run a production-like load profile. There must be no unexplained 5xx;
   overload must fail with bounded, retryable behavior rather than timeouts or
   fabricated results.
6. Promote the exact staging image digests through the protected production
   environment. Re-run smoke, auth, tenant isolation, real STEP, export,
   observability, and rollback-readiness gates on the production hostname.
7. A human owner reviews the evidence and explicitly records go/no-go.

## External inputs that cannot be fabricated in code

- ProofShape AWS payer/account access and a GitHub OIDC bootstrap role.
- A launch region and budget notification addresses.
- Resend account, verified sender/domain, and delivery test inboxes.
- Cloudflare Turnstile production site/secret keys.
- Sentry projects and a real alert destination.
- Optional custom domain and DNS. An AWS CloudFront hostname may be used for
  staging before a custom domain exists.
- Customer-authorized CAD/cost holdout data and acceptance owner.
- Legal, privacy, terms, IP/name clearance, export-control, and regulated-data
  decisions appropriate to the actual launch.

Until those inputs exist, engineering may truthfully report **product-proven**
and **cloud-deploy-ready**, but not **production-live**.
