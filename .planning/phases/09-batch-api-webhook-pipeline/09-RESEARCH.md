# Phase 9: Batch API + Webhook Pipeline - Research

**Researched:** 2026-04-15
**Status:** Complete

## Research Questions

### RQ-1: arq Coordinator Pattern for Batch Orchestration

**Question:** How should the batch coordinator job manage 10k+ items without exhausting Redis memory or starving other job types?

**Findings:**

The existing codebase uses arq 0.27 with `ArqJobQueue` (see `backend/src/jobs/arq_backend.py`). The current worker registers one task function (`run_sam3d_job`) in `WorkerSettings.functions` with `max_jobs=2` and `job_timeout=600`.

**Coordinator pattern (D-07):**

1. A single arq task `run_batch_coordinator` is enqueued per batch. This task:
   - Reads the `batches` row, extracts/fetches files, creates all `batch_items` rows with `status=pending`.
   - Maintains a sliding window of `concurrency_limit` active items.
   - Enqueues up to N items as `run_batch_item` arq tasks.
   - Polls/waits for completions (via DB status checks), enqueues next pending items.
   - On all items complete, fires batch-completion webhook, marks batch `completed`.

2. **arq limitations for coordinator pattern:** arq does not natively support job callbacks or completion notifications between jobs. The coordinator must poll the database for item completion status. Recommended approach:
   - Coordinator uses a polling loop with `asyncio.sleep(2)` between checks.
   - Each `run_batch_item` task updates its `batch_items` row to `completed`/`failed` and increments the denormalized counter on `batches` via an atomic SQL `UPDATE batches SET completed_items = completed_items + 1`.
   - Coordinator checks `SELECT completed_items + failed_items FROM batches WHERE id = ?` and enqueues more when slots free up.

3. **Job timeout for coordinator:** Must be very generous. A 10k-item batch at 10 concurrency * 10s/item = ~10,000s (~2.8 hours). Set coordinator `job_timeout` to 14400 (4 hours) with a safety margin. Individual `run_batch_item` tasks keep the existing 600s timeout.

4. **Worker configuration:** The coordinator is lightweight (DB queries only, no compute). It should run alongside item tasks. Increase `max_jobs` to 12 (10 item slots + 1 coordinator + 1 SAM-3D buffer) or use a separate worker process group for coordinators.

**Recommendation:** Single worker pool with `max_jobs=12`. Coordinator polls DB every 2 seconds. Item tasks update counters atomically. This avoids Redis memory bloat from 10k queued jobs.

### RQ-2: HMAC Webhook Signing

**Question:** How should webhook payloads be signed for verification by consumers?

**Findings:**

Industry standard patterns:

| Provider | Header | Format |
|----------|--------|--------|
| Stripe | `Stripe-Signature` | `t=timestamp,v1=HMAC-SHA256(timestamp.payload)` |
| GitHub | `X-Hub-Signature-256` | `sha256=HMAC-SHA256(payload)` |
| Svix | `svix-signature` | `v1,base64(HMAC-SHA256(msg_id.timestamp.payload))` |

**Recommended approach (Stripe-like, per D-09):**

```python
import hashlib
import hmac
import time

def sign_webhook(payload_bytes: bytes, secret: str) -> str:
    timestamp = str(int(time.time()))
    signed_content = f"{timestamp}.{payload_bytes.decode()}"
    signature = hmac.new(
        secret.encode(), signed_content.encode(), hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"
```

Header: `X-CadVerify-Signature: t=1713196800,v1=abc123...`

Consumer verification:
1. Parse `t` and `v1` from header.
2. Reconstruct `signed_content = f"{t}.{raw_body}"`.
3. Compute HMAC-SHA256 with their stored secret.
4. Compare with `v1` using `hmac.compare_digest()`.
5. Reject if `abs(now - t) > 300` (5-minute tolerance for replay protection).

**Secret storage:** For beta, store `webhook_secret` as plaintext in the `batches` table. The secret is per-batch (D-09), provided by the customer at batch creation. Application-level encryption can be added later using Fernet with a key from `WEBHOOK_SECRET_ENCRYPTION_KEY` env var.

### RQ-3: Batch Table Design and Migration

**Question:** How should the 3 new tables be structured for optimal query patterns?

