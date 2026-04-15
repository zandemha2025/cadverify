---
phase: 01-stabilize-core
plan: 01.A
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/src/parsers/step_parser.py
  - backend/src/api/upload_validation.py      # NEW
  - backend/src/api/routes.py                 # shared — edit _parse_mesh only
  - backend/tests/test_step_parser.py         # extend (existing)
autonomous: true
requirements: [CORE-01, CORE-07]
must_haves:
  truths:
    - "Uploading 100 malformed STEP files leaves /tmp clean"
    - "A .stl file whose first bytes are not STL-shaped returns 400 before parse"
    - "A .step file missing ISO-10303-21 magic returns 400 before parse"
    - "A file whose triangle count exceeds MAX_TRIANGLES returns 400 before mesh build"
    - "STEP temp files are created with mode 0o600 (owner read/write only)"
  artifacts:
    - path: backend/src/parsers/step_parser.py
      provides: "Context-managed temp file with os.chmod(0o600) and guaranteed unlink"
      contains: "os.unlink(tmp.name)"
    - path: backend/src/api/upload_validation.py
      provides: "validate_magic() and enforce_triangle_cap() callables"
      exports: ["validate_magic", "enforce_triangle_cap", "_max_triangles"]
    - path: backend/src/api/routes.py
      provides: "_parse_mesh calls validate_magic before parser dispatch"
      contains: "validate_magic"
  key_links:
    - from: backend/src/api/routes.py::_parse_mesh
      to: backend/src/api/upload_validation.py::validate_magic
      via: "direct import + call before parser dispatch"
      pattern: "validate_magic\\(data, suffix\\)"
    - from: backend/src/parsers/step_parser.py::parse_step_from_bytes
      to: tempfile.NamedTemporaryFile + os.unlink
      via: "try/finally block"
      pattern: "finally:\\s*tmp.close\\(\\)\\s*os.unlink"
---

<objective>
Close the STEP temp-file leak (CORE-01) and add pre-parse defense-in-depth
(CORE-07) so that the /validate endpoint cannot be weaponized via file-system
exhaustion, pathological uploads, or MIME-mismatched payloads.

Purpose: Phase 2 exposes this endpoint publicly. Every temp-file leak becomes a
disk-fill DoS; every bypass of the triangle cap becomes a memory-exhaustion
DoS. Both must ship before auth opens the gate.

Output:
- `backend/src/parsers/step_parser.py` with try/finally + `os.chmod(0o600)` +
  guaranteed `os.unlink` on both success and failure paths.
- `backend/src/api/upload_validation.py` (new) exporting `validate_magic()` +
  `enforce_triangle_cap()`.
- `backend/src/api/routes.py::_parse_mesh` calling both helpers before the
  existing parser dispatch.
- Extended `backend/tests/test_step_parser.py` covering cleanup and magic.
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
@backend/src/parsers/step_parser.py
@backend/src/parsers/stl_parser.py
@backend/src/api/routes.py

<interfaces>
<!-- Extracted contracts executors need. No codebase exploration required. -->

From backend/src/parsers/step_parser.py (current — to be replaced):
```python
def is_step_supported() -> bool: ...
def parse_step(file_path: str | Path, linear_deflection: float = 0.1) -> trimesh.Trimesh: ...
def parse_step_from_bytes(data: bytes, filename: str = "upload.step",
                          linear_deflection: float = 0.1) -> trimesh.Trimesh: ...
```
The PUBLIC SIGNATURES above MUST NOT change — they are imported by
`routes.py` (`from src.parsers.step_parser import is_step_supported,
parse_step_from_bytes`). Only the internal temp-file handling changes.

From backend/src/api/routes.py (current, lines 56–62) — env-reader pattern:
```python
def _max_upload_bytes() -> int:
    try:
        mb = int(os.getenv("MAX_UPLOAD_MB", "100"))
    except ValueError:
        mb = 100
    return max(1, mb) * 1024 * 1024
```
Clone this shape for `_max_triangles()` in `upload_validation.py`.

From backend/src/api/routes.py (current, _parse_mesh signature):
```python
def _parse_mesh(data: bytes, filename: str) -> tuple[trimesh.Trimesh, str]: ...
```
Call site: `mesh, suffix = _parse_mesh(data, filename)` (line 155). Do NOT
change this contract.

