# CadVerify Launch-Readiness Gauntlet — Adversarial Multi-Tenant QA

**Date:** 2026-07-11
**Target:** `origin/claude/resume-review-oxqw0l` @ `53ce84b` (HEAD confirmed)
**Stack:** backend uvicorn :8096 · frontend next :3096 · Postgres :5433 (`cadverify_gauntlet`, fresh UTF8 db, `alembic upgrade head` → 0037)
**Method:** real UI (Playwright/Chromium) + direct API (httpx/curl) against the live stack. All results below are from captured HTTP responses and screenshots — nothing simulated. Evidence in `evidence/*.json`, `screenshots/*.png`, `logs/*.log`.

---

## 0. Verdict up front

- **No tenant-isolation failure.** Every cross-org read attempt returned 404 / empty. This is the launch-critical property and it holds.
- **No 500s under junk input.** All 9 malformed-upload cases returned honest 4xx with no stack trace / path leak.
- **Auth edges clean.** Unauth/garbage/tampered/empty sessions all 401; logout clears the cookie.
- **One BLOCKER (availability):** a *single valid STEP file* (`nist_periodic_ctc05.stp`, a real repo test fixture) wedges the whole single-worker backend for ~2–3 min — health, signup and **every tenant's** request hang. The `ANALYSIS_TIMEOUT_SEC` safety cap does **not** fire. This is a cross-tenant noisy-neighbor / soft-DoS.
- **One MAJOR (contract):** `Retry-After` is silently stripped from every HTTPException-based 429/503 (org rate-limit, org quota, kill-switch, signup limit) by the global error handler.

---

## 1. Per-industry workflow results

| Industry | Org (email) | Declaration | Core flow | Result | Evidence |
|---|---|---|---|---|---|
| **Oil & gas** | ops@permian-sour.example | STEP part, sour service (H₂S / NACE MR0175), steel/stainless | Declare env → `/validate/cost` | **PASS** — sour-service materials **struck with cited standard**: `Mild Steel` and `Ductile Iron` excluded — *"sour service requires NACE MR0175 qualification"*. Cost coherent. | `evidence/oilgas_cost_steel.json`, screenshot `02b_oilgas_viewport.png` |
| **Aerospace / defense** | eng@delta-aero.example | Titanium, tight tolerance | `/validate/cost` (`material_class=titanium`, `tolerance_class=tight`, `complexity=very_complex`) | **PASS** — HTTP 200, coherent estimate. Zero-egress / IP-local messaging present: *"GEOMETRY NEVER LEAVES YOUR ENVIRONMENT… zero network egress"*, *"AIR-GAPPED · export-controlled programs"*, *"ITAR / AS9100 path"*. Cost route doc: *"IP-local compute: no network call."* | `evidence/aero_cost_titanium.json`, screenshot `04_security_zero_egress.png` |
| **Automotive** | cost@midwest-auto.example | Plastic part + high annual volume | `/validate/cost` (`material_class=polymer`, qty ladder 1…10 000, `cavities=4`) | **PASS** — HTTP 200; make-vs-buy **crossover / injection-molding / tooling-amortization** story rendered (section 5 "Resource cost — crossover scrub"). Should-cost $8.15/unit @ 10 000 on FDM/FFF. | `evidence/auto_cost_polymer.json`, screenshot `03_auto_result_full.png` |
| **Job-shop** | floor@jobshop-b.example | Machine floor (Haas VF-2, `cnc_3axis`, steel/SS), plate part | Declare machine → `/validate/cost` (`owned_processes=cnc_3axis`) | **PASS** — verdict `makeable_in_house`; make by `cnc_3axis` (Mild Steel); **marginal** unit cost $51.48 @ qty 10 (owned capital sunk). | `evidence/jobshop_cost.json` |
| **Extra orgs** | buyer@global-oem, quality@turbine-parts | concurrency/isolation load | see §3 | used as adversarial tenants | — |

**Recent fixes verified on the live stack:**

