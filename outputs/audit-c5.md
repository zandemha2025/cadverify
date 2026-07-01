# CadVerify Cycle 5 — Validation Audit (productionization)

Auditor: Cycle 5 Validation-Auditor · Date: 2026-06-29
Env: `/Users/nazeem/Desktop/developer/cadverify/backend/.venv/bin/python` (Python 3.9.6, macOS arm64 / Darwin 25.4); frontend Next.js 16.2.3 (Turbopack), node v25.9.0.
Method: I ran everything below myself. No claim here is taken from the builder notes without an independent run.

## Verdict: **COMPLETE** — all four checks PASS. No fabrication, frontend builds, no log leaks, full suite green, invariants intact.

| # | Check | Result |
|---|---|---|
| 1 | STEP ingestion (real file, end-to-end) | **PASS** |
| 2 | Frontend cost surface (build + render + errors) | **PASS** |
| 3 | Observability / reliability | **PASS** |
| 4 | No regression + invariants | **PASS** |

One honest BLOCK for the handoff (NOT a failure): STEP B-rep / GD&T / PMI / tolerance extraction (AP242) is out of scope — cadquery/OCP is not installable in this env. STEP is costed from a gmsh-tessellated shell, which the module docstring and the UI footnote both disclose. The cost/decision path itself works fully.

---

## CHECK 1 — STEP INGESTION → cost decision (REAL file, verified by running it)

**What I tested.** Whether a real, open-licensed STEP file runs end-to-end to a cost decision through the actual project code (not a hardcoded/fabricated result), and whether the invariants hold on the STEP-derived mesh.

**File provenance (confirmed real + licensed).**
- `eight_cyl.stp` fetched from `https://raw.githubusercontent.com/tpaviot/pythonocc-core/master/test/test_io/eight_cyl.stp`.
- 63,663 bytes; first line `ISO-10303-21;` (valid STEP header).
- License confirmed live via GitHub license API: `spdx_id: "LGPL-3.0"` ("GNU Lesser General Public License v3.0"). OSI-approved; usable as a test fixture.

**End-to-end run I executed** (`step_to_trimesh_from_bytes` → `routes._run_cost_engine` → `estimate_decision` → `report_to_dict`, the exact route path):
- gmsh mesh: **24,524 faces, 12,278 verts, watertight=True, volume 1175.26 cm³, bbox 499.4×195.8×453.9 mm, 0.28 s**.
- Decision: `status: OK`, **make_now = cnc_turning / 6061-T6 Aluminum**, **crossover_qty = 45.6**.
- Invariant `unit_cost == Σ(line_items)`: **PASS over all 8 estimates** (every estimate `abs(unit_cost − Σ) < 0.02`).
- Provenance: **every driver + assumption ∈ {MEASURED, USER, DEFAULT}** — valid.
- Coherence: headline `make_now=cnc_turning` **==** low-qty recommendation `recommendation[50].process=cnc_turning` — PASS.

This is the live engine output (it even self-flags the part as `dfm_ready=False` for molding, since it was modeled for printing). Nothing hardcoded.

**Gated real-file test through the harness:** `STEP_NETWORK_TESTS=1 pytest tests/test_step_network.py` → **1 passed (16.83 s)**.

**HTTP route + refusal paths** (via TestClient, `tests/test_cost_api.py` STEP cases, all green):
- `POST /validate/cost` with a gmsh-synthesized box STEP → **200**, `status:OK`, invariants + provenance hold.
- Open-shell (non-watertight) STEP → **400 `GEOMETRY_INVALID`** (G1 refusal, carries geometry payload).
- STEP suffix without `ISO-10303-21` magic → **400**.
- Renamed compound suffix `part.stp.bak` → **400** (unsupported type).

**Reliability wiring confirmed in code:** STEP meshing is offloaded to the executor under `ANALYSIS_TIMEOUT_SEC` via `_parse_mesh_async` (→ clean 504, no event-loop block); `_GMSH_LOCK` serializes the process-global gmsh context; `enforce_triangle_cap` runs post-mesh (2 M hard stop for runaway assemblies). The `gmsh.initialize(interruptible=False)` deviation is correct and required (the default installs a SIGINT handler that only works on the main thread; the route meshes in a thread pool).

