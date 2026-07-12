# Dual Production Launch Audit

Date: 2026-07-11
Verdict: **BLOCKED**

This verdict applies to both the commercial SaaS launch and any regulated
CUI/ITAR deployment. The repository now contains fail-closed production paths,
but neither external environment has supplied the evidence required to change
this verdict. No production deployment is authorized by this document.

## What is implemented

- Commercial images are built from protected `main`, scanned, SBOM-recorded,
  and captured by immutable digest in a CI-owned release artifact.
- `.github/workflows/saas-promote.yml` deploys that exact release to isolated
  staging first. `staging-only` is the default and cannot start production. The
  explicit `staging-and-production` scope requires protected supplier evidence;
  its production job depends on staging and reuses the same digests. Direct
  `main`-to-production deployment was removed.
- The commercial backend fails closed on missing production S3,
  observability, canonical HTTPS dashboard origin, TLS Redis, and required auth
  secrets. Token-protected deep health probes Postgres, Redis, queue/worker
  state, and an S3 write/read/list/delete/KMS canary; unauthenticated Prometheus
  exposition is disabled on the public Fly API hostname.
- Password and magic-link requests use a short-lived HMAC-signed client-IP
  handoff through the first-party frontend. Magic links keep tokens in URL
  fragments, require explicit consumption, and exchange sessions server-side;
  production session-returning password/magic endpoints reject unsigned direct
  callers, and promotion verifies the shared proxy secret end to end.
- Released commercial account creation is email-first; an authenticated user
  may add a password once and the operation rotates prior sessions. Released
  SAML regulated baseline disables all password login/signup/setup surfaces and
  renders the actual IdP initiation link. Its private profile gate requires
  strict signed-message/assertion/SHA-256 settings and HTTPS endpoints, while
  ACS and SP-initiated SLO bind responses to one-time Redis-backed request
  IDs/RelayState.
- Released dashboard-session validation fails closed if the authoritative user
  and revocation state cannot be read; a database outage cannot silently bypass
  deactivation or session-version enforcement.
- Security-sensitive mutations append their audit row in the same database
  transaction. OIDC/SAML/magic-link provisioning, default-key state, group
  assignment, and login evidence commit once before a session is issued; API-key
  rotation also revokes, replaces, and audits in one transaction. Audit failures
  therefore roll back or block the protected action instead of being lost in a
  background task.
- OIDC users are bound to unique immutable issuer+subject identities. First-time
  creation requires an explicitly verified email, an existing email cannot be
  silently linked, and a mapped subject cannot switch to a reassigned address.
  Discovery must return the exact configured issuer; every discovered endpoint
  is restricted to credential-free HTTPS on the issuer or an explicitly reviewed
  origin and is rejected when it resolves to a non-public network destination.
- Timed-out or cancelled untrusted CAD parses hard-kill their process workers,
  both API and ARQ startup reject in-process parsing in released builds, and
  protected browser CI fails required 4xx/5xx/unavailable journey skips.
- Magic-link rotation/failure cleanup is atomic and cluster-slot safe; corpus
  assets from GitHub are pinned to a commit with the exact license artifact
  validated and hashed at that commit.
- Protected CI rejects unapproved runtime and collection-time skips. Costing,
  AS1 assembly, NIST STEP, lifecycle cleanup, and OIDC issuer/subject/audience/
  time/nonce boundaries run from reproducible local fixtures.
- Initial-password creation and session rotation are one database transaction;
  concurrent parts-master imports use isolated object prefixes, and large
  reconstruction meshes stream from object storage instead of buffering in API
  memory.
- Per-request CSP nonces gate scripts, Sentry session replay is disabled, and
  backend/frontend Sentry payloads scrub auth material before export.
- Customer CAD, batch, reconstruction, mesh, RFQ, and cost-PDF paths use the
  object-store abstraction. Fly local files are disposable scratch/cache only.