**Findings:**

The existing migration pattern uses Alembic with sequential numbering (`0001_`, `0002_`, `0003_`). New migration will be `0004_create_batches_batch_items_webhook_deliveries.py`.

**Key design decisions from CONTEXT.md (D-13, D-14, D-15):**

1. **`batches` table:** Denormalized counters (`total_items`, `completed_items`, `failed_items`) for O(1) progress queries. Status enum: `pending -> extracting -> processing -> completed | failed | cancelled`.

2. **`batch_items` table:** Per-item lifecycle with FK to `analyses`. Composite index on `(batch_id, status)` for progress filtering. Index on `(batch_id, created_at)` for ordered listing. Status: `pending -> queued -> processing -> completed | failed | skipped`.

3. **`webhook_deliveries` table:** Audit trail for webhook dispatch. `next_retry_at` column enables efficient retry query: `SELECT * FROM webhook_deliveries WHERE status = 'pending' AND next_retry_at <= now()`.

**Atomic counter updates (critical for correctness):**

```sql
-- Item completion (called by run_batch_item task)
UPDATE batches
SET completed_items = completed_items + 1
WHERE id = :batch_id;

-- Item failure
UPDATE batches
SET failed_items = failed_items + 1
WHERE id = :batch_id;
```

These use Postgres atomic increment (no read-modify-write race). The coordinator reads counters to determine when all items are done: `completed_items + failed_items = total_items`.

**ORM models** follow the existing pattern in `backend/src/db/models.py`: `BigInteger` primary key, `Text` ULID unique column, `TIMESTAMP(timezone=True)` for dates, `JSONB` for structured data, `ForeignKey` with `ondelete` cascades.

### RQ-4: ZIP Streaming and Bomb Protection

**Question:** How should ZIP archives be safely extracted for batch processing?

**Findings:**

Python's `zipfile.ZipFile` supports streaming extraction via `ZipFile.open()` which returns a file-like object per entry without extracting the entire archive to disk.

**Safe extraction pattern:**

```python
import zipfile
import io

BATCH_MAX_ZIP_BYTES = int(os.getenv("BATCH_MAX_ZIP_BYTES", 5 * 1024**3))  # 5 GB
BATCH_MAX_FILE_BYTES = int(os.getenv("BATCH_MAX_FILE_BYTES", 100 * 1024**2))  # 100 MB
BATCH_MAX_ITEMS = int(os.getenv("BATCH_MAX_ITEMS", 10000))
MAX_COMPRESSION_RATIO = 100

VALID_EXTENSIONS = {".stl", ".step", ".stp"}

def extract_batch_zip(zip_bytes: bytes, output_dir: str) -> list[dict]:
    """Extract valid CAD files from ZIP, enforcing size and count limits."""
    items = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        entries = [
            info for info in zf.infolist()
            if not info.is_dir()
            and any(info.filename.lower().endswith(ext) for ext in VALID_EXTENSIONS)
        ]

        if len(entries) > BATCH_MAX_ITEMS:
            raise ValueError(f"ZIP contains {len(entries)} files, max {BATCH_MAX_ITEMS}")

        for info in entries:
            # Zip bomb check: compression ratio
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > MAX_COMPRESSION_RATIO:
                    raise ValueError(
                        f"Suspicious compression ratio {ratio:.0f}:1 for {info.filename}"
                    )

            # Per-file size limit
            if info.file_size > BATCH_MAX_FILE_BYTES:
                items.append({"filename": info.filename, "status": "skipped",
                              "error": f"Exceeds {BATCH_MAX_FILE_BYTES} byte limit"})
                continue

            # Extract to output directory
            target = os.path.join(output_dir, os.path.basename(info.filename))
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())

            items.append({"filename": info.filename, "path": target,
                          "size": info.file_size})

    return items
```

**Key protections (per D-05 and Pitfall 5):**
- `Content-Length` header check before reading body (reject > 5 GB immediately)
- `ZipInfo.file_size` pre-check per entry (no extraction needed)
- Compression ratio > 100:1 rejection
- Only extract `.stl`, `.step`, `.stp` files (ignore other entries)
- Recurse into subdirectories within ZIP (D-03)
- Path traversal prevention: use `os.path.basename()` to strip directory components

