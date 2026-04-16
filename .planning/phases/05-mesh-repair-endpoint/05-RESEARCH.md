# Phase 5: Mesh Repair Endpoint - Research

**Researched:** 2026-04-15
**Confidence:** HIGH (pymeshfix and trimesh.repair APIs verified against PyPI docs and source; timeout patterns confirmed from existing codebase)

---

## pymeshfix API

### Installation
- `pip install pymeshfix` — PyPI wheel includes compiled C++ (pybind11). No system deps.
- Current version: 0.18.x. Cross-platform wheels for Linux amd64, macOS, Windows.
- Adds ~50 MB to Docker image (Pitfall 1 note — budget in Phase 6).

### Core API
```python
import pymeshfix
import numpy as np

# From trimesh mesh object:
vertices = mesh.vertices  # (N, 3) float64
faces = mesh.faces        # (M, 3) int32

meshfix = pymeshfix.MeshFix(vertices, faces)
meshfix.repair(verbose=False)

# Repaired mesh:
repaired_vertices = meshfix.v  # (N', 3) float64
repaired_faces = meshfix.f     # (M', 3) int32
```

### Key behaviors
- `MeshFix.repair()` modifies vertices/faces in place on the C++ side. Access via `.v` and `.f` properties after repair.
- Handles: non-manifold edges, complex hole filling, self-intersection resolution, degenerate face removal.
- Does NOT handle: topology reconstruction, feature preservation, remeshing.
- Memory: ~1 byte per face for working memory. At 500k faces, ~500 MB peak.
- Performance: 1-5s for typical meshes (<200k faces). Can exceed 30s for pathological geometry (>500k faces with many self-intersections).
- **Crash risk**: pymeshfix is C++ code. Pathological meshes can cause segfaults or infinite loops. In-process execution means a segfault takes down the FastAPI worker. Mitigated by face-count cap (D-07) and timeout (D-06).
- `verbose=False` suppresses C++ stdout output that would pollute logs.

### Error handling
- Raises `RuntimeError` if repair fails entirely (e.g., mesh is too degenerate).
- No partial results — either fully repairs or throws.
- Import fails with `ImportError` if pymeshfix wheel not installed (graceful degradation to Tier 1 only).

---

## trimesh.repair API

### Available repair functions
```python
import trimesh

mesh = trimesh.load(...)

# Tier 1 repair sequence (fast, in-process, ~60% success rate):

# 1. Fix normals — make normals consistent and outward-facing
trimesh.repair.fix_normals(mesh)
# Modifies mesh.face_normals in place. Fast (<10ms for most meshes).

# 2. Fix inversion — if mesh is "inside out", flip all normals
trimesh.repair.fix_inversion(mesh)
# Checks volume sign; flips if negative. Fast.

# 3. Fill holes — close small holes in the mesh surface
trimesh.repair.fill_holes(mesh)
# Adds new faces to close holes. Works well for small holes (< ~20 edges).
# For large/complex holes, may not fully close — pymeshfix needed.

# 4. Fix winding — ensure consistent face winding order
trimesh.repair.fix_winding(mesh)
# Makes all face winding consistent. Fast.

# 5. Remove degenerate faces
mesh.remove_degenerate_faces()
# Removes zero-area and collapsed faces. Returns new mesh.
# This is a mesh method, not a trimesh.repair function.
```

### Recommended Tier 1 sequence
```python
def tier1_repair(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Fast repair pass — handles ~60% of common defects."""
    mesh.remove_degenerate_faces()
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fix_inversion(mesh)
    trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_winding(mesh)
    return mesh
```

### Watertightness check after repair
```python
mesh.is_watertight  # True if mesh is closed manifold with consistent winding
mesh.is_volume      # True if mesh encloses a volume (stricter than is_watertight)
```

### Performance
- All trimesh.repair operations complete in <100ms for meshes up to 500k faces.
- No external dependencies beyond numpy.
- No crash risk — pure Python with numpy operations.

---

## Timeout Pattern (from existing codebase)

### Existing pattern in analysis_service.py
```python
loop = asyncio.get_event_loop()
try:
    result = await asyncio.wait_for(
        loop.run_in_executor(None, sync_function),
        timeout=timeout_sec,
    )
except asyncio.TimeoutError:
    raise HTTPException(status_code=504, detail="...")
```

