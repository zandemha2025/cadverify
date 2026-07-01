# CadVerify Cycle 3 — `POST /validate/cost` API notes

**Author:** Cycle 3 API Builder · **Date:** 2026-06-28 · **Status:** DONE — endpoint live, tests RUN & green
**Spec:** `outputs/c3-spec.md` §C · **Files touched:** `backend/src/api/routes.py` (handler + helpers), `backend/tests/test_cost_api.py` (new). No `main.py` change — the router is already mounted at `prefix="/api/v1"`.

---

## 1. Endpoint contract

| | |
|---|---|
| **Method / path** | `POST /api/v1/validate/cost` |
| **Auth** | `Authorization: Bearer cv_live_...` → `require_role(Role.analyst)` (composes `require_api_key`). Missing/invalid key → 401; role < analyst → 403. |
| **Kill-switch** | `dependencies=[Depends(require_kill_switch_open)]` → 503 `service_paused` when closed. |
| **Rate limit** | `@limiter.limit("60/hour;500/day")` (same as the `/validate` family) → 429 `RATE_LIMITED`. |
| **Body** | `multipart/form-data` |
| **Persistence** | **None.** No `session` dependency, no mesh blob, no `result_json` row. CAD is parsed, costed in-process, and discarded. |
| **Network** | **Zero egress.** The costing layer opens no sockets; the endpoint makes no outbound call (asserted by `test_cost_zero_network_egress`, which blocks `AF_INET`/`AF_INET6`). |

### Form fields

| field | type | default | notes |
|---|---|---|---|
| `file` | file (required) | — | `.stl` / `.step` / `.stp`. Magic-byte + extension + triangle-cap validated via the shared `_parse_mesh`. |
| `qty` | str | `"50,5000"` | comma list of ints, 1..10,000,000, max 6 values. |
| `region` | str | `"US"` | `US\|EU\|MX\|CN\|IN\|SA`. Unknown region falls back to ×1.0 (by design — not a 400). |
| `cavities` | int | `1` | formative tooling cavity count; `!=1` → USER provenance. |
| `complexity` | str | `"moderate"` | `simple\|moderate\|complex\|very_complex`; `!=moderate` → USER. |
| `material_class` | str | `"polymer"` | `polymer\|aluminum\|steel\|stainless\|titanium`; `!=polymer` → USER. |

`*_is_user` provenance flips ONLY when the form value differs from the DEFAULT (matches CLI semantics: omitted/default = DEFAULT, explicit non-default = USER).

### Response (200) — `report_to_dict(report)`
Full glass-box decision JSON: `geometry` (MEASURED summary only — no mesh/vertices leave the process), `estimates[]` (per process×qty: `unit_cost_usd`, `line_items`, provenance-tagged `drivers[]`, and `lead_time` with the new R1 `capacity` sub-key), `engine_feasibility[]`, `assumptions[]`, and `decision{}` with `make_now_process`, `recommendation`, `if_redesigned`, `crossover_qty`. Invariants preserved end-to-end: `unit_cost_usd == Σ line_items` (G3), every `$` driver carries `provenance ∈ {MEASURED,USER,DEFAULT}` + non-empty `source` (G6).

### Error table (all via the wired `errors.py` handlers)

| condition | status | code |
|---|---|---|
| missing `file` field | 422 | VALIDATION_ERROR |
| empty file / bad extension / bad magic / parse fail | 400 | BAD_REQUEST |
| bad `qty`/`complexity`/`material_class`/`cavities` | 400 | BAD_REQUEST |
| **broken geometry (G1)** | 400 | **GEOMETRY_INVALID** (structured dict-with-code; carries `geometry` summary + `message` repair reason) |
| over `MAX_UPLOAD_MB` / over triangle cap | 413 | FILE_TOO_LARGE |
| STEP without cadquery | 501 | (passthrough) |
| compute > `ANALYSIS_TIMEOUT_SEC` | 504 | ANALYSIS_TIMEOUT |
| missing/invalid API key | 401 | auth_missing / auth_invalid |
| role < analyst | 403 | insufficient_role |
| kill-switch closed | 503 | service_paused |
| rate limit exceeded | 429 | RATE_LIMITED |

---

## 2. Implementation

`routes.py` adds (after `_resolve_target_processes`, before the routes block):
- **`_run_cost_engine(mesh, filename)`** — scores the **full** analyzer registry from an already-parsed in-memory mesh (mirrors `cli._run_engine`, no narrowing, no persistence) → `(AnalysisResult, mesh, features)`.
- **`_parse_qty_list(qty)`** + `_COMPLEXITY` / `_MATERIAL_CLASSES` / `_MAX_QTYS` / `_MAX_QTY` constants — option parsing/validation.
- **`validate_cost(...)`** handler (placed alongside `validate_demo`): validates options → `_read_capped` (413/400) → `_parse_mesh` (400/413/501) → lazy-imports the costing layer → runs `estimate_decision` inside `asyncio.wait_for(run_in_executor(...))` (504 on timeout) → returns `report_to_dict(report)`. `GEOMETRY_INVALID` is raised as a structured 400 carrying the geometry summary + reason (G1 surfaces clean, never a 500).

Reuses (does not reinvent): `_read_capped`, `_parse_mesh`, `_analysis_timeout_sec`, `report_to_dict`, the `errors.py` structured-code handlers, and the auth/kill-switch/rate-limit dependencies of the `/validate` siblings.

---

## 3. Real test output (RUN — not fabricated)

