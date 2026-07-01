---
phase: 01-stabilize-core
plan: 01.B
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/src/analysis/constants.py         # NEW
  - backend/src/analysis/additive_analyzer.py # import from constants
  - backend/src/analysis/cnc_analyzer.py      # import from constants
  - backend/src/analysis/molding_analyzer.py  # import from constants (if applicable)
  - backend/src/analysis/casting_analyzer.py  # import from constants (if applicable)
  - backend/src/api/routes.py                 # shared — delete PROCESS_ANALYZERS only
autonomous: true
requirements: [CORE-03, CORE-04]
must_haves:
  truths:
    - "Every requested process is dispatched exclusively through the registry (get_analyzer)"
    - "Changing a manufacturing threshold requires editing exactly one file (constants.py)"
    - "grep for PROCESS_ANALYZERS across backend/src returns zero hits"
    - "grep for MIN_WALL_THICKNESS assignments across backend/src/analysis returns only constants.py"
    - "All 21 process types still produce a ProcessScore on the cube_10mm fixture (no regressions)"
  artifacts:
    - path: backend/src/analysis/constants.py
      provides: "Single-source-of-truth for MIN_WALL_THICKNESS, SUPPORT_ANGLE_THRESHOLD, MIN_FEATURE_SIZE, STANDARD_TOOL_DIAMETERS, MAX_WORKPIECE, MAX_POCKET_DEPTH_RATIO, STANDARD_GAUGES"
      exports: ["MIN_WALL_THICKNESS", "SUPPORT_ANGLE_THRESHOLD", "MIN_FEATURE_SIZE", "STANDARD_TOOL_DIAMETERS", "MAX_WORKPIECE", "MAX_POCKET_DEPTH_RATIO", "STANDARD_GAUGES"]
    - path: backend/src/api/routes.py
      provides: "Registry-only dispatch; no legacy fallback"
      contains: "get_analyzer"
  key_links:
    - from: backend/src/analysis/additive_analyzer.py
      to: backend/src/analysis/constants.py
      via: "from src.analysis.constants import MIN_WALL_THICKNESS, ..."
      pattern: "from src\\.analysis\\.constants import"
    - from: backend/src/api/routes.py::validate_file
      to: backend/src/analysis/processes::get_analyzer
      via: "registry dispatch only — no PROCESS_ANALYZERS fallback"
      pattern: "get_analyzer\\(proc\\)"
---

<objective>
Complete the Phase-2 registry migration (CORE-03) and centralize all
manufacturing thresholds in one module (CORE-04). Delete the legacy
`PROCESS_ANALYZERS` dict and its fallback loop; extract scattered constants
from the four legacy analyzer files into `backend/src/analysis/constants.py`.

Purpose: The dual-path dispatch is a footgun — every bug fix must be applied
in two places, and tests diverge. Scattered constants mean a single CNC
machine upgrade forces edits across 4 files. Both patterns must die before
Phase 3 (persistence) starts caching results keyed by `analysis_version`.

Output:
- `backend/src/analysis/constants.py` with every manufacturing threshold.
- Legacy analyzer files importing from constants.py (no inline dicts).
- `routes.py` with `PROCESS_ANALYZERS` dict + legacy `else:` branch deleted.
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
@backend/src/api/routes.py
@backend/src/analysis/additive_analyzer.py
@backend/src/analysis/cnc_analyzer.py

<interfaces>
<!-- Contracts the executor needs — extracted from codebase. -->

From backend/src/analysis/processes/__init__.py (registry API):
```python
def get_analyzer(process: ProcessType) -> ProcessAnalyzer | None: ...
```
All 21 process types in ProcessType SHOULD have a registered analyzer. If any
returns None after this plan lands, that's a registry-registration bug that
must be fixed inside this plan (not deferred).

From backend/src/analysis/additive_analyzer.py (lines 22–64 — to be extracted):
```python
MIN_WALL_THICKNESS: dict[ProcessType, float] = { ProcessType.FDM: 0.8, ... }
SUPPORT_ANGLE_THRESHOLD: dict[ProcessType, float] = { ... }
MIN_FEATURE_SIZE: dict[ProcessType, float] = { ... }
```

