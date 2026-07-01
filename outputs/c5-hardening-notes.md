# CadVerify Cycle 5 — Hardening / Observability Notes (Workstream C)

Author: Hardening/Observability Builder · Date: 2026-06-29
Scope: production-harden the new Cycle-5 surfaces (`POST /api/v1/validate/cost`,
gmsh STEP ingestion, corpus labeling) per `c5-spec.md` §C. Code only — no git
commit. All counts below are from real runs in the project venv
(`backend/.venv/bin/python`, Python 3.9.6, macOS arm64).

---

## 1. What was added

### 1.1 Structured logging (structlog, request-id correlated, no CAD/secret leakage)
Both new surfaces previously used stdlib `logging.getLogger(...)`, which bypasses
the app's structlog JSON+scrub+request_id pipeline (`merge_contextvars →
add_log_level → TimeStamper → scrub_processor → JSONRenderer`, configured in
`main.py`; `request_id` bound by `RequestIDMiddleware`).

- **`src/api/routes.py`** — added a module-level `slog =
  structlog.get_logger("cadverify.cost")` and one structured outcome event per
  costed request in `validate_cost`:
  - `cost_estimate` (INFO) emitted after the report is produced. Fields:
    `file_sha8` (first 8 hex of `sha256(data)` — correlate without storing CAD),
    `suffix`, `face_count`, `watertight`, `status` (`OK`|`GEOMETRY_INVALID`),
    `make_now`, `crossover_qty`, `n_qty`, `region`, `material_class`,
    `duration_ms`. The single emit covers both the success path and the clean
    `GEOMETRY_INVALID` 400 refusal (status carries which).
  - `cost_timeout` (WARNING) on the 504 compute-timeout branch (same non-PII
    fields + `timeout_sec`).
  - **Never logged:** raw filename, mesh bytes, or any geometry beyond aggregate
    counts. `t0 = time.perf_counter()` captured at handler entry for latency.
- **`src/api/corpus_router.py`** — swapped the stdlib logger for
  `structlog.get_logger("cadverify.corpus")` and added request-scoped events:
  - `corpus_label` (INFO) on `POST /labels` — `part_id`, `label`, `labeler`,
    `ts` (no CAD; corpus ids/ontology keys only).
  - `corpus_mesh_404` (WARNING) on each `stream_mesh` 404 with a `reason`
    (`not_in_manifest` | `path_traversal` | `file_missing`).
  - `corpus_seed_failed` (WARNING) converted to structured kwargs.

### 1.2 Structured-error coverage gap closed
- **`src/api/errors.py`** — added `501: "NOT_IMPLEMENTED"` to `ERROR_CODES`.
  Before this, the degraded-no-gmsh STEP response (501 from `_parse_mesh`) mapped
  to the generic `UNKNOWN_ERROR`. Now it returns a stable
  `{code:"NOT_IMPLEMENTED", message, doc_url}`. (`test_error_codes_are_upper_snake`
  still green — `NOT_IMPLEMENTED` is UPPER_SNAKE.)

### 1.3 Reliability verification (no new code needed — confirmed in place)
The Wave-2 tree already wires the bounded-work primitives; verified by reading
`routes.py` + the new tests:
- **Triangle cap on STEP**: `_parse_mesh` runs `enforce_triangle_cap(mesh)`
  post-mesh for the STEP branch (the hard stop for runaway tessellation /
  assemblies) → clean 400.
- **Bounded parse**: `validate_cost` parses via `_parse_mesh_async`, which runs
  `_parse_mesh` in the executor under `asyncio.wait_for(_analysis_timeout_sec())`
  → 504 instead of blocking the event loop (this is the production-safety fix for
  slow gmsh STEP meshing).
- **Bounded compute**: the cost `_run` is itself wrapped in
  `asyncio.wait_for(..., _analysis_timeout_sec())` → 504.
- **gmsh concurrency**: `step_mesher._GMSH_LOCK` serializes the process-global
  gmsh context across executor threads.
- **Zero egress**: the costing layer + gmsh meshing (temp file + in-process OCC)
  open no network sockets.

### 1.4 Reliability/observability tests added — `backend/tests/test_cost_api.py`
Six new tests (file now 18 tests total, all green):
- `test_cost_emits_structured_log_without_cad` — asserts exactly one
  `cost_estimate` event with the non-PII fields and that the raw filename and
  mesh bytes never appear in any captured log.
- `test_cost_geometry_invalid_still_logs` — the 400 refusal path still emits one
  outcome event with `status=="GEOMETRY_INVALID"`.
- `test_cost_parse_timeout_is_clean_504` — a slow parse over
  `ANALYSIS_TIMEOUT_SEC` returns structured `504 ANALYSIS_TIMEOUT` (no hang).
- `test_cost_step_unavailable_is_structured_501` — gmsh-absent STEP degrades to
  structured `501 NOT_IMPLEMENTED` (not a 500/UNKNOWN_ERROR).
- `test_cost_concurrent_step_requests_both_ok` — two simultaneous STEP costs both
  return 200 (gmsh lock holds; no segfault / re-init error).
- `test_cost_step_zero_network_egress` — STEP cost path with `AF_INET`/`AF_INET6`
  blocked returns 200 (egress-free ingestion).

> Note on the log tests: `slog` is a cached lazy proxy under
> `cache_logger_on_first_use=True`, so `structlog.testing.capture_logs()` (which
> swaps processors) doesn't reach an already-resolved logger. The two log tests
> hand the handler a fresh, unresolved proxy via monkeypatch so it binds to the
> capture chain. This is a test-harness detail only; production logging is
> unaffected and is independently proven by the real end-to-end smoke below.

---

## 2. Real end-to-end log smoke (production pipeline, not capture_logs)

Posted a cost request through the real app (TestClient) with a secret-bearing
filename + `Authorization: Bearer cv_live_TOPSECRETKEY` + `X-Request-ID:
req-smoke-123`, capturing actual stdout. The emitted JSON line:

```json
{"file_sha8":"6b2a70aa","suffix":".stl","face_count":12,"watertight":true,
 "status":"OK","make_now":"mjf","crossover_qty":5917.7,"n_qty":2,"region":"US",
 "material_class":"polymer","duration_ms":9.9,"event":"cost_estimate",
 "request_id":"req-smoke-123","level":"info","timestamp":"2026-06-29T04:35:44Z"}
