# Ops truth gate — 2026-07-08

Scope: object-store abstraction, strict worker/queue health, and an executed
backup/restore drill. Every command below was actually run in this container;
outputs are pasted verbatim. Nothing is a stub described as working, and no
metric is fabricated. The REAL-vs-EXTERNAL-GATE list at the end states exactly
what was proven here versus what still requires infrastructure I cannot stand
up in this container.

Environment: FastAPI/Python backend at `backend/`, Python 3.11.15, PostgreSQL
16.13 on `127.0.0.1:5433` (dedicated `cadverify_ops` DB), venv at
`backend/.venv`. `boto3` (1.43.43) and `moto[s3]` (5.2.2) were installed into
the venv for the S3 contract run; **`boto3` is intentionally NOT added to
`requirements.txt`** — it stays an optional dependency (see import-safety
below).

---

## Part 1 — Object-store abstraction

### What it does now
New package `backend/src/storage/`:

- `base.py` — `ObjectStore` ABC (+ a `runtime_checkable` `ObjectStoreProtocol`)
  with `put / get / open / exists / delete / url`. Streaming-friendly (`put`
  accepts bytes **or** a readable binary stream and copies in 256 KiB chunks;
  `open` returns a readable stream) and content-type aware. Defines
  `ObjectStoreError` and `ObjectNotFoundError` (subclasses `KeyError`).
- `local.py` — `LocalObjectStore`, the **default, zero-dependency** adapter.
  Atomic writes (temp file + `os.replace`), path-traversal guard, and a
  `local_path()` accessor so existing readers that do `open(path, "rb")` keep
  working unchanged.
- `s3.py` — `S3ObjectStore` (boto3 against any S3 endpoint incl. MinIO via
  `endpoint_url`). **Import-safe when boto3 is absent**: `boto3` is imported
  lazily inside `_client()`, guarded with `# type: ignore[import-not-found]`,
  and a missing dependency surfaces only when an S3 store is actually used —
  as a clear `ObjectStoreError` naming boto3 — never at import time.
- `factory.py` — `get_object_store(purpose, default_root)`; selects via
  `OBJECT_STORE_BACKEND` (default `local`). With the default, the local store
  is rooted exactly at the caller's existing `*_BLOB_DIR`, so behavior is
  byte-identical.

### Seam wired in (no runtime behavior change)
`backend/src/services/job_service.py::save_mesh_blob` now persists through the
abstraction. With the default local backend it is byte-for-byte identical to
before: the blob still lands at `$MESH_BLOB_DIR/{hash}.bin`, the call is still
idempotent, and it still returns that absolute filesystem path (which
`src/jobs/tasks.py` opens with `open(path, "rb")`). Verified:

```
$ MESH_BLOB_DIR=$TMP/meshes .venv/bin/python -c "<save twice, check>"
path: /tmp/tmp.XXXX/meshes/abc123.bin
exists: True
content ok: True
endswith: True
idempotent same path: True
not overwritten: True
```

Honest scope note: only the mesh **write** path is wired to the abstraction as
the demonstrating seam. The other blob sites found in the audit
(`reconstruction_service`, `batch_service` extraction, the PDF caches) still
use direct filesystem I/O and are documented follow-on migration targets — I
did not silently claim them as migrated.

### Contract tests (real run)
`backend/tests/test_storage_contract.py` runs ONE behavioral spec against both
adapters via a parametrized fixture:
- **local** — the real filesystem adapter, run for real.
- **s3** — the boto3 adapter driven against an **in-memory moto S3 stand-in**
  (`moto.mock_aws`), which genuinely exercises `put_object` / `get_object` /
  `head_object` / `delete_object` and even asserts `ContentType` metadata is
  written. This is NOT a mock of my own code — it is boto3 talking to moto.

`backend/tests/test_storage_lazy_import.py` blocks `boto3`/`botocore` via a
`sys.meta_path` finder and asserts the package still imports, `S3ObjectStore`
still constructs, and only an actual operation raises a clear boto3 error —
while the local default keeps working.

```
$ .venv/bin/python -m pytest -q tests/test_storage_contract.py tests/test_storage_lazy_import.py
.............................                                            [100%]
29 passed in 2.25s
```

(24 contract assertions across both adapters + 5 lazy-import assertions. The
S3 parametrization ran — it was not skipped.)

---

## Part 2 — Strict worker + queue health (honest)

`/health` stays fast (unchanged). A new **`GET /health/deep`** reports REAL
dependency state and degrades honestly:

- **postgres** — real `SELECT 1` probe; `{ok, error}`.
- **redis** — real `ping`; `{ok, expected, configured, error}`. When Redis is
  expected (real `REDIS_URL` or `RELEASE` set) but unreachable → status
  `degraded` (503), never green.
- **worker** — a real **last-heartbeat age**. New lightweight heartbeat
  (`backend/src/jobs/heartbeat.py`): the arq worker writes an ISO-timestamp key
  `cadverify:worker:heartbeat` with a TTL, on startup and every minute (wired
  in `backend/src/jobs/worker.py` startup hook + a per-minute `cron`).
  `/health/deep` reports `state ∈ {ok, stale, unknown, unavailable}` +
  `heartbeat_age_seconds`. A present-but-old heartbeat is `stale`; an absent
  one is `unknown` (falling back to arq's own `arq:queue:health-check` key as a
  coarse signal) — never a fabricated `ok`. Under `WORKER_STRICT_HEALTH=1` a
  non-`ok` worker degrades the endpoint.
- **queue** — real `ZCARD` of the arq queue (`arq:queue`) → `{depth, name}`.

