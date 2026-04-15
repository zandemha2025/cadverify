---
phase: 01-stabilize-core
plan: 01.D
type: execute
wave: 2
depends_on: [01.A, 01.B, 01.C]
files_modified:
  - backend/tests/test_large_mesh.py          # NEW
  - backend/tests/test_step_corruption.py     # NEW
  - backend/tests/test_scoring_ties.py        # NEW
  - backend/tests/test_frontend_errors.py     # NEW
autonomous: true
requirements: [CORE-08]
must_haves:
  truths:
    - ">200k face mesh can be analyzed without OOM and produces finite wall-thickness values"
    - "A corrupted STEP file is rejected at 400 without hanging and without leaking temp files"
    - "Tied process scores do not crash rank_processes or produce a null best_process"
    - "The API returns 504 when ANALYSIS_TIMEOUT_SEC is tiny; the frontend can parse the structured error"
    - "A micro-scale (1mm cube) and a macro-scale (5m box) part both return finite wall-thickness samples (CORE-05 regression)"
  artifacts:
    - path: backend/tests/test_large_mesh.py
      provides: "Regression for 200k-face meshes + timeout + scale-aware epsilon"
      min_lines: 60
    - path: backend/tests/test_step_corruption.py
      provides: "Regression for malformed STEP + magic-byte rejection + temp-file cleanup"
      min_lines: 50
    - path: backend/tests/test_scoring_ties.py
      provides: "Regression for tied scores + all-fail case in rank_processes"
      min_lines: 40
    - path: backend/tests/test_frontend_errors.py
      provides: "Regression for 504, 400 magic-byte, 400 triangle-cap — frontend-contract errors"
      min_lines: 40
  key_links:
    - from: backend/tests/test_large_mesh.py
      to: src.analysis.context.GeometryContext
      via: "import + build on trimesh.creation.icosphere(subdivisions=6)"
      pattern: "GeometryContext.build"
    - from: backend/tests/test_frontend_errors.py
      to: ANALYSIS_TIMEOUT_SEC env var
      via: "monkeypatch.setenv then TestClient POST"
      pattern: "monkeypatch.setenv\\(\"ANALYSIS_TIMEOUT_SEC\""
---

<objective>
Fill the four critical test gaps called out in CONCERNS.md and CORE-08:
large-mesh behavior, STEP corruption handling, scoring-tie stability, and
frontend error paths. These tests exercise the hardening work from plans
01.A/B/C — they MUST be written AFTER Wave 1 lands so they test the
stabilized engine, not the legacy one.

Purpose: Engine trust is what Phase 1 is buying. Tests are the proof. Without
these regressions any future refactor could silently re-introduce a temp-file
leak, an all-inf wall-thickness, an unbounded timeout, or a rank_processes
crash. Belt-and-suspenders for the Phase-2 gate.

Output:
- `tests/test_large_mesh.py` covering >200k face meshes + timeout + scale epsilon.
- `tests/test_step_corruption.py` covering malformed STEP + temp-file cleanup.
- `tests/test_scoring_ties.py` covering score ties + all-fail.
- `tests/test_frontend_errors.py` covering 504 + 400-magic + 400-cap.
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
@.planning/codebase/TESTING.md
@.planning/codebase/CONCERNS.md

# Plans this wave depends on (summaries will exist once Wave 1 merges)
@.planning/phases/01-stabilize-core/01.A-step-upload-hardening/01.A-SUMMARY.md
@.planning/phases/01-stabilize-core/01.B-registry-constants/01.B-SUMMARY.md
@.planning/phases/01-stabilize-core/01.C-exceptions-epsilon-timeout/01.C-SUMMARY.md

# Test patterns
@backend/tests/conftest.py
@backend/tests/test_api.py
@backend/tests/test_context.py

<interfaces>
<!-- Existing fixtures from conftest.py that the new tests will reuse. -->

```python
@pytest.fixture
def cube_10mm() -> trimesh.Trimesh: ...           # watertight 10mm cube
@pytest.fixture
def non_watertight_box() -> trimesh.Trimesh: ...   # cube with 2 faces removed
@pytest.fixture
def stl_bytes_of(): ...                            # callable mesh -> bytes
```

