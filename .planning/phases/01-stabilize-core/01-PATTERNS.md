# Phase 1: Stabilize Core — Pattern Map

**Mapped:** 2026-04-15
**Files analyzed:** 10 new/modified files
**Analogs found:** 10 / 10

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/src/parsers/step_parser.py` | parser | file-I/O | `backend/src/parsers/stl_parser.py` | role-match |
| `backend/src/api/upload_validation.py` (new) | middleware/utility | request-response | `backend/src/api/routes.py` (`_read_capped`, `_parse_mesh`) | data-flow-match |
| `backend/src/api/routes.py` | controller | request-response | `backend/src/api/routes.py` (self — targeted edits) | exact |
| `backend/src/analysis/constants.py` (new) | config | — | `backend/src/analysis/additive_analyzer.py` (constants block lines 22–64) | data-flow-match |
| `backend/src/analysis/context.py` | service/utility | transform | `backend/src/analysis/context.py` (self — targeted edits) | exact |
| `backend/src/analysis/processes/checks.py` | utility | transform | `backend/src/analysis/processes/checks.py` (self — targeted edits) | exact |
| `backend/src/analysis/additive_analyzer.py` | service | transform | `backend/src/analysis/cnc_analyzer.py` | role-match |
| `backend/src/analysis/cnc_analyzer.py` | service | transform | `backend/src/analysis/additive_analyzer.py` | role-match |
| `backend/tests/test_large_mesh.py` (new) | test | batch | `backend/tests/test_context.py` | role-match |
| `backend/tests/test_step_corruption.py` (new) | test | file-I/O | `backend/tests/test_api.py` | role-match |
| `backend/tests/test_scoring_ties.py` (new) | test | request-response | `backend/tests/test_analyzers.py` | role-match |
| `backend/tests/test_frontend_errors.py` (new) | test | request-response | `backend/tests/test_api.py` | exact |

---

## Pattern Assignments

### `backend/src/parsers/step_parser.py` (parser, file-I/O)
**Change:** Convert `parse_step_from_bytes` to context manager; add `mode=0o600` to temp file.
**Analog:** `backend/src/parsers/stl_parser.py`

**Current pattern to replace** (step_parser.py lines 99–105):
```python
import tempfile

suffix = Path(filename).suffix or ".step"
with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
    tmp.write(data)
    tmp.flush()
    return parse_step(tmp.name, linear_deflection)
```

**Target pattern — copy from stl_parser.py lines 33–46 (io.BytesIO in-memory) and adapt to context-manager discipline:**
```python
import tempfile
import os

suffix = Path(filename).suffix or ".step"
tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w+b")
# mode=0o600 applied via os.chmod after creation (NamedTemporaryFile does not
# accept a mode= arg on all Python versions — use os.chmod immediately after open)
try:
    os.chmod(tmp.name, 0o600)
    tmp.write(data)
    tmp.flush()
    return parse_step(tmp.name, linear_deflection)
finally:
    tmp.close()
    os.unlink(tmp.name)   # guaranteed cleanup even on parse failure
