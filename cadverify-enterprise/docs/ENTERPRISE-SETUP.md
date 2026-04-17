# CadVerify Enterprise Setup Guide

This guide covers installation, SSO/SAML configuration, RBAC, audit logging,
air-gapped deployment, Kubernetes/Helm deployment, upgrading, and troubleshooting.
It is intended for enterprise IT teams deploying CadVerify on-premise.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Start (Docker Compose)](#2-quick-start-docker-compose)
3. [SSO/SAML Configuration](#3-ssosaml-configuration)
4. [RBAC Configuration](#4-rbac-configuration)
5. [Audit Log Configuration](#5-audit-log-configuration)
6. [Air-Gapped Installation](#6-air-gapped-installation)
7. [Kubernetes / Helm Deployment](#7-kubernetes--helm-deployment)
8. [Upgrading](#8-upgrading)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU cores | 4 | 8 |
| RAM | 8 GB | 16 GB |
| Disk | 100 GB SSD | 250 GB SSD |

### Software Requirements

**Docker deployment:**
- Docker Engine 24+ with Docker Compose v2

**Kubernetes deployment:**
- Kubernetes 1.28+
- Helm 3.12+

### Network Requirements

- Internal DNS resolving the CadVerify domain (e.g., `cadverify.company.com`)
- TLS certificate for the CadVerify domain (PEM format)
- Outbound access to your SAML Identity Provider (unless IdP is internal)
- Ports: 443 (HTTPS), 5432 (Postgres, internal only), 6379 (Redis, internal only)

### Identity Provider

A SAML 2.0-compatible Identity Provider is required for SSO. Tested providers:
- Okta
- Azure AD (Entra ID)
- PingFederate

Any SAML 2.0-compliant IdP should work.

---

## 2. Quick Start (Docker Compose)

Estimated time: **5-10 minutes**.

### Step 1: Extract the Bundle

Copy the `cadverify-enterprise/` bundle to your server:

```bash
tar xzf cadverify-enterprise-v2.0.tar.gz
cd cadverify-enterprise/
```

### Step 2: Load Docker Images

```bash
bash scripts/load-images.sh
```

This loads `cadverify-backend`, `cadverify-frontend`, `postgres:16-alpine`, and
`redis:7-alpine` from the bundled tar files.

### Step 3: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your production values. At minimum, change:

| Variable | Description | Example |
|----------|-------------|---------|
| `POSTGRES_PASSWORD` | Database password | `a-strong-random-password` |
| `DATABASE_URL` | Postgres connection string | `postgresql+asyncpg://cadverify:<password>@postgres:5432/cadverify` |
| `AUTH_MODE` | Authentication mode | `saml` |
| `SAML_SP_ENTITY_ID` | Your CadVerify URL | `https://cadverify.company.com` |
| `SAML_SP_ACS_URL` | SAML assertion endpoint | `https://cadverify.company.com/auth/saml/acs` |
| `SAML_SP_SLO_URL` | SAML logout endpoint | `https://cadverify.company.com/auth/saml/sls` |
| `DASHBOARD_ORIGIN` | Frontend URL | `https://cadverify.company.com` |
| `API_KEY_PEPPER` | 32-byte hex string | Generate with `openssl rand -hex 32` |

### Step 4: Start Services

```bash
docker compose up -d
```

### Step 5: Run Database Migrations

```bash
bash scripts/init-db.sh
```

### Step 6: Verify

```bash
bash scripts/health-check.sh
```

Or manually:

```bash
curl -s http://localhost:8000/health
# Expected: {"db": "ok", "redis": "ok"}
```

You should now be able to access CadVerify at `http://localhost:3000` (or your
configured domain with a reverse proxy).

---

## 3. SSO/SAML Configuration

CadVerify uses SAML 2.0 for enterprise SSO. The backend acts as a SAML Service
Provider (SP) and delegates authentication to your Identity Provider (IdP).

### 3a. Generate SP Certificate

Generate a self-signed certificate for SAML signature validation:

```bash
mkdir -p saml/
openssl req -new -x509 -days 3650 -nodes \
  -out saml/sp.crt \
  -keyout saml/sp.key \
  -subj "/CN=cadverify-sp"
chmod 600 saml/sp.key
```

### 3b. Configure saml/settings.json

Copy the template and edit:

```bash
cp saml/settings.json.template saml/settings.json
```

Key fields in `saml/settings.json`:

```json
{
  "sp": {
    "entityId": "https://cadverify.company.com",
    "assertionConsumerService": {
      "url": "https://cadverify.company.com/auth/saml/acs",
      "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
    },
    "singleLogoutService": {
      "url": "https://cadverify.company.com/auth/saml/sls",
      "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
    },
    "x509cert": "<contents of saml/sp.crt, single line, no headers>",
    "privateKey": "<contents of saml/sp.key, single line, no headers>"
  },
  "idp": {
    "entityId": "<from your IdP>",
    "singleSignOnService": {
      "url": "<from your IdP>",
      "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
    },
    "x509cert": "<from your IdP metadata>"
  }
}
```

Replace all `<...>` placeholders with values from your IdP.

### 3c. Okta Setup

1. In the Okta Admin Console, go to **Applications > Create App Integration**.
2. Select **SAML 2.0**, click **Next**.
3. Set **App name** to `CadVerify`.
4. Configure **SAML Settings**:
   - **Single sign-on URL:** `https://cadverify.company.com/auth/saml/acs`
   - **Audience URI (SP Entity ID):** `https://cadverify.company.com`
   - **Name ID format:** EmailAddress
   - **Application username:** Email
5. Add **Attribute Statements**:
   - `email` = `user.email`
6. Click **Next**, then **Finish**.
7. Under the **Sign On** tab, click **View SAML setup instructions**.
8. Download the **IdP metadata XML** and save as `saml/idp_metadata.xml`.
9. Copy the IdP Entity ID, SSO URL, and X.509 certificate into `saml/settings.json`
   under the `idp` section.

### 3d. Azure AD (Entra ID) Setup

1. In the Azure Portal, go to **Azure Active Directory > Enterprise Applications**.
2. Click **New application > Create your own application**.
3. Name it `CadVerify`, select **Integrate any other application**, click **Create**.
4. Go to **Single sign-on > SAML**.
5. Under **Basic SAML Configuration**:
   - **Identifier (Entity ID):** `https://cadverify.company.com`
   - **Reply URL (ACS URL):** `https://cadverify.company.com/auth/saml/acs`
   - **Logout URL:** `https://cadverify.company.com/auth/saml/sls`
6. Under **Attributes & Claims**, ensure `emailaddress` claim is mapped.
7. Under **SAML Signing Certificate**, download **Federation Metadata XML**.
8. Save as `saml/idp_metadata.xml`.
9. Copy the IdP Entity ID, Login URL, and certificate into `saml/settings.json`
   under the `idp` section.

### 3e. PingFederate Setup

1. In the PingFederate Admin Console, go to **SP Connections > Create New**.
2. Select **Browser SSO Profiles** with **SAML 2.0**.
3. Under **Import Metadata**, upload SP metadata from:
   `https://cadverify.company.com/auth/saml/metadata`
   (The `/auth/saml/metadata` endpoint provides SP metadata XML automatically.)
4. Configure the **Attribute Contract**:
   - Add `email` attribute, map to the user's email from your directory.
5. Set **Allowed Connections** to active.
6. Save the SP connection.
7. Export the IdP metadata from PingFederate and save as `saml/idp_metadata.xml`.
8. Copy the IdP Entity ID, SSO URL, and certificate into `saml/settings.json`.

### 3f. Enable SAML Authentication

In your `.env` file, set:

```
AUTH_MODE=saml
SAML_ENABLED=true
```

Restart services:

```bash
docker compose restart backend worker
```

### 3g. Verify SAML Login

1. Open your browser and navigate to:
   `https://cadverify.company.com/auth/saml/login`
2. You should be redirected to your IdP login page.
3. After successful authentication, you should be redirected back to
   `https://cadverify.company.com/dashboard`.
4. Check backend logs for confirmation:
   ```bash
   docker compose logs backend | grep "SAML user provisioned"
   ```

---

## 4. RBAC Configuration

CadVerify uses three roles with hierarchical permissions:

### Role Matrix

| Permission | viewer | analyst | admin |
|-----------|--------|---------|-------|
| View analyses | Yes | Yes | Yes |
| View processes and materials | Yes | Yes | Yes |
| Trigger new analyses | No | Yes | Yes |
| Manage own API keys | No | Yes | Yes |
| View all users | No | No | Yes |
| Assign user roles | No | No | Yes |
| View audit logs | No | No | Yes |
| Export audit data | No | No | Yes |

### Default Role for SAML Users

New SAML-authenticated users are assigned the `viewer` role by default. To change
the default, set the `RBAC_DEFAULT_ROLE` environment variable:

```
RBAC_DEFAULT_ROLE=analyst
```

Restart the backend after changing.

### Assigning Roles via Admin API

Admins can change a user's role with:

```bash
curl -X PATCH \
  https://cadverify.company.com/api/v1/admin/users/{user_id}/role \
  -H "Authorization: Bearer <admin-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"role": "analyst"}'
```

Valid roles: `viewer`, `analyst`, `admin`.

### First Admin Setup

After initial deployment, no admin user exists yet. Promote your IT admin directly
in the database:

```bash
docker compose exec postgres psql -U cadverify -d cadverify -c \
  "UPDATE users SET role='admin' WHERE email='it-admin@company.com';"
```

Replace `it-admin@company.com` with the email of the user who already logged in
via SAML. After this, they can manage other users' roles through the Admin API.

---

## 5. Audit Log Configuration

CadVerify maintains an append-only audit trail for compliance. Every significant
action (login, analysis, role change, export) is recorded with timestamp, user,
action type, and details.

### Default Settings

Audit logging is **enabled by default** -- no configuration is needed.

| Setting | Default | Environment Variable |
|---------|---------|---------------------|
| Enabled | `true` | `AUDIT_ENABLED` |
| Retention | 365 days | `AUDIT_RETENTION_DAYS` |

### Querying Audit Logs

Admins can query audit logs via the API:

```bash
curl -s \
  "https://cadverify.company.com/api/v1/admin/audit-log?start=2024-01-01&end=2024-12-31&limit=100" \
  -H "Authorization: Bearer <admin-api-key>"
```

Parameters:
- `start` (required): ISO 8601 date, start of range
- `end` (required): ISO 8601 date, end of range
- `user_id` (optional): filter by user
- `action` (optional): filter by action type (e.g., `auth.login`, `analysis.created`)
- `cursor` (optional): for pagination
- `limit` (optional): 1-200, default 50

### Exporting Audit Logs as CSV

```bash
curl -s \
  "https://cadverify.company.com/api/v1/admin/audit-log?start=2024-01-01&end=2024-12-31&format=csv" \
  -H "Authorization: Bearer <admin-api-key>" \
  -o audit-export.csv
```

CSV columns: `timestamp`, `user_email`, `action`, `resource_type`, `resource_id`,
`ip_address`, `file_hash`, `result_summary`.

### SIEM Integration

To forward audit data to your SIEM (Splunk, Elastic, ServiceNow):

**Option A: Scheduled CSV export (cron)**

```bash
# /etc/cron.d/cadverify-audit-export
0 2 * * * root curl -s \
  "https://cadverify.company.com/api/v1/admin/audit-log?start=$(date -d 'yesterday' +\%Y-\%m-\%d)&end=$(date +\%Y-\%m-\%d)&format=csv" \
  -H "Authorization: Bearer <admin-api-key>" \
  >> /var/log/cadverify/audit.csv
```

**Option B: Direct database query**

Connect to Postgres for custom reports:

```bash
docker compose exec postgres psql -U cadverify -d cadverify -c \
  "SELECT timestamp, user_email, action, resource_type, resource_id
   FROM audit_log
   WHERE timestamp >= '2024-01-01'
   ORDER BY timestamp DESC
   LIMIT 100;"
```

### Audit Actions Reference

| Action | Description |
|--------|-------------|
| `auth.login` | User logged in via SAML |
| `user.provisioned` | New SAML user created |
| `analysis.created` | CAD analysis triggered |
| `analysis.completed` | Analysis finished |
| `role.changed` | User role updated |
| `apikey.created` | API key generated |
| `audit.exported` | Audit log exported |

---

## 6. Air-Gapped Installation

For environments with no internet access (defense, critical infrastructure, etc.).

### On the Build Machine (Internet Access)

1. Export all Docker images to tar files:

```bash
cd cadverify-enterprise/
bash scripts/export-images.sh
```

This creates tar files in `images/`:
- `images/cadverify-backend.tar`
- `images/cadverify-frontend.tar`
- `images/postgres-16-alpine.tar`
- `images/redis-7-alpine.tar`

2. Verify the bundle is complete:

```bash
ls -la images/*.tar
ls -la docker-compose.yml .env.example scripts/
```

### Transfer to Air-Gapped Server

Copy the entire `cadverify-enterprise/` directory to the air-gapped server:

- **USB drive:** Copy to removable media, then copy onto the target server.
- **SCP (if network path exists):**
  ```bash
  scp -r cadverify-enterprise/ user@airgapped-server:/opt/cadverify/
  ```

### On the Air-Gapped Server

1. **Load Docker images:**

```bash
cd /opt/cadverify/cadverify-enterprise/
bash scripts/load-images.sh
```

2. **Configure environment:**

```bash
cp .env.example .env
# Edit .env with your production values (see Section 2, Step 3)
```

3. **Start services:**

```bash
docker compose up -d
```

4. **Run database migrations:**

```bash
bash scripts/init-db.sh
```

5. **Verify deployment:**

```bash
bash scripts/health-check.sh
# Expected: All services healthy
```

Or:

```bash
curl -s http://localhost:8000/health
# Expected: {"db": "ok", "redis": "ok"}
```

6. **Configure SAML** (see [Section 3](#3-ssosaml-configuration)) if your IdP is
   reachable from the air-gapped network.

### Air-Gapped Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `image not found` on `docker compose up` | Images not loaded | Run `scripts/load-images.sh` |
| `connection refused` on health check | Wrong hostnames in `.env` | Verify `DATABASE_URL` and `REDIS_URL` use container names (`postgres`, `redis`) |
| Migration fails | Postgres not ready | Wait 10 seconds, retry `scripts/init-db.sh` |

---

## 7. Kubernetes / Helm Deployment

For production Kubernetes deployments using the CadVerify Helm chart.

### Install the Chart

```bash
helm install cadverify charts/cadverify -f values-enterprise.yaml
```

### values-enterprise.yaml Walkthrough

Create `values-enterprise.yaml` by customizing these sections:

```yaml
# --- Replica Counts ---
replicaCount:
  backend: 2     # Scale based on analysis load
  worker: 2      # Scale based on batch processing needs
  frontend: 2    # Scale for user concurrency

# --- Container Images ---
image:
  backend:
    repository: cadverify-backend
    tag: "v2.0"
    pullPolicy: IfNotPresent    # Set to 'Never' for air-gapped
  frontend:
    repository: cadverify-frontend
    tag: "v2.0"
    pullPolicy: IfNotPresent    # Set to 'Never' for air-gapped

# --- Resource Limits ---
resources:
  backend:
    requests:
      cpu: "250m"
      memory: "512Mi"
    limits:
      cpu: "1000m"
      memory: "2Gi"
  worker:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "2000m"
      memory: "4Gi"
  frontend:
    requests:
      cpu: "100m"
      memory: "128Mi"
    limits:
      cpu: "500m"
      memory: "512Mi"

# --- Persistence ---
persistence:
  blobs:
    enabled: true
    size: 50Gi          # Increase for large CAD file volumes
    storageClass: ""    # Use cluster default or specify
  postgres:
    enabled: true
    size: 20Gi
    storageClass: ""

# --- SAML Configuration ---
saml:
  enabled: true
  spEntityId: "https://cadverify.company.com"
  spAcsUrl: "https://cadverify.company.com/auth/saml/acs"
  spSloUrl: "https://cadverify.company.com/auth/saml/sls"

auth:
  mode: "saml"

# --- Audit ---
audit:
  enabled: true
  retentionDays: 365

# --- RBAC ---
rbac:
  defaultRole: "analyst"

# --- Ingress ---
ingress:
  enabled: true
  className: "nginx"
  host: "cadverify.company.com"
  tls:
    - secretName: cadverify-tls
      hosts:
        - cadverify.company.com

# --- Database ---
postgresql:
  host: "postgres"       # Or external DB hostname
  port: 5432
  database: "cadverify"
  username: "cadverify"
  password: "<strong-password>"

# --- Redis ---
redis:
  host: "redis"
  port: 6379
```

### Air-Gapped Kubernetes

When your Kubernetes cluster has no internet access:

1. **Load images into containerd on each node:**

```bash
ctr -n k8s.io images import cadverify-backend.tar
ctr -n k8s.io images import cadverify-frontend.tar
ctr -n k8s.io images import postgres-16-alpine.tar
ctr -n k8s.io images import redis-7-alpine.tar
```

2. **Set pull policy to Never** in `values-enterprise.yaml`:

```yaml
image:
  backend:
    pullPolicy: Never
  frontend:
    pullPolicy: Never
```

3. **Install the chart:**

```bash
helm install cadverify charts/cadverify -f values-enterprise.yaml
```

### TLS Configuration

**Option A: cert-manager (automated)**

If you have cert-manager installed:

```yaml
ingress:
  enabled: true
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
  tls:
    - secretName: cadverify-tls
      hosts:
        - cadverify.company.com
```

**Option B: Pre-provisioned TLS secret**

```bash
kubectl create secret tls cadverify-tls \
  --cert=tls.crt \
  --key=tls.key \
  -n cadverify
```

Then reference in values:

```yaml
ingress:
  tls:
    - secretName: cadverify-tls
      hosts:
        - cadverify.company.com
```

### Database Migrations

Alembic migrations run automatically as a Helm pre-install/pre-upgrade hook.
No manual migration step is needed for Kubernetes deployments. To check migration
status:

```bash
kubectl logs job/cadverify-migrate -n cadverify
```

---

## 8. Upgrading

### Docker Compose Upgrade

1. **Stop current services:**

```bash
docker compose down
```

2. **Load new images** (from updated tar files or registry):

```bash
bash scripts/load-images.sh
```

3. **Run migrations:**

```bash
bash scripts/init-db.sh
```

4. **Start services:**

```bash
docker compose up -d
```

5. **Verify:**

```bash
bash scripts/health-check.sh
```

Data is preserved in named Docker volumes (`pgdata`, `redis-data`, `blobs`) across
upgrades.

### Kubernetes Upgrade

```bash
helm upgrade cadverify charts/cadverify -f values-enterprise.yaml
```

The Alembic migration job runs automatically as a Helm pre-upgrade hook.

### Rollback

**Docker:** Restore the previous image tar files and re-run `load-images.sh`,
then `docker compose up -d`.

**Kubernetes:**

```bash
helm rollback cadverify
```

This reverts to the previous release, including the previous image versions.

### Data Safety

- Database data persists in named volumes (Docker) or PVCs (Kubernetes).
- Upgrades only run forward migrations -- they never drop data.
- Always back up the Postgres database before major version upgrades:

```bash
# Docker
docker compose exec postgres pg_dump -U cadverify cadverify > backup.sql

# Kubernetes
kubectl exec -it deploy/postgres -- pg_dump -U cadverify cadverify > backup.sql
```

---

## 9. Troubleshooting

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| SAML login fails with "Invalid response" | Clock skew > 5 minutes between SP and IdP | Sync NTP on both the CadVerify server and IdP server |
| SAML login fails with "Signature validation failed" | Wrong IdP metadata or expired certificate | Re-download `idp_metadata.xml` from your IdP and update `saml/settings.json` |
| 403 on analysis endpoint | User has `viewer` role | Admin: PATCH the user's role to `analyst` (see Section 4) |
| Backend fails to start | Missing or invalid environment variables | Compare your `.env` against `.env.example` -- ensure all required variables are set |
| "Image not found" on `docker compose up` | Docker images not loaded | Run `scripts/load-images.sh` |
| Alembic migration fails | Database not ready | Wait for Postgres healthcheck to pass, then retry `scripts/init-db.sh` |

### Viewing Logs

**Docker Compose:**

```bash
# All services
docker compose logs -f

# Backend only
docker compose logs -f backend

# Worker only
docker compose logs -f worker

# Last 100 lines
docker compose logs --tail 100 backend
```

**Kubernetes:**

```bash
kubectl logs deploy/cadverify-backend -n cadverify -f
kubectl logs deploy/cadverify-worker -n cadverify -f
```

### Health Endpoint

The backend exposes a health endpoint that checks database and Redis connectivity:

```bash
curl -s http://localhost:8000/health
```

Expected response when healthy:

```json
{"db": "ok", "redis": "ok"}
```

If either dependency is down, the corresponding field will show an error message.

### SAML Debugging

Enable verbose SAML logging by setting:

```
LOG_LEVEL=DEBUG
```

in your `.env` file and restarting the backend. Check logs for SAML request/response
details:

```bash
docker compose logs backend | grep -i saml
```

### Support

If you cannot resolve an issue using this guide, collect the following before
contacting support:

1. Output of `docker compose logs backend --tail 500`
2. Output of `docker compose logs worker --tail 500`
3. Output of `curl -s http://localhost:8000/health`
4. Your `.env` file (redact passwords and secrets)
5. SAML settings (redact private keys)
