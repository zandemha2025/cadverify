# Phase 12: On-Premise Deployment Hardening - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area -- see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 12` if desired)

<domain>
## Phase Boundary

This phase hardens CadVerify for deployment inside enterprise networks. It adds SSO/SAML authentication (replacing or augmenting Google OAuth), role-based access control (viewer/analyst/admin), full audit logging for compliance, an air-gapped Docker Compose bundle that runs with zero external network calls, a Helm chart for Kubernetes deployment, and a configuration guide for enterprise IT teams.

Deliverables:
1. SAML 2.0 / SSO authentication module with configurable Identity Provider (Okta, Azure AD, PingFederate, etc.)
2. RBAC middleware with three roles (viewer, analyst, admin) and a permission matrix governing API access.
3. Audit logging service + Postgres `audit_log` table recording every analysis action.
4. Air-gapped Docker Compose deployment with all images and dependencies pre-bundled.
5. Helm chart for Kubernetes with configurable replicas, resource limits, and persistent volumes.
6. Enterprise configuration guide (SSO setup, RBAC configuration, audit log export, air-gapped installation).

**Explicitly out of scope for this phase:**
- Billing or paid tier gating (deferred per PROJECT.md)
- Multi-tenant organization model (ORG-01, ORG-02 deferred; RBAC here is per-deployment, not per-org)
- SOC2 formal certification (audit logging enables SOC2-adjacent compliance, not full certification)
- Custom IdP protocol development (SAML 2.0 only; OIDC could be future enhancement)
- Automated compliance reporting dashboards (admin can export audit logs; dashboards are future)
- GPU node scheduling in Helm (Phase 10 image-to-mesh uses CPU inference; GPU scheduling is future)

</domain>

<decisions>
## Implementation Decisions

### SAML/SSO Authentication

