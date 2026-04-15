---
phase: 01-stabilize-core
plan: 01.C
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/src/analysis/context.py
  - backend/src/analysis/processes/checks.py
  - backend/src/analysis/additive_analyzer.py
  - backend/src/analysis/cnc_analyzer.py
  - backend/src/api/routes.py                   # shared — timeout wrapper only
autonomous: true
requirements: [CORE-02, CORE-05, CORE-06]
must_haves:
  truths:
    - "An analyzer that encounters an unexpected exception emits an ANALYSIS_PARTIAL Issue; it never silently returns [] or swallows the error"
    - "Every bare `except Exception:` in analysis/parsers/context modules is replaced with logger.warning(..., exc_info=True) plus explicit continue or Issue emission"
    - "A 1 mm cube produces at least one finite wall-thickness sample (no all-inf)"
    - "A 5 m tank produces at least one finite wall-thickness sample (no all-inf)"
    - "An analysis that exceeds ANALYSIS_TIMEOUT_SEC returns HTTP 504 with a structured error, not a hanging connection"
  artifacts:
    - path: backend/src/analysis/context.py
      provides: "Scale-clamped epsilon + logged wall-thickness failure"
      contains: "max(1e-4, min(bbox_diag * 1e-4, 0.1))"
    - path: backend/src/analysis/processes/checks.py
      provides: "ANALYSIS_PARTIAL Issue emission on containment/ray errors"
      contains: "ANALYSIS_PARTIAL"
    - path: backend/src/api/routes.py
      provides: "_analysis_timeout_sec() + asyncio.timeout wrapping the analyzer loop; 504 on TimeoutError"
      contains: "asyncio.timeout"
  key_links:
    - from: backend/src/api/routes.py::validate_file
      to: asyncio.timeout
      via: "async with asyncio.timeout(_analysis_timeout_sec())"
      pattern: "asyncio.timeout\\("
    - from: backend/src/analysis/context.py::_compute_wall_thickness
      to: logger.warning
      via: "exception branch emits warning + exc_info=True"
      pattern: "logger\\.warning.*exc_info=True"
---

<objective>
Replace bare `except Exception:` in analyzers, context builder, and shared
checks with categorized warnings and explicit Issue emission (CORE-02).
Clamp the wall-thickness epsilon to a scale-aware range that handles sub-mm
and multi-meter parts (CORE-05). Add `ANALYSIS_TIMEOUT_SEC` with a 504
response on timeout (CORE-06).

Purpose: Silent failures corrupt engine trust — a user whose mesh crashes the
wall-thickness ray cast currently gets an empty issue list and a misleading
"pass" verdict. Scale-dependent epsilon breaks analysis for the two ends of
the market (micro medical parts, macro aerospace assemblies). An unbounded
analysis request can hold a worker forever, denying other users. All three
are pre-auth prerequisites.

Output:
- `context.py` with clamped epsilon + logged exception path.
- `processes/checks.py` with ANALYSIS_PARTIAL Issue emission on failures.
- `additive_analyzer.py` and `cnc_analyzer.py` exception blocks categorized.
- `routes.py` with asyncio.timeout + 504 handler.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phases/01-stabilize-core/01-CONTEXT.md
@.planning/phases/01-stabilize-core/01-PATTERNS.md
@.planning/codebase/CONVENTIONS.md
@.planning/codebase/CONCERNS.md

# Source files to be edited
@backend/src/analysis/context.py
@backend/src/analysis/processes/checks.py
@backend/src/analysis/additive_analyzer.py
@backend/src/analysis/cnc_analyzer.py
@backend/src/api/routes.py

<interfaces>
<!-- Extracted contracts the executor needs. -->

From backend/src/analysis/models.py:
```python
class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

class Issue:
    code: str
    severity: Severity
    message: str
    process: ProcessType | None
    fix_suggestion: str | None
    ...
```
The `ANALYSIS_PARTIAL` issue code is NEW to this plan. Severity = INFO.

From backend/src/analysis/context.py (line 76–78 — to be replaced):
```python
scale_eps = max(bbox_diag * 1e-5, 1e-5)
```
Replace with: `max(1e-4, min(bbox_diag * 1e-4, 0.1))` per PATTERNS.md.

From backend/src/api/routes.py (line 56–62 — clone this shape):
```python
def _max_upload_bytes() -> int:
    try:
        mb = int(os.getenv("MAX_UPLOAD_MB", "100"))
    except ValueError:
        mb = 100
    return max(1, mb) * 1024 * 1024
```

From backend/src/api/routes.py (current analyzer loop — to be wrapped):
```python
process_scores = []
for proc in target_processes:
    new_analyzer = get_analyzer(proc)
    ...
```
Wrap this loop (and only this loop) in `async with asyncio.timeout(...)`.