```

**Module-level import pattern** (step_parser.py lines 1–14):
```python
"""Parse STEP files ..."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import numpy as np
import trimesh
```
Keep this block; add `import os` if not present.

**Error-raise pattern** (step_parser.py lines 55–57):
```python
raise RuntimeError(
    "STEP parsing requires cadquery. Install with: pip install cadquery"
)
```
Use `ValueError` (not bare `Exception`) when parser detects malformed input — same convention as `stl_parser.py` lines 24–28.

---

### `backend/src/api/upload_validation.py` (utility, request-response) — NEW FILE
**Purpose:** Magic-byte validation + triangle-count cap, extracted before `_parse_mesh` is called.
**Analog:** `backend/src/api/routes.py` — specifically the `_read_capped` helper (lines 65–81) and the `_parse_mesh` guard block (lines 84–107).

**Imports pattern** — copy from routes.py lines 1–10:
```python
"""Pre-parse upload validation: magic bytes and triangle-count cap."""
from __future__ import annotations
import logging
import os
from fastapi import HTTPException

logger = logging.getLogger("cadverify.upload_validation")
```

**HTTPException raise pattern** — copy from routes.py lines 75–80:
```python
raise HTTPException(
    status_code=400,
    detail="File magic bytes do not match declared extension (.stl)",
)
```

**Environment-read pattern** — copy from routes.py lines 56–62 (`_max_upload_bytes`):
```python
def _max_triangles() -> int:
    """Read limit lazily so tests can override via monkeypatch."""
    try:
        n = int(os.getenv("MAX_TRIANGLES", "2000000"))
    except ValueError:
        n = 2_000_000
    return max(1, n)
```

**Magic-byte check skeleton** (no existing analog — derive from CONCERNS.md security note):
```python
# STL binary: no fixed magic; check minimum size + 80-byte header heuristic.
# STEP: magic bytes are "ISO-10303-21" at offset 0 (ASCII).
_STEP_MAGIC = b"ISO-10303-21"

def validate_magic(data: bytes, suffix: str) -> None:
    if suffix in (".step", ".stp"):
        if not data[:12] == _STEP_MAGIC:
            raise HTTPException(status_code=400, detail="File is not a valid STEP/STP (missing ISO-10303-21 header)")
    elif suffix == ".stl":
        # Binary STL minimum: 84 bytes (80 header + 4 count)
        if len(data) < 84:
            raise HTTPException(status_code=400, detail="File too small to be a valid STL")
```

---

### `backend/src/api/routes.py` (controller, request-response)
**Changes:** (1) Remove `PROCESS_ANALYZERS` legacy dict; (2) Add `ANALYSIS_TIMEOUT_SEC` env var + 504 handler; (3) Call `validate_magic` and triangle-count cap before `_parse_mesh`.
**Analog:** `backend/src/api/routes.py` (self — targeted edits)

**Legacy dict to remove** (routes.py lines 38–47):
```python
# DELETE this entire block:
PROCESS_ANALYZERS: dict[ProcessType, callable] = {}
for _p in ADDITIVE_PROCESSES:
    PROCESS_ANALYZERS[_p] = run_additive_checks
for _p in CNC_PROCESSES:
    PROCESS_ANALYZERS[_p] = run_cnc_checks
for _p in MOLDING_PROCESSES:
    PROCESS_ANALYZERS[_p] = run_molding_checks
PROCESS_ANALYZERS[ProcessType.SHEET_METAL] = run_sheet_metal_checks
for _p in CASTING_PROCESSES:
    PROCESS_ANALYZERS[_p] = run_casting_checks
```

**Fallback block to replace** (routes.py lines 175–183):
```python
# DELETE the else branch entirely:
else:
    legacy = PROCESS_ANALYZERS.get(proc)
    if legacy is None:
        continue
    try:
        proc_issues = legacy(mesh, geometry, proc, ctx.segments)
    except Exception:
        logger.exception("Legacy analyzer failed for %s", proc.value)
        continue
```
Replace with `continue` (or an explicit warning Issue emission — see exception-handling pattern below).

**Timeout env-read pattern** — follow `_max_upload_bytes` style (routes.py lines 56–62):
```python
def _analysis_timeout_sec() -> float:
    try:
        return max(1.0, float(os.getenv("ANALYSIS_TIMEOUT_SEC", "60")))
    except ValueError:
        return 60.0
```

**504 handler pattern** — follow existing HTTPException raise style (routes.py lines 75–80):
```python
import asyncio
try:
    async with asyncio.timeout(_analysis_timeout_sec()):
        # ... analysis loop ...
except asyncio.TimeoutError:
    raise HTTPException(status_code=504, detail="Analysis timed out. Reduce scope or try /validate/quick.")
```

**Logger pattern** — copy routes.py line 30:
```python
logger = logging.getLogger("cadverify.routes")
```

---

### `backend/src/analysis/constants.py` (config) — NEW FILE
**Purpose:** Single source of truth for all manufacturing thresholds currently scattered across `additive_analyzer.py` (lines 22–64), `cnc_analyzer.py` (lines 19–34), and similar files.
**Analog:** `backend/src/analysis/additive_analyzer.py` lines 22–64 (the constants block)

**Module header pattern** — copy from additive_analyzer.py lines 1–3:
```python
"""Manufacturing DFM thresholds — single source of truth.

