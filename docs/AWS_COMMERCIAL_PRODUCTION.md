# ProofShape commercial AWS architecture and release contract

This stack is production-shaped for ProofShape commercial staging and
production. It deliberately excludes Arcus and regulated/customer-controlled
planes. `Boundary=proofshape-commercial` tags, environment-specific state,
GitHub subjects, names, CIDRs, keys, repositories, secrets, and data services
must remain isolated. Staging and production use different AWS accounts; the
promotion workflow rejects equal account IDs before production OIDC.

## Architecture

```text
Browser --HTTPS--> CloudFront + optional WAF
                         |
                private VPC-origin ENI
                         |
                  internal ALB (403 default)
                    /              \
          public-IP Fargate     public-IP Fargate
             frontend              API
                                      \
                  public-IP worker ----+----> private RDS / ElastiCache
                                      \
                           KMS S3 durable + transient buckets
```

The VPC spans exactly two supported AZs. Fargate tasks run in public subnets
with assigned public IPv4 addresses so ECS/ECR/Secrets Manager/CloudWatch and
approved SaaS bootstrap do not require a NAT gateway. Their security groups have
no internet ingress: frontend and API accept only ALB traffic, API additionally
accepts frontend traffic for Cloud Map, and worker/migration accept no ingress.
RDS, ElastiCache, and the internal ALB use private subnets with no default route.

This is an intentional cost/egress tradeoff. Public task addresses are not
release endpoints and do not make task ports publicly reachable. The task
security groups allow outbound TCP/443 to `0.0.0.0/0`; that is transport/port
restriction, not a destination allowlist. Application SSRF/connector guards
remain mandatory, and a compromised workload could still exfiltrate over HTTPS.
Customers requiring network-enforced destination control need a separately
designed egress-proxy/firewall and private AWS endpoints; that higher-cost plane
is not represented by this budget profile.

## CloudFront is the only public release edge

The AWS-provided `*.cloudfront.net` hostname is a working HTTPS staging release
URL before a domain is purchased. Terraform computes that canonical origin and
injects it into `DASHBOARD_ORIGIN`, `API_ORIGIN`, `API_BASE`, the S3 CORS rules,
workflow output, and health checks. If an alias is configured, the same
contracts switch atomically to `https://<alias>`.

Dynamic/default traffic has caching disabled and forwards all viewer cookies,
query strings, headers, and HTTP methods required by Next.js, API, auth, upload,
share, SCIM, and health routes. The origin request policy explicitly includes
`CloudFront-Viewer-Address`. Frontend receives
`AUTH_PROXY_CLIENT_IP_SOURCE=cloudfront`; this plane does not trust ALB
`X-Forwarded-For`. Only hashed `/_next/static/*` assets may use the managed
optimized cache policy.

The ALB is not public. CloudFront VPC origins create private ENIs and an
account/VPC service-managed security group. The ALB security group accepts only
the selected listener port from that service group; the distribution is created
only after that rule exists. The ALB listener defaults to a fixed 403 and only
reviewed path rules forward to API or frontend. The stack does not share the VPC
origin through RAM.

This is the origin-verification control replacing a secret header: an arbitrary
internet or other-account CloudFront distribution cannot address the private
ALB. A same-account principal powerful enough to create/share VPC origins is
already inside the AWS control-plane trust boundary and must be constrained by
account IAM/SCPs. No reusable origin secret is placed in Git or Terraform state.

The raw ALB hostname is never a release URL.

### TLS profiles

- Budget staging: viewer HTTPS uses the default CloudFront certificate; the
  private CloudFront-to-ALB connection may use HTTP.
- Production/HA: Terraform requires a custom alias, a `us-east-1` viewer ACM
  certificate, a regional ALB ACM certificate covering the same hostname,
  `TLSv1.2_2021` at the viewer, TLS 1.2 from CloudFront to ALB, and the ALB
  `ELBSecurityPolicy-TLS13-1-2-2021-06` policy.

Production/HA also blocks without WAF, redacted WAF logging, CloudFront and ALB
access logging, ALB deletion protection, and CloudFront `retain_on_delete`. The
baseline WAF uses AWS managed common, known-bad-input, and IP-reputation groups
plus a configurable viewer-IP rate limit. When an alias exists, a leading rule
blocks every noncanonical viewer `Host`, including use of the distribution
hostname as an alternate release URL. Generic body-size/XSS rules count rather
than block the legitimate large CAD multipart body; application upload bounds
remain authoritative. WAF records redact authorization, cookies, and query
strings. The dedicated CloudFront/ALB S3 log bucket remains sensitive because
CloudFront standard logs can contain request query strings; it requires public
blocking, delivery-compatible encryption, versioning/retention, and
security-role-only read access.