New module contract (`backend/src/api/upload_validation.py`):
```python
_STEP_MAGIC: bytes = b"ISO-10303-21"
def validate_magic(data: bytes, suffix: str) -> None: ...          # raises HTTPException(400)
def enforce_triangle_cap(mesh) -> None: ...                        # raises HTTPException(400)
def _max_triangles() -> int: ...                                   # lazy env read
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task A1: Harden step_parser.py temp-file handling (CORE-01)</name>
  <files>backend/src/parsers/step_parser.py</files>
  <action>
Rewrite `parse_step_from_bytes` (currently at lines 90–105) to use try/finally
with guaranteed cleanup. Follow the pattern in PATTERNS.md §step_parser.py.

Specifically:
1. Add `import os` at module top if absent (keep other imports unchanged).
2. Replace the `with tempfile.NamedTemporaryFile(...)` block with:
   ```python
   tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w+b")
   try:
       os.chmod(tmp.name, 0o600)   # owner R/W only — CONCERNS.md security note
       tmp.write(data)
       tmp.flush()
       tmp.close()                  # close FD before cadquery re-opens by path
       return parse_step(tmp.name, linear_deflection)
   finally:
       # guaranteed cleanup even if parse_step raises
       try:
           os.unlink(tmp.name)
       except FileNotFoundError:
           pass
   ```
3. Do NOT change `parse_step()` or `is_step_supported()` — only
   `parse_step_from_bytes`.
4. Do NOT rename, reorder, or retype any public function.
  </action>
  <verify>
    <automated>cd backend &amp;&amp; pytest tests/test_step_parser.py -q</automated>
  </verify>
  <done>
- `parse_step_from_bytes` uses try/finally + os.chmod + os.unlink.
- File still importable; `is_step_supported()` unchanged.
- Existing test_step_parser.py passes (no behavior regression on happy path).
  </done>
</task>

<task type="auto">
  <name>Task A2: Create upload_validation.py with magic-byte + triangle-cap helpers (CORE-07)</name>
  <files>backend/src/api/upload_validation.py</files>
  <action>
Create a NEW file `backend/src/api/upload_validation.py` following PATTERNS.md
§upload_validation.py. Module must export exactly:

- `_STEP_MAGIC: bytes = b"ISO-10303-21"`
- `_max_triangles() -> int` — lazy env reader for `MAX_TRIANGLES` (default
  `2000000`). Clone `_max_upload_bytes()` style from routes.py:56–62.
- `validate_magic(data: bytes, suffix: str) -> None` — raises
  HTTPException(400) if the first bytes don't match the declared suffix.
  Rules:
    * `.step` or `.stp` → first 12 bytes MUST equal `_STEP_MAGIC`.
    * `.stl` → `len(data) >= 84` (80-byte header + 4-byte uint triangle
      count) AND if bytes[0:5] lowercases to `solid` it is accepted as ASCII
      STL; otherwise it is treated as binary STL and passes the length check.
    * Any other suffix: do nothing (routes.py already rejects unknown
      suffixes with 400).
  Error detail strings must be human-readable and MUST NOT echo file content
  back to the caller.
- `enforce_triangle_cap(mesh) -> None` — raises HTTPException(400) if
  `len(mesh.faces) > _max_triangles()`. Message format:
    f"Mesh has {len(mesh.faces):,} triangles, exceeds MAX_TRIANGLES limit "
    f"of {_max_triangles():,}. Reduce mesh resolution or contact support."

Imports (PEP 8 order):
```python
"""Pre-parse upload validation: magic bytes and triangle-count cap."""
from __future__ import annotations
import logging
import os
from fastapi import HTTPException