### 3a. Endpoint test suite — `tests/test_cost_api.py`
```
$ CADVERIFY_PARTS_DIR=<parts> .venv/bin/python -W ignore -m pytest tests/test_cost_api.py -v
tests/test_cost_api.py::test_cost_decision_on_clean_cube PASSED          [ 12%]
tests/test_cost_api.py::test_cost_geometry_invalid_is_clean_400 PASSED   [ 25%]
tests/test_cost_api.py::test_cost_requires_auth PASSED                   [ 37%]
tests/test_cost_api.py::test_cost_rejects_bad_complexity PASSED          [ 50%]
tests/test_cost_api.py::test_cost_rejects_bad_qty PASSED                 [ 62%]
tests/test_cost_api.py::test_cost_rejects_bad_extension PASSED           [ 75%]
tests/test_cost_api.py::test_cost_user_provenance_on_overrides PASSED    [ 87%]
tests/test_cost_api.py::test_cost_zero_network_egress PASSED             [100%]
============================== 8 passed in 0.51s ===============================
```

### 3b. Full required suite (no regressions)
```
$ CADVERIFY_PARTS_DIR=<parts> .venv/bin/python -W ignore -m pytest \
    tests/test_costing_model.py tests/test_costing_gates.py \
    tests/test_costing_accuracy.py tests/test_cost_api.py -q
48 passed in 359.46s (0:05:59)
```
(40 costing R1/R2 tests — the 36 prior + R1/R2 additions, with the two accuracy tests now asserting the fix — plus the 8 new API tests. Existing `tests/test_api.py tests/test_require_api_key.py tests/test_rate_limit.py tests/test_upload_validation.py` also re-run green: `25 passed`.)

### 3c. Live end-to-end on a REAL part (TestClient → `/api/v1/validate/cost`)
Real ECU firewall mount STL (`1090523_..._ECU_Firewall_mount.stl`, 66.79 cm³):
```
HTTP 200
status OK
make_now_process mjf | q50 reco mjf | crossover_qty 739.2      <- headline make-now == low-qty reco (coherent)
mjf q5000 unit_cost 43.98 | lead 49.7 - 92.3 days             <- R1 fix (was 744.1-1381.9 days)
mjf q5000 capacity 6 machines x 22.0 hr/day [ DEFAULT ]       <- R1 capacity assumption inspectable + overridable
Sigma-check mjf5000 True                                       <- unit_cost == round(Σ line_items)
```
Broken part (`655044_..._MAF_Sensor_Adapter...stl`, non-watertight, volume 0) → clean structured 400:
```json
{
  "code": "GEOMETRY_INVALID",
  "message": "Geometry is not a measurable solid (volume ≤ 0 or non-watertight). Cost requires a watertight, positive-volume mesh. Repair required.",
  "geometry": { "volume_cm3": 0.0, "surface_area_cm2": 1302.68,
                "bbox_mm": [173.8, 127.5, 104.1], "watertight": false, "face_count": 18028 },
  "doc_url": "https://docs.cadverify.com/errors#GEOMETRY_INVALID"
}
```
No crash, no 500 — the buyer sees *why* (G1 "refuse to monetize broken geometry").

---

## 4. curl example

```bash
# Clean part — full should-cost decision
curl -X POST https://api.cadverify.com/api/v1/validate/cost \
  -H "Authorization: Bearer cv_live_<your-key>" \
  -F "file=@ecu_mount.stl" \
  -F "qty=50,5000" \
  -F "region=US" \
  -F "material_class=polymer" \
  -F "cavities=1" \
  -F "complexity=moderate"
# -> 200: { "status":"OK", "decision":{ "make_now_process":"mjf", ... }, "estimates":[...], "assumptions":[...] }

# Override the lead-time machine pool / tooling cavities (flips those drivers to USER provenance):
curl -X POST https://api.cadverify.com/api/v1/validate/cost \
  -H "Authorization: Bearer cv_live_<your-key>" \
  -F "file=@ecu_mount.stl" -F "qty=5000" \
  -F "cavities=4" -F "complexity=complex"

# Broken / non-watertight geometry -> clean 400 GEOMETRY_INVALID (not a 500):
curl -X POST https://api.cadverify.com/api/v1/validate/cost \
  -H "Authorization: Bearer cv_live_<your-key>" \
  -F "file=@broken_part.stl"
# -> 400: { "code":"GEOMETRY_INVALID", "message":"...repair required", "geometry":{...} }
```

> Note: per-process lead-time capacity (`n_machines`, `machine_hours_per_day`) and rate-card overrides are NOT exposed as form fields on this endpoint (the spec's §C form surface is the should-cost knobs only). They remain overridable via the CLI (`--set n_machines.MJF=10`) and the `EstimateOptions.rate_overrides` programmatic path; the returned `lead_time.capacity` dict states the assumption inline so it is inspectable in every response.

---

## 5. Acceptance — met
- Endpoint test **RUNS** and passes against a real part; returns a coherent decision JSON (headline `make_now_process` == low-qty recommendation pick). ✓
- Broken geometry → clean structured **400 GEOMETRY_INVALID** carrying the geometry summary, not a crash/500. ✓
- Auth enforced (`test_cost_requires_auth`: no Bearer → 401). ✓
- Zero network egress (`test_cost_zero_network_egress`: no `AF_INET`/`AF_INET6` socket opened during the request). ✓
- Invariants hold in the response: `unit_cost == Σ line_items`, every `$` driver provenance-tagged, R1 `lead_time.capacity` present + inspectable. ✓
- No persistence (no DB session dependency). ✓ · 48-test suite green, no regression. ✓