From backend/src/analysis/cnc_analyzer.py (lines 19–34 — to be extracted):
```python
STANDARD_TOOL_DIAMETERS: list[float] = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0]
MAX_WORKPIECE: dict[ProcessType, tuple[float, float, float]] = { ... }
MAX_POCKET_DEPTH_RATIO: dict[ProcessType, float] = { ... }
```

From backend/src/analysis/processes/checks.py (line 635):
```python
STANDARD_GAUGES = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0]
```
Also move to constants.py. Update checks.py to import it.

From backend/src/api/routes.py (lines 38–47 — TO DELETE):
```python
PROCESS_ANALYZERS: dict[ProcessType, callable] = {}
for _p in ADDITIVE_PROCESSES: PROCESS_ANALYZERS[_p] = run_additive_checks
# ... etc ...
```
And the legacy `else:` branch (lines 175–183).

Imports to remove from routes.py after deletion:
- `from src.analysis.additive_analyzer import ADDITIVE_PROCESSES, run_additive_checks`
- `from src.analysis.casting_analyzer import CASTING_PROCESSES, run_casting_checks`
- `from src.analysis.cnc_analyzer import CNC_PROCESSES, run_cnc_checks`
- `from src.analysis.molding_analyzer import MOLDING_PROCESSES, run_molding_checks`
- `from src.analysis.sheet_metal_analyzer import run_sheet_metal_checks`

**IMPORTANT:** These legacy modules are NOT deleted — they are still imported
by their respective `processes/` registrations and by tests. Only the ROUTES
module stops depending on them.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task B1: Create constants.py (CORE-04)</name>
  <files>backend/src/analysis/constants.py</files>
  <action>
Create a NEW file at `backend/src/analysis/constants.py` following PATTERNS.md
§constants.py. Include every threshold listed in PATTERNS.md plus `STANDARD_GAUGES`.

Structure:
```python
"""Manufacturing DFM thresholds — single source of truth.

All process analyzers import from here. Changing a threshold requires
touching only this file.
"""
from __future__ import annotations
from src.analysis.models import ProcessType


# ──────────────────────────────────────────────────────────────
# Additive thresholds
# ──────────────────────────────────────────────────────────────
MIN_WALL_THICKNESS: dict[ProcessType, float] = {
    # COPY VERBATIM from additive_analyzer.py lines 22–34
}

SUPPORT_ANGLE_THRESHOLD: dict[ProcessType, float] = {
    # COPY VERBATIM from additive_analyzer.py lines 37–49
}

MIN_FEATURE_SIZE: dict[ProcessType, float] = {
    # COPY VERBATIM from additive_analyzer.py lines 52–64
}

# ──────────────────────────────────────────────────────────────
# CNC thresholds
# ──────────────────────────────────────────────────────────────
STANDARD_TOOL_DIAMETERS: list[float] = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0]

MAX_WORKPIECE: dict[ProcessType, tuple[float, float, float]] = {
    # COPY VERBATIM from cnc_analyzer.py lines 23–28
}

MAX_POCKET_DEPTH_RATIO: dict[ProcessType, float] = {
    # COPY VERBATIM from cnc_analyzer.py lines 31–34
}

# ──────────────────────────────────────────────────────────────
# Sheet metal
# ──────────────────────────────────────────────────────────────
STANDARD_GAUGES: list[float] = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0]

# ──────────────────────────────────────────────────────────────
# Additive build volumes (typical per-process machine envelope, mm)
# ──────────────────────────────────────────────────────────────
BUILD_VOLUMES: dict[ProcessType, tuple[int, int, int]] = {
    # COPY VERBATIM from additive_analyzer.py::check_build_volume BUILD_VOLUMES dict
}
```