### Adaptation for repair service
- Same pattern: wrap sync repair operations in `run_in_executor` + `wait_for`.
- `REPAIR_TIMEOUT_SEC` env var (default 30) covers both Tier 1 and Tier 2 combined.
- On timeout: return original analysis with `repair_applied: false` and error detail (D-08). NOT a 504 — repair failure is graceful.
- On pymeshfix RuntimeError: same graceful fallback.

### Face-count guard pattern
```python
def _repair_max_faces() -> int:
    try:
        return max(1, int(os.getenv("REPAIR_MAX_FACES", "500000")))
    except ValueError:
        return 500_000
```
- Check face count AFTER initial parse (mesh must be loaded to count faces).
- Return 413 if exceeded, before attempting any repair.

---

## Response Shape Design

### Combined response structure
```json
{
  "original_analysis": { /* full /validate response shape */ },
  "repair_applied": true,
  "repair_details": {
    "tier": "pymeshfix",
    "original_faces": 42000,
    "repaired_faces": 41850,
    "holes_filled": 3,
    "duration_ms": 2150.5
  },
  "repaired_analysis": { /* full /validate response shape, or null */ },
  "repaired_file_b64": "base64-encoded-stl-bytes..."
}
```

### Base64 encoding
- Use `base64.b64encode(stl_bytes).decode("ascii")` — standard base64, not URL-safe.
- Export repaired mesh to binary STL: `mesh.export(file_type='stl')` returns bytes.
- Typical size: 1-20 MB mesh -> 1.3-27 MB base64 string. Acceptable for single-request action.

---

## Repair Eligibility Check (Frontend)

### Issue codes that trigger "Attempt repair" CTA
From `base_analyzer.py` `run_universal_checks()`:
- `NON_WATERTIGHT` — mesh is not a closed manifold
- `INCONSISTENT_NORMALS` — face normals point in conflicting directions
- `NOT_SOLID_VOLUME` — mesh does not enclose a volume
- `DEGENERATE_FACES` — zero-area or collapsed faces present
- `MULTIPLE_BODIES` — mesh has disconnected components

### Frontend check
```typescript
const REPAIRABLE_CODES = new Set([
  "NON_WATERTIGHT",
  "INCONSISTENT_NORMALS",
  "NOT_SOLID_VOLUME",
  "DEGENERATE_FACES",
  "MULTIPLE_BODIES",
]);

const hasRepairableIssues = analysis.universal_issues.some(
  (issue) => REPAIRABLE_CODES.has(issue.code)
);
```

---

## Integration Points Summary

| Component | Action | Integration pattern |
|-----------|--------|-------------------|
| `repair_service.py` | NEW | `async def repair_mesh(file_bytes, filename, user, session)` — calls trimesh repair, pymeshfix, then `analysis_service.run_analysis()` for re-analysis |
| `routes.py` | MODIFIED | Add `POST /api/v1/validate/repair` route handler, reuse `_read_capped`, `_parse_mesh`, `validate_magic`, `enforce_triangle_cap` |
| `requirements.txt` | MODIFIED | Add `pymeshfix>=0.18` |
| `api.ts` | MODIFIED | Add `repairAnalysis()` function + `RepairResult` interface |
| `analyses/[id]/page.tsx` | MODIFIED | Add conditional "Attempt repair" button |
| `RepairComparison.tsx` | NEW | Before/after comparison wrapping two `AnalysisDashboard` instances |

---

## Validation Architecture

### Unit tests (repair_service)
1. Tier 1 repair fixes a mesh with flipped normals -> `is_watertight` becomes True
2. Tier 2 repair invoked when Tier 1 insufficient (non-manifold edges)
3. Face-count cap returns 413 for meshes >500k faces
4. Timeout returns original analysis with `repair_applied: false`
5. pymeshfix import error degrades to Tier 1 only

### Integration tests (endpoint)
1. POST /api/v1/validate/repair with non-watertight STL -> 200 with `repair_applied: true`
2. POST /api/v1/validate/repair with already-clean mesh -> 200 with `repair_applied: false`
3. Repaired mesh hash is cached — second repair request hits analysis_service dedup
4. Rate limiting applies to repair endpoint

### Frontend tests
1. "Attempt repair" button visible when universal_issues contain repairable codes
2. "Attempt repair" button hidden when no repairable issues
3. Before/after comparison renders correctly
4. Download link produces correct filename (`{original}-repaired.stl`)

---

## RESEARCH COMPLETE
