# ProofShape non-Arcus AWS staging runbook

Status: infrastructure code exists; external account provisioning and deployment
have not occurred

Target branch: `codex/proofshape-scalecad-staging`

Protected external system: Arcus Vercel `eager-euler` and every Arcus resource
are out of scope

## Outcome

This runbook creates one production-shaped ProofShape commercial staging
environment where a real user can sign in, complete onboarding, create/revise
CAD, preview/download exact revisions, send generated or uploaded CAD into
DFM/should-cost verification, and use the portfolio/decision/batch/RFQ flows.

Staging can earn live technical and product evidence. It cannot by itself earn
production-live, regulated authorization, name/IP clearance, or customer cost-
accuracy approval.

## Ownership boundary

- Create every account, state store, resource, provider project, domain, secret,
  and billing relationship in a new ProofShape-owned or owner-controlled scope.
- Do not use the Arcus Vercel team/project, any Arcus cloud organization,
  domains, billing, source settings, aliases, or secrets.
- Do not attach a ProofShape alias to `eager-euler` or redeploy it.
- ScaleCAD is an authorized product/capability reference for this branch. Public
  distribution still requires the source/IP evidence in
  `docs/PROOFSHAPE_SCALECAD_INTEGRATION.md`.

The checked-in Fly files and scripts are legacy/non-release references. AWS
commercial is the canonical staging path.

## Chosen staging topology

Use `infra/aws/environments/staging.tfvars.example` as the reviewed starting
profile:

| Layer | AWS staging target |
|---|---|
| Public URL | generated HTTPS CloudFront hostname; no purchased domain required |
| Origin | internal ALB through account/VPC CloudFront VPC origin; fixed 403 default |
| Web/API/worker | separate digest-pinned ECS Fargate services |
| Migration | one-shot digest-pinned Fargate Alembic task |
| Database | isolated encrypted RDS PostgreSQL with backups |
| Queue | isolated ElastiCache Redis with TLS and out-of-band AUTH |
| Durable artifacts | private KMS/versioned S3 evidence bucket |
| Incoming uploads | private KMS, deliberately unversioned transient S3 bucket |
| Email/bot/errors | Resend, Turnstile, Sentry, external uptime/alert delivery |
| Delivery | protected GitHub environment `aws-commercial-staging` and exact OIDC role |

Budget staging may honestly use one task per service, single-AZ RDS, and one
Redis node. It must be reported as non-HA and never relabeled production.

An all-Vercel deployment is not selected. The native CAD runtime, long-running
worker, Redis queue, background batch/reconstruction work, and large direct S3
uploads require the container/data plane defined here.

## Owner-supplied prerequisites

1. ProofShape staging AWS account access, billing, launch region, and budget
   notification address.
2. Terraform operator/bootstrap identity and GitHub OIDC bootstrap approval.
3. Protected GitHub environment `aws-commercial-staging`.
4. Real application database credentials, Redis AUTH token, cryptographic
   secrets, Resend sender/inbox, Turnstile pair, and Sentry/alert destination.
5. Optional staging domain. The generated CloudFront hostname is sufficient
   before a domain purchase.
6. Written source/name/IP approval before public or commercial distribution.

Never paste a secret into chat, source, issue comments, Terraform variables/
state, screenshots, or build logs.

## Ordered bootstrap

Follow `docs/AWS_ACCOUNT_BOOTSTRAP.md`; this summary is not a substitute.

1. Bootstrap isolated encrypted/versioned remote Terraform state.
2. Create ignored local staging backend/tfvars files from the examples.
3. Verify the exact account and plan with workloads/services disabled, image
   URIs empty, and cache/direct-upload attestations false.
4. Apply the reviewed foundation: VPC/subnets, internal edge, CloudFront, RDS,
   Redis metadata, S3/KMS, ECR, Secrets Manager metadata, logs/alarms, OIDC role.
5. Populate every runtime secret value out of band. Frontend and backend receive
   the same `AUTH_PROXY_SECRET`.
6. Run `scripts/ops/aws-enable-cache-auth.sh`; verify TLS/AUTH and set
   `cache_authentication_confirmed=true` only with retained evidence.