`/health/deep` is registered public in the route-auth allowlist
(`scripts/ci/check_route_auth.py`) with the same rationale as `/health`
(no PII/secrets; machine-readable posture only).

Tests: `backend/tests/test_health_deep.py` (healthy path reports all deps;
Redis-down → structured 503 not 500; Postgres-down → structured 503; stale/
unknown worker; strict-mode degrade; not-expected-is-ok) and
`backend/tests/test_worker_heartbeat.py` (write/read/age/classify + cron
safety). Existing `tests/test_health.py` still passes unchanged.

```
$ .venv/bin/python -m pytest -q tests/test_health.py tests/test_health_deep.py tests/test_worker_heartbeat.py
.......................                                                  [100%]
23 passed in 1.35s
```

Route-auth guard (DoD #5) — the repo's checker stays green with the new public
route added to the allowlist:

```
$ .venv/bin/python scripts/ci/check_route_auth.py
route-auth-coverage OK (136 routes across api modules)
```

(also enforced inside pytest via `tests/test_metrics.py::test_route_auth_guard_passes`.)

---

## Part 3 — Backup/restore drill (actually executed)

Extended `scripts/ops/postgres-restore-drill.sh` with an in-place full-cycle
mode (`RESTORE_DRILL_MODE=inplace`) that exercises the real DR path against the
target DB: (a) `alembic upgrade head` + seed a KNOWN marker row, (b) `pg_dump
--format=custom`, (c) `DROP`+`CREATE` the target DB itself (`template0`, UTF8),
(d) `pg_restore`, (e) verify the known row survived. The pre-existing side-DB
mode is untouched (default).

Executed against `cadverify_ops` on `127.0.0.1:5433`. Full captured output:
**`outputs/ops-proof/restore-drill-2026-07-08.txt`**. Key lines:

```
== CADVerify in-place restore drill ==
target_db=cadverify_ops  host=127.0.0.1  marker=drill-20260708T210250Z-1943
-- (a) apply migrations: alembic upgrade head --
alembic current: 0032_rfq_packages (head)
-- (a) seed known marker row --
seeded marker rows (pre-dump): 1
-- (b) pg_dump --format=custom --
dump bytes=132224 sha256=eb35c873afeacf456e80948af2b6e9eb84afb93000f54953f638fd6d99a3920c
-- (c) DROP + CREATE target DB (template0, UTF8) --
recreated encoding: UTF8
-- (d) pg_restore into recreated DB --
-- (e) verify known marker row survived --
marker rows (post-restore): 1
public tables (post-restore): 31
alembic_version rows (post-restore): 1
duration_sec: 1
RESULT: PASS (known row survived drop+recreate+restore)
```

This is a real drop-and-recreate of an actual database and a real restore that
recovered a specifically-seeded row — not a table-count heuristic.

---

## Part 4 — Definition-of-done evidence

Full suite (DoD #1):
```
$ cd backend && .venv/bin/python -m pytest -q
1368 passed, 84 skipped, 7 warnings in 91.64s (0:01:31)
```

Postgres-gated filtered suite against the dedicated DB (DoD #2):
```
$ DATABASE_URL=postgresql://postgres@127.0.0.1:5433/cadverify_ops \
    .venv/bin/python -m pytest -q -k "health or storage or worker or queue"
80 passed, 1372 deselected, 1 warning in 5.16s
```

Typecheck ratchet not regressed (repo runs a pyright baseline gate at 237):
```
$ pyright --pythonversion 3.12 --pythonpath .venv/bin/python --outputjson src/ | jq .summary.errorCount
237        # == baseline scripts/ci/pyright_baseline.txt; 0 errors in new/changed files
```

---

## REAL vs EXTERNAL-GATE

### REAL (proven here, outputs above)
- Object-store abstraction + local adapter — contract tests run for real.
- S3 adapter behavior — proven against an **in-memory moto S3 stand-in** that
  drives the real boto3 client code path (put/get/head/delete + ContentType).
- S3 adapter import-safety without boto3 — proven (import blocked in-test).
- `/health/deep` honest degradation (DB down, Redis down, stale/unknown worker)
  — proven via structured 503 bodies, never 500, never fabricated green.
- Worker heartbeat mechanism — implemented and unit-proven; wired into the arq
  worker startup + per-minute cron.
- Backup/restore drill — actually executed end-to-end against a real Postgres,
  including drop+recreate and known-row survival.
- Route-auth invariant preserved (checker + pytest guard green).
- Full test suite + Postgres-gated filtered suite green; pyright baseline held.

### EXTERNAL GATE (NOT proven here — require infra I cannot stand up)
- **Live S3 / MinIO**: no S3/MinIO endpoint is reachable in this container
  (ports 9000/9001/4566 closed). The S3 adapter is proven against moto only.
  Running the same contract against a live MinIO/S3 endpoint (set
  `OBJECT_STORE_S3_ENDPOINT`/bucket/creds) is an external gate. boto3 is
  deliberately kept out of `requirements.txt`; a deployment that selects the S3
  backend must install it.
- **Live Redis + running arq worker heartbeat**: `/health/deep` worker/queue
  probes are unit-tested with a mocked Redis. Observing a real
  `worker=="ok"` / real queue depth requires a live Redis and a running
  `arq src.jobs.worker.WorkerSettings` process — an external gate.
- **Reader-side S3 wiring**: only `save_mesh_blob`'s write path is wired; the
  matching read path and the recon/batch/PDF blob sites are follow-on
  migrations, not done here.
- **Load / throughput / latency numbers**: no load test (k6 or otherwise) was
  run. No latency/throughput figures are cited anywhere in this document.
- **Multi-AZ / production-scale failover, off-box backup storage, PITR**: not
  exercised; the drill is a local same-cluster dump/restore.