```

Verified on that line: `request_id` bound from the request header; the raw
filename (`SECRET_part_name`) is **absent** (only the `file_sha8` hash); the
`cv_live_TOPSECRETKEY` secret is **absent**; decision summary
(`make_now`/`crossover_qty`/`status`) and `duration_ms` present.

---

## 3. Test + build results (exact)

### Backend — FULL suite
```
cd backend && .venv/bin/python -m pytest -q
=> 500 passed, 5 skipped, 244 warnings in 383.47s (exit 0)
```
The 5 skips are environment-gated, not regressions:
- `test_features.py` — no boolean backend (manifold3d/blender).
- `test_step_ap242_parser.py` ×2 — OCP XDE not available (the BREP/GD&T v2 path,
  intentionally out of scope).
- `test_step_corruption.py` — cadquery not installed.
- `test_step_network.py` — gated behind `STEP_NETWORK_TESTS=1` (keeps CI green
  without egress).

No prior invariant regressed: `unit_cost==Σ(line_items)`, provenance on every
driver, G1 broken-geometry refusal, decision coherence, and zero-network-egress
guards all green (incl. the new STEP cases).

### Frontend — build + lint
```
cd frontend && npm run build
=> ✓ Compiled successfully; TypeScript finished; 19/19 static pages generated (exit 0)
   Routes built incl.  ○ /cost  and  ○ /dashboard/cost

cd frontend && npm run lint
=> ✖ 3 problems (0 errors, 3 warnings)
```
Lint: **0 errors**. The 3 warnings are pre-existing and in non-cost files
(`ModelViewer.tsx`, `ShareButton.tsx`, `reconstruct/ImageUploader.tsx`); none in
`CostDecisionCard.tsx` or the `/cost` page.

---

## 4. Files changed (this workstream — no git commit)
- `src/api/errors.py` — `501: "NOT_IMPLEMENTED"`.
- `src/api/routes.py` — `slog` + `cost_estimate`/`cost_timeout` structured events;
  module imports `hashlib`, `time`, `structlog`.
- `src/api/corpus_router.py` — structlog logger + `corpus_label` /
  `corpus_mesh_404` / `corpus_seed_failed` events.
- `tests/test_cost_api.py` — 6 new observability/reliability tests.

---

## 5. Production-readiness checklist — new surfaces

`POST /api/v1/validate/cost`
- [x] Auth: `require_kill_switch_open` + `require_role(analyst)`; rate-limited
      60/hour;500/day.
- [x] Bounded input: `_read_capped` (413 on size, 400 on empty); option
      validation fails fast before reading bytes.
- [x] Bounded parse: `_parse_mesh_async` under analysis timeout → 504 (no
      event-loop block on slow STEP meshing).
- [x] Bounded compute: cost `_run` under `wait_for` → 504.
- [x] Post-mesh triangle cap (2M default) → clean 400 on runaway tessellation.
- [x] Structured errors end-to-end: 400 `BAD_REQUEST`, 400 `GEOMETRY_INVALID`
      (with geometry payload), 413 `FILE_TOO_LARGE`, 422 `VALIDATION_ERROR`,
      429 `RATE_LIMITED`, 501 `NOT_IMPLEMENTED`, 504 `ANALYSIS_TIMEOUT`.
- [x] Structured outcome log (`cost_estimate`) — request_id-correlated, file
      hashed, no CAD/secret leakage; 504 logs `cost_timeout`.
- [x] Zero network egress (STL + STEP), no persistence (IP-local).
- [x] STEP ingestion serialized via `_GMSH_LOCK`; concurrent uploads queue,
      don't corrupt the global gmsh context.

Corpus labeling (`/api/v1/corpus`, dev-gated `LABELING_ENABLED=1`)
- [x] Structured `corpus_label` / `corpus_mesh_404` events (request_id-correlated).
- [x] Path-traversal guard on `stream_mesh` (now also logged).
- [x] Localhost-only env gate preserved (never ships to prod).

Open items / not in scope (handoff)
- STEP B-rep / GD&T / tolerance extraction remains BLOCKED (cadquery/OCP not
  installable here) — STEP is costed from a tessellated mesh, as disclosed.
- gmsh STEP throughput is serialized (one mesh at a time per process). Acceptable
  for V1; a process-pool is the future scale lever if STEP volume grows.
</content>
</invoke>