**Evidence:** real run captured in `scratchpad/e2e_step.py` + `coh2.py`; `tests/test_step_mesher.py`, `tests/test_cost_api.py`, `tests/test_step_network.py`.
**Fix:** none required.

## CHECK 2 — FRONTEND cost surface (build + render + errors)

**What I tested.** That the cost surface production-builds and typechecks, lints clean, and renders the full decision (process comparison + $/lead-time + crossover + make-vs-buy + provenance driver breakdown) with errors handled.

**Build (I ran it):** `npm run build` → **`✓ Compiled successfully in 2.1s`**, **`Finished TypeScript in 1497ms`** (no type errors), **`✓ Generating static pages (19/19)`**. Routes include `○ /cost` and `○ /dashboard/cost`.

**Lint (I ran it):** `npm run lint` → **0 errors, 3 warnings**, all in pre-existing untouched files (`ImageUploader.tsx`, `ModelViewer.tsx`, `ShareButton.tsx`). None in `CostDecisionCard.tsx` or the `/cost` page.

**Render coverage (`CostDecisionCard.tsx`, read + verified against `report_to_dict`):**
1. Make-vs-buy headline (`decision.note`, make-now process/material chip, tool/buy chip, crossover strip or explicit "No crossover in range").
2. Per-quantity recommendation table — qty · process/material · **$/unit** · lead `low–high d`, with "cheaper if redesigned" sub-row and "not DFM-ready" chip.
3. Process options comparison — per-process $/unit at each qty, `±error_band%`, MAKE-NOW highlight, DFM-blocker warning.
4. **Glass-box driver breakdown** — each driver `name · value+unit · [PROVENANCE source]` (MEASURED=blue/USER=green/DEFAULT=gray), the `line_items` map, and a **visible `Σ line items = unit cost` coherence line that flips red on divergence**.
5. Lead-time block — `low–high days` + components + capacity (`N machines × H hr/day [provenance]`).
6. Assumptions (provenance-tagged) + engine notes + fixed footnote "STEP files are costed from a tessellated mesh (DFM + cost), not B-rep/GD&T."
7. `GEOMETRY_INVALID` → `CostGeometryInvalidCard` repair card (reason + volume/bbox/watertight/faces + docs link).

**Error handling (`costEstimate` in `lib/api.ts`):** 200→report; 400 `GEOMETRY_INVALID`→`CostGeometryInvalidError(message, geometry)`→repair card; 429→toast; 5xx→toast+`Sentry.captureException`; other 4xx→error banner; network error→toast. Reuses `FileDropZone`, `ModelViewer`, `API_BASE`, auth/rate-limit idiom; nav item added. Client-side option validation mirrors the backend (qty ≤6 ints 1…10M; cavities ≥1; fixed enum lists) so bad options don't round-trip a 400.

**Evidence:** `scratchpad/fe-build.log`; `frontend/src/components/CostDecisionCard.tsx`, `frontend/src/app/(dashboard)/cost/page.tsx`, `frontend/src/lib/api.ts`.
**Fix:** none required.

## CHECK 3 — OBSERVABILITY / RELIABILITY (structured logs, no CAD/secret leak)

**What I tested.** That the new cost endpoint emits structured logs with NO raw CAD or secret leakage, with structured errors + caps + timeout applied.

**Real-stdout smoke I ran** (TestClient + conftest auth bypass, real structlog pipeline, secret-bearing filename + `Authorization: Bearer cv_live_TOPSECRET…` + `X-Request-ID: req-audit-smoke`):
```json
{"file_sha8":"6b2a70aa","suffix":".stl","face_count":12,"watertight":true,
 "status":"OK","make_now":"mjf","crossover_qty":5917.7,"n_qty":2,"region":"US",
 "material_class":"polymer","duration_ms":9.1,"event":"cost_estimate",
 "request_id":"req-audit-smoke","level":"info","timestamp":"2026-06-29T04:42:07Z"}
```
Verified on real captured stdout: `request_id` correlated from the header; **raw filename absent**, **`cv_live_…` secret absent**, **raw mesh bytes absent** (only the `file_sha8` hash + aggregate geometry). This is the production pipeline, not `capture_logs`.