logger = logging.getLogger("cadverify.upload_validation")
```
  </action>
  <verify>
    <automated>cd backend &amp;&amp; python -c "from src.api.upload_validation import validate_magic, enforce_triangle_cap, _max_triangles, _STEP_MAGIC; print('ok')"</automated>
  </verify>
  <done>
- File exists; `from src.api.upload_validation import validate_magic,
  enforce_triangle_cap, _max_triangles` succeeds.
- validate_magic raises HTTPException(400) on a JPEG renamed to .step (tested
  in A4).
- enforce_triangle_cap raises HTTPException(400) when len(mesh.faces) >
  MAX_TRIANGLES.
  </done>
</task>

<task type="auto">
  <name>Task A3: Wire upload_validation into routes.py::_parse_mesh (CORE-07)</name>
  <files>backend/src/api/routes.py</files>
  <action>
Modify `backend/src/api/routes.py::_parse_mesh` (currently lines 84–107).

1. Add near existing imports (after line 27, alphabetical within `src.api`):
   ```python
   from src.api.upload_validation import enforce_triangle_cap, validate_magic
   ```
2. Inside `_parse_mesh`, immediately after the suffix check at line 86–90 and
   BEFORE the `try:` block at line 91, add:
   ```python
   # CORE-07: defense-in-depth — verify magic bytes before dispatching
   # to parser libs (cadquery/trimesh can crash on adversarial input).
   validate_magic(data, suffix)
   ```
3. After a successful parse but BEFORE returning, enforce the triangle cap.
   Rewrite the return statements (currently lines 93 and 99) so the cap check
   runs on the produced mesh:
   ```python
   if suffix == ".stl":
       mesh = parse_stl_from_bytes(data, filename)
       enforce_triangle_cap(mesh)
       return mesh, suffix
   if not is_step_supported():
       raise HTTPException(
           status_code=501,
           detail="STEP parsing requires cadquery. Install with: pip install cadquery",
       )
   mesh = parse_step_from_bytes(data, filename)
   enforce_triangle_cap(mesh)
   return mesh, suffix
   ```
4. Leave the surrounding `try/except HTTPException/except ValueError/except
   Exception` block intact — the HTTPException raised by enforce_triangle_cap
   and validate_magic will propagate via the existing `except HTTPException:
   raise` clause.

**Merge discipline:** This plan touches routes.py region 84–107. Plans 01.B
(lines 38–47 and 175–183) and 01.C (lines 56–62, 165–189) edit disjoint
regions. If Plan 01.B has already landed, rebase before committing.
  </action>
  <verify>
    <automated>cd backend &amp;&amp; python -c "import main; from fastapi.testclient import TestClient; c = TestClient(main.app); r = c.post('/api/v1/validate', files={'file': ('bad.step', b'not a step', 'application/octet-stream')}); assert r.status_code == 400, r.status_code; print('ok')"</automated>
  </verify>
  <done>
- `_parse_mesh` calls `validate_magic(data, suffix)` before any parser.
- `enforce_triangle_cap(mesh)` runs after successful parse on both STL and
  STEP branches.
- JPEG-renamed-to-.step returns 400 with a magic-byte detail message.
- Existing test_api.py passes unchanged.
  </done>
</task>

<task type="auto">
  <name>Task A4: Extend test_step_parser.py with cleanup + magic-byte tests</name>
  <files>backend/tests/test_step_parser.py</files>
  <action>
Extend the existing test_step_parser.py (if it doesn't exist yet, create it
following PATTERNS.md §test_step_corruption.py module header pattern). Add the
following test functions. Do NOT remove existing tests.

```python
def test_step_parse_leaves_no_temp_files(tmp_path, monkeypatch):
    """parse_step_from_bytes must unlink its temp file even on parse failure."""
    import glob, os, tempfile
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.step"))) \
           | set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.stp")))
    from src.parsers.step_parser import parse_step_from_bytes
    try:
        parse_step_from_bytes(b"not a real step file", "test.step")
    except Exception:
        pass  # parse failure is expected; we're asserting cleanup
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.step"))) \
          | set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.stp")))
    assert after == before, f"Leaked temp files: {after - before}"


def test_step_temp_file_mode_is_0o600(monkeypatch):
    """Temp file created by parse_step_from_bytes must be owner-only (0o600)."""
    # Patch parse_step to capture the path before cleanup.
    import os
    import src.parsers.step_parser as sp

    captured = {}
    def fake_parse_step(path, linear_deflection=0.1):
        captured["mode"] = os.stat(path).st_mode & 0o777
        raise ValueError("stop here")  # force finally block to run
    monkeypatch.setattr(sp, "parse_step", fake_parse_step)
    try:
        sp.parse_step_from_bytes(b"ISO-10303-21;\nDUMMY;\n", "test.step")
    except ValueError:
        pass
    assert captured.get("mode") == 0o600, f"mode was {oct(captured.get('mode', 0))}"
```

Also add tests for the new magic-byte helper in a new file
`backend/tests/test_upload_validation.py`:

```python
"""Tests for pre-parse upload validation."""
from __future__ import annotations
import pytest
from fastapi import HTTPException
from src.api.upload_validation import validate_magic, enforce_triangle_cap

def test_validate_magic_accepts_valid_step():
    validate_magic(b"ISO-10303-21;\nHEADER;", ".step")  # no raise

def test_validate_magic_rejects_jpeg_as_step():
    with pytest.raises(HTTPException) as exc:
        validate_magic(b"\xff\xd8\xff\xe0JFIF", ".step")
    assert exc.value.status_code == 400