**S3 mode:** Workers fetch files individually via `boto3.client('s3').get_object()`. No local extraction needed. The coordinator creates `batch_items` rows from the CSV manifest, each storing the S3 key. Workers fetch on demand.

### RQ-5: Webhook Retry with Exponential Backoff

**Question:** How should the retry mechanism work for failed webhook deliveries?

**Findings:**

Per D-11, the retry policy is 5 retries with exponential backoff + jitter: 10s, 30s, 90s, 270s, 810s.

**Implementation approach:**

A dedicated arq task `dispatch_webhook` handles delivery:

```python
RETRY_DELAYS = [10, 30, 90, 270, 810]  # seconds

async def dispatch_webhook(ctx, delivery_id: int):
    """Deliver a webhook. On failure, schedule retry."""
    delivery = await get_delivery(delivery_id)
    if delivery.attempts >= 5:
        await mark_delivery_failed(delivery_id)
        return

    success = await _post_webhook(
        url=delivery.batch.webhook_url,
        payload=delivery.payload_json,
        secret=delivery.batch.webhook_secret,
    )

    if success:
        await mark_delivery_delivered(delivery_id)
    else:
        delay = RETRY_DELAYS[delivery.attempts]
        jitter = random.uniform(0, delay * 0.1)
        await update_delivery_retry(delivery_id, delay + jitter)
        # Re-enqueue with defer
        await ctx["redis"].enqueue_job(
            "dispatch_webhook", delivery_id,
            _defer_by=delay + jitter,
        )
```

The `_post_webhook` function:
- Uses `httpx.AsyncClient` with 10-second timeout
- Sets headers: `Content-Type: application/json`, `X-CadVerify-Signature: ...`
- Considers 2xx success, anything else failure
- Logs response status code on the `webhook_deliveries` row

**Decoupling (D-12):** Webhook dispatch is fire-and-forget from item processing. The `run_batch_item` task creates a `webhook_deliveries` row and enqueues `dispatch_webhook`, but does not wait for delivery. Webhook failures never block batch progress.

### RQ-6: CSV Export Streaming

**Question:** How should the CSV results endpoint handle large batches efficiently?

**Findings:**

For a 10k-item batch, the CSV export could be ~1-2 MB. Use FastAPI's `StreamingResponse` with a generator:

```python
from fastapi.responses import StreamingResponse
import csv
import io

async def batch_results_csv(batch_id: int, session: AsyncSession):
    async def generate():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["filename", "status", "verdict", "best_process",
                         "issue_count", "duration_ms", "analysis_url", "error"])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        # Paginated query to avoid loading all items into memory
        cursor = None
        while True:
            items = await fetch_batch_items_page(session, batch_id, cursor, limit=200)
            if not items:
                break
            for item in items:
                writer.writerow([...])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
            cursor = items[-1].ulid

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=batch_{batch_ulid}_results.csv"},
    )
```

This streams results without loading the full dataset into memory.

## Validation Architecture

### Critical Path Validations
1. **Batch creation flow:** POST -> validate input -> create `batches` row -> enqueue coordinator -> return 202 with batch ID (< 2 seconds)
2. **Coordinator lifecycle:** Extract/fetch -> create items -> drip-feed -> track -> complete
3. **Webhook delivery:** Item complete -> create delivery row -> enqueue dispatch -> retry on failure
4. **Progress API:** Single-row SELECT on `batches` for O(1) progress

### Risk Mitigations
- ZIP bomb: compression ratio check + per-file size limit + total count cap
- Redis exhaustion: coordinator drip-feed (not 10k simultaneous enqueues)
- Webhook consumer down: exponential backoff + 5 retry cap + audit trail
- Concurrent batch counter updates: Postgres atomic INCREMENT (no application-level locking)
- S3 credential security: per-batch in request body for beta; per-tenant settings for production

### Integration Points with Existing Code
- `analysis_service.run_analysis()` called per batch item (unchanged)
- `ArqJobQueue.enqueue()` extended with new task types
- `WorkerSettings.functions` list extended with 3 new task functions
- `models.py` extended with 3 new ORM classes
- New Alembic migration `0004`
- New routes in `batch_router.py`
- New services: `batch_service.py`, `webhook_service.py`

## RESEARCH COMPLETE