All process analyzers import from here. Changing a threshold requires
touching only this file.
"""
from __future__ import annotations
from src.analysis.models import ProcessType
```

**Constants block pattern to extract and centralize** (additive_analyzer.py lines 22–64):
```python
# Minimum wall thickness by process (mm)
MIN_WALL_THICKNESS: dict[ProcessType, float] = {
    ProcessType.FDM: 0.8,
    ProcessType.SLA: 0.3,
    ...
}

# Maximum overhang angle (degrees from vertical)
SUPPORT_ANGLE_THRESHOLD: dict[ProcessType, float] = { ... }

# Minimum feature size (mm)
MIN_FEATURE_SIZE: dict[ProcessType, float] = { ... }
```

**Additional constants to pull from cnc_analyzer.py lines 19–34:**
```python
STANDARD_TOOL_DIAMETERS: list[float] = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0]

MAX_WORKPIECE: dict[ProcessType, tuple[float, float, float]] = {
    ProcessType.CNC_3AXIS: (1000, 500, 500),
    ...
}

MAX_POCKET_DEPTH_RATIO: dict[ProcessType, float] = {
    ProcessType.CNC_3AXIS: 4.0,
    ProcessType.CNC_5AXIS: 6.0,
}
```

**Section-separator comment style** — copy from routes.py and checks.py:
```python
# ──────────────────────────────────────────────────────────────
# Additive thresholds
# ──────────────────────────────────────────────────────────────
```

---

### `backend/src/analysis/context.py` (service/utility, transform)
**Changes:** (1) Fix scale-aware epsilon for micro and macro parts; (2) Replace bare `except Exception:` in `_compute_wall_thickness` with logged warning.
**Analog:** `backend/src/analysis/context.py` (self — targeted edits)

**Current epsilon to fix** (context.py lines 77–78):
```python
# Current — wrong for sub-mm and >1000mm parts:
scale_eps = max(bbox_diag * 1e-5, 1e-5)
```
Replace with clamped range:
```python
# Clamped: min 1e-4mm (avoids sub-mm drift), max 0.1mm (avoids skipping thin walls)
scale_eps = max(1e-4, min(bbox_diag * 1e-4, 0.1))
```

**Exception-handling pattern to replace** (context.py line 161 — bare `except Exception:` in `_compute_wall_thickness`):
```python
# Current:
except Exception:
    return thickness
```
Follow the `logger.exception` pattern from routes.py lines 105–107:
```python
except Exception:
    logger.warning(
        "_compute_wall_thickness failed (mesh=%d faces, bbox_diag=%.2f): %s",
        len(centroids), eps / 1e-5, "ray cast error",
        exc_info=True,
    )
    return thickness
```
Logger declaration to add at module top — copy from routes.py line 30:
```python
logger = logging.getLogger("cadverify.context")
```

**`inf`-guard pattern for wall thickness** (checks.py lines 36–37 shows the correct downstream guard):
```python
# Already present in checks.py — context must produce finite values when possible:
finite = np.isfinite(wt)
thin = finite & (wt < min_wall_mm)
```
The fix is in `_compute_wall_thickness` itself: ensure rays that miss because of scale emit `np.inf` only after exhausting the scale-eps retry, not immediately on first empty-hit.

---

### `backend/src/analysis/processes/checks.py` (utility, transform)
**Change:** Replace bare `except Exception: pass` blocks with categorized warning + Issue emission.
**Analog:** `backend/src/analysis/processes/checks.py` (self — targeted edits)

**Current silent-failure pattern** (checks.py line 222 inside `check_trapped_volumes`):
```python
except Exception:
    pass
```

**Target pattern** — follow Issue-emission style from checks.py lines 45–58 and logger pattern from routes.py line 30:
```python
except Exception:
    logger.warning(
        "check_trapped_volumes: containment test failed for %s — skipping",
        process.value,
        exc_info=True,
    )
    # Emit a categorized informational issue so the user knows analysis was partial:
    issues.append(Issue(
        code="ANALYSIS_PARTIAL",
        severity=Severity.INFO,
        message=f"Trapped-volume check incomplete for {process.value} (geometry error).",
        process=process,
        fix_suggestion="Verify mesh integrity: run /validate/quick to check watertightness.",
    ))
```

**Issue construction pattern** — copy from checks.py lines 45–58:
```python
return [Issue(
    code="THIN_WALL",
    severity=sev,
    message=f"...",
    process=process,
    affected_faces=thin_faces[:100].tolist(),
    region_center=region,
    measured_value=min_measured,
    required_value=min_wall_mm,
    fix_suggestion=f"...",
)]
```

---

### `backend/src/analysis/additive_analyzer.py` and `cnc_analyzer.py` (service, transform)
**Change:** Replace bare `except Exception:` blocks with categorized warning + Issue emission. Import thresholds from new `constants.py` instead of defining inline.
**Analog:** Each file is the analog of the other — both follow the same check-function + runner pattern.

**Bare `except Exception:` to replace** (additive_analyzer.py line 94, cnc_analyzer.py lines 191–192):
```python
# Current in additive_analyzer.py check_wall_thickness:
except Exception:
    return issues  # Skip if ray casting fails

# Current in cnc_analyzer.py check_thin_walls_cnc:
except Exception:
    return issues
```

**Target pattern** — follow routes.py exception logging style (lines 105–107) + emit ANALYSIS_PARTIAL Issue:
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
        fix_suggestion="Verify mesh is watertight before re-running.",
    ))
    return issues
```

**Constants-import pattern** — after `constants.py` exists, replace inline dict literals:
```python
# Replace:
MIN_WALL_THICKNESS = { ProcessType.FDM: 0.8, ... }
# With:
from src.analysis.constants import MIN_WALL_THICKNESS, SUPPORT_ANGLE_THRESHOLD, MIN_FEATURE_SIZE
```

**Logger pattern** — add to each analyzer module (not present currently):
```python
import logging
logger = logging.getLogger("cadverify.additive_analyzer")
# or: logger = logging.getLogger("cadverify.cnc_analyzer")
```

---

### `backend/tests/test_large_mesh.py` (test, batch) — NEW FILE
**Purpose:** Regression for >200k face meshes and timeout behavior.
**Analog:** `backend/tests/test_context.py` (unit tests for context + wall thickness)

**Module header pattern** — copy from test_context.py lines 1–8:
```python
"""Tests for large-mesh behavior: wall thickness, memory, and timeout."""
from __future__ import annotations
import numpy as np
import pytest
import trimesh
from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
```

**Fixture pattern** — copy from conftest.py lines 30–34 (procedural mesh creation):
```python
@pytest.fixture
def large_mesh_200k() -> trimesh.Trimesh:
    """Sphere subdivided to ~200k faces — stress-tests ray casting."""
    mesh = trimesh.creation.icosphere(subdivisions=6)  # ~40k faces per subdivision step
    return mesh
```

**Test structure** — copy from test_context.py lines 11–19 (shape assertions) and lines 23–29 (value assertions):
```python
def test_large_mesh_context_builds_without_crash(large_mesh_200k):
    ctx = GeometryContext.build(large_mesh_200k, analyze_geometry(large_mesh_200k))
    assert ctx.wall_thickness.shape == (len(large_mesh_200k.faces),)
    # No all-inf result for a closed sphere
    finite = ctx.wall_thickness[np.isfinite(ctx.wall_thickness)]
    assert finite.size > 0

def test_large_mesh_wall_thickness_no_all_inf(large_mesh_200k):
    ctx = GeometryContext.build(large_mesh_200k, analyze_geometry(large_mesh_200k))
    inf_pct = np.mean(~np.isfinite(ctx.wall_thickness)) * 100
    assert inf_pct < 50, f"Too many inf values ({inf_pct:.1f}%) for large mesh"
```

**Timeout test pattern** — use monkeypatch env approach from test_api.py lines 80–93:
```python
def test_analysis_timeout_returns_504(monkeypatch, large_mesh_200k, stl_bytes_of):
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "0.001")  # near-zero → guaranteed timeout
    import importlib, main
    importlib.reload(main)
    client = TestClient(main.app)
    data = stl_bytes_of(large_mesh_200k)
    r = client.post("/api/v1/validate", files={"file": ("large.stl", data, "application/octet-stream")})
    assert r.status_code == 504
```

---

### `backend/tests/test_step_corruption.py` (test, file-I/O) — NEW FILE
**Purpose:** Regression for corrupted / truncated STEP files; temp-file cleanup verification.
**Analog:** `backend/tests/test_api.py` (error-path tests: bad extension, empty file)

**Fixture + client pattern** — copy from test_api.py lines 16–22:
```python
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main, importlib
    importlib.reload(main)
    return TestClient(main.app)
```

**Error-response assertion pattern** — copy from test_api.py lines 63–69:
```python
def test_corrupted_step_returns_400(client):
    bad_data = b"ISO-10303-21;\nDATA;\n<!-- truncated"  # valid magic, corrupt body
    r = client.post(
        "/api/v1/validate",
        files={"file": ("bad.step", bad_data, "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "detail" in r.json()

def test_non_step_magic_with_step_extension_returns_400(client):
    """A JPEG renamed to .step should fail magic-byte check."""
    r = client.post(
        "/api/v1/validate",
        files={"file": ("photo.step", b"\xff\xd8\xff\xe0", "application/octet-stream")},
    )
    assert r.status_code == 400
```

**Temp-file cleanup test** — use `tmp_path` fixture (see TESTING.md mock section):
```python
def test_step_parse_leaves_no_temp_files(tmp_path, monkeypatch):
    """Verify parse_step_from_bytes cleans up even on parse failure."""
    import tempfile, os, glob
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.step")))
    from src.parsers.step_parser import parse_step_from_bytes
    try:
        parse_step_from_bytes(b"not a real step file", "test.step")
    except Exception:
        pass
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.step")))
    assert after == before, f"Leaked temp files: {after - before}"
```

---

### `backend/tests/test_scoring_ties.py` (test, request-response) — NEW FILE
**Purpose:** Regression for tied process scores and `best_process` selection edge cases.
**Analog:** `backend/tests/test_analyzers.py` (process-level assertions)

**Module header + helper pattern** — copy from test_analyzers.py lines 1–16:
```python
"""Tests for process scoring: ties, all-fail, and rank stability."""
from __future__ import annotations
from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes import get_analyzer
from src.matcher.profile_matcher import rank_processes, score_process

def _build_ctx(mesh):
    info = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, info)
    ctx.features = detect_all(mesh)
    return ctx
```

**Assertion pattern** — copy from test_analyzers.py lines 19–24 (existence checks):
```python
def test_tied_scores_produce_stable_ranking(cube_10mm):
    """When multiple processes tie, rank_processes must not raise or return None."""
    ctx = _build_ctx(cube_10mm)
    from src.analysis.models import AnalysisResult
    # Build a synthetic result where all scores are equal
    scores = [score_process([], analyze_geometry(cube_10mm), pt) for pt in ProcessType]
    result = AnalysisResult(...)
    ranked = rank_processes(result)
    assert ranked is not None
    assert len(ranked) == len(list(ProcessType))

def test_all_fail_case_produces_no_best_process(non_watertight_box, stl_bytes_of):
    """When every process fails, best_process must be None (not crash)."""
    ...
```

---

### `backend/tests/test_frontend_errors.py` (test, request-response) — NEW FILE
**Purpose:** Regression for frontend error paths: network timeout simulation, 504 response, malformed JSON guard.
**Analog:** `backend/tests/test_api.py` (full integration test file)

**Module header + client fixture** — copy from test_api.py lines 1–22 verbatim:
```python
"""Frontend error-path tests: 504, magic-byte rejection, upload limit."""
from __future__ import annotations
import importlib
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    return TestClient(main.app)
```

**Status-code + detail assertion pattern** — copy from test_api.py lines 63–69 and 72–78:
```python
def test_magic_byte_rejection_returns_400(client):
    r = client.post(
        "/api/v1/validate",
        files={"file": ("fake.stl", b"PK\x03\x04notanstl", "application/octet-stream")},
    )
    assert r.status_code == 400
    body = r.json()
    assert "detail" in body

def test_triangle_cap_rejection_returns_400(client, monkeypatch):
    """Upload a valid STL but over the triangle cap."""
    monkeypatch.setenv("MAX_TRIANGLES", "1")
    # ... build oversized mesh, serialize, POST, assert 400
```

---

## Shared Patterns

### Exception Handling in Analyzer/Context Code
**Source:** `backend/src/api/routes.py` lines 173–174 and 182–183
**Apply to:** All `except Exception:` blocks in `additive_analyzer.py`, `cnc_analyzer.py`, `context.py`, `processes/checks.py`
```python
except Exception:
    logger.exception("New analyzer failed for %s", proc.value)
    continue  # or: emit ANALYSIS_PARTIAL Issue then return/continue
```
The upgrade rule: every swallowed exception must do two things — (1) `logger.warning(..., exc_info=True)` and (2) either emit a typed `Issue(code="ANALYSIS_PARTIAL", severity=Severity.INFO, ...)` or `continue` in the loop. Never silently `pass` or `return []`.

### Logger Instantiation
**Source:** `backend/src/api/routes.py` line 30; `backend/main.py` line 27
**Apply to:** Any module currently missing a `logger` declaration (`additive_analyzer.py`, `cnc_analyzer.py`, `context.py`, `processes/checks.py`)
```python
import logging
logger = logging.getLogger("cadverify.<module_name>")
```

### HTTPException Error Response
**Source:** `backend/src/api/routes.py` lines 75–78, 87–90, 119–121
**Apply to:** `upload_validation.py` (new), any new route additions in `routes.py`
```python
raise HTTPException(
    status_code=400,
    detail="Human-readable description safe to expose to client",
)
```
Status code conventions in use: 400 (bad input), 413 (too large), 501 (missing dep), 504 (timeout).

### Environment Variable Reading (Lazy, Test-Overridable)
**Source:** `backend/src/api/routes.py` lines 56–62 (`_max_upload_bytes`)
**Apply to:** `ANALYSIS_TIMEOUT_SEC` reader in `routes.py`, `MAX_TRIANGLES` reader in `upload_validation.py`
```python
def _some_limit() -> int:
    """Read limit lazily so tests can override via monkeypatch."""
    try:
        return max(1, int(os.getenv("ENV_VAR_NAME", "default")))
    except ValueError:
        return default_int
```

### Test Client Fixture with Env Isolation
**Source:** `backend/tests/test_api.py` lines 16–22
**Apply to:** All four new test modules
```python
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main, importlib
    importlib.reload(main)
    return TestClient(main.app)
```

### Procedural Mesh Fixtures (No Binary Files in Git)
**Source:** `backend/tests/conftest.py` lines 30–52
**Apply to:** `test_large_mesh.py`, `test_step_corruption.py`, `test_scoring_ties.py`
```python
@pytest.fixture
def my_mesh() -> trimesh.Trimesh:
    """Describe what the fixture exercises and why this size."""
    return trimesh.creation.<primitive>(...)
```
All test meshes are generated via `trimesh.creation.*`; no binary STL/STEP files committed.

### CSG Skip Guard
**Source:** `backend/tests/conftest.py` lines 19–24
**Apply to:** Any test fixture using `.difference()` or `.union()`
```python
def _try_csg(op):
    try:
        return op()
    except Exception as e:
        pytest.skip(f"boolean ops unavailable: {e}")
```

### Section-Separator Comment Style
**Source:** `backend/src/api/routes.py` lines 35–37; `backend/src/analysis/processes/checks.py` lines 25–27
**Apply to:** `constants.py` (separating additive / CNC / molding / casting sections)
```python
# ──────────────────────────────────────────────────────────────
# Section name
# ──────────────────────────────────────────────────────────────
```

---

## No Analog Found

None. Every Phase 1 file has a sufficiently close existing analog.

---

## Metadata

**Analog search scope:** `backend/src/api/`, `backend/src/analysis/`, `backend/src/parsers/`, `backend/tests/`
**Source files read:** routes.py, step_parser.py, stl_parser.py, context.py, additive_analyzer.py, cnc_analyzer.py, processes/checks.py, main.py, tests/conftest.py, tests/test_api.py, tests/test_context.py, tests/test_analyzers.py
**Pattern extraction date:** 2026-04-15