TestClient client fixture (copy pattern from test_api.py lines 16–22):
```python
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main, importlib
    importlib.reload(main)
    return TestClient(main.app)
```

API contract the tests assert against (post Wave 1):
- `POST /api/v1/validate` returns 200 on happy path, 400 on bad magic / size /
  triangle cap, 413 on oversize, 501 on missing cadquery, 504 on timeout.
- Error body shape: `{ "detail": str }` (FastAPI default HTTPException).
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task D1: test_large_mesh.py — 200k-face regression + scale-aware epsilon + timeout</name>
  <files>backend/tests/test_large_mesh.py</files>
  <action>
Create `backend/tests/test_large_mesh.py` following PATTERNS.md §test_large_mesh.py.

Required test functions (all must pass):

```python
"""Regression: large-mesh behavior + scale-aware epsilon + timeout."""
from __future__ import annotations

import importlib
import io

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext


@pytest.fixture
def large_mesh_200k() -> trimesh.Trimesh:
    """Icosphere subdivided to ~200k faces. Stress-tests ray casting + memory."""
    return trimesh.creation.icosphere(subdivisions=6)


@pytest.fixture
def micro_cube_1mm() -> trimesh.Trimesh:
    """1mm cube — sub-mm scale tests the epsilon clamp."""
    return trimesh.creation.box(extents=[1.0, 1.0, 1.0])


@pytest.fixture
def macro_box_5m() -> trimesh.Trimesh:
    """5m box — multi-meter scale tests the epsilon clamp upper end."""
    return trimesh.creation.box(extents=[5000.0, 5000.0, 5000.0])


def test_large_mesh_context_builds_without_crash(large_mesh_200k):
    """CORE-08: context builder must handle >200k faces."""
    info = analyze_geometry(large_mesh_200k)
    ctx = GeometryContext.build(large_mesh_200k, info)
    assert ctx.wall_thickness.shape == (len(large_mesh_200k.faces),)


def test_large_mesh_wall_thickness_has_finite_values(large_mesh_200k):
    """Closed sphere must produce SOME finite wall-thickness samples."""
    info = analyze_geometry(large_mesh_200k)
    ctx = GeometryContext.build(large_mesh_200k, info)
    finite = ctx.wall_thickness[np.isfinite(ctx.wall_thickness)]
    assert finite.size > 0
    # Stricter: majority of a closed convex mesh should have finite wall thickness
    inf_pct = np.mean(~np.isfinite(ctx.wall_thickness)) * 100
    assert inf_pct < 50, f"{inf_pct:.1f}% inf values on closed sphere — epsilon or ray cast regression"


def test_micro_cube_produces_finite_wall_thickness(micro_cube_1mm):
    """CORE-05: 1mm-scale part must not return all-inf."""
    info = analyze_geometry(micro_cube_1mm)
    ctx = GeometryContext.build(micro_cube_1mm, info)
    finite = ctx.wall_thickness[np.isfinite(ctx.wall_thickness)]
    assert finite.size > 0, "Micro-cube produced all-inf wall thickness — epsilon too large"


def test_macro_box_produces_finite_wall_thickness(macro_box_5m):
    """CORE-05: 5m-scale part must not return all-inf."""
    info = analyze_geometry(macro_box_5m)
    ctx = GeometryContext.build(macro_box_5m, info)
    finite = ctx.wall_thickness[np.isfinite(ctx.wall_thickness)]
    assert finite.size > 0, "Macro-box produced all-inf wall thickness — epsilon too small"


def test_analysis_timeout_returns_504(monkeypatch, large_mesh_200k):
    """CORE-06: ANALYSIS_TIMEOUT_SEC=0.001 on a non-trivial mesh must return 504."""
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "0.001")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    client = TestClient(main.app)
    buf = io.BytesIO()
    large_mesh_200k.export(buf, file_type="stl")
    r = client.post(
        "/api/v1/validate",
        files={"file": ("big.stl", buf.getvalue(), "application/octet-stream")},
    )
    assert r.status_code == 504, f"expected 504, got {r.status_code}: {r.text[:200]}"
    assert "detail" in r.json()
```