CloudFront VPC origins do not support gRPC or origin-request/origin-response
Lambda@Edge triggers. ProofShape's reviewed HTTP release paths do not depend on
those features.

## Data services

RDS PostgreSQL is private, KMS encrypted, forces TLS, exports logs, supports IAM
database authentication, uses automated backups/PITR, and can enable Multi-AZ,
Performance Insights, deletion protection, final snapshots, and retained
automated backups. Production tfvars enable the recovery/deletion controls.

ElastiCache Redis OSS is private, KMS encrypted at rest, TLS-required in
transit, and logs engine/slow events. `cache_node_count = 1` is an honest
single-node staging cost profile; two or more nodes enable Multi-AZ automatic
failover.

The provider's `auth_token` argument would persist a secret in Terraform state.
Therefore the stack creates only AUTH secret metadata and
`aws-enable-cache-auth.sh` applies the token out of band using ROTATE then SET.
Terraform ignores those two provider fields so it cannot remove the external
AUTH setting. API/worker services cannot be created until
`cache_authentication_confirmed = true`, and `REDIS_URL` must use `rediss://`
with that same token. The bootstrap interval before the helper runs is a real
residual: no workload service is allowed during it.

Terraform cannot observe the out-of-band AUTH state through the provider. Before
replacing the replication group, set `cache_authentication_confirmed = false`,
replace it, rerun the helper, verify authenticated Redis, update `REDIS_URL` if
needed, and only then attest `true` again. Leaving the boolean true across a
replacement is an invalid operational procedure.

## Truthful object-storage lifecycle

Customer bytes have two different lifecycle contracts:

| Store | Purpose | Versioning and deletion | Lifecycle |
| --- | --- | --- | --- |
| Durable evidence | accepted CAD, generated artifacts, batch evidence | Versioning enabled. Tasks may delete a current key but lack `DeleteObjectVersion`, so retained evidence versions cannot be permanently erased by the app. | No current-object expiration. Noncurrent retention is explicit: 90 days in the staging example, 365 days in production, or indefinite with `null`. Incomplete multipart uploads abort after the configured period. |
| Transient incoming uploads | unconsumed direct-upload ZIPs only | Versioning is deliberately never enabled, and the bucket policy denies `PutBucketVersioning`. Successful `DeleteObject` leaves no addressable current or noncurrent object, making `storage_cleaned_at` truthful. | Completed stragglers become eligible for asynchronous lifecycle expiration after two days by default (configurable only from 1–7); incomplete multipart uploads abort after one day. |

Both buckets use customer-managed KMS encryption, bucket keys, TLS 1.2 policy,
ownership enforcement, full public-access blocking, exact canonical-origin
CORS, and no wildcard origin. API and worker IAM can clean only
`<environment>/direct-uploads/*` in the transient bucket. Durable access is
limited to the environment prefix, and permanent version deletion is absent.
The non-customer `.cadverify-health` canary prefix has a separate one-day
current/noncurrent cleanup rule so recurring deep health does not consume the
customer-evidence retention window.

Task definitions export `DIRECT_UPLOAD_S3_BUCKET`,
`DIRECT_UPLOAD_S3_PREFIX`, `DIRECT_UPLOAD_S3_REGION`, and
`DIRECT_UPLOAD_S3_KMS_KEY_ID` separately from the durable `OBJECT_STORE_S3_*`
contract. Services are Terraform-blocked until an operator sets
`transient_upload_contract_confirmed = true`. That human attestation cannot waive
the workflow's exact-image gate: the sealed backend archive is run with distinct
durable/transient buckets and must construct the isolated
`<environment>/direct-uploads` store; the sealed frontend archive must start with
a read-only root and serve a CSP containing only the exact regional S3 upload
origin. A live multipart upload/consume/delete test remains blocking evidence.
Lifecycle is only an asynchronous backstop and must not be treated as proof of
immediate application cleanup.

## ECS workload controls

The stack creates four digest-pinned Fargate task families: frontend, API,
worker, and one-shot Alembic migration. Long-running services remain optional
until images and every secret version exist. Cloud Map publishes
`api.<environment>.proofshape.internal` for in-VPC API discovery.