Rules:
- Copy values VERBATIM. Do not "clean up", reorder, or change units.
- Do not add new thresholds in this commit — extraction only.
- If molding_analyzer.py or casting_analyzer.py have similar constants
  blocks, extract those too under new section headers.
  </action>
  <verify>
    <automated>cd backend &amp;&amp; python -c "from src.analysis.constants import MIN_WALL_THICKNESS, SUPPORT_ANGLE_THRESHOLD, MIN_FEATURE_SIZE, STANDARD_TOOL_DIAMETERS, MAX_WORKPIECE, MAX_POCKET_DEPTH_RATIO, STANDARD_GAUGES, BUILD_VOLUMES; from src.analysis.models import ProcessType; assert MIN_WALL_THICKNESS[ProcessType.FDM] == 0.8; assert MAX_POCKET_DEPTH_RATIO[ProcessType.CNC_3AXIS] == 4.0; print('ok')"</automated>
  </verify>
  <done>
- constants.py exists and imports without error.
- Values match the originals byte-for-byte (spot-check: FDM min wall = 0.8,
  CNC_3AXIS pocket ratio = 4.0).
- No duplicate definitions across module imports.
  </done>
</task>

<task type="auto">
  <name>Task B2: Replace inline dicts in legacy analyzer files with imports (CORE-04)</name>
  <files>backend/src/analysis/additive_analyzer.py, backend/src/analysis/cnc_analyzer.py, backend/src/analysis/processes/checks.py, backend/src/analysis/molding_analyzer.py, backend/src/analysis/casting_analyzer.py</files>
  <action>
For EACH file, delete the inline threshold dicts and replace with imports
from `src.analysis.constants`.

**additive_analyzer.py:**
1. Delete lines 22–34 (MIN_WALL_THICKNESS dict literal), 37–49
   (SUPPORT_ANGLE_THRESHOLD), 52–64 (MIN_FEATURE_SIZE), and the
   `BUILD_VOLUMES` dict inside `check_build_volume` (lines 303–316).
2. Add at imports block (after the existing `from src.analysis.models`
   import):
   ```python
   from src.analysis.constants import (
       BUILD_VOLUMES,
       MIN_FEATURE_SIZE,
       MIN_WALL_THICKNESS,
       SUPPORT_ANGLE_THRESHOLD,
   )
   ```
3. Inside `check_build_volume`, replace the local `BUILD_VOLUMES = { ... }`
   definition with the imported symbol.
4. Preserve `ADDITIVE_PROCESSES = list(MIN_WALL_THICKNESS.keys())` at the
   module tail — it now derives from the imported dict.

**cnc_analyzer.py:**
1. Delete lines 20–34 (STANDARD_TOOL_DIAMETERS, MAX_WORKPIECE,
   MAX_POCKET_DEPTH_RATIO).
2. Add:
   ```python
   from src.analysis.constants import (
       MAX_POCKET_DEPTH_RATIO,
       MAX_WORKPIECE,
       STANDARD_TOOL_DIAMETERS,
   )
   ```
3. Preserve `CNC_PROCESSES = list(MAX_WORKPIECE.keys())` at module tail
   (if present — if not, leave as-is).

**processes/checks.py:**
1. Delete line 635 `STANDARD_GAUGES = [...]`.
2. Add near the top imports:
   ```python
   from src.analysis.constants import STANDARD_GAUGES
   ```

**molding_analyzer.py, casting_analyzer.py:**
If these files contain constant dict literals (walk them — PATTERNS.md flags
the general pattern), extract to constants.py in a new section and import.
If they do not, leave them unchanged.

Do NOT change function signatures, docstrings, or analyzer logic. The ONLY
change is: literal dict → imported dict.

**Merge discipline:** This plan touches shared files (additive_analyzer.py,
cnc_analyzer.py) that Plan 01.C also edits (for exception handling). 01.C
edits ARE IN DIFFERENT LINES (exception blocks inside check_* functions).
Merge 01.B first, then 01.C. If 01.C lands first, rebase.
  </action>
  <verify>
    <automated>cd backend &amp;&amp; pytest tests/test_analyzers.py tests/test_context.py -q &amp;&amp; grep -Rn "^MIN_WALL_THICKNESS = {" src/analysis/ | grep -v constants.py | wc -l | grep -q "^0$" &amp;&amp; echo "ok"</automated>
  </verify>
  <done>
- No file other than `constants.py` contains `MIN_WALL_THICKNESS = {` at
  column 0.