Bare-except locations audited for this plan (grep targets):
- `backend/src/analysis/context.py`:95, 100, 105, 161, 184
- `backend/src/analysis/processes/checks.py`:222 (check_trapped_volumes), 563 (check_rotational_symmetry), 725 (check_core_feasibility)
- `backend/src/analysis/additive_analyzer.py`:94, 290
- `backend/src/analysis/cnc_analyzer.py`:191–192 (and any other similar block surfaced by grep)
Executor MUST `grep -n "except Exception" backend/src/analysis/` and edit
EVERY hit, not just the line numbers above.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task C1: Fix wall-thickness epsilon + log failures in context.py (CORE-05, CORE-02)</name>
  <files>backend/src/analysis/context.py</files>
  <action>
Edit `backend/src/analysis/context.py`:

1. Add logger at module top (after `import trimesh` at line 23):
   ```python
   import logging
   logger = logging.getLogger("cadverify.context")
   ```

2. Replace the epsilon computation at lines 76–78:
   ```python
   # OLD: scale_eps = max(bbox_diag * 1e-5, 1e-5)
   # NEW: clamped to avoid sub-mm drift (too small) or skipping thin walls (too large)
   scale_eps = max(1e-4, min(bbox_diag * 1e-4, 0.1))
   ```

3. Replace every `except Exception:` in this file (lines ~95, 100, 105, 161, 184)
   with an instrumented variant. Pattern:
   ```python
   # line 161 example — _compute_wall_thickness ray-cast failure:
   except Exception:
       logger.warning(
           "_compute_wall_thickness ray cast failed (n_faces=%d, eps=%.3g)",
           len(centroids), eps,
           exc_info=True,
       )
       return thickness
   ```
   For the `_safe_attr` helper (line 184), keep `return default` but add
   `logger.warning("getattr %s failed", name, exc_info=True)`.

   For the bodies/facets exceptions (lines 100, 105), log and fall through
   to the existing default (`[mesh]` or `[]`).

4. Do NOT change the public GeometryContext dataclass fields, the build()
   signature, or the `_compute_wall_thickness` return contract (still
   returns length-N array, inf for unknown).
  </action>
  <verify>
    <automated>cd backend && pytest tests/test_context.py -q && grep -c "logger.warning" src/analysis/context.py | awk '$1 >= 4 {exit 0} {exit 1}'</automated>
  </verify>
  <done>
- `scale_eps` formula updated to `max(1e-4, min(bbox_diag * 1e-4, 0.1))`.
- Every `except Exception:` in context.py is followed by `logger.warning(..., exc_info=True)`.
- `pytest tests/test_context.py` passes unchanged.
- Logger declared at module level.
  </done>
</task>

<task type="auto">
  <name>Task C2: Categorize exceptions in processes/checks.py (CORE-02)</name>
  <files>backend/src/analysis/processes/checks.py</files>
  <action>
Edit `backend/src/analysis/processes/checks.py`:

1. Add logger at top (after existing imports):
   ```python
   import logging
   logger = logging.getLogger("cadverify.checks")
   ```

2. For EVERY `except Exception: pass` or `except Exception: return issues`
   block in this file, replace with the categorized pattern per PATTERNS.md.
   Example for `check_trapped_volumes` (around line 222):
   ```python
   except Exception:
       logger.warning(
           "check_trapped_volumes containment test failed for %s",
           process.value,
           exc_info=True,
       )
       issues.append(Issue(
           code="ANALYSIS_PARTIAL",
           severity=Severity.INFO,
           message=f"Trapped-volume check incomplete for {process.value} (geometry error).",
           process=process,
           fix_suggestion="Verify mesh integrity via /validate/quick.",
       ))
   ```

   Apply the same shape to:
   - `check_rotational_symmetry` (~line 563)
   - `check_core_feasibility` (~line 725)
   - Any other `except Exception:` blocks — grep to find them all:
     `grep -n "except Exception" backend/src/analysis/processes/checks.py`.

