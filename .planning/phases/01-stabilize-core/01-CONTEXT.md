---
phase: 01-stabilize-core
type: coordination
plans: [01.A, 01.B, 01.C, 01.D]
shared_files:
  - backend/src/api/routes.py
  - backend/src/analysis/additive_analyzer.py
  - backend/src/analysis/cnc_analyzer.py
---

# Phase 1: Stabilize Core — Plan Coordination

**Goal:** The existing analyzer engine is trustworthy — no resource leaks, no silent
failures, no DoS vectors, no scale-dependent bugs — before any product surface is
built on top of it.

**Requirements covered (8 of 8):** CORE-01, CORE-02, CORE-03, CORE-04, CORE-05,
CORE-06, CORE-07, CORE-08.

## Parallelization Strategy

| Plan | Scope | Primary files | Requirements | Wave |
|------|-------|---------------|--------------|------|
| 01.A | STEP temp-file + magic-byte + triangle-cap | `parsers/step_parser.py`, `api/upload_validation.py` (new), `api/routes.py` (upload hook only) | CORE-01, CORE-07 | 1 |
| 01.B | Registry migration + constants | `analysis/constants.py` (new), `api/routes.py` (PROCESS_ANALYZERS delete), `additive_analyzer.py`, `cnc_analyzer.py` (import constants) | CORE-03, CORE-04 | 1 |
| 01.C | Exception handling + epsilon + timeout | `analysis/context.py`, `processes/checks.py`, `additive_analyzer.py`, `cnc_analyzer.py` (except blocks), `api/routes.py` (timeout hook only) | CORE-02, CORE-05, CORE-06 | 1 |
| 01.D | Test-gap fill | `tests/test_large_mesh.py`, `tests/test_step_corruption.py`, `tests/test_scoring_ties.py`, `tests/test_frontend_errors.py` (all new) | CORE-08 | 2 |

**Waves:**
- **Wave 1** (parallel): 01.A, 01.B, 01.C. All three touch `routes.py` but in
  disjoint regions (see Shared Files below).
- **Wave 2** (after Wave 1 merges): 01.D. Tests are written against the
  stabilized code and will fail if Wave 1 is incomplete.

## Shared Files — Merge Discipline

Three plans write to `backend/src/api/routes.py`. The edits are in disjoint
regions of the file and must be merged in this order to avoid conflicts:

### `backend/src/api/routes.py` edit regions

| Plan | Lines edited | Change |
|------|--------------|--------|
| 01.B | 38–47 (delete), 175–183 (delete `else` branch) | Remove `PROCESS_ANALYZERS` dict + legacy fallback |
| 01.A | 84–107 (inside `_parse_mesh`) + new import at top | Call `validate_magic()` + `enforce_triangle_cap()` before parser |
| 01.C | 56–62 pattern (new `_analysis_timeout_sec`), 165–189 (wrap analyzer loop in `asyncio.timeout`) | Add `ANALYSIS_TIMEOUT_SEC` + 504 handler |

**Merge order for routes.py:** 01.B → 01.A → 01.C.
- 01.B lands first because deleting legacy code simplifies the analyzer loop
  that 01.C wraps in a timeout context.
- 01.A next — adds magic-byte validation hook to `_parse_mesh`.
- 01.C last — wraps the (now-simpler) analyzer loop in `asyncio.timeout`.

Each plan's executor must git-pull before committing its routes.py edit. If two
Wave-1 plans race the executor SHOULD rebase rather than merge.

### `backend/src/analysis/additive_analyzer.py` and `cnc_analyzer.py`

Both 01.B (import constants) and 01.C (replace bare `except Exception:`) edit
these files, but the edits land in different lines:
- 01.B edits: lines 22–64 (additive), 19–34 (cnc) — constants block extraction
  and replaced with `from src.analysis.constants import ...`.
- 01.C edits: line 94 (additive), 191–192 (cnc) — exception handling inside
  check functions.

**Merge order:** 01.B → 01.C. 01.C's logger imports may already be added by
01.B when it touches file headers. Second-to-land executor must git-pull.

## Constraints Shared Across All Plans

- **Stack is fixed:** Python 3.10+ / FastAPI / trimesh / cadquery. No rewrites.
- **Conventions:** snake_case Python; `logger = logging.getLogger("cadverify.<mod>")`;
  HTTPException with structured `detail` string; lazy env-var reads via
  `os.getenv(..., default)` so tests can monkeypatch.
- **Error-response style:** status codes in use are 400 (bad input), 413 (too
  large), 501 (missing dep), 504 (timeout). Do NOT introduce new codes.
- **No binary test fixtures.** All test meshes generated via
  `trimesh.creation.*` (see `backend/tests/conftest.py`).
- **Pattern map:** Every file touched has an established analog documented in
  `01-PATTERNS.md`. Executors MUST read PATTERNS.md before implementing.

## Verification (phase-level)

After all four plans land:

1. `grep -R "PROCESS_ANALYZERS" backend/src/` returns zero hits (CORE-03).
2. `grep -Rn "except Exception:" backend/src/analysis/ backend/src/parsers/`
   returns zero bare-pass/bare-return matches; every hit is followed by a
   `logger.warning(..., exc_info=True)` line (CORE-02).
3. `pytest backend/tests/ -q` — all tests pass including the four new modules.
4. Upload 100 malformed `.step` files to `/api/v1/validate`; `ls /tmp/tmp*.step
   | wc -l` remains 0 after test (CORE-01).
5. `MAX_TRIANGLES=1 pytest -k triangle_cap` confirms 400 before parse (CORE-07).
6. `ANALYSIS_TIMEOUT_SEC=0.001 pytest -k timeout` confirms 504 (CORE-06).
7. `python -c "import src.analysis.constants as c; print(c.MIN_WALL_THICKNESS)"`
   returns the dict; `grep -Rn "MIN_WALL_THICKNESS = {" backend/src/analysis/`
   returns only `constants.py` (CORE-04).
8. Micro-cube (1mm) and macro-tank (5m) both yield finite wall_thickness
   samples on the new test (CORE-05).

## Risks

- **Merge conflict on routes.py.** Mitigation: disjoint edit regions + explicit
  merge order documented above.
- **01.B's constants extraction breaks analyzers.** Mitigation: 01.B's
  verification re-runs the full analyzer test suite after extraction. If
  analyzer outputs change for any fixture, 01.B is incomplete.
- **01.C's epsilon clamp changes existing test values.** Mitigation: 01.C
  verifies `test_context.py` still passes; if any assertion breaks, the new
  epsilon is too aggressive and must be tuned inside 01.C (not deferred to
  01.D).
- **01.D depends on Wave 1.** If any Wave-1 plan fails or regresses, 01.D's
  new tests will fail — surfacing the regression rather than masking it. This
  is the intended behavior.

---
*Coordination drafted 2026-04-15.*