- `pytest tests/test_analyzers.py tests/test_context.py` passes unchanged.
- Importing each legacy analyzer module still works.
- `ADDITIVE_PROCESSES` and `CNC_PROCESSES` are still exported.
  </done>
</task>

<task type="auto">
  <name>Task B3: Delete PROCESS_ANALYZERS dict and legacy fallback from routes.py (CORE-03)</name>
  <files>backend/src/api/routes.py</files>
  <action>
Modify `backend/src/api/routes.py`:

1. Delete the block at lines 35–47 in its entirety (the `PROCESS_ANALYZERS`
   dict construction and its section header comment).
2. Remove the now-unused imports at the top of the file:
   ```python
   from src.analysis.additive_analyzer import ADDITIVE_PROCESSES, run_additive_checks
   from src.analysis.casting_analyzer import CASTING_PROCESSES, run_casting_checks
   from src.analysis.cnc_analyzer import CNC_PROCESSES, run_cnc_checks
   from src.analysis.molding_analyzer import MOLDING_PROCESSES, run_molding_checks
   from src.analysis.sheet_metal_analyzer import run_sheet_metal_checks
   ```
   (These modules stay — they register themselves via the `@register`
   decorator. Only the ROUTES layer stops importing them.)
3. Inside `validate_file` (the analyzer loop currently at lines 165–189),
   simplify the body by removing the legacy `else:` branch. The loop
   becomes:
   ```python
   process_scores = []
   for proc in target_processes:
       new_analyzer = get_analyzer(proc)
       if new_analyzer is None:
           logger.warning("No registered analyzer for process %s — skipping", proc.value)
           continue
       try:
           proc_issues = new_analyzer.analyze(ctx)
       except Exception:
           logger.exception("Analyzer failed for %s", proc.value)
           continue
       if pack:
           proc_issues = pack.apply(proc_issues, proc)
       ps = score_process(proc_issues, geometry, proc)
       process_scores.append(ps)
   ```
4. If `from src.analysis.processes import get_analyzer` is already imported
   (line 20), leave it alone.

**CRITICAL — registry coverage check:**
Run `python -c "from src.analysis.models import ProcessType; from src.analysis.processes import get_analyzer; missing = [p.value for p in ProcessType if get_analyzer(p) is None]; print('missing:', missing)"`.

If `missing` is NON-EMPTY, the registry does NOT cover all 21 processes and
deleting `PROCESS_ANALYZERS` would drop support. In that case:
- STOP.
- Investigate which legacy analyzer(s) were not yet ported to `processes/`.
- For each missing ProcessType, create the registry class wrapper in the
  appropriate `processes/<category>/<name>.py` that delegates to the legacy
  run_*_checks function. This is part of this task (completing the
  migration), not a separate plan.
- Re-run the coverage check. Only proceed to delete the fallback once it
  passes (missing == []).

**Merge discipline:** routes.py edit region is lines 35–47 and 165–189. Plan
01.A edits lines 84–107 (disjoint). Plan 01.C edits env-reader pattern near
56–62 and wraps the 165–189 loop in `asyncio.timeout`. **01.C depends on
01.B landing first** — 01.C operates on the simplified (post-legacy) loop.
  </action>
  <verify>
    <automated>cd backend &amp;&amp; grep -Rn "PROCESS_ANALYZERS" src/ &amp;&amp; exit 1 || true; python -c "from src.analysis.models import ProcessType; from src.analysis.processes import get_analyzer; missing = [p.value for p in ProcessType if get_analyzer(p) is None]; assert not missing, f'missing: {missing}'; print('ok')" &amp;&amp; pytest tests/test_api.py -q</automated>
  </verify>
  <done>
- `grep -Rn PROCESS_ANALYZERS backend/src/` returns zero hits.
- Registry coverage check reports `missing: []` for all 21 ProcessType values.
- `pytest tests/test_api.py` passes.
  </done>
</task>

<task type="auto">
  <name>Task B4: Regression test — all-processes dispatch on cube fixture</name>
  <files>backend/tests/test_registry_coverage.py</files>
  <action>