Fargate uses an explicit `1.4.0` platform rather than mutable `LATEST`. The
cluster enables both on-demand and Spot capacity providers. Budget staging keeps
API/frontend on on-demand Fargate and may put only the durable/idempotent worker
on Spot; production/HA is Terraform-blocked unless every service uses on-demand
Fargate. CPU/memory pairs are checked against valid Fargate combinations, and
batch concurrency is explicitly bounded to protect worker memory.

Every container runs with `readonlyRootFilesystem=true`. API, worker, and
migration receive an explicit writable `/tmp` scratch volume; frontend receives
writable `/tmp` and `/app/.next/cache` volumes. Backend cache/blob directories
and `HOME`/`XDG_CACHE_HOME` resolve under `/tmp`. No blanket writable root is
accepted.

Execution roles can pull only the component's exact ECR repository, write only
its log group, and read only its named runtime secrets. API/worker task roles
have the two-bucket prefix permissions described above and KMS use constrained
through regional S3. Frontend and migration do not inherit object-store access.

### Reconstruction readiness is a release blocker when sold

The current production dependency lock intentionally does not install the local
TripoSR `torch`/`tsr` stack, while this AWS plane sets
`RECONSTRUCTION_BACKEND=local` and forbids silent remote egress. The application
therefore reports image-to-mesh reconstruction as unavailable instead of sending
customer imagery to a third party. Do not claim this feature is live. If it is
part of the launch offer, release remains blocked until a reviewed GPU/local
inference image and worker topology (including model provenance, capacity,
timeouts, health, cost, and exact-image acceptance) are implemented and tested,
or legal/security explicitly approve and the application implements a commercial
remote-egress contract. Neither outcome can be created by Terraform alone.

## Build, approval, and promotion contract

The GitHub OIDC role trust is exact to repository plus protected environment.
Its ECR policy has `GetAuthorizationToken` globally as required by ECR and
upload/download/`PutImage` actions only on the stack's backend/frontend
repository ARNs. ECR tags are immutable, scanning is on push, and repositories
use KMS encryption.

The AWS workflow does not accept caller-supplied digests. It:

1. checks that the requested SHA is protected-main reachable and has a successful
   exact-SHA `push` CI run on `main` (pull-request or manually dispatched CI is
   not sufficient);
2. builds backend/frontend once as `linux/amd64` Docker archives;
3. seals both archive hashes, runs the exact backend/frontend images under the
   release security/storage contract, scans those exact loaded images for every
   fixed or unfixed HIGH/CRITICAL finding, generates CycloneDX SBOMs from those
   same images, and binds image IDs plus machine-readable scan/SBOM hashes into
   a schema-2 manifest that publication re-verifies;
4. validates a confidential, release-bound supplier holdout before any staging
   migration/service mutation; production independently revalidates it after the
   protected-environment approval and requires the evidence digest to equal
   staging;
5. publishes the sealed bytes to exact staging ECR repositories;
6. downloads the same artifact for production and requires both ECR manifest
   digests to equal staging;
7. clones only the exact Terraform-produced baseline task-definition ARNs,
   validates their Fargate/read-only/role/storage shape, substitutes digest images
   and release IDs, runs Alembic, rolls services, waits stable, and proves API,
   worker, object store, auth proxy, frontend build header, and direct-upload CSP
   through canonical CloudFront;
8. performs an AWS-native staging kill-switch drill and restores the prior task
   definition before a final deep-health check; and
9. rolls updated services back to their prior task definitions if promotion
   fails.

Publish-only scopes seed ECR without requiring holdout evidence because they do
not mutate a database or runtime. Migration-only scopes solve first bootstrap
without starting an unmigrated service. Promotion scopes require existing
positive-desired-count services. The exact release artifact, scan evidence, and
SBOMs are retained in GitHub for 90 days; compliance evidence requiring longer
retention must be copied to the approved immutable evidence system. No production
rebuild is permitted inside one staging-to-production run.

The ECR lifecycle retains only the newest configured number of immutable
`release-` images, so rollback depth is bounded rather than an unbounded storage
bill. Confirm that a rollback target still exists before relying on it.

Automatic rollback is a service task-definition rollback only. Alembic is not
reversed. Every production migration must follow an expand/contract pattern that
remains compatible with the prior application revision; otherwise a task rollback
can restore old code against a new incompatible schema.

## Availability and cost profiles