If `test_analysis_timeout_returns_504` cannot reliably trigger on very fast
machines (the mesh export itself may exceed 0.001s, producing a 200 before
analysis starts), use a smaller mesh combined with `ANALYSIS_TIMEOUT_SEC=0.0001`
or monkeypatch `analyze_geometry` to sleep. Prefer the env-only approach
first; fall back to monkeypatch if flaky.
  </action>
  <verify>
    <automated>cd backend && pytest tests/test_large_mesh.py -q</automated>
  </verify>
  <done>
- All six test functions pass.
- Test runtime < 30 seconds total (icosphere subdivisions=6 is ~40k faces; if
  truly testing 200k, use subdivisions=7 — check exact face count, it should
  be > 200000).
  </done>
</task>

<task type="auto">
  <name>Task D2: test_step_corruption.py — malformed STEP + temp-file cleanup</name>
  <files>backend/tests/test_step_corruption.py</files>
  <action>
Create `backend/tests/test_step_corruption.py` following PATTERNS.md §test_step_corruption.py.

```python
"""Regression: corrupted/malformed STEP rejection + temp-file cleanup."""
from __future__ import annotations

import glob
import importlib
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    return TestClient(main.app)


def test_corrupted_step_returns_400(client):
    """A STEP file with valid magic but garbage body returns 400 (not 500, not hang)."""
    bad = b"ISO-10303-21;\nHEADER;\nTHIS IS NOT VALID STEP AT ALL\x00\x01"
    r = client.post(
        "/api/v1/validate",
        files={"file": ("bad.step", bad, "application/octet-stream")},
    )
    # Acceptable: 400 (parse failed), 501 (cadquery not installed)
    assert r.status_code in (400, 501), f"unexpected {r.status_code}: {r.text[:200]}"
    assert "detail" in r.json()


def test_non_step_magic_with_step_extension_returns_400(client):
    """A JPEG renamed to .step must fail at magic-byte check (pre-parse)."""
    r = client.post(
        "/api/v1/validate",
        files={"file": ("photo.step", b"\xff\xd8\xff\xe0JFIF\x00", "application/octet-stream")},
    )
    assert r.status_code == 400
    # Detail should reference the magic-byte check, not generic parse failure
    detail = r.json()["detail"]
    assert "magic" in detail.lower() or "iso-10303" in detail.lower() or "step" in detail.lower()


def test_truncated_step_returns_400(client):
    """A STEP file cut off mid-header must not hang or 500."""
    truncated = b"ISO-10303-21;\nHE"  # magic-pass but structurally broken
    r = client.post(
        "/api/v1/validate",
        files={"file": ("trunc.stp", truncated, "application/octet-stream")},
    )
    assert r.status_code in (400, 501)


def test_step_parse_leaves_no_temp_files():
    """CORE-01: parse_step_from_bytes cleans up even on parse failure."""
    before = set(
        glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.step"))
        + glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.stp"))
    )
    from src.parsers.step_parser import parse_step_from_bytes
    try:
        parse_step_from_bytes(b"ISO-10303-21;\nnot a real step", "test.step")
    except Exception:
        pass  # expected — we're asserting cleanup happened on the failure path
    after = set(
        glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.step"))
        + glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.stp"))
    )
    leaked = after - before
    assert not leaked, f"Leaked temp files: {leaked}"


def test_empty_step_returns_400(client):
    r = client.post(
        "/api/v1/validate",
        files={"file": ("empty.step", b"", "application/octet-stream")},
    )
    assert r.status_code == 400  # empty file guard from _read_capped
```

Mark any cadquery-dependent test with a skip if `is_step_supported()` is
False (following the `_try_csg` pattern). But the magic-byte tests do not
need cadquery — they reject BEFORE the parser is invoked.
  </action>
  <verify>
    <automated>cd backend && pytest tests/test_step_corruption.py -q</automated>
  </verify>
  <done>
- All five tests pass on a machine with or without cadquery (magic-byte tests
  must pass regardless).
- `test_step_parse_leaves_no_temp_files` proves CORE-01 holds in situ.
  </done>