def test_validate_magic_rejects_short_stl():
    with pytest.raises(HTTPException) as exc:
        validate_magic(b"short", ".stl")
    assert exc.value.status_code == 400

def test_validate_magic_accepts_binary_stl_header():
    # 84 bytes of zeros → valid binary STL structure (0 triangles, still parses)
    validate_magic(b"\x00" * 84, ".stl")

def test_enforce_triangle_cap_raises_when_exceeded(monkeypatch):
    monkeypatch.setenv("MAX_TRIANGLES", "10")
    import trimesh
    mesh = trimesh.creation.icosphere(subdivisions=3)  # >> 10 faces
    with pytest.raises(HTTPException) as exc:
        enforce_triangle_cap(mesh)
    assert exc.value.status_code == 400
```
  </action>
  <verify>
    <automated>cd backend &amp;&amp; pytest tests/test_step_parser.py tests/test_upload_validation.py -q</automated>
  </verify>
  <done>
- All four cleanup/magic tests pass.
- `test_step_temp_file_mode_is_0o600` confirms 0o600 on the created file.
- No residual tmp*.step files after the leak-check test.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| HTTP client → `/validate` | Untrusted uploads (any bytes, any extension) cross here |
| `_parse_mesh` → cadquery/trimesh native libs | C++ parsers can segfault / hang / OOM on adversarial input |
| `parse_step_from_bytes` → host filesystem (`/tmp`) | Persistent artifact created per request |

## STRIDE Register

| Threat ID | Category | Component | Disposition | Mitigation |
|-----------|----------|-----------|-------------|------------|
| T-01A-01 | Denial of Service | STEP temp file accumulation | mitigate | Try/finally with os.unlink; regression test confirms /tmp stable |
| T-01A-02 | Information Disclosure | Temp file world-readable | mitigate | os.chmod(tmp.name, 0o600) before write |
| T-01A-03 | Denial of Service | Pathological STL/STEP crashes parser | mitigate | validate_magic(data, suffix) before parser dispatch |
| T-01A-04 | Denial of Service | Oversize mesh exhausts RAM | mitigate | enforce_triangle_cap after parse (pre-analysis); MAX_TRIANGLES env |
| T-01A-05 | Tampering | Magic-byte bypass (prepend ISO-10303-21 to payload) | accept | Magic is defense-in-depth, not AuthN. cadquery/trimesh remain the real parse line; cap + timeout (Plan 01.C) bound blast radius. |
| T-01A-06 | Information Disclosure | HTTPException detail echoes user payload | mitigate | Detail strings are static; content never reflected back to client |
</threat_model>

<verification>
**Success criteria mapped to verifications:**

1. **/tmp stable after 100 bad uploads (CORE-01):**
   `for i in $(seq 1 100); do curl -s -X POST -F "file=@/tmp/bad.step" http://localhost:8000/api/v1/validate > /dev/null; done; ls /tmp/tmp*.step 2>/dev/null | wc -l` → 0.
2. **mode=0o600 on temp (CORE-01 sec note):** `test_step_temp_file_mode_is_0o600`.
3. **Magic-byte rejection (CORE-07):** `test_validate_magic_rejects_jpeg_as_step`.
4. **Triangle cap (CORE-07):** `test_enforce_triangle_cap_raises_when_exceeded`.
5. **Happy path unchanged:** full `pytest tests/` still green.
</verification>

<success_criteria>
- `grep -n "os.unlink" backend/src/parsers/step_parser.py` returns a match inside a `finally:` block.
- `grep -n "os.chmod" backend/src/parsers/step_parser.py` returns a match with `0o600`.
- `backend/src/api/upload_validation.py` exists and exports the four required names.
- `_parse_mesh` in routes.py contains a call to `validate_magic(data, suffix)`.
- `pytest backend/tests/test_step_parser.py backend/tests/test_upload_validation.py backend/tests/test_api.py -q` passes.
- No /tmp leak after the new leak regression test.
</success_criteria>

<output>
Create `.planning/phases/01-stabilize-core/01.A-step-upload-hardening/01.A-SUMMARY.md`
documenting:
- Files changed (routes.py, step_parser.py) + files created (upload_validation.py,
  test_upload_validation.py).
- The 4 commits this plan produced (one per task).
- Any deviations from PATTERNS.md and why.
- Confirmed sha of the `_STEP_MAGIC` check, the 0o600 chmod call, and the
  validate_magic import in routes.py.
</output>
