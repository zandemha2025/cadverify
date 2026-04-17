# Phase 9: Batch API + Webhook Pipeline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 09-batch-api-webhook-pipeline
**Areas discussed:** Batch input format, Batch size limits, Concurrency control, Webhook payload + retry, Batch status model, Batch upload storage, Result aggregation, Tenant isolation
**Mode:** `--auto` (all areas auto-resolved with recommended defaults)

---

## Batch Input Format

| Option | Description | Selected |
|--------|-------------|----------|
| ZIP + CSV manifest only | Simple, no external dependencies | |
| S3 reference only | Scale-friendly, no upload size limits | |
| ZIP + S3 + optional CSV manifest | Both modes on same endpoint, CSV optional | ✓ |

**User's choice:** [auto] ZIP + S3 + optional CSV manifest (recommended default)
**Notes:** BATCH-01 requires both ZIP and S3. Saudi Aramco's 14M parts necessitate S3 mode. ZIP for smaller customers.

---

## Batch Size Limits

| Option | Description | Selected |
|--------|-------------|----------|
| No limits (let infra handle it) | Maximum flexibility, risk of abuse | |
| Conservative (1k items, 1 GB ZIP) | Safe but limiting for enterprise | |
| Balanced (10k items, 5 GB ZIP, 100 MB/file) | Env-var configurable, zip bomb protection | ✓ |

**User's choice:** [auto] 10k items, 5 GB ZIP, 100 MB/file with env-var overrides (recommended default)
**Notes:** 10k per batch means ~1,400 batches for Saudi Aramco's 14M parts. Configurable via env vars for flexibility.

---

## Concurrency Control

| Option | Description | Selected |
|--------|-------------|----------|
| Enqueue all at once (arq handles it) | Simple but risks Redis exhaustion at scale | |
| Coordinator job with drip-feed | Controlled concurrency, respects per-tenant limits | ✓ |
| Separate worker pools per tenant | True isolation, high operational complexity | |

**User's choice:** [auto] Coordinator job with 10-concurrent drip-feed per tenant (recommended default)
**Notes:** Coordinator pattern prevents Redis memory exhaustion and enables per-tenant fairness.

---

## Webhook Payload + Retry

| Option | Description | Selected |
|--------|-------------|----------|
| Simple POST, no signing, no retries | Minimal implementation | |
| HMAC-signed, 3 retries, linear backoff | Moderate reliability | |
| HMAC-signed, 5 retries, exponential backoff + jitter | Production-grade, Stripe-style | ✓ |

**User's choice:** [auto] HMAC-signed with 5 retries and exponential backoff (recommended default)
**Notes:** Decoupled from item processing -- webhook failures never block batch progress.

---

## Batch Status Model

| Option | Description | Selected |
|--------|-------------|----------|
| Extend existing `jobs` table for batches | Less schema work, overloaded table | |
| Dedicated `batches` + `batch_items` tables | Clean separation, denormalized counters | ✓ |
| Event-sourced status (append-only log) | Most flexible, highest complexity | |

**User's choice:** [auto] Dedicated `batches` + `batch_items` + `webhook_deliveries` tables (recommended default)
**Notes:** Denormalized counters on `batches` enable O(1) progress queries.

---

## Batch Upload Storage

| Option | Description | Selected |
|--------|-------------|----------|
| Fly volume only | Reuses existing infra, limited capacity | ✓ |
| Tigris/R2 object storage | Unlimited capacity, new dependency | |
| S3 (customer's bucket) | No storage cost, only for S3 mode | |

**User's choice:** [auto] Fly volume at `/data/blobs/batch/` with 7-day retention (recommended default)
**Notes:** S3 mode fetches directly from customer's bucket. Volume space concern flagged in "Decisions to Revisit."

---

## Result Aggregation

| Option | Description | Selected |
|--------|-------------|----------|
| Progress API only (counts) | Minimal, no export | |
| Progress + paginated items + CSV export | Full enterprise workflow support | ✓ |
| Progress + items + CSV + PDF summary | Maximum value, highest effort | |

**User's choice:** [auto] Progress API + paginated items + CSV export (recommended default)
**Notes:** CSV export designed for PLM/ERP import. PDF summary deferred.

---

## Tenant Isolation

| Option | Description | Selected |
|--------|-------------|----------|
| No isolation (shared everything) | Simplest, risk of noisy neighbor | |
| Soft concurrency limits per tenant | Fair sharing, shared infrastructure | ✓ |
| Dedicated queues/workers per tenant | True isolation, high ops overhead | |

**User's choice:** [auto] Soft concurrency limits with priority support (recommended default)
**Notes:** Priority items use arq defer mechanism. Dedicated pools deferred for post-beta.

---

## Claude's Discretion

- S3 credential management approach (per-batch vs per-tenant)
- Batch coordinator arq job_timeout
- Batch cancellation API shape (PATCH vs DELETE)
- Webhook HMAC signature format specifics
- Frontend batch dashboard layout
- Webhook secret encryption at rest
- Batch file cleanup scheduling mechanism
- Partial ZIP extraction error handling
- usage_events tracking granularity for batch items

## Deferred Ideas

- Real-time progress via WebSocket/SSE
- Batch scheduling (cron batches)
- Dedicated worker pools per tenant
- Batch result PDF summary report
- SDK batch submission
- S3 result export
- Batch comparison (before/after)
