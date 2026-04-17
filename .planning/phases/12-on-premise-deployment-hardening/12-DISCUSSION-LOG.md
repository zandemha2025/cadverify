# Phase 12: On-Premise Deployment Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 12-on-premise-deployment-hardening
**Areas discussed:** SAML library, SAML configuration, User provisioning, RBAC model, Audit log schema, Audit implementation, Air-gapped bundling, Helm chart structure, Config guide format
**Mode:** `--auto` (all areas auto-resolved with recommended defaults)

---

## SAML Library Choice

| Option | Description | Selected |
|--------|-------------|----------|
| python3-saml (OneLogin) | Mature, 3k+ stars, clean API, good FastAPI docs | yes |
| pysaml2 | More feature-complete but steeper learning curve, less modern framework support | |

**User's choice:** [auto] python3-saml (recommended default)
**Notes:** python3-saml provides the cleanest integration path for FastAPI with well-documented request/response flow.

---

## RBAC Model

| Option | Description | Selected |
|--------|-------------|----------|
| 3 fixed roles (viewer/analyst/admin) | Simple hierarchical model, permission matrix in code | yes |
| ABAC (attribute-based) | Flexible but complex, overkill for 3 roles | |
| Configurable role-permission mapping | More flexible but adds config surface and audit complexity | |

**User's choice:** [auto] 3 fixed roles (recommended default)
**Notes:** Three roles map directly to enterprise usage patterns. Fixed matrix keeps RBAC auditable.

---

## Audit Log Schema

| Option | Description | Selected |
|--------|-------------|----------|
| Denormalized Postgres table | user_email denormalized, JSONB detail, indexed by time/user/action | yes |
| Append-only event stream (Kafka/Redis Streams) | Higher throughput but operational complexity | |
| File-based audit log (structured JSON lines) | Simple but not queryable, harder to export | |

**User's choice:** [auto] Denormalized Postgres table (recommended default)
**Notes:** Postgres is already in the stack. Denormalized schema ensures audit integrity even after user deletion.

---

## Air-Gapped Bundling

| Option | Description | Selected |
|--------|-------------|----------|
| Tar-exported Docker images in self-contained directory | Standard air-gap approach, load-images.sh script | yes |
| Private registry mirror (Harbor/Nexus) | More operational overhead, requires separate infrastructure | |
| Snap/Flatpak packaging | Unconventional for server software, limited enterprise adoption | |

**User's choice:** [auto] Tar-exported Docker images (recommended default)
**Notes:** Simplest approach. Enterprise IT copies directory to target server and runs load-images.sh.

---

## Helm Chart Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Standard Helm chart (Deployments, Services, Ingress) | No CRDs, no operators, works with any Kubernetes | yes |
| Kustomize overlays | Less packaging overhead but harder to parameterize | |
| Operator with CRD | Most powerful but highest development and operational cost | |

**User's choice:** [auto] Standard Helm chart (recommended default)
**Notes:** Standard Helm is the most widely adopted pattern in enterprise Kubernetes.

---

## Configuration Guide Format

| Option | Description | Selected |
|--------|-------------|----------|
| Single Markdown document | Universal, readable anywhere, printable | yes |
| Multi-page documentation site (Docusaurus/MkDocs) | Better navigation but requires hosting infrastructure | |
| PDF document | Professional but harder to maintain, not searchable in repo | |

**User's choice:** [auto] Single Markdown document (recommended default)
**Notes:** Markdown renders in GitHub/GitLab, works offline, and enterprise IT can convert to PDF if needed.

---

## Claude's Discretion

- python3-saml initialization code details
- SAML certificate generation instructions
- Audit log rotation/archival beyond 365-day default
- Helm chart CI testing approach
- Frontend admin UI layout
- Audit log table partitioning

## Deferred Ideas

- OIDC support (alternative to SAML)
- SCIM provisioning (automated user sync)
- Multi-tenant RBAC (per-organization roles)
- Audit log dashboards (Grafana/Kibana)
- Automated compliance reports
- Kubernetes operator pattern