| Control | Bootstrap staging | HA/production |
| --- | --- | --- |
| AZ footprint | Two AZ subnets | Two AZ subnets |
| API/frontend/worker | One task each; worker may use Fargate Spot | At least two each, all on-demand Fargate |
| RDS | Single-AZ | Multi-AZ |
| Redis | One node, no failover | At least two nodes, Multi-AZ failover |
| Autoscaling | Optional/off example | Enabled example with floor 2 |
| WAF/access logs | Optional for budget staging | Terraform-required |
| CloudFront origin TLS | Private HTTP allowed | HTTPS/TLS 1.2 required |
| NAT gateways | None | None; direct public-IP task egress remains |

Two AZ subnets do not make a one-copy bootstrap service highly available. The
`availability_posture` output reports actual copies and failover controls.

## Observability, recovery, and cost

CloudWatch log groups cover each ECS task family, RDS, Redis engine/slow logs,
and optional VPC flow logs. Optional alarms cover CloudFront/ALB 5xx, target
health, ECS CPU/memory, RDS CPU/storage, and Redis CPU. SNS subscriptions and
incident routing are operator-owned. The monthly budget is deliberately
account-wide rather than tag-filtered, so untaggable/shared costs and delayed
cost-allocation-tag activation cannot hide spend. It requires at least one valid
email recipient and alerts on forecasted 80%, actual 80%, and actual 100%.

The staging example's `$150` budget is an alarm, never a spending cap. An
always-on ALB, public IPv4 tasks, RDS, Redis, CloudFront/WAF/logs, KMS, and data
transfer cannot honestly be guaranteed below `$100/month`; credits reduce the
invoice, not measured usage. The budget profile disables staging flow logs and
Container Insights, uses seven-day logs, small data nodes/tasks, bounded ECR
history, and Spot only for the interruption-safe worker. Review Cost Explorer
after the first 24–72 hours and resize from measurements.

Production release evidence must include alarm delivery, CloudFront/WAF access
records, RDS restore to a scratch target, PITR retention, S3 durable-version and
transient physical-delete behavior, authenticated Redis queue behavior, ECS
rollback, and deep health. Configuration alone is not recovery evidence.

### AWS-native intake kill switch

`scripts/ops/aws-kill-switch.sh` clones the live API task definition only after
checking the exact account, region, cluster, service family, live release SHA,
digest image, roles, Fargate mode, and read-only root. It changes only
`ACCEPTING_NEW_ANALYSES`, rolls the exact API service, and probes the public demo
mutation through CloudFront. `off` must produce `503 service_paused` plus
`Retry-After: 3600`; `on` must reach normal application request validation. A
failed `on`/`test` restores the previous task definition; a failed `off` probe
fails closed on the off revision rather than silently reopening intake.

Every staging promotion executes `test`: off, prove, on, prove, restore the
original task definition/state, then deep health. Protected workflow scopes
provide staging `off`/`on`/`test` and production `off`/`on`; the disruptive test
is refused in production. Release promotion preserves the live switch state, so
deploying new code cannot silently reopen intake during an incident. This switch
stops new guarded mutations; it does not cancel already-running analyses or
drain queued work. All release and kill-switch workflow runs share one
non-cancelling concurrency queue so official off/on/deploy operations cannot
race or lose an intake-state update.

## Live release gates

Do not declare production live until all of these are true:

- Terraform's production/HA preconditions pass without overrides.
- CloudFront custom HTTPS is canonical; the private ALB cannot be reached
  directly.
- WAF, WAF logs, and CloudFront access logs are producing retained records.
- Every runtime secret has `AWSCURRENT`; cache AUTH is verified and attested.
- The exact sealed image/SBOM scan passes, the release image honors the separate
  transient-upload bucket variables, and
  `transient_upload_contract_confirmed` records that review.
- Staging and production independently validate the same fresh, exact-SHA
  supplier-holdout approval digest.
- A production-size multipart upload is consumed, its unversioned object is
  absent after cleanup, and durable evidence remains versioned per retention.
- The workflow names one exact SHA and matching staging/production digests,
  migration exits zero, services stabilize, deep health passes, and the staging
  AWS kill-switch drill restores successfully.
- Every feature represented as available to customers passes exact-image and
  browser acceptance in this plane; image-to-mesh reconstruction is explicitly
  excluded until the readiness blocker above is resolved.
- Recovery, alert delivery, budget notification, and human approval evidence is
  retained outside Terraform state.

See `docs/AWS_ACCOUNT_BOOTSTRAP.md` for the ordered bootstrap procedure.