Create a NEW test file `backend/tests/test_registry_coverage.py` that proves:
(a) every ProcessType is dispatched via the registry, and (b) constants
module is the single source for at least MIN_WALL_THICKNESS.

```python
"""Regression: registry covers all ProcessType values; constants are centralized."""
from __future__ import annotations

import pytest

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import ProcessType
from src.analysis.processes import get_analyzer


def test_registry_covers_every_process_type():
    """CORE-03: every ProcessType resolves to a registered analyzer."""
    missing = [p.value for p in ProcessType if get_analyzer(p) is None]
    assert not missing, f"Processes without registry entry: {missing}"


def test_constants_module_is_single_source(cube_10mm):
    """CORE-04: additive_analyzer imports MIN_WALL_THICKNESS from constants."""
    import src.analysis.additive_analyzer as aa
    import src.analysis.constants as c
    assert aa.MIN_WALL_THICKNESS is c.MIN_WALL_THICKNESS, (
        "additive_analyzer.MIN_WALL_THICKNESS must be the same object as "
        "constants.MIN_WALL_THICKNESS (imported, not redefined)"
    )


def test_registry_dispatch_on_cube_produces_scores(cube_10mm):
    """Smoke: every analyzer runs on the universal cube without raising."""
    info = analyze_geometry(cube_10mm)
    ctx = GeometryContext.build(cube_10mm, info)
    for proc in ProcessType:
        analyzer = get_analyzer(proc)
        assert analyzer is not None, f"No analyzer for {proc.value}"
        issues = analyzer.analyze(ctx)  # must not raise
        assert isinstance(issues, list)
```
  </action>
  <verify>
    <automated>cd backend && pytest tests/test_registry_coverage.py -q</automated>
  </verify>
  <done>
- All three tests pass.
- Failure of any test is a true regression and blocks the plan.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| `routes.py` → analyzer registry | Dispatch logic; divergence between paths = behavior mismatch |
| `constants.py` → analyzer modules | Threshold authority; wrong import = silent wrong output |

## STRIDE Register

| Threat ID | Category | Component | Disposition | Mitigation |
|-----------|----------|-----------|-------------|------------|
| T-01B-01 | Tampering (integrity) | Dual analyzer path diverges on same process | mitigate | Delete PROCESS_ANALYZERS; registry coverage test fails loudly if any ProcessType loses its analyzer |
| T-01B-02 | Repudiation | Threshold drift across files | mitigate | constants.py is the single source; test_constants_module_is_single_source asserts identity (`is`) not equality |
| T-01B-03 | Denial of Service | Registry miss silently drops a process from results | mitigate | `logger.warning` on None + test_registry_covers_every_process_type gates CI |
</threat_model>

<verification>
1. **CORE-03 registry-only dispatch:** `grep -Rn PROCESS_ANALYZERS backend/src/` returns zero hits.
2. **CORE-03 no-process-drops:** `test_registry_covers_every_process_type` passes.
3. **CORE-04 single-source constants:** `grep -Rn "^MIN_WALL_THICKNESS = {" backend/src/analysis/` returns only `constants.py`.
4. **CORE-04 same-object identity:** `test_constants_module_is_single_source` passes.
5. **No behavioral regression:** `pytest backend/tests/` green.
</verification>

<success_criteria>
- `backend/src/analysis/constants.py` exists with all seven constant collections.
- Every legacy analyzer file imports from constants (no inline dicts remain).
- `PROCESS_ANALYZERS` and its fallback `else:` branch are deleted from routes.py.
- Legacy analyzer imports removed from routes.py (ADDITIVE_PROCESSES et al).
- All 21 ProcessType values resolve via `get_analyzer()`.
- Full `pytest backend/tests/` suite passes.
</success_criteria>

<output>
Create `.planning/phases/01-stabilize-core/01.B-registry-constants/01.B-SUMMARY.md`
documenting:
- Which constants were extracted (list by symbol + source file + destination section).
- Whether any ProcessType required a new registry wrapper (if the coverage
  check surfaced gaps).
- The four commits produced (one per task).
- Any inline dicts that survived extraction and why (e.g., process-local
  tuning that is deliberately not a global threshold).
</output>