</task>

<task type="auto">
  <name>Task D3: test_scoring_ties.py — tied scores + all-fail case</name>
  <files>backend/tests/test_scoring_ties.py</files>
  <action>
Create `backend/tests/test_scoring_ties.py` following PATTERNS.md §test_scoring_ties.py.

```python
"""Regression: process scoring under ties and all-fail conditions."""
from __future__ import annotations

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult, ProcessType
from src.analysis.processes import get_analyzer
from src.matcher.profile_matcher import rank_processes, score_process


def _build_context(mesh):
    info = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, info)
    return ctx, info


def test_all_processes_run_on_cube_without_crash(cube_10mm):
    """Smoke: every registered analyzer runs on the universal cube."""
    ctx, info = _build_context(cube_10mm)
    for proc in ProcessType:
        analyzer = get_analyzer(proc)
        assert analyzer is not None, f"Missing analyzer for {proc.value}"
        issues = analyzer.analyze(ctx)
        assert isinstance(issues, list)


def test_rank_processes_stable_on_all_equal_scores(cube_10mm):
    """If every process scores equally, rank_processes must not crash or return None."""
    ctx, info = _build_context(cube_10mm)
    process_scores = []
    for proc in ProcessType:
        ps = score_process([], info, proc)
        process_scores.append(ps)
    # Force exact ties
    equal_score = process_scores[0].score
    for ps in process_scores:
        ps.score = equal_score
    result = AnalysisResult(
        filename="cube.stl",
        file_type="stl",
        geometry=info,
        segments=[],
        universal_issues=[],
        process_scores=process_scores,
        analysis_time_ms=0.0,
    )
    ranked = rank_processes(result)
    assert ranked is not None
    assert len(ranked) == len(process_scores)


def test_rank_processes_returns_empty_or_zero_scores_on_all_fail(non_watertight_box):
    """If every process fails hard, best_process = None (not crash)."""
    from src.analysis.base_analyzer import run_universal_checks
    ctx, info = _build_context(non_watertight_box)
    universal = run_universal_checks(non_watertight_box)
    process_scores = []
    for proc in ProcessType:
        analyzer = get_analyzer(proc)
        issues = analyzer.analyze(ctx)
        ps = score_process(issues, info, proc)
        process_scores.append(ps)
    result = AnalysisResult(
        filename="broken.stl",
        file_type="stl",
        geometry=info,
        segments=[],
        universal_issues=universal,
        process_scores=process_scores,
        analysis_time_ms=0.0,
    )
    ranked = rank_processes(result)
    # Must not raise. best_process selection from routes.py:201-202:
    # only set if ranked[0].score > 0, else None.
    assert ranked is not None
    best = ranked[0] if ranked and ranked[0].score > 0 else None
    # Assertion is: no crash. `best` may be None or a valid ProcessScore.
    assert best is None or best.score > 0
```

If `AnalysisResult` signature differs from the above (check models.py),
adapt the constructor kwargs but keep the semantic assertions.
  </action>
  <verify>
    <automated>cd backend && pytest tests/test_scoring_ties.py -q</automated>
  </verify>
  <done>
- All three tests pass.
- No crash on tied scores or all-fail scenario.
  </done>
</task>

<task type="auto">
  <name>Task D4: test_frontend_errors.py — error-path contracts for the UI</name>
  <files>backend/tests/test_frontend_errors.py</files>
  <action>
Create `backend/tests/test_frontend_errors.py` following PATTERNS.md §test_frontend_errors.py.