7. Copy Terraform's promotion outputs into the protected GitHub environment and
   store the matching deep-health token as an environment secret.
8. Run `AWS Commercial Promotion` with `publish-staging-only` for the reviewed
   exact SHA. Retain the image publication artifact.
9. Verify that backend digest consumes `DIRECT_UPLOAD_S3_*`; set
   `transient_upload_contract_confirmed=true`, add the digest-qualified images,
   enable workloads/services, and apply a reviewed plan.
10. Run the workflow with `staging-only`. Require migration exit zero, service
    stability, expected release identity, authenticated deep health, object
    storage, worker, and auth-proxy checks through CloudFront.

No step may point at an Arcus account or resource.

## Staging configuration truths

Terraform supplies the production-shaped runtime controls, including:

- canonical `API_BASE`, `API_ORIGIN`, and `DASHBOARD_ORIGIN` from CloudFront;
- `AUTH_PROXY_CLIENT_IP_SOURCE=cloudfront`;
- password plus verified magic-link UI with public unverified password signup
  disabled;
- mandatory S3, deep health, auth proxy, secret quality, SSRF, security header,
  host-only cookie, and TLS guards;
- separate durable and transient S3 variables;
- strict worker health and local, no-egress reconstruction; and
- exact release/build identifiers.

Do not shadow these reviewed controls with ad hoc runtime secret names. Every
Secrets Manager value must have `AWSCURRENT` before enabling services.

## Staging acceptance journey

Every item uses real staging dependencies, a fresh exact-build run, and at least
two organizations.

- [ ] CloudFront is the only release URL; the internal ALB is not reachable as
      a public origin and unrecognized paths hit the reviewed routing/default.
- [ ] `/health`, authenticated `/health/deep`, worker/object-store checks, and
      `/api/auth/proxy-health` pass with the exact release ID.
- [ ] A user completes Turnstile, receives a real magic link, creates the
      initial password, logs out/in, and exercises logout-all/revocation.
- [ ] Onboarding, Home, navigation, command palette, and empty states lead into
      Design Studio and Verify without contradictory or dead routes.
- [ ] Plate, bracket, and open enclosure produce real geometry, measured
      metadata, STL preview, and STEP; no mock/fallback geometry is accepted.
- [ ] Revision 2 leaves revision 1 preview/download/hash/Verify available.
- [ ] Generated and manually uploaded representative supported CAD return the
      expected geometry, DFM, numerical cost, persisted decision, and exports.
- [ ] A production-size ZIP uploads directly to transient S3, refreshes URLs,
      processes once, downloads the correct result, retries/cancels safely, and
      leaves no consumed transient object or browser cloud credential.
- [ ] Batch scheduling, cancellation/retry and reconstruction reach truthful
      terminal states through real workers.
- [ ] Viewer/auditor cannot mutate; the full role matrix matches the UI and API.
- [ ] The second organization receives tenant-obscuring denial for every first-
      org record, artifact, upload ID, batch, project, and revision identifier.
- [ ] Queue, worker, CAD kernel, object store, network, timeout, cancellation,
      stale state, refresh, and restart paths show a useful recovery and a
      truthful persisted terminal state.
- [ ] Sentry event, external uptime alert, budget alarm, WAF/access records, and
      backup status reach their accountable owners.
- [ ] RDS scratch restore, Redis interruption, durable-version retention,
      transient physical deletion, kill switch, and prior-digest rollback meet
      recorded outcomes/RPO/RTO.
- [ ] Desktop and mobile have no uncaught errors, indefinite spinner, hidden
      required action, placeholder success, or interaction-blocking layout.
- [ ] Load/soak has no unexplained 5xx; overload is bounded and retryable.

## Current blockers

No ProofShape AWS staging deployment evidence exists yet because account,
provider, and protected-environment inputs have not been supplied/applied in
this work. The exact commit also still needs its fresh final product/cloud proof
record before customer invitation.

Once the owner supplies those inputs through provider UIs, execute this runbook
without changing `eager-euler` or any other Arcus resource.