3. The ANALYSIS_PARTIAL Issue carries:
   - code = "ANALYSIS_PARTIAL"
   - severity = Severity.INFO
   - message includes WHICH check failed and for WHICH process
   - process = the current process argument
   - fix_suggestion is practical (usually "run /validate/quick to confirm
     watertightness")

4. Do NOT change function signatures. Do NOT change happy-path behavior.
  </action>
  <verify>
    <automated>cd backend && pytest tests/test_analyzers.py tests/test_context.py -q && grep -c "except Exception:" src/analysis/processes/checks.py | (read n; [ "$n" -gt 0 ] && grep -B0 -A1 "except Exception:" src/analysis/processes/checks.py | grep -q "logger.warning" && echo ok)</automated>
  </verify>
  <done>
- Every `except Exception:` in checks.py is followed by a `logger.warning` call.
- Every such block either emits an `ANALYSIS_PARTIAL` Issue or (for
  top-level `check_*` functions that cannot meaningfully emit) logs and
  returns `issues`.
- No `except Exception: pass` remains in the file.
  </done>
</task>

<task type="auto">
  <name>Task C3: Categorize exceptions in legacy additive/cnc analyzers (CORE-02)</name>
  <files>backend/src/analysis/additive_analyzer.py, backend/src/analysis/cnc_analyzer.py</files>
  <action>
For each file, add a logger and replace every `except Exception:` block with
the categorized pattern from PATTERNS.md §additive_analyzer.py and §cnc_analyzer.py.

**additive_analyzer.py (lines 94, ~290):**
1. Add logger after imports:
   ```python
   import logging
   logger = logging.getLogger("cadverify.additive_analyzer")
   ```
2. Replace line 94 (`check_wall_thickness`):
   ```python
   except Exception:
       logger.warning(
           "check_wall_thickness ray cast failed for %s",
           process.value,
           exc_info=True,
       )
       issues.append(Issue(
           code="ANALYSIS_PARTIAL",
           severity=Severity.INFO,
           message=f"Wall thickness check incomplete for {process.value} (ray cast failed).",
           process=process,
           fix_suggestion="Verify mesh is watertight; consider running /validate/quick.",
       ))
       return issues
   ```
3. Replace line ~290 (`check_trapped_volumes`) analogously with a message
   tailored to the trapped-volume check.

**cnc_analyzer.py (lines 191–192 and any others):**
Mirror the above. Logger name: `cadverify.cnc_analyzer`. Grep the file to
find every `except Exception:` and upgrade each one.

**Merge discipline:** Plan 01.B edits the import block (replacing inline
dicts with `from src.analysis.constants import ...`). 01.C edits bodies of
check functions. Different regions → should merge cleanly. If 01.B has not
landed yet, the inline dicts will still be present at the time 01.C makes
its edits — that is acceptable; 01.B will replace them later.
  </action>
  <verify>
    <automated>cd backend && pytest tests/test_analyzers.py -q && for f in src/analysis/additive_analyzer.py src/analysis/cnc_analyzer.py; do grep -c "except Exception:" "$f" | (read n; [ "$n" -eq 0 ] && echo "no-raw-excepts $f" && continue; grep -A1 "except Exception:" "$f" | grep -q "logger.warning" || { echo "FAIL $f"; exit 1; }); done; echo ok</automated>
  </verify>
  <done>
- Loggers declared in both files.
- Every `except Exception:` in both files is followed by `logger.warning(..., exc_info=True)` + either `ANALYSIS_PARTIAL` Issue emission or an explicit `return issues`.
- `pytest tests/test_analyzers.py` passes.
  </done>
</task>

<task type="auto">
  <name>Task C4: Add ANALYSIS_TIMEOUT_SEC + 504 handler in routes.py (CORE-06)</name>
  <files>backend/src/api/routes.py</files>
  <action>
Edit `backend/src/api/routes.py`:

1. Add `import asyncio` near the top of the file if not already present.

2. Add an env reader near the existing `_max_upload_bytes` (after line 62):
   ```python
   def _analysis_timeout_sec() -> float:
       """Read timeout lazily so tests can override via monkeypatch."""
       try:
           return max(0.1, float(os.getenv("ANALYSIS_TIMEOUT_SEC", "60")))
       except ValueError:
           return 60.0
   ```

3. Inside `validate_file`, wrap the analyzer work (from
   `geometry = analyze_geometry(mesh)` through the `process_scores` loop
   completion, i.e. lines 157–189 in the pre-01.B layout, or 157–~180 after
   01.B simplification) in an asyncio timeout. Structure:
   ```python
   try:
       async with asyncio.timeout(_analysis_timeout_sec()):
           geometry = analyze_geometry(mesh)
           ctx = GeometryContext.build(mesh, geometry)
           features = detect_features(mesh)
           ctx.features = features
           universal_issues = run_universal_checks(mesh)
           target_processes = _resolve_target_processes(processes)
           process_scores = []
           for proc in target_processes:
               # ... registry dispatch (from 01.B) ...
   except asyncio.TimeoutError:
       raise HTTPException(
           status_code=504,
           detail=(
               f"Analysis exceeded ANALYSIS_TIMEOUT_SEC="
               f"{_analysis_timeout_sec():.0f}s. Reduce scope with "
               f"?processes=... or try /validate/quick."
           ),
       )
   ```
   The `try` block must NOT wrap `_parse_mesh` or `_read_capped` — they run
   before analysis. It must wrap ONLY the geometry/context/analyzer work.

4. Python 3.10 compatibility note: `asyncio.timeout` is Python 3.11+. The
   project's minimum is Python 3.10 per PROJECT.md Constraints. If running
   on 3.10, use `asyncio.wait_for` instead:
   ```python
   async def _run_analysis(mesh, processes_param, pack):
       # ... move the analyzer body here ...
   try:
       result = await asyncio.wait_for(
           _run_analysis(mesh, processes, pack),
           timeout=_analysis_timeout_sec(),
       )
   except asyncio.TimeoutError:
       raise HTTPException(status_code=504, detail=...)
   ```
   Executor MUST check Python version (`python --version`) and pick the
   correct API. Prefer `asyncio.timeout` when 3.11+ is available.

**Merge discipline:** This is the LAST plan to touch routes.py in Wave 1.
Rebase onto the tip of 01.B (PROCESS_ANALYZERS deleted) and 01.A
(validate_magic wired in) before writing. The analyzer loop to wrap is the
post-01.B simplified loop.
  </action>
  <verify>
    <automated>cd backend && ANALYSIS_TIMEOUT_SEC=0.01 pytest tests/test_api.py -q -k "validate" || true; python -c "import os; os.environ['ANALYSIS_TIMEOUT_SEC']='0.001'; import importlib, main; importlib.reload(main); from fastapi.testclient import TestClient; import trimesh, io; m = trimesh.creation.icosphere(subdivisions=5); buf = io.BytesIO(); m.export(buf, file_type='stl'); c = TestClient(main.app); r = c.post('/api/v1/validate', files={'file': ('big.stl', buf.getvalue(), 'application/octet-stream')}); assert r.status_code == 504, r.status_code; print('ok')"</automated>
  </verify>
  <done>
- `_analysis_timeout_sec()` reader exists with ANALYSIS_TIMEOUT_SEC env + 60s default.
- Analyzer loop wrapped in `asyncio.timeout` (or `asyncio.wait_for` on 3.10).
- On timeout, endpoint returns 504 with a structured detail message.
- Normal-path tests in test_api.py still pass.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Analyzer → shared checks | Bare exceptions currently mask mesh-corruption bugs |
| HTTP client → analyzer loop | Unbounded runtime can pin a worker indefinitely |
| User-supplied mesh scale → epsilon math | Out-of-range scales silently produce all-inf results |

## STRIDE Register

| Threat ID | Category | Component | Disposition | Mitigation |
|-----------|----------|-----------|-------------|------------|
| T-01C-01 | Denial of Service | Unbounded analysis pins worker | mitigate | asyncio.timeout + 504; configurable via ANALYSIS_TIMEOUT_SEC |
| T-01C-02 | Repudiation | Silent swallowed exception hides failed check | mitigate | logger.warning(..., exc_info=True) + ANALYSIS_PARTIAL Issue |
| T-01C-03 | Information Disclosure | Exception message leaks mesh path / internal state | mitigate | `exc_info=True` goes to server logs only; HTTPException details are generic |
| T-01C-04 | Tampering (engine trust) | Scale-epsilon drift produces wrong verdict on micro/macro parts | mitigate | Clamped epsilon `max(1e-4, min(bbox_diag*1e-4, 0.1))` with regression tests in Plan 01.D |
</threat_model>

<verification>
1. **CORE-02:** `grep -Rn "except Exception:" backend/src/analysis/ backend/src/parsers/` shows every occurrence immediately followed by `logger.warning(..., exc_info=True)`.
2. **CORE-05 micro:** `test_context.py` adds a 1mm-cube test (landed in Plan 01.D) that asserts at least one finite wall-thickness.
3. **CORE-05 macro:** Same test with a 5m box.
4. **CORE-06 timeout:** Setting `ANALYSIS_TIMEOUT_SEC=0.001` on a non-trivial mesh returns 504 within 1 second. Verified by the task C4 inline script.
5. **No regression:** `pytest backend/tests/` green after all four tasks land.
</verification>

<success_criteria>
- Loggers present in `context.py`, `checks.py`, `additive_analyzer.py`, `cnc_analyzer.py`.
- `scale_eps` clamped formula in context.py.
- ANALYSIS_PARTIAL Issue code emitted from at least 3 sites (checks.py, additive_analyzer.py, cnc_analyzer.py).
- `_analysis_timeout_sec()` reader and `asyncio.timeout` wrapper in routes.py.
- 504 response on timeout demonstrated by inline verification script.
- Full test suite passes.
</success_criteria>

<output>
Create `.planning/phases/01-stabilize-core/01.C-exceptions-epsilon-timeout/01.C-SUMMARY.md`
documenting:
- Exact list of `except Exception:` sites upgraded (file:line + before/after snippet).
- The Python version used and whether `asyncio.timeout` or `asyncio.wait_for` was chosen.
- Any ANALYSIS_PARTIAL emissions added and the message content of each.
- Confirmation that the scale-eps clamp did not break test_context.py baseline.
</output>