- **D-01:** Use **python3-saml** (OneLogin's open-source SAML toolkit) for SAML 2.0 SP implementation.
  - Rationale (auto): python3-saml is the most mature Python SAML SP library with 3k+ GitHub stars, active maintenance, and documented integration patterns for FastAPI. It supports IdP metadata import, signed assertions, encrypted NameID, and SLO. The alternative (pysaml2) has a steeper learning curve and less documentation for modern async frameworks. python3-saml's `OneLogin_Saml2_Auth` class provides a clean request/response flow.

- **D-02:** SAML configuration via **environment variables + a `saml/` config directory** mounted into the container.
  - Config structure:
    ```
    saml/
      settings.json      # SP entity ID, ACS URL, SLO URL, NameID format
      advanced_settings.json  # Signature/encryption algorithms, security settings
      idp_metadata.xml   # Customer-provided IdP metadata (Okta/AzureAD/etc.)
      sp.crt             # SP signing certificate
      sp.key             # SP private key
    ```
  - Env vars: `SAML_ENABLED=true`, `SAML_STRICT=true`, `SAML_SP_ENTITY_ID`, `SAML_SP_ACS_URL`, `SAML_SP_SLO_URL`.
  - Rationale (auto): File-based config is the standard for SAML SPs and allows enterprise IT to drop in their IdP metadata XML without code changes. Env vars control feature toggles and basic SP identity. The `saml/` directory is mounted as a Docker volume or ConfigMap in Kubernetes.

- **D-03:** Auth mode is **switchable**: `AUTH_MODE=saml` disables Google OAuth and magic-link signup; `AUTH_MODE=google` retains current behavior; `AUTH_MODE=hybrid` allows both (SAML + Google OAuth).
  - Rationale (auto): Enterprise on-prem deployments will use SAML exclusively (no Google OAuth behind a firewall). SaaS deployments keep Google OAuth. Hybrid mode supports enterprise customers transitioning to SAML. The `AUTH_MODE` env var gates which auth routes are registered at startup.

- **D-04:** SAML-authenticated users are **auto-provisioned** on first login: a `users` row is created with `auth_provider='saml'`, `email` from SAML NameID, and a default role of `viewer`. An API key is minted automatically (same `cv_live_` format).
  - Rationale (auto): Just-in-time provisioning avoids manual user creation by admins. SAML NameID (email) is the unique identifier. Default `viewer` role follows least-privilege principle; admins can upgrade roles via the admin API.

- **D-05:** SAML endpoints mounted at `/auth/saml/`:
  - `GET /auth/saml/login` -- Redirects to IdP with AuthnRequest
  - `POST /auth/saml/acs` -- Assertion Consumer Service (receives SAML response)
  - `GET /auth/saml/logout` -- Initiates SLO with IdP
  - `POST /auth/saml/sls` -- Single Logout Service callback
  - `GET /auth/saml/metadata` -- SP metadata XML for IdP configuration
  - Rationale (auto): Standard SAML SP endpoint layout. The `/auth/saml/metadata` endpoint enables one-click IdP configuration (admin copies the URL into Okta/Azure AD). Mounting under `/auth/saml/` parallels existing `/auth/google/` routes.

### RBAC Model

- **D-06:** Three roles with a **fixed permission matrix** enforced via FastAPI dependency injection:
  | Permission | viewer | analyst | admin |
  |-----------|--------|---------|-------|
  | View analyses | yes | yes | yes |
  | View batch results | yes | yes | yes |
  | Trigger single analysis | no | yes | yes |
  | Submit batch jobs | no | yes | yes |
  | Trigger mesh repair | no | yes | yes |
  | Upload images (reconstruct) | no | yes | yes |
  | Create/rotate API keys | no | yes | yes |
  | View audit logs | no | no | yes |
  | Manage users (role assignment) | no | no | yes |
  | System configuration | no | no | yes |
  | Export audit logs | no | no | yes |
  - Rationale (auto): Three roles map to enterprise usage: viewers (management reviewing results), analysts (engineers running analyses), admins (IT managing the deployment). The matrix is fixed in code -- not configurable by users -- to keep RBAC simple and auditable. ABAC (attribute-based) is overkill for 3 roles.

- **D-07:** Role stored as a **`role` column on the `users` table** with enum values `viewer`, `analyst`, `admin`. Default for SAML-provisioned users: `viewer`. Default for Google OAuth users: `analyst` (backward-compatible with existing behavior where every user can analyze).
  - Rationale (auto): Adding a column to `users` is simpler than a separate roles table for 3 fixed roles. The default role difference (viewer for SAML, analyst for OAuth) ensures existing SaaS users are unaffected while enterprise deployments start with least-privilege.

- **D-08:** RBAC enforcement via a **`Depends(require_role(min_role))` dependency**:
  ```python
  async def require_role(min_role: Role) -> Callable:
      async def check(user: AuthedUser = Depends(require_api_key)):
          if user.role.rank < min_role.rank:
              raise HTTPException(403, detail={"code": "insufficient_role", ...})
          return user
      return check
  ```
  Roles are ranked: `viewer=1 < analyst=2 < admin=3`. `require_role(Role.analyst)` allows analysts and admins.
  - Rationale (auto): Composable with existing `require_api_key` dependency. Minimum-role check is the simplest RBAC pattern for a hierarchical role model. No per-endpoint config files -- roles are declared in route decorators.

- **D-09:** Admin API for role management:
  - `GET /api/v1/admin/users` -- List all users with roles
  - `PATCH /api/v1/admin/users/{id}/role` -- Assign role (`{"role": "analyst"}`)
  - `GET /api/v1/admin/users/{id}` -- User detail with activity summary
  - All admin endpoints require `require_role(Role.admin)`.
  - Rationale (auto): Minimal admin surface. Role assignment is the primary admin action. User listing enables the admin to see who has access. User detail supports audit workflows.

### Audit Logging

- **D-10:** Audit log schema (`audit_log` table):
  ```
  audit_log:
    id              BIGINT PRIMARY KEY (GENERATED ALWAYS AS IDENTITY)
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now()
    user_id         BIGINT NULL FK(users.id ON DELETE SET NULL)
    user_email      TEXT NOT NULL           -- denormalized for log integrity
    action          TEXT NOT NULL            -- 'analysis.created', 'batch.submitted', etc.
    resource_type   TEXT NOT NULL            -- 'analysis', 'batch', 'user', 'api_key'
    resource_id     TEXT NULL                -- ULID of the resource
    detail_json     JSONB NULL              -- action-specific context
    ip_address      TEXT NULL
    user_agent      TEXT NULL
    file_hash       TEXT NULL                -- mesh SHA for analysis actions
    result_summary  TEXT NULL                -- 'pass', 'issues', 'fail' for analysis
  ```
  Indexed on: `(timestamp)`, `(user_id, timestamp)`, `(action, timestamp)`.
  - Rationale (auto): Denormalized `user_email` ensures audit integrity even if the user is deleted. `detail_json` allows action-specific context without schema changes per event type. Indexes support time-range queries (compliance audits) and per-user queries (incident investigation). Schema aligns with SOC2 CC6.1/CC7.2 audit trail requirements.

- **D-11:** Audited actions:
  | Action | Trigger | detail_json includes |
  |--------|---------|---------------------|
  | `analysis.created` | Single analysis completes | process_types, verdict, file_name |
  | `analysis.viewed` | GET /analyses/{id} | - |
  | `batch.submitted` | Batch job created | item_count, input_mode |
  | `batch.completed` | Batch finishes | completed, failed, duration_sec |
  | `share.created` | Analysis shared | share_short_id |
  | `share.revoked` | Share removed | share_short_id |
  | `pdf.exported` | PDF downloaded | analysis_id |
  | `user.provisioned` | SAML first login | auth_provider, role |
  | `user.role_changed` | Admin assigns role | old_role, new_role, changed_by |
  | `api_key.created` | Key minted | key_prefix |
  | `api_key.rotated` | Key rotated | old_prefix, new_prefix |
  | `api_key.revoked` | Key revoked | key_prefix |
  | `auth.login` | Successful authentication | auth_provider |
  | `auth.logout` | SLO or session end | auth_provider |
  - Rationale (auto): Covers the key compliance questions: who accessed what data, who analyzed what file, who changed permissions. `analysis.viewed` enables read-access auditing (important for sensitive engineering data). The list is comprehensive without being noisy (no GET /health, no static asset requests).

- **D-12:** Audit logging implemented as an **async service** (`audit_service.py`) called explicitly from route handlers and service functions -- not middleware.
  - Rationale (auto): Middleware-based logging captures too much noise (health checks, static assets) and lacks action context (which analysis was viewed, what role was changed). Explicit calls from business logic provide precise, contextual audit entries. The async service uses `asyncio.create_task()` for fire-and-forget writes so audit logging never blocks request processing.

- **D-13:** Audit log export via `GET /api/v1/admin/audit-log` with query params:
  - `?start=ISO&end=ISO` -- time range (required, max 90 days)
  - `?user_id=` -- filter by user
  - `?action=` -- filter by action type
  - `?format=json` (default) or `?format=csv`
  - Paginated with cursor (consistent with Phase 3 pattern).
  - Rationale (auto): Enterprise compliance teams need exportable audit data. CSV for import into SIEM/GRC tools (Splunk, ServiceNow). Time-range requirement prevents unbounded queries. 90-day max keeps response sizes manageable; longer exports can use multiple requests.

### Air-Gapped Docker Compose

- **D-14:** Air-gapped bundle structure:
  ```
  cadverify-enterprise/
    docker-compose.yml            # Overrides for enterprise (SAML, volumes)
    docker-compose.override.yml   # Air-gap specific: no image pulls
    .env.example                  # All configurable env vars documented
    images/                       # Pre-exported Docker images
      cadverify-backend.tar
      cadverify-frontend.tar
      postgres-16-alpine.tar
      redis-7-alpine.tar
    saml/                         # SAML config template
      settings.json.template
      advanced_settings.json.template
    config/
      rbac-defaults.json          # Default role assignments
    scripts/
      load-images.sh              # docker load < images/*.tar
      init-db.sh                  # Run Alembic migrations
      health-check.sh             # Verify all services running
    docs/
      ENTERPRISE-SETUP.md         # Step-by-step configuration guide
  ```
  - Rationale (auto): Tar-exported images are the standard for air-gapped Docker deployments. The bundle is a self-contained directory that enterprise IT copies to the target server. `load-images.sh` handles `docker load` for all images. No `pip install` or `npm install` at runtime -- all dependencies baked into images.

- **D-15:** Docker images are **fully self-contained**: all Python dependencies (including python3-saml, lxml, xmlsec) baked into the image at build time. No `pip install` at runtime. Frontend is pre-built static assets served by Next.js standalone output.
  - Rationale (auto): Air-gapped environments have no internet access. Every dependency must be in the image. The existing Dockerfile already bakes Python deps; this decision confirms that SAML dependencies (python3-saml requires lxml + xmlsec1 C libraries) are included in the build.

- **D-16:** Air-gapped Docker Compose uses **local image references** (no registry pull):
  ```yaml
  services:
    backend:
      image: cadverify-backend:latest  # loaded from tar
      # no 'build:' directive in air-gap mode
  ```
  - Rationale (auto): `docker load` tags images locally. Docker Compose references local image names. No Docker Hub / registry access required.

- **D-17:** Data persistence via **named Docker volumes** for Postgres data, Redis data (optional), and blob storage (`/data/blobs`). Volumes survive container restarts and updates.
  - Rationale (auto): Named volumes are the standard Docker persistence mechanism. Enterprise deployments need data to survive `docker compose down && up`. Blob storage volume holds analysis files, batch uploads, and cached PDFs.

### Helm Chart

- **D-18:** Helm chart structure:
  ```
  charts/cadverify/
    Chart.yaml
    values.yaml                   # Default configuration
    values-enterprise.yaml        # Enterprise overlay (SAML, RBAC, audit)
    templates/
      deployment-backend.yaml
      deployment-worker.yaml
      deployment-frontend.yaml
      service-backend.yaml
      service-frontend.yaml
      ingress.yaml
      configmap-saml.yaml
      secret-db.yaml
      secret-saml.yaml
      pvc-blobs.yaml
      pvc-postgres.yaml
      hpa-backend.yaml            # Optional HPA
      job-migrate.yaml            # Alembic migration job
    _helpers.tpl
  ```
  - Rationale (auto): Standard Helm chart layout. Separate deployments for backend (API), worker (arq), and frontend match the existing docker-compose service split. ConfigMap for SAML settings, Secrets for DB credentials and SAML keys. PVCs for blob storage and Postgres. HPA template enables autoscaling. Migration job runs Alembic on deploy.

- **D-19:** Configurable via `values.yaml`:
  - `replicaCount.backend`, `replicaCount.worker`, `replicaCount.frontend` -- default 2/2/2
  - `resources.backend.requests/limits` -- CPU/memory for each deployment
  - `persistence.blobs.size`, `persistence.postgres.size` -- PVC sizes
  - `saml.enabled`, `saml.idpMetadata` -- SAML configuration
  - `rbac.defaultRole` -- default role for new users
  - `audit.retentionDays` -- how long to keep audit logs (default 365)
  - `ingress.enabled`, `ingress.host`, `ingress.tls` -- ingress configuration
  - `image.repository`, `image.tag`, `image.pullPolicy` -- image references
  - Rationale (auto): These are the knobs enterprise IT teams need. Replica counts for scaling, resource limits for capacity planning, persistence sizes for data requirements, and feature toggles for SAML/RBAC/audit. Follows Helm best practices (values.yaml documents all configurable options).

- **D-20:** Helm chart supports **air-gapped Kubernetes** by setting `image.pullPolicy: Never` and pre-loading images into cluster nodes via `ctr images import` or a private registry.
  - Rationale (auto): Same air-gap principle as Docker Compose. `pullPolicy: Never` prevents Kubernetes from trying to pull images from a registry. Enterprise IT loads images into the cluster-local container runtime.

### Enterprise Configuration Guide

- **D-21:** Configuration guide format: a single **Markdown document** (`ENTERPRISE-SETUP.md`) bundled in the air-gapped package and also available in the Git repository.
  - Rationale (auto): Markdown is universally readable (renders in GitHub, GitLab, any text editor). A single document keeps all setup steps in one place rather than scattered across multiple files. Enterprise IT teams can print it or convert to PDF if needed.

- **D-22:** Guide sections:
  1. Prerequisites (Docker 24+, Docker Compose v2, or Kubernetes 1.28+)
  2. Quick Start (5-minute docker-compose up path for evaluation)
  3. SSO/SAML Configuration (step-by-step for Okta, Azure AD, PingFederate with screenshots-as-text)
  4. RBAC Configuration (role matrix, how to assign roles, default behavior)
  5. Audit Log Configuration (retention, export, SIEM integration via CSV/JSON)
  6. Air-Gapped Installation (load images, configure offline, verify)
  7. Kubernetes / Helm Deployment (values.yaml walkthrough, ingress, TLS, PVCs)
  8. Upgrading (how to update images without data loss)
  9. Troubleshooting (common issues, health check endpoints, log locations)
  - Rationale (auto): Covers the full enterprise lifecycle from evaluation to production to upgrades. The order mirrors the typical deployment journey. IdP-specific subsections (Okta, Azure AD, PingFederate) address the three most common enterprise IdPs.

### Claude's Discretion

The following are left to the researcher/planner to resolve with standard patterns:
- Exact python3-saml initialization code and request/response mapping for FastAPI
- SAML certificate generation instructions (self-signed vs CA-signed for SP cert)
- Audit log rotation/archival strategy beyond the 365-day default
- Helm chart CI testing approach (chart linting, template rendering tests)
- Exact Kubernetes minimum version requirements
- Whether to include a Grafana/Prometheus monitoring stack in the Helm chart or keep it out of scope
- Frontend admin UI for user/role management (API is defined; UI layout is discretionary)
- Audit log table partitioning strategy for long-term retention

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing auth infrastructure
- `backend/src/auth/oauth.py` -- Google OAuth flow (login start, callback, user upsert, key minting). SAML module must parallel this pattern.
- `backend/src/auth/require_api_key.py` -- `require_api_key` dependency + `AuthedUser` model. RBAC extends this with role checking.
- `backend/src/auth/models.py` -- User and API key ORM models. `role` column added here.
- `backend/src/auth/hashing.py` -- `mint_token()`, `hmac_index()`, `verify_token()`. SAML auto-provisioning reuses key minting.
- `backend/src/auth/dashboard_session.py` -- Session cookie management for dashboard. SAML sessions may extend this.

### Database and persistence
- `backend/src/db/models.py` -- All ORM models (User, ApiKey, Analysis, Job, Batch, etc.). `audit_log` table added here.
- `backend/src/db/` -- SQLAlchemy async engine + session factory. Audit service uses same session.

### Existing Docker/deploy infrastructure
- `docker-compose.yml` -- Current compose file (backend, worker, postgres, redis, frontend). Air-gapped version extends this.
- `backend/Dockerfile` -- Backend image build. Must include python3-saml + xmlsec1 dependencies.

### Requirements and roadmap
- `.planning/REQUIREMENTS.md` -- ONPREM-01 through ONPREM-06 define acceptance criteria.
- `.planning/ROADMAP.md` -- Phase 12 details, success criteria, suggested plan decomposition (12.A-12.E).

### Prior phase infrastructure
- `.planning/phases/09-batch-api-webhook-pipeline/09-CONTEXT.md` -- D-13/D-14: Batch/BatchItem tables (audit logging hooks into batch events).
- `.planning/phases/11-step-ap242-gd-t-pmi-extraction/11-CONTEXT.md` -- D-09: AnalysisResult extension pattern (reference for extending models).

### Brownfield codebase map
- `.planning/codebase/ARCHITECTURE.md` -- Pipeline data flow, service layer pattern, auth module placement.
- `.planning/codebase/CONVENTIONS.md` -- snake_case, env-var config, HTTPException patterns, ULID for public IDs.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`require_api_key` dependency** (`auth/require_api_key.py`): Returns `AuthedUser(user_id, api_key_id, key_prefix)`. RBAC extends this to include `role` and adds `require_role(min_role)` as a composable dependency.
- **`mint_token()` / `upsert_user()`** (`auth/hashing.py`, `auth/models.py`): SAML auto-provisioning reuses the same key minting and user creation logic.
- **Google OAuth router** (`auth/oauth.py`): Blueprint for SAML router structure (mount under `/auth/saml/`, same redirect/callback pattern).
- **`dashboard_session.py`**: Session cookie management. SAML-authenticated sessions can reuse this for the dashboard.
- **Cursor pagination** (Phase 3): Audit log export endpoint reuses the same cursor-based pagination pattern.
- **docker-compose.yml**: Existing 5-service compose file. Air-gapped version extends with image loading and SAML volume mounts.

### Established Patterns
- **Env-var configuration**: All configurable values via `os.getenv()`. SAML/RBAC/audit settings follow this.
- **Service layer**: Routes call services, services call infrastructure. `audit_service.py` follows `analysis_service.py` pattern.
- **FastAPI dependency injection**: `Depends(require_api_key)` pattern. `Depends(require_role(Role.analyst))` composes on top.
- **Alembic migrations**: Schema changes via Alembic. `audit_log` table added as a new migration.
- **ULID for public IDs**: Audit log entries use BIGINT for internal ID (high-volume table; ULID overhead unnecessary).

### Integration Points
- New module: `backend/src/auth/saml.py` -- SAML SP implementation using python3-saml.
- New module: `backend/src/auth/rbac.py` -- Role enum, `require_role()` dependency, permission matrix.
- New module: `backend/src/services/audit_service.py` -- Async audit log writes.
- New routes: `/auth/saml/*` (login, ACS, SLO, metadata), `/api/v1/admin/*` (users, audit-log).
- New Alembic migration: Add `role` column to `users` table, create `audit_log` table.
- New directory: `charts/cadverify/` -- Helm chart.
- New directory: `cadverify-enterprise/` -- Air-gapped bundle (or build script to generate it).
- Modified: `backend/Dockerfile` -- Add `xmlsec1` and `python3-saml` to build deps.

</code_context>

<specifics>
## Specific Ideas

- **Saudi Aramco target**: Their IT will deploy on internal Kubernetes clusters behind corporate firewalls. The Helm chart and SAML integration are specifically designed for this use case.
- **Audit log as compliance enabler**: SOC2 CC6.1 requires audit trails of system access. The audit_log table schema is designed to satisfy this without requiring full SOC2 certification.
- **Zero-trust default**: SAML-provisioned users start as `viewer` (cannot trigger analyses). This prevents accidental resource consumption when an IdP auto-provisions hundreds of users.
- **Air-gap testing**: The air-gapped Docker Compose bundle should be testable by disconnecting from the internet and running `docker compose up` -- if any service fails, the bundle is incomplete.
- **Helm chart should work with standard Kubernetes**: No custom CRDs, no operator patterns, no service mesh requirements. Standard Deployments, Services, Ingress, PVCs, ConfigMaps, Secrets.

</specifics>

<deferred>
## Deferred Ideas

- **OIDC support** -- Many enterprise IdPs support OIDC natively alongside SAML. Adding OIDC as an alternative auth protocol could simplify some integrations. Future enhancement.
- **SCIM provisioning** -- Automated user provisioning/deprovisioning via SCIM protocol (Okta, Azure AD). Currently using JIT provisioning via SAML. SCIM enables bulk user sync and offboarding.
- **Multi-tenant RBAC** -- Per-organization roles (different role per tenant). Current RBAC is per-deployment. ORG-01/ORG-02 deferred.
- **Audit log dashboards** -- Grafana/Kibana dashboards for audit log visualization. Current export supports SIEM ingestion; dashboards are a future enhancement.
- **Automated compliance reports** -- Generate SOC2/ISO27001 compliance reports from audit data. Future feature beyond basic audit logging.
- **Operator pattern for Kubernetes** -- CRD-based operator for automated upgrades, backup, and scaling. Helm chart covers initial deployment; operator is for mature operations.

</deferred>

---

## Gray Areas Resolved in Auto Mode -- Summary Table

| # | Gray area | Auto-selected default | Decision ID(s) |
|---|-----------|----------------------|----------------|
| 1 | SAML library choice | python3-saml (OneLogin) | D-01 |
| 2 | SAML configuration approach | Env vars + saml/ config directory | D-02, D-03 |
| 3 | User provisioning | Auto-provision on first SAML login, default viewer role | D-04, D-05 |
| 4 | RBAC model | 3 fixed roles (viewer/analyst/admin), hierarchical, via Depends() | D-06, D-07, D-08, D-09 |
| 5 | Audit log schema | Denormalized Postgres table with 14 audited actions | D-10, D-11 |
| 6 | Audit implementation | Async service with explicit calls, not middleware | D-12, D-13 |
| 7 | Air-gapped bundle | Tar-exported images, self-contained directory, load-images.sh | D-14, D-15, D-16, D-17 |
| 8 | Helm chart | Standard structure, configurable replicas/resources/SAML/RBAC | D-18, D-19, D-20 |
| 9 | Config guide | Single Markdown doc, 9 sections covering full enterprise lifecycle | D-21, D-22 |

---

*Phase: 12-on-premise-deployment-hardening*
*Context gathered: 2026-04-15*
*Mode: --auto (all gray areas resolved with recommended defaults; see each D-## "Rationale" line)*