**Structured errors:** `errors.py` now maps `501: "NOT_IMPLEMENTED"`. Endpoint covers `400 BAD_REQUEST`, `400 GEOMETRY_INVALID` (with geometry), `413 FILE_TOO_LARGE`, `422 VALIDATION_ERROR`, `429 RATE_LIMITED`, `501 NOT_IMPLEMENTED`, `504 ANALYSIS_TIMEOUT`. The `test_cost_*` reliability tests all pass: timeout→504, gmsh-absent→501, two concurrent STEP costs→both 200, sockets-blocked STEP cost→200 (zero egress), no-CAD-in-logs.

**Corpus router:** swapped to `structlog.get_logger("cadverify.corpus")`; `corpus_label` logs only `part_id/label/labeler/ts`, `corpus_mesh_404` logs `part_id/reason` — no CAD bytes or paths. Dev-gated (`LABELING_ENABLED=1`), localhost-only.

**Evidence:** `scratchpad/logsmoke3.py` output; `tests/test_cost_api.py` (6 hardening tests); `src/api/errors.py`, `src/api/corpus_router.py`.
**Fix:** none required.

## CHECK 4 — NO REGRESSION + INVARIANTS

**What I tested.** The full backend suite for regressions, and each cross-cycle invariant.

**Full suite I ran:** `cd backend && .venv/bin/python -m pytest -q` → **500 passed, 5 skipped, 0 failed (425.71 s)**. The 5 skips are environment-gated, not regressions: no manifold3d/blender boolean backend (1), OCP XDE unavailable for the AP242 v2 path (2), cadquery not installed (1), and `test_step_network.py` gated behind `STEP_NETWORK_TESTS=1` (1). (Prior cycles cited "~80 tests"; the suite has since grown to 500 — all green.)

**Invariants (independently confirmed):**
- `unit_cost == Σ(line_items)` — holds on the real STEP part (8/8 estimates) and across the suite.
- Provenance on every driver/assumption — confirmed on STEP run + tests.
- G1 broken-geometry refusal — non-watertight STEP/STL → `400 GEOMETRY_INVALID`, never a 500.
- Decision coherence (headline == low-qty argmin recommendation) — PASS on real STEP.
- Legacy toy model unsurfaced in the cost layer — `cost_per_cm3`/`estimated_cost_factor` appear in `src/costing/` only inside comments asserting they are NOT used; `report_to_dict` does not emit them. `estimated_cost_factor` survives only in the legacy `_to_response` analysis serializer (where it always lived), not the cost path.
- Zero network egress in the cost/serve path — `test_cost_zero_network_egress` + `test_cost_step_zero_network_egress` pass with `AF_INET/AF_INET6` blocked; gmsh meshes locally (temp file + in-process OCC).
- CAD-as-IP — `data/` is gitignored (`.gitignore` adds `data/`; `git check-ignore` confirms; `git ls-files data/` = 0 tracked). No third-party exfil in the cost/serve path.

**Evidence:** `scratchpad/fullsuite.log`; `git diff`; independent runs above.
**Fix:** none required.

---

## Handoff notes (not failures)
- **STEP B-rep / GD&T / tolerance (AP242) — BLOCKED:** cadquery/OCP not installable in this env (known-hard). STEP is costed from a tessellated shell; disclosed in module docstring + UI footnote + `report.notes` (±40–60% absolute band; crossover direction robust). This is the cadquery "v2" story.
- **gmsh throughput is serialized** by `_GMSH_LOCK` (one mesh at a time per process). Correct + safe for V1; a process pool is the future scale lever if STEP volume grows.
- **gmsh wheel** is ~36 MB and `gmsh>=4.13` is in `requirements.txt`; if a deploy target lacks a wheel, the route degrades to a clean 501 (`is_step_supported()`), not a crash.
- Cosmetic: benign `RuntimeWarning: matmul/divide` noise from a few degenerate tessellation triangles; the engine clips/handles them and output is valid (not a failure).
