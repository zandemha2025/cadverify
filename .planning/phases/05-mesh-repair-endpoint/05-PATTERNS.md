# Phase 5: Mesh Repair Endpoint - Pattern Map

**Generated:** 2026-04-15
**Source:** 05-CONTEXT.md, 05-RESEARCH.md

---

## Files to Create/Modify

### NEW: `backend/src/services/repair_service.py`

**Role:** Repair orchestration service (Tier 1 trimesh + Tier 2 pymeshfix)
**Closest analog:** `backend/src/services/analysis_service.py`
**Data flow:** Receives raw file bytes -> parses mesh -> attempts repair -> calls `analysis_service.run_analysis()` for re-analysis -> returns combined result

**Pattern excerpts from analog:**

```python
# analysis_service.py — async timeout pattern (lines 276-293)
timeout_sec = analysis_timeout_sec_fn()
loop = asyncio.get_event_loop()
try:
    result = await asyncio.wait_for(
        loop.run_in_executor(None, _run_analysis_sync),
        timeout=timeout_sec,
    )
except asyncio.TimeoutError:
    raise HTTPException(status_code=504, detail="...")

# analysis_service.py — env var config pattern (lines 40-42)
def compute_mesh_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()
```

**Adaptation:** Repair service uses same `asyncio.wait_for()` + `run_in_executor` pattern but with `REPAIR_TIMEOUT_SEC` (default 30). On timeout, returns original analysis with `repair_applied: false` (NOT 504).

---

### MODIFIED: `backend/src/api/routes.py`

**Role:** Add `POST /api/v1/validate/repair` route handler
**Closest analog:** `validate_file` endpoint at line 133

**Pattern excerpts:**

```python
# routes.py — endpoint pattern (lines 133-168)
@router.post("/validate", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def validate_file(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    processes: Optional[str] = Query(None, ...),
    rule_pack: Optional[str] = Query(None, ...),
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    data = await _read_capped(file)
    return await analysis_service.run_analysis(...)
```

**Adaptation:** New repair endpoint follows identical signature pattern. Reuses `_read_capped`, adds face-count check before calling `repair_service.repair_mesh()`.

---

### MODIFIED: `backend/requirements.txt`

**Role:** Add `pymeshfix>=0.18` dependency
**Closest analog:** Existing entries in requirements.txt

---

### MODIFIED: `frontend/src/lib/api.ts`

**Role:** Add `repairAnalysis()` function + `RepairResult` interface
**Closest analog:** `validateFile()` function at line 108 and `downloadPdf()` at line 323

**Pattern excerpts:**

```typescript
// api.ts — POST with file upload (lines 108-136)
export async function validateFile(
  file: File,
  processes?: string[],
  rulePack?: string
): Promise<ValidationResult> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(url, { method: "POST", body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Validation failed");
  }
  return res.json();
}

// api.ts — auth headers pattern (lines 223-227)
function authHeaders(): Record<string, string> {
  const key = localStorage.getItem("cadverify_api_key");
  return key ? { Authorization: `Bearer ${key}` } : {};
}
```

**Adaptation:** `repairAnalysis()` follows same FormData + fetch pattern. Returns `RepairResult` interface (extends with `repair_applied`, `repair_details`, `repaired_analysis`, `repaired_file_b64`). Needs auth headers since repair endpoint is authenticated.

---

### MODIFIED: `frontend/src/app/(dashboard)/analyses/[id]/page.tsx`

**Role:** Add conditional "Attempt repair" button
**Closest analog:** Existing `ShareButton` and `PdfDownloadButton` integration at lines 79-84

**Pattern excerpts:**

```tsx
// page.tsx — action buttons area (lines 78-85)
<div className="mt-2 flex items-center gap-2">
  <ShareButton
    analysisId={id}
    initialShared={analysis.is_public}
    initialShareUrl={analysis.share_url}
  />
  <PdfDownloadButton analysisId={id} filename={analysis.filename} />
</div>
```

**Adaptation:** Add `RepairButton` component in the same flex container, conditionally rendered based on universal_issues codes.

---

### NEW: `frontend/src/components/RepairButton.tsx`

**Role:** "Attempt Mesh Repair" button with loading state
**Closest analog:** `frontend/src/components/PdfDownloadButton.tsx`

**Pattern:** PdfDownloadButton follows loading state -> fetch -> success/error pattern. RepairButton does the same but needs to accept a File object (for re-upload) or use the analysis data to construct the repair request.

---

### NEW: `frontend/src/components/RepairComparison.tsx`

**Role:** Before/after comparison layout with two AnalysisDashboard instances
**Closest analog:** `frontend/src/components/AnalysisDashboard.tsx` (reused as child)

**Pattern:** Wraps two `<AnalysisDashboard>` in a side-by-side layout with "Original" and "Repaired" labels plus a download button.

---

### NEW: `backend/tests/test_repair_service.py`

**Role:** Unit tests for repair service
**Closest analog:** Existing test files in `backend/tests/`

---

### NEW: `backend/tests/test_repair_endpoint.py`

**Role:** Integration tests for repair endpoint
**Closest analog:** Existing test patterns in `backend/tests/`

---

## PATTERN MAPPING COMPLETE
