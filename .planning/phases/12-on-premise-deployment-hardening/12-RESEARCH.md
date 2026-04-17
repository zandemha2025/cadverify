# Phase 12: On-Premise Deployment Hardening - Research

## RESEARCH COMPLETE

**Researched:** 2026-04-15
**Phase:** 12 - On-Premise Deployment Hardening
**Requirements:** ONPREM-01 through ONPREM-06

## 1. SAML 2.0 Integration with FastAPI

### python3-saml (OneLogin)
- **Package:** `python3-saml` (PyPI), requires `xmlsec` C library + `lxml`
- **FastAPI integration:** python3-saml is framework-agnostic. Wrap `OneLogin_Saml2_Auth(request_data, settings)` in FastAPI route handlers. The request_data dict must be built from Starlette's Request object:
  ```python
  request_data = {
      "https": "on" if request.url.scheme == "https" else "off",
      "http_host": request.url.hostname,
      "server_port": request.url.port,
      "script_name": request.url.path,
      "get_data": dict(request.query_params),
      "post_data": dict(await request.form()),
  }
  ```
- **Settings structure:** `settings.json` + `advanced_settings.json` in a `saml/` directory. IdP metadata can be loaded from XML file or URL.
- **Endpoints needed:** `/saml/login` (AuthnRequest redirect), `/saml/acs` (POST, assertion consumer), `/saml/sls` (POST/GET, single logout), `/saml/metadata` (GET, SP metadata XML).
- **Docker dependency:** `xmlsec1` system package + `python3-saml` pip package. Alpine: `apk add xmlsec-dev libxml2-dev`. Debian: `apt-get install xmlsec1 libxmlsec1-dev`.

### IdP Configuration Patterns
- **Okta:** Create SAML 2.0 app, provide SP metadata URL, configure attribute statements (email, firstName, lastName).
- **Azure AD (Entra ID):** Enterprise Application > SAML SSO, upload SP metadata or manual config, map user.mail to NameID.
- **PingFederate:** SP Connection wizard, import SP metadata XML.
- All three support IdP-initiated and SP-initiated SSO. SLO support varies (Okta supports it, Azure AD has limitations).

## 2. RBAC Patterns for FastAPI

### Dependency-Based RBAC
- FastAPI's `Depends()` chain enables composable auth:
  1. `require_api_key()` extracts and validates the API key, returns `AuthedUser`
  2. `require_role(min_role)` wraps `require_api_key`, checks `user.role >= min_role`
- Role enum with integer ranking: `viewer=1, analyst=2, admin=3`
- Route-level declaration: `Depends(require_role(Role.analyst))` on each endpoint

### Schema Approach
- Add `role` TEXT column to `users` table with CHECK constraint for valid values
- Default `viewer` for SAML-provisioned, `analyst` for OAuth (backward-compatible)
- No separate roles/permissions tables needed for 3 fixed roles

## 3. Audit Logging for SOC2 Compliance

### SOC2 Trust Service Criteria (relevant)
- **CC6.1:** Logical access security — who accessed what
- **CC7.2:** System monitoring — changes to system configuration
- **CC8.1:** Change management — who changed what when
- Audit log must be tamper-evident (append-only, no UPDATE/DELETE on audit rows)

### Schema Design
- Postgres table with BIGINT identity PK, TIMESTAMPTZ, denormalized user_email
- JSONB `detail_json` for action-specific context (flexible schema per event type)
- Indexes on `(timestamp)`, `(user_id, timestamp)`, `(action, timestamp)`
- Consider table partitioning by month for long-term retention (>1 year)

### Implementation Pattern
- Async fire-and-forget writes via `asyncio.create_task()`
- Explicit calls from service/route layer (not middleware)
- No UPDATE or DELETE operations on audit_log table (append-only)

## 4. Air-Gapped Docker Deployment

### Image Export Strategy
- `docker save image:tag > image.tar` for each image
- Bundle all tars in a release directory with `docker load` script
- All Python deps must be in the image (no pip install at runtime)
- Frontend built as Next.js standalone output (no npm install at runtime)

### python3-saml System Dependencies
- `xmlsec1`, `libxmlsec1-openssl`, `libxml2`, `libxslt` must be in the Docker image
- For Alpine-based images: `apk add --no-cache xmlsec-dev libxml2-dev libxslt-dev`
- For Debian-based images: `apt-get install -y xmlsec1 libxmlsec1-dev pkg-config`

### Volume Strategy
- Named volumes for: pgdata, redis-data (optional), blobs
- SAML config mounted as bind mount or volume from `saml/` directory
- `.env` file for all environment configuration

## 5. Helm Chart Best Practices

### Chart Structure
- Separate Deployment for backend (API), worker (arq), frontend
- Service + Ingress for external access
- ConfigMap for SAML settings, Secrets for credentials
- PVC for blob storage, PVC for Postgres (or external Postgres)
- Job for Alembic migrations (runs on `helm install/upgrade`)
- Optional HPA for backend autoscaling

### Air-Gapped Kubernetes
- `imagePullPolicy: Never` with pre-loaded images
- Images loaded via `ctr -n k8s.io images import image.tar` (containerd) or `docker load` (Docker-based nodes)
- No external chart dependencies (embedded Postgres or external reference)

### Configuration via values.yaml
- Feature toggles: `saml.enabled`, `audit.enabled`
- Replica counts, resource requests/limits
- Ingress class, host, TLS
- Persistence sizes
- Image repository/tag/pullPolicy

## 6. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| xmlsec1 build failure in Docker | Medium | Pin xmlsec version, test in CI |
| SAML clock skew between SP and IdP | Medium | Configure NotOnOrAfter tolerance in advanced_settings.json |
| Audit log table bloat | Low | Monthly partitioning, configurable retention |
| Helm chart version incompatibility | Low | Test with Helm 3.12+ and K8s 1.28+ |
| Air-gap bundle size | Low | Compress tars, document minimum disk requirements |

## Validation Architecture

### Test Strategy
- Unit tests: RBAC permission checks, audit log entry creation, SAML request_data building
- Integration tests: SAML flow with mock IdP, audit log queries, role enforcement on endpoints
- E2E tests: docker-compose air-gap smoke test (build images, export, load, start, verify health)
- Helm tests: `helm template` rendering, `helm lint`, `helm test` with health check pod