| Fix | Status | Evidence |
|---|---|---|
| Material-from-CAD provenance chip (magenta **CAD**, not DEFAULT) | **CONFIRMED** — uploading `cube_with_material.step` with no declared material auto-filled `material_class=aluminum`; response carries `assumptions[].provenance = "CAD"`, source *"material class = aluminum (read from the CAD file's material annotation)"*. | `evidence/material_provenance.json` |
| Long bar NOT routing to 5-axis | **CONFIRMED** — 300×20×20 bar → `best_process = binder_jetting` (cnc_5axis is feasible but **not** the pick). | `evidence/recent_fixes.json` |
| Fillet / chamfer features | **PARTIAL** — cylindrical **hole/boss** detection confirmed (`plate_with_hole` → `cylinder_hole` + `cylinder_boss`); explicit `FILLET`/`CHAMFER` labels **not observed on STL/mesh input** (rounded edges classify as `cylinder_boss`). Those labels appear reserved for analytic B-rep STEP, which I could not exercise — the only complex STEP fixture triggers Finding #1. Honest "couldn't fully test". | `evidence/recent_fixes.json` |

---

## 2. Tenant isolation (launch-critical)

Two orgs authed (A = `orgA-iso`, B = `orgB-iso`). Org A created an analysis + a persisted cost-decision; Org B probed them **by id** and **by list**.