- The regulated Helm path requires immutable digests, external secrets, S3
  KMS, HTTPS OTLP with an approved CA, TLS ingress, multi-replica workloads,
  disruption budgets, topology spread, non-root/read-only containers, and
  deny-by-default networking.
- Regulated release/deploy workflows require approved self-hosted GovCloud
  U.S.-person runners, separate OIDC roles, KMS signatures, signed release
  attestations, a successful push-triggered CI run for the exact source SHA,
  private values, server-side dry run, atomic deployment, and deployment
  evidence. The approved manifest is SAML-only, overrides external Sentry and
  remote reconstruction off, forces HTTPS, and verifies the real TLS ingress
  auth-proxy handshake. Staging and production must also resolve to distinct
  verified account/cluster/namespace fingerprints. Public `/s/*` pages remain
  on Next while their sanitized JSON is fetched over the internal backend
  service.

These controls reduce launch risk; they do not constitute FedRAMP, CMMC,
NIST 800-171, export-control, or customer authorization.

## Blocking findings

| Severity | Finding | Required closure evidence |
|---|---|---|
| Critical | No approved CUI/ITAR boundary, export classification, data-flow determination, Technology Control Plan, or authorized-person/operator roster has been supplied. | Written legal/export-control decision, system boundary/data-flow, personnel authorization, subcontractor/support scope, and accountable owner approval. |
| Critical | No GovCloud/customer regulated landing zone is provisioned or evidenced. | Approved GovCloud account, private EKS, RDS, Redis, S3/KMS, ECR, IdP, runner, SIEM/OTLP, network controls, backups, and private values with control-owner evidence. |
| Critical | The regulated CI control plane, action sources, runner image/egress, job logs, and evidence destination have not been approved as part of the boundary. | Written approval for the exact GitHub/GHES control plane and runner design, or move the workflow/evidence path fully in-boundary and retain an approved execution record. |
| High | The current live Fly applications do not satisfy the new commercial secret/runtime contract; the deployed API predates `/health/deep`, and the frontend was stopped when inspected. | Separate staging/production apps; API/web secrets including one matching `AUTH_PROXY_SECRET`; remove every forbidden config-shadowing Fly secret reported by the gate; custom DNS/TLS; successful protected staging promotion; deep health and proxy handshake; manual auth/STEP/tenant tests. |
| High | Production hardening remains in draft PR #24 targeting protected `main`; it is not merged or releasable yet. | Review the final diff, require green protected checks for the exact merge SHA, merge to `main`, and retain the resulting digest/SBOM release evidence. |
| High | No production acceptance evidence exists for real email, Turnstile, Sentry alert delivery, S3 lifecycle/deletion, custom domains, cross-tenant probes, or rollback. | Execute and retain the acceptance records in the applicable runbook. |
| High | Cost-model CI proves deterministic regression behavior against internally authored coupons; no real protected supplier holdout has been supplied yet. Technical `staging-only` runs are explicitly not approval evidence and cannot reach production. The full `staging-and-production` scope fails closed without fresh, matching evidence bound to the exact release SHA. | Supply the protected record defined in `docs/SUPPLIER_HOLDOUT_EVIDENCE.md`: at least 20 licensed/provenance-locked holdout parts, at least 5 parts and 3 independent suppliers per launch family, retained human approval, MAPE ≤30%, P90 absolute error ≤50%, and every process median bias within ±25%. |

## Commercial go/no-go rule

Change the commercial verdict only after all blockers not explicitly limited to
the regulated path are closed, `saas-staging` passes the complete acceptance
suite, a human reviews the evidence, and the protected `saas-production`
environment approves promotion. A successful CI build alone is not a go-live.

## Regulated go/no-go rule

Do not upload, process, log, back up, or support CUI/ITAR data until the
authorized legal/security owner has approved the boundary and data-flow, every
in-boundary dependency and operator is approved, the assessment/control gaps
are closed or formally accepted, regulated staging passes the runbook, and the
protected production promotion is independently approved.

## Current decision

**BLOCKED — do not deploy production and do not introduce regulated data.**