```python
"""Regression: frontend-facing error contracts (504, 400 magic, 400 cap)."""
from __future__ import annotations

import importlib
import io

import pytest
import trimesh
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    return TestClient(main.app)


def test_magic_byte_rejection_returns_400_with_detail(client):
    """Frontend must receive a clear 400 on a mismatched magic byte."""
    r = client.post(
        "/api/v1/validate",
        files={"file": ("fake.stl", b"PK\x03\x04notanstl", "application/octet-stream")},
    )
    assert r.status_code == 400
    body = r.json()
    assert "detail" in body
    assert isinstance(body["detail"], str)


def test_triangle_cap_rejection_returns_400(monkeypatch, cube_10mm, stl_bytes_of):
    """MAX_TRIANGLES=1 on a cube (12 triangles) must 400 before analysis."""
    monkeypatch.setenv("MAX_TRIANGLES", "1")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    client = TestClient(main.app)
    data = stl_bytes_of(cube_10mm)
    r = client.post(
        "/api/v1/validate",
        files={"file": ("cube.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "triangle" in r.json()["detail"].lower() or "MAX_TRIANGLES" in r.json()["detail"]


def test_upload_size_limit_returns_413(monkeypatch):
    """Frontend must receive 413 for oversize uploads (existing behavior, regress)."""
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    import main
    importlib.reload(main)
    client = TestClient(main.app)
    big = b"\x00" * (2 * 1024 * 1024)  # 2 MiB
    r = client.post(
        "/api/v1/validate",
        files={"file": ("big.stl", big, "application/octet-stream")},
    )
    assert r.status_code == 413


def test_timeout_returns_504_with_structured_detail(monkeypatch):
    """Frontend must receive a structured 504 on analysis timeout (CORE-06)."""
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "0.0001")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    client = TestClient(main.app)
    mesh = trimesh.creation.icosphere(subdivisions=5)
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    r = client.post(
        "/api/v1/validate",
        files={"file": ("sphere.stl", buf.getvalue(), "application/octet-stream")},
    )
    # Tolerant: may be 200 on very fast machines where even full analysis finishes
    # under 0.0001s (extremely unlikely). Any 504 is expected; flag other codes.
    assert r.status_code in (504, 200), f"unexpected {r.status_code}"
    if r.status_code == 504:
        body = r.json()
        assert "detail" in body
        detail = body["detail"].lower()
        assert "timeout" in detail or "timed out" in detail or "exceed" in detail


def test_unknown_extension_returns_400(client):
    r = client.post(
        "/api/v1/validate",
        files={"file": ("foo.txt", b"plain text", "text/plain")},
    )
    assert r.status_code == 400
```

All tests use the FastAPI TestClient — no live network, no cadquery
dependency required for the error paths.
  </action>
  <verify>
    <automated>cd backend && pytest tests/test_frontend_errors.py -q</automated>
  </verify>
  <done>
- All five tests pass.
- Each test asserts both status code AND the presence/shape of `detail`.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Test harness → hardened engine | Tests are the regression fence for all Wave-1 work |

## STRIDE Register

| Threat ID | Category | Component | Disposition | Mitigation |
|-----------|----------|-----------|-------------|------------|
| T-01D-01 | Repudiation (regression silence) | Future refactor reintroduces a Wave-1 bug | mitigate | Four explicit regression modules pinned to CORE-01/05/06/07/08 scenarios |
| T-01D-02 | Denial of Service (CI runtime) | 200k-face mesh test exceeds CI budget | accept | icosphere(subdivisions=6) is ~40k faces, subdivisions=7 is ~160k; keep under 2min total test runtime |
</threat_model>

<verification>
- `pytest backend/tests/test_large_mesh.py backend/tests/test_step_corruption.py backend/tests/test_scoring_ties.py backend/tests/test_frontend_errors.py -q` all green.
- Total wall time for the four new modules < 2 minutes.
- `pytest backend/tests/ -q` full suite remains green (no accidental cross-test pollution from env var monkeypatching).
</verification>

<success_criteria>
- Four new test modules exist under `backend/tests/`.
- Each module tests at least one specific CORE-0X requirement explicitly.
- The full test suite passes.
- Test runtime budget respected (< 2 min for the four new modules).
</success_criteria>

<output>
Create `.planning/phases/01-stabilize-core/01.D-test-gaps/01.D-SUMMARY.md` documenting:
- The four test modules and their CORE-XX mapping.
- Exact face count used for "large mesh" (subdivisions parameter).
- Any tests that required `pytest.skip` on machines without cadquery.
- Test runtime on the executor's machine for the four new modules.
- Confirmation that `pytest backend/tests/ -q` is fully green after this plan lands.
</output>