| Org B probe against Org A's data | Status | Leaked A's data? |
|---|---|---|
| `GET /api/v1/cost-decisions/{A_id}` | **404** | no |
| `GET /api/v1/cost-decisions/{A_id}/export.json` | **404** | no |
| `GET /api/v1/cost-decisions/{A_id}/pdf` | **404** | no |
| `GET /api/v1/analyses/{A_id}` | **404** | no |
| `POST /api/v1/cost-decisions/{A_id}/approve` | **404** | no |
| `GET /api/v1/analyses` (B's own list) | 200 → **empty** | no |
| `GET /api/v1/cost-decisions` (B's own list) | 200 → **empty** | no |

**Result: PASS.** No id-guess or list path returned another tenant's records. `evidence/isolation.json`.

---

## 3. Concurrency

12 concurrent `/validate/cost` requests across 3 orgs (parallel threads).

- All **12 → HTTP 200**, wall time ~14 s, no crash, backend did not wedge.
- No cross-tenant bleed: each org's persisted decisions reference only its own uploads; identical concurrent requests within an org idempotently dedup to one decision (expected).

**Result: PASS.** `evidence/concurrency.json`.

---

## 4. Per-org rate limit

The stack ran **without Redis** (`health.redis=false`), so the two org limiters behaved as designed:

- **Redis hour/day circuit-breaker (`org_rate_limited`):** fails **OPEN** with no Redis — `/validate` still returns 200. This is the documented fail-open behavior (a Redis blip must never 429 legit traffic). Confirmed live. To see the 429 you need a real Redis; I could not stand one up, so this ceiling's *positive* path is **untested** (noted honestly).
- **Durable daily-analyses quota (`org_quota_exceeded`, DB-backed):** works without Redis. Set `ORG_ANALYSES_PER_DAY=3`, restarted, and confirmed **per-org isolation**:

| Org | Sequential `/validate` statuses | Behavior |
|---|---|---|
| A | `200, 200, 200, 429, 429, 429` | throttled at its own cap of 3 |
| B (concurrent) | `200, 200, 200, 429` | **independent** cap — unaffected by A |

429 body: `{"code":"org_quota_exceeded","message":"…daily analyses cap of 3…"}`. **Isolation proven.** `evidence/rate_limit.json`.
⚠️ See Finding #2 — this 429 ships **without** a `Retry-After` header.

---

## 5. Junk-input robustness (no 500s)

`POST /api/v1/validate` (and `/validate/cost`) with hostile inputs:

| Case | Status | 5xx? | Stack/path leak? | Body |
|---|---|---|---|---|
| `.txt` (text, not CAD) | **400** | no | no | `Unsupported file type: .txt…` |
| 0-byte `.stl` | **400** | no | no | `Empty file uploaded` |
| truncated `.step` | **400** | no | no | `Could not read STEP geometry…` |
| valid ext + garbage bytes | **400** | no | no | `Empty mesh from: garbage.stl` |
| oversize (120 MB) | **413** | no | no | `File exceeds 100MB limit` |
| hostile name (`../../etc/passwd\0.stl`) | **400** | no | no | `Empty mesh from: …` (filename reflected as an escaped JSON string only; no path traversal, no file read) |

`/validate/cost` junk (txt / 0-byte / garbage) → same clean **400s**.

**Result: PASS — zero 500s, zero stack traces, zero internal-path leaks.** `evidence/junk_input.json`.

---

## 6. Auth edges

| Case | Result |
|---|---|
| Unauth `GET /api/v1/analyses` | **401** |
| Unauth `POST /api/v1/validate` | **401** |
| Garbage session cookie | **401** |
| Empty session cookie | **401** |
| Tampered (last-chars flipped) HMAC cookie | **401** |
| `POST /auth/logout` | `Set-Cookie: dash_session="" … Max-Age=0` (session cleared) |

**Result: PASS.** `evidence/auth_edges.json`.

---

## 7. Ranked findings

### 🔴 BLOCKER — F1: One valid STEP upload stalls the whole backend for all tenants (event-loop starvation; timeout cap does not fire)

- **Endpoint:** `POST /api/v1/validate` (also `/validate/cost`, `/validate/assembly`).
- **Input:** `backend/tests/assets/nist_periodic_ctc05.stp` — a **real NIST test fixture already in the repo**, valid CAD, cold (uncached).
- **Observed:** the request runs ~2–3 min (gmsh mesh: *"step mesher rung 'primary' failed (Impossible to mesh periodic surface 103); retrying with rung 'meshadapt-uniform'"* → 112 428 faces → wall-thickness ray-cast). **During that window the entire single-worker backend is unresponsive** — `/health`, `/auth/signup`, and every tenant's request hang/time out.
  - Health-poll timeline (baseline 13 ms): `+4s ok` → **`+8s..+64s+` all 3 s timeouts (HTTP 000)** until the mesh completes, then recovers to ~7 ms.
- **`ANALYSIS_TIMEOUT_SEC` does not rescue it:** default is 60 s (`os.getenv("ANALYSIS_TIMEOUT_SEC","60")`), and I re-ran with it set to **2 s** — the request still ran >40 s with **no 504**. Root cause: `analysis_service.run_analysis` does `await asyncio.wait_for(loop.run_in_executor(None, _run_analysis_sync), timeout)`. The heavy gmsh meshing runs in the **default thread executor** and holds the GIL, so the event loop can't run the timeout coroutine (or serve `/health`) until the C call returns. `wait_for` cannot cancel a running thread.
- **Expected:** a slow/pathological part should time out (504) and/or be offloaded so it cannot starve the event loop; one tenant's upload must never freeze the platform.
- **Actual:** platform-wide stall; `ANALYSIS_TIMEOUT_SEC` silently ineffective for the meshing phase.
- **Multi-tenant impact:** any of the 10 orgs uploading one such (valid) STEP degrades all others; a malicious/looping tenant trivially holds the worker down. Per-request/per-org rate limits don't help — it's *one* request that keeps computing. Prod multi-worker deployment reduces but does not remove this (N such uploads wedge N workers; the runbook/dev config is single-worker = one upload = full outage).
- **Evidence:** `logs/backend_dos.log`, `logs/backend_timeout.log`, health-poll table above.
- **Fix direction:** run STEP meshing in the **process pool** (already exists: `parse_pool`, 3 workers) rather than the in-process thread executor, and enforce a hard wall-clock cap that actually terminates the worker; return 504/`GEOMETRY_TOO_COMPLEX` past the cap.

### 🟠 MAJOR — F2: `Retry-After` stripped from all HTTPException-based 429/503 responses

- **Root cause:** `src/api/errors.py:48` `structured_http_error_handler` rebuilds a fresh `JSONResponse(status_code=exc.status_code, content=exc.detail)` and **never copies `exc.headers`**.
- **Affected (all set `headers={"Retry-After": …}` that is then dropped):**
  - `src/auth/org_limits.py:107` — `org_rate_limited` **and** `org_quota_exceeded` (per-org rate limit / quota).
  - `src/auth/kill_switch.py:42` — 503 kill-switch (`Retry-After: 3600`).
  - `src/auth/signup_limits.py:38` — signup abuse throttle.
- **Confirmed on the wire:** `curl -D -` on an `org_quota_exceeded` 429 → **no `Retry-After`, no `X-RateLimit-*`** (only `content-type` + `x-content-type-options`). The 200/`RateLimitExceeded`-slowapi path is unaffected (it uses a *separate* handler, `rate_limit_handler`, that writes headers directly).
- **Expected:** 429/503 carry `Retry-After` (the task's own acceptance criterion; the code intends to send it).
- **Actual:** clients cannot honor backoff on the org limiter, quota, or kill-switch. Contract broken platform-wide for those responses.
- **Fix direction:** in `structured_http_error_handler`, pass `headers=getattr(exc, "headers", None)` into the `JSONResponse`.

### 🟡 MINOR — F3: Fillet/chamfer feature labels not surfaced for mesh (STL) input

- On STL, true rounded edges classify as `cylinder_boss` / `cylinder_hole`; `FeatureKind.FILLET` / `CHAMFER` were never emitted for the meshes tested (a rounded-rect extrusion with r5 vertical fillets → `70 flat + 3 cylinder_boss`).
- Not confirmed as a bug — the analytic fillet/chamfer detectors (`src/analysis/features/fillets.py`) operate on B-rep topology (STEP), which STL doesn't carry, and I could not run a fillet-bearing STEP (blocked by F1). Reported as an untested-on-this-path gap, not a failure. Cylindrical hole/boss detection **is** correct.

### 🟡 MINOR — F4 (informational): launch-config gate reproduced

- Confirmed the runbook's premise: a bare `uvicorn` launch without `DASHBOARD_SESSION_SECRET` et al. 500s at signup. Setting the documented env fixed it (signup → 200). Not a product bug (the product correctly refuses to sign a session without a real secret) — but worth surfacing in deploy docs, as the runbook notes.

---

## 8. What I could NOT test (honest gaps)

- **Org Redis hour/day rate-limit ceiling** (`org_rate_limited`) — needs a live Redis; I confirmed only its **fail-open** path (no Redis → traffic passes). The positive 429 path is untested.
- **Fillet/chamfer on analytic STEP** — the one complex STEP fixture triggers F1; I did not author a fresh fillet-bearing STEP (no CAD kernel to emit B-rep).
- **UI env-strike rendering** — the NACE strike is proven via API (`env_exclusions`); in the Playwright run the sour-service chip toggle didn't register before auto-verify, so the on-screen strike block shows the ambient state. The service-condition chips ("sour service (H₂S)", etc.) and the makeability framing are visible in `screenshots/02b_oilgas_viewport.png`.

---

## 9. Evidence index

- `evidence/isolation.json`, `concurrency.json`, `junk_input.json`, `auth_edges.json`, `rate_limit.json`
- `evidence/oilgas_cost_steel.json`, `aero_cost_titanium.json`, `auto_cost_polymer.json`, `jobshop_cost.json`
- `evidence/material_provenance.json`, `recent_fixes.json`
- `screenshots/01_verify_landing.png`, `02b_oilgas_viewport.png`, `03_auto_result_full.png`, `04_security_zero_egress.png`, `05_provenance_cad_full.png`
- `logs/backend*.log`, `logs/frontend.log`
